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
│ Planning Council → CouncilPlan (DAG: steps + deps + review)     │
└────────────────────────────┬─────────────────────────────────────┘
                             │ CouncilPlan
┌────────────────────────────▼─────────────────────────────────────┐
│ LAYER 3: EXECUTION FABRIC                            ← 新增      │
│ DAG Parser · Execution Router · Fan-out/Gather Engine           │
│ Worker Contract · Batch Scheduler · Result Merger               │
└────────────────────────────┬─────────────────────────────────────┘
                             │ ExecutionBatch[]
┌────────────────────────────▼─────────────────────────────────────┐
│ LAYER 4: RUNTIME CORE                                           │
│ Scheduler · StateCenter · Evaluator(L1/L2/L3)                  │
│ Convergence · Graceful Degradation · Execution Trace           │
└────────────────────────────┬─────────────────────────────────────┘
                             │ 调用
┌────────────────────────────▼─────────────────────────────────────┐
│ LAYER 5: WORKER AGENTS + GUARDRAILS                             │
│ Role + Backstory + Expected Output + Tools                      │
│ Input Guardrail → Agent → Output Guardrail                      │
└────────────────────────────┬─────────────────────────────────────┘
                             │ 调用
┌────────────────────────────▼─────────────────────────────────────┐
│ LAYER 6: TOOL REGISTRY                                          │
│ Search · CodeExec · FileIO · Browser · API · Database          │
└────────────────────────────┬─────────────────────────────────────┘
                             │ 读写
┌────────────────────────────▼─────────────────────────────────────┐
│ LAYER 7: SHARED CONTEXT                                         │
│ StateCenter + ProjectContext + Checkpoint Store                 │
└────────────────────────────┬─────────────────────────────────────┘
                             │ 沉淀
┌────────────────────────────▼─────────────────────────────────────┐
│ LAYER 8: MEMORY                                                 │
│ Short-term · Long-term · Entity · Procedural                   │
└────────────────────────────┬─────────────────────────────────────┘
                             │ 反馈
┌────────────────────────────▼─────────────────────────────────────┐
│ LAYER 9: FEEDBACK LOOP + EVAL SYSTEM                            │
│ Convergence Report · Failure Taxonomy · Regression Compare      │
└──────────────────────────────────────────────────────────────────┘
```

最白的话解释：

- Layer 1：人类可以随时插手
- Layer 2：总控层决定下一步谁干什么（Planning Council 多模型讨论出方案）
- Layer 3：执行分发层把方案翻译成并行/串行批次，管理 Worker 生命周期
- Layer 4：运行时负责调度、状态、评估、收敛
- Layer 5：真正干活的角色层
- Layer 6：工具层
- Layer 7：共享项目上下文
- Layer 8：长期记忆
- Layer 9：反馈闭环和评估系统

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

### CC Frontend Integration

AAO 设计为被 AI 前端（Claude Code、Codex 等）驱动，而非独立对终端用户暴露 CLI。

交互协议：

```
用户（自然语言）
    |
    v
┌─────────────────────────────────────────────────┐
| Claude Code（Human Interface 层）                 |
|                                                  |
| · 理解用户意图                                    |
| · 渲染 Execution Plan Preview 给你看              |
| · 在 review point 展示结果并等待你的确认           |
| · 接收你中途的修改指令（如“P2 别改了”）           |
| · 格式化最终产物展示给你                          |
└─────────────────────────────────────────────────┘
                   | ask / run / inject / resume / status
                   v
┌─────────────────────────────────────────────────┐
| AAO（Runtime Engine）                             |
|                                                  |
| · Planning Council → 讨论出 Execution Plan       |
| · Scheduler → 执行循环，收敛控制                  |
| · Evaluator → L1 结构 + L2 语义双重质量检查       |
| · Checkpoint → 每步断点持久化，支持回滚           |
└─────────────────────────────────────────────────┘
```

CC 与 AAO 之间的命令协议：

| 命令 | 方向 | 作用 |
|------|------|------|
| `ask` | CC → AAO | 提交自然语言任务，返回 execution plan preview |
| `run` | CC → AAO | 确认计划，开始执行 |
| `status` | CC → AAO | 查询任务进度和当前状态 |
| `inject` | CC → AAO | 运行时注入修改指令 |
| `resume` | CC → AAO | 在 review point 确认后继续执行 |
| `abort` | CC → AAO | 中止当前任务 |

**关键设计决策：** AAO 不需要自己实现自然语言理解、格式化渲染、对话管理等用户界面能力。
Claude Code 天然提供了这些——它是对话循环，用户的每一句话就是 interrupt。
AAO 只需要暴露结构化的命令接口和状态查询。

LiveInterrupt 的 signal file 机制（`live_interrupt.py`）保留给**非 CC 场景**：
后台进程通过写 signal file 触发中断、从另一个终端发 abort 信号等。
在 CC 驱动的交互模式下，这些能力由 CC 直接调用命令接口完成。

### 长 Worker 中断机制

**当前限制：** LiveInterrupt 只在 agent 执行完成后的 step 边界检查信号文件。如果 worker 正在等待慢 LLM 响应（30 秒+），用户的 abort/inject 指令不会立即生效，必须等当前 step 跑完。

```
用户喊 "停！方向错了！"
      |
      +-- worker 正在等 LLM 返回（可能 30 秒+）
      +-- Scheduler 在循环末尾才读 interrupt file
          -> 用户干等
```

**解决方案（两阶段）：**

**阶段一：超时 + 轮询检查**
- 每个 agent 执行加 `execution_timeout` 配置（默认 120 秒，可声明式覆盖）
- agent 内部在等待 LLM 时，每 N 秒检查一次 `LiveInterruptController.is_signaled()`
- 超时或收到中断信号后，agent 标记失败，Scheduler 按 retry -> fail -> re-plan 正常流程处理

**阶段二：异步取消**
- LLM 调用改用 async SDK（Claude/OpenAI/DeepSeek 均支持 async + abort）
- Scheduler 维护每个 running agent 的 task handle
- LiveInterrupt 触发时，直接 `task.cancel()` -> `asyncio.CancelledError` -> agent cleanup -> 进入 re-plan

阶段一改动量小，覆盖 80% 的痛点场景。阶段二需要 Scheduler 循环从同步改异步，改动较大。



### 产物输出策略

**问题：** 一次运行产出 6+ 个 JSON 文件（execution_trace / checkpoint / state / report / memory / convergence_report），审计能力强但普通用户只看结果：

```
outputs/
├── states/task_xxx.json
├── checkpoints/task_xxx/  (每步一个快照)
├── reports/task_xxx.json
├── memory/task_xxx.json
├── convergence_report.json
└── regression_compare.json
```

**设计决策：默认输出人读格式，JSON 留给调试/审计。**

`--format text` 已实现：一次运行后输出一段摘要，包含执行步骤、每步耗时、provider/model、评估结果、supervisor 判断、产物路径。用户不需要知道底下有 6 个文件。

```
====================================================================
  Task: 研究 AI agent runtime 的关键能力
  Workflow: deep_research | Status: OK completed
  Duration: 3.2s | Steps: 5
====================================================================
  Execution:
    planner      pass   0.3s  (openai/worker)
    search       pass   1.2s  (tool)
    summarizer   pass   0.5s  (anthropic/worker)
    supervisor   pass   0.4s  (mock/orchestrator)

  Evaluations: 5 total | 0 failed
  Supervisor: accept
  Products:
    report: outputs/reports/abc123.json
====================================================================
```

CC 驱动时，这个 text 输出由 CC 进一步格式化为对话气泡、表格、折叠区等，用户体验更好。

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


### Task Complexity Fast-Path

Planning Council 不能默认用于所有任务，否则简单任务会被多模型规划成本拖慢。
用户在说"帮我解释一下这块代码"时，不可能等 2 分钟走完 Planning Council → Execution Fabric 全套流程。

**三级分流机制：**

```
用户任务
    |
    v
+--------------------------+
| Complexity Classifier     |  ← 规则 + 轻量 LLM
+--------------------------+
           |
           +-- simple  --> 单次 LLM 调用，不走 workflow，直接返回
           |               "解释这段代码" / "FastAPI middleware 怎么写"
           |
           +-- medium  --> 走 workflow，但跳过 Planning Council
           |               planner → search → summarizer（串行）
           |               "比较 React 和 Vue 的响应式原理"
           |
           +-- complex --> 完整 Planning Council → Execution Fabric → Review
                           "审查 TIP 项目代码质量，找出问题并给出改进方案"
```

**分类信号：**

| 信号 | 倾向 | 示例 |
|------|------|------|
| 单文件、单模块、纯解释 | simple | "讲讲 processor.py 这段在做什么" |
| 涉及多文件、需要对比分析 | medium | "比较 store.py 的三种运行模式" |
| 有依赖顺序（"先…再…"） | complex | "先审查代码质量，再出改进 PR" |
| 要求产出文件/代码 | medium+ | "写一个 FastAPI rate limit middleware" |
| 要求多步骤 + 质量审查 | complex | "审查整个项目的安全和性能问题" |
| 显式多轮确认要求 | complex | "每完成一个阶段找我确认一下" |

**实现策略：**

1. **第一阶段（规则）** — 关键词 + 正则匹配覆盖 80% case，零延迟
2. **第二阶段（轻量 LLM）** — 规则无法判断时，用最便宜的 haiku 模型做二分类
3. **第三阶段（学习）** — 用户的历史纠正反馈用于优化分类器

**核心原则：简单问题不应该比直接问 Claude Code 更慢。**

**为什么必须做 Fast-Path：Planning Council 的成本量化**

以"搜点资料总结一下"这种常见任务为例：

```
Planning Council 路径:
  规划: strategist(1次LLM) + executor(1次LLM) + risk_analyst(1次LLM) + CouncilMerger(1次LLM)
       = 4次LLM调用，~5秒，用户等着
  执行: search(1次LLM) + summarizer(1次LLM)
       = 2次LLM调用，~3秒
  总计: 6次LLM，8秒，规划成本(67%) > 执行成本(33%)

Fast-Path (medium):
  直接走 planner → search → summarizer
       = 3次LLM，~4秒

直接问 Claude Code:
  1次LLM，~2秒
```

没有 Fast-Path 的系统，用户问一句"帮我解释这个"也要等 Planning Council 讨论完再执行。第一次用就会放弃。

如果一句"帮我解释这个"要等 Planning Council 讨论完再跑 workflow，用户在第一次使用后就不会再用第二次。

---

### Layer 3：Execution Fabric（新增 — 并行执行与任务分发）

这是 v2 生态蓝图补齐的关键一层。

在 Planning Council 输出 DAG 方案后，Execution Fabric 负责：

- 理解任务之间的依赖关系（什么可以并行、什么必须串行）
- 将 DAG step 翻译为执行批次 `ExecutionBatch[]`
- 管理多 Worker 的生命周期（启动、监控、超时、取消）
- 并行结果合并策略（all / any / majority / first / degrade）
- Worker 失败协议（超时、格式错误、部分完成、拒绝执行）
- 并行执行与 checkpoint 持久化之间的一致性

**这一层的目标不是"把多个 Worker 同时跑起来"，而是"跑错了能兜住、跑慢了能取消、跑丢了能恢复"。**

详细设计见：`docs/design_execution_fabric.md`

### Execution Fabric 最小版实现策略

当前 Layer 3 设计完整但代码为零。如果先实现 Planning Council 再实现 Execution Fabric，会陷入"能规划出精妙并行方案、但执行引擎只能串行跑"的尴尬。

**最小版目标（先做）：**

```
Planning Council 方案:
  steps: [{id:1, deps:[]}, {id:2, deps:[]}, {id:3, deps:[]}, {id:4, deps:[1,2,3]}]

Execution Fabric 最小版:
  Batch 1: asyncio.gather(step1, step2, step3)  # 无依赖，并行
  Batch 2: step4                                  # 依赖 1/2/3，串行等待
```

实现要素：
1. DAG 拓扑排序 — 识别哪些节点没有未满足的依赖
2. 同批并行 — `asyncio.gather()` 跑同一批次的所有节点
3. 单一合并策略 — 先用 `gather_strategy=all`（全部完成才继续），后续再加 any/majority/first/degrade
4. 不进 Worker Contract — 先复刻现有 Agent 调用，不引入 CCWorkerAdapter

**最小版能立刻带来的收益：**
- "搜索三家云厂商 GPU 定价"从串行 15 秒变并行 5 秒
- 不改变 Scheduler 主循环结构，只改 `_execute_batch()` 内部

**完整版再补：**
- 5 种 gather_strategy（all / any / majority / first / degrade）
- Worker Contract + CCWorkerAdapter（`##RESULT:` 标记协议）
- 长 Worker 超时/取消/重试
- 动态资源分配

> 优先级判断：Execution Fabric 最小版应该在 Planning Council 之前做。能并行跑简单 workflow 比能规划复杂 workflow 但只能串行跑更有实际价值。


---

### Layer 4：Runtime Core

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

### Durable Task State（崩溃恢复）

当前 checkpoint 在进程优雅退出时正常工作。但如果进程被 kill -9、机器重启、OOM，中间状态会丢失。

Durable Task State 要解决的是：**下次启动时，系统自己能发现未完成任务，找到最近 checkpoint，从断点继续。**

```
崩溃前:
  $ python -m orchestrator run --workflow xxx --query "审查 TIP 项目"
  [planner 完成 ✓]
  [search 完成 ✓]
  [summarizer 执行中... 进程崩溃 ✗]

恢复:
  $ python -m orchestrator run --resume
  "检测到未完成任务 task_abc123
   最近 checkpoint: search 之后 (node_index=2)
   将从 summarizer 继续。确认？[y/n]"

  [summarizer 从崩溃前的 checkpoint 恢复，继续执行]
  [supervisor 完成 ✓]
  → completed
```

**实现方案（不改变 Scheduler 主循环）：**

1. `Scheduler.run()` 新增 `resume_task_id` 可选参数
2. 如果传入 `resume_task_id`：
   - 从 `outputs/states/{task_id}.json` 恢复 StateCenter
   - 从 `outputs/checkpoints/{task_id}/` 找最近 checkpoint 的 `node_index`
   - `_execute_agents()` 从该 index 继续
3. CLI 新增: `py -m orchestrator run --resume` 自动扫描 `outputs/states/` 中 status 不为 completed 且不为 failed 的未完成任务
4. 恢复时保留原有 `task_id`，确保产物路径和 memory index 一致

**与 checkpoint-backed replan 的关系：**

| | checkpoint-backed replan | Durable Task State |
|---|---|---|
| 触发方式 | 计划内（supervisor 主动触发） | 计划外（进程崩溃后被动续接） |
| 数据来源 | 同一进程内的 checkpoint 快照 | 磁盘上的持久化 state + checkpoint |
| 恢复入口 | `_execute_agents` 循环内跳转 | CLI `--resume` → `_execute_agents(start_index=N)` |
| 共用 | StateCenter.load_from() + checkpoint store | 同一套持久化基础设施 |


---

### Layer 5：Worker Agents + Guardrails

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

### Layer 6：Tool Registry

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

### Layer 7：Shared Context

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

### Layer 8：Memory

完整记忆分四层：

- `Short-term`
- `Long-term`
- `Entity`
- `Procedural`

另外还有一层很重要的：

- `Failure Memory`

这层非常贴当前项目路线，因为它和 future evaluate system、failure taxonomy、regression 全能接起来。

#### 检索方案

当前实现基于 token 重叠（关键词匹配），长期不可持续。完整版检索应升级为：

- **向量检索**：对 memory entry 的 `query + summary_conclusion` 做 embedding，用余弦相似度排序
- **fallback 到关键词**：cold start 阶段 embedding 不可用时，保留 token 重叠作为降级方案
- **top_k = 3~5**：检索结果不超过 5 条，避免注入过多噪声
- **相似度阈值**：低于阈值的 memory 不返回，即使 top_k 不满
- **时效衰减**：旧记忆应有权重衰减，新记忆优先
- **Failure Memory 特殊处理**：同类型失败记忆应优先匹配，用于防止重复踩坑

实现路径：先在 `MemoryManager.retrieve()` 里加 embedding 分支，用项目已有的 LLM provider 生成向量，不引入新的向量数据库依赖。

---

### Layer 9：Feedback Loop + Eval System

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

### 已完成的模块

**Layer 1 — Human Interface:**
- CLI 入口（`__main__.py`，支持 ask/run/review/resume/status/analyze/agent 等命令）
- Human Review Gate（声明式 terminal_behavior，await_human 暂停语义）
- Live Interrupt（ABORT/PAUSE/SKIP/INJECT，signal file 机制）

**Layer 2 — Supervisor Orchestrator:**
- SupervisorOrchestrator + TaskLedger（任务账本，PENDING/IN_PROGRESS/BLOCKED/COMPLETED/FAILED）
- Stall 检测（连续 N 轮无进展 → re_plan）
- 动态 revise 路由（supervisor 建议 → Scheduler 响应）
- LLM Router（自然语言 → workflow 自动选择）

**Layer 3 — Execution Fabric:**
- ❌ 设计完成（`docs/design_execution_fabric.md`），代码未实现

**Layer 4 — Runtime Core:**
- Scheduler（主执行循环，retry/fail/re-plan/human_review/live_interrupt 完整分支）
- StateCenter + DataPool + ConvergenceState（save/load 持久化）
- Evaluator L1（声明式 criteria，路径解析 + 类型 + 列表大小 + 允许值）
- Evaluator L2（6 种语义检查，加权评分，预定义规则）
- Checkpoint 持久化 + Rollback + Checkpoint-backed replan

**Layer 5 — Worker Agents + Guardrails:**
- 7 个 Agent（Planner/Search/Summarizer/Supervisor/HumanReview/Sales/CodeReviewer）
- Guardrails v1（input: 非空 query 检查，output: 敏感词拦截）
- Trust Hierarchy（agent.trust_level vs tool.risk_level）
- 声明式 terminal_behavior + eval_criteria

**Layer 6 — Tool Registry:**
- ToolRegistry + ToolSpec（risk_level）
- Mock 工具 + 真实工具（DuckDuckGo/Tavily/Serper）

**Layer 7 — Shared Context:**
- StateCenter + ProjectContext + Checkpoint Store
- 三处协同（内存 + 文件系统 + checkpoint）

**Layer 8 — Memory:**
- MemoryManager（五类记忆：Short/Long/Entity/Procedural/Failure）
- 可检索/可复用（token 重叠匹配 + index）

**Layer 9 — Feedback Loop + Eval System:**
- ConvergenceReport（timeline/flow/control/quality/artifact/audit）
- FailureTaxonomy（22 种失败分类 + 4 级严重度）
- RegressionCompare（no_regression/minor/major/improvement）
- Analyze CLI（list/show/failures/agents/memory/regression/health）

### 当前离完整生态还差什么

**未实现（有设计，待开发）：**
- Layer 3 Execution Fabric 全部（DAG Parser / Execution Router / Fan-out-Gather / Worker Contract）
- Planning Council 多模型讨论（`docs/design_multi_model_planning_council.md` 设计已完成）
- Durable Task State 崩溃恢复（本页 Layer 4 已补充设计）
- Task Complexity Fast-Path（本页 Layer 2 已补充设计）
- Review Policy 三级（before_execute / before_final / every_stage）
- Evaluator L3
- 长 Worker 中断机制（本页 Layer 1 已补充两阶段方案）

**未设计（仅记账，需补充设计）：**
- background queue / overnight summary

### 总体评估

- 9 层架构中 8 层已有代码实现
- Layer 3（Execution Fabric）设计完成待实现
- 整体代码完成度约 70-75%
- 最核心的差异化能力（Planning Council + Execution Fabric）是下一阶段的实现重点

---

## 8. 现在开始的执行基线

从这一刻起，后续推进不再只按“普通 orchestrator”思路，而是按这版生态蓝图推进。

### 当前最优先的实现顺序

#### 优先级 1（核心体验打穿）

- Task Complexity Fast-Path（简单/中等/复杂分流）
- Planning Council 多模型讨论
- Execution Plan Preview（`ask --preview-only`）
- Review Policy 接入 Scheduler（before_execute / before_final）

#### 优先级 2（补齐缺失层）

- Execution Fabric 最小版（DAG 拓扑排序 + gather_strategy=all）
- Durable Task State 崩溃恢复
- Evaluator L3
- 长 Worker 中断机制（本页 Layer 1 已补充两阶段方案）

#### 优先级 3（打磨）

- Memory 检索升级（关键词 → 向量检索 + 时效衰减）
- Worker Agent 角色增强（role + backstory + goal）
- CC ↔ AAO 交互协议标准化

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

这意味着后续所有实现，都应朝这 9 层完整生态方向推进。
