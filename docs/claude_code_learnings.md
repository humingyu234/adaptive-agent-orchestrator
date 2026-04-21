# 从 Claude Code 这类系统值得学习的设计点

## 1. 这份文档记录什么

这份文档记录的不是“复刻 Claude Code”，而是：

- 从 Claude Code / 你朋友那种 AI 生态里，哪些设计点值得学习
- 哪些点应该进入 `adaptive-agent-orchestrator` 的长期路线
- 哪些点当前先记住，后面再做

这份文档的目标是帮助我们后续推进时不跑偏：

- 不追表层功能
- 抓真正有长期价值的设计能力

---

## 2. 我们不是要学什么

我们现在不做的事情：

- 不照着做一个“Claude Code 克隆版”
- 不追所有产品层功能
- 不试图一次性做完整生态

当前正确方向是：

- 学它背后的系统思路
- 然后长出自己的 runtime / eval / reliability 路线

---

## 3. 值得学习的 5 个核心设计点

## 3.1 仓库即上下文（Repo as Context）

值得学的点：

- 不把上下文只放在聊天线程里
- 让代码仓库、状态文件、任务文件、日志成为主要上下文来源

对应到我们项目里：

- `PROJECT_STATE.md`
- `PROJECT_LOG.md`
- `docs/decisions/`
- `StateCenter`
- 未来的长期记忆层

这条线的重要性：

- 它让系统从“短对话助手”变成“可持续工作的工程系统”

---

## 3.2 统一工具接入层（Plugin / Adapter Layer）

值得学的点：

- 不让上层 runtime 直接硬耦合某个具体工具
- 对 `codex / claude / kimi / API` 等能力做统一适配

对应到我们项目里：

- 长期应增加 `provider / plugin / adapter` 层

这层以后负责：

- 统一输入输出格式
- 屏蔽不同 provider 的调用差异
- 让 Worker / Supervisor 更专注角色，而不是专注工具细节

当前状态：

- 先记录方向
- 当前一周不做满

---

## 3.3 持续运行的任务流（Durable Runtime）

值得学的点：

- 系统不只是单轮完成一次任务
- 要能承载长任务、持续状态、阶段性恢复与迭代

对应到我们项目里：

- `Scheduler`
- `StateCenter`
- `execution_trace`
- `retry / fail / timed_out`
- 未来的 rollback / checkpoint / memory

这条线的重要性：

- 它是 runtime 和普通 prompt orchestration 的区别之一

---

## 3.4 中层总控代理（Supervisor Layer）

值得学的点：

- 人类保留最高权限
- 但日常总控动作可以逐步代理给 Supervisor Agent

包括：

- 拆任务
- 分角色
- 汇总结果
- 第一轮 review
- 建议下一步动作

对应到我们项目里：

- `Human -> Supervisor -> Worker Agents`

当前状态：

- 已经写进最终版设计
- 当前一周先不做满，但后续应尽快补骨架

---

## 3.5 反馈闭环与自观察（Feedback Loop）

值得学的点：

- 系统不只是执行
- 还会观察执行结果、记录失败模式、调整下一次行为

对应到我们项目里：

- `Evaluator`
- future evaluate system
- failure taxonomy
- compare / regression
- 长期记忆层

关键点：

- 当前不追求“自由自我进化”
- 而是做“带护栏的自我改进”

---

## 4. 对我们项目的具体启发

### 当前已经在做的

- `Scheduler`
- `StateCenter`
- `Evaluator(L1)`
- 项目状态文档
- 决策记录体系
- `Human -> Supervisor -> Worker` 设计方向

### 后面应该逐步补的

- `Supervisor Agent` 最简骨架
- provider / plugin / adapter 层
- 长期记忆层
- 更完整的执行审计
- 更强的 `Evaluator(L2/L3)`
- 反馈闭环和 compare 体系接入

---

## 5. 当前不该误判的点

### 5.1 不要以为“学 Claude Code”=“做一个终端聊天工具”
真正值得学的是：

- runtime
- state
- adapter
- memory
- supervisor
- feedback loop

### 5.2 不要因为它是成熟产品，就去复制所有表层功能
我们当前更适合长出的，是：

- runtime core
- evaluation
- reliability

### 5.3 不要把这条路线理解成“以后全靠 agent，不用人了”
正确方向是：

- Human 保留最高权限
- Agent 逐步代理更多中层调度工作

---

## 6. 后续执行原则

以后推进项目时，遇到“这个能力要不要做”，优先问：

1. 它是否能让系统更像 repo-as-context？
2. 它是否能让工具接入更标准化？
3. 它是否能增强 runtime 的持续执行能力？
4. 它是否能让 Supervisor 层更清楚？
5. 它是否能让反馈闭环更完整？

如果答案都是否定的，它大概率不是当前最值得优先做的东西。

---

## 7. 一句话总结

从 Claude Code 这类系统真正值得学习的，不是表面上的“终端里能做很多事”，而是：

- 仓库即上下文
- 统一插件 / adapter 层
- 持续运行的 runtime
- Supervisor 总控代理
- 反馈闭环与长期记忆

这些会构成 `adaptive-agent-orchestrator` 后续最重要的演化方向。
