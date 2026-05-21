# Phase 7 - Final Integration Gate

Goal: Prove AAO Core behaves as one system, not scattered helpers.

## Files

Add or update:

```text
tests/test_control_plane_integration.py
```

## Required Scenarios

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

## Commands

```bash
python -m pytest
```

## Required Output

- total tests run
- passed/failed/skipped
- changed files
- remaining risks
- next recommended phase
