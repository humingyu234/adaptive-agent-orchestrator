# Phase 18 - Real Claude Code Worker Bridge

## Goal

Turn the existing AAO control chain into a real daily-use workflow by launching a
real Claude Code worker process from AAO, giving it a bounded task packet, and
then verifying the returned observed evidence before AAO marks the task complete.

This phase exists because packet creation, fake workers, demos, and golden
scenarios prove the control logic, but they do not prove the original blueprint:

```text
user task
  -> route
  -> planning / approval
  -> real worker executes
  -> observed evidence collected
  -> ControlPlane decides pass / retry / review / fail
  -> audit report
```

Phase 18 is the hard landing gate. If `--worker-mode claude-code` still does not
launch a real worker process, the blueprint is not complete.

## Current Reality This Phase Must Fix

The project may already have these pieces:

```text
worker_protocol.py      creates task packets
workers/claude_code.py  renders Claude Code instructions and loads results
planning.py             creates or validates plans
control_plane.py        evaluates evidence, policy, guardrails, and recovery
audit/report modules    summarize the run
```

But the missing link is:

```text
AAO starts a real Claude Code process
  -> passes the task packet or rendered task prompt
  -> waits for Claude Code to finish
  -> captures transcript / exit code / artifacts
  -> runs evidence verification
```

Do not treat `fake` or `packet` worker modes as completion for this phase.

## Preflight

Before editing, read:

```text
CLAUDE.md
.claude/phase-specs/phase-12-claude-code-worker-bridge.md
.claude/phase-specs/phase-13-planning-council.md
.claude/phase-specs/phase-16-golden-scenario-suite.md
.claude/phase-specs/phase-17-demo-readme-release.md
.claude/project-skills/aao-scope-guard.md
.claude/project-skills/aao-boundary-test-designer.md
.claude/project-skills/aao-reviewer-mode.md
.claude/project-skills/aao-phase-handoff.md
```

Then inspect the real current source paths. Do not assume module names from this
spec if the implementation already evolved:

```text
src/orchestrator/__main__.py
src/orchestrator/scheduler.py
src/orchestrator/planning.py
src/orchestrator/worker_protocol.py
src/orchestrator/workers/claude_code.py
src/orchestrator/control_plane.py
src/orchestrator/evidence.py
src/orchestrator/report_writer.py
tests/
```

Run first:

```bash
git status --short
```

Name unrelated dirty files in the handoff. Do not use `git add .`.

## Non-Goals

- No fake worker counted as real completion.
- No packet-only worker counted as real completion.
- No bypassing Claude Code permission prompts.
- No hard-coded API keys.
- No new LLM provider setup unless source inspection proves the existing command
  path cannot run without it.
- No broad scheduler rewrite unless the bridge cannot be integrated otherwise.
- No LangGraph rewrite in this phase.
- No multi-worker parallel execution yet.
- No full multi-model Planning Council redesign yet.
- No new dashboard.
- No replacing Claude Code with a homegrown code agent.

## Required Command Semantics

`--worker-mode claude-code` must mean one thing:

```text
AAO will try to launch a real Claude Code worker process.
```

It must not silently fall back to `fake`, `packet`, or a mock result.

Required behavior:

```text
--worker-mode fake
  may use deterministic fake files for tests and demos.

--worker-mode packet
  may create a task packet for manual execution.

--worker-mode claude-code
  must launch a configured Claude Code command, wait for completion, and verify
  returned evidence. If the command is missing or cannot run, fail clearly.
```

If the command cannot be found, return a structured failure such as:

```text
origin=worker
category=WORKER_ERROR or PROVIDER_ERROR, depending on existing taxonomy
reason=claude_code_command_unavailable
recovery_hint=configure_worker_command
```

Do not mark the task completed.

## Worker Command Configuration

The bridge must be command-configurable because local Claude Code setups vary
between Windows, WSL, shells, local proxies, and model backends.

Use safe subprocess invocation:

```text
no shell=True
command parsed as argv list
cwd = project root
timeout configured
stdout/stderr captured to observed files
environment allowlist or documented pass-through
```

Suggested configuration names:

```text
AAO_CLAUDE_CODE_COMMAND
AAO_CLAUDE_CODE_TIMEOUT_SECONDS
AAO_CLAUDE_CODE_PROMPT_MODE = stdin | file
```

The default command may be a best-effort local `claude` invocation, but the code
must not depend on one exact machine-specific launcher. Tests should use a fake
subprocess command, while the manual smoke test must use the user's real local
Claude Code command.

Do not require the user to paste model API keys into AAO. Claude Code should use
its own existing local authentication/configuration. AAO only needs to know how
to launch the worker command.

## Real Worker Flow

Implement the path as a clear adapter, not scattered terminal logic.

Recommended shape:

```text
run_claude_code_worker(packet, config) -> WorkerRunResult
```

It should:

```text
1. Render the packet into a strict Claude Code task prompt.
2. Write the prompt into the task directory for auditability.
3. Launch the configured Claude Code command.
4. Pass the prompt by stdin or by a prompt file, according to config.
5. Capture stdout/stderr/transcript into observed files.
6. Wait with timeout.
7. Load worker result/status/evidence files from the task directory.
8. Build WorkerResultPacket.
9. Return enough data for ControlPlane/evidence/audit to decide.
```

Observed files should include, where practical:

```text
observed/worker_stdout.txt
observed/worker_stderr.txt
observed/worker_exit.json
observed/test_output.txt
observed/diff.patch
result.md
status.json
```

If Claude Code exits successfully but does not produce required evidence, AAO
must treat the run as missing evidence, not success.

## Prompt Contract For Claude Code Worker

The task prompt must be strict enough that a reviewer can tell whether the worker
went off scope.

It should include:

```text
Objective
Allowed files
Denied/protected files
Required checks
Expected evidence files
Non-goals
How to write result.md
How to write status.json
How to capture test output
How to include diff.patch
```

The prompt must tell the worker:

```text
- Do not edit files outside the allowed set.
- Do not claim tests passed unless the test output is written to the expected file.
- If blocked by permissions, missing dependencies, command failure, or ambiguity,
  write a failed status and explain the blocker.
- Do not self-approve the task.
```

## Integration With Ask Path

The user-facing command must have an end-to-end path, not just helper functions.

The exact CLI flags may follow existing style, but the behavior must be possible:

```bash
python -m orchestrator ask "make a tiny bounded code change" \
  --approve \
  --worker-mode claude-code
```

Expected path:

```text
ask
  -> route task
  -> plan or select execution path
  -> create WorkerTaskPacket
  -> launch real Claude Code worker
  -> collect observed evidence
  -> ControlPlane checks policy/evidence/guardrails
  -> recovery decision if needed
  -> audit/report output
```

If current implementation has a MainlineExecutor or equivalent orchestrated path,
wire the bridge there. Do not leave the real bridge reachable only through a
private helper or standalone test.

## ControlPlane Requirements

AAO must stay the judge. Claude Code is the worker.

Required decisions:

```text
worker command unavailable
  -> clear failure, not fake fallback

worker exits nonzero
  -> worker failure with captured stderr/stdout

worker claims success but missing required evidence
  -> missing evidence, not success

worker changes protected/denied files
  -> policy violation / human review

required test output contains failure
  -> test failure / recovery decision

all evidence present and checks pass
  -> eligible for completion
```

The bridge must feed existing ControlPlane/evidence/recovery paths. Do not add a
hidden second decision system inside `workers/claude_code.py`.

## Test Plan

Unit tests must not require a real Claude Code install. Use a fake subprocess
command/script for deterministic tests.

Required tests:

```text
test_claude_code_mode_does_not_fallback_to_fake_when_command_missing
test_worker_command_is_invoked_with_project_root_cwd
test_worker_prompt_contains_allowed_denied_files_and_required_checks
test_worker_stdout_stderr_and_exit_code_are_captured_as_observed_evidence
test_success_exit_without_required_evidence_is_not_completed
test_nonzero_exit_creates_worker_failure
test_timeout_creates_worker_timeout_failure
test_denied_file_change_is_policy_violation
test_failing_test_output_blocks_or_requires_review
test_valid_worker_artifacts_pass_control_plane
```

Integration tests:

```text
test_ask_with_fake_subprocess_worker_runs_plan_execute_evidence_audit_chain
test_ask_claude_code_mode_command_missing_fails_clearly
test_report_includes_worker_command_status_and_evidence_paths
```

False-positive guards:

```text
- A docs-only task should not require diff.patch unless code changes are expected.
- A task with no required tests should not require test_output.txt.
- A worker failure should not be reported as policy violation unless policy was
  actually violated.
- Fake subprocess tests must not depend on the real user's Claude Code login.
```

## Manual Real Smoke Test

The phase is not fully accepted until one real manual smoke test is attempted
with the user's actual Claude Code setup.

Use a harmless bounded task, for example:

```text
Create or update a tiny scratch/demo file under an explicitly allowed path, run
one small check, and write result.md/status.json/observed files.
```

The handoff must include:

```text
exact command used
worker command config used
task packet path
result.md path
observed evidence paths
final AAO decision
report/audit path
whether the worker was real or fake
```

If the real local Claude Code command cannot run in the current environment,
the phase may be marked "code complete but real-smoke blocked", not "fully
landed". The blocker must be explicit.

## Validation Commands

Run targeted tests first:

```bash
PYTHONPATH=src python -m pytest -q tests/test_claude_code_worker_bridge.py tests/test_worker_protocol.py
PYTHONPATH=src python -m pytest -q tests/test_runtime_smoke.py tests/test_control_plane.py
```

Then run:

```bash
PYTHONPATH=src python -m pytest -q
python -m compileall -q src tests
git diff --check
git status --short
```

If the full suite is expensive, run targeted tests first and name exactly which
full-suite command was deferred. Do not replace tests with "looks good".

## Definition Of Done

Phase 18 is done only when:

```text
- `--worker-mode claude-code` exists and means real subprocess worker execution.
- `--worker-mode claude-code` never silently falls back to fake/packet mode.
- Worker command is configurable and uses safe subprocess invocation.
- Worker stdout/stderr/exit status are captured as observed evidence.
- Worker result/status/evidence files are loaded back into AAO.
- Missing observed evidence blocks completion or triggers recovery.
- Protected/denied file changes are detected where practical.
- Ask path can reach the real bridge, not only a helper test.
- Targeted tests pass.
- Full tests pass or unrelated failures are explicitly documented.
- A manual real-worker smoke test is run or explicitly blocked with reason.
- Final handoff states whether the original blueprint is now actually runnable.
```

## Required Handoff

Use `.claude/project-skills/aao-phase-handoff.md`.

Include:

```text
current phase
phase goal
what was real vs fake
changed files
dirty files outside current phase scope
worker command configuration
exact tests run
manual real smoke result
task packet path
observed evidence paths
audit/report path
known blockers
whether the original blueprint is now runnable end-to-end
next recommended step
```

## Required Final Explanation To User

Explain it naturally and concretely.

Use this mental model:

```text
Before this phase, AAO could write the work order and check fake returned files.
That proved the judge, but not the real worker.

After this phase, AAO can actually call Claude Code as the worker, give it the
work order, wait for the work, inspect the returned proof, and decide whether the
task is really done.
```

Make clear:

```text
what still uses fake tests
what now uses real Claude Code
where the evidence is stored
what happens when Claude Code fails
what happens when evidence is missing
whether API keys are needed or not
what remains for multi-worker / multi-model / LangGraph execution
```

Do not oversell. If the bridge only works for one worker and one bounded task,
say that clearly. That is still a real landing step.

## Claude Code Instruction

Read `CLAUDE.md` and this file. Implement only Phase 18. Your job is to connect
AAO to a real Claude Code worker process for one bounded end-to-end task path.
Do not count fake, packet-only, demo, or golden-scenario paths as complete. Keep
the bridge thin, command-configurable, source-backed, and testable. The final
handoff must say plainly whether `--worker-mode claude-code` truly launched a
real worker and whether the original blueprint is now runnable end-to-end.
