# Phase 16 - Golden Scenario Suite

## Goal

Build a deterministic golden scenario suite that proves AAO's control layer
works across the failure modes it claims to handle.

After this phase, AAO should have a small but strong set of repeatable scenarios
that can be run before demos, releases, refactors, and external review.

Mental model:

```text
Golden scenario = a small staged incident
  -> fake worker / fake runner produces known behavior
  -> AAO control layer observes it
  -> AAO decides continue / block / retry / pause / fail
  -> test asserts the decision, evidence, recovery, and report path
```

This phase is the proof phase. It turns "AAO has a control layer" into "AAO
blocks the exact bad behaviors it was built to catch."

## Why This Phase Exists

AAO's portfolio value depends on proof, not architecture vocabulary.

Without golden scenarios, AAO risks looking like:

```text
many modules
many phase names
unclear whether the control loop really works
```

With golden scenarios, AAO can show:

```text
worker claims done but evidence missing       -> blocked
protected file changed                         -> human review
tests fail                                     -> bounded recovery
plan too vague                                 -> revision requested
tool repeats with no progress                  -> halted
reported memory claims                         -> not accepted as proof
high-risk task without gate                    -> blocked before execution
audit report generated                         -> evidence visible
```

This is the suite that makes the project hard to dismiss as a toy.

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
.claude/phase-specs/phase-15-langgraph-runner.md
.claude/project-skills/aao-boundary-test-designer.md
.claude/project-skills/aao-reviewer-mode.md
.claude/project-skills/aao-phase-handoff.md
.claude/project-skills/aao-tutor-explanation.md
```

Then inspect:

```text
src/orchestrator/control_plane.py
src/orchestrator/control_models.py
src/orchestrator/policy.py
src/orchestrator/recovery.py
src/orchestrator/guardrails.py
src/orchestrator/evidence.py
src/orchestrator/planning.py
src/orchestrator/memory.py
src/orchestrator/worker_protocol.py
src/orchestrator/report_writer.py
src/orchestrator/runners/
tests/
```

Run first:

```bash
git status --short
```

Name unrelated dirty files in the handoff. Do not use `git add .`.

## Non-Goals

- No huge benchmark suite.
- No live LLM calls.
- No real Claude Code process.
- No network-dependent tests.
- No performance/load benchmark unless deterministic and cheap.
- No snapshot-only tests that ignore runtime path.
- No broad production dataset.
- No dashboard work.
- No new heavy dependency.
- No attempt to prove every possible agent failure.

## Allowed Files

Prefer this write set:

```text
tests/golden/
tests/golden/scenarios/
tests/test_golden_scenarios.py
examples/golden/
src/orchestrator/testing.py
src/orchestrator/golden.py
src/orchestrator/control_models.py
src/orchestrator/report_writer.py
docs/golden_scenarios.md
```

Rules:

- Add `golden.py` or `testing.py` only if helper code is useful outside one
  test file.
- Keep fake workers/runners deterministic.
- Do not modify production control logic just to make scenarios pass unless a
  real bug is exposed. If a real bug is exposed, fix it with focused tests.

## Golden Scenario Contract

Each golden scenario should have a small structured definition:

```text
id
title
purpose
task_input
run_mode
setup
fake_worker_behavior
expected_control_decisions
expected_failure_category optional
expected_recovery_action optional
expected_evidence
expected_report_sections
must_not_happen
```

Keep scenarios readable. A reviewer should understand each scenario in under a
minute.

## Scenario Runner

Implement a deterministic local scenario runner, not a new product runtime.

Expected shape:

```text
GoldenScenarioRunner
  -> builds fake state / fake plan / fake worker packet
  -> invokes the relevant AAO control path
  -> records control events
  -> returns GoldenScenarioResult
```

`GoldenScenarioResult` should include:

```text
scenario_id
status
control_decisions
failure_record
recovery_actions
evidence_items
report_path optional
assertions
```

The suite should test the runtime path, not only final strings.

## Required Scenario Set

Implement at least these scenarios:

```text
normal_completion_with_observed_evidence
missing_evidence_blocks_success
worker_reported_tests_without_observed_output
test_failure_triggers_bounded_recovery
guardrail_blocks_secret_leak
policy_denies_protected_file_change
high_risk_task_requires_human_review
human_review_approved_continues
human_review_rejected_stops
repeated_tool_call_halts_or_blocks
known_failure_category_uses_explicit_propagation
memory_hint_does_not_count_as_evidence
planning_missing_required_evidence_requests_revision
user_rejects_plan_and_execution_does_not_start
small_task_bypasses_heavy_orchestration
medium_task_uses_controlled_mode
complex_task_requires_plan_contract
runner_interrupt_can_resume
audit_report_contains_evidence_failure_and_recovery
regression_compare_detects_degraded_result
```

If one scenario cannot be implemented because the underlying runtime support is
not ready, do not silently skip it. Mark it as an explicit expected gap in the
handoff and add a focused TODO test if appropriate.

## Boundary Test Matrix

The suite must cover these contracts:

### Contract 1 - Evidence beats claims

```text
Bad case:
  worker says "tests passed" but no observed test output exists
Expected:
  completion is blocked or marked missing_evidence

Valid case:
  observed test output exists
Expected:
  evidence check can pass

False-positive guard:
  memory says previous tests passed
Expected:
  current run still needs current evidence
```

### Contract 2 - Policy controls risky actions

```text
Bad case:
  worker modifies protected file
Expected:
  needs_human_review or deny

Valid case:
  worker modifies allowed file
Expected:
  no policy block

Boundary:
  reviewer role tries to write
Expected:
  denied
```

### Contract 3 - Recovery is bounded

```text
Bad case:
  same retryable failure repeats beyond limit
Expected:
  stop / human review, no infinite loop

Valid case:
  first retryable provider timeout
Expected:
  retry_with_backoff allowed
```

### Contract 4 - Planning prevents bad execution

```text
Bad case:
  complex plan lacks evidence/success criteria
Expected:
  request revision before execution

Valid case:
  approved plan has evidence, gates, and boundaries
Expected:
  may execute
```

### Contract 5 - Reports are honest

```text
Bad case:
  report claims success without evidence/failure record
Expected:
  test fails

Valid case:
  report includes evidence, decision, failure/recovery if present
Expected:
  report is accepted
```

## Test Requirements

Required tests:

```text
test_golden_normal_completion_with_observed_evidence
test_golden_missing_evidence_blocks_success
test_golden_reported_tests_do_not_count_as_observed
test_golden_protected_file_requires_review
test_golden_reviewer_cannot_write_files
test_golden_recovery_retry_is_bounded
test_golden_known_failure_category_does_not_use_infer_fallback
test_golden_memory_hint_does_not_count_as_evidence
test_golden_plan_missing_evidence_requests_revision
test_golden_rejected_plan_does_not_execute
test_golden_repeated_tool_call_is_blocked
test_golden_audit_report_contains_evidence_failure_and_recovery
```

Regression tests:

```text
existing control plane tests still pass
existing policy tests still pass
existing recovery tests still pass
existing worker bridge tests still pass
existing planning tests still pass
existing memory tests still pass
existing runner tests still pass
```

Tests must be deterministic and API-free.

## Suggested Implementation Order

### Step 1 - Define golden scenario model

Add small scenario/result models. Keep them serializable.

### Step 2 - Build fake workers/runners

Fake components should produce controlled behavior:

```text
fake success with evidence
fake success without evidence
fake test failure
fake protected file write
fake repeated tool call
fake human approval/rejection
fake interrupted runner
```

### Step 3 - Implement scenario runner

Call real AAO control functions wherever possible. Avoid testing a fake copy of
the control layer.

### Step 4 - Add core golden tests

Start with the most valuable six:

```text
missing evidence
protected file
bounded recovery
plan revision
memory not evidence
audit report
```

Then add the rest.

### Step 5 - Add docs/demo hook

Write a short `docs/golden_scenarios.md` that explains:

```text
what the suite proves
how to run it
which scenarios map to AAO's demo
known gaps
```

This feeds Phase 17.

## Validation Commands

Use WSL explicitly from Windows PowerShell:

```bash
wsl -e bash -lc "cd /home/administrator/adaptive-agent-orchestrator && python3 -m pytest -q tests/golden tests/test_golden_scenarios.py"
wsl -e bash -lc "cd /home/administrator/adaptive-agent-orchestrator && python3 -m pytest -q tests/test_control_plane.py tests/test_memory.py tests/test_planning_council.py tests/test_claude_code_worker_bridge.py"
wsl -e bash -lc "cd /home/administrator/adaptive-agent-orchestrator && python3 -m compileall src/orchestrator"
wsl -e bash -lc "cd /home/administrator/adaptive-agent-orchestrator && git diff --check"
```

If editing directly inside WSL, equivalent local commands are fine.

## Definition Of Done

- Golden suite is deterministic and API-free.
- At least 20 golden scenarios exist or explicit gaps are documented.
- The suite proves control decisions, not only final output text.
- Missing evidence, policy deny, human review, recovery, memory/evidence
  separation, planning revision, and audit report are all covered.
- False-positive guards exist for valid behavior.
- Scenario docs explain how to run and what the suite proves.
- Existing Phase 10-15 tests still pass.
- Handoff lists which scenarios are implemented, skipped, or deferred and why.

## Reviewer Checklist

Reviewer must check:

```text
Does each golden scenario map to a real AAO control promise?
Are tests deterministic and offline?
Do tests call real control code instead of a fake duplicate?
Does the suite catch false green outcomes?
Are valid behaviors protected from false positives?
Are known gaps documented honestly?
Is this useful for Phase 17 demo/proof pack?
```

Explain bugs in plain language before technical diagnosis.

## Claude Code Instruction

Read `CLAUDE.md` and this file. Implement only Phase 16.

Keep the work centered on proof: AAO should demonstrate, with deterministic
scenarios, that it catches drift, missing evidence, risky actions, bad plans,
unbounded recovery, and dishonest success.

After implementation, explain naturally what each scenario proves, which AAO
claim it supports, what tests ran, and what remains intentionally out of scope.
