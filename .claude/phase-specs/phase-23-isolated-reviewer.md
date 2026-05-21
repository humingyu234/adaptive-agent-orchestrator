# Phase 23 - Isolated Reviewer

## Goal

把 reviewer 从 worker 中隔离出来，作为一个独立的、只读的检查角色。
Reviewer 不能改代码，不能基于 worker 的自我总结下判断，
只能基于 observed evidence 产生 ReviewFinding。

```
Worker 产出:
  git diff
  changed files
  test output
  result.md
  evidence artifacts

    ↓ (只读传入)

Reviewer 检查:
  - 代码改动是否符合 task 要求
  - 测试是否真的通过（不信任 worker 口述）
  - evidence 是否真实（不信任 worker 自述）
  - 有没有遗漏的检查项

    ↓

ReviewFinding:
  - severity: blocking | non_blocking | info
  - 具体位置: file:line 或 evidence path
  - 问题描述 + 建议

    ↓

MainlineExecutor:
  - blocking finding → FixTask (Phase 22)
  - non_blocking finding → 记录但继续
  - 全部通过 → 继续下一步
```

## Hard Rules

- Reviewer 只读，绝不能改代码
- Reviewer 不能复用 worker 的自我总结作为事实来源
- Reviewer 只能看 observed evidence（列表见下方）
- Reviewer 输出 ReviewFinding，不直接生成 FixTask
- MainlineExecutor 才负责把 ReviewFinding 转成 FixTask
- Reviewer 和 Worker 上下文必须隔离（不共享会话、不共享工作目录写入权限）

## What Reviewer CAN Read (Observed Evidence Only)

```
✅ git diff (实际代码改动)
✅ changed files 列表
✅ test output (测试框架原始输出)
✅ result.md (worker 的结构化结果)
✅ evidence artifacts (捕获的命令输出、文件内容)
✅ audit artifacts (前序步骤的 audit 记录)
```

## What Reviewer CANNOT Trust

```
❌ worker 的自我总结 ("I completed the task successfully")
❌ worker 的自我评估 ("The code looks good")
❌ 没有 evidence 支撑的任何 claim
❌ worker 声称但未在 test output 中出现的测试结果
```

## Interfaces

### Reviewer (抽象基类)

```python
class Reviewer(ABC):
    """Read-only inspector. Produces findings, never writes code."""

    @abstractmethod
    def review(
        self,
        task: WorkerTaskPacket,
        result: WorkerResultPacket,
        evidence: EvidencePack,
    ) -> list[ReviewFinding]:
        ...
```

### RuleBasedReviewer (确定性实现，用于测试)

```python
class RuleBasedReviewer(Reviewer):
    """Deterministic rule-based reviewer for tests and fast checks.

    Rules:
    - If test_output contains FAILED → blocking finding
    - If evidence.observed_paths is empty → blocking finding
    - If result claims "tests_pass=true" but test_output shows failures
      → blocking finding (evidence contradiction)
    - If diff touches files outside allowed_files → blocking finding
    - If changed_files != diff's actual files → non_blocking finding
    """
```

### FakeReviewer (测试用)

```python
class FakeReviewer(Reviewer):
    """Returns pre-configured findings for deterministic testing."""
```

### LLMReviewer / ClaudeCodeReviewer (预留接口)

```python
class LLMReviewer(Reviewer):
    """LLM-based reviewer. Reads evidence artifacts, produces findings.
    Must run in read-only mode. Must not call write tools.
    Future: launch as isolated Claude Code worker with write disabled.
    """
```

## Reviewer-Worker Isolation

```
Worker 工作目录:
  .aao/tasks/<run_id>/<step_id>/worker/

Reviewer 工作目录:
  .aao/tasks/<run_id>/<step_id>/review/

Reviewer 只读挂载 worker 目录的 evidence 子目录:
  .aao/tasks/<run_id>/<step_id>/worker/observed/  → 只读
  .aao/tasks/<run_id>/<step_id>/worker/result.md   → 只读

Reviewer 自己的输出:
  .aao/tasks/<run_id>/<step_id>/review/findings.json
```

Reviewer 进程/会话绝不能有 worker 目录的写权限。如果检测到 reviewer 尝试写入 worker 目录，这本身就是一个 system_issue（Phase 27）。

## ReviewFinding → FixTask 转换

这个转换在 MainlineExecutor 中完成，不在 Reviewer 中：

```python
# In MainlineExecutor:
for finding in review_findings:
    if finding.severity == "blocking":
        fix_task = FixTask(
            triggered_by_finding_id=finding.finding_id,
            step_id=step.id,
            target_file=extract_target_file(finding),
            fix_description=finding.suggested_fix or finding.description,
            verification=f"Re-run checks for {step.id}",
        )
        repair_queue.append(fix_task)
    elif finding.severity == "non_blocking":
        # Record in evidence but continue
        record_finding(finding)
```

## Test Plan

```
test_reviewer_has_no_write_permission
test_reviewer_only_bases_finding_on_observed_evidence
test_worker_self_reports_success_but_test_output_fails_reviewer_blocks
test_reviewer_finding_can_be_converted_to_fix_task_by_mainline
test_reviewer_does_not_directly_execute_fix
test_reviewer_context_isolated_from_worker
test_non_blocking_finding_recorded_but_does_not_block
test_rule_based_reviewer_detects_evidence_contradiction
test_fake_reviewer_returns_configured_findings
test_reviewer_rejects_worker_self_summary_as_evidence
```

## Definition Of Done

```
- Reviewer 接口定义完成（抽象基类）
- RuleBasedReviewer 可检测：测试失败、evidence 缺失、evidence 矛盾、越权文件修改
- FakeReviewer 可用于测试
- LLMReviewer / ClaudeCodeReviewer 接口预留
- Reviewer 与 Worker 上下文隔离（独立工作目录）
- Reviewer 无写权限
- ReviewFinding → FixTask 转换在 MainlineExecutor 中完成
- 所有测试通过
```

## Required Final Explanation To User

```
Phase 23 之前，worker 说自己做完了，AAO 就信了。或者 reviewer 和 worker
混在一起，自己审查自己。

Phase 23 之后，reviewer 是一个独立的只读检查员。它不看 worker 的自我总结
（"我做得很好"），只看实际证据（diff、测试输出、文件改动）。发现矛盾就
blocking。但它不会动手改代码——只会报告问题，让 Mainline 决定要不要修。

就像一个只评论不提交的 code reviewer。
```

## Claude Code Instruction

Read `CLAUDE.md` 和这个 spec。实现 Phase 23。
Reviewer 是只读检查员。它找问题、报告问题、不修问题。
隔离 reviewer 和 worker 的上下文。不要把 reviewer 做成 worker 的附庸。
