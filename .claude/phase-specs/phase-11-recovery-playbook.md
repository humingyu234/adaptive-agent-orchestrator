# Phase 11 - Recovery Playbook

## Goal

Turn failure classification into bounded runtime recovery decisions.

After this phase, AAO should not only know:

```text
this failed because evidence is missing
this failed because a provider was rate limited
this failed because policy blocked the step
```

It should also know the next safe action:

```text
retry once
retry with jittered backoff
request evidence
replan
pause for human review
fail fast
```

This phase is about controlled recovery, not about making the system endlessly
"try harder".

## Why This Phase Exists

Phase 7B strengthened failure taxonomy. Phase 10 made policy able to affect
runtime decisions. Phase 11 connects those facts to bounded next actions.

Mental model:

```text
FailureRecord says: what went wrong?
RecoveryPlaybook says: what is the safest next move?
Scheduler says: execute that move, but never invent recovery logic itself.
```

The recovery layer is the traffic controller. It does not fly the plane. It
looks at the failure, the attempt count, the run mode, and the available runtime
capability, then gives one clear instruction.

## Preflight

Before editing, read:

```text
CLAUDE.md
.claude/phase-specs/phase-09a-runtime-mode-cleanup-contract.md
.claude/phase-specs/phase-10-runtime-policy-enforcement.md
.claude/phase-specs/phase-11-recovery-playbook.md
.claude/project-skills/aao-boundary-test-designer.md
.claude/project-skills/aao-code-reviewer.md
.claude/project-skills/aao-phase-handoff.md
```

Then inspect the current source:

```text
src/orchestrator/control_models.py
src/orchestrator/control_plane.py
src/orchestrator/failure_taxonomy.py
src/orchestrator/policy.py
src/orchestrator/scheduler.py
src/orchestrator/live_view.py
src/orchestrator/report_writer.py
tests/test_failure_taxonomy.py
tests/test_control_plane.py
tests/test_control_plane_integration.py
tests/test_runtime_smoke.py
```

Run `git status --short` first. Name unrelated dirty files in the handoff. Do
not use `git add .`.

## Non-Goals

- No autonomous infinite retry loop.
- No Planning Council.
- No Claude Code Worker Bridge.
- No LangGraph runner.
- No ECC integration.
- No memory layer.
- No provider/model fallback implementation.
- No context compression implementation unless it already exists.
- No broad scheduler rewrite.
- No new LLM call in the default recovery path.
- No pretending a recovery hint is implemented if runtime support is missing.

Important distinction:

```text
recovery_hint = recommended type of recovery
RecoveryDecision = what this runtime can safely do now
```

If a hint says `fallback_model_or_provider` but AAO has no provider fallback
wired yet, the decision must say so explicitly and choose a safe current action
such as `needs_human_review` or `fail`.

## Allowed Files

Prefer this write set:

```text
src/orchestrator/recovery.py
src/orchestrator/control_models.py
src/orchestrator/control_plane.py
src/orchestrator/failure_taxonomy.py
src/orchestrator/scheduler.py
src/orchestrator/live_view.py
src/orchestrator/report_writer.py
tests/test_recovery.py
tests/test_control_plane.py
tests/test_control_plane_integration.py
tests/test_runtime_smoke.py
tests/test_live_view.py
```

Only touch other files if source inspection proves it is necessary. Explain the
reason in the handoff.

## Core Contract

Implement a deterministic recovery layer with a small public API.

Suggested model names:

```text
RecoveryDecision
RecoveryPlaybook
RecoveryAttemptKey
RecoveryAction
```

Suggested `RecoveryDecision` fields:

```text
failure_category
failure_reason
failure_origin
recovery_hint
action
reason
attempt_count
max_attempts
next_step_hint
delay_seconds
terminal
requires_human_review
runtime_supported
```

The exact field names may differ, but the model must answer these questions:

```text
What failed?
What action should happen now?
How many times have we already tried?
What is the maximum allowed?
Is this action terminal?
Does the runtime actually support this action?
What should the user or runner do next?
```

## Layer Boundary

Keep the responsibilities separate:

```text
failure_taxonomy.py
  creates FailureRecord:
    origin, category, reason, severity, recovery_hint

recovery.py
  turns FailureRecord + attempts + run mode + runtime capabilities
  into RecoveryDecision

control_plane.py
  exposes one runner-agnostic entry point for recovery decisions

scheduler.py
  calls ControlPlane / RecoveryPlaybook and executes the returned action
```

Do not put a large recovery matrix directly inside `scheduler.py`.

Scheduler may:

```text
collect current attempt count
call ControlPlane.decide_recovery(...)
record the recovery decision
retry / pause / fail / request evidence according to the decision
```

Scheduler must not:

```text
own the failure-to-action matrix
silently retry forever
convert unsupported recovery hints into fake success
call an LLM to decide recovery by default
hide recovery decisions from reports/live view
```

## Recovery Matrix

Start with this bounded matrix.

```text
Provider transient:
  rate_limit / timeout / overloaded / server_error
  -> retry_with_backoff
  -> max 2 attempts
  -> if exhausted: needs_human_review

Provider hard:
  auth_permanent / billing / format_error
  -> fail fast
  -> no retry

Provider route:
  model_not_found / auth
  -> fallback_model_or_provider if runtime supports it
  -> otherwise needs_human_review or fail with runtime_supported=false

Context overflow:
  -> compress_context if runtime supports it
  -> otherwise request_evidence or needs_human_review

Task quality:
  evaluation_failed / low_quality_output / missing_required_field
  -> retry once
  -> if exhausted: replan if runtime supports replan, otherwise needs_human_review

Missing evidence:
  -> request_evidence
  -> no blind retry

Guardrail blocked:
  input_guardrail_blocked / output_guardrail_blocked / sensitive_content
  -> fail fast
  -> no retry

Protected action:
  -> needs_human_review

Tool failed:
  -> retry once
  -> if exhausted: needs_human_review

Tool loop:
  exact_repeated_tool_failure / same_tool_repeated_failure / idempotent_no_progress
  -> replan if runtime supports it
  -> otherwise fail or needs_human_review
  -> no blind retry

Policy:
  protected_file_change / high_risk_tool
  -> needs_human_review

Policy hard:
  reviewer_write_attempt
  -> fail fast

Missing required check:
  -> request_evidence or needs_human_review
  -> no completed status

Unknown:
  -> fail or needs_human_review
  -> no blind retry
```

If existing enums use different exact names, map from the existing names rather
than creating duplicates.

## Run Mode Semantics

Respect Phase 9A:

```text
off
  recovery layer may be bypassed; preserve existing behavior

log
  compute and record RecoveryDecision, but do not enforce retry/pause/fail

controlled
  enforce RecoveryDecision

orchestrated
  may use the same controlled behavior until future runner support exists;
  do not fake unsupported replan/fallback behavior
```

Tests must prove at least `log` and `controlled` differ.

## Attempt Accounting

Retry limits must be explicit and deterministic.

Define a stable attempt key. Suggested fields:

```text
task_id
agent_name
failure_category
failure_reason
step_name
```

Do not count every unrelated failure as the same retry chain. Also do not let
minor wording changes create a brand-new retry chain for the same failure.

Minimum behavior:

```text
same agent + same category/reason -> increments attempt count
different agent or different reason -> separate attempt chain
attempt count is visible in RecoveryDecision
attempt exhaustion changes the action
```

## Jittered Backoff

Use the existing or Phase 7B-inspired jittered backoff helper if present. If it
does not exist yet, implement a small deterministic wrapper that can be tested
without sleeping.

Do not make tests wait in real time.

Minimum behavior:

```text
rate_limit attempt 1 -> retry_with_backoff with delay_seconds > 0
rate_limit after max attempts -> needs_human_review, not another retry
```

## Runtime Capability Awareness

Recovery must know what the runtime can currently do.

For this phase, define a small capability set such as:

```text
retry
retry_with_backoff
request_evidence
replan
compress_context
fallback_model_or_provider
human_review
fail
```

If the playbook recommends an unsupported action, the decision must include:

```text
runtime_supported=false
reason explaining the unsupported hint
safe fallback action
```

Example:

```text
FailureRecord.recovery_hint = fallback_model_or_provider
runtime has no provider fallback
RecoveryDecision.action = needs_human_review
runtime_supported = false
```

## ControlPlane Integration

Add one runner-agnostic entry point.

Suggested method:

```python
ControlPlane.decide_recovery(
    failure_record: FailureRecord,
    *,
    attempt_count: int = 0,
    run_mode: str = "controlled",
    runtime_capabilities: set[str] | None = None,
    context: dict | None = None,
) -> RecoveryDecision
```

The signature may differ, but the boundary must remain:

```text
runner gives ControlPlane the facts
ControlPlane returns the recovery decision
runner executes the decision
```

## Scheduler Integration

Keep the scheduler slice minimal.

Required runtime behavior:

```text
1. When a FailureRecord is produced, ask ControlPlane for RecoveryDecision.
2. Record the decision in execution trace / run metadata.
3. If action is retry or retry_with_backoff, retry only within the explicit limit.
4. If action is request_evidence, mark the run as not completed and explain what evidence is missing.
5. If action is needs_human_review, pause or mark needs_human_review consistently with existing human review flow.
6. If action is fail, fail with the structured recovery reason.
```

Do not refactor the whole scheduler in this phase. If scheduler size grows, the
handoff must state what was added and what future extraction is recommended.

## Trace / Live / Report Visibility

Recovery decisions must be visible enough to debug.

Minimum output:

```text
execution_trace includes a recovery decision event or equivalent structured data
live view shows last recovery action if available
report includes recovery action, attempt_count, and next_step_hint when a run fails or pauses
```

Do not build a new dashboard.

## Boundary Test Matrix

Contract:

```text
FailureRecord + attempts + run mode + runtime capability produce a bounded,
visible, deterministic RecoveryDecision.
```

Required unit tests:

```text
test_rate_limit_retries_with_backoff_then_human_review
test_billing_fails_fast_without_retry
test_missing_evidence_requests_evidence_without_blind_retry
test_guardrail_blocked_fails_fast
test_tool_loop_replans_or_fails_without_retry_loop
test_evaluation_failed_retries_once_then_review_or_replan
test_unknown_failure_does_not_retry_blindly
test_unsupported_provider_fallback_is_marked_runtime_unsupported
test_log_mode_records_recovery_without_enforcing
test_controlled_mode_enforces_recovery
test_attempt_key_separates_different_agents_or_reasons
```

Required integration tests:

```text
test_scheduler_records_recovery_decision
test_scheduler_does_not_complete_when_recovery_requests_evidence
test_scheduler_does_not_retry_past_limit
test_report_includes_recovery_summary
test_live_view_includes_last_recovery_decision
```

False-positive guards:

```text
normal successful run should not create a recovery decision
different failure reasons should not exhaust each other's retry budgets
log mode should not block a run only because recovery would block in controlled mode
```

## Validation Commands

Run targeted tests first:

```bash
PYTHONPATH=src python -m pytest -q tests/test_recovery.py tests/test_failure_taxonomy.py tests/test_control_plane.py
PYTHONPATH=src python -m pytest -q tests/test_control_plane_integration.py tests/test_runtime_smoke.py tests/test_live_view.py
```

Then run:

```bash
PYTHONPATH=src python -m pytest -q
python -m compileall -q src tests
git diff --check
git status --short
```

On Windows, use equivalent `py -m ...` commands if that is the working
interpreter.

## Definition Of Done

Phase 11 is done only when:

```text
- recovery.py exists and owns the recovery matrix
- ControlPlane exposes a recovery decision entry point
- scheduler calls the recovery entry point rather than owning the matrix
- retry limits are explicit and tested
- retry_with_backoff does not sleep in tests
- unsupported runtime hints are marked clearly and safely downgraded
- log vs controlled behavior is tested
- request_evidence cannot silently become completed
- guardrail and policy hard stops are not blindly retried
- tool-loop failures do not create retry loops
- recovery decisions are visible in trace/live/report where practical
- targeted tests pass
- full pytest passes or unrelated failures are documented
- compileall passes
- git diff --check passes
- final handoff includes dirty files outside phase scope and recommended commit slice
```

## Required Handoff

Use `.claude/project-skills/aao-phase-handoff.md`.

Include:

```text
current phase
phase goal
completed work
changed files
dirty files outside current phase scope
tests added or changed
exact test commands run
test result
reviewer result if used
known risks
unsupported recovery hints
deferred ideas
next recommended step
safe to proceed
recommended next commit slice
```

## Required Final Explanation To User

Explain Phase 11 naturally and concretely.

Use this mental model:

```text
Before Phase 11, AAO could say "this step failed."
After Phase 11, AAO can say "this failed because evidence is missing, so do not
pretend it is complete; ask for evidence. This failed because rate limit hit, so
retry with backoff only twice. This failed because a guardrail blocked it, so do
not retry; stop."
```

Make clear:

```text
what failures now recover
what failures fail fast
what retry limits exist
what happens when recovery is unsupported
where recovery decisions are recorded
what remains for Phase 12 worker bridge
```

Do not oversell Phase 11 as full autonomous self-healing.

## Claude Code Instruction

Read `CLAUDE.md` and this file. Implement only Phase 11. Keep recovery bounded,
deterministic, visible, and testable. Do not add Planning Council, LangGraph,
ECC, memory, or Claude Code Worker Bridge in this phase.
