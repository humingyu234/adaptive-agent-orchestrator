# 004 - 让 Supervisor 输出结构化修正建议

## 问题

当前 `SupervisorAgent` 已经能读取执行过程，但输出仍然偏“描述型”：

- 能说任务是否可接受
- 能列出关注点

但还不能明确回答下面这些更关键的问题：

- 为什么要 revise
- 建议回到哪一层处理
- 下一步更适合做什么动作

如果没有这一层结构化建议，`Supervisor` 更像一个会点评的角色，而不像一个能指导系统继续往前走的总控层。

## 决策

在 `supervisor_report` 中新增三个结构化字段：

- `review_reason`
- `suggested_target`
- `suggested_action`

当前版本的最小映射规则：

- 缺少任务拆解
  - `suggested_target = planner`
  - `suggested_action = revise_plan`
- 缺少资料支撑
  - `suggested_target = search`
  - `suggested_action = gather_more_evidence`
- 总结为空
  - `suggested_target = summarizer`
  - `suggested_action = rewrite_summary`
- 仅存在过程风险但最终结果可用
  - `suggested_target = supervisor`
  - `suggested_action = review_process`

如果没有明显问题：

- `suggested_target = none`
- `suggested_action = accept`

## 取舍

为什么现在就做这一步：

- `Supervisor` 已经能看过程，下一步最自然的增强就是“把判断变成结构化建议”
- 这一步能明显提高项目的可解释性和后续扩展性
- 后面要做更复杂的 supervisor-driven flow 或 re-plan，这些字段都能直接复用

为什么没有现在就让 `Supervisor` 直接改写 workflow：

- 当前阶段更适合先输出建议，而不是立即赋予执行层面的重写权限
- 先让建议格式稳定，再决定哪些建议需要真的进入调度路径
- 这样更容易测试，也更容易在面试和博客中讲清楚系统演化顺序

## 当前边界

当前 `Supervisor` 的结构化建议还是规则驱动的：

- 基于 plan / raw_documents / summary / execution_trace 做判断
- 还没有结合长期记忆
- 还没有做更复杂的多因素打分
- 还不会自动触发真正的 re-plan

## 后续演化

后续可以继续增强：

1. 让 `Supervisor` 根据失败模式输出更细的建议
2. 把 `suggested_target` / `suggested_action` 接入 Scheduler 的后续控制逻辑
3. 接入长期记忆，形成更稳定的总控策略

## 面试 / 博客表达

这一步可以这样讲：

> 我没有让 Supervisor 停留在“做一个最终 review 节点”的层面，而是让它开始输出结构化修正建议。这样它不仅能判断任务是否可接受，还能明确指出问题原因、建议回到哪一层处理，以及下一步更适合采取什么动作。这为后面把 Supervisor 真正接进 runtime 控制路径打下了接口基础。
