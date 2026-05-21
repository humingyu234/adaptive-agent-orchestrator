# Phase 7A - Core Closure Gate

Goal: Close the remaining quality gaps in Phase 0-7 before adding new
control-layer capabilities. This phase is a hardening and closure phase, not a
feature expansion phase.

## Why This Phase Exists

Phase 0-7 can pass tests while still leaving hidden interface drift:

```text
ControlPlane exists, but some runtime checks may still bypass it.
Live view exists, but progress may not yet represent the whole run clearly.
Evidence exists, but summaries must stay honest and bounded.
Policy exists, but it must not be described as runtime enforcement unless it is.
```

## Non-Goals

- no LangGraph
- no ClaudeCodeWorker
- no new top-level package
- no package migration
- no new heavy dependency
- no new planning council
- no Phase 7.5 control-layer expansion
- no broad rewrite of `scheduler.py`
- no unrelated sales-agent, docs, or job-search work

## Allowed Files

```text
src/orchestrator/control_models.py
src/orchestrator/control_plane.py
src/orchestrator/scheduler.py
src/orchestrator/live_view.py
src/orchestrator/evidence.py
src/orchestrator/report_writer.py
tests/test_control_models.py
tests/test_control_plane.py
tests/test_control_plane_integration.py
tests/test_live_view.py
tests/test_evidence_pack.py
tests/test_policy.py
.gitignore
CLAUDE.md
```

Any other file change must be explicitly justified before editing.

## Required Fixes

### 1. `ControlPlane.make_decision()` must guard the actual output

Current contract:

```text
input guard checks payload/input context
evaluator checks output
output guard checks output
```

It is not acceptable for output guardrails to check the input payload when the
caller provided a separate `output` object.

Required tests:

```text
test_make_decision_blocks_sensitive_output_even_when_input_payload_is_clean
test_make_decision_allows_clean_input_and_clean_output
```

### 2. Scheduler guardrail execution must go through ControlPlane

Target runtime path:

```text
Scheduler
  -> ControlPlane.guard_input(agent_name, payload=view, guardrail_names=agent.config.guardrails)
  -> agent.run(view)
  -> ControlPlane.guard_output(agent_name, payload=output, guardrail_names=agent.config.guardrails)
  -> ControlPlane.evaluate_output(...)
  -> ControlPlane.classify_failure(...)
```

The scheduler should not directly call `agent.apply_input_guardrails(...)` or
`agent.apply_output_guardrails(...)` unless those calls are retained only as
deprecated compatibility wrappers and are not used by the scheduler runtime path.

Required behavior to preserve:

- empty query still fails before agent execution
- sensitive output still fails after agent execution
- `guardrail_violation` trace event still contains: event, agent_name, stage, reason, failure_category, timestamp
- failure classification still emits `failure_classified`
- successful workflows still complete
- human review pause/resume still works

Required tests:

```text
test_scheduler_uses_control_plane_for_input_guardrail
test_scheduler_uses_control_plane_for_output_guardrail
test_scheduler_preserves_guardrail_violation_trace_shape
test_scheduler_preserves_human_review_pause_after_control_plane_guardrails
```

### 3. Control action naming must be consistent

Use `needs_human_review` everywhere. Do not introduce `human_review` unless
there is an explicit compatibility mapping and tests for it.

### 4. Live view progress must be honest and useful

`build_live_view(...)` must expose progress from real runtime signals:

```text
completed steps: execution log or successful evaluation/write events
current step: latest running/completed/failed agent signal available
total steps: workflow length when provided, otherwise a clear fallback
status: state metadata
last decision: latest evaluation/control decision
last failure: latest failure_classified event
human review: human_review_gate or needs_human_review status
artifacts: report/evidence paths when available
```

Backward compatibility: `build_live_view(state, result=None)` must still work.

Required tests:

```text
test_live_view_progress_uses_workflow_total_when_available
test_live_view_progress_has_honest_fallback_without_workflow
test_live_view_reports_current_step_for_failed_run
test_live_view_reports_current_step_for_human_review_run
```

### 5. EvidencePack must stay honest but become more readable

Evidence may include a short `output_summary` only if derived from data the
runtime actually recorded. Do not invent `files_changed`, `commands_run`,
`test_results`, or `diff_summary` unless the runtime really captures them.

Required tests:

```text
test_evidence_pack_derives_bounded_output_summary_from_recorded_output
test_evidence_pack_does_not_invent_files_commands_tests_or_diff
test_evidence_summary_in_report_is_readable_and_bounded
```

### 6. Policy scope must be explicit

Policy is a declarative helper in Phase 0-7. Runtime enforcement belongs to a
later phase unless the user explicitly asks to implement it now.

Required tests:

```text
test_policy_default_behavior_is_documented_by_tests
test_policy_protected_file_requires_review_when_configured
test_policy_high_risk_tool_requires_review_when_configured
```

### 7. Repository hygiene must pass

- add or update `.gitignore`
- ensure `.venv/`, `.claude/`, `.pytest_cache/`, `__pycache__/`, `tmp/`, `outputs/` are not intended commit content
- remove trailing whitespace from changed files
- avoid UTF-8 BOM
- normalize line endings

Required commands:

```bash
git diff --check
python3 -m compileall -q src tests
python3 -m pytest tests/test_control_models.py tests/test_control_plane.py tests/test_control_plane_integration.py tests/test_live_view.py tests/test_evidence_pack.py tests/test_policy.py -q
python3 -m pytest -q
git status --short
```

## Definition of Done

Phase 7A is done only when:
- all required tests exist and pass
- full pytest passes, compileall passes, git diff --check passes
- scheduler guardrails no longer bypass ControlPlane
- make_decision guards output, not input payload
- live view progress is honest and backward-compatible
- evidence is more readable without false claims
- policy scope is explicit
- the final report lists changed files and remaining risks
