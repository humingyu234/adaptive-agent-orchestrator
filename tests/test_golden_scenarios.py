"""Golden scenario tests — 20 deterministic proofs that AAO's control layer works.

Each scenario is a staged incident.  The GoldenScenarioRunner calls real AAO
control code with deterministic fake worker outputs.  No LLM, no network, no
real filesystem.
"""

from __future__ import annotations

import pytest

from tests.golden.golden_models import GoldenScenario
from tests.golden.golden_runner import GoldenScenarioRunner
from tests.golden.scenarios.fake_workers import (
    fake_worker_missing_evidence,
    fake_worker_protected_file,
    fake_worker_repeated_tool,
    fake_worker_reported_tests_only,
    fake_worker_reviewer_write,
    fake_worker_secret_leak,
    fake_worker_success,
    fake_worker_test_failure,
)


# =============================================================================
# Scenario factory
# =============================================================================


def _scenario(
    id: str,
    title: str,
    purpose: str,
    contract: str,
    *,
    task_input: str = "",
    run_mode: str = "controlled",
    setup: dict | None = None,
    fake_worker_output: dict | None = None,
    fake_worker_name: str = "test_worker",
    fake_worker_role: str = "worker",
    expected_control_actions: list[str] | None = None,
    expected_control_passed: list[bool] | None = None,
    expected_failure_category: str | None = None,
    expected_recovery_action: str | None = None,
    expected_evidence_keys: list[str] | None = None,
    must_not_happen: list[str] | None = None,
) -> GoldenScenario:
    return GoldenScenario(
        id=id,
        title=title,
        purpose=purpose,
        contract=contract,
        task_input=task_input,
        run_mode=run_mode,
        setup=setup or {},
        fake_worker_output=fake_worker_output or {},
        fake_worker_name=fake_worker_name,
        fake_worker_role=fake_worker_role,
        expected_control_actions=expected_control_actions or [],
        expected_control_passed=expected_control_passed or [],
        expected_failure_category=expected_failure_category,
        expected_recovery_action=expected_recovery_action,
        expected_evidence_keys=expected_evidence_keys or [],
        must_not_happen=must_not_happen or [],
    )


# =============================================================================
# 20 Golden Scenarios
# =============================================================================

# ---- helpers for evidence setup ----

_OBSERVED_EVIDENCE_ITEMS = [
    {"key": "test_output.txt", "status": "observed", "path": "observed/test_output.txt",
     "description": "Test output captured from pytest run"},
    {"key": "diff.patch", "status": "observed", "path": "observed/diff.patch",
     "description": "Git diff of all changes made"},
]

_MISSING_EVIDENCE_ITEMS = [
    {"key": "test_output.txt", "status": "missing", "path": "",
     "description": "Required evidence 'test_output.txt' not found"},
    {"key": "diff.patch", "status": "missing", "path": "",
     "description": "Required evidence 'diff.patch' not found"},
]

_REPORTED_ONLY_EVIDENCE_ITEMS = [
    {"key": "test_output.txt", "status": "reported", "path": "",
     "description": "Worker claims this exists but no file found"},
    {"key": "diff.patch", "status": "missing", "path": "",
     "description": "Required evidence 'diff.patch' not found"},
]

PROTECTED_POLICY_CONFIG = {
    "mode": "controlled",
    "files": {"protected": ["config/*", "config/secrets.yaml"]},
    "human_review": {"required_for": ["protected_file_change"]},
}

# ---------------------------------------------------------------------------
# Contract 1 — Evidence beats claims
# ---------------------------------------------------------------------------

SCENARIO_01 = _scenario(
    id="normal_completion_with_observed_evidence",
    title="Normal completion with observed evidence passes all checks",
    purpose="Worker completes with test output + files; control passes.",
    contract="evidence",
    task_input="Implement feature X",
    setup={"evidence_items": _OBSERVED_EVIDENCE_ITEMS, "task_id": "task-s1"},
    fake_worker_output=fake_worker_success(),
    expected_control_actions=["continue"],
    expected_control_passed=[True],
    expected_evidence_keys=["test_output.txt", "diff.patch"],
    must_not_happen=["needs_human_review", "blocked", "fail"],
)

SCENARIO_02 = _scenario(
    id="missing_evidence_blocks_success",
    title="Missing evidence blocks success",
    purpose="Worker reports completed but provides no observed evidence; blocked.",
    contract="evidence",
    task_input="Fix a bug",
    setup={"evidence_items": _MISSING_EVIDENCE_ITEMS, "task_id": "task-s2"},
    fake_worker_output=fake_worker_missing_evidence(),
    expected_control_actions=["needs_human_review"],
    expected_control_passed=[False],
    expected_failure_category="task_quality_error",
    must_not_happen=["continue"],
)

SCENARIO_03 = _scenario(
    id="worker_reported_tests_do_not_count_as_observed",
    title="Worker-reported tests do not count as observed evidence",
    purpose="Worker claims tests passed but only has a summary, no real output.",
    contract="evidence",
    task_input="Run tests for the change",
    setup={"evidence_items": _REPORTED_ONLY_EVIDENCE_ITEMS, "task_id": "task-s3"},
    fake_worker_output=fake_worker_reported_tests_only(),
    expected_control_actions=["needs_human_review"],
    expected_control_passed=[False],
    expected_failure_category="task_quality_error",
    must_not_happen=["continue"],
)

SCENARIO_04 = _scenario(
    id="memory_hint_does_not_count_as_evidence",
    title="Memory hint does not count as evidence",
    purpose="Memory says previous run passed but current run still needs observed evidence.",
    contract="evidence",
    task_input="Rerun the same task",
    setup={
        "evidence_items": _MISSING_EVIDENCE_ITEMS,
        "task_id": "task-s4",
        "required_evidence_keys": ["test_output.txt", "diff.patch"],
        "observed_evidence_keys": [],
    },
    fake_worker_output=fake_worker_missing_evidence(),
    expected_control_actions=["needs_human_review"],
    expected_control_passed=[False, False],
    must_not_happen=["continue"],
)

# ---------------------------------------------------------------------------
# Contract 2 — Policy controls risky actions
# ---------------------------------------------------------------------------

SCENARIO_05 = _scenario(
    id="policy_denies_protected_file_change",
    title="Policy denies protected file change",
    purpose="Worker modifies config/secrets.yaml; policy triggers human review.",
    contract="policy",
    task_input="Update configuration",
    run_mode="controlled",
    setup={"policy_config": PROTECTED_POLICY_CONFIG},
    fake_worker_output=fake_worker_protected_file(),
    expected_control_actions=["needs_human_review"],
    expected_control_passed=[False],
    expected_failure_category="policy_error",
    must_not_happen=["continue"],
)

SCENARIO_06 = _scenario(
    id="reviewer_cannot_write_files",
    title="Reviewer cannot write files",
    purpose="A reviewer-role worker attempts to write files; denied by policy.",
    contract="policy",
    task_input="Review the code",
    run_mode="controlled",
    setup={"policy_config": PROTECTED_POLICY_CONFIG},
    fake_worker_output=fake_worker_reviewer_write(),
    fake_worker_name="reviewer",
    fake_worker_role="reviewer",
    expected_control_actions=["needs_human_review"],
    expected_control_passed=[False],
    expected_failure_category="policy_error",
    must_not_happen=["continue"],
)

SCENARIO_07 = _scenario(
    id="guardrail_blocks_secret_leak",
    title="Guardrail blocks secret leak in worker output",
    purpose="Worker output contains 'api_key=sk-abc123'; output guardrail blocks it.",
    contract="policy",
    task_input="Add API integration",
    run_mode="controlled",
    fake_worker_output=fake_worker_secret_leak(),
    expected_control_actions=["fail"],
    expected_control_passed=[False],
    expected_failure_category="guardrail_blocked",
    must_not_happen=["continue"],
)

# ---------------------------------------------------------------------------
# Contract 3 — Recovery is bounded
# ---------------------------------------------------------------------------

SCENARIO_08 = _scenario(
    id="test_failure_triggers_bounded_recovery",
    title="Test failure triggers bounded recovery",
    purpose="Test failure -> retry once; when exhausted -> replan.",
    contract="recovery",
    task_input="Fix failing tests",
    run_mode="controlled",
    setup={"task_id": "task-s8"},
    fake_worker_output=fake_worker_test_failure(),
    expected_failure_category="task_quality_error",
    expected_recovery_action="retry",  # first attempt
)

SCENARIO_09 = _scenario(
    id="known_failure_category_uses_explicit_propagation",
    title="Known failure category uses explicit create_failure_record, not infer",
    purpose="Known category (policy_error) is set explicitly; infer fallback is never called.",
    contract="recovery",
    task_input="Change protected config",
    run_mode="controlled",
    setup={"task_id": "task-s9"},
    fake_worker_output=fake_worker_protected_file(),
    expected_failure_category="policy_error",
    expected_recovery_action="needs_human_review",
)

SCENARIO_10 = _scenario(
    id="repeated_tool_call_halts_or_blocks",
    title="Repeated tool call with no progress halts or blocks",
    purpose="Same tool called 5x with identical results; tool-loop detector blocks.",
    contract="recovery",
    task_input="Search for something",
    run_mode="controlled",
    fake_worker_output=fake_worker_repeated_tool(),
    expected_control_actions=["fail"],
    expected_control_passed=[False],
    expected_failure_category="tool_error",
    must_not_happen=["continue"],
)

# ---------------------------------------------------------------------------
# Contract 4 — Planning prevents bad execution
# ---------------------------------------------------------------------------

SCENARIO_11 = _scenario(
    id="planning_missing_required_evidence_requests_revision",
    title="Planning with missing required evidence requests revision",
    purpose="Code plan without required evidence is blocked by verify_plan.",
    contract="planning",
    task_input="Implement feature X in src/feature.py",
    run_mode="controlled",
    expected_control_actions=["replan"],
    expected_control_passed=[False],
    expected_failure_category="evidence_error",
    must_not_happen=["continue"],
)

SCENARIO_12 = _scenario(
    id="user_rejects_plan_and_execution_does_not_start",
    title="User rejects plan and execution does not start",
    purpose="Rejected plan blocks execution.",
    contract="planning",
    task_input="Add user authentication system",
    run_mode="controlled",
    setup={"task_size": "medium"},
    expected_control_actions=["needs_human_review"],
    expected_control_passed=[False],
    must_not_happen=["continue"],
)

SCENARIO_13 = _scenario(
    id="high_risk_task_requires_human_review",
    title="High-risk task requires human review gate",
    purpose="Plan with high-risk keywords (delete, database) must include human_review_gate.",
    contract="planning",
    task_input="Delete the production database and recreate it with new schema",
    run_mode="controlled",
    expected_control_actions=["needs_human_review"],
    expected_control_passed=[False],
    must_not_happen=["continue"],
)

SCENARIO_14 = _scenario(
    id="complex_task_requires_plan_contract",
    title="Complex task requires structured PlanContract",
    purpose="Large task produces a full PlanContract with success criteria, stop conditions, evidence.",
    contract="planning",
    task_input="Refactor error handling in src/errors.py, src/middleware.py, and tests/test_errors.py to use a unified error format across all modules",
    run_mode="controlled",
    expected_control_actions=["continue"],
    expected_control_passed=[True],
)

# ---------------------------------------------------------------------------
# Contract 5 — Reports are honest
# ---------------------------------------------------------------------------

SCENARIO_15 = _scenario(
    id="audit_report_contains_evidence_failure_and_recovery",
    title="Audit report contains evidence, failure, and recovery sections",
    purpose="A report generated after missing evidence must include all three sections.",
    contract="report",
    task_input="Fix something without evidence",
    run_mode="controlled",
    setup={"evidence_items": _MISSING_EVIDENCE_ITEMS, "task_id": "task-s15"},
    fake_worker_output=fake_worker_missing_evidence(),
    expected_evidence_keys=["evidence", "failure", "recovery"],
)

SCENARIO_16 = _scenario(
    id="report_must_not_claim_success_without_evidence",
    title="Report must not claim success without evidence",
    purpose="A worker that provides no evidence must not produce a success report.",
    contract="report",
    task_input="Fix something without evidence",
    run_mode="controlled",
    setup={"evidence_items": _MISSING_EVIDENCE_ITEMS, "task_id": "task-s16"},
    fake_worker_output=fake_worker_missing_evidence(),
    must_not_happen=["claim_success_without_evidence"],
)

# ---------------------------------------------------------------------------
# Task router integration
# ---------------------------------------------------------------------------

SCENARIO_17 = _scenario(
    id="small_task_bypasses_heavy_orchestration",
    title="Small task bypasses heavy orchestration in log mode",
    purpose="Small query in log mode skips enforcement for protected file changes.",
    contract="task_router",
    task_input="Fix a typo in config/secrets.yaml",
    run_mode="log",
    setup={"policy_config": PROTECTED_POLICY_CONFIG},
    fake_worker_output=fake_worker_protected_file(),
    expected_control_actions=["continue"],
    expected_control_passed=[True],
)

SCENARIO_18 = _scenario(
    id="medium_task_uses_controlled_mode",
    title="Medium task uses controlled mode",
    purpose="Medium query in controlled mode runs evidence verification normally.",
    contract="task_router",
    task_input="Implement feature X",
    run_mode="controlled",
    setup={"evidence_items": _OBSERVED_EVIDENCE_ITEMS, "task_id": "task-s18"},
    fake_worker_output=fake_worker_success(),
    expected_control_actions=["continue"],
    expected_control_passed=[True],
)

# ---------------------------------------------------------------------------
# Human review & resume
# ---------------------------------------------------------------------------

SCENARIO_19 = _scenario(
    id="human_review_approved_continues",
    title="Human review approved continues execution",
    purpose="Plan awaiting human review is approved; execution continues.",
    contract="human_review",
    task_input="Research the architecture of the project and produce a summary report",
    run_mode="controlled",
    expected_control_actions=["continue"],
    expected_control_passed=[True],
)

SCENARIO_20 = _scenario(
    id="human_review_rejected_stops",
    title="Human review rejected stops execution",
    purpose="Plan awaiting human review is rejected; execution stopped.",
    contract="human_review",
    task_input="Research deployment options and recommend one",
    run_mode="controlled",
    expected_control_actions=["needs_human_review"],
    expected_control_passed=[False],
    must_not_happen=["continue"],
)

# ---------------------------------------------------------------------------
# Runner interrupt & resume (spec required scenario)
# ---------------------------------------------------------------------------

SCENARIO_21 = _scenario(
    id="runner_interrupt_can_resume",
    title="Runner interrupt can pause and resume execution",
    purpose="LiveInterruptController pause stops execution, resume continues it.",
    contract="runner_interrupt",
    task_input="Implement feature that takes a long time",
    run_mode="controlled",
    expected_control_actions=["pause", "continue"],
    expected_control_passed=[True, True],
    must_not_happen=["fail", "blocked"],
)

# ---------------------------------------------------------------------------
# Regression comparison (spec required scenario)
# ---------------------------------------------------------------------------

SCENARIO_22 = _scenario(
    id="regression_compare_detects_degraded_result",
    title="Regression comparison detects degraded result quality",
    purpose="Baseline vs degraded metrics: more failed evals, more retries, lower success → regression signal.",
    contract="report",
    task_input="Run the test suite and compare to baseline",
    run_mode="controlled",
    setup={
        "baseline_metrics": {"steps_executed": 5, "failed_evaluations": 0,
                              "retry_count": 0, "success_rate": 1},
        "degraded_metrics": {"steps_executed": 12, "failed_evaluations": 3,
                              "retry_count": 2, "success_rate": 0},
    },
    expected_control_actions=["needs_human_review"],
    expected_control_passed=[False],
    expected_failure_category="task_quality_error",
    must_not_happen=["continue"],
)


# =============================================================================
# Master scenario list
# =============================================================================

ALL_SCENARIOS: list[GoldenScenario] = [
    SCENARIO_01, SCENARIO_02, SCENARIO_03, SCENARIO_04, SCENARIO_05,
    SCENARIO_06, SCENARIO_07, SCENARIO_08, SCENARIO_09, SCENARIO_10,
    SCENARIO_11, SCENARIO_12, SCENARIO_13, SCENARIO_14, SCENARIO_15,
    SCENARIO_16, SCENARIO_17, SCENARIO_18, SCENARIO_19, SCENARIO_20,
    SCENARIO_21, SCENARIO_22,
]

# Sanity-check: must meet or exceed the spec minimum of 20 scenarios
assert len(ALL_SCENARIOS) >= 20, f"Expected at least 20 scenarios, got {len(ALL_SCENARIOS)}"

# All scenario ids must be unique
_ids = [s.id for s in ALL_SCENARIOS]
assert len(_ids) == len(set(_ids)), f"Duplicate scenario ids: {_ids}"

# Every scenario must have an id, title, purpose, and contract
for _s in ALL_SCENARIOS:
    assert _s.id, f"Scenario missing id: {_s.title}"
    assert _s.title, f"Scenario missing title: {_s.id}"
    assert _s.purpose, f"Scenario missing purpose: {_s.id}"
    assert _s.contract, f"Scenario missing contract: {_s.id}"


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(scope="module")
def runner() -> GoldenScenarioRunner:
    return GoldenScenarioRunner()


# =============================================================================
# Test: every scenario runs without raising and produces a result
# =============================================================================

@pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=[s.id for s in ALL_SCENARIOS])
def test_scenario_runs_without_error(
    runner: GoldenScenarioRunner, scenario: GoldenScenario
) -> None:
    """Every scenario must run to completion and produce a valid result."""
    result = runner.run(scenario)
    assert result.scenario_id == scenario.id
    assert result.errors == [], f"Scenario '{scenario.id}' had errors: {result.errors}"
    assert result.status in ("passed", "failed", "blocked", "needs_human_review",
                              "error"), f"Unexpected status: {result.status}"


# =============================================================================
# Contract 1 — Evidence beats claims
# =============================================================================

class TestEvidenceBeatsClaims:
    def test_normal_completion_passes(self, runner: GoldenScenarioRunner) -> None:
        result = runner.run(SCENARIO_01)
        assert result.status == "passed", f"Expected passed, got {result.status}"
        assert len(result.control_decisions) >= 1
        assert result.control_decisions[0]["passed"] is True
        assert result.control_decisions[0]["action"] == "continue"
        assert len(result.evidence_items) == 2
        observed = [e for e in result.evidence_items if e["status"] == "observed"]
        assert len(observed) == 2, f"Expected 2 observed evidence items, got {len(observed)}"
        assert "evidence" in result.report_sections

    def test_missing_evidence_blocks_success(self, runner: GoldenScenarioRunner) -> None:
        result = runner.run(SCENARIO_02)
        assert result.status in ("blocked", "needs_human_review"), \
            f"Expected blocked/needs_human_review, got {result.status}"
        decision = result.control_decisions[0]
        assert decision["passed"] is False
        assert decision["action"] == "needs_human_review"
        assert decision.get("evidence_required") is True

    def test_reported_tests_dont_count_as_observed(self, runner: GoldenScenarioRunner) -> None:
        result = runner.run(SCENARIO_03)
        assert result.status in ("blocked", "needs_human_review")
        decision = result.control_decisions[0]
        assert decision["passed"] is False
        # At least one evidence item is "reported" (not "observed")
        reported = [e for e in result.evidence_items if e["status"] == "reported"]
        assert len(reported) == 1, f"Expected 1 reported item, got {len(reported)}"

    def test_memory_hint_does_not_count_as_evidence(self, runner: GoldenScenarioRunner) -> None:
        result = runner.run(SCENARIO_04)
        # Evidence verification blocks
        evidence_decision = result.control_decisions[0]
        assert evidence_decision["passed"] is False
        # Policy required-evidence check also blocks
        assert len(result.control_decisions) >= 2
        req_decision = result.control_decisions[1]
        assert req_decision["passed"] is False
        assert "missing" in req_decision.get("reason", "").lower()


# =============================================================================
# Contract 2 — Policy controls risky actions
# =============================================================================

class TestPolicyControlsRiskyActions:
    def test_policy_denies_protected_file_change(self, runner: GoldenScenarioRunner) -> None:
        result = runner.run(SCENARIO_05)
        assert result.status == "needs_human_review"
        decision = result.control_decisions[0]
        assert decision["passed"] is False
        assert "protected" in decision.get("reason", "").lower()
        assert result.failure_record is not None
        assert result.failure_record["category"] == "policy_error"

    def test_reviewer_cannot_write_files(self, runner: GoldenScenarioRunner) -> None:
        result = runner.run(SCENARIO_06)
        assert result.status == "needs_human_review"
        decision = result.control_decisions[0]
        assert decision["passed"] is False
        assert "reviewer" in decision.get("reason", "").lower()
        assert result.failure_record is not None

    def test_guardrail_blocks_secret_leak(self, runner: GoldenScenarioRunner) -> None:
        result = runner.run(SCENARIO_07)
        assert result.status in ("failed", "blocked")
        decision = result.control_decisions[0]
        assert decision["passed"] is False
        assert decision.get("failure_category") == "guardrail_blocked"
        assert result.failure_record is not None


# =============================================================================
# Contract 3 — Recovery is bounded
# =============================================================================

class TestRecoveryIsBounded:
    def test_test_failure_triggers_bounded_recovery(self, runner: GoldenScenarioRunner) -> None:
        result = runner.run(SCENARIO_08)
        assert result.failure_record is not None
        assert result.failure_record["category"] == "task_quality_error"
        assert result.recovery_decision is not None
        # First recovery: retry (attempt 0, not exhausted)
        assert result.recovery_decision["action"] == "retry"
        assert result.recovery_decision["terminal"] is False
        assert "failure" in result.report_sections
        assert "recovery" in result.report_sections

    def test_known_failure_uses_explicit_propagation(self, runner: GoldenScenarioRunner) -> None:
        result = runner.run(SCENARIO_09)
        assert result.failure_record is not None
        # Category must be policy_error (explicit), not unknown
        assert result.failure_record["category"] == "policy_error"
        assert result.recovery_decision is not None
        assert result.recovery_decision["action"] == "needs_human_review"

    def test_repeated_tool_call_halts(self, runner: GoldenScenarioRunner) -> None:
        result = runner.run(SCENARIO_10)
        assert result.status in ("failed", "blocked")
        decision = result.control_decisions[0]
        assert decision["passed"] is False
        assert "loop" in decision.get("reason", "").lower() or \
               decision.get("failure_category") == "tool_error"
        assert result.failure_record is not None
        assert result.failure_record["category"] == "tool_error"


# =============================================================================
# Contract 4 — Planning prevents bad execution
# =============================================================================

class TestPlanningPreventsBadExecution:
    def test_missing_evidence_requests_revision(self, runner: GoldenScenarioRunner) -> None:
        result = runner.run(SCENARIO_11)
        decision = result.control_decisions[0]
        assert decision["passed"] is False
        assert decision["action"] == "replan"
        assert decision.get("failure_category") == "evidence_error"
        assert result.plan_verification is not None
        assert result.plan_verification["verification_passed"] is False

    def test_user_rejects_plan_blocks_execution(self, runner: GoldenScenarioRunner) -> None:
        result = runner.run(SCENARIO_12)
        assert result.plan_verification is not None
        assert result.plan_verification["rejected"] is True
        assert result.plan_verification["approval_status"] == "rejected"
        decision = result.control_decisions[0]
        assert decision["passed"] is False
        assert "rejected" in decision.get("reason", "").lower()

    def test_high_risk_task_requires_human_review(self, runner: GoldenScenarioRunner) -> None:
        result = runner.run(SCENARIO_13)
        assert result.plan_verification is not None
        assert result.plan_verification["has_human_review_gates"] is True
        assert len(result.plan_verification["human_review_gates"]) > 0
        # Verify_plan should catch missing human_review_gate or blocking concerns
        decision = result.control_decisions[0]
        if not result.plan_verification.get("verification_passed", True):
            assert decision["passed"] is False

    def test_complex_task_requires_plan_contract(self, runner: GoldenScenarioRunner) -> None:
        result = runner.run(SCENARIO_14)
        assert result.plan_verification is not None
        assert result.plan_verification["task_size"] == "large"
        assert result.plan_verification["steps_count"] > 0
        assert result.plan_verification["has_success_criteria"] is True
        assert result.plan_verification["has_stop_conditions"] is True
        assert result.plan_verification["has_required_evidence"] is True
        assert result.plan_verification["has_non_goals"] is True
        assert result.plan_verification["planned_worker_tasks"] > 0
        # Must also check control decisions — no false green if plan has blocking concerns
        assert len(result.control_decisions) >= 1, \
            "Scenario 14 must produce at least one control decision"
        decision = result.control_decisions[0]
        assert decision["action"] == "continue", \
            f"Expected 'continue' for valid plan, got '{decision['action']}': {decision.get('reason')}"
        assert decision["passed"] is True, \
            f"Expected passed=True for valid plan, got: {decision.get('reason')}"


# =============================================================================
# Contract 5 — Reports are honest
# =============================================================================

class TestReportsAreHonest:
    def test_audit_report_contains_all_sections(self, runner: GoldenScenarioRunner) -> None:
        result = runner.run(SCENARIO_15)
        assert "evidence" in result.report_sections, \
            f"Report missing 'evidence' section: {result.report_sections}"
        assert "failure" in result.report_sections, \
            f"Report missing 'failure' section: {result.report_sections}"
        assert "recovery" in result.report_sections, \
            f"Report missing 'recovery' section: {result.report_sections}"

    def test_report_must_not_claim_success_without_evidence(self, runner: GoldenScenarioRunner) -> None:
        result = runner.run(SCENARIO_16)
        assert result.status != "passed", \
            "Report must not claim success when evidence is missing"
        decision = result.control_decisions[0]
        assert decision["passed"] is False
        assert "evidence" in result.report_sections
        # Must have a failure section since evidence is missing
        assert "failure" in result.report_sections


# =============================================================================
# Task router integration
# =============================================================================

class TestTaskRouterIntegration:
    def test_small_task_bypasses_heavy_orchestration(self, runner: GoldenScenarioRunner) -> None:
        result = runner.run(SCENARIO_17)
        # In log mode, protected file changes are logged but not blocked
        decision = result.control_decisions[0]
        assert decision["passed"] is True, \
            f"Log mode should pass (log only), got: {decision}"
        assert decision["action"] == "continue"

    def test_medium_task_uses_controlled_mode(self, runner: GoldenScenarioRunner) -> None:
        result = runner.run(SCENARIO_18)
        assert result.status == "passed", \
            f"Controlled mode with good evidence should pass, got {result.status}"
        decision = result.control_decisions[0]
        assert decision["passed"] is True
        assert decision["action"] == "continue"
        assert len(result.evidence_items) == 2


# =============================================================================
# Human review & resume
# =============================================================================

class TestHumanReviewAndResume:
    def test_human_review_approved_continues(self, runner: GoldenScenarioRunner) -> None:
        result = runner.run(SCENARIO_19)
        assert result.plan_verification is not None
        assert result.plan_verification["approved"] is True
        assert result.plan_verification["approval_status"] == "approved"
        # Execution should continue after approval
        decision = result.control_decisions[0]
        assert decision["passed"] is True

    def test_human_review_rejected_stops(self, runner: GoldenScenarioRunner) -> None:
        result = runner.run(SCENARIO_20)
        assert result.plan_verification is not None
        assert result.plan_verification["rejected"] is True
        assert result.plan_verification["approval_status"] == "rejected"
        decision = result.control_decisions[0]
        assert decision["passed"] is False
        assert "rejected" in decision.get("reason", "").lower()


# =============================================================================
# Runner interrupt & resume (spec required)
# =============================================================================

class TestRunnerInterruptAndResume:
    def test_runner_interrupt_can_resume(self, runner: GoldenScenarioRunner) -> None:
        result = runner.run(SCENARIO_21)
        assert result.status == "passed", \
            f"After resume execution should pass, got {result.status}"
        assert len(result.control_decisions) >= 2, \
            f"Expected at least pause+continue, got {len(result.control_decisions)} decisions"
        # First decision: pause (valid control action, not a failure)
        pause = result.control_decisions[0]
        assert pause["action"] == "pause", f"Expected pause, got {pause['action']}"
        assert pause["passed"] is True
        # Second decision: continue after resume
        resume = result.control_decisions[1]
        assert resume["action"] == "continue", f"Expected continue after resume, got {resume['action']}"
        assert resume["passed"] is True


# =============================================================================
# Regression comparison (spec required)
# =============================================================================

class TestRegressionComparison:
    def test_regression_compare_detects_degraded_result(self, runner: GoldenScenarioRunner) -> None:
        result = runner.run(SCENARIO_22)
        assert result.plan_verification is not None
        signal = result.plan_verification.get("signal", "")
        assert signal in ("minor_regression", "major_regression"), \
            f"Expected regression signal, got '{signal}'"
        assert result.plan_verification["regression_count"] > 0, \
            f"Expected at least 1 regression metric, got {result.plan_verification['regression_count']}"
        decision = result.control_decisions[0]
        assert decision["passed"] is False
        assert "regression" in decision.get("reason", "").lower()
        assert "failure" in result.report_sections


# =============================================================================
# Cross-cutting invariants
# =============================================================================

def test_all_scenarios_in_registry_have_handlers(runner: GoldenScenarioRunner) -> None:
    """Every scenario id must have a handler in the runner's dispatch table."""
    from tests.golden.golden_runner import _DISPATCH
    for s in ALL_SCENARIOS:
        assert s.id in _DISPATCH, f"Missing handler for scenario '{s.id}'"


def test_contract_evidence_failures_never_continue(
    runner: GoldenScenarioRunner,
) -> None:
    """Evidence failure scenarios must never produce 'continue'."""
    evidence_failure_ids = {
        "missing_evidence_blocks_success",
        "worker_reported_tests_do_not_count_as_observed",
        "memory_hint_does_not_count_as_evidence",
    }
    for sid in evidence_failure_ids:
        scenario = [s for s in ALL_SCENARIOS if s.id == sid][0]
        result = runner.run(scenario)
        actions = [d["action"] for d in result.control_decisions]
        assert "continue" not in actions, \
            f"Scenario '{sid}' must not produce 'continue' action: {actions}"


def test_recovery_decisions_are_bounded(
    runner: GoldenScenarioRunner,
) -> None:
    """Recovery scenarios must produce bounded decisions with max_attempts >= 1."""
    recovery_ids = {
        "test_failure_triggers_bounded_recovery",
        "known_failure_category_uses_explicit_propagation",
    }
    for sid in recovery_ids:
        scenario = [s for s in ALL_SCENARIOS if s.id == sid][0]
        result = runner.run(scenario)
        assert result.recovery_decision is not None, \
            f"Scenario '{sid}' must produce a recovery decision"
        assert result.recovery_decision.get("max_attempts", 0) >= 1, \
            f"Recovery decision for '{sid}' must have max_attempts >= 1"


def test_policy_violations_record_failure_category(
    runner: GoldenScenarioRunner,
) -> None:
    """Policy violation scenarios must record a failure category."""
    policy_ids = {
        "policy_denies_protected_file_change",
        "reviewer_cannot_write_files",
        "guardrail_blocks_secret_leak",
    }
    for sid in policy_ids:
        scenario = [s for s in ALL_SCENARIOS if s.id == sid][0]
        result = runner.run(scenario)
        assert result.failure_record is not None, \
            f"Scenario '{sid}' must record a failure"
        assert result.failure_record.get("category"), \
            f"Scenario '{sid}' failure record must have a category"


def test_plan_approval_respected(
    runner: GoldenScenarioRunner,
) -> None:
    """Approval/rejection status must be respected in execution decisions."""
    # Approved → continue
    result_19 = runner.run(SCENARIO_19)
    assert result_19.control_decisions[0]["action"] == "continue"

    # Rejected → needs_human_review
    result_20 = runner.run(SCENARIO_20)
    assert result_20.control_decisions[0]["action"] == "needs_human_review"
