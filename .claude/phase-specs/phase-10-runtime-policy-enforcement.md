# Phase 10 - Runtime Policy Enforcement

## Goal

Move policy from a declarative helper into a minimal real runtime control path.

After this phase, policy should not only answer "what does the YAML say?" It
should be able to influence a run through `ControlDecision`:

```text
allow -> continue
deny -> fail
needs_human_review -> pause for human review
require_evidence -> block completion until required evidence exists
```

This is the first phase where policy becomes a runtime gate.

## Why This Phase Exists

Phase 6 made policy declarative. Phase 9A made run modes and runtime boundaries
explicit. Phase 10 connects those two pieces.

The mental model:

```text
Worker wants to do or report something
  -> Runner records the attempted action/result
  -> ControlPlane asks Policy for a decision
  -> Scheduler follows the decision
```

Policy should not live as scattered `if` statements in `scheduler.py`.
Scheduler may call policy/control helpers, but it should not become the policy
engine.

## Preflight

Before editing, read:

```text
CLAUDE.md
.claude/phase-specs/phase-09a-runtime-mode-cleanup-contract.md
.claude/phase-specs/phase-10-runtime-policy-enforcement.md
.claude/project-skills/aao-boundary-test-designer.md
.claude/project-skills/aao-phase-handoff.md
```

Then inspect the current source:

```text
src/orchestrator/policy.py
src/orchestrator/control_plane.py
src/orchestrator/control_models.py
src/orchestrator/scheduler.py
src/orchestrator/live_view.py
src/orchestrator/report_writer.py
tests/test_policy.py
tests/test_control_plane_integration.py
```

Run `git status --short` first. If unrelated files are dirty, name them in the
handoff. Do not use `git add .`.

## Non-Goals

- No OPA/Casbin.
- No enterprise policy engine.
- No broad permission framework.
- No filesystem sandbox.
- No LangGraph.
- No ECC integration.
- No Claude Code Worker Bridge.
- No Recovery Playbook.
- No provider/model fallback.
- No broad scheduler rewrite.
- No new heavy dependency.
- No fake enforcement claims without runtime-path tests.

## Allowed Files

Prefer this write set:

```text
src/orchestrator/policy.py
src/orchestrator/control_plane.py
src/orchestrator/control_models.py
src/orchestrator/scheduler.py
src/orchestrator/live_view.py
src/orchestrator/report_writer.py
examples/policy.yaml
tests/test_policy.py
tests/test_control_plane.py
tests/test_control_plane_integration.py
tests/test_runtime_smoke.py
tests/test_live_view.py
```

Only touch other files if source inspection proves it is necessary. Explain the
reason in the handoff.

## Policy Decision Contract

Policy enforcement should speak the existing AAO control language. Prefer
returning or embedding `ControlDecision` rather than inventing a parallel
decision type unless a small helper model is clearly needed.

Required decision mapping:

```text
allow
  ControlDecision(passed=True, action="continue", recovery_hint="continue")

deny
  ControlDecision(
      passed=False,
      action="fail",
      failure_category="policy_error",
      failure_origin="policy",
      recovery_hint="fail",
  )

needs_human_review
  ControlDecision(
      passed=False,
      action="needs_human_review",
      failure_category="policy_error",
      failure_origin="policy",
      recovery_hint="needs_human_review",
  )

require_evidence
  ControlDecision(
      passed=False,
      action="fail" or "needs_human_review",
      evidence_required=True,
      failure_category="evidence_error" or "policy_error",
      failure_origin="policy",
      recovery_hint="request_evidence",
  )
```

If the current taxonomy already has a more precise category/reason, use it. Do
not add broad new categories unless necessary.

## Required Runtime Slice

Implement the smallest real runtime enforcement slice that covers these cases:

```text
1. reviewer workers are read-only
2. protected files require human review
3. high-risk tools require human review
4. failed required checks block success
5. missing required evidence blocks success
6. policy decisions are visible in trace/live/report where practical
```

### 1. Reviewer workers are read-only

If a worker/agent is acting as a reviewer, policy must prevent it from writing
files or reporting file changes as acceptable.

Minimum acceptable behavior:

```text
reviewer + files_changed not empty -> deny or needs_human_review
reviewer + no file changes -> allow
```

Do not rely only on the worker saying "I was read-only." Use observed
`files_changed` or equivalent runtime data when available.

### 2. Protected files require human review

When policy declares protected file patterns, changing or attempting to change a
matching path must produce a human-review decision.

Examples:

```text
.env
secrets/**
CLAUDE.md
```

Protected file policy should not block unrelated files.

### 3. High-risk tools require human review

When policy declares a tool as high risk and the policy says high-risk tools
require review, using that tool must produce a human-review decision.

Examples:

```text
shell: high
delete_file: high
network_write: high
```

Low-risk tools must still pass.

### 4. Failed required checks block success

If policy requires checks such as `pytest` or `compileall`, a run must not be
reported as successfully complete when the corresponding observed check failed.

Important boundary:

```text
observed failed check -> block success
worker merely claims tests passed -> not enough if observed evidence is absent
no required checks configured -> do not block
```

### 5. Missing required evidence blocks success

If policy requires evidence and the runtime has no observed evidence for it,
the run must not silently complete.

This is a control-plane problem, not a wording problem. Do not solve it only by
changing the final report text.

### 6. Trace/live/report visibility

Where practical, record policy decisions in existing trace/live/report fields.
Do not build a new dashboard in this phase.

Minimum acceptable visibility:

```text
execution_trace contains a policy decision event or equivalent structured data
live view can show the last policy decision if available
report/audit output does not hide policy-triggered review/failure
```

## Integration Boundaries

### ControlPlane

Add policy methods to `ControlPlane` or route through an existing composite
method. The key is that runner-agnostic policy decisions should have a single
entry point.

Suggested methods:

```text
check_policy_for_worker_result(...)
check_policy_for_tool_call(...)
check_policy_for_files(...)
check_policy_for_evidence(...)
```

Names may differ, but tests must prove scheduler/runtime paths use the
ControlPlane or a small policy helper, not scattered scheduler rules.

### Scheduler

Scheduler may:

```text
collect runtime facts
call ControlPlane/policy helper
record a policy event
pause/fail according to ControlDecision
```

Scheduler must not:

```text
contain a large policy matrix
guess policy failure categories from raw strings
implement retry/recovery playbook
silently convert needs_human_review into completed
```

If `scheduler.py` must be touched, the final handoff must include:

```text
scheduler.py line count before/after
what policy responsibility was added
why it could not live in policy.py/control_plane.py
whether any responsibility was moved out
```

### Policy module

`policy.py` may grow small, focused helpers. Keep it deterministic and easy to
unit test. Do not add LLM calls.

### Run mode

Respect Phase 9A semantics:

```text
off -> no enforcement
log -> record/display only; no blocking
controlled -> enforce policy
orchestrated -> future runner or explicit fallback; do not fake completion
```

If the current runtime does not pass mode deeply enough to enforce this, make
the smallest explicit wiring needed and test it.

## Boundary Test Matrix

Contract:

```text
Configured policy can affect runtime decisions without turning scheduler.py into
the policy engine, and valid low-risk behavior still passes.
```

Required tests:

```text
Bad case: reviewer worker reports file changes
  Expected: deny or needs_human_review, not completed

Bad case: protected file changed
  Expected: needs_human_review with policy_error/protected_file reason

Bad case: high-risk tool used
  Expected: needs_human_review with policy decision recorded

Bad case: required check failed
  Expected: success is blocked

Bad case: required evidence missing
  Expected: request_evidence / fail / human_review, not completed

Normal case: allowed file + low-risk tool + required checks pass
  Expected: continue

Boundary case: no policy configured
  Expected: existing behavior preserved

False-positive guard: protected pattern does not match unrelated path
  Expected: continue

Regression path: existing human_review workflow still pauses/resumes
  Expected: current human review tests keep passing

Runtime path test: scheduler/control integration actually calls policy path
  Expected: a fake or spy policy decision changes runtime outcome
```

Prefer behavior-first test names:

```text
test_reviewer_worker_cannot_write
test_protected_file_requires_human_review
test_high_risk_tool_requires_human_review
test_failed_required_check_blocks_success
test_missing_required_evidence_blocks_success
test_policy_decision_is_recorded
test_policy_allows_low_risk_valid_result
test_policy_default_preserves_existing_behavior
test_scheduler_uses_control_plane_for_policy_decision
```

## Validation Commands

Run targeted tests first:

```bash
PYTHONPATH=src python -m pytest -q tests/test_policy.py tests/test_control_plane.py tests/test_control_plane_integration.py
```

Then run:

```bash
PYTHONPATH=src python -m pytest -q tests/test_runtime_smoke.py tests/test_live_view.py
PYTHONPATH=src python -m pytest -q
python -m compileall -q src tests
git diff --check
git status --short
```

On Windows, use equivalent `py -m ...` commands if that is the working
interpreter.

## Definition Of Done

Phase 10 is done only when:

```text
- policy is no longer only parsed; at least the required slice affects runtime
  decisions
- reviewer write attempts are blocked or sent to human review
- protected file changes require human review
- high-risk tool usage requires human review
- failed required checks block success
- missing required evidence blocks success
- policy decisions are recorded in trace/live/report where practical
- off/log/controlled/orchestrated behavior respects Phase 9A semantics
- scheduler does not contain a large embedded policy matrix
- targeted tests pass
- full pytest passes or unrelated failures are documented
- compileall passes
- git diff --check passes
- final handoff includes dirty files outside phase scope and recommended commit
  slice
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
deferred ideas
next recommended step
safe to proceed
recommended next commit slice
```

## Required Final Explanation To User

Explain Phase 10 naturally and concretely.

Use this mental model:

```text
Before Phase 10, policy was like a rulebook sitting on the table.
After Phase 10, the runtime can actually stop at the door and say:
this file needs review, this tool is high risk, these tests failed, or this
evidence is missing.
```

Make clear:

```text
what policy cases are now enforced
where the runtime checks happen
what happens when policy says human review
what happens when required evidence/checks are missing
what remains for Phase 11 recovery
what remains for Phase 12 worker bridge
```

Do not oversell Phase 10 as a full enterprise policy system.
