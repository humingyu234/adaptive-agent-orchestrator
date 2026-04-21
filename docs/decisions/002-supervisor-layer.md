# Supervisor Layer 最小骨架

## 这份记录是做什么的

这份记录沉淀的是：为什么在当前阶段就要把 `Supervisor Agent` 落一层最小代码骨架，以及这层现在到底承担什么、不承担什么。

---

## 1. 问题

项目的最终设计已经明确是：

- Human（最高权限）
- Supervisor Agent（代理日常总控）
- Worker Agents（执行角色）

但如果代码里始终只有 Worker，没有 Supervisor，这个层级就只存在于文档里。这样会导致：

- 长期设计和当前实现断层
- 面试或博客时很难证明这不是纸上架构
- 后面接 memory / feedback / multi-model routing 时缺少一个自然承接点

---

## 2. 决策

当前阶段不把 Supervisor 做成完整生态中枢，而是先落一个最小骨架：

- 新增 `SupervisorAgent`
- 让它读取：`query / plan / raw_documents / summary`
- 让它输出：`supervisor_report`
- 新增 supervised workflow：
  - `planner -> search -> summarizer -> supervisor`
- 在 `Evaluator(L1)` 中增加最小 supervisor 输出检查

这样做的目标不是“马上让 Supervisor 接管整个系统”，而是：

- 先把层级立住
- 让代码结构第一次真正体现 `Human -> Supervisor -> Worker`

---

## 3. 取舍

### 为什么现在就做骨架

因为这层是整个项目和普通多 Agent workflow 区分开的关键设计之一。

如果一直只写 Worker，项目会更像：

- 运行时 + 三个工人

而不是：

- 有潜力长成生态内核的 runtime

### 为什么不现在做满

因为完整 Supervisor 需要承担很多更重的能力：

- 任务拆解
- 角色分发
- 进度汇总
- 风险判断
- 基于历史记忆调整策略

这些任何一项做满都会把当前阶段拉得太重。

所以这次的取舍是：

- 不做满
- 但也不继续只停在文档里

---

## 4. 当前边界

当前的 `SupervisorAgent` 还没有覆盖：

- 真正的任务拆分
- 动态分角色
- 基于长期记忆做判断
- 驱动 re-plan
- 多模型协调

它现在更像：

- 一层“总控代理接口”
- 一个第一轮审查与汇总节点

---

## 5. 后续演化

后续这层最自然的增强顺序是：

1. 让 Supervisor 读取执行轨迹和失败信息
2. 让 Supervisor 结合历史记录给出下一步建议
3. 让 Supervisor 触发更明确的 retry / re-plan 建议
4. 再接入 provider / plugin 层，让它能调不同模型或工具

---

## 6. 面试 / 博客表达

### 一句话版本

我没有等到完整生态都做好才引入 Supervisor，而是先把它做成一个最小骨架节点，让系统在代码结构上就开始体现 Human、Supervisor、Worker 的分层协作。

### 稍展开版本

这个项目的长期目标不是普通多 Agent workflow，而是一个更接近 AI 协作生态内核的 runtime。Supervisor 层是这个目标里非常关键的一层，所以我在当前阶段先把它做成一个可运行的最小节点：它能读取前面 Worker 的结果，产出第一轮总控报告，并通过 supervised workflow 跑通。这样做不会过早把系统做重，但能让长期设计开始在代码里出现真实形态。
