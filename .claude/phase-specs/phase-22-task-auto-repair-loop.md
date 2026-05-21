# Phase 22 - Task Auto Repair Loop

## Goal

Worker task 失败或被 reviewer 发现问题后，AAO 能自动产生 FixTask、派 worker 修、重测、重审，直到成功或进入人工审核。不是盲目重试，是有目标的修复闭环。

```
主链路:

WorkerTaskPacket
  → worker 执行
  → evidence / test output
  → ControlPlane 或 Isolated Reviewer 发现问题
  → ReviewFinding (blocking / non-blocking)
  → blocking finding → 生成 FixTask
  → FixTask 派 worker 执行修复
  → retest / re-verify
  → rereview
  → success → 记录 audit → 继续
  或 still failing → human review (blocked_needs_review)
```

## Hard Rules

- max repair attempts 默认 2，超过进入 human review
- non-blocking finding 不触发 FixTask
- system_issue 不触发普通 FixTask（那是 Phase 27 的事）
- 每轮 fail/fix/pass 都必须记录在 audit 里
- FixTask 必须限定修复范围（一个文件、一个检查），不能无限扩散

## Models

### ReviewFinding

```python
class ReviewFinding:
    finding_id: str
    step_id: str
    severity: "blocking" | "non_blocking" | "info"
    category: str  # e.g. "missing_evidence", "test_failure", "lint_error"
    description: str
    location: str  # file:line or evidence path
    suggested_fix: str | None
    source: str  # "reviewer" | "control_plane" | "evaluator"
```

### FixTask

```python
class FixTask:
    fix_id: str
    triggered_by_finding_id: str
    step_id: str
    target_file: str               # exactly one file
    fix_description: str
    verification: str              # what check proves the fix worked
    max_attempts: int = 2
    current_attempt: int = 0
    status: "pending" | "in_progress" | "fixed" | "still_failing"
```

## Repair Loop

```
Round 1:
  worker executes → fails (test output shows FAILED)
  → ControlPlane/Reviewer 产生 blocking ReviewFinding
  → 生成 FixTask(target_file, fix_description, verification)
  → 派 worker 执行 FixTask
  → retest
  → rereview
  → pass → 记录 "repair_round_1: fail → fix → pass" → 继续

Round 2 (if round 1 still fails):
  → 生成第二个 FixTask（修复角度不同）
  → 派 worker 执行
  → retest
  → rereview
  → pass → 记录 "repair_round_2: fail → fix → pass"

Round 3 (if round 2 still fails):
  → max_attempts=2 已达到
  → status = blocked_needs_review
  → 不产生新 FixTask
  → 进入 human review 路径
```

## Audit Requirements

每轮修复必须记录：

```
{
  "repair_round": 1,
  "finding_id": "F-001",
  "finding": "test_output.txt shows 2 FAILED",
  "fix_task_id": "FT-001",
  "fix_description": "Fix assertion in test_memory.py:42",
  "worker_result": "pass",
  "retest_result": "2 passed, 0 failed",
  "rereview_result": "no blocking findings",
  "status": "fixed"
}
```

## Non-Goals

- 不处理 system_issue（Phase 27）
- 不处理 non-blocking finding
- 不过度修复（一个 FixTask 只修一个文件）
- 不替代 Phase 11 recovery（retry → backoff → replan → review 链路仍然存在，Phase 22 是在 retry 之后的新选项）

## Relationship to Recovery Playbook (Phase 11)

Phase 11 的 recovery 链路：
```
step fails → retry → retry_with_backoff → replan → human review → fail
```

Phase 22 在 "retry" 之后插入 "auto-repair"：
```
step fails → retry → [auto-repair: 最多2轮 FixTask] → still failing → replan → human review → fail
```

## Test Plan

```
test_first_attempt_success_no_fix_task_generated
test_missing_evidence_generates_fix_task_second_attempt_succeeds
test_test_failure_generates_fix_task_second_attempt_succeeds
test_repair_still_fails_after_max_attempts_enters_human_review
test_non_blocking_finding_does_not_trigger_fix_task
test_system_issue_does_not_trigger_ordinary_fix_task
test_infinite_loop_prevention_max_attempts_enforced
test_audit_records_every_fail_fix_pass_round
test_fix_task_targets_only_one_file
```

## Definition Of Done

```
- ReviewFinding → FixTask 链路完整
- max_attempts=2 硬约束生效
- non-blocking finding 不触发修复
- system_issue 不触发普通 FixTask
- 每轮 fail/fix/pass 记录在 audit
- 超过 max_attempts 后进入 blocked_needs_review
- 所有测试通过（fake worker + 确定性 reviewer）
- 一次真实 smoke：故意写一个会失败的测试，交给 worker，证明 AAO 检测到、生成 FixTask、修复、重跑通过
```

## Required Final Explanation To User

```
Phase 22 之前，worker 失败只能重试或者等人。

Phase 22 之后，AAO 能看懂失败原因（测试挂了、lint 报错、evidence 缺失），
生成一个有范围的 FixTask（"修这个文件里的这个函数"），派 worker 去修，
修完重测重审。最多试 2 轮。修好了自动继续，修不好才找你。

不是"AI 自由发挥改代码"，而是有边界、有记录、有次数限制的修复闭环。
```

## Claude Code Instruction

Read `CLAUDE.md` 和这个 spec。实现 Phase 22。目标是 bounded auto-repair：
一个文件、一个检查、最多两轮。不是自主调试，不是自由重构。
