# Phase 2 - ControlPlane Facade

Goal: Create one runner-independent control entry point that wraps existing
evaluator, guardrail, and failure taxonomy functionality.

## Allowed Files

```text
src/orchestrator/control_plane.py
tests/test_control_plane.py
```

## Allowed Imports

- `Evaluator`
- `GuardrailManager`
- `build_default_guardrail_manager`
- `GuardrailViolation`
- `failure_taxonomy`
- `control_models`
- `models`

## Forbidden Imports

- `Scheduler`
- `LangGraph`
- CLI modules
- any runner

## Implement

```text
ControlPlane.evaluate_output(...)
ControlPlane.guard_input(...)
ControlPlane.guard_output(...)
ControlPlane.classify_failure(...)
ControlPlane.make_decision(...)
```

## Required Tests

- valid output produces a continue decision
- evaluator failure produces a non-continue decision
- input guardrail violation produces fail + guardrail category
- output guardrail violation produces fail + guardrail category
- failure classification returns a structured failure record/category

## Commands

```bash
python -m pytest tests/test_control_plane.py
python -m pytest
```

Do not integrate with `scheduler.py` yet unless the user explicitly asks.
