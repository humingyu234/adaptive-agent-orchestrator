# Execution Fabric — 并行执行与任务分发层

> 这份文档补齐 8 层生态蓝图里缺失的一层：多任务并行执行、DAG 调度、Worker 分发、结果合并与失败协议。
>
> 它整合了 `tmp/claude_plan.md` 和 `tmp/codex_plan.md` 中的并行设计草案，并补齐了四个之前只有方向没有深度的关键模块。

---

## 1. 在生态中的位置

这一层插在 Supervisor Orchestrator (L2) 和 Runtime Core (L3) 之间：

```text
┌──────────────────────────────────────────────────────────────────┐
│ LAYER 2: SUPERVISOR ORCHESTRATOR                                │
│ Planning Council → CouncilPlan (steps + deps + review_points)    │
└────────────────────────────┬─────────────────────────────────────┘
                             │ CouncilPlan
┌────────────────────────────▼─────────────────────────────────────┐
│ LAYER 9: EXECUTION FABRIC                             ← 这份文档  │
│ DAG Parser · Execution Router · Batch Scheduler                  │
│ Worker Contract · Result Merger · Fan-out/Gather Engine          │
└────────────────────────────┬─────────────────────────────────────┘
                             │ ExecutionBatch[]
┌────────────────────────────▼─────────────────────────────────────┐
│ LAYER 3: RUNTIME CORE                                           │
│ Scheduler · StateCenter · Evaluator(L1/L2) · Checkpoint          │
└──────────────────────────────────────────────────────────────────┘
```

**为什么叫 Execution Fabric 而不是只叫 Parallel Runner**

因为它的职责不只是"并行跑"，而是：
- 理解任务之间的依赖关系（什么可以并行、什么必须串行）
- 管理多 Worker 的生命周期（启动、监控、超时、取消）
- 处理并行结果的合并策略（全部完成 / 部分降级 / 冲突仲裁）
- 在并行执行与 checkpoint 持久化之间保持一致

---

## 2. DAG 任务模型

### 2.1 任务图定义

Planning Council 输出的方案，用 DAG 而不是线性 workflow 描述：

```json
{
  "steps": [
    {
      "id": 1,
      "action": "search",
      "target": "AWS GPU 价格与可用区",
      "parallel_group": "vendor_search",
      "worker_type": "cc_worker",
      "timeout_s": 180
    },
    {
      "id": 2,
      "action": "search",
      "target": "Azure GPU 价格与可用区",
      "parallel_group": "vendor_search",
      "worker_type": "cc_worker",
      "timeout_s": 180
    },
    {
      "id": 3,
      "action": "search",
      "target": "GCP GPU 价格与可用区",
      "parallel_group": "vendor_search",
      "worker_type": "cc_worker",
      "timeout_s": 180
    },
    {
      "id": 4,
      "action": "merge_results",
      "depends_on": [1, 2, 3],
      "gather_strategy": "all",
      "worker_type": "summarizer",
      "timeout_s": 120
    },
    {
      "id": 5,
      "action": "verify",
      "depends_on": [4],
      "gather_strategy": "single",
      "worker_type": "supervisor",
      "timeout_s": 60
    }
  ],
  "milestone_review_points": [
    {"after_step": 4, "reason": "合并后的对比表需要人工确认"}
  ]
}
```

### 2.2 核心概念

| 概念 | 含义 |
|---|---|
| `parallel_group` | 同一 group 内的 step 可以并行执行，共享 group 级的 gather_strategy |
| `depends_on` | 必须等这些 step 全部完成（按 gather_strategy 判断"完成"）后才能开始 |
| `worker_type` | 到什么 Worker 池去找执行体 |
| `gather_strategy` | 决定了"等待策略"——必须全部成功、还是任意一个、还是多数 |
| `timeout_s` | 单个 step 的超时时间 |

### 2.3 Step 完整生命周期

```
                    ┌──────────┐
                    │  QUEUED  │  被依赖的 step 还没跑完，等着
                    └────┬─────┘
                         │ 依赖全部满足
                         ▼
                    ┌──────────┐
                    │ ASSIGNED │  已分配给 Worker
                    └────┬─────┘
                         │ Worker 开始执行
                         ▼
              ┌─────────────────────┐
              │      RUNNING        │
              └──┬──────┬──────┬───┘
                 │      │      │
        ┌────────▼┐ ┌───▼──┐ ┌─▼──────┐
        │COMPLETED│ │FAILED│ │TIMED_OUT│
        └────────┬┘ └──┬───┘ └─┬──────┘
                 │     │       │
                 ▼     ▼       ▼
              ┌─────────────────────┐
              │    GATHER 判断       │
              │  按策略决定是否继续   │
              └─────────────────────┘
```

每个 step 在 transition 时打 event 进 execution_trace，和现有的 L3 审计体系一致。

---

## 3. Fan-out / Gather 引擎

这是之前设计里最缺的部分。一个 DAG step 的依赖有多条边进来时，怎么判断"所有依赖已完成、可以继续"？

### 3.1 Gather Strategy 枚举

```python
class GatherStrategy(str, Enum):
    ALL = "all"           # 全部成功才继续。缺一个 → 整个 batch 标记 FAILED
    ANY = "any"           # 任意一个成功就继续。其他 Worker 收到取消信号
    MAJORITY = "majority" # 超过半数成功就继续。少数失败 → 标记为 DEGRADED，带着不完整结果继续
    FIRST = "first"       # 最快的那个，其他取消。适合竞速类任务（多个搜索源搜同一个东西）
    DEGRADE = "degrade"   # 缺了也继续，但标记降级，后续 step 能感知到数据不完整
```

### 3.2 Gather 决策流程

```python
def evaluate_gather(
    strategy: GatherStrategy,
    results: dict[str, StepResult],  # step_id → StepResult
) -> GatherDecision:

    succeeded = {k: v for k, v in results.items() if v.status == "completed"}
    failed = {k: v for k, v in results.items() if v.status in ("failed", "timed_out")}
    total = len(results)

    if strategy == GatherStrategy.ALL:
        if len(succeeded) == total:
            return GatherDecision(proceed=True, quality="full", missing=[])
        return GatherDecision(proceed=False, quality="failed",
                              missing=[v.step_id for v in failed.values()])

    if strategy == GatherStrategy.ANY:
        if len(succeeded) >= 1:
            return GatherDecision(proceed=True, quality="partial",
                                  missing=[v.step_id for v in failed.values()],
                                  cancel_remaining=[v.step_id for v in results.values()
                                                    if v.status == "running"])
        return GatherDecision(proceed=False, quality="failed", missing=list(results.keys()))

    if strategy == GatherStrategy.MAJORITY:
        if len(succeeded) > total / 2:
            return GatherDecision(proceed=True, quality="degraded",
                                  missing=[v.step_id for v in failed.values()])
        return GatherDecision(proceed=False, quality="failed",
                              missing=[v.step_id for v in failed.values()])

    if strategy == GatherStrategy.FIRST:
        if len(succeeded) >= 1:
            return GatherDecision(proceed=True, quality="first_available",
                                  cancel_remaining=[v.step_id for v in results.values()
                                                    if v.status in ("running", "queued", "assigned")])
        return GatherDecision(proceed=False, quality="failed", missing=list(results.keys()))

    if strategy == GatherStrategy.DEGRADE:
        return GatherDecision(proceed=True, quality="degraded" if failed else "full",
                              missing=[v.step_id for v in failed.values()])
```

### 3.3 GatherDecision 结构

```python
@dataclass
class GatherDecision:
    proceed: bool                # 是否继续到下一步
    quality: str                 # "full" | "partial" | "degraded" | "first_available" | "failed"
    missing: list[str]           # 缺失的 step_id 列表
    cancel_remaining: list[str]  # 需要取消的正在跑的 step_id（FIRST 和 ANY 场景）
```

`quality != "full"` 时，系统会把这个信息注入 `state.data_pool.intermediate["fabric_quality"]`，后续 step 和 Evaluator 能感知到"上游数据不完整"——这是 Graceful Degradation 在并行层的具体落地。

---

## 4. Worker Contract — 失败协议

之前的 Worker Contract 只定义了"怎么派活"，没有失败处理。这里补齐完整的双向约定。

### 4.1 Runtime → Worker 的契约

```python
@dataclass
class WorkerTask:
    """Runtime 发给 Worker 的任务描述"""
    task_id: str
    step_id: str
    task_prompt: str            # 人话，告诉 worker 要干什么
    expected_output: dict       # 约定输出 JSON schema
    result_marker: str          # 默认 "##RESULT:"，Worker 用这个标记来界定输出
    timeout_s: int              # 超时秒数
    interrupt_check_file: str   # Worker 在执行过程中定期检查这个文件，发现中断信号就优雅退出
    checkpoint_dir: str         # Worker 的半成品应该写到这里
    context: dict               # 输入数据
```

### 4.2 Worker → Runtime 的响应

```python
@dataclass
class WorkerResult:
    """Worker 返回的结果"""
    step_id: str
    status: str                 # "completed" | "failed" | "timed_out" | "refused"
    output: dict | None         # 成功时包含结构化结果
    error: str | None           # 失败时的错误信息
    confidence: float           # Worker 自己对结果的信心 0.0~1.0
    partial_output: dict | None # 半成品——超时或被中断但已有部分结果
    duration_s: float
    token_usage: dict | None
```

### 4.3 四种失败模式的 Runtime 处理

| Worker 状态 | Runtime 行为 |
|---|---|
| `completed` | L1/L2 评估 + 写入 intermediate + 标记 step 完成 |
| `failed` | 记录 `WorkerResult.error` → 按 gather_strategy 决定是否继续。如果策略不要这个 step 也能继续，标记缺失。如果策略要求 all，整个 batch 失败 |
| `timed_out` | 检查 `partial_output`。有半成品 → 用 L1 评估半成品 → 如果能用就标记 DEGRADED。没有半成品 → 等同于 failed |
| `refused` | Worker 返回"我不确定/我做不到"。这是一个**有效但不完整**的结果。不重试。标记为 REFUSED。策略上把它和 failed 同等看待——gather 时看这个 step 能不能缺 |

### 4.4 重试策略

重试由 Runtime 决定，不由 Worker 自己重试：

```python
class RetryPolicy:
    max_retries: int = 1           # 默认不重试（和 L3 的重试 loop 区分——那个是 agent 自己的重试）
    retryable_errors: list[str]    # 只有这些错误才重试：["timeout", "api_error"]
    non_retryable_errors: list[str]# 这些不重试：["refused", "format_error", "guardrail_blocked"]
    backoff_s: int = 5             # 重试间隔
```

---

## 5. 并行执行与 Checkpoint 的一致性

这是之前设计里完全没有触及的问题。线性执行时每步结束后打 checkpoint 是自然的。并行执行时，不同 Worker 完成时间不同，checkpoint 打在哪里？

### 5.1 三层 Checkpoint

```text
            Worker A 完成 ──► Worker A 独立 checkpoint
                  │
Worker B 仍在运行（不打全局 checkpoint）
                  │
            Worker B 完成 ──► Worker B 独立 checkpoint
                  │
          Batch 全部结束 ──► Batch-level global checkpoint
                             （此时所有 Worker 状态一致）
```

| 层级 | 时机 | 内容 | 用途 |
|---|---|---|---|
| **Per-worker checkpoint** | 每个 Worker 完成时立即打 | 该 Worker 的完整输出 + intermediate snap | Worker 崩溃后单个重跑 |
| **Batch-level checkpoint** | 整个 batch 的 gather 判断完成后 | 所有 Worker 结果 + gather decision + 合并后的 intermediate | 整个 batch 崩溃后从断点恢复 |
| **Milestone checkpoint** | `milestone_review_point` 处 + 人工确认后 | 完整 state snap + milestone review 记录 | 人工确认后的安全点 |

### 5.2 崩溃恢复路径

```
    Batch 执行中，进程崩溃
         │
         ▼
   重新启动，扫描 outputs/states/ 中 status != completed && != failed 的任务
         │
         ▼
   读取最近一个 batch-level checkpoint
         │
   检查每个 Worker 的 per-worker checkpoint：
   ├── 所有 Worker 都有 checkpoint → 从 batch checkpoint 继续，跳转到下一个 batch
   ├── 部分 Worker 有 checkpoint → 只重跑缺失的 Worker，保留已有结果
   └── 没有任何 Worker checkpoint → 整个 batch 重跑
```

### 5.3 关键约束

- **一个 batch 内的不同 Worker 必须独立输出目录**。共享的 `outputs/memory/index.json` 只在 batch 全部结束后统一写，不在 Worker 执行中写。
- **LiveInterrupt 的 signal file 在 batch 模式下按 task 隔离**：`outputs/interrupts/<task_id>/signal.json`，不同 task 互不影响。
- **重跑是幂等的**：同一个 step 重跑两次，输出覆盖到同一个 `outputs/steps/<task_id>/<step_id>/result.json`，不产生重复数据。

---

## 6. Execution Router — 把 DAG 翻译成执行批次

### 6.1 拓扑排序 + 合批

```python
class ExecutionRouter:
    """读 CouncilPlan，生成执行批次"""

    def route(self, plan: CouncilPlan) -> list[ExecutionBatch]:

        # Step 1: 拓扑排序
        sorted_steps = self._topological_sort(plan.steps)

        # Step 2: 相邻的、同 parallel_group、无互相依赖的 step 合并到一个 batch
        batches = self._batch_adjacent_parallel(sorted_steps)

        # Step 3: 注入 milestone review checkpoint
        for review_point in plan.milestone_review_points:
            self._inject_review_checkpoint(batches, review_point)

        return batches


@dataclass
class ExecutionBatch:
    batch_id: str
    steps: list[StepDef]          # 这个 batch 内可以并行执行的 step
    gather_strategy: GatherStrategy
    depends_on_batch: str | None  # 等哪个 batch 跑完
    is_milestone_review: bool     # 这个 batch 结束后是否暂停等人确认
    review_reason: str
```

### 6.2 Batch 执行流程

```python
def run_batch(batch: ExecutionBatch, state: StateCenter) -> BatchResult:
    """执行一个 batch"""

    # 并行启动所有 Worker（进程池或线程池）
    with ThreadPoolExecutor(max_workers=len(batch.steps)) as executor:
        futures = {
            executor.submit(run_single_step, step, state): step
            for step in batch.steps
        }

        # 等待全部完成（或超时）
        results = {}
        for future in as_completed(futures, timeout=MAX_BATCH_TIMEOUT):
            step = futures[future]
            try:
                results[step.id] = future.result()
            except TimeoutError:
                results[step.id] = WorkerResult(step.id, status="timed_out")
            except Exception as e:
                results[step.id] = WorkerResult(step.id, status="failed", error=str(e))

    # Gather 判断
    gather = evaluate_gather(batch.gather_strategy, results)

    # 打 batch-level checkpoint
    state.create_checkpoint(
        created_by="execution_router",
        reason=f"batch_{batch.batch_id}_complete",
        node_name=f"batch_{batch.batch_id}",
        node_index=batch_index,
        project_root=project_root,
    )

    return BatchResult(
        batch_id=batch.batch_id,
        step_results=results,
        gather_decision=gather,
    )
```

---

## 7. Parallel Batch Runner — 批量验证工具

这个是给 demo 和批量验证用的轻量工具，和 Execution Router 不是同一个东西。

### 7.1 定位

Execution Router 跑的是**一个 DAG 内部的并行步**。Parallel Batch Runner 跑的是**多个独立 task（不同的 query/workflow）同时验证**。

### 7.2 接口

```python
class BatchCase(BaseModel):
    name: str
    query: str
    workflow: str | None = None
    review_policy: str = "none"

class BatchRunResult(BaseModel):
    case_name: str
    task_id: str
    status: str
    workflow_name: str
    report_path: str
    duration_ms: int
    error: str | None = None

def run_batch(
    cases: list[BatchCase],
    max_workers: int = 1,       # 默认串行，避免污染共享文件
    delay_between_s: float = 0  # 秒，API rate limit 保护
) -> list[BatchRunResult]:
```

### 7.3 隔离规则

| 资源 | 隔离方式 |
|---|---|
| `outputs/reports/<task_id>.json` | 天然按 task_id 隔离，安全 |
| `outputs/states/<task_id>.json` | 天然按 task_id 隔离，安全 |
| `outputs/logs/<task_id>.jsonl` | 天然按 task_id 隔离，安全 |
| `outputs/memory/index.json` | **共享写点**。`max_workers>1` 时加 file lock 或全部跑完后统一写 |
| `outputs/interrupts/signal.json` | **全局文件**。batch 模式禁用 LiveInterrupt 或切为 `per_task` 模式 |
| 真实 LLM API | `--delay-seconds` 控制请求间隔，避免触发 rate limit |

### 7.4 CLI

```bash
py -m orchestrator batch --file examples/demo_batch.json --max-workers 1
```

---

## 8. 实现优先级

### 第一批（打穿最小链路）

| 模块 | 范围 | 时间 |
|---|---|---|
| `StepDef` / `CouncilPlan` 模型 | 在 `models.py` 里新增 DAG 步骤模型 | 1 天 |
| `ExecutionRouter` 最小版 | 拓扑排序 + 合批（只支持 `gather_strategy=all`） | 2 天 |
| `ParallelBatchRunner` 最小版 | `max_workers=1` 默认，按 task_id 隔离输出 | 1 天 |
| 测试 | 3 个独立 query batch 跑通 + 一个并行 group 的 DAG 跑通 | 1 天 |

### 第二批（补齐 gather 策略）

| 模块 | 范围 |
|---|---|
| `GatherStrategy` 全部 5 种 | `all` / `any` / `majority` / `first` / `degrade` |
| `GatherDecision` 完整逻辑 | 包括 `cancel_remaining` 和 `quality` 标记 |
| `milestone_review_point` 接入 | batch 结束后自动暂停，输出 review package |

### 第三批（补齐持久化一致性）

| 模块 | 范围 |
|---|---|
| Per-worker checkpoint | 每个 Worker 完成时独立持久化 |
| Batch-level checkpoint | Gather 判断完成后统一打点 |
| 崩溃恢复入口 | `run --resume` 自动扫描未完成任务 |

### 第四批（Worker Contract 生产级）

| 模块 | 范围 |
|---|---|
| `RetryPolicy` | 超时/API 错误的重试逻辑 |
| `partial_output` 处理 | 半成品评估 + 降级标记 |
| `refused` 状态处理 | Worker 拒绝执行的语义 |
| CC Worker Adapter | `CCWorkerAdapter` 桥接 CC 的输入输出 |

---

## 9. 与现有模块的关系

| 现有模块 | 并行层怎么用 |
|---|---|
| `SupervisorOrchestrator` | Planning Council 输出的 `CouncilPlan` 作为 Execution Router 的输入 |
| `Scheduler._execute_agents()` | 并行版调用 `run_batch()`，串行版保持现有逻辑 |
| `StateCenter` | 并行版的 intermediate 读写需要加**文件锁**（多个 Worker 完成时并发写） |
| `Evaluator(L1/L2)` | 每个 Worker 的结果独立评估。合并结果再评估一次 |
| `Checkpoint` | 新增 per-worker + batch-level checkpoint，不改现有 step-level checkpoint 逻辑 |
| `MemoryManager` | 只在整个 task 完成后写一次 memory，不在并行 Worker 执行中写 |
| `LiveInterruptController` | batch 模式禁用全局 signal，改为 `per_task` 隔离 |

---

## 10. 一句话总结

Execution Fabric 把"固定 workflow 线性跑"升级为"Planning Council 出 DAG → Execution Router 拆批次 → 并行 Worker 执行 → Gather 判断 → 继续或暂停"。它是 8 层生态蓝图从"单任务完整运行"到"多任务高效编排"的关键跃迁层。当前设计已经覆盖了 DAG 模型、生命周期、5 种 gather 策略、Worker 失败协议、并行 checkpoint 一致性——剩下的就是分批实现。
