# 项目状态

## 当前主线

正在构建一个独立于 `deep_research_agent` 的新项目：

**Adaptive Agent Orchestrator**

它的目标不是做具体业务应用，而是做一个可复用的多 Agent 编排与评估内核。

## 当前定位

- 类型：编排引擎 / 运行时内核
- 重点：共享状态、显式契约、运行时评估、收敛控制、诚实降级
- 长期目标：Human -> Supervisor Agent -> Worker Agents
- 完整生态方向：8 层多智能体生态（Human / Supervisor / Runtime / Worker / Tools / Context / Memory / Feedback）
- 当前一周实现重点：先做可运行 runtime core
- 运行形态：CLI 优先
- 技术栈：Python + Pydantic + PyYAML

## 文档分层

为了避免“长期目标”和“当前实现”混在一起，现在正式分成两份：

- 当前设计基线：`docs/architecture.md`
- 完整生态蓝图 v2：`docs/ecosystem_architecture_v2.md`

## 当前一周必须完成

- `StateCenter`
- `Scheduler`
- `Evaluator(L1)`
- `AgentRegistry`
- `PlannerAgent`
- `SearchAgent`
- `SummarizerAgent`
- 最简执行日志
- CLI 入口
- 跑通一个 `deep_research` workflow

## 当前一周不要求做满

- 完整 `Supervisor Agent`
- 长期记忆层
- `L2 / L3`
- 完整 checkpoint rollback
- 多模型路由
- 完整 feedback loop
- Web UI / API
- 并发执行

## 当前开发方式判断

当前这个项目仍然以对话框模式开发为主。

同时开始练：

- 文件化上下文
- 1 主 1 辅会话分工
- 任务拆解
- 角色边界定义

完整路线见：

- `docs/workflow_evolution.md`

## 这条线和其他项目的关系

- `deep_research_agent`
  - 真实 workflow 应用
  - future app layer
- future evaluate system
  - 未来评估层
  - 为本项目 `Evaluator` 提供方法论来源

完整说明见：

- `docs/project_relationships.md`

## 当前长期成长方向

长期路线是：

- 用 `deep_research_agent` 稳住应用和 eval
- 用 `adaptive-agent-orchestrator` 长出编排内核
- 逐步把 evaluate system 抽出来
- 最终形成“应用层 + 引擎层 + 评估层”这条 agent infra 路线

完整说明见：

- `docs/growth_path.md`
- `docs/market_signals_and_skill_focus.md`

## 下一步

1. 逐步把 `human_review` / `Evaluator` 等过渡实现收敛成更声明式的 V2 方案
2. 补更明确的 tool usage / guardrail 边界，为后续 `Guardrails v1` 铺路
3. 让 `LLMClient` 从 mock profile 继续长向 provider-aware client
4. 持续扩 `MemoryManager`，从当前 query-based retrieval 走向更强的可检索/可复用
5. 持续沉淀 `docs/decisions/` 中的关键模块取舍

## 文档约定

- 当前设计基线：`docs/architecture.md`
- 完整生态蓝图 v2：`docs/ecosystem_architecture_v2.md`
- 下一对话框衔接文档：`docs/next_session_handoff.md`
- 工作方式路线：`docs/workflow_evolution.md`
- 项目关系说明：`docs/project_relationships.md`
- 成长路径：`docs/growth_path.md`
- 市场方向锚点：`docs/market_signals_and_skill_focus.md`
- 项目状态：`PROJECT_STATE.md`
- 历史推进记录：`PROJECT_LOG.md`

## 决策记录约定
- 关键模块和关键取舍统一记录在：docs/decisions/ 
- 索引文件：docs/decisions/README.md 
- 模板文件：docs/decisions/000-template.md 
- 后续每做一个关键模块，都要同步沉淀一份设计与取舍记录。

## 当前最新进展

- `SupervisorAgent` 已从“只看最终结果”升级为“开始读取执行轨迹、重试次数和状态信息”
- `supervisor_report` 现在包含 `process_review`，能输出最小过程审查结果
- `supervisor_report` 现在还能输出：
  - `review_reason`
  - `suggested_target`
  - `suggested_action`
- 当前 `Supervisor` 已从“做 review”进一步升级到“能给结构化修正建议”
- `Scheduler` 已开始响应最小 Supervisor 建议路由，可以按建议回到现有节点重新执行
- `Supervisor` 已开始区分：
  - 普通修补（补资料 / 重写总结）
  - 最小 `re_plan`（回到 planner 重新规划）
- `Scheduler` 已支持最小 `re_plan`，并会清掉依赖旧规划的下游状态
- `StateCenter` 已补齐基础 `save/load` 能力，可把完整运行时状态序列化到磁盘
- `Scheduler` 已把最小 `re_plan` 升级为 checkpoint-backed replan
- `Human review gate` 已接入最小 runtime 闭环：
  - `supervisor` 之后可进入 `human_review`
  - runtime 会输出结构化人工审查包
  - 系统会停在 `needs_human_review` 状态等待人工拍板
- `MemoryManager v1` 已接入 runtime 收尾闭环：
  - 每次运行结束都会沉淀 `memory_bundle`
  - memory 会按 `short_term / long_term / entity / procedural / failure_memory` 结构落盘
- 第二个非 research workflow 已落地：
  - `workflows/customer_support_brief.yaml`
  - 当前 runtime 已验证不只适配 research 查询，也能支撑 service/content 风格任务
- runtime 现在会自动产出：
  - checkpoint snapshots
  - persisted state json
  - `ConvergenceReport`
  - memory artifact
- `ConvergenceReport` 已增强为更完整的 execution audit：
  - timeline
  - flow summary
  - control summary
  - quality summary
  - artifact summary
  - execution audit history
- `ToolRegistry v1` 已接入：
  - 当前已把 mock search context 能力从 `SearchAgent` 中抽到统一注册表
  - agent 可声明自己使用哪些工具
  - report 已能看到 declared tools 和工具痕迹
- `LLMClient v1` 已接入：
  - planner / summarizer / supervisor 已通过统一 client 生成结构化结果
  - 当前支持最小 model profiles：`worker` / `worker_fast` / `orchestrator`
  - agent 不再自己直接长“模型式输出逻辑”
- `MemoryManager` 已从“只会沉淀”升级到“可检索 / 可复用”：
  - 每次 memory 会进入统一索引
  - 新任务启动时会先检索相关历史 memory
  - planner 会感知本次用了多少 memory hints
- `human_review` 的暂停语义已从 Scheduler 名字特判收敛为声明式 agent 契约：
  - `AgentConfig` 现在可声明 `terminal_behavior`
  - `HumanReviewAgent` 通过配置声明自己会在 `await_human` 时暂停 runtime
  - Scheduler 已改为根据 agent 契约读取主写入字段，而不是识别某个具体 agent 名称
- `Evaluator` 已从按 agent 名字写死的 `if/elif` 分支，收敛为声明式 criteria map：
  - 当前 L1 规则已改为通过字段路径、类型、数量和允许值进行统一检查
  - `Evaluator` 现在支持注入自定义 criteria map，便于后续逐步走向更完整的 V2 评估配置
- `Guardrails v1` 已接入 worker 执行闭环：
  - agent 现在可声明 `guardrails`
  - runtime 会在 agent 执行前做 input guardrail，执行后做 output guardrail
  - 当前默认护栏已覆盖：
    - 非空 query 检查
    - 敏感输出词拦截
  - 触发护栏时，系统会留下结构化 `guardrail_violation` 事件并直接失败
- 最小 `tool permission / trust hierarchy` 已接入：
  - agent 现在可声明 `trust_level`
  - tool 现在可声明 `risk_level`
  - `run_tool()` 会在实际调用前检查信任级别是否足够
  - `ConvergenceReport` 已能看到 agent trust level 和 tool risk level
- `Evaluator L2` 已实现语义级评估：
  - 支持 completeness / consistency / relevance / quality 四个维度
  - 提供 min_length / min_items / has_keywords / coverage 等检查类型
  - 预定义 planner / summarizer / supervisor 的 L2 规则
  - L1 与 L2 串联执行，先结构验证再语义评估
- `SupervisorOrchestrator` 已实现真正的总控编排：
  - 维护 TaskLedger（任务账本）跟踪任务状态
  - 动态决定下一步 agent（而非固定 workflow）
  - 检测 stalled / no progress 并触发 re_plan
  - 与 Scheduler 集成，影响运行时调度决策
- 当前系统已具备：
  - Worker 执行层
  - Runtime 调度层
  - L1 结构评估层
  - L2 语义评估层
  - 最小 Supervisor 过程感知层
  - 最小 Supervisor 控制闭环
  - 最小重规划信号
  - checkpoint-backed replan
  - human review gate
  - MemoryManager v1
  - 第二 workflow 通用性验证
  - 增强版运行时审计产物闭环
  - ToolRegistry v1
  - LLMClient v1
  - 可检索 / 可复用的 MemoryManager
  - 声明式 terminal behavior 雏形
  - 声明式 evaluator criteria 雏形
  - Guardrails v1
  - 最小 trust hierarchy / tool permission
  - SupervisorOrchestrator 总控编排器
  - Evaluator L2 语义级评估
  - RegressionCompare 回归对比
  - ProjectContext 项目文件上下文
  - LiveInterruptController 实时中断控制器
  - Agent Health 追踪和失败案例分析
  - LLM Provider 抽象层（GLM/Kimi/OpenAI/Codex/Ollama）
  - 真实工具集成（Tavily/Serper/DuckDuckGo 搜索）

## Claude Code 方向参考
- 已补充参考文档：`docs/claude_code_learnings.md`
- 用于后续判断哪些生态层能力值得逐步吸收到本项目中。
## 已记账的后续能力项

- 新增 agent / workflow 的首次上线验收机制
  - 单独跑 agent
  - 跑最小 workflow
  - 跑 3 到 5 个代表性任务
  - 结合 report / analyze 做验收判断
- 生态级自动 debug / failure analysis agent
  - 能读取 report / state / failure taxonomy / regression compare / project context / memory 等信息
  - 后续考虑设计 `DebugAgent` / `RuntimeInvestigator` 这类专门角色
- RegressionCompare 智能化增强
  - 先保持当前可用版本
  - 后续增强为“最近运行里前后差异较大”的更直观表达
  - 进一步区分真实退化、故意失败测试样本、正常波动
- 编码与文案卫生
  - 统一使用 UTF-8
  - 修改用户可见文案后，顺手做一次终端肉眼验收
  - 不继续复制已有乱码文本，发现后原地替换
- 自然语言 CLI 入口
  - 后续提供更短的命令行使用方式，尽量减少手写 workflow / agent / llm 参数
  - 支持直接输入任务描述，由系统解析意图并路由到合适的 workflow / agent / model
  - 参数式 CLI 继续保留，作为开发 / 调试 / 高级控制模式
  - 第一阶段先自然语言化任务入口
  - 后续再逐步覆盖 analyze / agents / project-context 等后台命令
- 长任务阶段性对齐 / 防跑偏机制
  - 长时间任务不能只依赖一开始的详细 prompt
  - 后续需要在关键里程碑自动做 alignment check，确认当前方向是否仍符合原始目标
  - 可结合 supervisor 巡检、Evaluator、checkpoint、human review，在低置信度或高风险时暂停给人确认
  - 目标是减少长任务越跑越偏、最后产物不符合预期的问题

