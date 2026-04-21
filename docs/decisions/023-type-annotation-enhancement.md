# 023 Type Annotation Enhancement

## 背景

项目中大量使用 `dict` / `dict[str, Any]` 作为类型注解：

```python
def run(self, context_view: dict) -> dict:
    ...

state.data_pool["intermediate"]["plan"]["sub_questions"]
```

## 问题

- 运行时容易因为 key 拼写错误崩溃
- 嵌套层级不对难以发现
- IDE 无法提供自动补全
- 没有类型保护

## 决策

### 新增 Pydantic Model

```python
class PlanOutput(BaseModel):
    sub_questions: list[str]
    plan_type: str = "research"
    confidence: float = 0.0

class SummaryOutput(BaseModel):
    conclusion: str
    sections: list[SummarySection] = []

class SupervisorReport(BaseModel):
    next_action: Literal["accept", "revise"]
    concerns: list[str] = []
    ...
```

### 新增 TypedDict

```python
class ContextView(TypedDict, total=False):
    query: str
    plan: dict[str, Any]
    raw_documents: list[dict[str, Any]]
    ...
```

### 重构 StateCenter

从字典改为对象：

```python
# 之前
state.metadata["task_id"]
state.data_pool["intermediate"]["plan"]
state.convergence["retry_counters"]

# 现在
state.metadata.task_id
state.data_pool.intermediate["plan"]
state.convergence.retry_counters
```

新增三个类：
- `StateMetadata` - 运行元数据
- `ConvergenceState` - 收敛状态
- `DataPool` - 数据池

## 为什么这样做

### 1. 类型安全

```python
# 之前：拼写错误不会被发现
state.data_pool["intermidiate"]["plan"]  # typo

# 现在：IDE 会提示错误
state.data_pool.intermidiate  # AttributeError
```

### 2. 自动补全

IDE 可以提供属性自动补全。

### 3. 文档化

类型定义本身就是文档。

### 4. 运行时验证

Pydantic Model 提供运行时验证。

## 影响

- 代码更健壮
- 开发体验更好
- 改动面较大，但测试全部通过
