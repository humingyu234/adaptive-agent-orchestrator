# Phase 26 - Project Resume and Interactive Ask

## Goal

让项目可以跨天续跑，并能在任何阶段回答用户的追问。
用户不只是被动审批，而是可以主动提问、理解、然后决定。

```
两个核心能力:

1. Resume: 关闭 Claude Code 后重新打开，AAO 能接上之前的项目状态
2. Interactive Ask: 用户可以在 milestone gate、review、或任何暂停点
   向 AAO 提问，AAO 基于记录回答
```

## Hard Rules

回答必须基于：
- DecisionLog
- EvidencePack
- AuditReport
- worker outputs
- reviewer findings
- session artifacts

不能基于：
- 模型自由猜测
- worker 自我总结（除非被 observed evidence 佐证）
- 没有记录在任何 artifact 中的上下文

当没有足够信息回答时，必须明确说：
"我没有关于这个的足够记录。建议查看 [具体 artifact 路径]。
 如果你想让我以后能回答这类问题，需要在 [具体 phase/step] 中记录 [具体信息]。"

## Resume Flow

```
用户: python -m orchestrator project continue
  （或 session resume --project-id <id>）

1. 加载 session.json
2. 加载 milestones.json
3. 加载 project_context.json
4. 显示恢复摘要:
   - 项目目标
   - 当前 milestone 和状态
   - 已完成 milestones
   - 上一个决策是什么、为什么
   - 待审批事项（如果有）
   - 下一步建议
5. 如果当前 milestone 是 paused_for_approval:
   - 显示验收摘要
   - 提醒用户 approve/reject/request-changes
6. 如果当前 milestone 是 in_progress:
   - 找到最后一个未完成的 step
   - 准备继续执行
```

## Ask Flow

```
用户: python -m orchestrator project ask "<question>"

1. 解析问题类型:
   - 关于设计决策:      查 DecisionLog
   - 关于执行结果:      查 EvidencePack + AuditReport
   - 关于 reviewer 发现: 查 reviewer findings
   - 关于 milestone 内容: 查 milestone summary + run links
   - 关于历史步骤:      查 task_log + worker outputs

2. 组装 ProjectContext:
   - 当前 milestone 状态
   - 最近 N 条 DecisionLog
   - 相关 evidence links
   - 相关 reviewer findings
   - 相关 worker outputs

3. 生成回答:
   - 引用具体 artifact 路径
   - 区分 "observed" vs "reported" 信息
   - 不知道时诚实说明
   - 如果需要的证据缺失，指出缺失了哪个 phase 的什么记录
```

### 可回答的问题类型

```
"为什么选择方案A而不是方案B？"
  → 查 DecisionLog.alternatives

"上一个 milestone 改了什么文件？"
  → 查 MilestoneApproval.files_changed + EvidencePack

"测试结果怎么样？"
  → 查 test output in evidence artifacts

"reviewer 发现了什么问题？"
  → 查 reviewer findings

"修了几轮才通过？"
  → 查 Phase 22 repair audit

"还有什么风险？"
  → 查 MilestoneApproval.open_risks + reviewer risk_flags

"下一步应该做什么？"
  → 查 session.next_recommended_action
```

### 不能回答的问题

如果用户问的问题没有对应的 artifact 记录，AAO 必须说不知道，例如：

```
用户: "worker 执行过程中有没有遇到什么奇怪的事情？"
AAO: "我没有关于运行时异常的足够记录。worker stdout 在
      .aao/tasks/run-001/step-001/worker/stdout.txt，
      但目前没有自动异常检测记录。
      如果你想让我以后能自动检测，需要在 Phase 27 中启用 self-issue detection。"
```

知道就说知道，不知道就说不知道加上怎么补。

## Test Plan

```
test_resume_after_process_restart_shows_correct_status
test_ask_about_design_decision_answers_from_decision_log
test_ask_about_execution_result_answers_from_evidence
test_ask_about_reviewer_findings_answers_from_review_report
test_ask_unknown_question_returns_honest_dont_know
test_ask_unknown_question_suggests_what_artifact_to_check
test_ask_does_not_launch_workers_or_modify_state
test_resume_continues_from_correct_milestone
test_resume_shows_pending_approval_when_gate_is_open
```

## Definition Of Done

```
- 关闭进程后重新启动仍能 project status
- project ask 能回答设计决策来源（DecisionLog）
- project ask 能回答执行结果来源（EvidencePack / worker output）
- project ask 不知道时必须说不知道，并指出缺少什么 evidence
- resume 后继续正确的 milestone
- resume 不重跑已完成的步骤
- 所有回答引用具体 artifact 路径
```

## Required Final Explanation To User

```
Phase 26 之前，AAO 是一次性的。跑完就完了。关了窗口，什么也没留下。

Phase 26 之后，AAO 是可以对话的项目协作者。你明天回来，resume 一下，
它告诉你做到了哪里。你问"为什么上次选方案A不用方案B？"
它查决策日志告诉你原因。你不知道的它可能知道（因为有记录），
它不知道的会告诉你去哪里自己看，以及怎么补上这个缺口。
```

## Claude Code Instruction

Read `CLAUDE.md` 和这个 spec。实现 Phase 26。
Resume 是状态恢复器，ask 是只读查询器。两者都不执行新任务、不改代码。
不知道就说不知道。永远引用 artifact 路径。
