# 016 Declarative Evaluator Criteria

## 背景

当前 runtime 已经不再只有最初那几个固定 agent：

- workflow 已开始变多
- agent 契约也在变得更明确

如果 `Evaluator` 继续用：

- `if agent_name == "planner"`
- `if agent_name == "search"`

这种分支方式，后续每加一个 agent 或一类新 workflow，都要继续改 evaluator 源码。

## 问题

这种做法的问题不是"现在不能用"，而是：

1. 扩展一个 agent，要改核心分发逻辑
2. 规则本身和执行机制混在一起
3. 不利于后续走向更完整的 V2 评估配置

## 决策

### 第一阶段：声明式规则（已完成）

把当前 L1 评估收敛为声明式 criteria map。

每条规则可声明：

- `path`
- `expected_type`
- `min_items`
- `max_items`
- `allowed_values`
- `action`
- `reason`

### 第二阶段：下沉到 AgentConfig（已完成）

把 eval criteria 从 evaluator.py 移到每个 agent 的 config 里：

```python
class AgentConfig(BaseModel):
    name: str
    reads: list[str]
    writes: list[WriteSpec]
    tools: list[str] = []
    guardrails: list[str] = []
    eval_criteria: list[EvalCriteriaItem] = []  # 新增
    ...
```

每个 agent 自己声明产出格式约束：

```python
@register("planner")
class PlannerAgent(BaseAgent):
    config = AgentConfig(
        name="planner",
        ...
        eval_criteria=[
            EvalCriteriaItem(
                path="plan",
                expected_type="dict",
                action="retry",
                reason="planner 必须输出 plan 字段",
            ),
            EvalCriteriaItem(
                path="plan.sub_questions",
                expected_type="list",
                action="retry",
                reason="sub_questions 数量必须在 2 到 6 之间",
                min_items=2,
                max_items=6,
            ),
        ],
    )
```

Evaluator 不再按 agent 名查字典，而是直接接收 criteria 列表：

```python
# 之前
eval_result = evaluator.evaluate(agent_name, state, output)

# 现在
eval_result = evaluator.evaluate(agent.config.eval_criteria, output)
```

## 为什么这样做

### 1. 让"规则"从"执行器"里分离出来

新增 agent 不再需要修改 evaluator.py，只需在自己的 config 里声明 eval_criteria。

### 2. 与其他声明式特性一致

和已经做的：

- `tools` - agent 声明自己用的工具
- `guardrails` - agent 声明自己需要的护栏
- `trust_level` - agent 声明自己的信任级别
- `terminal_behavior` - agent 声明自己的终止行为

方向一致，都是"让 agent 自己声明自己的属性"。

### 3. 为后续扩展打基础

- 可以从外部配置文件加载 criteria
- 可以支持 L2/L3 评估
- 可以做 workflow-aware eval

## 影响

- Evaluator 可维护性提升
- 新 agent 的接入阻力下降
- 规则与 agent 紧密绑定，更易理解
