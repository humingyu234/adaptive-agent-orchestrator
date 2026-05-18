# Multi-Model Planning Council

## Why This Matters

这个功能是 `adaptive-agent-orchestrator` 后续从“已有 workflow runtime”走向“真正任务生态”的关键能力。

用户真正想要的不是简单地输入一句任务后立刻执行，而是：

> 先让多个模型理解任务、讨论方案、形成执行计划，再让用户确认，最后带着计划执行。

这样可以避免长任务一开始理解错、执行中跑偏、最后得到用户不满意的结果。

## Core User Need

用户可能提出一个复杂任务，例如：

> 帮我做一个新项目，从行业调研、产品设计、技术架构到代码实现。

但用户自己的初始想法不一定完全正确，也可能没有把任务边界、优先级、执行顺序说清楚。

所以系统不应该马上执行，而应该先组织一次“规划会”：

- 多个 LLM / agent 分别理解任务
- 各自提出方案
- 互相质疑和补充
- 系统融合成一版执行计划
- 执行前交给用户确认
- 用户可以提出修改意见
- 直到用户批准后再执行

## Target Experience

理想流程：

```text
用户提出任务
↓
多个模型分别理解任务
↓
它们各自给出方案
↓
系统对比、融合、质疑
↓
生成一版执行计划
↓
给用户确认
↓
用户提出修改意见
↓
系统重新融合计划
↓
用户批准
↓
系统按计划执行
↓
到达预设检查点时暂停并询问用户
```

这不是普通 `ask`，而是一个：

> Multi-Model Planning Council

## Command Shape

### Start A Planning Council

```powershell
py -m orchestrator council "帮我做一个 SaaS 项目，从调研、产品设计到代码实现"
```

可能输出：

```json
{
  "task_id": "...",
  "status": "awaiting_plan_review",
  "candidate_plans": [
    {
      "planner": "codex",
      "view": "先拆成 research -> architecture -> implementation -> review"
    },
    {
      "planner": "deepseek",
      "view": "先明确 MVP 范围和验收指标，再进入实现"
    },
    {
      "planner": "kimi",
      "view": "先做用户场景和产品文档，再做技术方案"
    }
  ],
  "merged_plan": {
    "phases": [
      "需求澄清",
      "市场/竞品调研",
      "产品方案",
      "技术架构",
      "实现",
      "测试",
      "人工验收"
    ],
    "checkpoints": [
      "需求澄清后找用户确认",
      "技术方案确定后找用户确认",
      "MVP 跑通后找用户确认"
    ]
  }
}
```

### Reply With User Feedback

```powershell
py -m orchestrator council reply --task-id <task_id> "我不想先做太大，先收敛成一个 MVP"
```

系统应该基于用户反馈重新融合计划。

### Approve The Plan

```powershell
py -m orchestrator council approve --task-id <task_id>
```

批准后，系统才开始执行。

### Checkpoint Policy

用户应该能一开始指定做到什么程度需要找自己确认。

示例：

```powershell
py -m orchestrator council "帮我做一个项目，每完成一个大阶段先问我"
```

或者：

```powershell
py -m orchestrator council "帮我做一个项目" --checkpoint-policy phase
```

## Key Concepts

### Candidate Plans

不同模型或 agent 对同一任务给出的独立理解。

目标不是让它们输出完全一样的计划，而是利用差异发现盲点。

### Critique / Debate

系统应该允许不同方案之间互相指出风险：

- 任务边界是否太大
- 是否缺少验收标准
- 是否需要先调研
- 是否需要人工确认
- 是否有高风险步骤
- 是否需要更强模型或工具

### Merged Plan

最终给用户看的不是一堆散乱建议，而是一份融合后的执行计划。

它应该包含：

- 任务目标
- 范围边界
- 阶段拆分
- 每阶段 agent 分工
- 每阶段 LLM / provider 分配
- 工具需求
- 风险点
- 用户确认点
- 验收标准

### User Approval

没有用户批准前，系统不应该直接进入长任务执行。

状态可以是：

```text
awaiting_plan_review
```

用户批准后再进入：

```text
approved_for_execution
```

### Runtime Checkpoints

执行过程中也要支持阶段性暂停。

例如：

- 需求澄清后暂停
- 技术方案后暂停
- 第一个 MVP 跑通后暂停
- 高风险工具调用前暂停
- 预算或时间超过阈值时暂停

## Why This Is Better Than Direct Ask

直接 `ask` 的问题：

- 容易一开始理解错
- 长任务容易跑偏
- 用户很晚才发现方向不满意
- 难以表达“做到某个程度先问我”
- 不适合复杂项目型任务

Planning Council 的优势：

- 执行前先对齐目标
- 多模型互补，减少盲点
- 用户可以迭代计划
- 阶段性 checkpoint 降低跑偏风险
- 更符合真实项目协作方式

## Future Implementation Direction

后续实现可以拆成几个模块：

- `CouncilPlanner`
- `CandidatePlan`
- `PlanCritic`
- `PlanMerger`
- `CheckpointPolicy`
- `PlanReviewState`
- `DynamicWorkflowComposer`
- `CouncilExecutor`

执行链路：

```text
Natural Task
-> CouncilPlanner
-> Candidate Plans
-> Critique / Merge
-> User Plan Review
-> Dynamic Workflow Composer
-> Runtime Execution
-> Phase Checkpoints
-> User Confirm / Revise / Continue
```

## Execution Plan Preview (ask --preview-only)

Planning Council 讨论产生方案后，不是直接开始执行，而是先把方案展示给用户确认。

### 命令

```bash
py -m orchestrator ask "研究 X，并在写正式结论前让我确认" --preview-only
py -m orchestrator ask "研究 X" --preview-only --review-policy before_execute
```

### 数据模型

```python
class ExecutionPlanPreview(BaseModel):
    task_id: str
    query: str
    selected_workflow: str
    review_policy: str              # none / before_execute / before_final / every_stage
    planned_agents: list[str]       # 按执行顺序排列的 agent 列表
    plan_preview: dict              # Planning Council 产出的步骤、风险、memory hints
    risks: list[str]                # Council 标记的风险项
    estimated_steps: int            # 预计执行步数
    next_command: str               # "run --task-id xxx" 或 "resume-plan --task-id xxx --approve"
```

### 流

```
ask --preview-only
    |
    v
Planning Council 讨论
    |
    v
ExecutionPlanPreview 输出  →  用户看到: workflow、步骤、风险、预计产物
    |
    v
用户决策:
    ├── approve  → run --task-id xxx              # 开始执行
    ├── revise   → 修改 query 或 review_policy，重新预览
    └── reject   → 放弃
```

### 产物

预览结果写入 `outputs/plans/<task_id>.json`，独立于完整执行产物，不生成 report/memory。

### 恢复执行

用户确认后，通过 CLI 恢复执行：

```bash
py -m orchestrator resume-plan --task-id <task_id> --approve
# 等价于
py -m orchestrator run --workflow <workflow> --query "<query>" --review-policy <policy>
```

也可以直接在预览输出里看到等价命令，复制粘贴即可执行。

---

## Review Policy

用户可以在任务开始时声明做到哪一步先让我 review，而不是只能依赖 workflow 里预先写死的 human_review 节点。

### 三级 Review Policy

| Policy | 行为 | 适用场景 |
|--------|------|----------|
| `none` | 全程不暂停，跑完直接出结果 | 信任度高的简单任务 |
| `before_final` | 进入最后一个 agent 前暂停 | "总结前让我看一眼" |
| `before_execute` | 启动后立即暂停，等用户确认 plan | "先把方案给我看，别急着跑" |
| `every_stage` | 每个 agent 执行后都暂停 | 高风险任务 / 用户想逐步把控 |

### 运行时行为

```
ask --review-policy before_final

planner → search → summarizer → [⏸ 暂停] → supervisor → completed
                                      |
                              "到 summarizer 了，
                               总结草案在这，你确认一下"
```

### 实现要点

1. `review_policy` 写入 `state.data_pool.intermediate["review_policy"]`
2. `Scheduler._execute_agents()` 在每个 agent 完成后检查 policy
3. 暂停时复用 `_finalize_run(status="needs_human_review")`，写入 `review_checkpoint`
4. `status` 命令可查询当前暂停原因和 `next_command`

### 与 Planning Council 的关系

- Planning Council 在讨论阶段可以**推荐** review policy（如检测到高风险任务建议 before_final）
- 用户可以在 `ask` 时显式指定 `--review-policy`，覆盖 Council 的推荐
- 最终以用户指定为准（人类最高权限）

---

## Status

当前项目还没有完整实现这个能力。

当前已有基础：

- `ask` 自然语言入口
- LLM Router
- Scheduler
- StateCenter
- Evaluator L1 / L2
- checkpoint / rollback / replan
- Human Review approve / reject / resume
- 多 LLM provider
- analyze / report / memory

这些底座可以支撑 Planning Council，但还需要新增 council 层。

## Importance

这个功能优先级很高。

它直接对应用户最核心的长期目标：

> 给出一个复杂任务，让生态先理解、讨论、形成计划、征求确认，然后再组织 agent 去执行。

