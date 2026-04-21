# 024 Agent CLI 命令与可插拔接口

## 背景

项目需要支持外部 CLI 工具（如 glm、codex、kimi）调用 orchestrator 的能力。

之前 orchestrator 只有两个命令：
- `run`：运行完整 workflow
- `analyze`：分析历史运行

缺少"单独调用某个 agent"的接口。

## 问题

- 外部 CLI 工具无法感知 orchestrator 的 agent 能力
- 没有轻量级 workflow 适合快速任务
- 无法列出可用的 agents

## 决策

### 1. 新增 `agent` 命令

```bash
orchestrator agent --name planner --query "Python async" --format json
```

- 直接调用单个 agent
- 支持 `json` 和 `text` 两种输出格式
- 错误时提示可用 agents

### 2. 新增 `agents` 命令

```bash
orchestrator agents           # 简洁列表
orchestrator agents --verbose # 详细信息
```

- 列出所有已注册的 agents
- 显示每个 agent 的 reads/writes/tools/trust_level

### 3. 新增轻量 workflow

```yaml
# workflows/quick_search.yaml
name: quick_search
description: 轻量搜索工作流，适合外部 CLI 调用
max_steps: 5

agents:
  - name: search
    next: summarizer

  - name: summarizer
    next: null
```

- 跳过 planner，直接搜索 + 总结
- 输出更友好，适合人类阅读

### 4. 修复 JSON 序列化

`run` 命令输出时，`state.metadata` 需要调用 `.to_dict()` 而不是直接序列化。

## 为什么这样做

### 1. 分层设计

| 命令 | 用途 | 输出 |
|------|------|------|
| `agent` | 调试、开发 | 原始 JSON |
| `run --workflow quick_search.yaml` | 快速任务 | 友好总结 |
| `run --workflow deep_research.yaml` | 完整研究 | 完整报告 |

### 2. 向后兼容

- 现有 workflow 不受影响
- 现有测试全部通过
- 新增功能不破坏现有接口

### 3. 可扩展

- 新增 agent 只需在 `@register` 装饰器注册
- `agents` 命令自动识别新 agent
- 外部 CLI 只需知道命令格式

## 影响

- 新增 2 个 CLI 命令
- 新增 1 个轻量 workflow
- 新增 3 个测试
- 修复 1 个 JSON 序列化 bug
- 测试从 33 个增加到 36 个
