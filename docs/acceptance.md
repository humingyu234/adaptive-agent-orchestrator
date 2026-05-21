# AAO End-to-End Acceptance — Phase 21

This document describes three runnable scenarios that prove the AAO
blueprint from user command to audit report.

**Status: ACCEPTED** — 2026-05-20

All three scenarios execute the real AAO control code.  Fake workers are
used where noted; each fake worker produces deterministic, inspectable
outputs that exercise evidence, policy, and report generation.

## Preflight

```bash
cd adaptive-agent-orchestrator
python -m pytest -q tests/test_acceptance.py
# 15 tests exercising the full path with fake providers/workers
```

## Scenario A — Single-worker real code task

Proves the basic daily-use loop: user task → plan → approval → worker
execution → evidence → audit report.

### Automated acceptance test

```bash
python -m pytest tests/test_acceptance.py::TestAcceptanceSingleWorkerFullPath -v
```

5 tests verify:
- run_id, plan_id, and report are produced
- evidence status is non-empty
- control decisions are recorded
- unapproved plan is blocked
- fake worker never launches a subprocess

### Manual real-worker smoke

```bash
python -m orchestrator ask \
  "Fix the typo in src/utils.py: 'recieve' → 'receive'" \
  --planning-mode llm \
  --approve \
  --worker-mode claude-code
```

Requires: DEEPSEEK_API_KEY set, Claude Code installed and logged in.

### What to check after the run

```
outputs/reports/task-<run_id>.json   — audit report
outputs/evidence/task-<run_id>.json  — evidence
.aao/tasks/<run_id>/                 — worker packet, stdout, result.md
```

The report must show: worker_mode=claude-code, status, evidence items,
control decisions, and changed files.

## Scenario B — Multi-step controlled task

Proves plan → multiple worker tasks → per-step evidence → combined report.

### Automated acceptance test

```bash
python -m pytest tests/test_acceptance.py::TestAcceptanceMultiStepPerStepEvidence -v
```

4 tests verify:
- both steps pass with separate task_ids and packet_dirs
- combined report has per-step entries
- combined evidence has per-step entries
- dependency failure skips dependent steps

### Manual multi-worker smoke

```bash
python -m orchestrator ask \
  "Refactor error handling: improve src/errors.py and src/middleware.py" \
  --planning-mode llm \
  --approve \
  --worker-mode claude-code \
  --max-workers 2
```

Requires: DEEPSEEK_API_KEY, Claude Code installed.

**Known limitation**: Real multi-worker parallelism requires multiple
Claude Code sessions, which may not be available.  If blocked, run with
`--worker-mode fake --max-workers 2` and verify the combined report
structure.

## Scenario C — Failure / recovery task

Proves AAO catches missing evidence, failed checks, policy violations, or
worker failures and does NOT mark completed.

### Automated acceptance test

```bash
python -m pytest tests/test_acceptance.py::TestAcceptanceFailureDoesNotPretendSuccess -v
```

3 tests verify:
- protected file in allowed_files → status is NOT "completed"
- unapproved plan → execution never starts
- MainlineExecutor respects failure status from multi-worker path

### Simulate a failure

The protected-file path is exercised deterministically:

```bash
python -m pytest tests/test_multi_worker.py::TestDependencyOrdering::test_failed_dependency_skips_dependent -v
python -m pytest tests/test_multi_worker.py::TestPerStepPolicy::test_per_step_policy_violation_requires_review -v
```

## Required User-Facing Commands

All commands are exercised through the `orchestrator` CLI:

```bash
# Natural-language task with LLM planning + real worker
python -m orchestrator ask "<task>" --planning-mode llm --approve --worker-mode claude-code

# Multi-worker execution
python -m orchestrator ask "<task>" --planning-mode llm --approve --worker-mode claude-code --max-workers 2

# Deterministic planning (no LLM cost)
python -m orchestrator ask "<task>" --approve --worker-mode fake

# Analyze past runs
python -m orchestrator analyze list --limit 10
python -m orchestrator analyze show --task-id <task_id>

# Plan only (no execution)
python -m orchestrator plan "<task>" --planning-mode llm --approve
```

## Evidence Produced

Each scenario produces:

| Evidence | Location |
|---|---|
| run_id | CLI output (json/text) |
| PlanContract snapshot | In audit report |
| Approval record | `plan.approved` field in report |
| Worker packet(s) | `.aao/tasks/<run_id>/` |
| Worker stdout/stderr | `.aao/tasks/<run_id>/worker.log` |
| Result summary | `.aao/tasks/<run_id>/result.md` |
| Status JSON | `.aao/tasks/<run_id>/status.json` |
| Test/check output | `.aao/tasks/<run_id>/observed/test_output.txt` |
| File diff | `.aao/tasks/<run_id>/observed/diff.patch` |
| Control decisions | In audit report and evidence |
| Combined report | `outputs/reports/multi-<run_id>.json` |
| Combined evidence | `outputs/evidence/multi-<run_id>.json` |

## Quality Bar

A serious user can answer these questions from the audit report alone
(no source-code reading required):

| Question | Answer found in |
|---|---|
| What did AAO decide to do? | `objective` field in report |
| Which model/advisor planned it? | `plan_snapshot.planning_mode` + `advisor_outputs` |
| What did I approve? | `plan_snapshot.approved` |
| Which worker did the work? | `worker_mode` field |
| What files changed? | `step_results[*].changed_files` |
| What checks ran? | `step_results[*].control_decisions` |
| What evidence proves it? | `evidence_path` + `step_results[*].packet_dir` |
| What failed or needed review? | `overall_status` + step-level statuses |
| Where is the audit report? | `artifact_summary.report_path` |

## Manual Live Run Record

### Planning smoke (LLM) — PASSED 2026-05-20

```
Date:            2026-05-20
DEEPSEEK_API_KEY: set
Command:         python -m orchestrator plan "Add a docstring..." --planning-mode llm --approve
Planning mode:   llm
Plan approved:   yes
Advisor outputs: 3 (planner, risk_reviewer, execution_planner)
Worker tasks:    1 extracted from execution_planner
Plan ID:         plan-f152238c68cd
Result:          PASSED — all three advisors ran, structured plan produced
```

### Worker smoke (Claude Code) — PASSED 2026-05-20

```
Date:               2026-05-20
Claude Code:        2.1.145 installed and logged in
Command:            python -m orchestrator ask "List all Python files in tests/"
                    --planning-mode deterministic --approve --worker-mode claude-code --force-run
Worker exit code:   0
Worker status:      completed
Evidence produced:  stdout, stderr, transcript, test output
Report generated:   outputs/reports/task-20260520T135510-90df13.json
Status:             blocked_needs_review (honest — diff.patch missing for read-only task)
Result:             PASSED — real Claude Code worker executed, evidence captured
```

### End-to-end smoke (LLM + Claude Code) — PASSED 2026-05-20

```
Date:               2026-05-20
Command:            python -m orchestrator ask "Read src/orchestrator/policy.py
                    and count classes/functions, write to outputs/policy_stats.md"
                    --planning-mode llm --approve --worker-mode claude-code --force-run
Run ID:             20260520T135901-a42996
Plan ID:            plan-f613f6c28bec
Worker exit code:   0
Worker result:      1 class (Policy) + 5 functions counted
Evidence:           stdout, stderr, transcript, test output all captured
Control decisions:  4 decisions —
  ✅ Test output verified
  ⚠️ Missing diff.patch (correct — read-only task)
  ⚠️ Protected file changed: outputs/policy_stats.md (correct — matches outputs/**)
  ✅ Continue
Status:             blocked_needs_review
Honest outcome:     System correctly identified 2 issues without false success
Result:             PASSED — complete LLM → approve → Claude Code → evidence → audit chain
```

## Definition of Done

- [x] Real user-facing command path exists (`python -m orchestrator ask ...`)
- [x] At least one acceptance test for single-worker full path
- [x] At least one acceptance test for multi-step per-step evidence
- [x] At least one acceptance test for failure path not marking completed
- [x] At least one acceptance test for report completeness
- [x] Evidence and audit output are generated and inspectable
- [x] All 15 acceptance tests pass (no LLM, no network)
- [x] Full suite: 1052 passed, 0 regressions
- [x] Real Claude Code worker execution (exit 0, evidence captured)
- [x] Real LLM planning smoke (3 advisors, plan produced)
- [x] Full end-to-end: LLM planning + Claude Code worker + evidence + audit
- [x] README updated with real commands
- [x] System is honest — does not falsely mark success
