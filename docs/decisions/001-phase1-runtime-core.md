# Phase 1 Runtime Core

## 这份记录是做什么的

这份记录沉淀的是 `adaptive-agent-orchestrator` 第一个真正落地的关键决策：

- 为什么 Phase 1 要先把 runtime core 做成最小闭环
- 为什么先做 `Evaluator(L1)`、`Scheduler` 收敛保护和 3 个最小 Worker Agents
- 为什么现在不先把完整 Supervisor / Memory / L2/L3 做满

---

## 1. 问题

项目早期最大的风险不是“想法不够大”，而是：

- 架构文档很多
- 设计层级很完整
- 但代码里没有真正可运行的 runtime

具体卡点包括：

- `Evaluator` 只是空壳，无法支撑 reliability 叙事
- `Scheduler` 没有 retry 上限保护，无法证明流程收敛
- 3 个 Worker Agents 虽然声明存在，但没有真正形成最小闭环
- 没有 CLI 和日志，就无法做端到端演示和后续调试

如果继续往上加概念层，而不先把 runtime 跑起来，项目很容易变成“设计很大、系统很空”。 

---

## 2. 决策

Phase 1 正式收敛成一个 `v1 final runtime core`，优先完成：

- `StateCenter`
- `Scheduler`
- `Evaluator(L1)`
- `PlannerAgent`
- `SearchAgent`
- `SummarizerAgent`
- 最简结构化日志
- CLI 入口

当前实现里，runtime 已经能够：

- 跑通 `deep_research` workflow
- 在运行时做 `L1` 规则检查
- 在评估失败时触发 retry
- 在超过重试上限时 fail
- 输出最简执行日志

---

## 3. 取舍

### 为什么先做 `L1`

因为 `L1`：

- 零 LLM 成本
- 最快能把运行时评估做成真的能力
- 最适合一周内做成可演示的闭环

### 为什么不先做 `L2 / L3`

因为 `L2 / L3` 会把项目直接拉向：

- embedding
- 语义相关性
- 一致性判断
- 幻觉检测

这在长期路线里很重要，但当前最优先的不是“评估很高级”，而是“评估真的参与调度闭环”。

### 为什么不先做完整 Supervisor / Memory

因为这些属于最终版生态层的一部分。

当前正确顺序是：

- 先把 runtime core 做实
- 再让 Supervisor / Memory / Feedback loop 长在一个真的能跑的系统上

这次牺牲的是“完整生态感”，换来的是“真正能工作的内核”。

---

## 4. 当前边界

当前实现还没有覆盖：

- `L2 / L3`
- 完整 `Supervisor Agent`
- 长期记忆系统
- checkpoint rollback
- 多模型路由
- 完整 feedback self-improvement loop

当前也没有接真实 LLM 调用，而是先用最小 stub 打通运行时闭环。

这不是否认这些能力重要，而是明确它们属于下一阶段。

---

## 5. 后续演化

下一步最自然的演化顺序是：

1. 强化 `Evaluator(L1)` 规则覆盖
2. 增加更完整的执行审计与收敛报告
3. 引入 `Supervisor Agent` 的最简代码骨架
4. 补第二个 workflow，验证抽象没有写死
5. 再进入 `L2 / L3` 与更完整 feedback loop

---

## 6. 面试 / 博客表达

### 一句话版本

我们没有先追求做一个“看起来完整的多 Agent 生态”，而是先把最核心的 runtime core 做成真的：让调度、状态、评估、重试和失败处理真正进入闭环。

### 稍展开版本

这个项目早期最大的风险是文档很强、实现很空，所以第一阶段我们有意识地把范围收成一个 `v1 final runtime core`。这样做不是降低标准，而是优先保证系统真的能跑通 workflow、真的能在运行时做质量判断、真的能在失败时收敛退出。等这一层站稳以后，再往上长 Supervisor、Memory 和更强的 Evaluator，系统会更健康。
