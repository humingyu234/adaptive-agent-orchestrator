# Adaptive Agent Orchestrator - Working Guide

AAO 项目级入口。新会话先读这里，但不要只凭这里下结论。

## 0. Start Here

接管 AAO 时先做：

```bash
git status --short
python -m orchestrator front-door "<current task>"
```

然后读：

- `AAO_FRONT_DOOR.md`
- `docs/current_state.md`
- `docs/next_steps.md`
- 最新的 `docs/incidents/*.md` / `docs/reviews/*.md`

没有源码、测试或 artifact 证据前，不要说“没有这个功能”“已经接通”“测试通过”。

## 1. What AAO Is

AAO 是 **coding-agent execution control layer**。

它不是 Claude Code / Codex / LangGraph / CI 的替代品。更合理的分层是：

```text
Claude Code / Codex = worker
pytest / CI = checks
git = evidence source
ControlPlane = decision maker
AAO = coordinator + policy + evidence + recovery + audit
```

核心原则：

```text
worker 负责执行
AAO 负责独立验收
ControlPlane 负责判断能否放行
reviewer 只读复审 AAO-owned evidence
audit 负责留下可追溯记录
```

## 2. Task Routing

不要让小任务绕远路，也不要让复杂任务裸奔。

```text
small
  1-2 文件、低风险、简单问答或小修
  -> 直接做，但先读相关源码

medium
  多文件、小特性、bugfix、需要测试/evidence
  -> AAO controlled

large
  多阶段、多 worker、可恢复、需要 milestone/resume
  -> project session
```

真实 worker 必须显式使用 `--worker-mode claude-code`。fake / packet / dry-run 结果必须明确标成非真实执行。

## 3. Hard Rules

- 先读源码和 artifact，不凭聊天记忆判断。
- 不把 worker 自报当 observed evidence。
- 不把 fake / demo / deterministic fixture 说成 real run。
- 不让 reviewer 写代码；reviewer 只输出 findings。
- 不让 AAO 自动修改 AAO 核心文件，除非用户明确要求。
- 不编辑 `.env`、secrets、`.venv`、`outputs/`、`tmp/`，除非任务明确需要。
- 不引入大框架来掩盖主链路未跑通。
- 不扩 memory / dashboard / multi-worker，直到 real single-worker medium 路径稳定。

## 4. Current Priority

当前不要横向扩功能。按这个顺序：

```text
1. Review latest evidence-integrity commit if needed
2. Add Worker Doctor / Claude worker preflight
3. Run medium real task acceptance
4. Validate guardrail / failure / recovery / audit on a controlled failure
5. Add lightweight Control Trace for demo and PR review
```

Parking lot:

```text
AAO memory system
OpenViking evaluation
deep LangGraph hardening
large dashboard
multi-worker real reliability
```

## 5. Project Skills

Official Claude Code skill entrypoints live under `.claude/skills/<skill>/SKILL.md`.

Use the relevant skill when the task matches:

| Skill | Use when |
| --- | --- |
| `aao-core-builder` | changing AAO runtime/control/evidence/worker code |
| `aao-boundary-test-designer` | adding or changing runtime behavior |
| `aao-reviewer-mode` | doing isolated read-only review |
| `aao-tutor-explanation` | explaining completed work to the user |
| `aao-scope-guard` | scope starts expanding |
| `aao-live-visibility` | status, progress, evidence, report, Control Trace |
| `aao-phase-handoff` | ending a work slice or preparing next session |

Legacy `.claude/project-skills/*.md` files remain only because old phase specs reference them.
New work should use `.claude/skills/.../SKILL.md`.

## 6. Verification

Before claiming done, report exactly what was verified.

For code changes, prefer:

```bash
git diff --check
python -m compileall -q src tests
python -m pytest -q <targeted tests>
```

Run full tests when the change touches shared runtime behavior, control contracts, evidence integrity, worker execution, or project session paths.

Core explanation after work:

```text
what changed
why it mattered
how runtime path works now
what tests/artifacts prove
what remains unproven
next recommended step
```

Keep explanations direct and concrete.
