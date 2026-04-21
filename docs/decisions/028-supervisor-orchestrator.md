# 028 - SupervisorOrchestrator 总控编排器

## 背景

当前 SupervisorAgent 只是一个 review 节点，能读取执行过程并输出建议，但还不是真正的总控层。

完整生态设计里，Supervisor 应该是：
- 生态的大脑
- 先讨论，再决定怎么执行
- 动态决定下一步 agent
- 维护 TaskLedger（任务账本）
- 检测 stalled / no progress
- 必要时触发 re-plan

## 问题

当前 SupervisorAgent 存在以下局限：

1. 只是 workflow 里的一个节点，不是更高一层的主控
2. 只能输出建议，不能主动驱动调度
3. 没有维护任务账本，无法跟踪任务状态
4. 无法检测任务是否卡住

## 决策

实现 SupervisorOrchestrator - 真正的总控编排器。

### 核心设计

```python
@dataclass
class TaskLedger:
    """任务账本 - 跟踪所有任务状态"""
    query: str
    tasks: list[TaskItem]
    current_task_id: str | None
    iteration_count: int
    max_iterations: int

    def is_stalled(self) -> bool: ...
    def progress_summary(self) -> dict: ...
```

```python
@dataclass
class OrchestrationDecision:
    """编排决策"""
    action: str  # continue / re_plan / escalate / complete / fail
    next_agent: str | None
    reason: str
    task_updates: list[dict]
    context_updates: dict
```

```python
class SupervisorOrchestrator:
    """总控编排器"""
    
    def initialize(self, query: str) -> TaskLedger
    def decide_next_step(self, state, trace) -> OrchestrationDecision
    def handle_failure(self, agent, error, state) -> OrchestrationDecision
```

### 与 Scheduler 集成

```python
class Scheduler:
    def __init__(self, workflow, use_orchestrator=True):
        if use_orchestrator:
            self.orchestrator = SupervisorOrchestrator()
    
    def run(self, query):
        self.orchestrator.initialize(query)
        
        # 在每个 step 后获取编排决策
        decision = self.orchestrator.decide_next_step(state, trace)
        
        if decision.action == "re_plan":
            # 触发重规划
            ...
        if decision.action == "complete":
            # 完成
            ...
```

## 职责划分

| 层级 | 职责 |
|---|---|
| SupervisorOrchestrator | 维护任务账本、决定下一步、检测卡住、触发重规划 |
| SupervisorAgent | 读取执行过程、输出审查报告、提供结构化建议 |
| Scheduler | 执行调度、处理重试、管理状态 |

**关键区别**：
- SupervisorOrchestrator 是"调度大脑"，决定做什么
- SupervisorAgent 是"审查角色"，评估做得好不好

## 取舍

### 为什么不直接让 SupervisorAgent 承担总控

- SupervisorAgent 是 workflow 里的节点，职责边界更清晰
- SupervisorOrchestrator 是更高一层的主控，与 workflow 节点解耦
- 分开后可以独立演化、独立测试

### 为什么现在做

- 当前 Supervisor 基础版本已完成
- 下一步最自然的增强是让它成为真正的总控
- 对项目叙事价值很高

## 借鉴来源

| 框架 | 借鉴内容 |
|---|---|
| AutoGen MagenticOne | 任务账本（TaskLedger）设计 |
| CrewAI hierarchical | 总控角色与 Worker 角色的分层 |

## 后续演化

1. 让 SupervisorOrchestrator 支持动态 agent 分配
2. 接入长期记忆，形成更稳定的总控策略
3. 支持 multi-model 协调
4. 支持 plugin / provider 层

## 面试表达

> 我没有把 Supervisor 做成只是一个 workflow 节点，而是把它提升为 SupervisorOrchestrator - 真正的总控编排器。它维护任务账本，动态决定下一步，检测任务是否卡住，并能主动触发重规划。这样 Supervisor 不再只是"会提意见的角色"，而是能真正影响运行时行为的总控层。