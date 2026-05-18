# Adaptive Agent Orchestrator - Claude Code Working Guide

This file is the project-level operating guide for Claude Code when working on
Adaptive Agent Orchestrator (AAO).

Read this before making changes. Follow it unless the user explicitly overrides
the plan.

---

## 0. Final Product Direction

AAO is an Agent Runtime Control Plane.

It is not:

- a Claude Code replacement
- a LangGraph replacement
- a generic all-in-one agent framework
- a tracing platform
- an eval SaaS
- a heavyweight workflow platform for every tiny task

It is:

- a control layer for agent workflows
- a runtime judge for whether a step should continue, retry, replan, pause for
  human review, roll back, or fail
- a system for evidence, live progress, failure classification, and audit
  reports

Why this position:

Better models and workers improve agent capability. AAO improves agent
reliability by judging whether a step is correct, risky, incomplete, or
recoverable independent of which model or worker produced it. These are
different problems; keep the control layer independent from the worker layer.

Final intended shape:

```text
Human
  -> Claude Code frontend
  -> AAO command protocol
  -> AAO Control Plane
      -> Task sizing
      -> Plan contract
      -> Policy engine
      -> Evaluator gate
      -> Guardrails
      -> Failure taxonomy
      -> Human review gate
      -> Evidence pack
      -> Live run view
      -> Audit report
      -> Regression compare
  -> Runner layer
      -> NativeRunner
      -> LangGraphRunner
      -> ClaudeCodeWorker
      -> TestWorker
      -> ReviewWorker
```

The user should still communicate with Claude Code naturally. AAO should work in
the background as the control, visibility, and audit layer.

Layer terminology:

```text
Claude Code frontend
  The user's primary conversation and coding interface.

AAO Control Plane
  The runtime control layer: task sizing, plan contracts, policy, evaluator
  gates, guardrails, failure taxonomy, recovery decisions, evidence, live view,
  human review, audit reports, and regression comparison.

Runner / Execution Engine
  The system that executes workflow structure. NativeRunner and LangGraphRunner
  are runners. They are not workers.

Worker
  The actor that performs work inside a step: Claude Code, an LLM provider, a
  search/tool worker, TestWorker, ReviewWorker, or HumanReviewer.

ECC / Everything Claude Code
  A Claude Code worker-discipline pack: commands, hooks, agents, rules, and
  skills that make Claude Code behave more predictably. It can strengthen the
  Claude Code worker, but it is not the AAO control layer.

Claude Code Agent View
  A multi-session view for Claude Code workers. It shows which sessions are
  running, waiting, or complete. It is not a quality/evidence/control monitor.

AAO Live Watch
  A control-layer view. It shows task progress, current step, last decision,
  evidence, failure classification, recovery action, and human-review state.
```

Keep these terms strict. Do not call NativeRunner or LangGraphRunner workers.
Do not turn AAO Live Watch into a clone of Claude Code Agent View.

---

## 1. Hard Constraints

Do not do these unless the user explicitly asks:

- Do not create a new top-level `aao/` package yet.
- Do not move `agents`, `llm`, `cli`, `models`, `workflow`, `state`, or
  `scheduler` into a new package in one large step.
- Do not rewrite `scheduler.py` from scratch.
- Do not remove or reset existing user changes.
- Do not edit `.env`, secrets, generated outputs, `.venv`, or `tmp/` unless the
  task explicitly requires it.
- Do not add LangGraph, Langfuse, DeepEval, LiteLLM, OPA, or Casbin in the core
  phases.
- Do not add extra LLM calls to the default control path.
- Do not make simple tasks slower by forcing them through heavyweight workflow
  machinery.
- Do not claim evidence exists unless the code actually records it.

Default principle:

```text
AAO core must be lightweight by default and extensible by adapter.
```

Over-design filter:

Before adding any new subsystem, ask whether it clearly helps at least one of
these product goals:

```text
- make AI task execution less likely to drift
- detect failure earlier
- reduce wasted time or tokens
- make evidence more trustworthy
- make runtime progress more visible
- make human review safer and better timed
- make the project easier to demonstrate, review, or use
```

If the answer is not a clear yes, defer the idea. Prefer a thin adapter over a
new platform.

External wheel intake rule:

AAO is not a wheel collector. External projects such as Hermes Agent,
LangGraph, Claude Code, ECC, Langfuse, LangSmith, Braintrust, Guardrails AI,
or OpenTelemetry may be studied only through this filter:

```text
Does this strengthen AAO's control loop?

control loop:
observe execution
  -> detect abnormal behavior
  -> classify the failure
  -> choose bounded recovery
  -> record evidence
  -> expose progress/audit state
```

Only take an external idea if it clearly improves one of these control-loop
links. Do not take features just because they are impressive.

Allowed intake forms:

```text
learn a failure mode
learn a small control primitive
write a thin adapter
add a deterministic test scenario
```

Forbidden intake forms:

```text
merge another agent framework into AAO core
copy an entire conversation loop
copy an entire gateway/TUI/memory/plugin platform
make AAO depend on a large external system before its own core contract is stable
```

Stop adding wheels when AAO can prove its own core value:

```text
one real worker can be controlled
20+ golden reliability scenarios can run
false completion can be blocked
failure categories map to recovery actions
evidence and audit reports are real, not claimed
the 3-5 minute demo is clear to a new reviewer
```

---

## 2. Work Modes

AAO should support these final modes:

```text
off
  Use Claude Code directly. No AAO involvement.

log
  AAO records the task and outcome but does not block or route execution.

controlled
  AAO performs control checks, evidence collection, failure classification,
  human gates, live status, and audit reporting.

orchestrated
  AAO uses a runner such as LangGraph for complex multi-stage workflows with
  checkpoint, resume, branching, parallel work, and human interrupt.
```

Task sizing rule:

```text
small task
  1-2 files, low risk, easy to inspect, under about 30 minutes.
  Use off/log.

medium task
  one feature slice, several files, tests required, review needed.
  Use controlled.

large task
  multi-stage, multi-worker, long-running, resumable, or needs branching.
  Use orchestrated.
```

Do not force AAO onto small tasks.

---

## 3. Current Implementation Reality

The current AAO implementation already has useful control pieces, but they are
spread across the runtime:

- `src/orchestrator/scheduler.py`
  - currently acts as the native runtime loop
  - owns much of execution, evaluation, failure handling, checkpoints, and final
    reporting
- `src/orchestrator/evaluator.py`
  - L1 structural evaluation and optional L2 semantic evaluation
- `src/orchestrator/guardrails.py`
  - input and output guardrails
- `src/orchestrator/failure_taxonomy.py`
  - failure categories, severity, and failure records
- `src/orchestrator/report_writer.py`
  - convergence/audit report generation
- `src/orchestrator/agents/base.py`
  - tool declaration and trust-level tool permission checks

The next architectural move is not a big package migration. The next move is to
create a stable ControlPlane facade that can reuse these pieces.

---

## 4. Target Core Contracts

The project needs a small set of common contracts that every runner and worker
can speak.

Suggested models:

```text
TaskSize
  small | medium | large

RunMode
  off | log | controlled | orchestrated

ControlAction
  continue | retry | replan | rollback | needs_human_review | fail

ControlDecision
  action
  passed
  reason
  severity
  failure_category
  evidence_required
  next_step_hint

WorkerTask
  task_id
  objective
  allowed_files
  required_checks
  risk_level
  mode

WorkerResult
  task_id
  worker_name
  status
  output
  files_changed
  commands_run
  tests_run
  errors

EvidencePack
  task_id
  step_name
  files_changed
  commands_run
  test_results
  diff_summary
  notes
```

These contracts should be small, typed, serializable, and runner-independent.

---

## 5. Construction Plan

Work in phases. Do not skip phase gates. Each phase must have targeted tests and
must preserve existing behavior unless the phase explicitly changes it.

### Phase 0 - Baseline Inspection

Do not edit files.

Run or inspect:

```text
git status --short
src/orchestrator/scheduler.py
src/orchestrator/evaluator.py
src/orchestrator/guardrails.py
src/orchestrator/failure_taxonomy.py
src/orchestrator/report_writer.py
tests/
```

Then run the current test suite:

```bash
python -m pytest
```

If pytest is unavailable, report that clearly and use:

```bash
python -m unittest discover -s tests
```

Phase 0 output must include:

- current dirty files
- current test command and result
- current scheduler responsibilities
- existing control capabilities
- missing control capabilities

No code edits in this phase.

### Phase 1 - Core Models

Goal:

Add the shared contract language without touching runtime behavior.

Allowed files:

```text
src/orchestrator/control_models.py
tests/test_control_models.py
```

Implement:

- `TaskSize`
- `RunMode`
- `ControlAction`
- `ControlDecision`
- `WorkerTask`
- `WorkerResult`
- `EvidencePack`

Tests must prove:

- valid default `ControlDecision` can represent `continue`
- failed `ControlDecision` can include a failure category
- `WorkerTask` can record allowed files and required checks
- `EvidencePack` can record commands and test results
- all models are serializable with Pydantic/model dump

Commands:

```bash
python -m pytest tests/test_control_models.py
python -m pytest
```

Do not modify `scheduler.py` in this phase.

### Phase 2 - ControlPlane Facade

Goal:

Create one runner-independent control entry point that wraps existing evaluator,
guardrail, and failure taxonomy functionality.

Allowed files:

```text
src/orchestrator/control_plane.py
tests/test_control_plane.py
```

Allowed imports:

- `Evaluator`
- `GuardrailManager`
- `build_default_guardrail_manager`
- `GuardrailViolation`
- `failure_taxonomy`
- `control_models`
- `models`

Forbidden imports:

- `Scheduler`
- `LangGraph`
- CLI modules
- any runner

Implement:

```text
ControlPlane.evaluate_output(...)
ControlPlane.guard_input(...)
ControlPlane.guard_output(...)
ControlPlane.classify_failure(...)
ControlPlane.make_decision(...)
```

Tests must prove:

- valid output produces a continue decision
- evaluator failure produces a non-continue decision
- input guardrail violation produces fail + guardrail category
- output guardrail violation produces fail + guardrail category
- failure classification returns a structured failure record/category

Commands:

```bash
python -m pytest tests/test_control_plane.py
python -m pytest
```

Do not integrate with `scheduler.py` yet unless the user explicitly asks.

### Phase 3 - Scheduler Uses ControlPlane

Goal:

Gradually route native runtime decisions through ControlPlane without changing
external behavior.

Allowed files:

```text
src/orchestrator/scheduler.py
tests/test_runtime_smoke.py
tests/test_control_plane_integration.py
```

Rules:

- Keep existing CLI behavior compatible.
- Keep existing workflow YAML format compatible.
- Keep existing agent interface compatible.
- Keep existing report fields compatible.
- Any new report/evidence fields must be backward-compatible.
- Preserve human review pause behavior.
- Preserve guardrail failure behavior.
- Preserve failure classification trace event.

Implementation direction:

```text
Scheduler.__init__ creates self.control_plane
existing evaluation paths begin delegating to ControlPlane
existing failure classification begins delegating to ControlPlane
old private methods may remain as compatibility wrappers
```

Tests must prove:

- standard workflow still completes
- human-review workflow still pauses
- guardrail violation still fails with structured trace
- failure classified event still exists

Commands:

```bash
python -m pytest tests/test_runtime_smoke.py
python -m pytest tests/test_control_plane_integration.py
python -m pytest
```

### Phase 4 - EvidencePack

Goal:

Make runtime evidence explicit without inventing evidence that is not captured.

Allowed files:

```text
src/orchestrator/evidence.py
src/orchestrator/scheduler.py
src/orchestrator/report_writer.py
tests/test_evidence_pack.py
```

Start with evidence the current runtime really has:

- task id
- step/agent name
- input view summary
- output summary
- status
- duration
- evaluation result
- failure reason
- report path

Do not pretend to capture:

- git diff
- command output
- test output
- file changes

unless the implementation actually captures them.

Tests must prove:

- successful step can produce evidence
- failed step records error/failure reason
- missing commands/files do not crash serialization
- evidence can be written to JSON

Commands:

```bash
python -m pytest tests/test_evidence_pack.py
python -m pytest
```

### Phase 5 - Live Run View

Goal:

Expose task progress in a form Claude Code and humans can read.

Allowed files:

```text
src/orchestrator/live_view.py
src/orchestrator/__main__.py
tests/test_live_view.py
tests/test_cli_output.py
```

Core functions:

```text
build_live_view(state, result=None) -> dict
render_live_view(view) -> str
```

CLI commands may be added after the pure functions exist:

```text
python -m orchestrator status --task-id <task_id>
python -m orchestrator watch --task-id <task_id>
```

View should include:

- task id
- status
- current step
- progress
- steps total
- steps completed
- last decision
- last failure
- human review required
- report path

Tests must prove:

- completed run renders completed
- failed run shows failure reason
- needs-human-review run shows human review waiting state
- missing optional paths do not crash

Commands:

```bash
python -m pytest tests/test_live_view.py
python -m pytest tests/test_cli_output.py
python -m pytest
```

### Phase 6 - Policy YAML

Goal:

Make basic control policy declarative.

Allowed files:

```text
src/orchestrator/policy.py
examples/policy.yaml
tests/test_policy.py
```

Policy concepts:

```yaml
mode: controlled

files:
  allowed:
    - src/orchestrator/**
    - tests/**
  protected:
    - .env
    - secrets/**
    - outputs/**

checks:
  required:
    - pytest

human_review:
  required_for:
    - high_risk_tool
    - protected_file_change
    - failed_tests

tools:
  shell:
    risk_level: high
  search:
    risk_level: low
```

Tests must prove:

- allowed files pass
- protected files are blocked or require human review
- high-risk tool requires human review
- missing policy uses safe defaults

Commands:

```bash
python -m pytest tests/test_policy.py
python -m pytest
```

### Phase 7 - Final Integration Gate

Goal:

Prove AAO Core behaves as one system, not scattered helpers.

Add or update:

```text
tests/test_control_plane_integration.py
```

Required scenarios:

```text
1. Normal workflow
   run deep_research.yaml
   expect completed
   expect report exists
   expect live view can render
   expect evidence can be generated

2. Guardrail workflow
   trigger sensitive output
   expect failed
   expect failure category GUARDRAIL_BLOCKED

3. Human review workflow
   run deep_research_human_review.yaml
   expect needs_human_review
   expect live view says human review is required

4. Evaluator failure
   construct missing-field output
   expect ControlDecision is not continue

5. Failure taxonomy
   construct error context
   expect category and severity are present
```

Commands:

```bash
python -m pytest
```

Final phase output must include:

- total tests run
- passed/failed/skipped
- changed files
- remaining risks
- next recommended phase

### Phase 7A - Core Closure Gate

Goal:

Close the remaining quality gaps in Phase 0-7 before adding new control-layer
capabilities. This phase is a hardening and closure phase, not a feature
expansion phase.

This phase exists because Phase 0-7 can pass tests while still leaving hidden
interface drift:

```text
ControlPlane exists, but some runtime checks may still bypass it.
Live view exists, but progress may not yet represent the whole run clearly.
Evidence exists, but summaries must stay honest and bounded.
Policy exists, but it must not be described as runtime enforcement unless it is.
```

Non-goals:

- no LangGraph
- no ClaudeCodeWorker
- no new top-level package
- no package migration
- no new heavy dependency
- no new planning council
- no Phase 7.5 control-layer expansion
- no broad rewrite of `scheduler.py`
- no unrelated sales-agent, docs, or job-search work

Allowed files:

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

Required fixes:

1. `ControlPlane.make_decision()` must guard the actual output.

   Current contract:

   ```text
   input guard checks payload/input context
   evaluator checks output
   output guard checks output
   ```

   It is not acceptable for output guardrails to check the input payload when
   the caller provided a separate `output` object.

   Required tests:

   ```text
   test_make_decision_blocks_sensitive_output_even_when_input_payload_is_clean
   test_make_decision_allows_clean_input_and_clean_output
   ```

2. Scheduler guardrail execution must go through ControlPlane.

   Target runtime path:

   ```text
   Scheduler
     -> ControlPlane.guard_input(agent_name, payload=view, guardrail_names=agent.config.guardrails)
     -> agent.run(view)
     -> ControlPlane.guard_output(agent_name, payload=output, guardrail_names=agent.config.guardrails)
     -> ControlPlane.evaluate_output(...)
     -> ControlPlane.classify_failure(...)
   ```

   The scheduler should not directly call:

   ```text
   agent.apply_input_guardrails(...)
   agent.apply_output_guardrails(...)
   ```

   unless those calls are retained only as deprecated compatibility wrappers and
   are not used by the scheduler runtime path.

   Required behavior to preserve:

   - empty query still fails before agent execution
   - sensitive output still fails after agent execution
   - `guardrail_violation` trace event still contains:
     - `event`
     - `agent_name`
     - `stage`
     - `reason`
     - `failure_category`
     - `timestamp`
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

3. Control action naming must be consistent.

   Use this spelling everywhere in code, tests, and documentation:

   ```text
   needs_human_review
   ```

   Do not introduce a second action name such as `human_review` unless there is
   an explicit compatibility mapping and tests for it.

4. Live view progress must be honest and useful.

   `build_live_view(...)` must not pretend to know more than the runtime state
   records. It should expose progress from real runtime signals:

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

   Backward compatibility rule:

   ```text
   build_live_view(state, result=None) must still work.
   Optional extra arguments are allowed only if old callers keep working.
   ```

   Required tests:

   ```text
   test_live_view_progress_uses_workflow_total_when_available
   test_live_view_progress_has_honest_fallback_without_workflow
   test_live_view_reports_current_step_for_failed_run
   test_live_view_reports_current_step_for_human_review_run
   ```

5. EvidencePack must stay honest but become more readable.

   Evidence may include a short `output_summary` only if it is derived from data
   the runtime actually recorded.

   Do not invent:

   ```text
   files_changed
   commands_run
   test_results
   diff_summary
   ```

   unless the runtime really captures those fields.

   Required tests:

   ```text
   test_evidence_pack_derives_bounded_output_summary_from_recorded_output
   test_evidence_pack_does_not_invent_files_commands_tests_or_diff
   test_evidence_summary_in_report_is_readable_and_bounded
   ```

6. Policy scope must be explicit.

   Phase 6 introduced a declarative policy parser/check helper. In Phase 7A,
   do not claim runtime policy enforcement unless scheduler/runtime enforcement
   is actually implemented and tested.

   Default closure requirement:

   ```text
   Policy is a declarative helper in Phase 0-7.
   Runtime enforcement belongs to a later phase unless the user explicitly asks
   to implement the minimal enforcement slice now.
   ```

   Required tests:

   ```text
   test_policy_default_behavior_is_documented_by_tests
   test_policy_protected_file_requires_review_when_configured
   test_policy_high_risk_tool_requires_review_when_configured
   ```

7. Repository hygiene must pass.

   Required cleanup:

   - add or update `.gitignore`
   - ensure `.venv/`, `.claude/`, `.pytest_cache/`, `__pycache__/`, `tmp/`, and
     generated `outputs/` are not intended commit content
   - remove trailing whitespace from changed files
   - avoid UTF-8 BOM in source and markdown files unless explicitly required
   - normalize line endings for edited source files

   Required commands:

   ```bash
   git diff --check
   python3 -m compileall -q src tests
   python3 -m pytest tests/test_control_models.py tests/test_control_plane.py tests/test_control_plane_integration.py tests/test_live_view.py tests/test_evidence_pack.py tests/test_policy.py -q
   python3 -m pytest -q
   git status --short
   ```

Definition of done:

```text
Phase 7A is done only when:
- all required tests exist
- all targeted tests pass
- full pytest passes
- compileall passes
- git diff --check passes
- scheduler guardrails no longer bypass ControlPlane
- make_decision guards output, not input payload
- live view progress is honest and backward-compatible
- evidence is more readable without false claims
- policy scope is explicit
- the final report lists changed files and remaining risks
```

Required final explanation to the user:

Explain Phase 7A naturally and concretely. Do not just say "tests pass."
Explain:

```text
what was wrong before
what was changed
how the runtime path works now
what tests prove it
what is still intentionally not included
```

### Phase 7B - Hermes-Informed ControlPlane Hardening

Goal:

Strengthen the AAO control layer using lessons from mature agent execution
systems, especially `NousResearch/hermes-agent`, without integrating Hermes as
a dependency or changing AAO's product direction.

This phase exists because Phase 0-7A can make the ControlPlane structurally
connected while still leaving important product-grade control cases
underspecified:

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

Reference sources:

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

Borrowing policy:

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
  Hermes conversation loop
  gateway
  TUI
  memory system
  provider failover runtime
  worker/delegation runtime
```

If code or data is copied or closely adapted from Hermes, add a short source
comment near each borrowed piece and keep the MIT license obligations in mind.
The comment should name the exact upstream file and symbol/pattern when
possible, for example:

```python
# Adapted from Hermes Agent (MIT): agent/error_classifier.py _BILLING_PATTERNS
```

Prefer copying small stable data/utility code over copying large behavior. The
source comment is not just legal hygiene; it makes the borrowed production
experience visible to reviewers and future maintainers.

Non-goals:

- no Hermes dependency
- no Hermes gateway
- no Hermes TUI
- no Hermes conversation loop
- no Hermes full memory system
- no LangGraph
- no Claude Code Worker Bridge
- no Planning Council
- no web dashboard
- no new heavy dependency
- no broad scheduler rewrite
- no extra LLM call in the default control path
- no automatic infinite retry loop

Allowed files:

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

Any other file change must be justified before editing.

Required work:

1. Failure classification must distinguish origin, category, reason, and
   recovery.

   Do not turn `FailureCategory` into a flat dumping ground for every provider
   error. Keep the model readable:

   ```text
   origin/source
     where the failure was observed or reported

   category
     broad failure family

   reason
     concrete machine-readable cause

   recovery hint / action
     bounded next action
   ```

   Important boundary:

   ```text
   ControlPlane does not directly call LLM providers.

   Provider/API failures are reported by a worker or provider layer:
     Worker/Provider -> FailureRecord -> ControlPlane classify/decide

   ControlPlane-originated failures come from control decisions:
     evaluator failed
     guardrail blocked
     policy denied
     evidence missing
   ```

   Suggested origins/sources:

   ```text
   control_plane
   worker
   provider
   tool
   policy
   scheduler
   unknown
   ```

   Recommended categories and reasons:

   ```text
   PROVIDER_ERROR
     auth
     auth_permanent
     billing
     rate_limit
     timeout
     overloaded
     server_error
     context_overflow
     model_not_found
     format_error

   TASK_QUALITY_ERROR
     evaluation_failed
     low_quality_output
     missing_required_field
     missing_evidence

   GUARDRAIL_BLOCKED
     input_guardrail_blocked
     output_guardrail_blocked
     sensitive_content
     protected_action

   TOOL_ERROR
     tool_failed
     exact_repeated_tool_failure
     same_tool_repeated_failure
     idempotent_no_progress

   POLICY_ERROR
     protected_file_change
     high_risk_tool
     reviewer_write_attempt
     missing_required_check

   UNKNOWN
     unknown
   ```

   Existing categories must remain backward-compatible where practical. If a
   compatibility mapping is needed, add tests for it.

   Provider reasons such as `billing`, `rate_limit`, or `timeout` do not mean
   the ControlPlane caused the provider failure. They mean the ControlPlane can
   understand a provider failure reported by the worker and choose a bounded
   next action.

2. Recovery hints must be explicit and bounded.

   Each known failure should map to a recovery hint. Suggested actions:

   ```text
   continue
   retry
   retry_with_backoff
   request_evidence
   compress_context
   fallback_model_or_provider
   replan
   needs_human_review
   fail
   ```

   Do not let the scheduler guess recovery from raw strings when the
   ControlPlane already knows the failure reason.

   A recovery hint is not the same thing as implemented runtime capability.
   For example, `fallback_model_or_provider` means "this failure is safe to
   solve by provider fallback if such a provider route exists." If AAO does not
   yet have provider fallback wired, return the hint clearly but do not pretend
   the runtime actually switched providers.

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

3. Jittered backoff must be used only for transient failures.

   Add a small local utility if needed. It may be inspired by Hermes
   `jittered_backoff`, but do not import Hermes.

   Use it only for:

   ```text
   rate_limit
   timeout
   overloaded
   server_error
   ```

   Never use blind retry/backoff for:

   ```text
   guardrail_blocked
   protected_file_change
   missing_evidence
   evaluation_failed without a retry limit
   billing
   auth_permanent
   format_error without a changed request
   ```

4. Add a pure tool-loop guardrail controller.

   Inspired by Hermes `tool_guardrails.py`, add a small AAO-native control
   primitive that can be called by ControlPlane.

   It should detect:

   ```text
   exact repeated failure
     same tool name + same normalized arguments fails repeatedly

   same tool repeated failure
     same tool fails repeatedly even with different arguments

   idempotent no-progress
     read-only/idempotent tool returns the same result repeatedly
   ```

   This controller must be pure and testable. It should not require a live
   runner, live shell, model call, or Hermes dependency.

   Suggested output shape:

   ```text
   action: allow | warn | block | halt
   code
   reason
   tool_name
   count
   normalized_signature or args hash
   recovery_hint
   ```

   Safety rules:

   - normalize tool arguments with stable ordering
   - do not store raw sensitive arguments in public metadata if avoidable
   - read-only no-progress should compare stable result hashes, not long raw
     outputs
   - different arguments or different results should not be falsely blocked
   - warnings and hard stops must have separate thresholds

5. Do not fake runtime integration.

   If the current scheduler/runtime does not yet record enough tool-call events
   to apply this controller during real runs, keep the controller as a pure
   ControlPlane capability and write tests for it. Do not pretend it is wired
   into runtime if it is not.

   Runtime wiring can happen only when there is a real event path:

   ```text
   tool call planned
     -> ControlPlane pre-tool check
     -> tool executed or blocked
     -> tool result recorded
     -> ControlPlane post-tool update
     -> trace/evidence updated
   ```

6. Worker isolation lessons are documentation/checklist only in this phase.

   From Hermes `delegate_tool.py`, record the worker isolation checklist for
   later Phase 12:

   ```text
   independent context
   restricted tools
   independent task id
   focused task prompt
   parent sees result/evidence summary, not full child reasoning
   heartbeat/stall detection
   dangerous action approval does not block the main control loop
   ```

   Do not implement the Claude Code Worker Bridge in Phase 7B.

7. Hermes memory/reflection prompt ideas are deferred.

   Hermes also contains useful background review / reflection ideas about what
   should be remembered, what should not be remembered, and how skills should
   be updated. Do not implement that in Phase 7B. Record it as Phase 14 memory
   layer reference material only.

Required tests:

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

If existing test filenames differ, use the closest matching test file or add a
focused new test file. Keep test names contract-based.

Required commands:

```bash
python -m pytest tests/test_failure_taxonomy.py tests/test_control_plane.py tests/test_guardrails.py -q
python -m pytest tests/test_control_plane_integration.py -q
python -m pytest -q
git diff --check
python -m compileall -q src tests
git status --short
```

If the full suite fails for an environment reason, report the exact failing
command and error. Do not claim the phase is done.

Definition of done:

```text
Phase 7B is done only when:
- provider/API failure reasons exist and are tested
- known failure reasons map to bounded recovery hints
- transient retry uses jitter/backoff only where appropriate
- non-retryable failures do not silently retry
- tool-loop guardrail controller exists and is pure/tested
- recovery hints whose runtime support is not yet implemented are listed in
  the phase handoff, not silently treated as done
- no Hermes dependency was added
- no Phase 8+ feature was started
- targeted tests pass
- full tests pass or failures are precisely explained
- final explanation says what was borrowed from Hermes and what was not
```

Required final explanation to the user:

Explain Phase 7B naturally and concretely. Include:

```text
what got stronger in ControlPlane
which Hermes ideas were borrowed
which Hermes parts were intentionally not integrated
which failures can retry
which failures must not retry
what the tool-loop guardrail detects
what remains for Phase 8/10/11/12
```

---

## 5B. AAO v1 Product Release Plan

Phase 0-7B closes AAO Core. Phase 8-17 turn that core into the complete
version the user can actually use, record, and show as proof of AI-native
engineering ability.

CLAUDE.md keeps the product map and hard constraints. Detailed construction
specs live in .claude/phase-specs/. For Phase 8+, always read the matching
phase spec before editing files.

Product-release phases:

```text
Phase 8   Real-Time Watch
          Make runtime progress, evidence, failures, recovery, and human-review
          state visible while a task is running.

Phase 9   Task Router
          Route small/medium/large work into off/log/controlled/orchestrated
          modes without making simple tasks heavy.

Phase 9A  Runtime Mode + Cleanup Contract
          Turn the routing labels into explicit runtime semantics and stop the
          CLI/scheduler from accumulating more mixed responsibilities before
          policy, recovery, worker, and LangGraph phases add more pressure.

Phase 10  Runtime Policy Enforcement
          Turn declarative policy into minimal real runtime blocking/review
          behavior for protected files, high-risk tools, failed checks, and
          missing evidence.

Phase 11  Recovery Playbook
          Map failure categories to bounded actions such as retry, request
          evidence, replan, human review, or fail.

Phase 12  Claude Code Worker Bridge
          Let AAO create task packets for Claude Code workers and verify the
          returned evidence/result files.

Phase 12A ECC Integration Pack
          Use ECC-style commands, hooks, and worker rules to make Claude Code
          workers more disciplined without replacing AAO ControlPlane.

Phase 13  Planning Council
          For complex tasks, create a plan, challenge risks, merge a final plan,
          and require user approval before execution.

Phase 14  Memory Layer
          Add lightweight inspectable project memory for decisions, constraints,
          failures, and runs, with observed/reported/inferred source labels.

Phase 15  LangGraph Runner
          Add LangGraph as an optional orchestrated-mode runner for complex DAG,
          checkpoint, resume, branching, and human interrupt.

Phase 16  Golden Scenario Suite
          Prove AAO's control behavior with deterministic scenarios such as
          missing evidence, policy deny, human review, recovery, and audit.

Phase 17  Demo, README, and Release
          Make AAO easy to understand, run, trust, and record in a 3-5 minute
          demo.
```

Phase spec index:

```text
.claude/phase-specs/phase-08-real-time-watch.md
.claude/phase-specs/phase-09-task-router.md
.claude/phase-specs/phase-09a-runtime-mode-cleanup-contract.md
.claude/phase-specs/phase-10-runtime-policy-enforcement.md
.claude/phase-specs/phase-11-recovery-playbook.md
.claude/phase-specs/phase-12-claude-code-worker-bridge.md
.claude/phase-specs/phase-12a-ecc-integration-pack.md
.claude/phase-specs/phase-13-planning-council.md
.claude/phase-specs/phase-14-memory-layer.md
.claude/phase-specs/phase-15-langgraph-runner.md
.claude/phase-specs/phase-16-golden-scenario-suite.md
.claude/phase-specs/phase-17-demo-readme-release.md
```

Do not ask Claude Code to implement Phase 8-17 in one pass. Start exactly one
phase at a time, read that phase spec, implement it, test it, hand it off, and
review it before moving on.

Do not start Phase 8 until Phase 7B is reviewed. Phase 8 is a visibility phase;
it should display real control decisions, not compensate for a shallow
ControlPlane.

---

## 6. Optional Integrations - Not Core Phases

These are future adapters. Do not add them during Phase 0-7B. When a later
product-release phase introduces one, use it as a thin adapter, not as the AAO
brain.

```text
LangGraph
  Use later for complex DAG, parallelism, checkpoint, resume, and human
  interrupt. It should be a runner, not the AAO brain.

Langfuse
  Use later as trace/export dashboard. It should receive AAO events, not control
  AAO decisions.

DeepEval
  Use later for offline regression/eval suites. It should test AAO outputs, not
  replace ControlPlane.

LiteLLM
  Use later for model gateway, provider routing, fallback, and cost tracking.

Guardrails AI
  Use later as optional validator adapters. Keep AAO GuardrailManager as the
  control entry point.

OPA/Casbin
  Use much later only if enterprise policy needs justify it. Start with YAML
  policy.

Hermes Agent
  Do not integrate Hermes as a whole system. Treat it as a mature execution
  project to study for failure modes and small control primitives. Acceptable
  references: error classification, tool-loop guardrails, jittered retry, and
  worker isolation checklists. Future support may be a thin HermesWorker
  adapter, not a Hermes-based AAO core.
```

---

## 7. Project Skills

Use project skills as operating modes. CLAUDE.md keeps the index and global
communication rule; detailed project-skill instructions live in
.claude/project-skills/.

Communication rule for all project skills:

```text
Use the skill as an internal operating checklist, not a rigid answer template.
Be strict about evidence, tests, scope, file paths, and validation.
Be natural in explanation and teaching.
Use structured checklists when risk is high, when reviewing code, or when
handing off a phase. For quick explanations, use clear prose first.
```

If the user says they do not understand, slow down and explain the concrete
runtime path before adding more abstraction.

Project-skill index:

```text
.claude/project-skills/aao-core-builder.md
  Use when modifying AAO core architecture.

.claude/project-skills/aao-boundary-test-designer.md
  Use before adding or changing runtime behavior.

.claude/project-skills/aao-reviewer-mode.md
  Use in a separate read-only review session. Reviewer must check final
  behavior, runtime path, architecture contract, and false-green tests.

.claude/project-skills/aao-tutor-explanation.md
  Use after every phase, feature slice, bug fix, or important design decision.

.claude/project-skills/aao-scope-guard.md
  Use when the task starts expanding or a dependency/feature feels tempting.

.claude/project-skills/aao-live-visibility.md
  Use when implementing runtime status, progress, evidence, or reporting.

.claude/project-skills/aao-phase-handoff.md
  Use before stopping work or moving to the next phase.
```

Before starting a phase, read the matching phase spec and any relevant
project-skill file. Do not load every phase spec or every project skill by
default.

---

## 8. Repository Hygiene And Phase Commit Discipline

Product-release phases must not blur into one giant working tree.

If `git status --short` shows many unrelated changes, do not keep piling on new
work blindly. First classify what is in the tree.

Use these buckets:

```text
A. phase spec / project rules
   CLAUDE.md
   .claude/phase-specs/
   .claude/project-skills/

B. current phase source + tests
   the smallest code/test set that implements the active phase

C. supporting docs
   docs/, README notes, ADRs, demo scripts

D. local or generated noise
   .claude/projects/
   tmp/
   outputs/
   caches
   local settings
```

Rules:

1. Do not use `git add .` in this project.
2. Stage explicit file lists only.
3. Keep phase-rule/docs commits separate from code commits when practical.
4. Do not start the next phase if the current phase code is not tested and
   handoff-reviewed.
5. If the tree is already messy, stop and report the buckets before adding more
   changes.

Preferred commit slicing:

```text
Commit 1
  phase rules / phase spec / CLAUDE.md updates

Commit 2
  current phase code + tests

Commit 3
  optional supporting docs or demo material
```

Before any commit, run:

```bash
git status --short
git diff --check
python -m compileall -q src tests
python -m pytest -q
```

Use the equivalent `py -m ...` commands on Windows if needed.

If full pytest is too expensive for the current step, run targeted tests first
and say clearly what full-suite coverage is still pending.

---

## 9. Reviewer Workflow

For each phase:

1. Implementation session makes the smallest phase-bounded change.
2. Implementation session runs targeted tests.
3. Implementation session runs full tests when practical.
4. Separate reviewer session reviews the diff in read-only mode.
5. Reviewer names the architecture contract for the phase.
6. Reviewer traces the runtime path from source event to final report/audit.
7. Reviewer asks what current tests would still pass if the design were only
   superficially wired.
8. P0 issues must be fixed before moving on.
9. P1 issues should be fixed unless clearly deferred with reason.
10. P2 issues are recorded as follow-up.
11. User approves before the next phase begins.

Do not let one session both implement and approve its own work.

---

## 10. Testing Standard

For any runtime-control change, tests must include:

- bad case fails safely
- normal case still passes
- boundary case
- false-positive guard
- nearby regression path
- contract/path test when the phase promises a specific runtime path

Use targeted tests first, then full tests.

For control-layer changes, do not only test the final value. Add at least one
test that would fail if the implementation merely guessed the right result at
the end.

Examples:

- Known failure categories are propagated explicitly; `infer_failure_category`
  is used only for unknown fallback paths.
- Observed evidence comes from captured command/test output, not from worker
  claims.
- A read-only reviewer path cannot call write tools even if the final report
  would look valid.

Preferred command order:

```bash
python -m pytest tests/<target_test_file>.py
python -m pytest
```

If pytest is unavailable:

```bash
python -m unittest discover -s tests
```

Report the exact command and result. Do not say tests passed unless the command
actually passed.

---

## 10. Final Definition of Done

AAO has two definitions of done: Core Done and v1 Product/Portfolio Release
Done.

AAO Core is considered done only when:

- Control models exist and are tested.
- ControlPlane exists and is runner-independent.
- Scheduler delegates relevant decisions to ControlPlane without breaking
  current CLI/workflows.
- Known failure categories are propagated explicitly instead of being guessed
  through fallback inference.
- Failure classification includes enough reason/recovery information to decide
  whether to retry, back off, request evidence, replan, ask for human review, or
  fail.
- Transient provider failures and non-retryable control failures are clearly
  separated.
- Tool-loop/no-progress guardrails exist as pure tested control primitives.
- EvidencePack records real runtime evidence.
- LiveRunView can show task progress and human-review state.
- Policy YAML can express basic allowed/protected files, required checks, and
  human-review triggers.
- Integration tests cover normal, guardrail, human-review, evaluator-failure,
  failure-taxonomy, recovery-hint, and tool-loop paths.
- Full test suite passes or any skipped tests are clearly explained.
- Reviewer session has no blocking P0 findings.

Only after this should the project move into product-release phases such as:

- Real-Time Watch
- Task Router
- Runtime Policy Enforcement
- Recovery Playbook
- Claude Code Worker Bridge
- LangGraphRunner
- Golden Scenario Suite
- Demo/README release work

AAO v1 Product/Portfolio Release is considered done only when:

- a real task can be run through the Claude Code worker bridge
- Live Watch shows task progress and control decisions while the task runs
- false completion can be blocked by missing tests/evidence/policy
- failures are classified and mapped to recovery actions
- human review can pause and resume a risky run
- Audit Report includes real observed evidence and clear limitations
- Golden Scenario Suite passes
- README quickstart works from a clean clone
- the demo script can show AAO's value in 3-5 minutes

Do not claim AAO v1 is complete just because the core tests pass. Core tests
prove the control foundation; product-release tests prove it is usable and
showable.
