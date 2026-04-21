# 017 Guardrails v1

## 背景

当前 runtime 已经具备：

- 可插拔 agent
- 可插拔 workflow
- ToolRegistry
- LLMClient
- Memory
- Human review gate

但在 Worker 执行层，之前还缺少一层真正工作的护栏。

也就是说，agent 虽然能跑、能评估、能回滚，但还没有：

- 执行前的输入边界
- 执行后的输出边界

## 问题

如果没有 guardrails，runtime 会出现一个缺口：

1. agent 接到明显异常输入时，仍会继续执行
2. agent 输出明显不该暴露的内容时，没有统一拦截层
3. safety 边界只能靠 evaluator 或人工 review 兜底

这不符合完整生态 v2 里：

- `Worker Agents + Guardrails`

这一层的设计目标。

## 决策

新增：

- `GuardrailManager`
- `GuardrailSpec`
- `GuardrailViolation`

并让 `AgentConfig` 支持声明：

- `guardrails`

当前 runtime 会在两个时机执行护栏：

1. agent 执行前：`input guardrail`
2. agent 执行后：`output guardrail`

当前默认提供两条最小可工作护栏：

- `require_non_empty_query`
- `block_sensitive_output_terms`

## 为什么这样做

### 1. 先把护栏做成 runtime 真实能力

这次不是只在文档里写“后面要有 safety”，而是先把最小护栏链路接进真正的执行闭环。

### 2. 保持与 agent 契约一致

guardrails 和：

- tools
- model_profile
- terminal_behavior

一样，属于 agent 自己声明的能力边界。

### 3. 失败语义保持明确

护栏触发后，当前策略不是重试，而是：

- 记录 `guardrail_violation`
- 明确失败

因为这类问题更接近 safety / policy boundary，而不是普通质量不稳。

## 当前边界

当前 `Guardrails v1` 还是最小实现：

- 只覆盖 agent 输入/输出
- 还没有细化到 tool-level permission policy
- 还没有引入更丰富的 safety taxonomy

但这已经足够把“护栏”从概念变成 runtime 真正工作的层。

## 影响

- Worker 层更接近完整生态 v2
- 安全边界不再只靠 evaluator 兜底
- 后续继续做：
  - tool permission
  - safety review
  - trust hierarchy

会更自然
