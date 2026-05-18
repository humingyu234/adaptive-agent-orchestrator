# Phase 11 - Recovery Playbook

## Goal

Map failure classifications to concrete next actions.

## Why This Phase Exists

AAO should not only say a run failed. It should decide whether to retry, request
evidence, replan, ask for human review, or fail fast.

## Non-Goals

- No autonomous infinite retry loops.
- No new LLM evaluator in the default path.
- No complex planner yet.

## Allowed Files

```text
src/orchestrator/recovery.py
src/orchestrator/failure_taxonomy.py
src/orchestrator/control_plane.py
src/orchestrator/scheduler.py
tests/test_recovery.py
tests/test_control_plane_integration.py
```

## Required Behavior

Start with this playbook:

```text
TEST_FAILED -> retry once, then needs_human_review
MISSING_EVIDENCE -> request_evidence
GUARDRAIL_BLOCKED -> fail
POLICY_DENIED -> needs_human_review or fail
TOOL_REPEATED -> replan or fail
LOW_QUALITY_OUTPUT -> retry or replan
```

Every recovery decision must include:

```text
failure_category
action
reason
attempt_count
next_step_hint
```

Record recovery decisions in trace/audit metadata.

## Required Tests

```text
test_test_failure_retries_once_then_human_review
test_missing_evidence_requests_evidence
test_guardrail_blocked_fails_fast
test_policy_denied_requires_review_or_fails
test_recovery_decision_is_recorded
test_recovery_does_not_loop_forever
```

## Commands

```bash
python -m pytest tests/test_recovery.py tests/test_control_plane_integration.py
python -m pytest
```

## Definition Of Done

- Failure categories have deterministic recovery decisions.
- Retry limits are explicit.
- Recovery decisions are visible in audit/live state.
- Targeted and full tests pass or failures are explained.

## Claude Code Instruction

Read `CLAUDE.md` and this file. Implement only Phase 11. Keep recovery bounded
and deterministic. Do not add Planning Council.
