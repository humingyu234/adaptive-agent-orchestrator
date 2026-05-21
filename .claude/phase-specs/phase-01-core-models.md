# Phase 1 - Core Models

Goal: Add the shared contract language without touching runtime behavior.

## Allowed Files

```text
src/orchestrator/control_models.py
tests/test_control_models.py
```

## Implement

- `TaskSize`
- `RunMode`
- `ControlAction`
- `ControlDecision`
- `WorkerTask`
- `WorkerResult`
- `EvidencePack`

## Required Tests

- valid default `ControlDecision` can represent `continue`
- failed `ControlDecision` can include a failure category
- `WorkerTask` can record allowed files and required checks
- `EvidencePack` can record commands and test results
- all models are serializable with Pydantic/model dump

## Commands

```bash
python -m pytest tests/test_control_models.py
python -m pytest
```

Do not modify `scheduler.py` in this phase.
