# 027 - Evaluator L2 语义级评估

## 背景

当前 Evaluator(L1) 只做结构验证（字段存在、类型正确、数量范围）。

但对于一些场景，需要更深入的语义评估：
- 内容是否足够充实（不只是有字段，还要有实质内容）
- 输出是否与输入/上下文一致
- 覆盖率是否达标（如子问题回答覆盖）

## 问题

如果只有 L1，系统只能检查"结构正确"，无法检查"内容质量"。

这会导致：
- 空内容可能通过评估
- 质量低下的输出可能被接受
- 缺乏更细粒度的质量控制

## 决策

引入 L2 语义级评估：

### 评估维度

- **completeness** - 完整性：输出是否包含必要信息
- **consistency** - 一致性：输出是否与输入/上下文一致
- **relevance** - 相关性：输出是否与任务相关
- **quality** - 质量：输出内容的质量评分

### 检查类型

- `min_length` - 最小长度
- `min_items` - 最小数量
- `has_keywords` - 关键词检查
- `field_match` - 字段匹配
- `not_empty` - 非空检查
- `score_threshold` - 分数阈值
- `coverage` - 覆盖率检查

### 实现方式

```python
@dataclass
class L2Criterion:
    dimension: str  # completeness / consistency / relevance / quality
    check_type: str  # min_length / has_keywords / ...
    params: dict[str, Any]  # 规则参数
    weight: float = 1.0  # 权重
    action_on_fail: str = "warn"  # warn / retry / fail
    reason: str = ""
```

### 与 L1 串联

Evaluator 现在支持多层评估：
1. L1 结构验证（必须通过）
2. L2 语义评估（可选）

```python
eval_result = evaluator.evaluate(
    criteria=l1_criteria,
    output=output,
    context=context,
    l2_criteria=l2_criteria,
)
```

## 取舍

为什么这样设计：

- L1 和 L2 分离，避免混淆
- L2 可选，不影响现有行为
- 加权评分，支持多维度综合判断
- 预定义规则，方便 agent 直接使用

为什么不直接做 L3：

- L3 需要更复杂的评估逻辑（如 LLM-as-judge）
- 当前阶段先做好 L2，为后续扩展打基础

## 影响

- Evaluator 能做更细粒度的质量控制
- Agent 可以声明自己的 L2 规则
- 为后续更高级评估打基础