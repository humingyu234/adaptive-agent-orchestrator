# Phase 14 - Memory Layer

## Goal

Give AAO lightweight project memory so it can reuse decisions, constraints, and
failure lessons without adding a heavy memory system.

## Why This Phase Exists

The user needs continuity across sessions and runs. AAO should remember project
constraints and previous failure lessons, but it should not pretend memory is
observed truth.

## Non-Goals

- No vector database.
- No semantic retrieval system first.
- No hidden memory that cannot be inspected.
- No trusting memory without source type.

## Allowed Files

```text
src/orchestrator/memory.py
src/orchestrator/control_models.py
src/orchestrator/report_writer.py
tests/test_memory.py
```

## Required Behavior

Use local file memory:

```text
.aao/memory/project.md
.aao/memory/decisions/*.md
.aao/memory/failures/*.json
.aao/memory/runs/*.json
```

Memory types:

```text
run memory
project constraints
architecture decisions
failure lessons
review decisions
```

Each memory item must carry a source type:

```text
observed
reported
inferred
```

## Required Tests

```text
test_memory_item_requires_source_type
test_project_memory_can_be_loaded
test_failure_lesson_can_be_recorded_and_reused
test_memory_does_not_convert_reported_to_observed
test_missing_memory_files_do_not_crash
```

## Commands

```bash
python -m pytest tests/test_memory.py
python -m pytest
```

## Definition Of Done

- Memory is inspectable local files.
- Memory source type is explicit.
- AAO can load project constraints and prior failure lessons.
- Memory is referenced honestly in audit/report output.

## Claude Code Instruction

Read `CLAUDE.md` and this file. Implement only lightweight local memory. Do not
add vector databases or hidden state.
