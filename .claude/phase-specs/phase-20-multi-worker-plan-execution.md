# Phase 20 - Multi-Worker Plan Execution

## Goal

Turn an approved PlanContract into multiple bounded worker tasks and execute
them with real worker modes. Independent tasks may run in parallel; dependent or
risky tasks must run sequentially or require human review.

This phase closes the third major gap in the original blueprint:

```text
before:
  one real worker can execute one task

after:
  an approved plan can become several worker tasks, each with its own boundaries,
  evidence, control decisions, recovery path, and audit trail
```

## Hard Rule

Do not count a fixed YAML workflow as multi-worker plan execution. Phase 20 must
use the approved PlanContract steps as the source of execution.

## Preflight

Read:

```text
CLAUDE.md
.claude/phase-specs/phase-18-real-claude-code-worker-bridge.md
.claude/phase-specs/phase-19-real-llm-planning-council.md
src/orchestrator/mainline_executor.py
src/orchestrator/scheduler.py
src/orchestrator/planning.py
src/orchestrator/worker_protocol.py
src/orchestrator/workers/claude_code.py
src/orchestrator/control_plane.py
src/orchestrator/evidence.py
src/orchestrator/live_view.py
tests/
```

Run:

```bash
git status --short
```

## Non-Goals

- No new Planning Council roles.
- No new provider integration.
- No broad scheduler rewrite unless needed to execute PlanContract steps.
- No uncontrolled parallel writes to the same file.
- No fake worker success in real acceptance tests.
- No LangGraph dependency required for v1 landing. Native execution is enough if
  it supports dependency-aware worker tasks. LangGraph parity can be optional.

## Execution Model

AAO must convert PlanContract steps into worker tasks:

```text
PlanContract.steps[]
  -> WorkerTaskPacket per executable step
  -> execute with worker_kind / worker_mode
  -> collect WorkerResultPacket
  -> verify evidence
  -> update step status
  -> continue / retry / review / fail
```

Step status must be explicit:

```text
pending
running
passed
failed
blocked
needs_human_review
skipped_dependency_failed
```

## Parallelism Rules

Parallelism is allowed only when safe:

```text
can run in parallel when:
  - dependencies are complete
  - steps do not write overlapping files
  - neither step touches protected/high-risk files unless explicitly approved
  - concurrency limit allows it

must run sequentially when:
  - one step depends on another
  - write sets overlap
  - policy requires human review
  - evidence from an earlier step is required before the next step
```

Suggested config:

```text
AAO_MAX_WORKERS
AAO_WORKER_MODE = fake | packet | claude-code
AAO_PARALLEL_EXECUTION = true | false
```

Default should be conservative but useful:

```text
max_workers=2
parallel enabled only for non-overlapping independent steps
```

## Worker Isolation

Each worker task must have its own task directory:

```text
.aao/tasks/<run_id>/<step_id>/
```

Each task directory must contain separate:

```text
task.md
manifest.json
constraints.md
expected_evidence.md
result.md
status.json
observed/
```

Do not let one worker's result satisfy another worker's evidence requirements.

## Control Gates During Execution

Control must happen per step, not only at the very end.

Required gates:

```text
before worker launch:
  policy check
  allowed/denied/protected file check
  dependency check

after worker completion:
  evidence check
  test output check
  diff/path policy check
  recovery decision
  audit event
```

If a step fails, AAO must decide whether to:

```text
retry same step
request evidence
replan remaining steps
pause for human review
fail run
skip dependent steps
```

Reuse existing recovery logic. Do not invent a hidden recovery system in the
executor.

## User-Facing Command

There must be a realistic command path:

```bash
python -m orchestrator ask "implement a small multi-file task" \
  --planning-mode llm \
  --approve \
  --worker-mode claude-code \
  --max-workers 2
```

For tests, fake subprocess workers are allowed. For final smoke, at least one
real Claude Code worker must be used.

## Live View / Progress

During multi-worker execution, the user should be able to see:

```text
overall run status
current plan steps
which workers are running
which steps passed / failed / need review
evidence path per step
recovery decision per failed step
```

Do not build a new UI if existing live view can show this. Keep it terminal-first.

## Test Plan

Use fake subprocess workers for deterministic tests.

Required tests:

```text
test_plan_steps_create_separate_worker_packets
test_independent_non_overlapping_steps_can_run_in_parallel
test_dependency_order_is_respected
test_overlapping_write_sets_run_sequentially_or_block
test_worker_failure_blocks_dependent_steps
test_missing_evidence_in_one_step_does_not_satisfy_another_step
test_per_step_policy_violation_requires_review
test_successful_multi_step_run_produces_combined_audit_report
test_max_workers_limits_concurrent_execution
test_fake_worker_mode_does_not_count_as_real_smoke
```

False-positive guards:

```text
- Two steps that both write the same file must not run in parallel.
- A passed first step does not automatically pass later dependent steps.
- A failed optional step must not fail the whole run unless the plan marks it required.
- A real worker command failure must not be treated as a planning failure.
```

## Manual Smoke Test

Run a small real task with two steps:

```text
Step 1: make a tiny bounded source/doc change
Step 2: run or update a small test/check
```

The handoff must include:

```text
command used
plan summary
worker task paths
which steps ran real Claude Code vs fake
evidence paths per step
control decisions per step
final audit/report path
```

If real parallel Claude Code workers cannot be launched safely in the current
environment, run one real worker plus one fake worker and mark the limitation
explicitly. Do not claim full multi-real-worker landing until it is actually
done.

## Definition Of Done

Phase 20 is done only when:

```text
- Approved PlanContract steps drive execution.
- Multiple WorkerTaskPackets are created from the plan.
- Dependency and write-overlap rules are enforced.
- Independent safe tasks can run concurrently with a max-worker limit.
- Each step has separate evidence and status.
- ControlPlane decisions happen per step.
- Failed steps trigger recovery/skip/review behavior.
- Final report summarizes the whole plan and each worker step.
- Tests cover ordering, parallelism, failure, evidence, and policy.
- Manual smoke proves at least one real worker step in the multi-step path.
```

## Required Final Explanation To User

Explain it like this:

```text
Before Phase 20, AAO could send one bounded job to Claude Code.

After Phase 20, AAO can take an approved plan, split it into several jobs, run
safe jobs side by side, stop unsafe overlaps, and verify each worker's evidence
before combining the result.
```

## Claude Code Instruction

Read `CLAUDE.md` and this file. Implement only Phase 20. The goal is not more
planning and not more demo output. The goal is turning an approved plan into
real bounded worker execution with dependency-aware parallelism and per-step
control decisions.
