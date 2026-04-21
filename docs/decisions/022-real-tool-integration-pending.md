# 022 Real Tool Integration (Pending)

## 背景

当前 `tool_registry.py` 只有一个 `mock_search_context`，返回模拟数据：

```python
def _mock_search_context(*, query: str, sub_questions: list[str], plan_type: str) -> list[dict]:
    documents.append({
        "snippet": f"围绕"{sub_question}"整理的模拟上下文材料...",
        ...
    })
```

## 问题

- SearchAgent 调的是假工具
- 整个 orchestrator 的"手脚"是残的
- 不能产生真实价值

## 解决方案

接入真实搜索 API，如：

1. **Serper** (Google Search API)
2. **Exa** (AI-native search)
3. **DuckDuckGo** (免费，无需 API key)

## 实现要点

- 环境变量读取 API key
- 网络错误处理
- 超时处理
- 限流处理
- 测试 mock

## 优先级

低。当前 mock 工具能支撑开发调试，不影响系统功能。

## 状态

Pending。等需要真实数据时再实现。
