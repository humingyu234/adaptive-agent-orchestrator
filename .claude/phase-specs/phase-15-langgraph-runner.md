# Phase 15 - LangGraph Runner

## Goal

Add LangGraph as an optional runner for complex workflows with DAGs,
checkpoint, resume, branching, parallel steps, and human interrupt.

## Why This Phase Exists

AAO should not reimplement mature workflow execution machinery. LangGraph can
run complex flows while AAO stays responsible for control decisions, evidence,
policy, and audit.

## Non-Goals

- Do not replace ControlPlane.
- Do not replace NativeRunner for simple/medium tasks.
- Do not migrate the entire project to LangGraph.
- Do not make LangGraph required for core tests.

## Allowed Files

```text
src/orchestrator/runners/langgraph_runner.py
src/orchestrator/runners/__init__.py
src/orchestrator/control_plane.py
src/orchestrator/evidence.py
tests/test_langgraph_runner.py
tests/test_control_plane_integration.py
```

If adding the dependency is required, justify it and keep it optional where
possible.

## Required Behavior

LangGraphRunner must preserve AAO contracts:

```text
same ControlPlane decisions
same EvidencePack contract
same Audit Report contract
same policy/recovery path
```

Use only in orchestrated mode unless the user overrides.

## Required Tests

```text
test_langgraph_runner_executes_simple_workflow
test_langgraph_runner_calls_control_plane_after_node
test_langgraph_runner_records_evidence
test_langgraph_runner_can_resume_or_checkpoint_basic_state
test_native_runner_still_works_without_langgraph
```

## Commands

```bash
python -m pytest tests/test_langgraph_runner.py tests/test_control_plane_integration.py
python -m pytest
```

## Definition Of Done

- LangGraph is optional runner infrastructure.
- NativeRunner still works.
- ControlPlane remains the decision center.
- At least one complex demo workflow runs through LangGraphRunner.

## Claude Code Instruction

Read `CLAUDE.md` and this file. Implement LangGraph as a runner adapter only.
Do not make it the AAO brain.
