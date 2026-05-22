# Phase 30 - Codex LLM Reviewer

## Goal

把 Codex CLI 作为 LLM 审查后端接入 AAO Reviewer 体系。
Codex CLI 在隔离的只读沙箱中运行，零共享上下文，
只接收 observed evidence，输出结构化的 ReviewFinding。

这是 Phase 23 预留的 `LLMReviewer` 接口的具体实现。

```
EvidenceBundle (diff, test_output, result.md)
    ↓
CodexReviewer._build_prompt()
    ↓ 只读 prompt + JSON Schema
codex exec --sandbox read-only --output-schema review_schema.json
    ↓ 隔离沙箱，零上下文
结构化 JSON:
  { findings: [{ severity, category, description, location, suggested_fix }],
    overall_pass: bool }
    ↓
CodexReviewer._to_findings() → list[ReviewFinding]
```

## Why Codex CLI

- `--sandbox read-only` 天然保证只读，无代码注入风险
- `--output-schema` 约束输出为结构化 JSON，可靠解析
- 独立子进程，零共享上下文（不继承 AAO 的会话状态）
- 不同模型交叉验证（Claude 写 → Codex 审）
- 用户已安装、已登录、可直接使用

## Two-Layer Review Architecture

```
Step 完成
    │
    ├── Layer 1: RuleBasedReviewer (永远跑, $0, 瞬时)
    │     ├── 5 条确定性规则
    │     ├── blocking → FixTask → 抢修
    │     └── 通过
    │
    └── Layer 2: CodexReviewer (按需跑)
          触发条件:
            - task_size == "large" 或 risk_level == "high"
            - Layer 1 规则通过但信号可疑（见下方）
            - 上一轮修复失败后本轮"通过"
          
          codex exec --sandbox read-only
            ├── 隔离目录，零上下文
            ├── --output-schema 约束格式
            └── 输出结构化 findings
                  │
                  ├── blocking → FixTask / human review
                  └── non_blocking → 记录
```

## Layer 2 触发条件

| 触发信号 | 含义 |
|---------|------|
| `task_size == "large"` 或 `risk_level == "high"` | 高风险任务，直接启用 |
| 上一轮 auto-repair 失败后本轮通过 | 警惕障眼法 |
| diff 行数很少但声称修了多个测试 | 可能是删测试/改预期值 |
| 只改了测试文件 | 可能删断言蒙混过关 |
| evidence_contradiction 出现后又消失 | 修复过程掩盖了矛盾 |
| `codex` 不在 PATH | 永远不触发，静默跳过 |

## Review Prompt Template

```
You are an isolated code reviewer. You did NOT write this code.
You have NO context beyond what is provided below.
Never trust the worker's self-assessment. Cite concrete evidence.

== TASK ==
{step_id}

== CHANGED FILES ==
{changed_files}

== DIFF ==
{diff_content}

== TEST OUTPUT ==
{test_output}

== RESULT.MD (worker self-report — DO NOT TRUST) ==
{result_md}

== ALLOWED FILES ==
{allowed_files}

== REQUIRED CHECKS ==
{required_checks}

For each issue found, provide file:line or evidence path as location.
Output as structured JSON per the output schema.
```

## Hard Rules

- CodexReviewer 只读，`--sandbox read-only` 已保证
- 零共享上下文：`--session-id` 每次新建，不继承任何会话
- 隔离目录：`-C <tempdir>` 确保看不到项目代码
- Codex 不可用时静默跳过，不阻断流程
- 超时 10 分钟，超时视为审查未完成（不阻塞）
- 解析失败同样静默跳过

## Interfaces

### CodexReviewer

```python
class CodexReviewer(Reviewer):
    """LLM reviewer backed by Codex CLI in read-only sandbox.

    Launches an isolated ``codex exec`` subprocess with write tools
    disabled.  Receives only the EvidenceBundle contents via stdin prompt.
    Output is constrained by a JSON Schema to produce structured
    ReviewFinding-compatible output.
    """

    def __init__(self, schema_path: str = "", timeout: int = 600):
        ...

    def review(self, evidence: EvidenceBundle) -> list[ReviewFinding]:
        ...

    @staticmethod
    def is_available() -> bool:
        """True if codex CLI is on PATH."""
        ...
```

### Trigger logic (in MainlineExecutor)

```python
def _should_invoke_codex_reviewer(
    cls,
    task_size: str,
    risk_level: str,
    rule_findings: list[ReviewFinding],
    repair_history: list[RepairRound] | None = None,
) -> bool:
    """Determine whether Layer 2 (Codex) review is warranted."""
    ...
```

## Test Plan

```
test_codex_reviewer_builds_correct_prompt
test_codex_reviewer_parses_valid_json_response
test_codex_reviewer_handles_missing_codex
test_codex_reviewer_handles_timeout
test_codex_reviewer_handles_malformed_output
test_should_invoke_for_large_task
test_should_invoke_for_high_risk
test_should_invoke_after_failed_repair_then_pass
test_should_skip_when_codex_not_available
test_should_skip_for_small_low_risk_clean_signal
test_codex_reviewer_is_a_reviewer_subclass
```

## Definition Of Done

```
- CodexReviewer 实现 Review 接口
- JSON Schema 正确约束 Codex 输出
- Layer 2 触发逻辑白盒可测
- Codex 不可用时静默跳过
- 超时/解析失败不阻断流程
- RuleBasedReviewer (Layer 1) 永远先跑
- 8+ 个测试通过
```

## Required Final Explanation To User

```
Phase 23 只做了确定性规则审查——能拦住测试挂了、文件越界、口述撒谎，
但拦不住"代码逻辑本身不对"。

Phase 30 用 Codex CLI 的只读沙箱做 Layer 2 审查。
不同模型、不同上下文、只看到证据快照——真正的 Cold Validation。
高风险任务或信号可疑时才触发，不浪费 token。
```
