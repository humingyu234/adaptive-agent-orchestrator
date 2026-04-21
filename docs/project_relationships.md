# 项目关系说明

## 这份文档记录什么
这份文档记录的是三个东西之间的关系：

- `deep_research_agent`
- `adaptive-agent-orchestrator`
- 未来的 evaluate system

这份文档的目标，是避免后面把三条线混成一个大项目，或者把它们误以为是重复项目。

---

## 一句话关系

可以先用一句最白的话记住：

- `deep_research_agent`：负责把事做出来
- `adaptive-agent-orchestrator`：负责让多个 Agent 稳定协作
- evaluate system：负责判断系统哪里坏了、怎么坏的、和上次比有没有变好

也就是说：

- 一个是具体应用
- 一个是运行时引擎
- 一个是评估层

---

## 1. `deep_research_agent` 是什么

`deep_research_agent` 是一个已经存在的具体应用型项目。

它主要负责：

- 拆题
- 搜资料
- 反思证据是否足够
- 组织总结
- 输出报告

可以把它理解成：

- 一个真实的 research workflow
- 一个真实的 agent 应用系统

它的价值不只是“能做研究”，还包括：

- workflow 设计
- 题型拆解
- search / selector / reflector 的协作
- quick checks / eval / failure taxonomy
- reliability / regression 思维

所以它是一个：

- 具体应用项目
- 也是 evaluate 资产的来源项目

---

## 2. `adaptive-agent-orchestrator` 是什么

`adaptive-agent-orchestrator` 不是再做一个具体业务应用，而是在做：

- 多 Agent 编排引擎
- 运行时内核

它主要负责：

- `Scheduler`（调度器）
- `StateCenter`（状态中心 / 共享白板）
- `Evaluator`（评估器）
- `Workflow`（工作流配置）
- `graceful degradation`（诚实降级）

它要解决的问题不是：

- “研究问题怎么回答”

而是：

- “多个 Agent 如何稳定协作”
- “什么时候重试、回退、降级”
- “状态如何传递、质量如何把关”

所以它的定位是：

- 引擎层
- 基础设施层
- runtime 层

更进一步说，这个引擎未来不只应该支持普通执行 Agent，还应该支持：

- `Supervisor Agent`（总控 / 监督智能体）

也就是让系统具备这样的层级：

- Human（人类，最高权限）
- Supervisor Agent（代理日常总控动作）
- Planner / Executor / Reviewer / Evaluator 等其他角色

---

## 3. evaluate system 是什么

未来的 evaluate system，不是重新发明一个全新平台，而是把当前 `deep_research_agent` 里已经验证过有价值的裁判能力抽出来。

它主要负责：

- `cases`（评估题集）
- `runners`（评估运行方式）
- `judges`（判卷逻辑）
- `taxonomy`（失败分类）
- `compare`（回归对比）
- `summaries / baselines`（结果沉淀）

它要解决的问题不是：

- “业务怎么做”

而是：

- “怎么判断流程有没有跑歪”
- “是哪个模块出了问题”
- “问题属于哪种失败模式”
- “和上个版本相比是进步了还是退化了”

所以它的定位是：

- 评估层
- 裁判层
- regression / reliability 层

---

## 三者的关系图

```text
                 ┌──────────────────────┐
                 │  deep_research_agent │
                 │                      │
                 │  负责“做事”           │
                 │  - planner           │
                 │  - search            │
                 │  - summarizer        │
                 │  - reflector         │
                 └──────────┬───────────┘
                            │
                            │ 输出运行结果
                            ▼
                 ┌──────────────────────┐
                 │    evaluate system   │
                 │                      │
                 │  负责“判卷”           │
                 │  - cases             │
                 │  - runners           │
                 │  - judges            │
                 │  - taxonomy          │
                 │  - compare           │
                 └──────────┬───────────┘
                            │
                            │ 反哺评估方法与质量判断
                            ▼
                 ┌──────────────────────┐
                 │ adaptive-agent-      │
                 │ orchestrator         │
                 │                      │
                 │  负责“组织协作”       │
                 │  - scheduler         │
                 │  - state center      │
                 │  - evaluator         │
                 │  - workflow runtime  │
                 │  - supervisor layer  │
                 └──────────────────────┘
```

---

## 更直观的理解

### `deep_research_agent`
像：

- 干活的人

它的任务是：

- 把研究型任务真正做出来

### evaluate system
像：

- 裁判组

它的任务是：

- 判断干活的人哪里做得不对
- 记录失败模式
- 比较这次和上次的变化

### `adaptive-agent-orchestrator`
像：

- 调度系统 / 团队协作操作系统

它的任务是：

- 让多个角色稳定配合
- 让状态和评估进入运行时闭环
- 让 Supervisor Agent 代理部分总控动作
- 让人类只在高杠杆节点做最终判断

---

## 为什么说 `deep_research_agent` 以后可以跑在这个引擎上

这句话的真正意思不是：

- 现在就已经一行命令能直接迁过去

而是：

- `deep_research_agent` 现在已经天然包含一组很像 Agent 的能力单元

例如：

- `planner.py`
- `search.py`
- `reflector.py`
- `summarizer.py`
- `reporter.py`

这些模块以后可以被包装成：

- `PlannerAgent`
- `SearchAgent`
- `SummarizerAgent`
- 以及研究场景下的 Evaluator / Reporter 组件

然后由 `adaptive-agent-orchestrator` 统一去调度。

更进一步，未来这条链还可以由：

- `Supervisor Agent`

先做任务拆解、角色分配、进度汇总和第一轮验收，再由人类拍板。

也就是说：

- 现在：`deep_research_agent` 自己带着流程跑
- 以后：`deep_research_agent` 可以变成一个运行在 orchestrator 上的应用工作流
- 再以后：这条工作流还可以进入“人类最高权限 + Supervisor Agent 代理日常总控”的模式

---

## 为什么 evaluate system 和 orchestrator 不是重复的

很多时候这两条线容易混。

它们的区别是：

### evaluate system
重点是：

- 怎么判
- 怎么分失败类型
- 怎么做 regression
- 怎么看版本变化

### orchestrator
重点是：

- 怎么调度
- 怎么共享状态
- 怎么在运行时决定 retry / re-plan / degrade
- 怎么让 Supervisor Agent 组织其他 Agent 协作

所以：

- evaluate system 更像“裁判逻辑和评估资产”
- orchestrator 更像“协作运行时和总控代理层”

两者是互补关系，不是重复关系。

---

## 当前正式结论

当前三条线的关系正式定为：

1. `deep_research_agent` 是真实应用项目，也是 evaluate 资产来源。
2. evaluate system 是从 `deep_research_agent` 中逐步抽离出来的裁判层。
3. `adaptive-agent-orchestrator` 是未来承载多 Agent 协作的运行时内核。
4. 长期理想状态下：
   - evaluate system 为 orchestrator 提供评估方法和失败分类经验
   - `deep_research_agent` 可以作为一个具体 workflow 跑在 orchestrator 上
   - Supervisor Agent 可代理大量日常总控动作
   - 人类保留最高权限与最终拍板权

---

## 一句话总结

三者不是三个重复项目，而是三层不同的东西：

- `deep_research_agent` 负责做事
- evaluate system 负责判事
- `adaptive-agent-orchestrator` 负责组织多个角色稳定做事，并逐步支持 Supervisor Agent 代理部分总控工作
