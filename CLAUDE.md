# Adaptive Agent Orchestrator - Claude Code Working Guide

AAO 项目级操作指南。改代码前先读这个。遵循它除非用户明确推翻。

---

## 0. 新会话 Front Door

新开 Claude Code / Codex 会话接管 AAO 时，不要直接凭记忆判断功能状态。

先读 `AAO_FRONT_DOOR.md`，再做：

```bash
git status --short
python -m orchestrator front-door "<当前任务>"
```

Front Door 只做轻量分流：

- **small**：直接做，但先读相关源码再回答。
- **medium**：走 AAO controlled，使用真实 worker 时必须显式 `--worker-mode claude-code`。
- **large**：走 project session / milestone / resume。

没有源码、测试、或 artifact 证据前，不要说“没有这个功能”“已经接通”“测试通过”。

---

## 1. AAO 是什么

AAO 是 **Agent Runtime Control Plane**（Agent 运行时控制层）。

不是：
- Claude Code 替代品
- LangGraph 替代品
- 通用 all-in-one agent 框架
- tracing / eval / workflow 平台

是：
- agent 工作流的控制层
- 运行时裁判：继续 / 重试 / 重新规划 / 暂停等人工 / 回滚 / 失败
- evidence（证据）、live progress（实时进度）、failure classification（失败分类）、audit report（审计报告）系统

核心原则：更好的模型提升 agent **能力**。AAO 提升 agent **可靠性**——独立于模型和 worker 去判断每一步是否正确、有风险、不完整、可恢复。

---

## 2. 分层定义

```
Human → Claude Code frontend → AAO Control Plane → Runner → Worker
                                                      ↘ Reviewer (只读)
```

| 层 | 职责 |
|----|------|
| **Claude Code frontend** | 用户的主对话和编码界面 |
| **AAO Control Plane** | 运行时控制：任务分级、计划契约、策略、评估、护栏、失败分类、恢复、evidence、实时视图、人工审核、审计 |
| **Runner / Execution Engine** | 执行工作流结构（NativeRunner, LangGraphRunner）。是 runner，不是 worker。 |
| **Worker** | 执行具体步骤：Claude Code、LLM provider、TestWorker、ReviewWorker、HumanReviewer |
| **Reviewer** | 只读检查员，审查 worker 产出。不改代码。输出 ReviewFinding。 |
| **Human Reviewer** | 人工审批者，在 milestone gate 确认或拒绝 |
| **Project Session** | 跨任务持久层：项目记忆、milestone 状态、审批日志、会话标识 |

术语要严格。不要把 runner 叫 worker。不要让 reviewer 写代码。

---

## 3. 硬约束

除非用户明确要求，否则不做：

- 不重写 scheduler.py
- 不随意引入大框架（LangGraph、Langfuse、DeepEval、LiteLLM、OPA、Casbin）
- 不 claim evidence 除非代码真的记录了 observed evidence
- 不在默认控制路径上加额外 LLM 调用
- 不让简单任务被重型工作流拖慢
- 不让 AAO 偷偷自动修改 AAO 自己（src/orchestrator/*.py、CLAUDE.md、phase specs）
- 不编辑 .env、secrets、.venv、outputs/、tmp/ 除非任务需要

过度设计过滤器——加任何新子系统前先问：

```
能不能让 AI 任务执行更不容易跑偏？
能不能更早发现失败？
能不能减少浪费的时间/token？
能不能让 evidence 更可信？
能不能让运行时进度更可见？
能不能让 human review 更安全、时机更好？
能不能让项目更容易演示、审查、使用？
```

答案不是明确的"是"就推迟。偏好薄适配器而不是新平台。

控制循环焦点：

```
观察执行 → 检测异常 → 分类失败 → 选择有界恢复 → 记录 evidence → 暴露进度/审计状态
```

---

## 4. 工作模式

| 模式 | 说明 |
|------|------|
| **off** | 直接用 Claude Code。AAO 不参与。 |
| **log** | AAO 记录任务和结果，但不阻断或路由执行。 |
| **controlled** | 全控制：检查、evidence、失败分类、人工门、审计。 |
| **orchestrated** | 复杂 DAG：checkpoint、resume、分支、并行、人工中断。 |

任务分级：
- **small**（1-2文件、低风险、<30分钟）→ off / log
- **medium**（一个特性切片、多文件、需要测试）→ controlled
- **large**（多阶段、多 worker、长运行、可恢复）→ orchestrated

不要对小任务强加 AAO。

---

## 5. 施工入口

按 phase 施工。每个 phase 有独立 spec 在 `.claude/phase-specs/`。
做 phase 前必须读对应 spec。做完必须跑对应测试并中文汇报。

### Phase 00-21（已完成）

核心基础（0-7B）+ v1 产品发布（8-21）。spec 和代码均已完成。

### Phase 29（优先 — Runner 架构修正，建议在 22 之前做）

| Phase | 名称 | Spec |
|-------|------|------|
| 29 | Runner Architecture Boundary Cleanup | `phase-29-runner-architecture-boundary-cleanup.md` |

Phase 29 把已存在的 LangGraphRunner 接到 MainlineExecutor 主链路正确位置，
清理 native / langgraph / mainline / multi_worker 边界。v2 协作能力依赖干净的 runner 架构。

### Phase 22-28（v2 项目协作能力，建议 29 之后按序执行）

| Phase | 名称 | Spec |
|-------|------|------|
| 22 | Task Auto Repair Loop | `phase-22-task-auto-repair-loop.md` |
| 23 | Isolated Reviewer | `phase-23-isolated-reviewer.md` |
| 24 | Project Session Layer | `phase-24-project-session-layer.md` |
| 25 | Milestone Gate / Human Approval | `phase-25-milestone-gate-human-approval.md` |
| 26 | Project Resume + Interactive Ask | `phase-26-project-resume-and-interactive-ask.md` |
| 27 | AAO Self-Issue Handling | `phase-27-aao-self-issue-handling.md` |
| 28 | Project Collaboration Acceptance | `phase-28-project-collaboration-acceptance.md` |

完整 spec 文件索引见 `.claude/phase-specs/` 目录。

不要一次实现多个 phase。一次一个：读 spec → 实现 → 测试 → handoff → review。

---

## 6. Project Skills

操作检查清单在 `.claude/project-skills/`。当内部检查清单用，不是死板模板。

| Skill | 使用场景 |
|-------|---------|
| `aao-core-builder.md` | 修改 AAO 核心架构 |
| `aao-boundary-test-designer.md` | 添加或改变运行时行为前 |
| `aao-reviewer-mode.md` | 独立只读审查会话。Reviewer 必须隔离、只读、不信 worker 自述、输出 finding 不直接修。 |
| `aao-tutor-explanation.md` | 讲解：先举具体例子，再给直观图景，然后真实代码路径，最后工程术语。 |
| `aao-scope-guard.md` | 任务范围开始膨胀时 |
| `aao-live-visibility.md` | 实现运行时状态、进度、evidence、报告 |
| `aao-phase-handoff.md` | 停止工作或进入下一个 phase 前。必须说明真实 vs mock vs artifact 边界。 |

---

## 7. 提交纪律

- 绝不用 `git add .`
- 只 stage 明确文件列表
- phase spec 和代码分 commit
- 当前 phase 没测完不过审前，不开始下个 phase

提交前：

```bash
git status --short
git diff --check
python -m compileall -q src tests
python -m pytest -q
```

---

## 8. 测试标准

运行时控制变更必须覆盖：
- 坏 case 安全失败
- 正常 case 仍然通过
- 边界 case
- 误报防护
- 邻近回归路径
- phase 承诺了特定运行时路径时必须有 contract/path 测试

控制层变更：至少一个测试在实现只是"猜对了最终值"时会失败。

---

## 9. Reviewer 流程

1. 实施会话做最小的 phase 限定变更
2. 跑针对性测试 + 全量测试
3. 单独 reviewer 会话只读审查 diff
4. Reviewer 命名架构契约、追踪运行时路径、检查表面接线
5. P0 必须修、P1 应该修、P2 记录为跟进
6. 用户批准后才开始下个 phase

不要让同一个会话既实施又审批。

---

## 10. 完成定义

### Core Done (Phase 0-7B)
Control models、ControlPlane、EvidencePack、LiveRunView、Policy YAML 存在且经过测试。
失败分类明确传播，integration 测试覆盖 guardrail、human-review、evaluator-failure 等路径。

### v1 Product Release Done (Phase 0-21)
真实任务通过 Claude Code worker bridge 运行。Live Watch 显示进度和控制决策。
False completion 可被阻止。失败分类映射到恢复动作。Human review 可暂停/恢复。
Audit Report 含真实 observed evidence。Golden Scenario Suite 通过。

### v2 Collaboration Done (Phase 22-28)
见 `phase-28-project-collaboration-acceptance.md`。核心要求：复杂多阶段协作任务
（调研→对比→设计→审批→并行执行→独立审查→自动修复→milestone gate→resume+追问）
端到端跑通。

---

不夸证不举。Core 测试证明控制基础。v1 测试证明可用性。v2 测试证明多会话项目能力。
每层都要自己的 evidence。
