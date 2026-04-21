# 020 Analyze CLI

## 背景

系统运行后会产生大量产物：
- `outputs/reports/*.json`：收敛报告
- `outputs/memory/*.json`：记忆包
- `outputs/states/*.json`：状态快照
- `outputs/checkpoints/`：检查点

但之前没有便捷的方式查看和分析这些历史数据。

## 问题

没有分析工具，会导致：

1. **调试困难**：想知道"最近一次运行为什么失败"需要手动打开 JSON 文件
2. **缺乏洞察**：无法快速回答"哪种失败最常见"、"哪个 agent 最慢"
3. **运维不便**：无法快速查看系统运行历史

## 决策

新增 `analyze` CLI 子命令，提供历史运行分析能力。

### 子命令

| 命令 | 功能 |
|------|------|
| `analyze list` | 列出最近运行 |
| `analyze show --task-id <id>` | 查看单个运行详情 |
| `analyze failures` | 统计失败类型分布 |
| `analyze agents` | 统计 agent 性能 |
| `analyze memory` | 查看 memory 索引摘要 |

### 输出格式

使用 ASCII 表格，易读且不需要额外依赖：

```
ID       | Workflow      | Query                  | Status    | Steps | Time
-------------------------------------------------------------------------------------------
e9882a60 | deep_research | test query for analyze | completed | 3     | 2026-04-16 03:17:53
```

### RunAnalyzer 类

提供编程接口，便于后续扩展：

```python
analyzer = RunAnalyzer(project_root)

# 列出最近运行
runs = analyzer.list_recent_runs(limit=10)

# 获取详情
detail = analyzer.get_run_detail(task_id)

# 统计失败
stats = analyzer.get_failure_statistics()

# 统计 agent 性能
perf = analyzer.get_agent_performance()

# memory 摘要
mem = analyzer.get_memory_summary()
```

## 为什么这样做

### 1. 把"打开 JSON 文件"变成"一条命令"

之前：
```bash
cat outputs/reports/xxx.json | jq .
```

现在：
```bash
py -m orchestrator analyze show --task-id xxx
```

### 2. 提供聚合视角

不只是"看单个运行"，还能：
- 统计失败类型分布
- 统计 agent 性能
- 查看 memory 索引

### 3. 为后续监控打基础

当前是 CLI 工具，后续可以：
- 接入 Web UI
- 接入监控系统
- 生成定期报告

## 当前边界

当前是最小版本：
- 只读分析，不修改数据
- 只支持表格输出，不支持图表
- 没有实时监控，只有历史分析

但这已经足够让开发者快速了解系统运行状态。

## 影响

- 调试更方便
- 运维更直观
- 为后续监控、可视化打基础
