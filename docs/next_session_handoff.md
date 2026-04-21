# 下一对话框衔接文档

> 目的：让下一个对话框、新协作者或未来的自己，可以**不靠聊天上下文**，直接接上当前项目主线。

---

## 1. 当前在做什么项目

当前主要推进的项目是：

- `C:\Users\Administrator\Desktop\adaptive-agent-orchestrator`

它现在不再只按“多 Agent 编排器”理解，而是正式朝：

**多智能体生态运行时内核**

这个方向推进。

最准确的描述是：

- `agent orchestration runtime`
- `agent infra`
- `multi-agent ecosystem runtime core`

它不是某一个具体业务 Agent，而是负责：

- 组织多个角色协作
- 维护共享状态
- 在运行时做评估
- 接收 Supervisor 建议
- 响应 retry / fail / 最小 re_plan
- 未来承接 memory / tools / feedback / HITL

---

## 2. 旧项目的关系

另一个相关项目是：

- `C:\Users\Administrator\Desktop\deep_research_agent`

这个旧项目的重要价值是：

- 提供真实 workflow 资产
- 提供 evaluate 资产来源
- future evaluate system 会从这里逐步抽出来

所以现在的整体关系是：

- `deep_research_agent`：应用与评估资产来源
- `adaptive-agent-orchestrator`：运行时与生态内核
- future evaluate system：独立评估层

---

## 3. 当前完整设计基线

### 当前正式目标

项目现在已经切换到这版完整生态蓝图：

- `docs/ecosystem_architecture_v2.md`

这是当前最完整、最明确的设计基线。

### 这版蓝图的核心是 8 层

1. `Human Interface`
2. `Supervisor Orchestrator`
3. `Runtime Core`
4. `Worker Agents + Guardrails`
5. `Tool Registry`
6. `Shared Context`
7. `Memory`
8. `Feedback Loop + Eval System`

最白的话：

- 人类保留最高权限
- Supervisor 负责讨论、调度、重规划
- Runtime 负责状态、评估、收敛
- Worker 真正干活
- Tool / Context / Memory / Feedback 支撑整个生态长期协作

---

## 4. 当前已经做到什么程度

### 4.1 已有核心模块

- `Scheduler`
- `StateCenter`
- `Evaluator(L1)`
- `PlannerAgent`
- `SearchAgent`
- `SummarizerAgent`
- `SupervisorAgent`
- CLI 入口
- execution logs
- smoke tests

### 4.2 当前 workflow

现有 workflow：

- `workflows/deep_research.yaml`
- `workflows/deep_research_supervised.yaml`

普通版：

```text
planner -> search -> summarizer
```

带总控版：

```text
planner -> search -> summarizer -> supervisor
```

### 4.3 当前运行时已经具备的能力

#### Evaluator

`Evaluator(L1)` 已经是真实工作的，不再是空壳。

当前会检查：

- planner 输出是否有有效 `sub_questions`
- search 是否找到至少一条 `raw_documents`
- summarizer 是否写出非空 `conclusion`
- supervisor 是否输出有效 `supervisor_report`

#### Supervisor

`SupervisorAgent` 现在已经不只是一个“最后 review 一下”的占位角色。

它已经能：

- 读取执行过程
- 读取重试次数
- 读取状态
- 输出 `supervisor_report`
- 输出结构化建议：
  - `review_reason`
  - `suggested_target`
  - `suggested_action`

#### Scheduler

`Scheduler` 已开始响应 supervisor 建议。

当前已经支持：

- 按建议回到已有节点重新执行
- 区分最小 revise 和最小 re_plan

#### 最小 re_plan

这是当前很关键的一步。

如果 `Supervisor` 认为问题不是“小修补”，而是“规划本身不稳”，当前系统已经能：

- 发出 `suggested_target = planner`
- 发出 `suggested_action = re_plan`
- `Scheduler` 跳回 `planner`
- 清理依赖旧规划的下游状态：
  - `plan`
  - `raw_documents`
  - `summary`

也就是说：

系统已经有了**最小重规划信号**。

### 4.4 测试状态

当前测试全部通过：

- `6` 个测试
- `OK`

已验证：

- 普通 workflow 可跑通
- supervised workflow 可跑通
- supervisor 可给 revise 建议
- scheduler 可响应 supervisor guidance
- supervisor 可发出最小 `re_plan`
- scheduler 可清理旧规划的下游状态

---

## 5. 当前还没做满的地方

当前项目已经明显不只是骨架，但也还没到完整生态完全体。

还没做满的主要是：

- `Human review gate`
- `StateCenter save/load`
- `CheckpointStore`
- checkpoint-backed replan
- `ConvergenceReport`
- `MemoryManager`
- `Evaluator(L2 / L3)`
- `Guardrails`
- `ToolRegistry`
- `LLMClient`
- 第二个 workflow
- `TrustHierarchy`
- `SafetyGuard`

所以当前最准确的定位是：

**已经有了很强的 runtime core + 最小 supervisor control loop + 最小 re_plan 信号。**

---

## 6. 当前最关键的代码文件

### Runtime Core

- `src/orchestrator/state_center.py`
- `src/orchestrator/evaluator.py`
- `src/orchestrator/scheduler.py`
- `src/orchestrator/registry.py`
- `src/orchestrator/workflow.py`
- `src/orchestrator/__main__.py`

### Agents

- `src/orchestrator/agents/planner_agent.py`
- `src/orchestrator/agents/search_agent.py`
- `src/orchestrator/agents/summarizer_agent.py`
- `src/orchestrator/agents/supervisor_agent.py`

### Workflow

- `workflows/deep_research.yaml`
- `workflows/deep_research_supervised.yaml`

### Tests

- `tests/test_runtime_smoke.py`

---

## 7. 最值得先看的文档

推荐阅读顺序：

1. `README.md`
2. `PROJECT_STATE.md`
3. `docs/architecture.md`
4. `docs/ecosystem_architecture_v2.md`
5. `docs/project_relationships.md`
6. `docs/project_relationships.md`
7. `docs/workflow_evolution.md`
8. `docs/claude_code_learnings.md`

如果时间有限，至少先看：

- `README.md`
- `PROJECT_STATE.md`
- `docs/ecosystem_architecture_v2.md`

---

## 8. 最值得先看的决策记录

这些文件能帮助新对话框快速理解：项目不是随便长出来的，而是一步步做取舍长出来的。

- `docs/decisions/001-phase1-runtime-core.md`
- `docs/decisions/002-supervisor-layer.md`
- `docs/decisions/003-supervisor-process-awareness.md`
- `docs/decisions/004-supervisor-structured-guidance.md`
- `docs/decisions/005-supervisor-guidance-routing.md`
- `docs/decisions/006-minimal-replan-signal.md`

用户非常重视：

- 为什么这么做
- 为什么不选别的方案
- 当前边界是什么
- 后面怎么扩

所以每次重要推进都需要继续写决策记录。

---

## 9. 当前最推荐的下一步

在新的生态 v2 基线下，当前最值得继续做的是：

### 第一优先级

**把最小 `re_plan` 和 `checkpoint / save-load` 真正接起来。**

原因：

- 当前已经有最小 `re_plan` 信号
- 当前 `StateCenter` 已有基础 checkpoint 能力
- 现在最自然的升级，就是把“回到 planner 重来”变成“有依据地回滚再重规划”

### 第二优先级

补：

- `ConvergenceReport`
- execution audit 增强

### 第三优先级

再往生态层补：

- `Human review gate`
- `MemoryManager v1`

---

## 10. 和用户的合作协议

这个非常重要，新对话框必须遵守。

### 语言

- 全程中文

### 风格

- 像“超级导师 + CTO”
- 温和、支持、但真实
- 不要高高在上
- 不要太生硬
- 不要只会列模板

### 解释方式

用户非常喜欢：

- 直观解释
- 白话解释
- 比喻解释

常用比喻：

- Worker = 工人
- Scheduler = 工头
- StateCenter = 共享白板
- Evaluator = 老师 / 质检员
- Supervisor = 小主管

### 深度要求

用户不是只想听“做了什么”，还想听：

- 为什么这么做
- 为什么不选别的方案
- 这样做的好处
- 当前边界是什么
- 面试和博客时怎么讲

但也不要过度啰嗦。

正确方式是：

- 抓核心
- 讲清楚最重要的变化
- 让用户能逐步掌控每一步

### 工作习惯

每次重要推进都要同步沉淀：

- `PROJECT_LOG.md`
- `PROJECT_STATE.md`
- `docs/decisions/*.md`

因为用户明确要把这个项目变成：

- 技术博客素材
- 求职展示素材
- 面试讲解素材

所以项目的交付物不只是代码，还包括：

- 设计
- 取舍
- 演化过程
- 面试表达材料

---

## 11. 新对话框最适合的开场方式

建议下一个对话框这样接：

> 我已经接上你现在的主线了。当前项目已经不只是“多 Agent 编排器”，而是在按生态 v2 方向推进。现在系统已经有 Worker、Evaluator、Supervisor 控制闭环和最小 re_plan 信号。下一步最顺的是把最小 re_plan 和 checkpoint / save-load 真正接起来，让系统从“回到 planner 重来”升级成“有依据地回滚再重规划”。我们就沿着这条线继续。

---

## 12. 一句话总结

当前项目已经不是概念架构，而是：

**一个已经跑通 Worker + Evaluator + Supervisor + 最小控制闭环 + 最小重规划信号的多智能体生态运行时内核。**

下一步最值得继续做的是：

**checkpoint-backed replan。**
