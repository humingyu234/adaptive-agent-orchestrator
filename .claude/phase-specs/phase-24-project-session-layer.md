# Phase 24 - Project Session Layer

## Goal

把 AAO 从"单次任务执行器"升级成"项目会话系统"。
让 AAO 能记住跨任务的项目状态、在多次会话之间续跑、回答关于项目历史的问题。

```
之前:
  AAO 跑一个 task → 出 report → 忘掉一切

之后:
  AAO 创建 ProjectSession → 跑多个 milestone → 记录决策/证据
    → 关闭 session → 下次可以 resume → 可以问历史问题
```

## New Concepts

### ProjectSession

```python
class ProjectSession:
    project_id: str          # 唯一标识，跨重启不变
    goal: str                # 项目目标
    status: "active" | "paused" | "completed" | "abandoned"
    created_at: datetime
    last_active_at: datetime

    current_milestone: str | None
    completed_milestones: list[str]
    pending_decisions: list[str]  # 等待人工决策的事项
    open_risks: list[str]
    next_recommended_action: str | None
```

### ProjectMilestone

```python
class ProjectMilestone:
    milestone_id: str
    name: str
    description: str
    status: "pending" | "in_progress" | "completed" | "blocked"
    plan_step_ids: list[str]
    depends_on: list[str]  # milestone IDs
    approval_required: bool
    approved_by: str | None  # "human" or None
    approved_at: datetime | None
```

### DecisionLog

```python
class DecisionLog:
    entry_id: str
    timestamp: datetime
    decision: str            # 做了什么决定
    reason: str              # 为什么这样决定
    alternatives: list[str]  # 考虑过的其他方案
    made_by: str             # "control_plane" | "human" | "planning_council"
    evidence_refs: list[str] # 支撑这个决定的证据
```

### ProjectContext

```python
class ProjectContext:
    """Assembled at resume/ask time to answer questions."""
    goal: str
    current_milestone: ProjectMilestone | None
    completed_milestones: list[ProjectMilestone]
    recent_decisions: list[DecisionLog]  # last N
    important_design_choices: list[DecisionLog]
    open_risks: list[str]
    evidence_links: dict[str, str]  # milestone_id → evidence path
    audit_links: dict[str, str]     # milestone_id → audit path
```

### ProjectRunLink

```python
class ProjectRunLink:
    """Links a project milestone to a specific MainlineExecutor run."""
    milestone_id: str
    run_id: str
    evidence_path: str
    audit_path: str
    status: str
```

## CLI Commands

```
# 创建项目
python -m orchestrator project start "<goal>"

# 查看项目状态
python -m orchestrator project status

# 问项目相关问题
python -m orchestrator project ask "<question>"

# 继续当前项目
python -m orchestrator project continue

# 关闭项目
python -m orchestrator project close
```

### project start

```
python -m orchestrator project start "研究并重构 AAO memory 系统"

→ 创建 .aao/sessions/<project_id>/
→ 写入 session.json
→ 初始化 Planning Council 创建计划
→ 显示 plan 等待审批
```

### project status

```
python -m orchestrator project status

→ 显示:
  - 项目目标
  - 当前 milestone
  - 已完成 milestones
  - 待决策事项
  - 最近决策
  - 下一步建议
```

### project ask

```
python -m orchestrator project ask "为什么选择方案A而不是方案B？"

→ 查询 DecisionLog
→ 查询 EvidencePack
→ 查询 AuditReport
→ 查询 reviewer findings
→ 基于记录的上下文回答
→ 没有记录时明确说 "我没有关于这个的记录，建议查 X artifact"
```

回答必须基于：
- DecisionLog
- EvidencePack
- AuditReport
- worker outputs
- reviewer findings

不能基于：
- 模型自由猜测
- worker 自我总结（不信任，除非被 observed evidence 佐证）
- 没有记录在 session 中的上下文

### project continue

```
python -m orchestrator project continue

→ 加载 session
→ 找到 current_milestone
→ 恢复执行
→ 如果 milestone 处于 paused_for_approval，显示提醒
```

### project close

```
python -m orchestrator project close

→ 标记 session status = "completed"
→ 写入最终 audit summary
→ close 后不能 continue
```

## Storage

```
.aao/sessions/<project_id>/
  session.json           # ProjectSession 元数据
  milestones.json        # milestone 状态
  decision_log.jsonl     # 追加型决策日志
  run_links.jsonl        # milestone → run 映射
  project_context.json   # 快速 resume 所需的上下文快照
```

JSONL 用于追加型日志（一行一条记录，不重写）。JSON 用于可更新状态。

## Test Plan

```
test_project_start_creates_session
test_project_status_shows_current_milestone
test_project_ask_answers_based_on_decision_log
test_project_ask_says_unknown_when_no_record
test_project_continue_resumes_current_milestone
test_project_close_prevents_further_continue
test_session_survives_process_restart
test_decision_log_appended_not_overwritten
test_run_link_connects_milestone_to_evidence
```

## Definition Of Done

```
- project start 创建 session 并开始 planning
- project status 能显示当前项目阶段
- project ask 能基于 artifact 回答，不知道时明确说不知道
- project continue 能接上当前 milestone
- project close 后不能继续执行
- session 状态跨进程重启不丢失
- 所有回答来源可追溯（DecisionLog / EvidencePack / AuditReport / worker output）
```

## Required Final Explanation To User

```
Phase 24 之前，AAO 是金鱼记忆——每次任务都是全新的，关了窗口就忘了一切。

Phase 24 之后，AAO 有了项目会话。你创建一个项目，它记住目标、计划、
每个 milestone 做了什么、每个关键决策为什么这样选。你关掉电脑明天回来，
resume 一下，它知道做到哪了、下一步是什么。你问它"为什么这样设计？"
它能从决策日志和证据里回答，而不是瞎编。
```

## Claude Code Instruction

Read `CLAUDE.md` 和这个 spec。实现 Phase 24。
ProjectSession 是持久化层，不是新的控制机制。用文件存储，保持可审计。
ask 必须基于记录回答，不允许自由发挥。
