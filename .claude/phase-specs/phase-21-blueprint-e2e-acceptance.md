# Phase 21 - Blueprint End-to-End Acceptance

## Goal

Prove the original AAO blueprint with real user-facing commands and a repeatable
acceptance script.

This phase is not a feature phase. It is the acceptance gate for the system the
user originally wanted:

```text
user gives task
  -> real multi-advisor planning
  -> user approval
  -> real Claude Code worker execution
  -> runtime control / evidence / policy / recovery
  -> audit report
  -> user can understand what happened
```

## Hard Rule

Do not add major new capability in Phase 21. If the end-to-end path fails, fix
the integration gap. Do not escape into more framework work.

## Preflight

Read:

```text
CLAUDE.md
.claude/phase-specs/phase-18-real-claude-code-worker-bridge.md
.claude/phase-specs/phase-19-real-llm-planning-council.md
.claude/phase-specs/phase-20-multi-worker-plan-execution.md
README.md
docs/demo.md
docs/known_limitations.md
```

Run:

```bash
git status --short
```

## Acceptance Scenarios

Create or document three runnable scenarios:

```text
Scenario A: single-worker real code task
  proves the basic daily-use loop

Scenario B: multi-step controlled task
  proves plan -> multiple worker tasks -> per-step evidence

Scenario C: failure / recovery task
  proves AAO catches missing evidence, failed check, policy violation, or worker
  failure and does not pretend success
```

At least Scenario A must use a real Claude Code worker. Scenario B should use
real workers if the environment supports it; otherwise use one real worker plus
deterministic fake workers and clearly label the limitation. Scenario C may use
a deterministic failing worker to avoid wasting API quota.

## Required User-Facing Commands

The final system must have clear commands for the user:

```bash
python -m orchestrator ask "<task>" --planning-mode llm --approve --worker-mode claude-code

python -m orchestrator ask "<task>" --planning-mode llm --approve --worker-mode claude-code --max-workers 2

python -m orchestrator analyze show <run_id>
```

If exact command names differ, update this spec and README so the actual command
is unambiguous. Do not leave acceptance dependent on private helper scripts.

## Evidence Required For Acceptance

Each scenario must produce:

```text
run id
plan or PlanContract path
approval record
worker task packet path(s)
worker stdout/stderr/exit evidence
result.md / status.json
test/check output where required
diff.patch where code changed
ControlPlane decision(s)
recovery decision where relevant
final audit/report path
```

The final report must make it clear what was:

```text
observed
reported
inferred
missing
```

## No More Fake Completion

These are useful tests, but they do not satisfy Phase 21 by themselves:

```text
golden scenario suite
fake subprocess worker
packet-only worker
dry-run planning
README demo output
unit tests only
```

Phase 21 requires at least one real command that goes through the real path.

## Quality Bar

The system is acceptable only if a serious user can answer:

```text
What did AAO decide to do?
Which model/advisor planned it?
What did I approve?
Which worker did the work?
What files changed?
What checks ran?
What evidence proves it?
What failed or needed review?
Where is the audit report?
```

If the answer requires reading internal source code, the acceptance flow is not
clear enough.

## Test Plan

Add a small acceptance test layer that does not require live model keys:

```text
test_acceptance_single_worker_path_with_fake_provider_and_fake_subprocess
test_acceptance_multi_step_path_records_per_step_evidence
test_acceptance_failure_path_does_not_mark_completed
test_acceptance_report_contains_plan_worker_evidence_and_decisions
```

Then document manual live commands for real provider / real worker smoke.

## Manual Acceptance Run

Run and record:

```text
one real LLM planning smoke
one real Claude Code worker smoke
one end-to-end ask command using both, if keys/config allow it
```

If the real full chain is blocked by local keys, proxy, permissions, or Claude
Code CLI constraints, state exactly what is blocked. Do not mark it complete.

## Definition Of Done

Phase 21 is done only when:

```text
- The original blueprint has a real user-facing command path.
- At least one real Claude Code worker execution is included.
- Real LLM planning is included or explicitly blocked with environment reason.
- User approval is recorded before execution.
- Evidence and audit output are generated and inspectable.
- Failure scenario proves AAO does not falsely mark success.
- README/docs point to the real commands, not stale fake demos.
- Final handoff states exactly what is real, what is fake, and what remains.
```

## Required Final Explanation To User

Explain it like this:

```text
This is the "can I actually use it?" phase.

If Phase 21 passes, AAO is no longer just a collection of control modules. It is
a usable workflow: plan with models, get your approval, send work to Claude Code,
check the proof, and give you an audit report.
```

## Claude Code Instruction

Read `CLAUDE.md` and this file. Implement only Phase 21. Do not expand the
architecture. Do not add new optional integrations. Prove the original blueprint
with real commands, clear evidence, and an honest final status.
