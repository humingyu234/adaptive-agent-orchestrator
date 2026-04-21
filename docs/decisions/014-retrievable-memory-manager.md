# 可检索 / 可复用的 MemoryManager

## 这份记录是做什么的

这份记录沉淀的是 `adaptive-agent-orchestrator` 在 `MemoryManager v1` 之后，继续把 Memory 从“会沉淀”推进到“可检索 / 可复用”时做出的实现取舍：

- 为什么现在要让 memory 进入下一次运行
- 为什么当前先做 query-based retrieval，而不是直接上复杂向量检索
- 为什么先让 planner 使用 retrieved memories

---

## 1. 问题

在 `MemoryManager v1` 之后，系统已经能在每次运行结束时生成 memory artifact。

但这时还有一个明显问题：

**memory 只是被存下来了，还没有真正回流到下一次运行里。**

如果长期停留在这种状态，就会出现：

- 系统会“记”
- 但系统不会“用”

这对完整生态 v2 的 Memory 层来说是不够的。

---

## 2. 决策

当前先补一个最小但真实可用的 retrieval 闭环：

- MemoryManager 增加 memory index
- 每次 memory 生成后自动进入 index
- 新任务启动时，runtime 会按 query 检索相关历史 memory
- 检索结果写入 `retrieved_memories`
- `PlannerAgent` 开始读取 `retrieved_memories`
- plan 中会记录本次用了多少 `memory_hints`

这意味着：

**memory 不再只是产物，而是开始进入下一轮决策。**

---

## 3. 为什么这样取舍

### 为什么现在就要做 retrieval

因为如果不把 memory 拉回运行入口，它就只是“归档”，还不是“记忆系统”。

当前 runtime 已经有：

- checkpoint
- human review
- audit report
- ToolRegistry
- LLMClient

这时补最小 memory retrieval，正好能把 Memory 层真正接回主循环。

### 为什么先做 query-based retrieval

因为当前最重要的是：

**先让 retrieval 这条链路成立。**

而不是：

**先让 retrieval 非常高级。**

如果一上来就做 embedding、vector store、ranking，会让系统过早变复杂。  
当前更合理的策略是：

- 先建立 memory index
- 先按 query/token overlap 找到相关记忆
- 先让 planner 真正用起来

### 为什么先让 planner 使用 retrieved memories

因为 planner 是整个 runtime 的起点。

如果要验证 memory 是否开始“可复用”，最自然的地方就是：

- 先看看历史记忆能不能影响新的规划入口

这一步对后面扩到：

- supervisor
- summarizer
- future evaluators

都很自然。

---

## 4. 当前实现边界

已经做到：

- memory 自动进入统一索引
- runtime 启动时会自动检索相关历史 memory
- planner 能感知 memory hints 数量
- report 能看到 retrieved memory count

还没做到：

- 语义级检索
- vector retrieval
- memory ranking 策略
- procedural / entity memory 的更深复用
- human review / supervisor 对 memory 的更强利用

所以当前更准确的定位是：

**retrieval 闭环已经成立，但还属于最小 query-based retrieval。**

---

## 5. 后续演化

最自然的下一步是：

1. 收敛更多过渡实现到更声明式的 V2 方案
2. 明确 tool usage / guardrail 边界
3. 让 `LLMClient` 继续长成 provider-aware client
4. 后续再考虑更强的 memory ranking / retrieval

---

## 6. 面试 / 博客表达

### 一句话版本

我们没有让 Memory 停留在“会存档”的阶段，而是让 runtime 在新任务开始时先检索相关历史 memory，并把这些记忆真正喂给 planner，形成最小的记忆复用闭环。

### 稍展开版本

很多系统会说自己有 Memory，但实际上只是把结果存在磁盘里。我们这一步做的，是把 Memory 从“沉淀层”重新接回“运行入口”：系统会把历史 memory 建索引、按 query 做最小检索、把 retrieved memories 提供给 planner，并记录本次到底用了多少 memory hints。这样 Memory 才开始真正参与 runtime 决策。
