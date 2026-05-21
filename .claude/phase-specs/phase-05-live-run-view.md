# Phase 5 - Live Run View

Goal: Expose task progress in a form Claude Code and humans can read.

## Allowed Files

```text
src/orchestrator/live_view.py
src/orchestrator/__main__.py
tests/test_live_view.py
tests/test_cli_output.py
```

## Core Functions

```text
build_live_view(state, result=None) -> dict
render_live_view(view) -> str
```

CLI commands may be added after the pure functions exist:

```text
python -m orchestrator status --task-id <task_id>
python -m orchestrator watch --task-id <task_id>
```

## View Should Include

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

## Required Tests

- completed run renders completed
- failed run shows failure reason
- needs-human-review run shows human review waiting state
- missing optional paths do not crash

## Commands

```bash
python -m pytest tests/test_live_view.py
python -m pytest tests/test_cli_output.py
python -m pytest
```
