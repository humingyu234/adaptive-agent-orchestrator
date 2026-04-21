# Adaptive Agent Orchestrator

**Adaptive Agent Orchestrator is a reusable Agent Runtime Control Plane for building multi-workflow, evaluation-aware, recoverable agent systems.**

它不是一个固定的 AI Demo，也不是单一场景的 Agent App。
它是一层可复用的运行时内核，用来让 Agent Workflow 具备：

- **可编排（Orchestrated）**
- **可评估（Evaluated）**
- **可恢复（Recoverable）**
- **可审计（Auditable）**
- **可人工介入（Human-in-the-loop）**

> **这不是一个“会动的 Agent Demo”，而是一层让 Agent Workflow 真正变成可控系统的运行时底座。**

---

## Why This Project Exists

复杂 Agent 系统真正困难的地方，从来不是单次 LLM 调用，而是运行时控制：

- 多个 agent 如何分工并共享状态？
- 输出质量如何在运行时被检查？
- 失败后如何重试、回滚、重规划？
- 什么时候应该继续、降级、停机、转人工？
- 不同 agent 是否可以使用不同模型和工具？
- 整次执行过程如何被记录、审计和复盘？

`Adaptive Agent Orchestrator` 关注的不是“再做一个 Agent”，而是：

> **让 Agent Workflow 变成可控系统。**

---

## What Makes It Different

这个项目的重点不在“某个 prompt 写得多好”，而在：

- **runtime state governance**，而不是纯 prompt glue
- **evaluation-aware execution**，而不是 fire-and-forget agents
- **recoverability and replan**，而不是脆弱的一次性链路
- **human review and trust boundaries**，而不是失控自动化
- **workflow / provider / tool composability**，而不是单一 demo

它更像一个 **Agent Infra / Agent Runtime**，而不是一次性的聊天机器人项目。

---

## Core Pillars

### 1. Workflow Orchestration

把 agent 和 workflow 从代码里解耦，让不同角色、流程、工具和模型可以被组合、替换和复用。

当前能力包括：

- 可插拔 agent
- YAML workflow
- 自然语言 `ask` 入口
- LLM Router 自动分流
- `SupervisorOrchestrator` 总控编排
- per-agent LLM provider / model 配置

当前内置角色包括：

- `planner`
- `search` / `real_search`
- `summarizer`
- `supervisor`
- `human_review`

---

### 2. Runtime Evaluation & Control

系统不是“agent 跑完就算了”，而是在运行过程中持续检查、调整和收敛。

当前能力包括：

- `Evaluator L1`：结构检查
- `Evaluator L2`：语义质量检查
- retry / fail / continue
- checkpoint-backed replan
- supervisor revision
- rollback
- max step 收敛控制
- Guardrails
- trust hierarchy
- tool permission
- Human Review v2

这让流程更像一个可靠系统，而不是一串 prompt。

---

### 3. Recoverability & Observability

运行结果不只是一份最终输出，系统会自动沉淀完整的运行产物，便于恢复、分析和持续改进。

当前会自动生成：

- state persistence
- checkpoints
- execution logs
- convergence report
- memory bundle
- failure taxonomy
- regression compare
- analyze CLI

> 这些产物不是调试附属品，而是 runtime 可恢复、可审计、可持续迭代的基础设施。

---

## Validated Workflow Types

当前 runtime 已验证过以下几类工作流：

- **Research workflows**
  资料检索、总结、监督复核、人工审核

- **Service / support workflows**
  客服、工单、回复方案

- **Code / review workflows**
  代码审查、工具调用、过程控制

对应 workflow 文件包括：

- `deep_research.yaml`
- `deep_research_supervised.yaml`
- `deep_research_human_review.yaml`
- `customer_support_brief.yaml`
- `quick_search.yaml`
- `real_research.yaml`
- `code_review_pipeline.yaml`

---

## Quick Start

### 1. Install

```powershell
pip install -e .
```

如果要使用真实搜索或 HTTP LLM provider：

```powershell
pip install -e ".[all]"
```

---

### 2. Ask in natural language

```powershell
py -m orchestrator ask "研究固态电池商业化进展，需要主管复核"
```

---

### 3. Run with a workflow

```powershell
py -m orchestrator run --workflow workflows/deep_research.yaml --query "solid-state battery progress"
```

---

### 4. Test a single agent

```powershell
py -m orchestrator agent --name planner --query "solid-state battery progress" --format json
```

---

### 5. Review a human-review task

```powershell
py -m orchestrator review --task-id <task_id> --decision approve --reason "人工审核通过"
```

支持：

- `needs_human_review`
- `approve`
- `reject`
- approve 后继续执行后续 agent
- reject 后明确失败或按推荐目标回退

---

## Multi-Provider Runtime

项目支持多种 provider：

- `mock`
- `codex`
- `glm`
- `kimi`
- `deepseek`
- `openai`
- `anthropic`
- `ollama`

查看当前 provider 状态：

```powershell
py -m orchestrator providers --verbose
```

也可以让不同 agent 使用不同 provider / model：

```powershell
py -m orchestrator run `
  --workflow workflows/deep_research_supervised.yaml `
  --query "solid-state battery progress" `
  --agent-llm planner=codex:gpt-5.4,supervisor=deepseek:deepseek-chat
```

---

## Runtime Analysis

查看最近运行：

```powershell
py -m orchestrator analyze list --limit 10
```

查看某次详情：

```powershell
py -m orchestrator analyze show --task-id <task_id>
```

查看失败统计：

```powershell
py -m orchestrator analyze failures --limit 20
```

查看 memory：

```powershell
py -m orchestrator analyze memory
```

查看回归对比：

```powershell
py -m orchestrator analyze regression --find 10
```

---

## CLI Overview

### Task entry

```powershell
py -m orchestrator ask "自然语言任务"
```

### Workflow run

```powershell
py -m orchestrator run --workflow workflows/deep_research.yaml --query "任务"
```

### Single-agent debugging

```powershell
py -m orchestrator agent --name planner --query "任务"
```

### Inspect agents

```powershell
py -m orchestrator agents --verbose
```

### Inspect providers

```powershell
py -m orchestrator providers --verbose
```

### Human review

```powershell
py -m orchestrator review --task-id <task_id> --decision approve
py -m orchestrator review --task-id <task_id> --decision reject --reason "人工拒绝"
```

### Analyze backend

```powershell
py -m orchestrator analyze list --limit 10
py -m orchestrator analyze show --task-id <task_id>
py -m orchestrator analyze failures --limit 20
py -m orchestrator analyze memory
py -m orchestrator analyze regression --find 10
```

---

## Environment Variables

可以通过 `.env` 或系统环境变量配置 provider：

```env
LLM_PROVIDER=deepseek
LLM_DEFAULT_MODEL=deepseek-chat

DEEPSEEK_API_KEY=...
DEEPSEEK_API_BASE=https://api.deepseek.com/v1

GLM_API_KEY=...
GLM_API_BASE=...

KIMI_API_KEY=...
KIMI_API_BASE=https://api.moonshot.cn/v1
```

注意：`.env` 已被 `.gitignore` 排除，不要把 API Key 提交到 GitHub。

---

## Project Structure

```text
adaptive-agent-orchestrator/
├── src/orchestrator/
│   ├── agents/
│   ├── scheduler.py
│   ├── state_center.py
│   ├── evaluator.py
│   ├── evaluator_l2.py
│   ├── supervisor_orchestrator.py
│   ├── llm_client.py
│   ├── llm_providers.py
│   ├── memory_manager.py
│   ├── report_writer.py
│   ├── regression_compare.py
│   └── __main__.py
├── workflows/
├── tests/
├── docs/
├── examples/
├── PROJECT_STATE.md
├── PROJECT_LOG.md
└── README.md
```

---

## Runtime Maturity Snapshot

已完成并测试通过的主干能力：

- 多 agent workflow runtime
- `StateCenter` 共享状态
- checkpoint / rollback / replan
- Evaluator L1 + L2
- `SupervisorAgent` + `SupervisorOrchestrator`
- Human review approve / reject / resume
- `MemoryManager` 检索与沉淀
- `ToolRegistry`
- `Guardrails`
- Trust hierarchy
- LLM Provider abstraction
- Codex / DeepSeek 实机路径验证
- Analyze CLI
- RegressionCompare
- Natural-language `ask` + LLM Router

当前测试：

```powershell
$env:PYTHONPATH='src'; py -m unittest discover -s tests -p "test_*.py" -q
```

最近全量测试：`66 tests OK`

---

## Roadmap

接下来会继续增强：

- 接入已有 `deep_research_agent` 作为完整 research 能力模块
- 长任务阶段性 alignment check，减少长流程跑偏
- 更智能的 RegressionCompare
- 自动 Debug / Failure Analysis Agent
- 更完整的自然语言后台命令
- 给外部用户/朋友试用的最小体验手册

---

## Docs

- 当前状态：`PROJECT_STATE.md`
- 历史推进：`PROJECT_LOG.md`
- 当前架构：`docs/architecture.md`
- 完整生态蓝图：`docs/ecosystem_architecture_v2.md`
- 决策记录：`docs/decisions/`
- 项目关系：`docs/project_relationships.md`
- 成长路线：`docs/growth_path.md`

---

## One-line Summary

**Adaptive Agent Orchestrator 的目标不是让 Agent 更会“说”，而是让 Agent Workflow 更会“活”。**

它关注的不是生成一次答案，而是让整个执行过程具备控制、评估、恢复和复盘能力。
