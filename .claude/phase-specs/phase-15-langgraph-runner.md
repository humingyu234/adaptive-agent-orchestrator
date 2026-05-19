# Phase 15 - LangGraph Runner

## Goal

Add LangGraph as an optional orchestrated-mode runner so AAO can execute complex
workflow structure without reimplementing DAG, checkpoint, resume, branching,
parallel steps, and human interrupt machinery.

After this phase, AAO should be able to run a small approved workflow through a
LangGraph-backed runner while keeping AAO's own ControlPlane, evidence,
recovery, memory, policy, and audit contracts in charge.

Mental model:

```text
User request
  -> TaskRouter marks task as orchestrated
  -> Phase 13 Planning Council creates approved PlanContract
  -> LangGraphRunner executes workflow structure
       -> before/after each node, AAO ControlPlane checks the result
       -> evidence is recorded through AAO EvidencePack
       -> failures go through AAO RecoveryPlaybook
       -> human interrupt maps to AAO HumanReviewGate
  -> AAO report/audit remains the final source of record
```

LangGraph is the railway track. AAO is still the signal system, checkpoint
inspector, incident desk, and audit office.

## Why This Phase Exists

NativeRunner is useful for local demos and simple sequential execution, but AAO
should not spend its core engineering energy rebuilding mature workflow engine
features.

Use LangGraph for:

```text
DAG execution
checkpoint / resume
branching
parallel node execution
interrupt / human approval points
state passing between nodes
```

Keep AAO responsible for:

```text
task sizing
plan contract
policy decision
guardrail decision
evaluation decision
failure classification
recovery action
evidence integrity
human review meaning
memory context
audit report
```

This is not a retreat from AAO. It is the correct split:

```text
LangGraph decides how nodes move.
AAO decides whether node results are acceptable.
```

## Preflight

Before editing, read:

```text
CLAUDE.md
.claude/phase-specs/phase-09-task-router.md
.claude/phase-specs/phase-10-runtime-policy-enforcement.md
.claude/phase-specs/phase-11-recovery-playbook.md
.claude/phase-specs/phase-12-claude-code-worker-bridge.md
.claude/phase-specs/phase-13-planning-council.md
.claude/phase-specs/phase-14-memory-layer.md
.claude/project-skills/aao-scope-guard.md
.claude/project-skills/aao-boundary-test-designer.md
.claude/project-skills/aao-reviewer-mode.md
.claude/project-skills/aao-phase-handoff.md
```

Then inspect:

```text
src/orchestrator/scheduler.py
src/orchestrator/planning.py
src/orchestrator/task_router.py
src/orchestrator/control_plane.py
src/orchestrator/control_models.py
src/orchestrator/recovery.py
src/orchestrator/evidence.py
src/orchestrator/worker_protocol.py
src/orchestrator/memory.py
src/orchestrator/report_writer.py
src/orchestrator/live_view.py
tests/test_planning_council.py
tests/test_control_plane.py
tests/test_claude_code_worker_bridge.py
```

Run first:

```bash
git status --short
```

Name unrelated dirty files in the handoff. Do not use `git add .`.

## Non-Goals

- Do not replace ControlPlane.
- Do not replace NativeRunner for simple/direct or medium/controlled tasks.
- Do not migrate the whole project to LangGraph.
- Do not require LangGraph for AAO core tests.
- Do not call real LLM APIs in tests.
- Do not call Claude Code directly from LangGraphRunner tests.
- Do not make LangGraph the source of policy/recovery decisions.
- Do not hide AAO evidence inside LangGraph state only.
- Do not add a new dashboard.
- Do not rewrite scheduler broadly.
- Do not implement distributed execution, queues, remote workers, or cloud
  orchestration.

## Allowed Files

Prefer this write set:

```text
src/orchestrator/runners/__init__.py
src/orchestrator/runners/langgraph_runner.py
src/orchestrator/runners/native_runner.py
src/orchestrator/control_models.py
src/orchestrator/control_plane.py
src/orchestrator/evidence.py
src/orchestrator/planning.py
src/orchestrator/task_router.py
src/orchestrator/scheduler.py
src/orchestrator/report_writer.py
src/orchestrator/live_view.py
tests/test_langgraph_runner.py
tests/test_runner_contracts.py
tests/test_runtime_smoke.py
```

Rules:

- Create `src/orchestrator/runners/` if it does not exist.
- Keep LangGraph imports optional and isolated inside `langgraph_runner.py`.
- If adding a dependency in `pyproject.toml` or requirements, make it optional
  or clearly explain why it is required.
- If LangGraph is not installed, AAO should fail gracefully for
  orchestrated/langgraph mode and NativeRunner tests should still pass.

## Core Concepts

### Runner

A runner executes workflow structure. It is not a worker.

```text
NativeRunner
  Runs AAO's existing local sequential workflow.

LangGraphRunner
  Runs an approved workflow through LangGraph's graph/checkpoint machinery.
```

Do not call LangGraphRunner a worker.

### Worker

A worker performs work inside a node:

```text
Claude Code worker
TestWorker
ReviewWorker
LLM worker
tool/search worker
human reviewer
```

LangGraphRunner may call a worker adapter, but it is not itself the worker.

### RunnerResult

If a shared model does not already exist, define a small runner result contract:

```text
run_id
status
steps_completed
last_node
evidence_paths
control_events
failure_record optional
recovery_actions
checkpoint_id optional
report_path optional
```

Do not create a parallel reporting system.

## Required Behavior

### 1. LangGraph is selected only for orchestrated mode

Expected routing:

```text
off/direct/log/controlled simple task   -> no LangGraph
controlled medium task                  -> no LangGraph by default
orchestrated complex task               -> LangGraphRunner allowed
explicit user override                  -> LangGraphRunner allowed if installed
```

If existing run-mode names differ, adapt to current enums. Do not create a
second task router.

### 2. Approved plan becomes graph input

Phase 13 `PlanContract` is the primary input for complex workflows.

Mapping:

```text
PlanContract.steps              -> graph nodes or node sequence
PlannedWorkerTask               -> node work packet
human_review_gates              -> interrupt / approval nodes
required_evidence               -> post-node evidence checks
success_criteria                -> final completion check
stop_conditions                 -> early stop rules
non_goals                       -> policy/context constraints
```

Do not execute an unapproved plan.

### 3. ControlPlane wraps node execution

Each meaningful node should follow this control path:

```text
pre_node_policy_check
  -> run node / worker
  -> collect observed/reported/inferred evidence
  -> post_node_control_check
  -> recovery decision if needed
  -> record control event
```

The important test is not "LangGraph ran"; it is:

```text
AAO still gets to say continue / retry / pause / fail after each node.
```

### 4. Evidence stays in AAO's contract

LangGraph state may carry references, but AAO evidence files/events remain the
auditable source.

Do not bury evidence only inside graph state.

### 5. Checkpoint and resume are minimal but real

Implement one cheap checkpoint/resume path:

```text
run first node
checkpoint state
resume from checkpoint
complete remaining node
```

It can use LangGraph's checkpointer if available. If test environment cannot
install/use LangGraph, implement a small backend abstraction and test the AAO
runner contract with a fake graph backend, plus skip a true LangGraph integration
test when unavailable.

Do not overbuild persistence.

### 6. Human interrupt maps to AAO human review

If a node requires human review:

```text
LangGraph interrupt / pause
  -> AAO HumanReviewGate state
  -> user approve/reject/edit
  -> runner resumes or stops
```

Do not treat a LangGraph pause as success.

### 7. NativeRunner remains valid

The user must still be able to use AAO without LangGraph.

If LangGraph is missing:

```text
simple/direct tasks still work
controlled tasks still work
orchestrated langgraph mode reports clear unavailable error
tests for core control still pass
```

## Optional Dependency Strategy

Preferred approach:

```text
try:
    import langgraph
except ImportError:
    LangGraphRunner unavailable with clear error
```

Tests should split:

```text
contract tests with fake backend          -> always run
real LangGraph smoke test if installed    -> skip if unavailable
```

This keeps AAO usable in clean local environments.

## Test Requirements

Required tests:

```text
test_langgraph_runner_is_unavailable_cleanly_when_dependency_missing
test_native_runner_still_works_without_langgraph
test_langgraph_runner_requires_approved_plan
test_langgraph_runner_executes_simple_approved_workflow
test_langgraph_runner_calls_control_plane_after_node
test_langgraph_runner_records_evidence_in_aao_contract
test_langgraph_runner_stops_when_control_plane_blocks_node
test_langgraph_runner_maps_human_review_gate_to_interrupt
test_langgraph_runner_can_checkpoint_and_resume_basic_state
test_langgraph_runner_does_not_treat_memory_as_evidence
test_langgraph_runner_preserves_worker_task_boundaries
```

False-positive guards:

```text
test_direct_task_does_not_pay_langgraph_cost
test_unapproved_plan_never_executes
test_graph_state_alone_does_not_count_as_evidence
```

Regression tests:

```text
existing task router tests still pass
existing planning council tests still pass
existing control/recovery tests still pass
existing worker bridge tests still pass
existing memory tests still pass
```

Tests must not call real LLM APIs.

## Suggested Implementation Order

### Step 1 - Add runner interface / folder

If the project does not already have runner abstractions, introduce the smallest
one needed:

```text
RunnerProtocol
RunnerResult
NativeRunner compatibility wrapper if needed
LangGraphRunner shell
```

Do not move the entire scheduler in this phase.

### Step 2 - Implement fake backend contract tests

Before fighting LangGraph dependency/API details, prove AAO's runner contract:

```text
approved plan required
control after node
evidence recorded
block stops execution
human review pauses
checkpoint/resume state flows
```

### Step 3 - Add LangGraph adapter

Use the current official LangGraph API available in the environment. If API
version differs from memory, inspect installed docs/source before coding.

Keep all LangGraph-specific code in `langgraph_runner.py`.

### Step 4 - Wire orchestrated mode

Minimal scheduler/task router integration:

```text
if run_mode == orchestrated and runner == langgraph:
    require approved plan
    call LangGraphRunner
else:
    existing path
```

### Step 5 - Report/live-view summary

Expose compact fields:

```text
runner=langgraph
checkpoint_id
last_node
node_count
control_decisions
human_review_state
evidence_count
```

Do not build a new UI.

## Validation Commands

Use WSL explicitly from Windows PowerShell:

```bash
wsl -e bash -lc "cd /home/administrator/adaptive-agent-orchestrator && python3 -m pytest -q tests/test_langgraph_runner.py tests/test_runner_contracts.py"
wsl -e bash -lc "cd /home/administrator/adaptive-agent-orchestrator && python3 -m pytest -q tests/test_planning_council.py tests/test_control_plane.py tests/test_claude_code_worker_bridge.py tests/test_memory.py"
wsl -e bash -lc "cd /home/administrator/adaptive-agent-orchestrator && python3 -m compileall src/orchestrator"
wsl -e bash -lc "cd /home/administrator/adaptive-agent-orchestrator && git diff --check"
```

If editing directly inside WSL, equivalent local commands are fine.

## Definition Of Done

- LangGraphRunner exists as optional runner infrastructure.
- NativeRunner/core path works without LangGraph installed.
- Orchestrated tasks require an approved PlanContract before graph execution.
- ControlPlane is called after meaningful nodes.
- Evidence is recorded through AAO contracts, not hidden only in graph state.
- A blocked control decision stops or pauses graph execution.
- Human review gate maps to interrupt/pause/resume semantics.
- Basic checkpoint/resume behavior is tested.
- Direct/small tasks do not pay LangGraph overhead.
- No real LLM/API calls in tests.
- Handoff clearly states whether real LangGraph integration ran or was skipped.

## Reviewer Checklist

Reviewer must check:

```text
Is LangGraph only a runner, not the AAO brain?
Can AAO still run without LangGraph?
Can any unapproved plan execute?
Does every node result pass through ControlPlane?
Is evidence still AAO-owned?
Does checkpoint/resume actually preserve state?
Does human interrupt map to AAO review, not success?
Did scheduler grow too much?
Are tests deterministic and API-free?
```

Explain bugs in plain language before technical diagnosis.

## Claude Code Instruction

Read `CLAUDE.md` and this file. Implement only Phase 15.

Keep the work centered on one thing: LangGraph may execute complex workflow
structure, but AAO still owns planning approval, control decisions, evidence,
recovery, memory, and audit.

After implementation, explain naturally what LangGraph now does, what AAO still
controls, which tests prove the split, and what remains intentionally deferred.
