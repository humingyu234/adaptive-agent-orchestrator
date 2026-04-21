# 026 真实工具接入

## 背景

项目之前只有 `mock_search_context` 工具，返回假数据。系统无法真正完成任务。

## 问题

- 无法进行真实搜索
- 无法验证整个流程在真实数据下的表现
- 用户无法获得有用的结果

## 决策

### 1. 新增 `real_tools.py`

提供真实搜索能力：

```python
# DuckDuckGo（免费，无需 API Key）
web_search_duckduckgo(query, top_k=5)

# Tavily（专为 AI Agent 设计，需要 API Key）
web_search_tavily(query, top_k=5)

# Serper（Google 搜索 API，需要 API Key）
web_search_serper(query, top_k=5)
```

### 2. 扩展 `ToolRegistry`

```python
# 构建真实工具注册表
registry = build_real_tool_registry()

# 根据环境变量自动注册可用工具
# DuckDuckGo 总是可用
# Tavily 需要 TAVILY_API_KEY
# Serper 需要 SERPER_API_KEY
```

### 3. 新增 `RealSearchAgent`

```python
@register("real_search")
class RealSearchAgent(BaseAgent):
    config = AgentConfig(
        tools=["web_search", "duckduckgo"],
        ...
    )
```

### 4. 更新 `BaseAgent`

新增 `use_real_tools` 参数：

```python
agent = BaseAgent(use_real_tools=True)
```

## 为什么这样做

### 1. 分层设计

```
Agent
  ↓ 调用
ToolRegistry
  ↓ 选择
真实工具 / Mock 工具
```

### 2. 向后兼容

- 默认使用 mock 工具
- 测试不需要外部依赖
- 用户可以选择启用真实工具

### 3. 自动降级

如果真实搜索失败，自动 fallback 到 mock。

## 使用方式

### 环境变量

```bash
# Tavily（可选）
export TAVILY_API_KEY=your_key

# Serper（可选）
export SERPER_API_KEY=your_key
```

### 代码

```python
# 使用真实搜索
from orchestrator.real_tools import web_search_duckduckgo_sync

results = web_search_duckduckgo_sync("Python async", top_k=5)
```

### CLI

```bash
# 使用真实搜索 agent
orchestrator agent --name real_search --query "Python async"
```

## 依赖

```toml
[project.optional-dependencies]
search = ["ddgs>=6.0", "httpx>=0.25"]
```

安装：
```bash
pip install "adaptive-agent-orchestrator[search]"
```

## 影响

- 新增 `real_tools.py`（~150 行）
- 修改 `tool_registry.py`（+50 行）
- 修改 `search_agent.py`（+50 行）
- 修改 `base.py`（+use_real_tools 参数）
- 更新 `pyproject.toml`（+可选依赖）
