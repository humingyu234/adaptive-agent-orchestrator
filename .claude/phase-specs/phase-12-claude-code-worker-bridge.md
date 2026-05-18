# Phase 12 - Claude Code Worker Bridge

## Goal

Make AAO useful with the user's real daily workflow: Claude Code as a worker
that executes task packets and returns evidence.

## Why This Phase Exists

The user wants to talk to Claude Code naturally while AAO supervises evidence,
policy, failure, and audit. AAO should not require replacing Claude Code.

## Non-Goals

- No attempt to control Claude Code internals.
- No fragile terminal automation first.
- No Agent View clone.
- No LangGraph.

## Allowed Files

```text
src/orchestrator/workers/claude_code.py
src/orchestrator/worker_protocol.py
src/orchestrator/evidence.py
src/orchestrator/report_writer.py
src/orchestrator/__main__.py
tests/test_worker_protocol.py
tests/test_claude_code_worker_bridge.py
```

## Required Behavior

Create a file-based task packet protocol:

```text
.aao/tasks/<run_id>/task.md
.aao/tasks/<run_id>/constraints.md
.aao/tasks/<run_id>/expected_evidence.md
.aao/tasks/<run_id>/result.md
.aao/tasks/<run_id>/test_output.txt
.aao/tasks/<run_id>/diff.patch
```

AAO should be able to:

```text
create task packet
state allowed files and checks
state evidence requirements
read worker result
verify observed evidence
classify failures
generate audit report
```

Claude Code worker should be treated as an external worker until evidence is
read back from files.

## Required Tests

```text
test_task_packet_is_created
test_task_packet_includes_constraints_and_evidence_requirements
test_worker_result_is_loaded
test_missing_required_evidence_is_detected
test_test_output_file_counts_as_observed_evidence
test_diff_patch_file_counts_as_observed_evidence_when_present
```

## Commands

```bash
python -m pytest tests/test_worker_protocol.py tests/test_claude_code_worker_bridge.py
python -m pytest
```

## Definition Of Done

- AAO can create and read task packets.
- Evidence is not trusted unless it is observed in the expected files.
- The bridge does not require Claude Code internals.
- Targeted and full tests pass or failures are explained.
- Final explanation shows how this lets the user keep using Claude Code while
  AAO supervises.

## Claude Code Instruction

Read `CLAUDE.md` and this file. Implement only the file-based bridge. Do not
automate terminal sessions or add LangGraph.
