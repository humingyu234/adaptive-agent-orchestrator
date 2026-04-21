# 019 Failure Taxonomy

## 背景

之前系统在失败时只是简单记录 `status=failed` 和 `reason=...`，没有对失败类型进行分类。

这意味着：
- 无法区分"可重试的失败"和"需要人工介入的失败"
- 无法统计"哪种失败最常见"
- 无法根据失败类型采取不同的恢复策略

## 问题

没有统一的失败分类体系，会导致：

1. **调试困难**：看到一堆 failed 状态，但不知道是格式问题还是权限问题
2. **无法自动恢复**：所有失败都被同等对待，无法针对不同类型采取不同策略
3. **缺乏可观测性**：无法回答"系统最近一周最常遇到什么问题"

## 决策

新增 `FailureTaxonomy` 模块，提供统一的失败分类体系。

### FailureCategory

定义 20+ 种失败类型，覆盖：

| 类别 | 具体类型 |
|------|----------|
| 格式相关 | format_error, missing_field, invalid_type |
| 内容相关 | insufficient_content, empty_output, quality_below_threshold |
| 评估相关 | evaluation_failed, retry_exhausted |
| 安全相关 | guardrail_blocked, permission_denied, trust_level_insufficient |
| 执行相关 | timeout, max_steps_exceeded, agent_error |
| 控制相关 | supervisor_rejected, replan_failed, checkpoint_restore_failed |
| 外部相关 | tool_error, llm_error, external_service_error |
| 未知 | unknown |

### FailureSeverity

定义 4 级严重程度：

| 级别 | 含义 | 典型场景 |
|------|------|----------|
| low | 可以重试 | format_error, missing_field |
| medium | 需要调整策略 | timeout, evaluation_failed |
| high | 需要人工介入 | guardrail_blocked, agent_error |
| critical | 系统级问题 | external_service_error |

### classify_failure()

根据运行时信息自动分类：

```python
def classify_failure(
    *,
    status: str,           # failed, timed_out, guardrail_blocked
    reason: str,           # 失败原因文本
    agent_name: str | None,
    event_type: str | None,  # 从 execution_trace 获取
    eval_action: str | None, # retry, fail
) -> FailureRecord:
```

### 集成点

1. `Scheduler._finalize_run()` 在失败时自动分类
2. 分类结果写入 `execution_trace`
3. `ConvergenceReport` 汇总 `failure_summary`

## 为什么这样做

### 1. 把"发生了什么"变成"是什么类型的问题"

之前：
```json
{"status": "failed", "reason": "重试次数耗尽"}
```

现在：
```json
{
  "status": "failed",
  "reason": "重试次数耗尽",
  "failure_category": "retry_exhausted",
  "failure_severity": "medium"
}
```

### 2. 为后续自动恢复打基础

有了分类，后续可以：
- `retry_exhausted` → 自动降级
- `timeout` → 调整超时参数重试
- `guardrail_blocked` → 需要人工审批

### 3. 提升可观测性

可以回答：
- "最近一周最常遇到什么失败？"
- "哪些 agent 最容易出问题？"
- "系统稳定性趋势如何？"

## 当前边界

当前是最小版本：
- 只做分类，不做自动恢复
- 只在 `_finalize_run` 分类，不在运行时实时分类
- 严重程度是静态映射，还未支持动态调整

但这已经足够让系统具备"失败类型感知"能力。

## 影响

- 失败处理更精细
- 调试更容易
- 为后续自动恢复、智能降级打基础
