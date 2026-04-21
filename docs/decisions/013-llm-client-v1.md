# LLMClient v1

## 这份记录是做什么的

这份记录沉淀的是 `adaptive-agent-orchestrator` 在 ToolRegistry 之后，对模型层做出的第一版正式抽象：

- 为什么现在要引入 `LLMClient v1`
- 为什么当前先做统一入口和最小 profile，而不是直接接真实 provider
- 为什么 planner / summarizer / supervisor 要优先迁到统一 client

---

## 1. 问题

在补完：

- ToolRegistry v1
- execution audit
- MemoryManager v1
- human review gate

之后，系统的几个核心 agent 仍然存在一个问题：

**很多“像模型一样的生成行为”还直接写在 agent 体内。**

比如：

- planner 直接拼 plan
- summarizer 直接拼 summary
- supervisor 直接拼 review report

这样做在最小 demo 阶段没问题，但对完整生态 v2 来说有明显风险：

- agent 和模型行为耦合太紧
- 后续想切真实 provider 或做分层路由时，没有统一入口
- 不同 agent 的模型配置无法集中管理

---

## 2. 决策

当前先补一个最小但正式的 `LLMClient v1`：

- 新增 `ModelProfile`
- 新增 `LLMClient`
- `AgentConfig` 新增 `model_profile`
- `BaseAgent` 新增 `complete_structured()`

当前支持的最小 profiles：

- `worker`
- `worker_fast`
- `orchestrator`

同时先把 3 个最关键的“模型型 agent”迁过去：

- `PlannerAgent`
- `SummarizerAgent`
- `SupervisorAgent`

---

## 3. 为什么这样取舍

### 为什么现在就要做 LLMClient

因为 ToolRegistry 已经把工具层拉出来了。  
如果模型层还继续散落在 agent 里，后续 architecture 就会出现一种不对称：

- 工具有统一入口
- 模型没有统一入口

而完整生态 v2 明确要求模型层也应统一进入 `LLMClient`。

### 为什么先做 profile，而不是先做真实 provider

因为当前最需要先做对的是：

**模型调用的接口边界。**

不是：

**模型供应商的真实接入。**

如果接口边界没立住，后面不管接 OpenAI、Anthropic 还是别的 provider，都会继续把 provider 逻辑揉进 agent 里。

### 为什么先迁 planner / summarizer / supervisor

因为这 3 个角色最明显承担的是“结构化生成”职责。

先迁它们能最快验证：

- profile 分层是否合理
- agent / model 解耦是否顺畅
- 后续 orchestrator profile 是否有存在感

---

## 4. 当前实现边界

已经做到：

- 统一模型入口存在
- agent 已可以声明 `model_profile`
- 3 个核心生成型 agent 已接入统一 client
- 产物里已经能看到 `model_profile` 痕迹

还没做到：

- 真实 provider 接入
- token usage 真实统计
- model fallback / routing policy
- provider adapter 层
- prompt 资产外置化

所以当前更准确的定位是：

**LLMClient v1 已经把模型层正式拉出来了，但仍然是 mock/provider-free 的第一步。**

---

## 5. 后续演化

最自然的下一步是：

1. 扩 Memory，让模型使用信息也能进入长期沉淀
2. 明确 tool usage / guardrail 边界
3. 再往后接真实 provider-aware client
4. 引入更细的 profile routing 与 fallback

---

## 6. 面试 / 博客表达

### 一句话版本

我们没有继续让每个 agent 自己偷偷长模型生成逻辑，而是把模型层抽成了统一 `LLMClient`，并通过 profile 机制让 worker 和 orchestrator 开始有不同的模型角色定位。

### 稍展开版本

一个真正的 agent runtime，不应该让 worker 和 supervisor 各自随意调用模型。我们这一步的重点，就是先把模型层从 agent 里剥出来，建立统一的 `LLMClient` 和 profile 机制。这样即使当前还是 mock backend，后续接真实 provider、做模型路由和成本控制时，架构也不会被推翻。
