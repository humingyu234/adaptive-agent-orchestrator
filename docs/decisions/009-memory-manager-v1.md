# MemoryManager v1

## 这份记录是做什么的

这份记录沉淀的是 `adaptive-agent-orchestrator` 在 Phase 2A 之后继续往完整生态推进时，对 Memory 层做出的第一版实现取舍：

- 为什么现在要补 `MemoryManager v1`
- 为什么当前先做“运行结束后结构化沉淀 memory artifact”
- 为什么暂时不直接做复杂检索式长期记忆系统

---

## 1. 问题

在补完 checkpoint-backed replan 和 Human review gate 之后，runtime 已经开始具备：

- 可回滚
- 可暂停
- 可审计

但这时还缺一层很重要的能力：

**系统做完一次任务之后，没有正式“记住这次经历”的地方。**

如果没有 Memory 层，后续就会出现几个问题：

- 每次运行结束后，状态虽然可保存，但没有抽象成“值得复用的记忆”
- 后续想做 failure memory、经验回放、workflow 迁移时，会缺少统一入口
- Human review、ConvergenceReport、Future Eval System 很难和长期积累接起来

---

## 2. 决策

当前先补一个最小、但真正进入 runtime 的 `MemoryManager v1`：

- 在 runtime 收尾阶段自动执行
- 根据当前 `StateCenter` 生成 `memory_bundle`
- 把 memory 落盘到 `outputs/memory/<task_id>.json`
- 同时写回 state，作为当前运行结果的一部分

当前 memory 结构分成 5 块：

- `short_term`
- `long_term`
- `entity`
- `procedural`
- `failure_memory`

---

## 3. 为什么这样取舍

### 为什么现在就要补 Memory

因为 Memory 在完整生态 v2 里是正式一层，不是附属功能。

而且当前阶段正好已经具备了很适合接 Memory 的前提：

- state save/load
- checkpoint
- convergence report
- human review gate

这时补 Memory，属于顺着 runtime 主线自然往前长。

### 为什么先做“沉淀式 Memory”，而不是“检索式 Memory”

因为当前最需要解决的问题不是“模型怎么高效召回过去知识”，而是：

**runtime 先要有一个统一地方，把一次运行里值得记住的内容收起来。**

如果现在直接跳到：

- embedding
- retrieval
- ranking
- long-term memory search

会把项目重心过早拉向更复杂的信息检索系统，而当前 runtime 主线还没完全站稳。

### 为什么要把 failure memory 先放进来

因为这个项目的路线本来就很重视：

- evaluator
- failure taxonomy
- regression
- feedback loop

所以即使是 Memory v1，也应该从一开始就保留一块位置，专门记：

- 这次哪里失败了
- 最近的失败信号是什么
- 后面可以如何分析复发问题

---

## 4. 当前实现边界

已经做到：

- runtime 结束时自动生成 memory artifact
- memory 会进入 state 和磁盘产物
- 覆盖正常完成、需要人工审核、超时等多种结束状态

还没做到：

- memory 检索
- memory 注入下一次运行
- entity extraction 的更强语义抽取
- procedural memory 的策略级复用
- long-term memory 的跨任务索引

所以当前更准确的定位是：

**MemoryManager v1 是“先把记忆沉淀下来”，还不是“让系统主动取用记忆”。**

---

## 5. 后续演化

最自然的下一步是：

1. 让 memory 能被后续运行读取
2. 给 `failure_memory` 接更多 failure taxonomy 字段
3. 把 entity / procedural 做得更像真正可复用经验
4. 再考虑 retrieval、ranking 和更长期的 memory store

---

## 6. 面试 / 博客表达

### 一句话版本

我们没有把 Memory 直接做成一个复杂的向量检索系统，而是先让 runtime 在每次运行结束后自动沉淀结构化记忆，把短期结果、过程经验和失败信号统一收起来，为后续长期记忆和反馈闭环打基础。

### 稍展开版本

很多系统一提 Memory 就直接跳到“检索增强”，但对于一个运行时内核来说，第一步其实应该是先把“这次任务到底值得记住什么”沉淀清楚。我们这一步做的就是把 Memory 正式接进 runtime 收尾阶段，让系统先具备记忆产物，再逐步走向记忆复用。
