# Phase 7B - Hermes-Informed ControlPlane Hardening

Goal: Strengthen the AAO control layer using lessons from mature agent execution
systems, especially `NousResearch/hermes-agent`, without integrating Hermes as
a dependency or changing AAO's product direction.

## Why This Phase Exists

Phase 0-7A can make the ControlPlane structurally connected while still leaving
important product-grade control cases underspecified:

```text
it can say "failed"
but not always "what kind of failure"
it can say "retry"
but not always "which failures should never retry"
it can detect content guardrails
but not tool-loop/no-progress behavior
```

Phase 7B is the bridge between "ControlPlane is wired" and "ControlPlane is
robust enough to guide recovery decisions."

## Reference Sources

```text
Hermes Agent error classification:
  NousResearch/hermes-agent/agent/error_classifier.py

Hermes Agent tool loop guardrails:
  NousResearch/hermes-agent/agent/tool_guardrails.py

Hermes Agent jittered retry:
  NousResearch/hermes-agent/agent/retry_utils.py

Hermes Agent worker isolation pattern:
  NousResearch/hermes-agent/tools/delegate_tool.py
```

Use these as design references, not as copy-paste integration targets.

## Borrowing Policy

Hermes Agent is MIT-licensed, so small pieces may be reused when doing so is
cleaner than reinventing them. Still keep AAO's architecture in control.

```text
May reuse directly with attribution and tests:
  small pure utilities
  provider error pattern lists
  tiny deterministic helpers such as jittered backoff

May adapt, but must rewrite around AAO contracts:
  tool-loop detection algorithms
  failure classification pipeline
  retry/failover decisions

Do not copy or integrate wholesale:
  Hermes conversation loop, gateway, TUI, memory system,
  provider failover runtime, worker/delegation runtime
```

If code or data is copied or closely adapted from Hermes, add a short source
comment near each borrowed piece:

```python
# Adapted from Hermes Agent (MIT): agent/error_classifier.py _BILLING_PATTERNS
```

## Non-Goals

- no Hermes dependency, gateway, TUI, conversation loop, or full memory system
- no LangGraph, Claude Code Worker Bridge, Planning Council, web dashboard
- no new heavy dependency, no broad scheduler rewrite
- no extra LLM call in the default control path
- no automatic infinite retry loop

## Allowed Files

```text
src/orchestrator/control_models.py
src/orchestrator/control_plane.py
src/orchestrator/failure_taxonomy.py
src/orchestrator/guardrails.py
src/orchestrator/scheduler.py
tests/test_control_models.py
tests/test_control_plane.py
tests/test_failure_taxonomy.py
tests/test_guardrails.py
tests/test_control_plane_integration.py
CLAUDE.md
```

## Required Work

### 1. Failure classification must distinguish origin, category, reason, and recovery

Do not turn `FailureCategory` into a flat dumping ground. Keep the model readable:

```text
origin/source    — where the failure was observed or reported
category         — broad failure family
reason           — concrete machine-readable cause
recovery hint    — bounded next action
```

Important boundary: ControlPlane does not directly call LLM providers.
Provider/API failures are reported by a worker or provider layer:
`Worker/Provider -> FailureRecord -> ControlPlane classify/decide`

Suggested origins: `control_plane`, `worker`, `provider`, `tool`, `policy`, `scheduler`, `unknown`

Recommended categories and reasons:

```text
PROVIDER_ERROR
  auth, auth_permanent, billing, rate_limit, timeout, overloaded,
  server_error, context_overflow, model_not_found, format_error

TASK_QUALITY_ERROR
  evaluation_failed, low_quality_output, missing_required_field, missing_evidence

GUARDRAIL_BLOCKED
  input_guardrail_blocked, output_guardrail_blocked, sensitive_content, protected_action

TOOL_ERROR
  tool_failed, exact_repeated_tool_failure, same_tool_repeated_failure,
  idempotent_no_progress

POLICY_ERROR
  protected_file_change, high_risk_tool, reviewer_write_attempt, missing_required_check

UNKNOWN
  unknown
```

### 2. Recovery hints must be explicit and bounded

Suggested actions: `continue`, `retry`, `retry_with_backoff`, `request_evidence`,
`compress_context`, `fallback_model_or_provider`, `replan`, `needs_human_review`, `fail`

Initial mapping:

```text
rate_limit            -> retry_with_backoff
timeout               -> retry_with_backoff
overloaded            -> retry_with_backoff
server_error          -> retry_with_backoff, bounded
context_overflow      -> compress_context
model_not_found       -> fallback_model_or_provider or fail
auth                  -> fallback_model_or_provider or needs_human_review
auth_permanent        -> fail or needs_human_review
billing               -> fail or fallback_model_or_provider, not blind retry
format_error          -> fail or needs_human_review, not blind retry
missing_evidence      -> request_evidence
evaluation_failed     -> retry or replan, bounded
guardrail_blocked     -> fail or needs_human_review, not retry
protected_file_change -> needs_human_review
exact_repeated_tool_failure -> replan or fail
same_tool_repeated_failure  -> replan or fail
idempotent_no_progress      -> replan or fail
unknown               -> safe fallback with clear uncertainty
```

A recovery hint is not the same as implemented runtime capability. If the runtime
doesn't yet have provider fallback, return the hint but don't pretend it happened.

### 3. Jittered backoff must be used only for transient failures

Use only for: `rate_limit`, `timeout`, `overloaded`, `server_error`

Never use blind retry/backoff for: `guardrail_blocked`, `protected_file_change`,
`missing_evidence`, `evaluation_failed` without a retry limit, `billing`,
`auth_permanent`, `format_error` without a changed request.

### 4. Add a pure tool-loop guardrail controller

Inspired by Hermes `tool_guardrails.py`. Should detect:

```text
exact repeated failure
  same tool name + same normalized arguments fails repeatedly

same tool repeated failure
  same tool fails repeatedly even with different arguments

idempotent no-progress
  read-only/idempotent tool returns the same result repeatedly
```

Must be pure and testable — no live runner, shell, model call, or Hermes dependency.

Suggested output shape: `action (allow|warn|block|halt)`, `code`, `reason`,
`tool_name`, `count`, `normalized_signature`, `recovery_hint`

Safety rules:
- normalize tool arguments with stable ordering
- do not store raw sensitive arguments in public metadata
- compare stable result hashes for no-progress, not long raw outputs
- different arguments or results should not be falsely blocked
- warnings and hard stops must have separate thresholds

### 5. Do not fake runtime integration

If the scheduler doesn't yet record enough tool-call events for real runs, keep
the controller as a pure ControlPlane capability with tests. Runtime wiring
requires a real event path:

```text
tool call planned -> ControlPlane pre-tool check -> tool executed/blocked
-> tool result recorded -> ControlPlane post-tool update -> trace/evidence updated
```

### 6. Worker isolation lessons (documentation only)

From Hermes `delegate_tool.py`, record for later Phase 12:

```text
independent context, restricted tools, independent task id, focused task prompt
parent sees result/evidence summary, not full child reasoning
heartbeat/stall detection
dangerous action approval does not block the main control loop
```

Do not implement the Claude Code Worker Bridge in Phase 7B.

### 7. Hermes memory/reflection ideas deferred to Phase 14

## Required Tests

```text
test_rate_limit_maps_to_retry_with_backoff
test_timeout_maps_to_retry_with_backoff
test_context_overflow_maps_to_compress_context
test_billing_does_not_blind_retry
test_guardrail_blocked_does_not_retry
test_missing_evidence_requests_evidence
test_unknown_failure_uses_safe_fallback

test_exact_repeated_tool_failure_reaches_block_threshold
test_same_tool_repeated_failure_reaches_warning_or_block_threshold
test_idempotent_no_progress_is_detected
test_tool_loop_allows_different_arguments
test_tool_loop_allows_different_results
test_tool_loop_metadata_does_not_expose_raw_sensitive_arguments

test_control_plane_returns_recovery_hint_for_provider_failure
test_control_plane_returns_recovery_hint_for_tool_loop_failure
```

## Commands

```bash
python -m pytest tests/test_failure_taxonomy.py tests/test_control_plane.py tests/test_guardrails.py -q
python -m pytest tests/test_control_plane_integration.py -q
python -m pytest -q
git diff --check
python -m compileall -q src tests
git status --short
```

## Definition of Done

Phase 7B is done only when:
- provider/API failure reasons exist and are tested
- known failure reasons map to bounded recovery hints
- transient retry uses jitter/backoff only where appropriate
- non-retryable failures do not silently retry
- tool-loop guardrail controller exists and is pure/tested
- recovery hints whose runtime support is not yet implemented are listed in the phase handoff
- no Hermes dependency was added
- no Phase 8+ feature was started
- targeted tests pass; full tests pass or failures are precisely explained
- final explanation says what was borrowed from Hermes and what was not
