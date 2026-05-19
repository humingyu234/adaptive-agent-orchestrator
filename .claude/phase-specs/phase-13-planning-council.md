# Phase 13 - Planning Council

## Goal

Add a bounded planning checkpoint before complex task execution.

After this phase, AAO should be able to take a complex user request, generate a
reviewed plan contract, show it to the user, accept edit/reject/approve input,
and only then hand the approved work to a runner or worker.

Mental model:

```text
User asks for a complex task
  -> TaskRouter marks it orchestrated
  -> Planning Council creates a plan contract
  -> ControlPlane checks the plan is bounded and evidenced
  -> User approves / edits / rejects
  -> Runner or Worker Bridge executes only after approval
```

This phase is about planning quality and approval. It is not about making the
system more autonomous.

## Why This Phase Exists

AAO already has stronger runtime control:

```text
Phase 9    routes task size and run mode
Phase 10   enforces runtime policy
Phase 11   maps failures to recovery decisions
Phase 12   hands bounded work packets to Claude Code workers
```

The next failure mode is earlier than execution: the first plan can be vague,
too broad, risky, or impossible to validate. If AAO starts execution from a bad
plan, later guardrails can only stop damage. Planning Council should prevent
bad execution by creating a concrete plan contract first.

Key distinction:

```text
Planning Council decides what should be attempted.
Runner/Worker performs the approved work.
ControlPlane checks whether the plan and later execution are acceptable.
```

Do not put execution inside the council.

## Preflight

Before editing, read:

```text
CLAUDE.md
.claude/phase-specs/phase-09-task-router.md
.claude/phase-specs/phase-09a-runtime-mode-cleanup-contract.md
.claude/phase-specs/phase-10-runtime-policy-enforcement.md
.claude/phase-specs/phase-11-recovery-playbook.md
.claude/phase-specs/phase-12-claude-code-worker-bridge.md
.claude/project-skills/aao-scope-guard.md
.claude/project-skills/aao-boundary-test-designer.md
.claude/project-skills/aao-reviewer-mode.md
.claude/project-skills/aao-phase-handoff.md
.claude/project-skills/aao-tutor-explanation.md
```

Then inspect:

```text
src/orchestrator/task_router.py
src/orchestrator/control_models.py
src/orchestrator/control_plane.py
src/orchestrator/policy.py
src/orchestrator/recovery.py
src/orchestrator/worker_protocol.py
src/orchestrator/workers/claude_code.py
src/orchestrator/scheduler.py
src/orchestrator/report_writer.py
src/orchestrator/live_view.py
src/orchestrator/__main__.py
tests/test_task_router.py
tests/test_control_plane.py
tests/test_claude_code_worker_bridge.py
```

Run first:

```bash
git status --short
```

Name unrelated dirty files in the handoff. Do not use `git add .`.

## Non-Goals

- No executing tasks inside Planning Council.
- No calling Claude Code from Planning Council.
- No terminal automation.
- No bypassing worker permission prompts.
- No LangGraph runner in this phase.
- No ECC integration in this phase.
- No memory layer.
- No hidden real LLM/API calls in tests.
- No multi-round debate loop without a hard cap.
- No running council for small/direct tasks by default.
- No broad scheduler rewrite.
- No dashboard rewrite.
- No pretending plan approval means execution succeeded.

## Allowed Files

Prefer this write set:

```text
src/orchestrator/planning.py
src/orchestrator/control_models.py
src/orchestrator/control_plane.py
src/orchestrator/task_router.py
src/orchestrator/scheduler.py
src/orchestrator/report_writer.py
src/orchestrator/live_view.py
src/orchestrator/__main__.py
tests/test_planning_council.py
tests/test_task_router.py
tests/test_control_plane.py
tests/test_runtime_smoke.py
```

Rules:

- Put planning-specific dataclasses/models in `planning.py` unless another
  module truly needs them.
- Only add shared control data to `control_models.py`.
- Touch `scheduler.py` only for minimal wiring: invoke council before execution
  for complex/orchestrated tasks and respect approve/edit/reject decisions.
- Do not widen `worker_protocol.py` unless a planned worker task must be mapped
  into an existing `WorkerTaskPacket`.
- Do not introduce a new dependency for this phase.

## Core Concepts

### PlanCandidate

One planning perspective's proposal.

Expected fields:

```text
role              # planner / risk_reviewer / execution_planner
summary
steps
risks
non_goals
required_evidence
human_review_gates
assumptions
```

### PlanContract

The final merged plan that can be shown to the user and audited.

Expected fields:

```text
objective
run_mode
task_size
steps
risks
non_goals
required_evidence
human_review_gates
success_criteria
stop_conditions
planned_worker_tasks
source_candidates
approval_status       # draft / approved / edited / rejected
```

### PlannedWorkerTask

A planned unit of work that can later become a Phase 12 worker packet.

Expected fields:

```text
title
objective
allowed_files
denied_files
required_checks
expected_evidence
risk_level
```

Do not execute it in Phase 13. It is only a plan-level work order.

## Required Behavior

### 1. Council is gated by task size and run mode

Planning Council should run only when the task is complex/orchestrated.

Expected behavior:

```text
small/direct/log task      -> no council
medium/controlled task     -> no council by default unless explicitly requested
complex/orchestrated task  -> council required before execution
```

If existing router names differ, adapt to existing enums. Do not invent a
second router.

### 2. Council produces bounded candidates

Use three planning perspectives:

```text
planner             -> proposes a useful plan
risk_reviewer       -> challenges scope, risk, missing evidence, unclear success
execution_planner   -> turns the plan into small executable steps
```

Implementation can use deterministic local classes or fake advisors first.
Do not require three real model calls for tests.

Hard caps:

```text
max_candidates = 3
max_revision_rounds = 1
no unbounded discussion loop
```

### 3. Council merges one final PlanContract

The final plan must include:

```text
objective
ordered steps
non-goals
risks
assumptions
required evidence
success criteria
stop conditions
human review gates
planned worker tasks when useful
```

If these fields are missing, the plan is not execution-ready.

### 4. ControlPlane verifies plan quality

Add a small plan verification path to ControlPlane or a planning validator that
ControlPlane calls.

Plan verification should catch:

```text
missing steps
missing success criteria
missing required evidence for code-changing work
empty non-goals for broad tasks
high-risk task without human review gate
planned worker task without boundaries
```

Decision mapping:

```text
valid plan                 -> continue / request user approval
missing required fields     -> request_plan_revision
high risk without gate      -> needs_human_review
rejected by user            -> fail_or_cancel without execution
```

Use existing `ControlDecision` style where possible. Do not create a parallel
decision system if current models can carry the result.

### 5. User approval is explicit

Support three user paths:

```text
approve -> plan becomes approved and execution may continue
edit    -> user edits or adds constraints; council updates the plan
reject  -> execution stops
```

This can be CLI-level and testable without a full UI.

Do not auto-approve a complex plan.

### 6. Worker Bridge integration is plan-to-packet, not execution

For planned worker tasks, Phase 13 may create structures that can be converted
into Phase 12 `WorkerTaskPacket`.

The mapping should preserve:

```text
objective
allowed_files
denied_files
protected_files if present
required_checks
expected_evidence
risk_level
run_mode
```

Do not invoke Claude Code in this phase. The council only prepares bounded work.

### 7. Visibility and reports include the plan

If practical, include a compact planning summary in live view and reports:

```text
plan_status
number_of_steps
top_risks
required_evidence
approval_status
```

Keep this small. Do not build a new dashboard.

## Test Requirements

Add focused tests. Prefer fake/deterministic advisors.

Required tests:

```text
test_small_task_does_not_invoke_planning_council
test_complex_task_generates_plan_contract
test_plan_contract_contains_steps_risks_evidence_success_and_non_goals
test_plan_missing_required_evidence_requests_revision
test_high_risk_plan_without_gate_requires_human_review
test_user_rejects_plan_and_execution_does_not_start
test_user_edits_plan_and_contract_is_updated
test_planned_worker_task_preserves_boundaries_for_worker_packet
test_council_keeps_advisor_disagreements_for_audit
test_council_has_bounded_rounds
```

Regression tests:

```text
existing task router behavior still passes
existing worker bridge evidence tests still pass
existing control plane policy/recovery tests still pass
```

Tests must not call real LLM APIs.

## Suggested Implementation Order

### Step 1 - Add planning models and local advisors

Create `src/orchestrator/planning.py`.

Implement:

```text
PlanCandidate
PlannedWorkerTask
PlanContract
PlanningCouncil
PlanningAdvisor protocol/interface
LocalPlannerAdvisor
LocalRiskReviewerAdvisor
LocalExecutionPlannerAdvisor
```

Keep advisors deterministic enough for tests.

### Step 2 - Add plan verification

Add plan verification through ControlPlane or a small planning validator called
by ControlPlane.

The important behavior is not "the plan sounds nice"; it is:

```text
Can this plan be executed, checked, stopped, and reviewed?
```

### Step 3 - Wire complex-task planning

Use the existing router/run mode result.

For complex/orchestrated tasks:

```text
route task
build plan
verify plan
ask approval/edit/reject
only approved plan can proceed
```

Keep the scheduler change small. If wiring becomes large, stop and report the
boundary problem instead of expanding scheduler indefinitely.

### Step 4 - Add report/live-view summary

Add only compact fields. Do not build a planning UI.

### Step 5 - Tests and handoff

Run focused tests first, then broader relevant tests.

## Validation Commands

Use the project environment that actually contains the source. If running from
Windows PowerShell, prefer WSL explicitly:

```bash
wsl -e bash -lc "cd /home/administrator/adaptive-agent-orchestrator && python3 -m pytest -q tests/test_planning_council.py"
wsl -e bash -lc "cd /home/administrator/adaptive-agent-orchestrator && python3 -m pytest -q tests/test_task_router.py tests/test_control_plane.py tests/test_claude_code_worker_bridge.py"
wsl -e bash -lc "cd /home/administrator/adaptive-agent-orchestrator && python3 -m compileall src/orchestrator"
wsl -e bash -lc "cd /home/administrator/adaptive-agent-orchestrator && git diff --check"
```

If the repository is being edited directly inside WSL, the equivalent local
commands are fine:

```bash
python3 -m pytest -q tests/test_planning_council.py
python3 -m pytest -q tests/test_task_router.py tests/test_control_plane.py tests/test_claude_code_worker_bridge.py
python3 -m compileall src/orchestrator
git diff --check
```

## Definition Of Done

- Complex/orchestrated tasks produce a `PlanContract` before execution.
- Small/direct tasks do not pay planning cost by default.
- Plan contract includes steps, risks, non-goals, required evidence, success
  criteria, stop conditions, and human review gates when needed.
- Plan verification blocks or requests revision for vague/unbounded plans.
- User approve/edit/reject paths are implemented and tested.
- Rejected plans do not execute.
- Approved plans can produce planned worker tasks compatible with Phase 12
  packet boundaries.
- Advisor disagreements are preserved for audit.
- No real LLM/API calls in tests.
- Existing Phase 10/11/12 tests still pass.
- Handoff clearly lists what was implemented, what remains stubbed, and which
  runtime support is not yet implemented.

## Reviewer Checklist

Reviewer must check:

```text
Is the council gated to complex tasks?
Can any path execute before approval?
Does the plan include evidence and stop conditions?
Are high-risk tasks forced through human review?
Are worker task boundaries preserved?
Are tests deterministic and API-free?
Did scheduler grow too much?
Are missing capabilities listed as handoff, not silently treated as done?
```

Explain any bug in plain language before the technical diagnosis.

## Claude Code Instruction

Read `CLAUDE.md` and this file. Implement only Phase 13.

Keep the work centered on one thing: complex tasks get a reviewed, bounded,
user-approved plan before execution. Do not add new runners, model providers,
memory, LangGraph, ECC, or dashboard work in this phase.

After implementation, explain naturally what changed, why the design is shaped
this way, what tests prove, and what the user should understand before moving
to the next phase.
