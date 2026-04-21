# Adaptive Agent Orchestrator

一个面向 **多 Agent 协作、运行时评估、可恢复执行和人类介入** 的轻量级 Agent Runtime。

它不是一个固定的 AI Demo，而是一个可复用的多智能体编排底座：你可以在上面接入不同的 agent、workflow、tools 和 LLM provider，让系统按任务需要自动组织执行。

> 简单说：这是一个让多个 AI agent 像一个团队一样协作的运行时平台。

---

## 这个项目解决什么问题

单个 LLM 调用很容易做到，但真正做复杂任务时会遇到这些问题：

- 多个 agent 怎么分工？
- 中间状态怎么共享？
- 哪一步失败了怎么恢复？
- 输出质量怎么在运行时检查？
- 什么时候继续、重试、回滚、转人工？
- 不同 agent 能不能使用不同模型和工具？
- 跑完以后怎么复盘整次执行过程？

`Adaptive Agent Orchestrator` 解决的就是这些 **Agent 工程化问题**。

---

## 核心亮点

### 1. 可插拔 Agent

每个 agent 都有清晰契约：

- 读什么状态
- 写什么结果
- 能用什么工具
- 使用什么 trust level
- 是否需要 human review
- 使用什么 LLM profile / provider

当前内置角色包括：

- `planner`：任务规划
- `search` / `real_search`：检索资料
- `summarizer`：总结输出
- `supervisor`：过程复核与修正建议
- `human_review`：人工审核关口

---

### 2. 可插拔 Workflow

workflow 不是写死在代码里的，而是 YAML 配置。

当前已有：

- `deep_research.yaml`
- `deep_research_supervised.yaml`
- `deep_research_human_review.yaml`
- `customer_support_brief.yaml`
- `quick_search.yaml`
- `real_research.yaml`
- `code_review_pipeline.yaml`

这意味着同一个 runtime 可以承载不同类型任务。

---

### 3. 自然语言入口 + LLM Router

你可以用更自然的方式启动任务：

```powershell
py -m orchestrator ask "研究固态电池商业化进展，需要主管复核"
```

`ask` 会先通过轻量 LLM Router 判断任务意图，再选择合适 workflow；如果 router 不可用，会自动 fallback 到规则路由。

当前支持自动分流到：

- `deep_research`
- `deep_research_supervised`
- `deep_research_human_review`
- `customer_support_brief`

---

### 4. 运行时评估与收敛控制

系统不是“agent 跑完就算了”，而是在运行过程中持续检查：

- `Evaluator L1`：结构检查
- `Evaluator L2`：语义质量检查
- retry / fail / continue
- checkpoint-backed replan
- supervisor revision
- rollback
- max step 收敛控制

这让流程更像可靠系统，而不是一串 prompt。

---

### 5. Human Review v2

系统可以在关键节点暂停给人确认：

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

### 6. 多 LLM Provider

项目支持多种调用模式：

- `mock`：本地 mock provider
- `codex`：本地 Codex CLI
- `glm`：OpenAI-compatible HTTP API
- `kimi`：OpenAI-compatible HTTP API
- `deepseek`：OpenAI-compatible HTTP API
- `openai`：OpenAI-compatible HTTP API
- `anthropic`：Anthropic Messages API
- `ollama`：本地 Ollama CLI

查看当前 provider 状态：

```powershell
py -m orchestrator providers --verbose
```

也可以让不同 agent 使用不同模型：

```powershell
py -m orchestrator run `
  --workflow workflows/deep_research_supervised.yaml `
  --query "solid-state battery progress" `
  --agent-llm planner=codex:gpt-5.4,supervisor=deepseek:deepseek-chat
```

---

### 7. Memory / Report / Analyze 后台

每次运行都会自动沉淀：

- state
- checkpoints
- execution logs
- convergence report
- memory bundle

你可以查看最近运行：

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

## 快速开始

### 1. 安装依赖

```powershell
pip install -e .
```

如果要使用真实搜索或 HTTP LLM provider：

```powershell
pip install -e ".[all]"
```

### 2. 运行最简单任务

```powershell
py -m orchestrator ask "帮我做一个行业研究"
```

### 3. 指定 workflow 运行

```powershell
py -m orchestrator run --workflow workflows/deep_research.yaml --query "solid-state battery progress"
```

### 4. 单独测试某个 agent

```powershell
py -m orchestrator agent --name planner --query "solid-state battery progress" --format json
```

### 5. 使用真实 provider

```powershell
py -m orchestrator agent --name planner --query "solid-state battery progress" --llm codex --model gpt-5.4
```

---

## CLI 总览

### 任务入口

```powershell
py -m orchestrator ask "自然语言任务"
```

### 指定 workflow

```powershell
py -m orchestrator run --workflow workflows/deep_research.yaml --query "任务"
```

### 单 agent 调试

```powershell
py -m orchestrator agent --name planner --query "任务"
```

### 查看 agent

```powershell
py -m orchestrator agents --verbose
```

### 查看 provider

```powershell
py -m orchestrator providers --verbose
```

### 人工审核

```powershell
py -m orchestrator review --task-id <task_id> --decision approve
py -m orchestrator review --task-id <task_id> --decision reject --reason "人工拒绝"
```

### 后台分析

```powershell
py -m orchestrator analyze list --limit 10
py -m orchestrator analyze show --task-id <task_id>
py -m orchestrator analyze failures --limit 20
py -m orchestrator analyze memory
py -m orchestrator analyze regression --find 10
```

---

## 环境变量

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

## 项目结构

```text
adaptive-agent-orchestrator/
├── src/orchestrator/
│   ├── agents/                  # 内置 agents
│   ├── scheduler.py             # Runtime 调度器
│   ├── state_center.py          # 共享状态中心
│   ├── evaluator.py             # L1 结构评估
│   ├── evaluator_l2.py          # L2 语义评估
│   ├── supervisor_orchestrator.py
│   ├── llm_client.py
│   ├── llm_providers.py
│   ├── memory_manager.py
│   ├── report_writer.py
│   ├── regression_compare.py
│   └── __main__.py              # CLI 入口
├── workflows/                   # YAML workflows
├── tests/                       # 回归测试
├── docs/                        # 架构与决策文档
├── examples/                    # 示例 agent
├── PROJECT_STATE.md
├── PROJECT_LOG.md
└── README.md
```

---

## 当前能力状态

已完成并测试通过的主干能力：

- 多 agent workflow runtime
- StateCenter 共享状态
- checkpoint / rollback / replan
- Evaluator L1 + L2
- SupervisorAgent + SupervisorOrchestrator
- Human review approve / reject / resume
- MemoryManager 检索与沉淀
- ToolRegistry
- Guardrails
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

## 和普通 Agent Demo 的区别

这个项目重点不在“某个 prompt 写得多好”，而在：

- 运行时状态治理
- 多 agent 协作契约
- 过程评估与失败处理
- 人类介入和恢复执行
- 可审计的执行报告
- 可扩展的 provider / workflow / tool 层

它更像一个 **Agent Infra / Agent Runtime**，而不是一次性的聊天机器人。

---

## 后续方向

接下来会继续增强：

- 接入已有 `deep_research_agent` 作为完整 research 能力模块
- 长任务阶段性 alignment check，减少长流程跑偏
- 更智能的 RegressionCompare
- 自动 Debug / Failure Analysis Agent
- 更完整的自然语言后台命令
- 给外部用户/朋友试用的最小体验手册

---

## 文档导航

- 当前状态：`PROJECT_STATE.md`
- 历史推进：`PROJECT_LOG.md`
- 当前架构：`docs/architecture.md`
- 完整生态蓝图：`docs/ecosystem_architecture_v2.md`
- 决策记录：`docs/decisions/`
- 项目关系：`docs/project_relationships.md`
- 成长路线：`docs/growth_path.md`

