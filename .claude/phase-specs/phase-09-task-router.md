# Phase 9 - Task Router

## Goal

Add a deterministic Task Router that decides how much AAO should be involved in
a task.

This phase answers one question before execution starts:

```text
Should this task be left to Claude Code directly, logged lightly, controlled by
AAO, or routed toward a future orchestrated runner?
```

The router is a traffic light at the front door. It is not a planner, not a
worker, and not a new execution engine.

## Why This Phase Exists

AAO should not make simple work heavy.

The project needs a clean route between:

```text
small task  -> stay out of the way or only log
medium task -> use AAO control checks
large task  -> mark as orchestrated work, without pretending LangGraph exists yet
```

Without this phase, every task tends to look like a workflow problem. That is
the wrong shape. A control plane is valuable only if it knows when to engage.

## Non-Goals

- No Planning Council.
- No LangGraph.
- No Claude Code Worker Bridge.
- No new runner.
- No model call in the default router.
- No perfect classifier.
- No hidden execution of `orchestrated` mode before an orchestrated runner
  exists.
- No broad rewrite of `ask` or `run`.
- No attempt to answer small questions inside AAO.

## Important Terms

Keep these separate:

```text
task_size
  How large or risky the user's request is: small | medium | large.

run_mode
  How much AAO participates: off | log | controlled | orchestrated.

workflow routing
  Which existing YAML workflow to run, such as deep_research or
  customer_support_brief.
```

Phase 9 is about `task_size` and `run_mode`. Existing workflow routing may be
reused, but do not mix the concepts.

Example:

```text
"Explain what guardrails.py does"
  task_size: small
  run_mode: log or off
  workflow: none

"Review this PR and identify P0/P1/P2 risks"
  task_size: medium
  run_mode: controlled
  workflow: review/control workflow if available

"Implement Phase 12 worker bridge with tests and handoff"
  task_size: large
  run_mode: orchestrated
  workflow: future orchestrated runner, or explicit controlled fallback
```

## Allowed Files

Prefer this write set:

```text
src/orchestrator/task_router.py
src/orchestrator/control_models.py
src/orchestrator/state_center.py
src/orchestrator/__main__.py
src/orchestrator/cli_output.py
src/orchestrator/report_writer.py
tests/test_task_router.py
tests/test_cli_output.py
tests/test_live_view.py
tests/test_state_center.py
```

Only touch other files if the implementation proves it is necessary. Explain
the reason in the handoff.

Do not edit:

```text
.env
outputs/
tmp/
.venv/
workflow YAML files
agents
llm providers
ControlPlane internals
Scheduler internals beyond passing/recording run_mode
```

## Required Router Contract

Create `src/orchestrator/task_router.py`.

Suggested public model:

```text
TaskRouteDecision
  task_size: small | medium | large
  run_mode: off | log | controlled | orchestrated
  risk_level: low | medium | high
  task_type: question | explanation | review | bugfix | feature | refactor |
             research | ops | phase_work | project | unknown
  confidence: low | medium | high
  reasons: list[str]
  signals: dict[str, object]
  user_override: bool
  workflow_hint: str | None
  runtime_support: native | route_only | fallback_controlled | future_orchestrated
```

Suggested functions:

```text
route_task(
    query: str,
    *,
    explicit_mode: RunMode | None = None,
    explicit_workflow: str | None = None,
) -> TaskRouteDecision

render_route_decision(decision: TaskRouteDecision) -> str
```

Rules:

- The router must be deterministic by default.
- The router must not call an LLM.
- The router must be pure enough to test without filesystem, network, runner,
  or model setup.
- The router must return reasons, not only a label.
- The router must prefer safe escalation when risk is high.
- The router must not silently pretend a future runner exists.

## Default Routing Policy

Use this default mapping:

```text
small  -> log
medium -> controlled
large  -> orchestrated
```

`off` is allowed only as an explicit user override.

Why:

- If the user invoked AAO, default small work can still be logged lightly.
- If the user wants zero AAO involvement, they can choose `--mode off`.
- This avoids making every small question enter a full workflow.

## User Override

User override always wins:

```text
--mode off
--mode log
--mode controlled
--mode orchestrated
```

But winning does not mean lying.

If the user chooses `--mode orchestrated` before an orchestrated runner exists,
the decision may say:

```text
run_mode: orchestrated
runtime_support: future_orchestrated
```

If the CLI falls back to the current native workflow, record that explicitly:

```text
runtime_support: fallback_controlled
reason: orchestrated runner is not implemented yet
```

Do not silently mark a native run as fully orchestrated.

## Size And Risk Signals

The first implementation should use explicit, inspectable rules.

Small signals:

```text
explain / what is / translate / summarize this concept
single direct question
no file path
no edit intent
no test requirement
no deployment / migration / secret / destructive operation
```

Medium signals:

```text
review
bugfix
add or update tests
one feature slice
mentions one to three files
PR / issue / code review
refactor with bounded scope
asks for implementation but not a full project
```

Large signals:

```text
phase work
multi-step project
end-to-end implementation
architecture migration
many files or modules
parallel agents / multiple workers
release / deployment / production change
long-running task
resume / checkpoint / audit / full workflow
```

High-risk signals:

```text
delete
remove recursively
rm -rf
reset
force push
migrate
deploy
release
production
database
credentials
secret
.env
payment
auth
security
permission
protected file
```

High risk must escalate at least to `controlled`, even if the task text looks
small.

## File Mention Signals

Extract simple file/path hints from the query.

Suggested rules:

```text
0 files mentioned
  size is determined by intent and risk words.

1-3 files mentioned
  usually medium if edit/review/test words are present.

4+ files or multiple directories mentioned
  usually large, unless the request is read-only explanation.
```

Do not require a perfect parser. A simple regex for backticked paths and common
path-like strings is enough.

## CLI Integration

Add a route-only command:

```bash
python -m orchestrator route --query "explain guardrails.py"
python -m orchestrator route --query "implement Phase 12 worker bridge" --format text
python -m orchestrator route --query "deploy database migration" --mode controlled
```

The route command must:

- not run Scheduler
- not call LLM
- print the route decision in JSON or text
- include reasons
- include whether the mode was user-overridden

Add `--mode` to `ask` and `run`.

For `run`:

- explicit workflow means execution is still workflow-based
- default mode should be `controlled` unless `--mode` is provided
- record the selected run mode and route decision

For `ask`:

- call the router before workflow selection
- if the route is `log` or `off`, do not run a heavy workflow by default
- print a clear route decision instead of pretending AAO answered the task
- if a user wants the old behavior, provide an explicit flag such as
  `--force-run` or equivalent and test it
- if the route is `controlled`, use the existing native workflow path
- if the route is `orchestrated` before an orchestrated runner exists, either:
  - stop with a clear "orchestrated runner not implemented yet" route result, or
  - require explicit fallback to controlled mode

Do not silently run a large task as controlled while labeling it orchestrated.

## Metadata And Audit Recording

The route decision must be persisted when a run is actually created.

At minimum record:

```text
run_mode
task_size
risk_level
task_type
reasons
user_override
runtime_support
router_version
```

Acceptable places:

```text
StateCenter.metadata.route_decision
execution_trace event: route_decision
run payload / report metadata
```

Preferred trace event:

```json
{
  "event": "route_decision",
  "task_size": "medium",
  "run_mode": "controlled",
  "risk_level": "medium",
  "task_type": "review",
  "reasons": ["review intent", "file path mentioned"],
  "user_override": false,
  "runtime_support": "native",
  "timestamp": "..."
}
```

If adding metadata fields, keep `StateCenter.load_from(...)` backward-compatible
with older state files.

## Relationship To Existing Workflow Routing

`_resolve_workflow_for_ask(...)` currently chooses a workflow. Phase 9 should
not simply rename that function.

Target separation:

```text
route_task(...)
  decides AAO involvement: log / controlled / orchestrated

_resolve_workflow_for_ask(...)
  chooses a YAML workflow only when the selected route actually needs a workflow
```

Do not let the LLM workflow router become the Task Router. The Task Router must
stay deterministic by default.

Existing LLM workflow routing may remain for choosing a workflow after the task
has already been routed into `controlled`, but it must not be the only route
decision path.

## Required Tests

Add `tests/test_task_router.py`.

Router unit tests:

```text
test_simple_question_routes_to_small_log
test_explicit_off_override_wins
test_review_with_file_routes_to_medium_controlled
test_bugfix_with_tests_routes_to_medium_controlled
test_phase_work_routes_to_large_orchestrated
test_project_level_request_routes_to_large_orchestrated
test_high_risk_words_escalate_to_controlled
test_destructive_word_escalates_even_if_query_is_short
test_many_files_escalates_to_large
test_read_only_many_files_can_stay_medium_or_log_if_no_edit_intent
test_ambiguous_task_defaults_to_controlled_or_log_with_low_confidence
test_route_decision_is_serializable
test_route_decision_includes_reasons
test_router_does_not_call_llm_or_scheduler
```

CLI tests:

```text
test_route_command_prints_decision_without_running_scheduler
test_route_command_honors_mode_override
test_ask_records_route_decision_for_controlled_run
test_ask_does_not_run_heavy_workflow_for_log_route
test_run_accepts_mode_and_records_run_mode
test_orchestrated_route_does_not_fake_langgraph_support
```

State/report tests:

```text
test_state_metadata_loads_without_route_decision_for_old_state
test_route_decision_trace_event_is_written
test_report_or_payload_includes_route_decision_when_run_exists
```

Boundary tests:

```text
test_small_question_with_secret_keyword_escalates
test_user_override_can_force_controlled_for_small_task
test_user_override_can_force_log_for_medium_task
test_invalid_mode_is_rejected_by_cli
```

Use contract-based test names. Do not rely only on final printed text; include
at least one test that proves the scheduler is not called for route-only/log
paths.

## Required Commands

Run targeted tests first:

```bash
python -m pytest tests/test_task_router.py -q
python -m pytest tests/test_cli_output.py -q
python -m pytest tests/test_live_view.py -q
```

Then run broader checks:

```bash
python -m pytest -q
python -m compileall -q src tests
git diff --check
git status --short
```

If the full suite fails for an environment reason, report the exact command and
error. Do not claim the phase is done.

## Definition Of Done

Phase 9 is done only when:

- `task_router.py` exists and is deterministic/tested.
- The router returns task size, run mode, risk, type, reasons, and runtime
  support.
- User `--mode` override wins and is tested.
- Simple/log routes do not accidentally start heavy workflow execution.
- Controlled routes still use the existing native workflow path.
- Orchestrated routes are not faked before an orchestrated runner exists.
- Route decisions are persisted when a run is created.
- Existing `ask`, `run`, `status`, and `watch` behavior is not broken.
- Targeted tests pass.
- Full tests pass or failures are precisely explained.
- Final handoff includes examples of small, medium, and large routing.

## Reviewer Checklist

The reviewer must check:

```text
Can the router be tested without model/network/filesystem?
Does any route path silently call LLM?
Does any small/log path still start Scheduler?
Does user override truly win?
Does high risk escalate?
Does large/orchestrated avoid pretending LangGraph exists?
Is run_mode recorded in state/report/live payload?
Are old state files still loadable?
Would the tests still pass if the implementation only guessed labels?
```

P0 issues:

```text
LLM call in default router
small/log path still starts heavy workflow without explicit force
orchestrated label silently uses native runner as if it were real orchestration
route decision is not persisted for actual runs
existing run/status/watch commands break
```

## Required Final Explanation To The User

Explain Phase 9 naturally and concretely.

Use this intuition:

```text
Phase 9 is AAO's front-door traffic light.

Green / small:
  Claude Code can handle it directly; AAO may only log it.

Yellow / medium:
  Use AAO control checks because code, tests, review, or evidence matters.

Red / large:
  This needs a real workflow/orchestration plan. Mark it honestly and do not
  pretend the future LangGraph runner already exists.
```

The explanation must include:

- what signals the router looks at
- why small tasks should not become heavy workflows
- how user override works
- where the decision is recorded
- what is still deferred to Phase 10/12/15

## Claude Code Instruction

Read `CLAUDE.md`, `.claude/project-skills/aao-core-builder.md`,
`.claude/project-skills/aao-boundary-test-designer.md`, and this file.

Implement only Phase 9.

Keep it deterministic. Keep it small. Do not add Planning Council, LangGraph,
Claude Code Worker Bridge, or any new model call.
