# 021 Code Quality Improvements

## 背景

代码审查发现三个影响可维护性的问题：

1. **#3 BaseAgent class attribute 共享状态**：`tool_registry` / `guardrail_manager` / `llm_client` 是类属性，所有实例共享
2. **#6 FailureTaxonomy 字符串匹配不稳定**：`classify_failure()` 通过关键词猜失败类型
3. **#2 Scheduler 臃肿**：一个类 675 行，`_write_convergence_report` 占 220+ 行

## 问题

### #3 共享状态问题

```python
class BaseAgent:
    tool_registry: ToolRegistry = build_default_tool_registry()  # 类属性
```

影响：
- 多实例共享同一对象
- 并发执行时状态污染
- 测试时互相覆盖

### #6 字符串匹配问题

```python
if "重试" in reason or "retry" in reason.lower():
    return FailureRecord(category=FailureCategory.RETRY_EXHAUSTED, ...)
```

影响：
- 改文案会误分类
- 国际化困难
- 正常失败碰巧包含关键词也会误判

### #2 臃肿问题

Scheduler 承担了：
- 主循环调度
- Supervisor 指令解析
- checkpoint 创建/回滚
- convergence report 生成
- execution log 持久化

影响：
- 改一个功能可能误伤其他
- 难以测试
- 难以理解

## 决策

### #3 修复：实例属性 + 依赖注入

```python
class BaseAgent:
    def __init__(
        self,
        *,
        tool_registry: ToolRegistry | None = None,
        guardrail_manager: GuardrailManager | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._tool_registry = tool_registry or build_default_tool_registry()
        self._guardrail_manager = guardrail_manager or build_default_guardrail_manager()
        self._llm_client = llm_client or LLMClient()

    @property
    def tool_registry(self) -> ToolRegistry:
        return self._tool_registry
```

### #6 修复：显式传入 category

```python
# 失败源头显式指定 category
class GuardrailViolation(ValueError):
    def __init__(self, *, guardrail_name: str, stage: str, message: str,
                 failure_category: FailureCategory = FailureCategory.GUARDRAIL_BLOCKED):
        ...

# 推荐方式
create_failure_record(
    category=FailureCategory.GUARDRAIL_BLOCKED,
    agent_name="planner",
    reason="输入不能为空",
)

# Fallback 方式（保留向后兼容）
classify_failure(status="failed", reason="...", agent_name="planner")
```

### #2 修复：拆分模块

新增 `report_writer.py`：

```python
class ConvergenceReportWriter:
    def write(self, *, state: StateCenter, final_node: str | None,
              memory_path: Path, failure_record: FailureRecord | None = None) -> Path:
        ...
```

Scheduler 从 675 行减少到 443 行。

## 为什么这样做

### #3 实例属性

- 每个实例独立
- 支持依赖注入
- 方便测试 mock
- 为并发执行做准备

### #6 显式 category

- 失败源头最清楚失败类型
- 不依赖字符串匹配
- 更稳定、更可靠

### #2 拆分模块

- 单一职责
- 易于测试
- 易于理解
- 改 report 不影响调度

## 影响

- 代码更健壮
- 可维护性提升
- 为后续并发执行打基础
- 测试全部通过（33 个）
