# 多 Agent 编排与评估系统架构设计（当前设计基线）

## 1. 这份文档的定位

这份文档记录的是：

- 当前项目的正式设计基线
- 当前到最终版之间的实现边界
- 哪些属于最终目标形态
- 哪些属于当前一周冲刺必须做完的部分

如果要看完整长期目标，请同时参考：

- `docs/ecosystem_architecture_v2.md`

---

## 2. 项目定位

`adaptive-agent-orchestrator` 的定位不是具体业务应用，而是一个：

- 轻量级多 Agent 编排引擎
- 运行时内核（runtime core）
- 面向可靠性、评估与收敛控制的协作系统

---

## 3. 长期目标层级（目标形态）

长期目标不是单纯 workflow，而是：

```text
Human（人类，最高权限）
  ↓
Supervisor Agent（总控 / 监督智能体）
  ↓
Scheduler（调度器）
  ↓
Worker Agents（Planner / Search / Summarizer / Reviewer / Evaluator ...）
  ↓
StateCenter + Evaluator + Memory + Feedback Loop
```

这部分属于最终目标形态，不代表当前实现已全部完成。

---

## 4. 当前一周冲刺的实现边界

当前这一周，我们按“最终版方向不变，但实现先收敛成最小闭环”的原则推进。

### 这一周必须做完

- `StateCenter`
- `Scheduler`
- `Evaluator(L1)`
- `AgentRegistry`
- `PlannerAgent`
- `SearchAgent`
- `SummarizerAgent`
- 最简执行日志
- CLI 入口
- 一个能真正跑通的 `deep_research` workflow

### 这一周不要求做满

- 完整 `Supervisor Agent`
- 长期记忆层
- `L2 / L3`
- 真正 checkpoint rollback
- 多模型路由
- 完整 feedback self-improvement loop
- Web UI / API
- 并发执行

也就是说：

当前不是缩小目标，而是：

- 长期设计按完整生态写清楚
- 当前实现先做最核心的 runtime core

---

## 5. 当前必须实现的核心模块

## 5.1 Scheduler（调度器）

当前必须做到：

- 顺序调度
- retry 上限保护
- fail 路径
- `max_steps` 收敛保护
- 最简 workflow 执行

当前不要求：

- 复杂条件边全覆盖
- 真正的 re-plan + rollback 闭环

---

## 5.2 StateCenter（共享状态中心）

当前必须做到：

- 保存 query / plan / raw_documents / summary
- 维护 `execution_trace`
- `prepare_view()` 白名单裁剪
- 基础写入接口

当前不要求：

- 成熟长期记忆系统
- 完整 checkpoint 快照系统

---

## 5.3 Evaluator（运行时评估器）

当前必须做到：

- `L1` 规则检查
- 对 planner / search / summarizer 做最小合法性判断
- 返回 `continue / retry / fail`

当前不要求：

- `L2 / L3`
- 重型语义判断
- 完整 failure taxonomy 融入 runtime

---

## 5.4 Worker Agents

当前必须做到：

- `PlannerAgent`
- `SearchAgent`
- `SummarizerAgent`

目标是：

- 先让一条 workflow 真的跑起来
- 再逐步扩展更多角色

---

## 5.5 Logging / Observability

当前必须做到：

- 每步执行后记录最简结构化日志

当前不要求：

- 完整评估审计
- 完整 convergence dashboard

---

## 6. 为什么这样取舍

### 6.1 我们不是放弃最终版
而是明确分开：

- 最终版目标形态
- 当前一周可交付范围

### 6.2 如果一周里直接做完整生态，会炸
因为完整生态需要同时做：

- runtime
- supervisor
- memory
- eval full stack
- feedback loop
- multi-model coordination

这会直接超出当前冲刺范围。

### 6.3 当前最优策略
当前最优策略是：

- 用一周把 runtime core 做实
- 保留完整生态方向
- 让后续扩展是加层，而不是推翻重来

---

## 7. 当前架构优点

- 分层清楚
- runtime / app / evaluate 路线明确
- 支持未来 Supervisor 层引入
- evaluator-first 的差异化很强
- 非常适合吸收 `deep_research_agent` 的 eval 资产

---

## 8. 当前架构风险

- 如果 `Evaluator` 不落地，差异化会塌
- 如果只写文档不跑 workflow，会变成概念项目
- 如果没有第二个 workflow 验证，后续可能写死成 research 专用

---

## 9. 与其他两条线的关系

### `deep_research_agent`
- 具体应用
- 未来可运行在本引擎上
- 也是 evaluate 资产来源

### future evaluate system
- 裁判层
- 为本项目的 `Evaluator` 提供方法论来源

### `adaptive-agent-orchestrator`
- 运行时内核
- 负责组织多个角色稳定协作
- 长期目标支持 Supervisor 代理总控动作

---

## 10. 一句话总结

当前设计不是保守缩小，而是明确分成两层：

- **最终版目标**：Human -> Supervisor -> Worker + Memory + Evaluation + Feedback Loop
- **当前一周实现**：先把 `Scheduler + StateCenter + Evaluator(L1) + 3 个 Worker Agents + CLI + 日志` 做成真的可运行内核
