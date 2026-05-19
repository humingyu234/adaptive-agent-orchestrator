# Golden Scenario Suite — Phase 16

Deterministic proof that AAO's control layer works across all advertised failure mode
contracts.  20 staged incidents, 0 LLM calls, 0 network, 0 real filesystem.

## Contracts

### Contract 1 — Evidence beats claims

The control layer must distinguish observed evidence (files on disk, test output
captured) from reported claims (worker says "tests passed" but no file exists).

| # | Scenario | What we test | Expected |
|---|----------|-------------|----------|
| 1 | `normal_completion_with_observed_evidence` | Worker completes with test output + diff on disk | Pass |
| 2 | `missing_evidence_blocks_success` | Worker claims completion but provides nothing observable | Blocked, `needs_human_review` |
| 3 | `worker_reported_tests_do_not_count_as_observed` | Worker claims "tests passed" in summary but no file exists | Blocked, evidence is reported not observed |
| 4 | `memory_hint_does_not_count_as_evidence` | Memory hints claim previous run passed; current run still needs evidence | Blocked, memory is not evidence |

### Contract 2 — Policy controls risky actions

Declarative policy rules (protected files, reviewer restrictions, guardrails) must
be enforced regardless of worker output quality.

| # | Scenario | What we test | Expected |
|---|----------|-------------|----------|
| 5 | `policy_denies_protected_file_change` | Worker modifies `config/secrets.yaml` | `needs_human_review`, `policy_error` |
| 6 | `reviewer_cannot_write_files` | Reviewer-role worker writes files | `needs_human_review`, denied |
| 7 | `guardrail_blocks_secret_leak` | Worker output contains `api_key=sk-abc123` | `fail`, `guardrail_blocked` |

### Contract 3 — Recovery is bounded

Every failure handling path must be bounded: max attempts, explicit termination,
no infinite retry loops.

| # | Scenario | What we test | Expected |
|---|----------|-------------|----------|
| 8 | `test_failure_triggers_bounded_recovery` | Test failure triggers retry, exhausted → replan | Retry once, then replan |
| 9 | `known_failure_category_uses_explicit_propagation` | Failure category set explicitly, no infer fallback | Explicit `policy_error`, not inferred |
| 10 | `repeated_tool_call_halts_or_blocks` | Same tool called 5x with identical results | Tool loop detected, blocked |

### Contract 4 — Planning prevents bad execution

The Planning Council must catch missing evidence, high-risk gaps, and scope
problems before execution starts.

| # | Scenario | What we test | Expected |
|---|----------|-------------|----------|
| 11 | `planning_missing_required_evidence_requests_revision` | Code plan with no required evidence | `replan`, `evidence_error` |
| 12 | `user_rejects_plan_and_execution_does_not_start` | User rejects plan | `needs_human_review`, execution blocked |
| 13 | `high_risk_task_requires_human_review` | High-risk keywords trigger human review gate | `needs_human_review` |
| 14 | `complex_task_requires_plan_contract` | Large task produces full PlanContract | Structured fields present |

### Contract 5 — Reports are honest

Audit reports must include evidence, failure, and recovery sections.  Reports
must never claim success when evidence is missing.

| # | Scenario | What we test | Expected |
|---|----------|-------------|----------|
| 15 | `audit_report_contains_evidence_failure_and_recovery` | Missing evidence generates all three sections | evidence + failure + recovery present |
| 16 | `report_must_not_claim_success_without_evidence` | No evidence → report must not claim success | Status is not "passed" |

### Task router integration

Run mode (off / log / controlled / orchestrated) must gate the depth of
control enforcement.

| # | Scenario | What we test | Expected |
|---|----------|-------------|----------|
| 17 | `small_task_bypasses_heavy_orchestration` | Log mode: protected file changes logged, not blocked | Pass (log only) |
| 18 | `medium_task_uses_controlled_mode` | Controlled mode: evidence verification runs normally | Pass with observed evidence |

### Human review & resume

The human review gate must correctly allow continuation after approval and
stop execution after rejection.

| # | Scenario | What we test | Expected |
|---|----------|-------------|----------|
| 19 | `human_review_approved_continues` | Plan approved → execution continues | Pass |
| 20 | `human_review_rejected_stops` | Plan rejected → execution stopped | `needs_human_review` |

### Runner interrupt & resume

| # | Scenario | What we test | Expected |
|---|----------|-------------|----------|
| 21 | `runner_interrupt_can_resume` | LiveInterruptController pause → resume → continue | Pass after resume |

### Regression comparison

| # | Scenario | What we test | Expected |
|---|----------|-------------|----------|
| 22 | `regression_compare_detects_degraded_result` | Baseline vs degraded metrics comparison | Regression detected, `needs_human_review` |

## Architecture

```
tests/golden/
├── __init__.py              # Package marker
├── golden_models.py         # GoldenScenario, GoldenScenarioResult dataclasses
├── golden_runner.py         # GoldenScenarioRunner (calls real AAO control code)
└── scenarios/
    ├── __init__.py          # Package marker
    └── fake_workers.py      # 8 deterministic fake worker functions

tests/test_golden_scenarios.py  # 45 pytest tests (20 parametrized + 25 targeted)
docs/golden_scenarios.md        # This file
```

### Key principle

The GoldenScenarioRunner calls **real** AAO control code:

- `ControlPlane` — `evaluate_output`, `guard_output`, `verify_worker_evidence`,
  `check_policy_for_file_changes`, `check_policy_for_reviewer_result`,
  `verify_plan`, `decide_recovery`
- `Policy` — `from_dict`, `is_file_protected`, `requires_human_review_for_file`
- `RecoveryPlaybook` — `decide` (full matrix: retry, exhausted, replan)
- `PlanningCouncil` — `create_plan`
- `PlanContract` — `approve`, `reject`
- `ToolCallGuardrailController` — tool-loop detection (5 identical calls → halt)

Fake components are ONLY the workers — deterministic dicts with no LLM,
no network, no filesystem.

## Running

```bash
# Golden suite only
python3 -m pytest tests/test_golden_scenarios.py -v

# Golden suite + golden unit tests
python3 -m pytest tests/golden tests/test_golden_scenarios.py -v

# Full project suite
python3 -m pytest -v
```

## Fake workers

| Worker | Output signature |
|--------|-----------------|
| `fake_worker_success` | test_output=14 passed, files_changed, tools_called |
| `fake_worker_missing_evidence` | status=completed, summary only |
| `fake_worker_reported_tests_only` | status=completed, claims tests passed |
| `fake_worker_test_failure` | test_output=2 failed, errors present |
| `fake_worker_protected_file` | files_changed includes config/secrets.yaml |
| `fake_worker_reviewer_write` | reviewer role, files_changed |
| `fake_worker_repeated_tool` | tools_called=["web_search"]*5 |
| `fake_worker_secret_leak` | summary contains api_key credential |

## Boundary test matrix

| Dimension | Covered by scenario |
|-----------|-------------------|
| `run_mode=off` | All policy checks have an off-mode bypass |
| `run_mode=log` | #17, #18 |
| `run_mode=controlled` | #1-16, #18-22 |
| `run_mode=orchestrated` | #14 (large task implies orchestrated readiness) |
| `task_size=small` | #17 (log mode) |
| `task_size=medium` | #11, #18, #19, #20 |
| `task_size=large` | #14 |
| `risk_level=low` | #1-4, #11, #12, #17-20 |
| `risk_level=medium` | #5-10, #15-16 |
| `risk_level=high` | #13 |
| Evidence: all observed | #1, #18 |
| Evidence: all missing | #2, #4, #15, #16 |
| Evidence: reported only | #3 |
| Policy: protected file hit | #5, #17 |
| Policy: reviewer write | #6 |
| Guardrail: output block | #7 |
| Recovery: retry → exhausted | #8 |
| Recovery: explicit category | #9 |
| Tool loop: repeated idempotent | #10 |
| Planning: missing evidence | #11 |
| Planning: user reject | #12, #20 |
| Planning: high risk gate | #13 |
| Planning: full contract | #14 |
| Report: all sections | #15 |
| Report: no false success | #16 |
| Human review: approve | #19 |
| Human review: reject | #20 |
| Runner: interrupt + resume | #21 |
| Regression: metric diff + signal | #22 |

## Definition of Done

- [x] 22 scenarios implemented (spec minimum: 20), all documented and testable
- [x] Every scenario has a handler in `_DISPATCH`
- [x] Every scenario produces a `GoldenScenarioResult` with control decisions
- [x] Evidence, failure, and recovery paths all exercised through real control code
- [x] All 49 tests pass deterministically (no randomness, no network)
- [x] Contracts 1-5 verified with targeted assertions
- [x] Run mode matrix covered (log, controlled)
- [x] Task size matrix covered (small, medium, large)
- [x] Human review approve/reject flow covered
- [x] Runner interrupt/resume covered (#21, LiveInterruptController)
- [x] Regression comparison covered (#22, RegressionCompare metric diff + signal)
- [x] Import paths use standard `orchestrator.xxx` (not `src.orchestrator.xxx`)
- [x] No silent ValueError swallowing — plan approval errors recorded in plan_verification
- [x] Scenario 14 control_decisions explicitly asserted (no false green)

## Known Gaps

All 20 spec-required scenarios are implemented.  Two additional scenarios (#21-22)
were added during review to complete the spec's Required Scenario Set.  The
`regression_compare_detects_degraded_result` scenario exercises the pure metric
diff and signal determination logic of `RegressionCompare` without filesystem
access; full end-to-end regression comparison (loading reports from disk) is
testable at the integration level.
