# 完整生态设计方案 v2

> 这份文档是当前项目的**完整生态目标蓝图**。  
> 它不是当前已全部完成的实现清单，而是后续实现、取舍、博客叙事和面试表达的统一设计基线。

---

## 1. 设计借鉴来源

这套设计不是凭空拍脑袋长出来的，而是有意识地吸收了不同框架里最成熟的部分。

| 框架 / 来源 | 借鉴的核心设计 | 为什么借 |
|---|---|---|
| LangGraph | checkpoint-based HITL、typed state、interrupt_before/after | human-in-the-loop 机制最成熟 |
| AutoGen v0.4 | MagenticOne 的 re-plan、SelectorGroupChat 的 supervisor 驱动 | 动态重规划最成熟 |
| OpenAI Agents SDK | guardrails、handoff、built-in tracing | agent 间控制权转移最干净 |
| CrewAI | 4 层记忆、role + backstory、expected_output | 认知记忆架构最完整 |
| Anthropic 生产设计思路 | trust hierarchy、minimal footprint、memory module、eval-driven | 生产级安全与保守默认值 |

### 当前项目自己的独特点

这些不是照抄来的，而是当前项目本身要坚持保留的核心差异化：

- `Evaluator(L1/L2/L3)` 作为一等公民
- `Graceful Degradation` 4 个 level
- 显式契约：`reads / writes / schema`
- `bounded execution`（收敛保证）
- `EvalCriteria` 外置配置

---

## 2. 完整生态总体层级

```text
┌──────────────────────────────────────────────────────────────────┐
│ LAYER 1: HUMAN INTERFACE                                        │
│ CLI · Approval Gates · Live Interrupt · Command Injection       │
└────────────────────────────┬─────────────────────────────────────┘
                             │ 最高优先级信号
┌────────────────────────────▼─────────────────────────────────────┐
│ LAYER 2: SUPERVISOR ORCHESTRATOR                                │
│ Discussion-First · LLM-driven next_agent · Re-plan             │
└────────────────────────────┬─────────────────────────────────────┘
                             │ 调度
┌────────────────────────────▼─────────────────────────────────────┐
│ LAYER 3: RUNTIME CORE                                           │
│ Scheduler · StateCenter · Evaluator(L1/L2/L3)                  │
│ Convergence · Graceful Degradation · Execution Trace           │
└────────────────────────────┬─────────────────────────────────────┘
                             │ 调用
┌────────────────────────────▼─────────────────────────────────────┐
│ LAYER 4: WORKER AGENTS + GUARDRAILS                             │
│ Role + Backstory + Expected Output + Tools                      │
│ Input Guardrail → Agent → Output Guardrail                      │
└────────────────────────────┬─────────────────────────────────────┘
                             │ 调用
┌────────────────────────────▼─────────────────────────────────────┐
│ LAYER 5: TOOL REGISTRY                                          │
│ Search · CodeExec · FileIO · Browser · API · Database          │
└────────────────────────────┬─────────────────────────────────────┘
                             │ 读写
┌────────────────────────────▼─────────────────────────────────────┐
│ LAYER 6: SHARED CONTEXT                                         │
│ StateCenter + ProjectContext + Checkpoint Store                 │
└────────────────────────────┬─────────────────────────────────────┘
                             │ 沉淀
┌────────────────────────────▼─────────────────────────────────────┐
│ LAYER 7: MEMORY                                                 │
│ Short-term · Long-term · Entity · Procedural                   │
└────────────────────────────┬─────────────────────────────────────┘
                             │ 反馈
┌────────────────────────────▼─────────────────────────────────────┐
│ LAYER 8: FEEDBACK LOOP + EVAL SYSTEM                            │
│ Convergence Report · Failure Taxonomy · Regression Compare      │
└──────────────────────────────────────────────────────────────────┘
```

最白的话解释：

- Layer 1：人类可以随时插手
- Layer 2：总控层决定下一步谁干什么
- Layer 3：运行时负责调度、状态、评估、收敛
- Layer 4：真正干活的角色层
- Layer 5：工具层
- Layer 6：共享项目上下文
- Layer 7：长期记忆
- Layer 8：反馈闭环和评估系统

---

## 3. 每层职责

### Layer 1：Human Interface

目标：

- 人类保留最高权限
- 任何不可逆动作默认需要明确确认
- 支持三种介入：
  - approval gate
  - live interrupt
  - instruction injection

这一层的关键不是“人类一直手动调度”，而是：

**人类随时可以接管，并且系统必须尊重这种优先级。**

---

### Layer 2：Supervisor Orchestrator

这是生态的大脑。

不是 workflow 里的普通节点，而是更高一层的主控。

它负责：

- 先讨论，再决定怎么执行
- 动态决定下一步 agent
- 维护 `TaskLedger`
- 检测 stalled / no progress
- 必要时触发 `re-plan`

这个层借鉴的核心是：

- AutoGen MagenticOne 的任务账本
- CrewAI 的 hierarchical manager
- 你朋友生态里“先讨论再决定”的工作方式

---

### Layer 3：Runtime Core

这是当前项目最核心、最独特的地方。

负责：

- `Scheduler`
- `StateCenter`
- `Evaluator(L1/L2/L3)`
- `Convergence`
- `Graceful Degradation`
- `Execution Trace`

这是当前项目和很多只是“会调 Agent”的系统最不同的地方：

**重点不只是“跑起来”，而是“收敛、评估、纠偏、降级”。**

---

### Layer 4：Worker Agents + Guardrails

这里是真正干活的角色库。

每个 Worker Agent 后续都应该有：

- `role`
- `backstory`
- `goal`
- `expected_output`
- `reads`
- `writes`
- `tools`
- `handoffs`
- `guardrails`
- `llm_model`

这一层要从现在的最小 stub，升级成：

**角色清楚、工具清楚、输入输出清楚、护栏清楚的真实执行层。**

---

### Layer 5：Tool Registry

统一管理：

- `web_search`
- `python_exec`
- `file_io`
- `browser`
- `database`
- 未来的 provider / plugin adapters

这一层的目标是：

**任何 Agent 想调用能力，都通过统一注册表，不要在 Agent 里直接乱接工具。**

---

### Layer 6：Shared Context

这一层不是只有 `StateCenter`。

完整版本里应该包含：

- `StateCenter`：运行时内存状态
- `ProjectContext`：项目文件上下文
- `CheckpointStore`：可恢复断点

也就是说，上下文不只在 prompt 里，而是在：

- 内存
- 文件系统
- checkpoint store

三处协同。

---

### Layer 7：Memory

完整记忆分四层：

- `Short-term`
- `Long-term`
- `Entity`
- `Procedural`

另外还有一层很重要的：

- `Failure Memory`

这层非常贴当前项目路线，因为它和 future evaluate system、failure taxonomy、regression 全能接起来。

---

### Layer 8：Feedback Loop + Eval System

这是整个生态闭环的最后一层。

负责：

- `ConvergenceReport`
- `FailureTaxonomy`
- `RegressionCompare`
- `Analyze CLI`

这层意味着：

**系统不只是做完任务，而是能回头看自己哪里坏了，并调整下一次策略。**

---

## 4. 如何支持任意类型项目

这个生态真正的价值，不是只支持 research，而是：

**同一个 runtime + 不同 workflow + 不同角色组合，可以支持不同项目类型。**

例如：

- research
- coding
- customer service
- data analysis
- content creation

为什么能做到？

因为 runtime 只关心：

- 谁先执行
- 状态怎么传
- 质量怎么判断
- 失败怎么处理
- 人类什么时候介入

它不关心具体业务内容，具体业务内容属于：

- workflow 配置
- agent 角色
- tools
- eval criteria

---

## 5. LLM 接入和模型分层

完整生态里，大模型不应该乱接，而应该统一进：

- `LLMClient`

并支持模型分层：

- `orchestrator`：最强模型，给 Supervisor
- `sonnet`：给大多数 worker
- `haiku`：给简单、便宜、频繁的任务

这一层的目标不是“统一都用一个最强模型”，而是：

**让架构能兼顾效果和成本。**

---

## 6. Trust Hierarchy / Safety

这一层非常重要。

完整生态里应该明确：

- `HUMAN` 权限最高
- `SUPERVISOR` 不能覆盖 human 指令
- `WORKER` 只能执行被分配任务
- `TOOL` 权限最低

同时必须遵守：

- 不可逆动作默认要 human approval
- 不确定时先停，不要猜
- 任何 agent 都不能绕过 human abort

---

## 7. 当前完成度判断

### Phase 1：当前已完成的大概范围

当前已经完成或基本完成的：

- `StateCenter`
- `Scheduler`
- `Evaluator(L1)`
- 三个 Worker Agent stub
- `SupervisorAgent` 最小控制闭环
- execution logs
- CLI
- smoke tests
- 最小 supervisor guidance
- 最小 `re_plan` 信号

### 当前离完整生态还差什么

最重要的缺口是：

- Human review gates
- `ConvergenceReport`
- `MemoryManager`
- `StateCenter save/load`
- `CheckpointStore`
- `LLMClient`
- `Guardrails`
- `ToolRegistry`
- `FailureTaxonomy` runtime 接入
- `Analyze CLI`
- 第二个 workflow
- `TrustHierarchy`

---

## 8. 现在开始的执行基线

从这一刻起，后续推进不再只按“普通 orchestrator”思路，而是按这版生态蓝图推进。

### 当前最优先的实现顺序

#### 优先级 1

- `Human review gate`
- `ConvergenceReport`
- `StateCenter save/load`
- `Checkpoint-backed replan`
- `MemoryManager v1`

#### 优先级 2

- `LLMClient`
- Worker 接真实 LLM
- `Evaluator(L2)`
- `Guardrails v1`
- `FailureTaxonomy`

#### 优先级 3

- `SupervisorOrchestrator` 升级
- `ToolRegistry`
- `Analyze CLI`
- 第二个 workflow
- `TrustHierarchy`

---

## 9. 和当前项目的关系

这份文档是：

- **完整生态目标蓝图**

不是：

- 当前已经全部完成的状态

当前项目的关系应该这样理解：

- `docs/architecture.md`：当前可执行基线
- `docs/architecture.md`：当前可执行基线
- `docs/ecosystem_architecture_v2.md`：新的、更加完整的生态蓝图

后续如果有设计取舍或实现顺序冲突，以：

- **当前实现可落地**
- **但长期方向对齐生态 v2**

为原则。

---

## 10. 一句话总结

当前项目不再只是一个多 Agent 编排器，而是正式升级为：

**一个面向 AI 项目协作的多智能体生态运行时内核。**

这意味着后续所有实现，都应朝这 8 层完整生态方向推进。
