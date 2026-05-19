# Phase 12 - Claude Code Worker Bridge

## Goal

Let AAO delegate a bounded task to Claude Code as an external worker, then read
back the worker's result and evidence through files.

After this phase, the user should be able to keep talking to Claude Code as the
front-stage coding assistant, while AAO acts as the supervisor that creates the
work order, states the boundaries, and verifies the returned evidence.

Mental model:

```text
User talks to Claude Code naturally.
AAO writes the job packet.
Claude Code does the work.
AAO reads the result files.
AAO decides whether the work is evidenced, missing evidence, needs review, or failed.
```

This phase is not about replacing Claude Code. It is about making Claude Code's
work inspectable and auditable by AAO.

## Why This Phase Exists

Earlier phases made AAO stronger at control:

```text
Phase 8   shows runtime state
Phase 9   routes task size and run mode
Phase 10  enforces runtime policy
Phase 11  maps failures to bounded recovery decisions
```

But AAO still needs a practical worker path for the user's real daily workflow.
The user already uses Claude Code effectively. Phase 12 should connect that
workflow to AAO without fragile terminal automation.

Key distinction:

```text
Claude Code is the worker that may write code.
AAO is the control layer that decides whether the worker's claim is supported by evidence.
```

A worker saying "tests passed" is reported evidence. A captured `test_output.txt`
file is observed evidence.

## Preflight

Before editing, read:

```text
CLAUDE.md
.claude/phase-specs/phase-09a-runtime-mode-cleanup-contract.md
.claude/phase-specs/phase-10-runtime-policy-enforcement.md
.claude/phase-specs/phase-11-recovery-playbook.md
.claude/phase-specs/phase-12-claude-code-worker-bridge.md
.claude/project-skills/aao-scope-guard.md
.claude/project-skills/aao-boundary-test-designer.md
.claude/project-skills/aao-reviewer-mode.md
.claude/project-skills/aao-phase-handoff.md
.claude/project-skills/aao-tutor-explanation.md
```

Then inspect the current source:

```text
src/orchestrator/control_models.py
src/orchestrator/control_plane.py
src/orchestrator/evidence.py
src/orchestrator/failure_taxonomy.py
src/orchestrator/policy.py
src/orchestrator/recovery.py
src/orchestrator/scheduler.py
src/orchestrator/live_view.py
src/orchestrator/report_writer.py
src/orchestrator/__main__.py
tests/test_control_models.py
tests/test_evidence_pack.py
tests/test_control_plane.py
tests/test_control_plane_integration.py
tests/test_runtime_smoke.py
```

Run first:

```bash
git status --short
```

Name unrelated dirty files in the handoff. Do not use `git add .`.

## Non-Goals

- No terminal automation of Claude Code.
- No trying to control Claude Code internals.
- No bypassing Claude Code permission prompts.
- No Agent View clone.
- No LangGraph runner.
- No ECC integration in this phase. Phase 12A handles worker discipline pack.
- No Planning Council.
- No memory layer.
- No new model provider integration.
- No new dashboard.
- No broad scheduler rewrite.
- No pretending worker-reported evidence is observed evidence.
- No marking a worker task complete when required evidence is missing.

## Allowed Files

Prefer this write set:

```text
src/orchestrator/worker_protocol.py
src/orchestrator/workers/__init__.py
src/orchestrator/workers/claude_code.py
src/orchestrator/control_models.py
src/orchestrator/control_plane.py
src/orchestrator/evidence.py
src/orchestrator/failure_taxonomy.py
src/orchestrator/recovery.py
src/orchestrator/live_view.py
src/orchestrator/report_writer.py
src/orchestrator/__main__.py
tests/test_worker_protocol.py
tests/test_claude_code_worker_bridge.py
tests/test_control_plane.py
tests/test_evidence_pack.py
tests/test_live_view.py
tests/test_runtime_smoke.py
```

Only touch `scheduler.py` if source inspection proves that the bridge must be
called from a runtime path in this phase. If touched, keep the change minimal and
explain it in the handoff.

Do not edit unrelated docs, sales demos, provider configuration, or old phase
specs unless directly required.

## Core Contract

Create a file-based worker protocol. AAO must be able to create a task packet,
hand it to Claude Code, and later load the result and observed evidence.

Suggested packet root:

```text
.aao/tasks/<run_id>/<task_id>/
```

Suggested files:

```text
manifest.json
  machine-readable task metadata

task.md
  natural-language task for Claude Code

constraints.md
  allowed files, denied files, non-goals, risk notes, required commands

expected_evidence.md
  what files or command outputs AAO expects back

result.md
  worker-written summary, changed files, claims, risks, follow-up notes

observed/test_output.txt
  captured test output, if tests were required

observed/diff.patch
  captured diff, if code changes were required

observed/commands.jsonl
  optional command records if available

status.json
  machine-readable worker status written or loaded by AAO
```

The exact layout may differ, but it must preserve this separation:

```text
Task instructions       -> what the worker should do
Constraints             -> what the worker must not do
Expected evidence       -> what AAO will verify
Reported result         -> what the worker claims
Observed evidence       -> files AAO can inspect directly
```

## Required Models / Data Shape

If current `control_models.py` already has suitable models, extend them rather
than duplicating concepts.

At minimum, the implementation needs models or dataclasses that can represent:

```text
WorkerTaskPacket
  run_id
  task_id
  title/objective
  run_mode
  worker_kind = "claude_code"
  allowed_files
  denied_files
  required_checks
  expected_artifacts
  expected_evidence
  risk_level
  created_at

WorkerResultPacket
  run_id
  task_id
  status
  summary
  changed_files
  reported_checks
  observed_evidence_files
  missing_evidence
  risks
  raw_result_path

WorkerEvidenceStatus
  observed
  reported
  missing
  invalid
```

Do not let `result.md` alone prove success. `result.md` can explain the work,
but observed evidence must come from expected files such as `test_output.txt`,
`diff.patch`, or other explicitly required artifacts.

## Layer Boundary

Keep the responsibilities separate:

```text
worker_protocol.py
  owns packet file names, serialization, loading, validation, and schema shape

workers/claude_code.py
  owns Claude Code specific task rendering and result loading convenience methods

control_plane.py
  turns worker result + evidence status into control decisions

evidence.py
  classifies observed/reported/missing evidence and builds evidence packs

recovery.py
  receives missing-evidence or worker-failure records and decides bounded recovery

__main__.py
  exposes small CLI commands to create/read packets if needed
```

Do not put packet parsing and evidence verification directly into `__main__.py`.
Do not make `workers/claude_code.py` own policy, recovery, or evaluation logic.

## Required Behavior

AAO must be able to:

```text
1. Create a Claude Code task packet in .aao/tasks/<run_id>/<task_id>/.
2. Include allowed files, denied files, non-goals, required checks, and expected evidence.
3. Render a clear instruction that the user can paste into Claude Code or that Claude Code can read.
4. Load a completed result packet from disk.
5. Treat worker claims as reported evidence until observed files prove them.
6. Detect missing required evidence.
7. Detect result/status mismatch, such as status=success but no required test output.
8. Convert missing evidence or invalid worker output into FailureRecord / RecoveryDecision through existing ControlPlane paths.
9. Include worker packet/result/evidence summary in report output where practical.
10. Show worker packet status in live view where practical.
```

Minimum CLI support, if `__main__.py` is touched:

```text
python -m orchestrator worker create --task "..." --allowed src/orchestrator/foo.py --check "python -m pytest ..."
python -m orchestrator worker inspect .aao/tasks/<run_id>/<task_id>
```

CLI exact names may differ, but the commands should be thin wrappers over
`worker_protocol.py` and `workers/claude_code.py`.

## Claude Code Task Instruction Shape

Generated task instructions should be natural but explicit. They should include:

```text
Objective:
  what to accomplish

Allowed files:
  exact paths or path prefixes

Denied files:
  protected paths or explicitly forbidden areas

Required checks:
  commands or manual checks expected

Evidence to write back:
  result.md
  observed/test_output.txt if tests are run
  observed/diff.patch if code changed

Non-goals:
  what not to implement in this task

Handoff expectation:
  explain what changed, what was validated, what remains risky
```

Do not generate vague instructions such as "improve the project". Every task
packet should be concrete enough for a reviewer to know whether the worker went
off scope.

## Evidence Rules

Use these rules strictly:

```text
Observed evidence:
  files AAO reads directly, such as test_output.txt, diff.patch, status.json,
  command logs, generated reports, or structured artifacts.

Reported evidence:
  worker-written statements in result.md, such as "tests passed" or "I changed X".

Inferred evidence:
  AAO's own conclusion from observed files, such as "diff.patch exists, so code changed".
```

Required behavior:

```text
- Reported evidence can help explain a run but cannot satisfy required evidence alone.
- Missing observed evidence must produce a missing-evidence control result.
- A worker cannot self-approve its own result.
- Reviewer-style worker packets must be read-only unless explicitly allowed.
```

## Policy Integration

Task packets must carry enough policy context for the worker to avoid unsafe
work, and for AAO to judge violations after the fact.

Minimum policy fields:

```text
allowed_files
denied_files
protected_files
allowed_tools or allowed_actions if available
required_checks
risk_level
human_review_required
```

If a worker result reports or shows changes outside allowed files, AAO should
classify that as a policy violation, not as a normal successful result.

## Recovery Integration

Phase 12 should reuse Phase 11 recovery rather than inventing new recovery rules.

Examples:

```text
required test_output.txt missing
  -> FailureRecord: missing_evidence
  -> RecoveryDecision: request_evidence or needs_human_review

worker status says failed with rate limit
  -> FailureRecord origin=worker/provider, reason=rate_limit
  -> RecoveryDecision from recovery.py

worker changed denied file
  -> FailureRecord: policy violation
  -> RecoveryDecision: needs_human_review or fail

worker result malformed
  -> FailureRecord: invalid_worker_result / format_error
  -> RecoveryDecision: request_evidence or fail, depending on severity
```

Do not add a separate hidden recovery path inside the worker bridge.

## Run Mode Semantics

Respect Phase 9A:

```text
off
  may create/read packets manually, but does not enforce evidence decisions

log
  records missing evidence or policy concerns but does not block

controlled
  blocks completion when required evidence is missing or policy is violated

orchestrated
  can use the same controlled behavior for now; do not pretend full autonomous
  worker orchestration exists unless implemented
```

Tests must prove at least one difference between `log` and `controlled` for
missing evidence.

## Boundary Test Matrix

Required unit tests:

```text
test_task_packet_is_created_with_manifest_and_markdown_files
test_task_packet_includes_allowed_files_denied_files_and_non_goals
test_task_packet_includes_required_checks_and_expected_evidence
test_worker_result_is_loaded_from_result_file
test_worker_result_without_required_evidence_is_not_success
test_test_output_file_counts_as_observed_evidence
test_diff_patch_file_counts_as_observed_evidence_when_code_changes_are_expected
test_worker_claim_tests_passed_is_only_reported_without_test_output
test_malformed_status_json_is_classified_as_invalid_worker_result
test_result_changing_denied_file_creates_policy_violation
test_log_mode_records_missing_evidence_without_blocking
test_controlled_mode_blocks_missing_evidence
test_worker_packet_paths_are_sanitized_under_task_root
```

Required integration tests:

```text
test_control_plane_turns_missing_worker_evidence_into_recovery_decision
test_report_includes_worker_packet_and_evidence_summary
test_live_view_includes_worker_status_when_available
test_cli_can_create_and_inspect_worker_packet_if_cli_is_added
```

False-positive guards:

```text
- A result with all required observed evidence should not be blocked.
- A task that does not require code changes should not require diff.patch.
- A task that does not require tests should not require test_output.txt.
- Different task IDs must not read each other's evidence files.
```

## Validation Commands

Run targeted tests first:

```bash
PYTHONPATH=src python -m pytest -q tests/test_worker_protocol.py tests/test_claude_code_worker_bridge.py
PYTHONPATH=src python -m pytest -q tests/test_control_plane.py tests/test_evidence_pack.py tests/test_live_view.py
```

Then run:

```bash
PYTHONPATH=src python -m pytest -q
python -m compileall -q src tests
git diff --check
git status --short
```

On Windows, use equivalent `py -m ...` commands if that is the working
interpreter.

## Definition Of Done

Phase 12 is done only when:

```text
- worker_protocol.py owns the file-based packet contract
- workers/claude_code.py exists and stays thin
- AAO can create a task packet under .aao/tasks/<run_id>/<task_id>/
- AAO can load worker result files from that packet
- required evidence is verified from observed files, not trusted from result.md
- missing evidence cannot silently become completed in controlled mode
- worker-reported success without observed evidence is blocked or marked incomplete
- denied-file or protected-file violations are detected where practical
- recovery.py / ControlPlane handle missing worker evidence through existing recovery paths
- live view or report includes worker packet/evidence status where practical
- targeted tests pass
- full pytest passes or unrelated failures are documented
- compileall passes
- git diff --check passes
- final handoff names dirty files outside the phase scope
```

## Required Handoff

Use `.claude/project-skills/aao-phase-handoff.md`.

Include:

```text
current phase
phase goal
completed work
changed files
dirty files outside current phase scope
tests added or changed
exact test commands run
test result
reviewer result if used
known risks
unsupported worker automation features
deferred ideas
next recommended step
safe to proceed
recommended next commit slice
```

## Required Final Explanation To User

Explain Phase 12 naturally and concretely.

Use this mental model:

```text
Before Phase 12, Claude Code could tell you "I did the task" and AAO had to
trust the conversation.

After Phase 12, AAO gives Claude Code a work order, then checks the returned
files: result, test output, diff, and status. If the worker says "tests passed"
but no test output exists, AAO treats that as missing evidence instead of
pretending the task is complete.
```

Make clear:

```text
what a task packet is
what Claude Code writes back
what AAO verifies
what counts as observed evidence
what remains manual
why this does not bypass Claude Code permission prompts
what remains for Phase 12A ECC discipline pack
```

Do not oversell Phase 12 as fully autonomous Claude Code control. It is the
bridge that makes Claude Code work auditable.

## Claude Code Instruction

Read `CLAUDE.md` and this file. Implement only Phase 12. Build the file-based
Claude Code worker bridge, keep Claude Code as an external worker, and verify
observed evidence independently. Do not automate terminal sessions, bypass
permissions, add LangGraph, add ECC, add Planning Council, or implement memory in
this phase.