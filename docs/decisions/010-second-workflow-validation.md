# 第二个 Workflow 通用性验证

## 这份记录是做什么的

这份记录沉淀的是 `adaptive-agent-orchestrator` 在完成 Phase 2A 主干之后，对“runtime 是否写死在 research 场景”做出的第一次正式验证：

- 为什么必须补第二个 workflow
- 为什么这一步不只是“多加一个 yaml”
- 为什么当前选择 service/content 风格任务来验证通用性

---

## 1. 问题

在只有 `deep_research` 及其 supervised / human review 变体的时候，系统虽然已经有：

- runtime core
- supervisor guidance
- checkpoint-backed replan
- human review gate
- memory manager

但还有一个关键问题没有被证明：

**这套 runtime 到底是通用内核，还是只是 research workflow 的高级壳子？**

如果不补第二个 workflow，就很容易出现一种错觉：

- 架构看起来很抽象
- 但实际所有 agent 文案、产物和默认行为都还是 research 偏置

---

## 2. 决策

当前先补一个轻量但明确非 research 的 workflow：

- `workflows/customer_support_brief.yaml`

同时把当前 3 个最小 Worker 的默认产物从“research 专用口吻”泛化成：

- 更通用的任务拆解
- 更通用的上下文材料
- 更通用的总结交付

这样验证的重点就不是“新业务逻辑有多复杂”，而是：

**同一套 runtime + 同一批最小 worker，能否顺利切到另一个任务类型。**

---

## 3. 为什么这样取舍

### 为什么现在必须补第二个 workflow

因为这是区分“概念抽象”和“真实抽象”的关键一步。

只有当第二个 workflow 能自然跑起来，才更有资格说：

- runtime 不只适配一个 demo
- agent 组合开始具备可迁移性
- 后续再谈 ToolRegistry、LLMClient、Guardrails 才更有基础

### 为什么不直接做特别复杂的新 workflow

因为当前要验证的是：

**runtime 的抽象有没有写死。**

而不是：

**新业务逻辑够不够复杂。**

所以选择一个更轻的 service/content 风格任务，能更快看清问题：

- planner 的任务拆解是不是太 research 化
- search 的上下文产物是不是太 research 化
- summarizer 的结论是不是太 research 化

### 为什么要同步泛化 3 个 Worker

因为如果第二个 workflow 只是换个 yaml，但 worker 本身仍然写死成研究语境，那验证意义会很弱。

这一步要证明的不是“workflow 文件能复制一份”，而是：

**最小 worker 层已经开始具备跨任务类型复用能力。**

---

## 4. 当前实现边界

已经做到：

- 第二个非 research workflow 跑通
- planner / search / summarizer 的默认口吻已从 research 特化变成更通用的任务表达
- runtime 已验证可以输出 `service` 类型 plan / summary

还没做到：

- 真正丰富的多角色新 workflow
- 针对不同任务类型的专门 agent 库
- ToolRegistry 驱动下的动态能力切换
- 更成熟的 handoff / guardrails

所以当前更准确的定位是：

**已经证明 runtime 不是纯 research 专用，但离完整多领域 agent 生态还有距离。**

---

## 5. 后续演化

最自然的下一步是：

1. 增强 execution audit / `ConvergenceReport`
2. 引入 `ToolRegistry v1`
3. 设计 `LLMClient v1`
4. 继续扩 Memory，让记忆不只沉淀，还能复用

---

## 6. 面试 / 博客表达

### 一句话版本

我们没有停留在单个 research workflow 的成功案例上，而是主动补了第二个非 research workflow，验证这套 runtime 和最小 worker 层已经开始具备跨任务类型复用能力。

### 稍展开版本

很多项目会把一个 workflow 跑通之后就默认自己是“通用框架”，但真正的验证方式是换一个任务类型再跑一遍。我们这一步就是在做这个验证：保持 runtime 不变，只把任务类型从 research 切到 service/content 风格，确认当前抽象没有写死在原来的场景里。
