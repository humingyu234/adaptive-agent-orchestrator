# Phase 12A - ECC Integration Pack

## Goal

Use ECC/Everything Claude Code ideas to make Claude Code workers more
disciplined without making ECC the AAO core.

## Why This Phase Exists

AAO needs reliable worker behavior. ECC-style commands, hooks, and role rules
can improve Claude Code execution discipline, while AAO remains responsible for
control, evidence, policy, and audit.

## Non-Goals

- Do not copy a large external framework blindly.
- Do not make AAO core tests depend on ECC.
- Do not replace ControlPlane with ECC.
- Do not add external dependencies unless explicitly justified.

## Allowed Files

```text
CLAUDE.md
.claude/commands/*
.claude/hooks/*
.claude/agents/*
src/orchestrator/workers/claude_code.py
tests/test_claude_code_worker_bridge.py
```

If `.claude/` is ignored and these files should become project assets, ask the
user before changing `.gitignore`.

## Required Behavior

Create an AAO Claude Code worker profile:

```text
read task packet
state plan before editing
stay within allowed files
run required checks
write result.md
write observed evidence files
report remaining risks
do not self-approve
```

Optional hooks may remind the worker to write evidence, but AAO must still
verify evidence independently.

## Required Tests

Tests should focus on AAO reading and validating the worker output, not on
Claude Code internals:

```text
test_worker_profile_requires_result_file
test_worker_profile_requires_expected_evidence
test_missing_worker_evidence_blocks_success
```

## Commands

```bash
python -m pytest tests/test_claude_code_worker_bridge.py
python -m pytest
```

## Definition Of Done

- There is a clear Claude Code worker profile.
- Worker instructions are compatible with AAO task packets.
- AAO still verifies evidence independently.
- No large ECC dependency is introduced.

## Claude Code Instruction

Read `CLAUDE.md` and this file. Implement only the AAO worker discipline pack.
Do not turn ECC into the AAO control layer.
