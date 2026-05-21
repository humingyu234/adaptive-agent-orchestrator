# Phase 27 - AAO Self-Issue Handling

## Goal

识别 AAO 自身控制链路的问题，与普通任务问题分开处理。
AAO 绝对不能自动修改自己的核心代码。

## 区分两种 Issue

### TaskIssue（当前任务代码问题）

```
- 测试失败 → Phase 22 Auto Repair
- lint 报错 → Phase 22 Auto Repair
- evidence 缺失 → Phase 22 Auto Repair
- worker 产出不符合 spec → FixTask
```

这些是业务代码级别的问题，可以自动修（在 Phase 22 边界内）。

### SystemIssue（AAO 自身控制链路问题）

```
- MainlineExecutor 没消费 ControlDecision
- Reviewer 没隔离（尝试写入 worker 目录）
- Evidence 缺失但系统误判成功
- Human review resume 断链
- Worker bridge 没真正启动 worker
- ControlPlane 的决策在 scheduler 中被跳过
- Plan 和实际执行不一致（plan-reality drift）
- 同一 failure category 被不同步骤不同处理
```

这些是 AAO 自身的问题，绝不能自动修。

## SystemIssue 处理链路

```
1. Self-check 检测到 SystemIssue
2. 生成 SystemFinding
3. status = blocked_needs_review
4. 不生成普通 FixTask
5. 可选: 生成 SelfRepairProposal
6. 必须等用户批准 SelfRepairProposal
7. 用户批准前不执行任何修改
```

## Models

### SystemFinding

```python
class SystemFinding:
    finding_id: str
    category: str  # "control_chain_gap" | "isolation_violation"
                   # | "evidence_false_positive" | "resume_broken"
                   # | "worker_bridge_bypass" | "plan_reality_drift"
                   # | "decision_inconsistency"
    severity: "critical" | "high" | "medium"
    description: str
    evidence_refs: list[str]  # 证明这个系统问题的证据路径
    affected_components: list[str]  # 受影响的 AAO 组件
    detected_at: str  # 哪个阶段触发的
```

### SelfRepairProposal

```python
class SelfRepairProposal:
    proposal_id: str
    triggered_by: list[str]  # SystemFinding IDs
    summary: str             # 建议怎么修
    affected_files: list[str]          # AAO 源文件
    risks: list[str]                   # 修了可能引入什么问题
    test_plan: str                     # 修完之后怎么验证
    requires_human_approval: bool = True  # 永远 True
```

## Self-Check Triggers

```
自动触发:
- 每个 step 完成后: 检查 evidence 质量、isolation 边界
- 每个 milestone 完成后: 检查 plan-reality 对齐、decision 一致性
- 任何 replan 后: 检查 loop 风险

手动触发:
- python -m orchestrator self-check --project-id <id>
- python -m orchestrator self-check --project-id <id> --category control_chain_gap
```

## SelfRepairProposal 审批链路

```
1. SystemFinding 触发 → 可选生成 SelfRepairProposal
2. 提案展示给用户:
   - 问题是什么
   - 建议修哪几个文件
   - 修了有什么风险
   - 测试计划是什么
3. 用户操作:
   - approve → 允许执行修复（由用户或 AAO worker 执行）
   - reject → 记录原因，问题保持 open
   - 用户选择自己去修，不经过 AAO
4. 审批记录写入 DecisionLog
```

## 禁止事项

```
- 绝对不自动修改 src/orchestrator/*.py
- 绝对不自动修改 CLAUDE.md
- 绝对不自动修改 .claude/phase-specs/*.md
- 绝对不自动修改 .claude/project-skills/*.md
- 绝对不自动修改 policy YAML
- 绝对不自动修改 .env 或配置
- 绝对不自动修改 git 历史
```

这些是用户和开发者的领域。AAO 可以建议，绝不能执行。

## Test Plan

```
test_system_issue_not_auto_fixed
test_system_issue_enters_human_review
test_self_repair_proposal_includes_risks_and_test_plan
test_self_repair_proposal_not_executed_before_approval
test_task_issue_still_triggers_ordinary_fix_task
test_system_issue_detection_distinguishes_from_task_issue
test_self_check_command_outputs_structured_system_findings
test_proposal_to_modify_aao_source_is_blocked_at_generation
```

## Definition Of Done

```
- TaskIssue 和 SystemIssue 被明确区分
- SystemIssue 不自动修
- SystemIssue 进入 blocked_needs_review
- SelfRepairProposal 包含风险、影响文件、测试计划
- SelfRepairProposal 用户批准前不执行
- AAO 核心代码修改提案被阻止生成
- self-check CLI 可用
- 所有测试通过
```

## Required Final Explanation To User

```
Phase 27 之前，AAO 检查 worker 的输出，但不检查自己。如果 AAO 自己的
控制链路出了问题（比如 reviewer 没隔离、evidence 缺失但误判成功、
resume 后链路断了），没人会发现。

Phase 27 之后，AAO 有了自检能力。它能区分两种问题：
- TaskIssue（"测试挂了"）→ Phase 22 自动修
- SystemIssue（"reviewer 没隔离"）→ 停下来报告你

对于 SystemIssue，它可以出修复方案，但绝对不自己动手改 AAO 代码。
你是唯一的审批人。AAO 可以建议，但钥匙在你手里。
```

## Claude Code Instruction

Read `CLAUDE.md` 和这个 spec。实现 Phase 27。
关键区分：TaskIssue → 可修，SystemIssue → 只能报。
SelfRepairProposal 永远需要 human approval。
AAO 绝不自动修改自己的核心代码。这是硬约束，没有例外。
