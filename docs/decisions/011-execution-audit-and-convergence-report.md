# Execution Audit 与 ConvergenceReport 增强

## 这份记录是做什么的

这份记录沉淀的是 `adaptive-agent-orchestrator` 在 runtime 主干逐步变厚之后，对 execution audit 和 `ConvergenceReport` 做出的增强取舍：

- 为什么当前阶段必须把 report 从“几个计数”升级成“可复盘报告”
- 为什么这一步不是简单多加字段，而是把 runtime 行为讲清楚
- 为什么当前先从聚合现有产物入手，而不是直接做完整 Analyze CLI

---

## 1. 问题

在补完 checkpoint-backed replan、human review gate、MemoryManager v1 和第二个 workflow 之后，runtime 已经会发生很多关键控制行为：

- checkpoint 创建
- rollback
- supervisor guidance
- human review 停机
- memory 沉淀

但此前的 `ConvergenceReport` 还比较薄，只能告诉我们：

- 最终状态
- 执行步数
- checkpoint 数量
- retry counters

这对于最小 demo 够用，但对完整生态方向来说还不够，因为：

- 无法快速看出流程具体怎么走的
- 无法看出控制信号是怎么触发的
- 无法把 memory、log、checkpoint、state 这些产物统一串起来

---

## 2. 决策

当前把 `ConvergenceReport` 升级成更完整的 execution audit 入口，结构上增加：

- `timeline`
- `flow_summary`
- `control_summary`
- `quality_summary`
- `artifact_summary`
- `execution_audit`
- `memory_summary`

它现在会聚合：

- workflow 名称
- 每个 agent 的耗时
- evaluation action 分布
- failed evaluation reasons
- supervisor guidance 历史
- checkpoint replan 历史
- human review 状态
- state / memory / report / log / checkpoint 路径

---

## 3. 为什么这样取舍

### 为什么现在必须增强 report

因为 runtime 已经不只是“跑通 workflow”了，而是开始真正承担：

- 收敛控制
- 人工门
- 回滚
- 记忆沉淀

这时如果 report 还停留在最小计数层，就会出现一种情况：

- 系统做了很多事
- 但人和后续工具很难看清到底发生了什么

### 为什么先做聚合式 execution audit

因为当前系统已经有很多分散产物：

- logs
- state
- checkpoints
- memory
- execution trace

最自然的下一步不是先发明一个新大层，而是：

**先把这些已存在的产物聚合起来，形成统一复盘入口。**

这样做的好处是：

- 实现成本可控
- 直接服务当前调试与复盘
- 为后续 Analyze CLI 做准备

### 为什么顺手修 workflow loader 的 BOM 兼容

因为 report 增强后，我们开始更依赖 workflow 顶层元信息，例如：

- workflow name

如果 loader 在部分 UTF-8 BOM 文件上读不到顶层 `name`，report 就会缺少重要标识。

所以这次也一起修了 loader 的健壮性，让 runtime 和 report 对 workflow 文件更稳。

---

## 4. 当前实现边界

已经做到：

- 更完整的 runtime report
- human review / replan / memory 等行为都能进入 report
- workflow 名称稳定进入 runtime report

还没做到：

- 专门的 Analyze CLI
- 多次运行之间的自动对比
- regression compare
- failure taxonomy 的更深接入

所以当前更准确的定位是：

**execution audit 已经从“最小计数”升级到“可复盘报告”，但还没到完整分析平台。**

---

## 5. 后续演化

最自然的下一步是：

1. 设计 `ToolRegistry v1`
2. 扩 Memory，让 report 和 memory 之间产生更多可复用联动
3. 后续引入 `Analyze CLI`
4. 再往上长 `RegressionCompare` 和更完整的 failure taxonomy

---

## 6. 面试 / 博客表达

### 一句话版本

我们把运行报告从“简单状态计数”升级成了更完整的 execution audit，让 runtime 不只是会做 checkpoint、replan、human review 和 memory，还能把这些行为串成一份可复盘报告。

### 稍展开版本

一个真正的 runtime 内核，价值不只在于执行任务，还在于解释自己为什么这样执行、何时触发了控制信号、最后留下了哪些可追溯产物。这一步的重点，就是把 runtime 已经具备的 checkpoint、rollback、supervisor guidance、human review 和 memory 统一汇总成可读的 audit report，为后续分析工具和反馈闭环打基础。
