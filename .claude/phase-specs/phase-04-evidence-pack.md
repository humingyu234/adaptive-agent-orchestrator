# Phase 4 - EvidencePack

Goal: Make runtime evidence explicit without inventing evidence that is not
captured.

## Allowed Files

```text
src/orchestrator/evidence.py
src/orchestrator/scheduler.py
src/orchestrator/report_writer.py
tests/test_evidence_pack.py
```

## Start With Evidence the Current Runtime Really Has

- task id
- step/agent name
- input view summary
- output summary
- status
- duration
- evaluation result
- failure reason
- report path

## Do Not Pretend to Capture

- git diff
- command output
- test output
- file changes

unless the implementation actually captures them.

## Required Tests

- successful step can produce evidence
- failed step records error/failure reason
- missing commands/files do not crash serialization
- evidence can be written to JSON

## Commands

```bash
python -m pytest tests/test_evidence_pack.py
python -m pytest
```
