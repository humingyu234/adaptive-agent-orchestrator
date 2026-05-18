# Phase 9A - Runtime Mode + Cleanup Contract

## Goal

Make Phase 9's routing labels operationally clear before adding runtime policy,
recovery, worker bridge, planning, or LangGraph features.

This phase answers:

```text
When the router says off/log/controlled/orchestrated, what does AAO actually do?
Which files are allowed to keep growing, and which must stop collecting mixed
responsibilities?
```

This is a cleanup and contract phase. It is not a feature expansion phase.

## Why This Phase Exists

Phase 9 introduced task routing. Phase 10 and Phase 11 will add policy and
recovery pressure to the runtime. If mode semantics and cleanup boundaries stay
implicit, `scheduler.py` and `__main__.py` will keep getting larger and harder
to reason about.

The purpose is to make the runtime path boring and explicit:

```text
small task  -> AAO stays out or only logs
medium task -> AAO controls the native run
large task  -> AAO marks it as orchestrated/future-orchestrated honestly
```

Do not treat this as a delay. Treat it as a guardrail against future messy
implementation.

## Required Runtime Semantics

Define the behavior of each run mode in code and tests.

```text
off
  Route/classify only if needed, then do not execute a workflow, do not block,
  do not run evaluator/guardrails/policy/recovery.

log
  Record or display the route decision, but do not block or escalate. This mode
  is for visibility, not control.

controlled
  Run through the current native runtime and let AAO control decisions apply:
  guardrails, evaluator gates, explicit failure classification, policy, recovery
  as each phase makes those capabilities real.

orchestrated
  Reserved for complex multi-step orchestration. Until a real orchestrated
  runner exists, mark it as future_orchestrated or fallback_controlled. Never
  pretend the native runner is a completed orchestrated runner.
```

These semantics must be easy to find from source. Prefer a small helper/model
over scattered `if run_mode == ...` logic.

## Worker vs Runner Language

Keep this wording precise:

```text
Worker
  Claude Code worker, LLM worker, or another execution actor that actually does
  a task.

Runner
  NativeRunner, future LangGraphRunner, or another runtime that schedules steps
  and calls workers.

ControlPlane
  The AAO decision layer that evaluates, blocks, classifies, requests evidence,
  and decides recovery. It should not become a worker or runner.
```

Do not call NativeRunner or LangGraphRunner "workers" in code comments,
handoffs, docs, or PR descriptions.

## Non-Goals

- No LangGraph integration.
- No ECC integration.
- No Claude Code worker bridge.
- No new Planning Council.
- No new provider gateway.
- No new recovery playbook behavior beyond explicit boundaries.
- No broad rewrite of `scheduler.py`.
- No broad rewrite of `__main__.py`.
- No fake runtime integration.
- No new heavy dependency.

## Allowed Files

Prefer this write set:

```text
src/orchestrator/task_router.py
src/orchestrator/control_models.py
src/orchestrator/__main__.py
src/orchestrator/cli_output.py
src/orchestrator/state_center.py
src/orchestrator/report_writer.py
src/orchestrator/sales_preview.py        # new if moving preview logic out
tests/test_task_router.py
tests/test_cli_output.py
tests/test_state_center.py
tests/test_sales_preview.py              # new if sales preview is moved
```

Touch `src/orchestrator/scheduler.py` only if needed to pass or record
`run_mode` cleanly. Do not add policy/recovery implementation there in this
phase.

## Required Cleanup Work

### 1. Make mode semantics explicit

Add a small source-level contract for run-mode behavior. It may be:

```text
RunModeSemantics
should_execute_workflow(decision)
should_apply_control(decision)
should_only_log(decision)
requires_future_runner(decision)
```

or an equivalent small helper. The important part is that `ask`, `run`, and
future phases do not each invent their own interpretation.

### 2. Align CLI behavior with mode semantics

Review both main command paths:

```text
ask
run
```

They must not silently ignore `run_mode`.

Acceptable behavior examples:

```text
ask + off/log
  show or record the route decision and do not execute a workflow

ask + controlled
  execute current native workflow with AAO controls

ask + orchestrated before real orchestrated runner exists
  say clearly that orchestrated runtime is not implemented yet, or use an
  explicit fallback_controlled path if the user forced it

run + explicit workflow
  either document that explicit workflow means controlled native execution, or
  require/record a clear fallback reason
```

Do not let the CLI say "orchestrated" while actually doing an ordinary native
run with no marker.

### 3. Move business preview logic out of CLI

`__main__.py` should parse commands and dispatch work. It should not contain
business-specific preview building logic.

Move `_build_sales_cli_preview` or equivalent business preview logic into a
small dedicated module such as:

```text
src/orchestrator/sales_preview.py
```

Add tests for the moved helper. Keep the CLI wrapper thin.

### 4. Add a scheduler growth contract

Before Phase 10 and Phase 11, write down this rule in handoff notes and, if
needed, in the next phase specs:

```text
No new raw policy or recovery logic should be embedded directly in scheduler.py.
Scheduler may call policy/recovery/control helpers, but it should not become
the place where policy matrices, retry decisions, recovery hints, or failure
reason inference are implemented.
```

If a later phase must touch `scheduler.py`, the phase handoff must include:

```text
- scheduler.py line count before/after
- what responsibility was added
- why it could not live in a smaller helper
- whether any responsibility was moved out
```

### 5. Clarify `.claude/` project assets

Confirm the intended repository policy:

```text
.claude/phase-specs/       project assets, should be tracked
.claude/project-skills/    project assets, should be tracked
.claude/projects/          local session state, should not be tracked
.claude/settings*.json     local settings/secrets, should not be tracked
```

If `.gitignore` already expresses this, do not churn it. If it does not, fix it
minimally.

## Tests

Add or update focused tests:

```text
tests/test_task_router.py
tests/test_cli_output.py
tests/test_state_center.py
tests/test_sales_preview.py
```

Minimum behavior tests:

```text
small/default route does not trigger full workflow execution
off mode never executes workflow
log mode records/displays route without blocking
controlled mode is the only current fully executable mode
orchestrated mode is marked future_orchestrated unless explicitly falling back
explicit workflow run records/communicates controlled native execution
sales preview helper preserves previous output shape after moving out of CLI
```

If testing CLI execution directly is expensive, test the helper functions that
the CLI calls and explain any remaining manual check.

## Validation Commands

Run:

```text
PYTHONPATH=src python -m pytest -q tests/test_task_router.py tests/test_cli_output.py tests/test_state_center.py
PYTHONPATH=src python -m pytest -q
python -m compileall -q src tests
git diff --check
git status --short
```

On Windows, use the equivalent `py -m ...` commands if `python` is not the
right interpreter.

## Definition Of Done

Phase 9A is done only when:

```text
- off/log/controlled/orchestrated semantics are explicit in source
- ask/run behavior follows those semantics or documents an explicit fallback
- no CLI path silently pretends future orchestration exists
- business preview logic is no longer embedded directly in __main__.py
- scheduler.py did not receive new raw policy/recovery implementation
- .claude tracking policy is clear and minimally reflected in .gitignore
- targeted tests pass
- full pytest passes or any failure is unrelated and documented
- compileall passes
- git diff --check passes
- final handoff explains what was clarified, what was moved, and what remains
  for Phase 10/11/12
```

## Required Final Explanation To User

Explain this phase naturally, not as a bureaucratic checklist.

Make the point concrete:

```text
Before this phase, AAO knew labels like log/controlled/orchestrated.
After this phase, each label has behavior.

This is like labeling road lanes:
the small-task lane does not enter the heavy control highway,
the controlled lane enters the native AAO runtime,
and the orchestrated lane is clearly marked as a future bridge, not a fake road.
```

Also explain:

```text
what changed in ask/run behavior
what got moved out of __main__.py
why scheduler.py should not keep absorbing policy/recovery logic
what Phase 10 and Phase 11 can now build on safely
```
