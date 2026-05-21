# Phase 25 - Milestone Gate / Human Approval

## Goal

实现阶段性暂停和人工确认。每个 milestone 执行完成后，
AAO 生成验收包、暂停、等用户确认，用户 approve 后才继续下一个 milestone。

```
链路:

milestone 执行完成
  → 生成验收包 (evidence summary + reviewer findings + audit)
  → status = paused_for_approval
  → 用户可以:
      - project ask "<question>"  追问细节
      - project approve <milestone_id>  批准继续
      - project reject <milestone_id> --reason "..."  拒绝并说明原因
      - project request-changes <milestone_id> --notes "..."  要求调整
  → approve → 下一个 milestone 开始
  → reject → 生成调整任务
  → request-changes → 进入修复路径
```

## Hard Rules

- milestone 完成后不会自动进入下一个阶段——必须等人
- human approval 记录必须写入 audit
- reject/request-changes 的原因必须保留
- 不能跳过 gate（即使所有测试通过、reviewer 给 pass）
- gate 之前用户可以追问任何问题（Phase 26）

## CLI Commands

```
# 批准 milestone
python -m orchestrator project approve <milestone_id>

# 拒绝 milestone
python -m orchestrator project reject <milestone_id> --reason "..."

# 要求修改
python -m orchestrator project request-changes <milestone_id> --notes "..."
```

## Milestone Approval Model

```python
class MilestoneApproval:
    milestone_id: str
    status: "awaiting_approval" | "approved" | "rejected" | "changes_requested"
    approved_by: str | None      # "human"
    approved_at: datetime | None
    rejection_reason: str | None
    changes_requested_notes: str | None

    # What the human is approving:
    evidence_summary: str        # 这个 milestone 做了什么
    files_changed: list[str]
    test_results_summary: str
    reviewer_findings: list[str] # reviewer 发现了什么
    repair_history: list[str]    # 修了几轮
    open_risks: list[str]        # reviewer 标记的风险
```

## Approval Flow Detail

```
1. Milestone 所有步骤完成
2. Reviewer 审查完成（如果有）
3. 生成 MilestoneApproval 对象
4. 写入 session: milestone status = "awaiting_approval"
5. 显示验收摘要给用户
6. 用户操作:
   a. approve → session 记录 → 下一个 milestone 解锁
   b. reject → 生成调整 PlanContract → 需要重新执行或 replan
   c. request-changes → 生成 FixTask(s) → 修复后重新提交审核
7. Audit 记录人工确认
```

## Relationship to Other Phases

```
Phase 22 (Auto Repair):
  在 milestone 内自动修复 step 级别的问题。
  Milestone gate 是更高层的检查点。

Phase 23 (Reviewer):
  Reviewer 在 milestone gate 之前运行。
  Reviewer 的 blocking finding 会在 gate 之前触发 Phase 22 repair。
  Gate 打开时，reviewer 已经给过 pass。

Phase 24 (Session):
  Milestone 状态存在 session 中。
  Gate 的决定记录在 DecisionLog 里。

Phase 26 (Resume + Ask):
  Gate 暂停期间，用户可以用 project ask 追问。
```

## Test Plan

```
test_milestone_completed_does_not_auto_continue_to_next
test_approve_unlocks_next_milestone
test_reject_generates_adjustment_task
test_request_changes_enters_repair_path
test_audit_records_human_approval
test_cannot_skip_gate_even_if_all_checks_pass
test_rejection_reason_preserved_in_session
test_approval_required_but_not_given_blocks_all_subsequent_milestones
```

## Definition Of Done

```
- milestone 完成后不会自动进入下一阶段
- approve 后才能继续下一个 milestone
- reject 后生成调整任务
- request-changes 后进入修复路径
- audit 记录每次人工确认
- gate 不能被跳过
- 所有测试通过
```

## Required Final Explanation To User

```
Phase 25 之前，AAO 可能一口气跑完整个计划，中间不停。

Phase 25 之后，每完成一个模块（milestone），AAO 会停下来，把验收包摆在你面前：
做了什么、改了什么、测试怎样、reviewer 发现了什么、修了几轮。
你看完可以追问细节，然后 approve（继续）、reject（重做）、或 request-changes（修完再看）。

这就是真实软件项目的"模块交付验收"，AAO 现在也必须走这个流程。
```

## Claude Code Instruction

Read `CLAUDE.md` 和这个 spec。实现 Phase 25。
Milestone gate 是执行阻断器，不是建议。人等机器，不是机器等人。
不要实现 auto-approve。不要跳过 gate。
