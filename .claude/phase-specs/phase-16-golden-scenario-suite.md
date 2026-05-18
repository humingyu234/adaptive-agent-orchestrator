# Phase 16 - Golden Scenario Suite

## Goal

Prove AAO's control layer with fixed scenarios that can be rerun after every
change.

## Why This Phase Exists

AAO's value is not that it has many architecture nouns. Its value is that it
blocks, pauses, retries, classifies, and audits the right things in known
failure scenarios.

## Non-Goals

- No huge benchmark suite.
- No flaky live LLM dependency for the golden path.
- No performance benchmark unless deterministic and cheap.

## Allowed Files

```text
tests/golden/
tests/test_golden_scenarios.py
examples/golden/
src/orchestrator/testing.py
```

## Required Scenarios

At least:

```text
normal completion
test failure
missing evidence
guardrail block
human review requested
human review approved
human review rejected
repeated tool call
protected file change
reviewer tries to write
dangerous shell command
known failure category uses explicit propagation
small task route
medium task route
large task route
planner edited by user
runner interrupted and resumed
policy deny
recovery retry
regression compare
audit report generated
```

## Required Tests

```text
test_golden_normal_completion
test_golden_missing_evidence_blocks_success
test_golden_protected_file_requires_review
test_golden_recovery_retry_is_bounded
test_golden_known_failure_category_does_not_use_infer_fallback
test_golden_audit_report_generated
```

## Commands

```bash
python -m pytest tests/golden tests/test_golden_scenarios.py
python -m pytest
```

## Definition Of Done

- Golden suite is deterministic.
- It does not require live LLM calls by default.
- It proves the main control promises.
- It includes at least one anti-false-green test that proves the runtime path,
  not only the final output value.
- It is documented enough for the demo/release phase.

## Claude Code Instruction

Read `CLAUDE.md` and this file. Build the golden suite as proof of AAO control
behavior. Keep it deterministic and cheap.
