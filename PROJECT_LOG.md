# 项目日志

## 2026-04-11

### 项目创建

- 新建独立项目 `adaptive-agent-orchestrator`
- 明确这个项目不是继续塞进 `deep_research_agent`，而是一个新的通用编排引擎仓库

### 项目定位确认

- 项目目标：构建一个轻量级多 Agent 编排与评估引擎
- 核心差异化：运行时评估、动态调整、诚实降级、强制收敛
- 技术栈：Python + Pydantic + PyYAML + CLI

### 架构基线确认

- 采用“多 Agent 编排与评估系统架构设计（完整版 v2）”作为当前设计基线
- 关键增强包括：
  - Checkpoint 快照回滚
  - EvalCriteria 显式配置表
  - Workflow 条件边
  - Schema 写入契约
  - 三类可观测性
  - 四级诚实降级
  - 显式注册表

### 已完成内容

- 创建项目目录骨架
- 创建 `README.md`
- 创建 `pyproject.toml`
- 创建 `PROJECT_STATE.md`
- 创建 `src/orchestrator/` 基础源码骨架
- 创建 `workflows/deep_research.yaml`

### 当前判断

- 架构阶段已经足够，不再继续空转打磨概念
- 下一步应进入 Phase 1：把骨架变成最小可运行内核

### 编码与文档要求

- 本项目所有源码、Markdown、YAML、JSON 文件统一使用 UTF-8
- 中文文档优先保持可读、结构化，不允许出现乱码文本
- 如果编码安全与开发速度冲突，编码安全优先

## 2026-04-13

### 文档路线补齐

- 补充 `docs/workflow_evolution.md`
  - 记录为什么当前仍以对话框模式开发为主
  - 记录如何从当前模式过渡到 1 主 1 辅，再到总控式多 Agent 工作流
- 补充 `docs/project_relationships.md`
  - 记录 `deep_research_agent`、future evaluate system、`adaptive-agent-orchestrator` 三者关系
- 更新 `README.md`
  - 把上述文档接入主入口
- 更新 `PROJECT_STATE.md`
  - 把工作方式与项目关系正式记为当前共识

### 当前阶段性结论

- 当前新项目不仅有架构设计，也已经有了开发方式路线和项目边界说明
- 后续不需要再靠聊天记录回忆“为什么做这个引擎”和“它和另外两条线是什么关系”
- 接下来可以更专注地进入 Phase 1 的最小可运行内核实现

## 2026-04-14 市场信号与能力积累方向
- 新增 docs/market_signals_and_skill_focus.md
- 基于真实岗位信号整理值得优先积累的 5 个能力
- 在 README 和 PROJECT_STATE.md 中加入该文档入口


## 2026-04-15 设计文档重写与基线对齐
- 重写 docs/architecture.md，按最新设计基线整理为 UTF-8 中文版
- 同步更新 PROJECT_STATE.md，使其与最新 Human -> Supervisor -> Worker 设计一致
- 明确当前 Phase 1 MVP：Evaluator(L1)、Scheduler 收敛保护、3 个最小 Worker Agents、CLI 与日志


## 2026-04-15 最终版形态与一周冲刺边界拆分
- 新增 docs/final_target_architecture.md，单独记录完整最终版形态
- 重写 docs/architecture.md，明确区分长期目标与当前一周实现范围
- 更新 PROJECT_STATE.md，使当前冲刺目标与最终版目标分离展示


## 2026-04-15 决策记录体系初始化
- 新增 docs/decisions/README.md 作为决策记录索引
- 新增 docs/decisions/000-template.md 作为统一决策模板
- 在 README 和 PROJECT_STATE.md 中加入决策记录入口

## 2026-04-15 Phase 1 Runtime Core 首轮落地
- 实现 `Evaluator(L1)`，覆盖 planner/search/summarizer 的最小规则检查
- 重写 `Scheduler`，补齐 retry 上限、fail 路径和最简结构化执行日志
- 补齐 `PlannerAgent`、`SearchAgent`、`SummarizerAgent` 三个最小 Worker Agents
- 新增 CLI 入口：`py -m orchestrator run --workflow ... --query ...`
- 新增 workflow loader 的无依赖 fallback，避免本机缺少 `PyYAML` 时无法运行
- 新增 `tests/test_runtime_smoke.py`，验证 `deep_research` workflow 能端到端完成
- 新增第一篇决策记录：`docs/decisions/001-phase1-runtime-core.md`


## 2026-04-15 README 按最新设计重写
- README 更新为当前设计基线 + 最终目标形态双层表述
- 明确 Human -> Supervisor -> Worker 的长期层级
- 明确本周必须完成的 v1 final runtime core 范围
- 补齐文档导航、图示入口和项目价值说明


## 2026-04-15 Claude Code 设计学习点沉淀
- 新增 docs/claude_code_learnings.md
- 记录值得学习的 5 个方向：repo-as-context、plugin/adapter、durable runtime、Supervisor layer、feedback loop
- 在 README 和 PROJECT_STATE.md 中加入该文档入口

## 2026-04-15 Supervisor Layer 首轮落地
- 新增 `SupervisorAgent`，作为最小总控代理骨架
- 在 `Evaluator(L1)` 中加入 supervisor 输出检查
- 新增 `workflows/deep_research_supervised.yaml`
- smoke test 扩展为同时验证普通 workflow 和 supervised workflow
- 新增决策记录：`docs/decisions/002-supervisor-layer.md`

## 2026-04-15 Supervisor 过程感知增强
- 扩展 `StateCenter.prepare_view()`，允许按需暴露 `execution_trace`、`retry_counters`、`global_step`、`status`、`failure_reason`
- 重写 `SupervisorAgent`，让其从“只看最终结果”升级为“能读取执行过程并输出 process_review”
- smoke test 增加对 `process_review` 的断言，确保监督层不仅存在，而且真的拿到了过程信息
- 新增决策记录：`docs/decisions/003-supervisor-process-awareness.md`

## 2026-04-15 Supervisor 结构化修正建议
- 增强 `SupervisorAgent` 输出，新增 `review_reason`、`suggested_target`、`suggested_action`
- 让 supervisor 不只判断 accept / revise，还能明确指出建议回到哪一层修正
- 为正常 workflow 增加“接受建议”断言，并新增直接单测验证 revise 场景下的结构化建议
- 新增决策记录：`docs/decisions/004-supervisor-structured-guidance.md`

## 2026-04-15 Supervisor 建议路由进入 Scheduler
- 重写 `scheduler.py` 为干净 UTF-8 版本，清理旧乱码
- 新增最小 Supervisor 建议路由：当 `next_action=revise` 且目标节点合法时，Scheduler 可跳回该节点重新执行
- 增加 `max_supervisor_revisions` 保护，避免 Supervisor 驱动回路无限循环
- 新增单测验证 Scheduler 能识别并执行 Supervisor 的建议路由
- 新增决策记录：`docs/decisions/005-supervisor-guidance-routing.md`

## 2026-04-15 最小 re_plan 信号接入
- 重写 `SupervisorAgent` 为干净 UTF-8 版本，清理旧乱码
- 让 Supervisor 开始区分“普通修补”和“规划层需要重来”
- 当规划阶段不稳时，Supervisor 输出 `suggested_target=planner` 与 `suggested_action=re_plan`
- Scheduler 在收到最小 `re_plan` 建议时，会回到 `planner` 并清理依赖旧规划的下游状态
- 新增单测验证：
  - Supervisor 能发出 `re_plan`
  - Scheduler 会清理旧 plan / raw_documents / summary
- 新增决策记录：`docs/decisions/006-minimal-replan-signal.md`

## 2026-04-15 设计基线升级为生态 v2
- 新增 `docs/ecosystem_architecture_v2.md`
- 正式把项目目标从“多 Agent 编排内核”升级为“多智能体生态运行时内核”
- 将 README、PROJECT_STATE、next_session_handoff 对齐到生态 v2 蓝图
- 明确后续执行优先级调整为：
  - checkpoint / save-load / replan
  - ConvergenceReport
  - Human review gate
  - MemoryManager v1

## 2026-04-15 docs 清理与入口收敛
- 清理了已被新版生态蓝图替代的旧文档与旧图片：
  - `docs/architecture-overview.svg`
  - `docs/ecosystem-vs-runtime.png`
  - `docs/human-supervisor-workers.png`
  - `docs/final_target_architecture.md`
  - `docs/README.md`
- 把剩余主入口统一到：
  - `docs/architecture.md`
  - `docs/ecosystem_architecture_v2.md`
  - `docs/next_session_handoff.md`
- 修正旧引用，避免清理后留下断链

## 2026-04-15 Phase 2A 首轮落地
- `StateCenter` 补齐基础 `save/load` 能力，支持完整状态序列化与恢复
- checkpoint 从内存快照升级为磁盘持久化产物，落到 `outputs/checkpoints/<task_id>/`
- `Scheduler` 不再只做“清状态重来”，而是会在 `re_plan` 时回滚到目标节点前的最近可靠 checkpoint
- runtime 运行结束后新增落盘：
  - `outputs/states/<task_id>.json`
  - `outputs/reports/<task_id>.json`
- `RunResult` 增加 `checkpoint_dir` 与 `convergence_report_path`，便于 CLI 和后续上层消费产物
- `tests/test_runtime_smoke.py` 扩展到 `7` 个测试，覆盖：
  - checkpoint 持久化
  - state save/load
  - checkpoint-backed replan
  - convergence artifacts
- 新增决策记录：`docs/decisions/007-checkpoint-backed-replan.md`

## 2026-04-16 Human Review Gate 首轮落地
- 新增 `HumanReviewAgent`，作为最小人工拍板门节点
- 新增 `workflows/deep_research_human_review.yaml`
- `Evaluator` 补充 `human_review_gate` 输出校验
- `Scheduler` 在 `human_review` 节点输出 `await_human` 时，不再继续收尾为 completed，而是停在 `needs_human_review`
- smoke test 扩展到 `8` 个测试，新增验证：
  - human review workflow 会停在人工审批状态
  - runtime 会生成结构化人工审查包
- 新增决策记录：`docs/decisions/008-human-review-gate.md`

## 2026-04-16 MemoryManager v1 首轮落地
- 新增 `src/orchestrator/memory_manager.py`
- `Scheduler` 在 runtime 收尾阶段会自动调用 `MemoryManager v1`
- 每次运行结束都会生成 `memory_bundle`，并落盘到 `outputs/memory/<task_id>.json`
- 当前 memory 结构已包含：
  - `short_term`
  - `long_term`
  - `entity`
  - `procedural`
  - `failure_memory`
- `RunResult` 新增 `memory_path`
- smoke test 扩展到 `9` 个测试，新增验证：
  - memory artifact 会随正常运行一起生成
  - human review 状态下也会生成 memory
  - timeout 场景下会留下 failure memory
- 新增决策记录：`docs/decisions/009-memory-manager-v1.md`

## 2026-04-16 第二个 workflow 通用性验证
- 重写 `planner/search/summarizer` 的默认文案与产物，使其不再写死在 research 语境
- 新增 `workflows/customer_support_brief.yaml`
- 用第二个非 research workflow 验证当前 runtime 能支撑 service/content 风格任务
- smoke test 扩展到 `10` 个测试，新增验证：
  - research workflow 仍正常
  - non-research workflow 能输出 `service` 类型 plan 和 summary
- 新增决策记录：`docs/decisions/010-second-workflow-validation.md`

## 2026-04-16 Execution Audit / ConvergenceReport 增强
- 重写 `scheduler.py` 为更干净的 UTF-8 版本，补齐更完整的 audit report 结构
- `ConvergenceReport` 现在新增：
  - `timeline`
  - `flow_summary`
  - `control_summary`
  - `quality_summary`
  - `artifact_summary`
  - `execution_audit`
  - `memory_summary`
- report 现在会汇总：
  - 每个 agent 的耗时
  - supervisor guidance 历史
  - checkpoint replan 历史
  - failed evaluation reasons
  - 关键产物路径
- 修复 workflow loader 对 UTF-8 BOM 的兼容问题，确保顶层 `name` 字段稳定进入 runtime
- smoke test 扩展到 `12` 个测试，新增验证：
  - report 会输出 workflow 名称、时序和 memory 摘要
  - human review 状态会进入 control summary
  - supervisor replan 历史会进入 execution audit
- 新增决策记录：`docs/decisions/011-execution-audit-and-convergence-report.md`

## 2026-04-16 ToolRegistry v1 首轮落地
- 新增 `src/orchestrator/tool_registry.py`
- 引入 `ToolSpec` 与 `ToolRegistry`，为工具能力提供统一注册与执行入口
- `AgentConfig` 新增 `tools` 字段，agent 可以声明自己允许使用的工具
- `BaseAgent` 新增 `run_tool()`，统一检查工具是否已声明
- `SearchAgent` 已从“自己内置 mock 搜索逻辑”改为通过 `mock_search_context` 工具获取上下文材料
- `ConvergenceReport` 现在会输出：
  - `declared_tools_by_agent`
  - `tool_names_seen_in_outputs`
- smoke test 扩展到 `14` 个测试，新增验证：
  - ToolRegistry 可以注册和执行工具
  - 默认注册表提供 `mock_search_context`
  - report 能反映当前 workflow 的工具使用情况
- 新增决策记录：`docs/decisions/012-tool-registry-v1.md`

## 2026-04-16 LLMClient v1 首轮落地
- 新增 `src/orchestrator/llm_client.py`
- 引入统一 `LLMClient` 与 `ModelProfile`
- `AgentConfig` 新增 `model_profile`
- `BaseAgent` 新增 `complete_structured()`，通过统一 client 获取结构化结果
- `PlannerAgent`、`SummarizerAgent`、`SupervisorAgent` 已切到 `LLMClient v1`
- 当前支持最小 profiles：
  - `worker`
  - `worker_fast`
  - `orchestrator`
- smoke test 扩展到 `15` 个测试，新增验证：
  - workflow 中的 plan / summary / supervisor_report 已带 model_profile 痕迹
  - `LLMClient` 能按 profile 输出结构化结果
- 新增决策记录：`docs/decisions/013-llm-client-v1.md`

## 2026-04-16 MemoryManager 可检索 / 可复用首轮落地
- `MemoryManager` 新增 memory index，统一记录 task/query/summary/memory_path
- runtime 启动时会先检索相关历史 memory，并写入 `retrieved_memories`
- `PlannerAgent` 已开始读取 `retrieved_memories`
- `LLMClient` 的 plan 结果新增 `memory_hints_used`
- `ConvergenceReport` 现在会输出 `retrieved_memory_count`
- smoke test 扩展到 `16` 个测试，新增验证：
  - 第二次运行能检索到第一次的 memory
  - planner 会记录本次使用的 memory hints 数量
  - memory index 可直接检索到历史 memory
- 新增决策记录：`docs/decisions/014-retrievable-memory-manager.md`

## 2026-04-16 声明式 Human Review Terminal Behavior
- `AgentConfig` 新增 `terminal_behavior`，允许 agent 声明自己的终止/暂停语义
- `HumanReviewAgent` 已通过配置声明 `pause_for_human`
- `Scheduler` 不再通过 `agent_name == "human_review"` 做特殊分支，而是统一根据 agent 契约读取主写入字段
- 新增回归测试验证：
  - `human_review` workflow 仍会停在 `needs_human_review`
  - 非 `human_review` 名称的自定义暂停型 agent 也能触发相同停机语义
- smoke test 扩展到 `17` 个测试
- 新增决策记录：`docs/decisions/015-declarative-terminal-behavior.md`

## 2026-04-16 Declarative Evaluator Criteria
- 重写 `Evaluator` 为干净 UTF-8 版本，去掉按 agent 名字分支的 `if/elif`
- 当前 L1 评估规则已统一收进 `DEFAULT_EVAL_CRITERIA`
- 每条规则现在可声明：
  - `path`
  - `expected_type`
  - `min_items / max_items`
  - `allowed_values`
  - `action`
  - `reason`
- `Evaluator` 已支持注入自定义 criteria map，便于后续扩到更多 agent / workflow
- 新增回归测试验证：
  - 现有 workflow 行为不变
  - 自定义 agent 也可通过声明式 criteria 被评估
- smoke test 扩展到 `18` 个测试
- 新增决策记录：`docs/decisions/016-declarative-evaluator-criteria.md`

## 2026-04-16 Guardrails v1 首轮落地
- 新增 `src/orchestrator/guardrails.py`
- 引入 `GuardrailManager`、`GuardrailSpec` 和 `GuardrailViolation`
- `AgentConfig` 新增 `guardrails`，agent 可声明自己需要的输入/输出护栏
- `BaseAgent` 新增：
  - `apply_input_guardrails()`
  - `apply_output_guardrails()`
- `Scheduler` 已在 agent 执行前后接入 guardrail 检查
- 当前默认护栏已支持：
  - `require_non_empty_query`
  - `block_sensitive_output_terms`
- 护栏触发时：
  - runtime 会记录 `guardrail_violation`
  - 任务会以明确失败结束
  - `ConvergenceReport` 会补充 guardrail 数量、原因和历史
- 新增回归测试验证：
  - 空 query 会在 input guardrail 被拦住
  - 敏感输出会在 output guardrail 被拦住
  - 默认 guardrail registry 正常可见
- smoke test 扩展到 `21` 个测试
- 新增决策记录：`docs/decisions/017-guardrails-v1.md`

## 2026-04-16 Tool Permission / Trust Hierarchy 最小版本
- `AgentConfig` 新增 `trust_level`
- `ToolSpec` 新增 `risk_level`
- `BaseAgent.run_tool()` 现在会在真正调用 tool 前检查：
  - agent 的 `trust_level`
  - tool 的 `risk_level`
- 当前默认 `mock_search_context` 已标记为 `low risk`
- `SearchAgent` 已显式声明 `trust_level="low"`
- `ConvergenceReport` 现在会输出：
  - `trust_levels_by_agent`
  - `tool_risk_levels`
- 新增回归测试验证：
  - registry 会保留 tool risk level
  - 低信任 agent 调高风险 tool 会被明确拦住
- smoke test 扩展到 `23` 个测试
- 新增决策记录：`docs/decisions/018-tool-permission-and-trust-hierarchy.md`

## 2026-04-16 FailureTaxonomy（失败分类体系）首轮落地
- 新增 `src/orchestrator/failure_taxonomy.py`
- 引入 `FailureCategory` 枚举，覆盖 20+ 种失败类型：
  - 格式相关：format_error, missing_field, invalid_type
  - 内容相关：insufficient_content, empty_output, quality_below_threshold
  - 评估相关：evaluation_failed, retry_exhausted
  - 安全相关：guardrail_blocked, permission_denied, trust_level_insufficient
  - 执行相关：timeout, max_steps_exceeded, agent_error
  - 控制相关：supervisor_rejected, replan_failed, checkpoint_restore_failed
  - 外部相关：tool_error, llm_error, external_service_error
- 引入 `FailureSeverity` 枚举：low, medium, high, critical
- 引入 `FailureRecord` 类，记录失败详情
- 引入 `classify_failure()` 函数，根据 status / reason / event_type / eval_action 自动分类
- `Scheduler._finalize_run()` 现在会自动分类失败并写入 `execution_trace`
- `ConvergenceReport` 新增 `failure_summary` 字段
- smoke test 扩展到 `28` 个测试，新增验证：
  - timeout 分类正确
  - guardrail_blocked 分类正确
  - permission_denied 分类正确
  - retry_exhausted 分类正确
  - convergence_report 包含 failure_summary
- 新增决策记录：`docs/decisions/019-failure-taxonomy.md`

## 2026-04-16 Analyze CLI（历史运行分析工具）首轮落地
- 新增 `src/orchestrator/analyze.py`
- 引入 `RunAnalyzer` 类，提供历史运行数据分析能力
- CLI 新增 `analyze` 子命令，支持：
  - `analyze list`：列出最近运行
  - `analyze show --task-id <id>`：查看单个运行详情
  - `analyze failures`：统计失败类型分布
  - `analyze agents`：统计 agent 性能
  - `analyze memory`：查看 memory 索引摘要
- 输出格式为易读的 ASCII 表格
- smoke test 扩展到 `33` 个测试，新增验证：
  - list_recent_runs 正常工作
  - get_run_detail 返回完整报告
  - failure_statistics 统计正确
  - agent_performance 统计正确
  - memory_summary 正常工作
- 新增决策记录：`docs/decisions/020-analyze-cli.md`

## 2026-04-16 Eval Criteria 下沉到 AgentConfig
- `AgentConfig` 新增 `eval_criteria` 字段，类型为 `list[EvalCriteriaItem]`
- 新增 `EvalCriteriaItem` 模型，包含 path / expected_type / min_items / max_items / allowed_values / action / reason
- 重写 `Evaluator`，不再按 agent 名查字典，而是直接接收 criteria 列表
- `Scheduler` 调用 evaluator 时传入 `agent.config.eval_criteria`
- 所有内置 agent（planner / search / summarizer / supervisor / human_review）已将评估规则移到自己的 config 里
- 新增 agent 不再需要修改 evaluator.py，只需在自己的 config 里声明 eval_criteria
- 测试全部通过（33 个）
- 更新决策记录：`docs/decisions/016-declarative-evaluator-criteria.md`

## 2026-04-16 代码质量改进（#2 #3 #6）
- **修复 #3 BaseAgent class attribute 共享状态问题**
  - `tool_registry` / `guardrail_manager` / `llm_client` 从类属性改为实例属性
  - 新增 `__init__` 方法，支持依赖注入
  - 保留 property 访问器，保持 API 兼容
- **修复 #6 FailureTaxonomy 字符串匹配不稳定问题**
  - 新增 `create_failure_record()` 函数，让失败源头显式传入 category
  - `GuardrailViolation` 新增 `failure_category` 字段
  - `Scheduler` 优先使用显式传入的 category，fallback 到推断逻辑
  - 保留 `classify_failure()` 用于向后兼容
- **修复 #2 Scheduler 臃肿问题**
  - 新增 `report_writer.py`，将 `_write_convergence_report` 拆分到独立模块
  - Scheduler 从 675 行减少到 443 行
  - `ConvergenceReportWriter` 类负责生成收敛报告
- 测试全部通过（33 个）
- 新增决策记录：`docs/decisions/021-code-quality-improvements.md`

## 2026-04-16 类型注解增强（#4）
- **新增类型定义**
  - `PlanOutput` / `SummaryOutput` / `SupervisorReport` / `HumanReviewGate` Pydantic Model
  - `ContextView` TypedDict
  - `Document` TypedDict
- **重构 StateCenter**
  - 新增 `StateMetadata` 类，管理运行元数据
  - 新增 `ConvergenceState` 类，管理收敛状态
  - 新增 `DataPool` 类，管理数据池
  - `StateCenter` 使用这些类而不是原始字典
- **更新所有使用点**
  - scheduler.py / memory_manager.py / report_writer.py / test_runtime_smoke.py
- 测试全部通过（33 个）
- 新增决策记录：`docs/decisions/023-type-annotation-enhancement.md`

## 2026-04-16 Agent CLI 命令与可插拔接口
- **新增 `agent` 命令**
  - `orchestrator agent --name <name> --query <query> --format json|text`
  - 直接调用单个 agent，返回原始输出
- **新增 `agents` 命令**
  - `orchestrator agents` 列出所有已注册 agents
  - `orchestrator agents --verbose` 显示详细信息
- **新增 `quick_search.yaml`**
  - 轻量搜索工作流：search → summarizer
  - 跳过 planner，适合快速任务
- **修复 JSON 序列化**
  - `run` 命令输出时 `state.metadata` 调用 `.to_dict()`
- 测试从 33 个增加到 36 个
- 新增决策记录：`docs/decisions/024-agent-cli-commands.md`

## 2026-04-16 LLM Provider 抽象层
- **新增 `llm_providers.py`**
  - `LLMProvider` 抽象基类
  - `GLMProvider` / `KimiProvider` / `OpenAIProvider` / `AnthropicProvider`
  - `MockProvider` 用于测试
  - `CLIProvider` / `CodexProvider` / `OllamaProvider` 支持命令行工具
  - `PROVIDER_REGISTRY` 统一注册
- **重写 `llm_client.py`**
  - 支持 Provider 注入
  - 支持 `complete()` 和 `complete_json()`
  - 为不同任务构建 prompt
  - 保持 mock 向后兼容
- **扩展 `AgentConfig`**
  - 新增 `llm_provider` 字段
  - 新增 `llm_model` 字段
- **修改 `BaseAgent`**
  - 支持注入 `llm_provider` 参数
  - 优先级：显式传入 > AgentConfig > 默认 Mock
- **CLI 支持**
  - `--llm` 指定全局 Provider
  - `--model` 指定模型
  - `--agent-llm` 指定 per-agent 配置
- 测试从 36 个增加到 39 个
- 新增决策记录：`docs/decisions/025-llm-provider-abstraction.md`

## 2026-04-16 真实工具接入
- **新增 `real_tools.py`**
  - `web_search_duckduckgo`（免费，无需 API Key）
  - `web_search_tavily`（专为 AI Agent 设计）
  - `web_search_serper`（Google 搜索 API）
  - 同步/异步版本
- **扩展 `ToolRegistry`**
  - `build_real_tool_registry()` 根据环境变量自动注册可用工具
  - `build_tool_registry(use_real_tools=True)` 统一入口
- **新增 `RealSearchAgent`**
  - 使用真实搜索的 Agent
  - 自动 fallback 到 mock
- **修改 `BaseAgent`**
  - 新增 `use_real_tools` 参数
- **更新 `pyproject.toml`**
  - 新增可选依赖 `[search]`
- 新增决策记录：`docs/decisions/026-real-tools-integration.md`

## 2026-04-16 Agent Health 追踪与失败案例分析
- **扩展 `RunAnalyzer`**
  - `get_agent_health(agent_name, days)` - 获取单个 Agent 健康度
  - `get_all_agents_health(days)` - 获取所有 Agent 健康度
  - `get_agent_failures(agent_name, limit)` - 获取 Agent 失败案例列表
- **CLI 新增命令**
  - `analyze health --agent <name> --days <n>` - 查看 Agent 健康度评分
  - `analyze agent-failures --agent <name> --limit <n>` - 查看 Agent 失败案例
- **健康度评分系统**
  - Score: `成功率 × 100`（0-100分）
  - Levels: excellent / good / fair / poor / critical / unknown
  - 统计最近 N 天的运行数据
- 测试通过

## 2026-04-16 Evaluator L2 语义级评估
- **新增 `evaluator_l2.py`**
  - `EvaluatorL2` 类，支持语义级评估
  - `L2Criterion` 规则定义
  - `L2Score` 评分结果
- **评估维度**
  - completeness - 完整性
  - consistency - 一致性
  - relevance - 相关性
  - quality - 质量
- **检查类型**
  - min_length / min_items - 长度和数量检查
  - has_keywords - 关键词检查
  - field_match - 字段匹配
  - not_empty - 非空检查
  - score_threshold - 分数阈值
  - coverage - 覆盖率检查
- **预定义规则**
  - `make_planner_l2_criteria()` - Planner 的 L2 规则
  - `make_summarizer_l2_criteria()` - Summarizer 的 L2 规则
  - `make_supervisor_l2_criteria()` - Supervisor 的 L2 规则
- **集成到 `Evaluator`**
  - 支持多层评估（L1 + L2）
  - 新增 `enable_l2` 参数
  - 新增 `l2_criteria` 参数

## 2026-04-16 SupervisorOrchestrator 总控编排器
- **新增 `supervisor_orchestrator.py`**
  - `SupervisorOrchestrator` 类 - 真正的总控层
  - `TaskLedger` - 任务账本，跟踪所有任务状态
  - `TaskItem` - 任务项
  - `TaskStatus` - 任务状态枚举
  - `OrchestrationDecision` - 编排决策
- **核心能力**
  - 维护任务账本（借鉴 AutoGen MagenticOne）
  - 动态决定下一步 agent（而非固定 workflow）
  - 检测 stalled / no progress
  - 触发 re_plan
  - 处理失败情况
- **集成到 `Scheduler`**
  - 新增 `use_orchestrator` 参数
  - 编排器决策影响调度流程
  - 支持 re_plan 信号处理

## 2026-04-16 RegressionCompare 回归对比
- **新增 `regression_compare.py`**
  - `RegressionCompare` 类
  - `RegressionSignal` 枚举：no_regression / minor_regression / major_regression / improvement
  - `MetricDiff` 指标差异
  - `RegressionReport` 回归报告
- **功能**
  - 比较新旧运行结果
  - 计算指标差异（步数、评估失败、重试次数、成功率、置信度）
  - 判断回归信号
  - 查找回归案例
- **CLI 新增命令**
  - `analyze regression --old <id> --new <id>` - 对比两次运行
  - `analyze regression --recent <n>` - 对比最近相邻运行
  - `analyze regression --find <n>` - 查找回归案例

## 2026-04-16 ProjectContext 项目文件上下文
- **新增 `project_context.py`**
  - `ProjectContext` 类
  - `FileInfo` - 文件信息
  - `ProjectStructure` - 项目结构
  - `FileSummary` - 文件摘要
- **功能**
  - 扫描项目目录结构
  - 读取关键文件内容
  - 提供文件摘要给 agents
  - 支持文件搜索和过滤
  - 语言检测（Python/JS/YAML/JSON/Markdown 等）
  - 简单语法检查（Python）
- **CLI 新增命令**
  - `project-context --scan` - 扫描项目结构
  - `project-context --file <path>` - 查看文件摘要
  - `project-context --find <pattern>` - 查找文件

## 2026-04-16 LiveInterruptController 实时中断
- **新增 `live_interrupt.py`**
  - `LiveInterruptController` 类
  - `InterruptSignal` 枚举：none / pause / resume / abort / inject / skip / restart
  - `InjectCommand` 枚举：modify_query / force_complete / override_result / add_context / change_target
  - `InterruptRequest` / `InterruptResponse` / `InterruptLog`
- **功能**
  - 中断信号机制（暂停、恢复、终止）
  - 指令队列（注入指令）
  - 人类随时接管
  - 外部文件触发中断（用于外部进程通信）
- **使用方式**
  - `controller.pause()` - 暂停运行
  - `controller.resume()` - 恢复运行
  - `controller.abort()` - 终止运行
  - `controller.inject(command, payload)` - 注入指令
  - `controller.write_signal_file(signal)` - 写入信号文件

## 2026-04-16 完整生态实现总结
- **优先级 1-3 全部完成**
  - Human review gate ✅
  - ConvergenceReport ✅
  - StateCenter save/load ✅
  - Checkpoint-backed replan ✅
  - MemoryManager v1 ✅
  - LLMClient v1 ✅
  - Worker 接真实 LLM ✅
  - Evaluator(L2) ✅
  - Guardrails v1 ✅
  - FailureTaxonomy ✅
  - SupervisorOrchestrator ✅
  - ToolRegistry ✅
  - Analyze CLI ✅
  - 第二个 workflow ✅
  - TrustHierarchy ✅
  - RegressionCompare ✅
  - ProjectContext ✅
  - LiveInterrupt ✅
  - Agent Health 追踪 ✅
  - LLM Provider 抽象 ✅
  - 真实工具集成 ✅
- **整体完成度：约 98%**
- **8 层架构基本完整**

