# Phase 3 - Scheduler Uses ControlPlane

Goal: Gradually route native runtime decisions through ControlPlane without
changing external behavior.

## Allowed Files

```text
src/orchestrator/scheduler.py
tests/test_runtime_smoke.py
tests/test_control_plane_integration.py
```

## Rules

- Keep existing CLI behavior compatible.
- Keep existing workflow YAML format compatible.
- Keep existing agent interface compatible.
- Keep existing report fields compatible.
- Any new report/evidence fields must be backward-compatible.
- Preserve human review pause behavior.
- Preserve guardrail failure behavior.
- Preserve failure classification trace event.

## Implementation Direction

```text
Scheduler.__init__ creates self.control_plane
existing evaluation paths begin delegating to ControlPlane
existing failure classification begins delegating to ControlPlane
old private methods may remain as compatibility wrappers
```

## Required Tests

- standard workflow still completes
- human-review workflow still pauses
- guardrail violation still fails with structured trace
- failure classified event still exists

## Commands

```bash
python -m pytest tests/test_runtime_smoke.py
python -m pytest tests/test_control_plane_integration.py
python -m pytest
```
