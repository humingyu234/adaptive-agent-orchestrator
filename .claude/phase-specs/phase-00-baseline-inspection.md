# Phase 0 - Baseline Inspection

Goal: Inspect the current codebase without editing any files. Understand what
exists before making changes.

## Instructions

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

## Required Output

- current dirty files
- current test command and result
- current scheduler responsibilities
- existing control capabilities
- missing control capabilities

No code edits in this phase.
