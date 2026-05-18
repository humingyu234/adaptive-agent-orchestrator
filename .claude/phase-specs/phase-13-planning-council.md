# Phase 13 - Planning Council

## Goal

For complex tasks, create a reviewed plan before execution and require user
approval before the runner starts.

## Why This Phase Exists

Long AI tasks fail when the first plan is vague or wrong. Planning Council adds
a planning checkpoint before expensive execution.

## Non-Goals

- No council for small tasks.
- No forced multi-model call on every request.
- No uncontrolled cost increase.
- No autonomous execution before user approval.

## Allowed Files

```text
src/orchestrator/planning.py
src/orchestrator/control_models.py
src/orchestrator/__main__.py
src/orchestrator/report_writer.py
tests/test_planning_council.py
tests/test_cli_output.py
```

## Required Behavior

For large/orchestrated tasks:

```text
planner proposes
risk reviewer challenges
execution planner simplifies
AAO merges final plan
user confirms, edits, or rejects
runner executes only after approval
```

The final plan must include:

```text
objective
steps
risk notes
required evidence
human review gates
non-goals
```

## Required Tests

```text
test_planning_council_generates_final_plan
test_plan_contains_steps_risks_evidence_and_non_goals
test_user_can_edit_plan_before_execution
test_rejected_plan_does_not_execute
test_planning_is_not_used_for_small_tasks_by_default
```

## Commands

```bash
python -m pytest tests/test_planning_council.py tests/test_cli_output.py
python -m pytest
```

## Definition Of Done

- Complex tasks can produce a plan contract.
- User approval/edit/reject paths work.
- Planning output is recorded in audit metadata.
- Small tasks do not pay planning cost by default.

## Claude Code Instruction

Read `CLAUDE.md` and this file. Implement only Phase 13. Keep the council gated
to complex tasks and user approval.
