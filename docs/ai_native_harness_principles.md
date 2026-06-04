# AI-Native Harness Principles

Updated: 2026-06-04

This document records the working model behind AAO after the recent
stabilization and strategy discussions. It is not a phase log. Use it as the
short shared memory for future sessions.

## Core Position

AAO is not a normal agent demo. It is an AI-native engineering harness:

```text
Make AI workers usable in real software projects by making their work
planned, bounded, independently verified, reviewed, recoverable, and auditable.
```

The important distinction:

```text
AI worker can produce code.
AAO decides whether that code is trustworthy enough to continue.
```

## Three-Layer Model

Claude Code best practices, Claude ultracode/dynamic workflows, and AAO are not
competing systems. They operate at different layers.

```text
Claude best practices
= worker-level rules: context, CLAUDE.md, skills, tests, hooks, permissions,
  subagents, review, session hygiene.

Claude ultracode / dynamic workflows
= stronger worker backend: lets Claude Code create workflows and run multiple
  subagents for large work.

AAO
= project-level control layer: task routing, Planning Council, PlanContract,
  worker packets, evidence, policy, ControlPlane, reviewer, repair, audit,
  project session, resume.
```

Mental model:

```text
Best practices = worker handbook
Ultracode      = stronger work crew
AAO            = project manager + safety gate + QA + audit trail
```

AAO should absorb Claude best practices into its worker layer, and treat
ultracode as a possible future worker backend. AAO should not compete with
ultracode by trying to be the best "agent swarm" engine.

## Target Flow

```text
User task
  -> Front Door route: small / medium / large
  -> small: direct Codex/Claude, with source reading and checks
  -> medium: AAO controlled path, worker packet, evidence, checks
  -> large: Planning Council, PlanContract, human approval, milestones
  -> worker backend: Claude Code / Codex / future ultracode
  -> AAO-owned evidence: git status, git diff, required checks, test exits
  -> ControlPlane: policy, guardrail, failure classification, recovery
  -> reviewer: rule-based / LLM / external review
  -> artifacts: Control Trace, audit report, review brief, proof pack
```

Current reality:

```text
AAO has router/front-door CLI support.
AAO does not yet automatically intercept every Codex or Claude chat session.
The front door must be invoked by CLI or enforced by project instructions.
```

## Routing Principle

AAO uses deterministic routing rules as a stable default:

```text
small
  Explanation, question, read-only clarification.
  Direct assistant work is fine.

medium
  Single bugfix, small feature, focused test work, review of a bounded diff.
  Use AAO controlled execution when the task changes code or affects quality.

large
  Multi-stage, multi-module, architecture, audit, resume, project-level work.
  Use Planning Council -> PlanContract -> human approval -> milestones.
```

Model judgment can override the route, but the rule-based router gives a
testable, repeatable baseline. The stable default matters because each new AI
session may otherwise make a different process decision.

## Evidence Trust Hierarchy

Never treat worker self-report as ground truth.

```text
reported evidence
  status.json, result.md, worker-written summaries.
  Useful for narrative, not sufficient for trust.

observed evidence
  AAO-run git status, git diff, required checks, test exit codes,
  reviewer findings, audit artifacts.
  This is the basis for ControlPlane decisions.
```

The control path should prefer AAO-observed evidence over worker-reported
evidence whenever both exist.

## AAO Control vs Hooks / Permissions

AAO currently provides checkpoint-level control:

```text
Before worker:
  route, plan, approval, git baseline, Worker Doctor.

After worker:
  independent git diff/status, required checks, evidence classification,
  ControlPlane decision, reviewer, audit.
```

Claude hooks, permissions, and sandboxing provide tool-call-level control:

```text
Worker is about to modify a forbidden file -> hook blocks immediately.
Worker is about to run a dangerous command -> permission/sandbox blocks it.
```

Future direction:

```text
AAO should keep checkpoint-level control and integrate hooks/permissions as
worker-layer hard stops.
```

## Subagents and Investigation Workers

AAO already has execution-oriented multi-worker concepts through
`planned_worker_tasks` and `MultiWorkerExecutor`.

AAO does not yet have a mature investigation-subagent workflow.

Future useful shape:

```text
investigation task
  read_only = true
  allowed_files = task-scoped files
  expected_evidence = investigation_report.md

Examples:
  explorer A: inspect live_view/status/watch
  explorer B: inspect mainline state/trace writing
  explorer C: inspect tests and review coverage
```

Investigation subagents should reduce context pollution. They should report
facts and source paths, not implement changes.

## Session and Memory Discipline

One task per AI session does not mean disconnected work. The connection is the
repository record, not chat memory.

```text
AI session
  does the current task.

git commit
  records code state.

docs/current_state.md
  records current system state.

docs/next_steps.md
  records next concrete work.

outputs/evidence, outputs/reports, future Control Trace
  record observed facts.
```

Do not rely on chat history as the only memory. Chat context compacts and
drifts. Project state must live in files and artifacts.

## Interview and External Project Mode

For time-sensitive interview projects or external PRs, do not depend on full
AAO automation until the large path is stable.

Use AAO-lite:

```text
Explore problem
  -> PlanContract-lite
  -> vertical slices
  -> tests after each slice
  -> review
  -> README / design notes / verification
  -> clean GitHub handoff
```

This applies especially when the language is new, such as Go or Java. The goal
is not to become a language expert immediately. The goal is to own the project:
run it, test it, explain it, and patch small bugs.

## Code Ability Training

AI may draft most code. The human must own key paths.

Minimum recurring training:

```text
Read diffs.
Trace one runtime path.
Hand-write small tests.
Hand-fix small bugs.
Explain the behavior, evidence, and risk.
```

Target ability:

```text
AI can generate code, but the human can judge whether the critical change is
correct, bounded, tested, and explainable.
```

## Practice Order

Recommended order:

```text
1. Record this harness model.
2. Build lightweight Control Trace.
3. Run one large rehearsal.
4. Build Review Brief / PR Proof Pack.
5. Use AAO-lite for interview tasks and external PRs.
6. Keep daily code-control training.
7. Integrate hooks / permissions into the worker layer.
8. Evaluate ultracode as a future worker backend.
9. Only then revisit memory system / OpenViking / generic harness packaging.
```

Non-goal right now:

```text
Do not turn AAO into a broad platform before the real worker, evidence, review,
and trace path is demonstrably useful.
```
