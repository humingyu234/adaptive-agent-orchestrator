# 006 - 让 Supervisor 能区分普通修补和最小 re-plan

## 问题

当前系统已经支持：

- Supervisor 读取执行过程
- Supervisor 输出结构化建议
- Scheduler 响应建议并跳回已有节点

但还缺一个关键分界：

- 有些问题只是“补资料”或“重写总结”
- 有些问题已经说明规划本身不稳，需要重新规划

如果系统不能区分这两类问题，Supervisor 的建议层就不够成熟。

## 决策

在当前版本中引入最小 `re_plan` 信号：

- 当规划阶段缺少有效子问题
- 或规划阶段已经出现重试/失败评估

Supervisor 将输出：

- `suggested_target = planner`
- `suggested_action = re_plan`

同时让 Scheduler 在收到这个信号时：

- 跳回 `planner`
- 清掉旧的 `plan`
- 清掉依赖旧计划的 `raw_documents`
- 清掉 `summary`

## 取舍

为什么现在做这一步：

- 这是 Supervisor 从“修补型建议”升级到“最小重规划建议”的关键一步
- 这一步能明显增强项目的控制层层次感
- 实现成本仍然可控，适合当前阶段

为什么没有直接做完整 checkpoint / rollback：

- 完整重规划会牵涉 checkpoint、历史状态恢复、复杂分支控制
- 当前更适合先把“最小 re_plan 信号”跑通
- 先证明 Supervisor 能判断“该不该重新规划”，再往更复杂的 rollback 走，顺序更稳

## 当前边界

当前 `re_plan` 仍然是最小版：

- 只支持回到 `planner`
- 通过清理下游产物实现最小重规划
- 还不是完整 checkpoint rollback

## 后续演化

后续可以继续增强：

1. 把 `re_plan` 和 checkpoint 机制接起来
2. 让不同失败类型映射到不同的 Supervisor 建议
3. 让 Scheduler 支持更复杂的多步重规划

## 面试 / 博客表达

这一步可以这样讲：

> 在让 Supervisor 具备结构化建议能力之后，我进一步让它开始区分两类问题：普通修补和真正需要重新规划的问题。当前版本里，如果规划阶段本身不稳，Supervisor 会发出最小 `re_plan` 信号，Scheduler 会回到 planner 并清掉依赖旧计划的下游产物。这让我把“Supervisor 提建议”进一步推进到了“系统开始具备最小重规划能力”。
