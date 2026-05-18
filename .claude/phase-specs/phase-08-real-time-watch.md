# Phase 8 - Real-Time Watch

## Goal

Turn `watch` from a one-shot status command into a real runtime control view.
AAO Live Watch should show whether the task is progressing correctly, not only
whether a Claude Code session is alive.

Current slice:

```text
Only make runtime progress/control state visible while a run is happening.
Do not add new execution behavior.
Do not add a dashboard.
Do not start routing, policy enforcement, recovery execution, worker bridge, or
LangGraph work.
```

## Why This Phase Exists

The user needs to see a run as it happens: current step, control decisions,
evidence status, failures, recovery actions, and human-review waits. This is a
core part of making AAO usable and demoable.

## Non-Goals

- No web dashboard.
- No Claude Code Agent View clone.
- No fake progress.
- No new runner.
- No new heavy dependency.

## Allowed Files

```text
src/orchestrator/live_view.py
src/orchestrator/__main__.py
src/orchestrator/state.py
tests/test_live_view.py
tests/test_cli_output.py
```

Any scheduler change must be justified as exposing real state needed by the
view, not as a runtime rewrite.

If a scheduler change is truly needed, keep it to one of these:

```text
- persist current step / total steps
- persist current worker / current agent
- persist last control decision
- persist last failure record
- persist last recovery hint
- persist human-review waiting state
- persist evidence/report path
```

Do not change scheduling decisions, retry behavior, failure classification, or
agent execution order in this phase.

## Runtime State Contract

The watch view must read recorded runtime state. It must not invent progress by
counting time, guessing from logs, or assuming a step succeeded.

At minimum, the state shape should support these concepts, even if some are
optional for older runs:

```text
task_id
run_mode
status
current_step
total_steps
current_worker
last_control_decision
last_evaluator_decision
last_guardrail_decision
last_policy_decision
last_failure_category
last_failure_reason
last_failure_origin
last_recovery_hint
evidence_status
human_review_state
report_path
evidence_path
started_at
updated_at
```

Backward compatibility requirement:

```text
Existing state files without these new fields must still render.
Missing optional fields should show "unknown", "none", or be omitted cleanly.
They must not crash `status` or `watch`.
```

## CLI Behavior Contract

`status`:

```text
- render once
- never loop
- never sleep
- suitable for scripts
```

`watch`:

```text
- refresh until the run reaches a terminal state
- support `--once`
- support a small interval option, for example `--interval 1.0`
- stop on terminal states: completed, failed, cancelled, timed_out,
  guardrail_blocked, human_rejected, or any existing project terminal state
- handle missing or deleted state files gracefully
```

The refresh loop must be testable. Prefer a small pure function or injectable
sleep/loader helper over burying everything in CLI code.

## Rendering Contract

The rendered output should be useful to a human watching a run, not a raw dump.

Show the most important state first:

```text
Task: <task_id>
Mode: <run_mode>
Status: <status>
Progress: <current_step>/<total_steps>
Worker: <current_worker>
Control: <last_control_decision>
Failure: <origin/category/reason>
Recovery: <last_recovery_hint>
Evidence: <evidence_status>
Human Review: <human_review_state>
Report: <report_path>
Elapsed: <elapsed time>
```

Do not over-format. A plain terminal view is enough.

Important distinction:

```text
Claude Code Agent View shows what an agent is doing.
AAO Live Watch shows what the control layer believes about the run:
progress, evidence, failures, recovery, and review state.
```

## Required Behavior

- `status` remains one-shot.
- `watch` refreshes until terminal state unless `--once` is provided.
- `watch` supports a small interval option.
- The rendered view shows:
  - task id
  - run mode
  - status
  - current step / total steps
  - current worker when known
  - last control/evaluator/guardrail/policy decision when known
  - last failure classification when known
  - recovery action when known
  - evidence status
  - human-review state
  - report/evidence paths
  - elapsed time when known
- Partial state must render safely.

## Suggested Implementation Order

1. Read existing `live_view.py`, CLI command parsing, and state persistence.
2. Identify the current source of truth for run state.
3. Add the smallest state fields needed for watch rendering.
4. Update the live view renderer as pure functions first.
5. Update CLI wiring so `status` and `watch` are distinct.
6. Add tests for renderer behavior before broad CLI tests.
7. Run targeted tests, then full tests.

Before editing, state:

```text
Expected files to touch:
- <file>: <why>

Runtime source of truth:
- <state file/model/function>

Test plan:
- <targeted tests>
- <full test command>
```

## Boundary Test Matrix

Contract:

```text
AAO watch displays real persisted runtime/control state repeatedly until the
run is terminal, while status remains a one-shot command.
```

Tests:

```text
Bad case:
  status accidentally loops or sleeps
  Expected: status renders once and exits

Normal case:
  watch sees state change from running to completed
  Expected: watch refreshes and exits after terminal state

Boundary case:
  state is missing optional control/failure/evidence fields
  Expected: render succeeds without traceback

False-positive guard:
  watch must not show fake progress when current_step/total_steps are missing
  Expected: progress shows unknown/omitted, not guessed

Regression path:
  existing one-shot live view/status tests still pass
  Expected: old behavior stays compatible
```

## Required Tests

```text
test_status_is_one_shot
test_watch_refreshes_from_updated_state
test_watch_shows_current_step_and_total_steps
test_watch_shows_failure_classification
test_watch_shows_human_review_waiting_state
test_watch_handles_missing_optional_fields
test_watch_does_not_fake_progress_when_step_fields_are_missing
```

## Commands

```bash
python -m pytest tests/test_live_view.py tests/test_cli_output.py
python -m compileall -q src tests
git diff --check
python -m pytest
```

## Definition Of Done

- `status` and `watch` behavior are distinct.
- Watch view is based on recorded runtime state.
- Missing optional fields do not crash rendering.
- Watch does not fake progress.
- Any scheduler change is limited to exposing state for the view.
- Targeted tests pass.
- `python -m compileall -q src tests` passes.
- `git diff --check` passes.
- Full tests pass or failures are explained.
- Final explanation teaches the user what AAO Live Watch shows that Claude Code
  Agent View does not.

## Review Checklist

The reviewer should check:

```text
- Is status still one-shot?
- Does watch really loop until terminal state?
- Is the view using persisted state, not guessed progress?
- Are missing optional fields safe?
- Did the phase avoid new runner/policy/recovery behavior?
- If scheduler changed, is it only exposing state?
- Do tests cover one-shot, refresh, missing fields, failure, recovery, and
  human review?
```

## Claude Code Instruction

Read `CLAUDE.md` and this file. Implement only Phase 8. Before editing, state
the exact files you expect to touch and how you will test the change. Do not
start Phase 9.
