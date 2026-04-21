# 005 - 让 Scheduler 开始响应 Supervisor 建议

## 问题

当前 `SupervisorAgent` 已经能输出结构化建议：

- `review_reason`
- `suggested_target`
- `suggested_action`

但如果 `Scheduler` 完全不理这些建议，那 `Supervisor` 仍然只是一个“会提意见的角色”，而不是能影响运行时行为的总控层。

## 决策

在当前版本中，让 `Scheduler` 开始支持最小 Supervisor 建议路由：

- 当 `supervisor_report.next_action == revise`
- 且 `suggested_target` 指向一个有效 worker 节点
- Scheduler 将跳回对应节点重新执行

同时加入最小保护：

- 使用 `max_supervisor_revisions`
- 防止 supervisor 驱动的修正回路无限循环

## 取舍

为什么现在做这一步：

- `Supervisor` 已经能理解过程并输出建议，下一步最自然的增强就是让系统开始响应这些建议
- 这一步能让项目从“有 Supervisor 层”升级为“Supervisor 开始进入控制路径”
- 对项目叙事价值很高，而且实现成本可控

为什么没有直接做复杂 re-plan：

- 当前阶段更适合先做“跳回已有节点”这种简单、可解释的控制路径
- 复杂 re-plan 涉及 checkpoint、rollback、动态图改写，问题面会迅速变大
- 先把简单修正回路打通，后面再往更复杂的 runtime control 扩，顺序更稳

## 当前边界

当前版本只支持：

- Supervisor 建议回到现有节点
- 简单 revision 上限保护

还不支持：

- 自动生成新 workflow
- 真正的 checkpoint rollback
- Supervisor 驱动的复杂多跳重规划

## 后续演化

下一步可以继续增强：

1. 让 `Supervisor` 的不同建议映射到更明确的调度策略
2. 把失败类型和 Supervisor 建议接起来
3. 再往后接入 checkpoint / re-plan / 更复杂的 runtime control

## 面试 / 博客表达

这一步可以这样讲：

> 我先让 Supervisor 具备结构化建议能力，然后没有直接跳到复杂 re-plan，而是先让 Scheduler 支持最小建议路由：当 Supervisor 认为需要修正时，系统可以回到已有节点重新执行。这让 Supervisor 第一次真正进入控制路径，而不仅仅是一个 review 角色。
