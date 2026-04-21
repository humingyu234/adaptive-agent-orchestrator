# 015 Declarative Terminal Behavior

## 背景

`HumanReviewAgent` 已经让 runtime 具备了最小人工拍板门能力，但 Scheduler 之前是通过：

- `if agent_name == "human_review"`

来决定是否停在 `needs_human_review`。

这种写法在功能上可用，但它把“暂停语义”绑定到了某个具体 agent 名字上。

## 问题

这样会带来两个问题：

1. Scheduler 知道了过多业务细节
2. 以后如果再加别的暂停型节点，只能继续堆名字特判

这不符合当前项目从 runtime 骨架逐步走向完整生态 v2 的方向。

## 决策

在 `AgentConfig` 中新增：

- `terminal_behavior`

当前先支持：

- `continue`
- `pause_for_human`
- `fail`

然后让 agent 自己声明自己的终止行为。

`HumanReviewAgent` 改为：

- `terminal_behavior="pause_for_human"`

Scheduler 则只做统一规则执行：

- 读取 agent 的 `terminal_behavior`
- 如果是 `pause_for_human`，读取该 agent 的主写入字段
- 当其 `decision == "await_human"` 时，把 runtime 收尾为 `needs_human_review`

## 为什么这样做

### 1. 把暂停能力收进 agent 契约

这样“这个节点会不会让系统停下来”不再是 scheduler 猜的，而是 agent 自己声明的。

### 2. 为后续更多 gate / approval 节点留出扩展点

以后如果有：

- safety review
- compliance review
- release approval

这类节点，不需要再修改 scheduler 的名字判断分支。

### 3. 保持当前改动面可控

这次没有顺手把所有终止语义都做成一整套复杂状态机，而是只先把已经存在的一类真实需求抽象出来。

## 当前边界

当前 `terminal_behavior` 还是最小版本：

- 只真正用到了 `pause_for_human`
- payload 读取仍以“主写入字段”为约定

这已经足够把现有 `human_review` 逻辑从硬编码分支升级成声明式契约，但还不是完整终止状态机。

## 影响

- Scheduler 对具体 agent 名称的耦合下降
- `human_review` 的停机语义更接近完整生态 v2 里的声明式节点设计
- 后续收敛 `Evaluator`、`Guardrails`、更多 gate 节点时，会更容易继续沿着统一契约扩展
