# Phase 29 - Runner Architecture Boundary Cleanup

## Goal

把已经写出来的 LangGraphRunner 接到 MainlineExecutor 主链路的正确位置，
清理 native / langgraph / mainline / multi_worker 四者之间的边界混乱。

这不是新功能。所有代码已经存在。改的是接线。

```
当前（混乱）:

  CLI ask
    → _resolve_execution_path()
      → controlled   → ("mainline", "fake")    ← 跟 orchestrated 一样！
      → orchestrated → ("mainline", "fake")    ← 没用到 LangGraph
    → MainlineExecutor.execute()
      → _execute_multi_worker() → MultiWorkerExecutor(ThreadPoolExecutor)

  Scheduler.run_orchestrated() → LangGraphRunner   ← 挂在旧 Scheduler 下

目标（清晰）:

  CLI ask
    → _resolve_execution_path()
      → controlled   → ("mainline", "native")
      → orchestrated → ("mainline", "langgraph")
        → langgraph 不可用时 → ("blocked", None) + 明确提示缺少依赖
        → --force-run → ("mainline", "native") 回退
    → MainlineExecutor.execute(execution_backend="native"|"langgraph")
      → native:    MultiWorkerExecutor (ThreadPoolExecutor)
      → langgraph: LangGraphRunner.run(plan, control_plane, ...)

  Scheduler.run_orchestrated() → 保留为 legacy compatibility，标记 deprecated
```

## Hard Rules

- MainlineExecutor 是唯一的新主链路入口，不要新增第二条主链路
- LangGraphRunner 和 native backend 是平级关系，不是 Scheduler 的子功能
- LangGraphRunner 不能绕过 ControlPlane — 每个 step 仍然走 worker dispatch → evidence → ControlPlane 检查
- 不要在 LangGraphRunner 里复制一套新的 worker 逻辑
- 如果 langgraph 未安装，orchestrated 必须明确报 dependency missing，不能静默走 fake/native
- 不重写 Scheduler，不删除 Scheduler

## Preflight

Read:

```
CLAUDE.md
.claude/phase-specs/phase-15-langgraph-runner.md
.claude/phase-specs/phase-20-multi-worker-plan-execution.md
src/orchestrator/__main__.py               # _resolve_execution_path, _handle_ask_command
src/orchestrator/mainline_executor.py      # execute(), _execute_multi_worker()
src/orchestrator/runners/langgraph_runner.py  # LangGraphRunner.run()
src/orchestrator/multi_worker.py           # MultiWorkerExecutor
src/orchestrator/scheduler.py              # run_orchestrated() — legacy
src/orchestrator/task_router.py            # requires_future_runner(), _langgraph_available()
tests/
```

Run:

```bash
git status --short
python -m pytest tests/ -q
```

## Changes Required

### 1. CLI 路由 (`__main__.py`)

修改 `_resolve_execution_path()`:

```python
def _resolve_execution_path(
    decision,
    explicit_worker_mode: str | None = None,
    force_run: bool = False,
) -> tuple[str, str | None, str | None]:
    """Returns (path, effective_worker_mode, execution_backend).

    path: "mainline" | "legacy" | "blocked" | "noop"
    effective_worker_mode: "fake" | "packet" | "claude-code" | None
    execution_backend: "native" | "langgraph" | None
    """
    # Explicit --worker-mode always wins → mainline + native
    if explicit_worker_mode is not None:
        return ("mainline", explicit_worker_mode, "native")

    # Router says off/log → no execution
    if should_only_log(decision) and not force_run:
        return ("noop", None, None)

    # controlled → mainline + native backend
    if decision.run_mode == "controlled":
        return ("mainline", "fake", "native")

    # orchestrated → mainline + langgraph backend
    if decision.run_mode == "orchestrated":
        from .runners.langgraph_runner import _LANGGRAPH_AVAILABLE
        if _LANGGRAPH_AVAILABLE:
            return ("mainline", "fake", "langgraph")
        elif force_run:
            print("Warning: LangGraph not installed. Falling back to native backend (--force-run).")
            return ("mainline", "fake", "native")
        else:
            return ("blocked", None, None)

    # Everything else → legacy Scheduler
    return ("legacy", None, None)
```

`_handle_ask_command()` 传递 `execution_backend` 到 MainlineExecutor。

### 2. MainlineExecutor (`mainline_executor.py`)

增加 `execution_backend` 参数:

```python
def execute(
    self,
    plan: PlanContract,
    *,
    worker_mode: str = "fake",
    max_workers: int = 2,
    execution_backend: str = "native",   # NEW: "native" | "langgraph"
) -> MainlineResult:
```

- `execution_backend="native"` → 走现有 `_execute_multi_worker()` 或单 worker 路径
- `execution_backend="langgraph"` → 调用 `_execute_langgraph(plan, worker_mode, ...)`

新增 `_execute_langgraph()`:

```python
def _execute_langgraph(
    self,
    plan: PlanContract,
    *,
    worker_mode: str = "fake",
    **kwargs,
) -> MainlineResult:
    """Execute plan via LangGraphRunner.

    LangGraphRunner 接收 PlanContract，每个 step 仍然走:
    worker dispatch → evidence → ControlPlane 检查。
    LangGraphRunner 不绕过 ControlPlane，不复制 worker 逻辑。
    """
    from .runners.langgraph_runner import LangGraphRunner

    runner = LangGraphRunner(project_root=str(self.project_root))
    lg_result = runner.run(
        plan=plan,
        control_plane=self._control_plane,
        policy=self._policy,
        worker_mode=worker_mode,
        **kwargs,
    )
    return self._convert_langgraph_result(lg_result)
```

### 3. LangGraphRunner 集成 (`langgraph_runner.py`)

LangGraphRunner.run() 已经接收 PlanContract + ControlPlane，架构正确。
需要确认/修改的点：

- `run()` 的 `worker_registry` 参数 — 确保 worker dispatch 复用现有的 `_execute_worker()` 路径，而不是在 LangGraphRunner 内部重新实现一套 worker 调用
- 每个 node 必须经过: pre-node policy → worker execute → evidence collect → post-node ControlPlane check
- 把 worker_mode 参数传下去（fake/packet/claude-code）
- `RunnerResult` 能够转换成 `MainlineResult`（或统一返回类型）

### 4. 旧 Scheduler (`scheduler.py`)

- `run_orchestrated()` 保留不动
- 在函数 docstring 和类 docstring 中加入 deprecation 标记：

```python
class Scheduler:
    """Legacy YAML-workflow scheduler.

    Deprecated for new work. Use MainlineExecutor for all new task execution.
    MainlineExecutor supports both native (MultiWorkerExecutor) and langgraph
    (LangGraphRunner) backends.

    This class is preserved for:
    - Legacy YAML workflow compatibility
    - run_orchestrated() as a legacy compatibility path (not the main entry
      point for LangGraph)
    """
```

### 5. blocked 路径信息

当 orchestrated 但 langgraph 未安装时，blocked 消息改为：

```
"Orchestrated mode requires LangGraph, which is not installed.
 Install with: pip install langgraph
 Or use --force-run to fall back to native backend."
```

## Non-Goals

- 不重写 Scheduler
- 不删除 Scheduler
- 不新增另一套 worker 协议
- 不让 LangGraphRunner 直接生成假结果绕过 evidence/control
- 不修改 MultiWorkerExecutor 的内部逻辑
- 不修改 ControlPlane 的接口

## Test Plan

### 路由测试

```
test_controlled_routes_to_mainline_native_backend
test_orchestrated_routes_to_mainline_langgraph_backend
test_orchestrated_without_langgraph_returns_blocked
test_orchestrated_without_langgraph_force_run_falls_back_native
test_explicit_worker_mode_routes_to_mainline_native
test_off_log_mode_returns_noop
```

### MainlineExecutor backend 测试

```
test_execute_with_native_backend_uses_multi_worker
test_execute_with_langgraph_backend_calls_langgraph_runner
test_langgraph_backend_does_not_bypass_control_plane
test_langgraph_backend_returns_mainline_result
test_native_backend_still_runs_multi_worker
```

### LangGraphRunner 集成测试

```
test_langgraph_runner_receives_plan_contract
test_langgraph_runner_each_step_passes_through_control_plane
test_langgraph_runner_worker_dispatch_uses_existing_path
test_langgraph_runner_refuses_unapproved_plan
test_langgraph_runner_not_installed_raises_clear_error
```

### 回归测试

```
现有测试全部通过（python -m pytest tests/ -q）
Scheduler 的 legacy 测试不受影响
MultiWorkerExecutor 测试不受影响
```

## Files That Will Change

```
src/orchestrator/__main__.py               # _resolve_execution_path + _handle_ask_command
src/orchestrator/mainline_executor.py      # execute() + _execute_langgraph() 新增
src/orchestrator/runners/langgraph_runner.py  # worker_mode 传递 + 注释
src/orchestrator/scheduler.py              # deprecation docstring
tests/test_mainline_routing.py             # 新测试（路由 + backend）
tests/test_langgraph_integration.py        # 新测试（集成）
```

## Definition Of Done

```
- controlled → MainlineExecutor + native backend
- orchestrated → MainlineExecutor + langgraph backend
- langgraph 不可用时 orchestrated → blocked + 明确 dependency missing 提示
- --force-run → orchestrated 回退 native backend
- native backend 仍能跑 multi-worker（现有行为不退化）
- langgraph backend 不绕过 ControlPlane
- Scheduler 标记为 legacy，不作为 LangGraph 主入口
- 所有新测试通过
- 所有现有测试通过（无回归）
- 一次真实 smoke：python -m orchestrator ask "..." --mode orchestrated
  确认路由到 langgraph backend（或正确报 missing dependency）
```

## Required Final Explanation To User

```
Phase 29 之前，runner 架构是乱的:

- MainlineExecutor 用 ThreadPoolExecutor 做并行
- LangGraphRunner 挂在旧 Scheduler 下面
- controlled 和 orchestrated 在 CLI 路由里走同一条路
- 三套东西（mainline / native / langgraph）各跑各的，边界模糊

Phase 29 之后:

- MainlineExecutor 是唯一入口
- execution_backend="native" → ThreadPoolExecutor（轻量并行）
- execution_backend="langgraph" → LangGraphRunner（checkpoint/resume/分支）
- controlled 默认走 native，orchestrated 默认走 langgraph
- langgraph 没装时明确告诉你，不偷偷降级
- Scheduler 退休到 legacy 状态

这不是加新功能。是把已经造好的零件装到正确的位置。
```

## Claude Code Instruction

Read `CLAUDE.md` 和这个 spec。Phase 29 是架构接线，不是造新轮子。
所有代码已存在（MainlineExecutor、LangGraphRunner、MultiWorkerExecutor、
CLI 路由）。你的工作是:
1. 在 CLI 路由里区分 controlled 和 orchestrated
2. 给 MainlineExecutor 加 execution_backend 参数
3. 让 langgraph backend 走 LangGraphRunner.run()
4. 标记 Scheduler 为 legacy
5. 写测试证明接线正确
不重写、不删除、不新建 worker 协议。
