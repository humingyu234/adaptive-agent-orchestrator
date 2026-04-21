# 市场信号与能力积累方向

## 1. 这份文档是做什么的

这份文档记录的是基于真实招聘市场信号整理出来的判断：

- 企业现在在真实招聘哪些 Agent / AI Infra 方向的工程师
- 哪些能力是重复出现、值得优先积累的
- 为什么 `deep_research_agent + adaptive-agent-orchestrator + future evaluate system` 这条路线是合理的
- 后续项目迭代时，应该优先补哪些能力，而不是平均发力

这不是泛泛的职业建议，而是围绕真实岗位描述提炼出来的方向文档。

---

## 2. 真实市场里反复出现的需求信号

### 2.1 Orchestration / Runtime（编排 / 运行时）

很多岗位不再只要“会接模型 API”，而是明确要求：

- agent orchestration
- stateful / multi-step workflows
- execution runtime
- tool calling with guardrails
- long-running tasks
- memory management
- supervisor / sub-agent patterns

这说明市场需要的不是单点 AI 应用开发，而是能把多步、多角色 Agent 系统稳定跑起来的人。

### 2.2 Evaluation / Reliability（评估 / 可靠性）

这是现在非常强的市场信号之一。多个岗位明确提到：

- evaluation frameworks
- regression suites
- release gating
- baseline / comparative evaluation
- KPI / quality metrics
- safe, reliable, production-ready agent features

也就是说：

企业已经不满足于“Agent 能跑”，而是在要求：

- 怎么衡量它好不好
- 怎么知道新版本有没有退化
- 怎么在上线前做质量门

### 2.3 Observability / Monitoring（可观测性 / 监控）

岗位里反复出现：

- tracing
- logging
- alerting
- behavior monitoring
- failure analysis
- dashboards
- auditability

这说明企业正在把 Agent 当成需要被持续观测的生产系统，而不是一次性 demo。

### 2.4 Memory / Context / Durable State（记忆 / 上下文 / 持久状态）

多个岗位强调：

- long-term memory
- context management
- distributed context
- durable state
- versioning / persistent systems

这和你前面讨论的“文件化上下文”“共享状态”“长期记忆”方向高度一致。

### 2.5 Human-in-the-loop / Failure Handling（人工介入 / 失败处理）

真实岗位很关注：

- graceful handoff to humans
- escalation
- retries / timeouts / idempotency
- fallback / non-happy path
- safe degradation

这说明企业真正缺的是：

能把 Agent 从“理想 happy path”拉到“真实世界非 happy path”里还能稳定运行的人。

---

## 3. 这些市场信号对应你现在正在做的三条线

### 3.1 `deep_research_agent`

它证明的是：

- 你会做真实 workflow
- 你会做 eval / regression / taxonomy
- 你会在一个具体业务场景里处理 reliability 问题

### 3.2 `adaptive-agent-orchestrator`

它证明的是：

- 你会做 orchestration runtime
- 你会做 shared state / scheduler / evaluator
- 你开始把“多个 Agent 如何稳定协作”抽成引擎

### 3.3 future evaluate system

它证明的是：

- 你不只是做应用和运行时
- 你还在抽 workflow-native evaluation layer
- 你会把 failure taxonomy / judge / compare / regression 变成更独立的系统能力

---

## 4. 后续最值得优先积累的 5 个能力

这 5 个能力不是抽象建议，而是从真实岗位反复出现的要求里整理出来的。

### 4.1 Orchestration（编排）

重点积累：

- Scheduler（调度器）
- StateCenter（状态中心）
- Workflow runtime（工作流运行时）
- retry / re-plan / graceful degradation
- 多角色 Agent 协作边界

为什么重要：

这是你从“会做 Agent 功能”升级到“会做 Agent 系统”的关键一步。

### 4.2 Evaluation / Reliability（评估 / 可靠性）

重点积累：

- failure taxonomy
- judge
- quick checks / full eval / variant eval
- baseline / compare / regression
- enough / insufficient / quality gates

为什么重要：

现在“会做 agent eval”的人，比“会调个 agent 跑起来”的人更稀缺。

### 4.3 Observability（可观测性）

重点积累：

- execution trace
- eval audit
- convergence report
- structured logs
- failure analysis

为什么重要：

企业最终要的是：出了问题能知道哪里坏了，而不是只能重跑。

### 4.4 AI-native Working Style（AI 原生工作方式）

重点积累：

- 文件化上下文
- PROJECT_STATE / PROJECT_LOG / REVIEW_NOTES
- 1 主 1 辅 -> Supervisor + Workers 的过渡
- 角色分工
- 人类总控与总控 Agent 的边界

为什么重要：

未来的竞争不只是“谁会写代码”，而是“谁会组织人类 + 多 Agent 稳定协作”。

### 4.5 Technical Narrative（技术叙事）

重点积累：

- 能清楚讲 `deep_research_agent` 在做什么
- 能清楚讲 `adaptive-agent-orchestrator` 在做什么
- 能清楚讲 future evaluate system 为什么值得抽出来
- 能清楚讲这三者是怎么构成一条路线的

为什么重要：

市场上很多人有 demo，但很少有人能把自己的方向讲成一条系统路线。

---

## 5. 未来 6-12 个月最应该优先补的顺序

### 第一优先级

- Orchestration
- Evaluation / Reliability

原因：

这是你当前最有机会形成明显差异化的核心。

### 第二优先级

- Observability
- AI-native Working Style

原因：

这是把项目从“能跑”推向“能维护、能协作、能长期优化”的关键。

### 第三优先级

- Technical Narrative

原因：

这不是最后再补的包装，而是要随着项目推进同步沉淀。你已经开始做这件事，后面要继续强化。

---

## 6. 我们接下来怎么用这份文档

后续做项目迭代时，不再只问：

- 这个功能酷不酷
- 这个架构抽象大不大

而是优先问：

1. 它是否在增强 orchestration 能力？
2. 它是否在增强 evaluation / reliability？
3. 它是否让系统更可观测？
4. 它是否更接近 AI-native working style？
5. 它是否能加强你的整体技术叙事？

如果答案都是否定的，那它大概率不是当前阶段最优先的工作。

---

## 7. 代表性市场信号来源（岗位链接）

以下是整理这份方向判断时参考的部分真实岗位：

- RYZ Labs – Applied AI Engineer  
  https://jobs.lever.co/RyzLabs/f15d2e8b-31b6-4cff-837b-38aeed6c9791
- Boson AI – Member of Technical Staff, Agent Platform (Agent OS)  
  https://jobs.lever.co/bosonai/35858631-de70-4ddf-b310-ea9417af3b29
- Kumo – AI Engineer, Relational Foundation Models & Agentic Systems  
  https://jobs.lever.co/kumo/df6990cb-ce02-4be4-be3f-970a244fa0ea
- Netomi – Senior Product Manager, Autonomous Agents  
  https://jobs.lever.co/netomi/c83a8721-a18f-4e31-93b6-057b97d21e38
- Tandems – AI Platform Engineer  
  https://jobs.lever.co/tandems/f9674954-40c0-47cf-a7bf-e78dfe51e3b1
- StackAdapt – Automation Engineer, Agentic Orchestration  
  https://jobs.lever.co/stackadapt/3031d6fa-4f16-437c-8c9b-a9aae8e90f18
- Anomali – Senior Agentic AI Engineer (Cybersecurity)  
  https://jobs.lever.co/anomali/c9f77f77-abc6-432e-bb12-531441f640a2
- Anomali – Senior Engineer, AI Evaluation & Reliability (Agentic AI)  
  https://jobs.lever.co/anomali/35848707-2902-48ec-af8d-d7c22fb7eb6d
- HighLevel – Staff Product Manager, AI Platform  
  https://jobs.lever.co/gohighlevel/7ae588d7-b7fe-4e71-87b7-f411229efafc
- CI&T – AI Quality Engineer Senior, QA  
  https://jobs.lever.co/ciandt/1e06dadb-5342-470d-a9a1-cb42755381a2
- Netomi – SDE II, Agentic Engineer  
  https://jobs.lever.co/netomi/c81f4efa-21e8-4098-b8f5-e8f49673c5b8

---

## 8. 一句话结论

你现在这条路线并不是在做“没人要的超前概念”，而是在做：

- 市场真实需要
- 但标准还没完全定型
- 很适合通过项目积累拉开差异化

的 Agent Infra / Agent Runtime / Agent Evaluation 方向。
