"""Integration tests for the mainline execution path.

Contracts:
1. Normal completion → all evidence observed, status=completed
2. Missing evidence → blocked, needs_human_review
3. Protected file → policy blocks, needs_human_review
4. Test failure → evidence observed but worker reports failures
5. Planning Council integration → plan verified, approved, executed
6. Audit report → generated with evidence, control, plan sections
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.control_plane import ControlPlane
from orchestrator.failure_taxonomy import FailureCategory
from orchestrator.mainline_executor import MainlineExecutor
from orchestrator.planning import (
    PlanContract,
    PlannedWorkerTask,
    PlanningCouncil,
    build_default_council,
)
from orchestrator.policy import Policy
from orchestrator.worker_protocol import (
    WorkerTaskPacket,
    classify_worker_evidence_from_packet,
    load_worker_result_text,
    load_worker_status,
    list_observed_files,
)


REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_plan(
    objective: str,
    *,
    steps: list[str] | None = None,
    required_evidence: list[str] | None = None,
    allowed_files: list[str] | None = None,
    risk_level: str = "medium",
) -> PlanContract:
    """Build a minimal approved PlanContract for testing."""
    plan = PlanContract(
        objective=objective,
        run_mode="controlled",
        task_size="medium",
        steps=steps or ["Implement the change", "Run tests", "Collect evidence"],
        risks=["Standard implementation risk"],
        non_goals=["Do not change unrelated files"],
        required_evidence=required_evidence or ["test_output.txt", "diff.patch"],
        success_criteria=["All tests pass", "Evidence collected"],
    )
    if allowed_files:
        plan.planned_worker_tasks = [
            PlannedWorkerTask(
                title=f"Execute: {objective[:60]}",
                objective=objective,
                allowed_files=allowed_files,
                required_checks=["python -m pytest"],
                expected_evidence=list(plan.required_evidence),
            )
        ]
    plan.approve()
    return plan


# ---------------------------------------------------------------------------
# Test 1 — Normal completion (success behaviour)
# ---------------------------------------------------------------------------


class TestNormalCompletion:
    def test_success_behaviour_produces_observed_evidence(self) -> None:
        executor = MainlineExecutor(REPO_ROOT)
        plan = _build_plan(
            "Add a helper function to src/utils.py",
            allowed_files=["src/utils.py", "tests/test_utils.py"],
        )
        result = executor.execute(plan, worker_mode="fake")

        assert result.status == "completed"
        assert result.worker_mode == "fake"
        assert result.evidence_status is not None
        assert result.evidence_status["has_missing_required"] is False

    def test_success_evidence_items_all_observed(self) -> None:
        executor = MainlineExecutor(REPO_ROOT)
        plan = _build_plan("Refactor src/middleware.py")
        result = executor.execute(plan, worker_mode="fake")

        items = result.evidence_status["items"]
        assert len(items) >= 2
        for item in items:
            assert item["status"] == "observed", f"{item['key']} should be observed"

    def test_success_all_control_decisions_pass(self) -> None:
        executor = MainlineExecutor(REPO_ROOT)
        plan = _build_plan("Update src/config.py")
        result = executor.execute(plan, worker_mode="fake")

        for d in result.control_decisions:
            assert d["passed"], f"Decision {d['action']} should pass: {d['reason']}"

    def test_success_worker_writes_result_md(self) -> None:
        executor = MainlineExecutor(REPO_ROOT)
        plan = _build_plan("Implement feature in src/feature.py")
        result = executor.execute(plan, worker_mode="fake")

        packet_path = Path(result.worker_packet_path)
        result_md = packet_path / "result.md"
        assert result_md.exists()
        content = result_md.read_text()
        assert "## Result:" in content
        assert "pytest:" in content

    def test_success_worker_writes_status_json(self) -> None:
        executor = MainlineExecutor(REPO_ROOT)
        plan = _build_plan("Add tests for src/service.py")
        result = executor.execute(plan, worker_mode="fake")

        packet_path = Path(result.worker_packet_path)
        status_json = packet_path / "status.json"
        assert status_json.exists()
        data = json.loads(status_json.read_text())
        assert data["status"] == "completed"
        assert "changed_files" in data

    def test_success_generates_report_and_evidence(self) -> None:
        executor = MainlineExecutor(REPO_ROOT)
        plan = _build_plan("Update src/handler.py")
        result = executor.execute(plan, worker_mode="fake")

        assert result.report_path
        assert Path(result.report_path).exists()
        assert result.evidence_path
        assert Path(result.evidence_path).exists()

    def test_success_changed_files_are_captured(self) -> None:
        executor = MainlineExecutor(REPO_ROOT)
        plan = _build_plan("Refactor the error handling code")
        result = executor.execute(plan, worker_mode="fake")

        assert len(result.changed_files) > 0


# ---------------------------------------------------------------------------
# Test 2 — Missing evidence blocks completion
# ---------------------------------------------------------------------------


class TestMissingEvidence:
    def test_missing_evidence_status_is_blocked(self) -> None:
        executor = MainlineExecutor(REPO_ROOT)
        plan = _build_plan(
            "Fix the thing but I think I fixed it with missing evidence and no observed files",
            allowed_files=["src/utils.py"],
        )
        # "missing" and "no evidence" trigger missing_evidence behaviour
        result = executor.execute(plan, worker_mode="fake")

        assert result.evidence_status is not None
        assert result.evidence_status["has_missing_required"] is True

    def test_control_decision_requests_evidence(self) -> None:
        executor = MainlineExecutor(REPO_ROOT)
        plan = _build_plan(
            "Update code but produce missing evidence and no test output",
            allowed_files=["src/utils.py"],
        )
        result = executor.execute(plan, worker_mode="fake")

        decisions = result.control_decisions
        actions = [d["action"] for d in decisions if not d["passed"]]
        assert "needs_human_review" in actions

    def test_missing_evidence_items_have_missing_status(self) -> None:
        executor = MainlineExecutor(REPO_ROOT)
        plan = _build_plan(
            "Quick fix with missing evidence and no observed files",
            allowed_files=["src/handler.py"],
        )
        result = executor.execute(plan, worker_mode="fake")

        items = result.evidence_status["items"]
        statuses = {item["key"]: item["status"] for item in items}
        assert any(s == "missing" for s in statuses.values())


# ---------------------------------------------------------------------------
# Test 3 — Protected file requires human review
# ---------------------------------------------------------------------------


class TestProtectedFile:
    def test_protected_file_triggers_policy_check(self) -> None:
        """When worker changes a protected file, the policy check must fire."""
        policy = Policy(
            protected_files=["config/secrets.yaml", "**/credentials/*"],
            human_review_required_for=["protected_file_change"],
        )
        cp = ControlPlane(policy=policy)
        decision = cp.check_policy_for_file_changes(
            files_changed=["config/secrets.yaml"]
        )
        assert not decision.passed
        assert decision.action == "needs_human_review"
        assert "config/secrets.yaml" in decision.reason

    def test_protected_file_with_log_mode_passes(self) -> None:
        """In log mode, policy violations are recorded but don't block."""
        policy = Policy(
            protected_files=["config/secrets.yaml"],
            human_review_required_for=["protected_file_change"],
            mode="log",
        )
        cp = ControlPlane(policy=policy)
        decision = cp.check_policy_for_file_changes(
            files_changed=["config/secrets.yaml"]
        )
        assert decision.passed
        assert decision.action == "continue"

    def test_non_protected_file_passes_policy(self) -> None:
        policy = Policy(
            protected_files=["config/secrets.yaml"],
            human_review_required_for=["protected_file_change"],
        )
        cp = ControlPlane(policy=policy)
        decision = cp.check_policy_for_file_changes(
            files_changed=["src/utils.py"]
        )
        assert decision.passed
        assert decision.action == "continue"


# ---------------------------------------------------------------------------
# Test 4 — Test failure triggers recovery
# ---------------------------------------------------------------------------


class TestTestFailure:
    def test_failure_record_has_task_quality_category(self) -> None:
        cp = ControlPlane()
        record = cp.create_failure_record(
            category=FailureCategory.TASK_QUALITY_ERROR,
            agent_name="fake_worker",
            reason="2 tests failed",
            severity="medium",
            context={"failed_tests": ["test_edge_case", "test_timeout"]},
        )
        assert record.category == FailureCategory.TASK_QUALITY_ERROR
        assert record.severity == "medium"

    def test_recovery_decision_for_test_failure(self) -> None:
        cp = ControlPlane()
        record = cp.create_failure_record(
            category=FailureCategory.TASK_QUALITY_ERROR,
            agent_name="fake_worker",
            reason="2 failed, 10 passed",
        )
        recovery = cp.decide_recovery(record, attempt_count=1, run_mode="controlled")
        assert recovery.action in ("retry", "replan", "request_evidence", "fail")

    def test_worker_with_test_failures_still_produces_evidence(self) -> None:
        """Even when tests fail, observed evidence should be present."""
        executor = MainlineExecutor(REPO_ROOT)
        plan = _build_plan(
            "Refactor with broken tests and error handling",
            allowed_files=["src/errors.py"],
        )
        result = executor.execute(plan, worker_mode="fake")

        # Evidence exists even when worker encounters failures
        assert result.evidence_status is not None
        # Worker may report failures but evidence is still collected
        items = result.evidence_status["items"]
        observed_keys = [i["key"] for i in items if i["status"] == "observed"]
        assert len(observed_keys) >= 1  # test failure still produces evidence


# ---------------------------------------------------------------------------
# Test 5 — Planning Council integration
# ---------------------------------------------------------------------------


class TestPlanningCouncilIntegration:
    def test_council_creates_valid_plan(self) -> None:
        council = build_default_council()
        plan = council.create_plan(
            "Implement a structured logging system in src/middleware.py with tests",
            task_size="large",
            run_mode="controlled",
        )
        assert plan is not None
        assert len(plan.steps) > 0
        assert len(plan.required_evidence) > 0
        assert len(plan.success_criteria) > 0

    def test_plan_verified_by_control_plane(self) -> None:
        council = build_default_council()
        plan = council.create_plan(
            "Refactor src/middleware.py to improve error handling",
            task_size="medium",
            run_mode="controlled",
            risk_level="low",
        )
        # Remove blocking concerns that come from no-files detection
        plan.blocking_concerns = []
        plan.approve()

        cp = ControlPlane()
        verification = cp.verify_plan(plan)
        assert verification.passed, f"Plan verification failed: {verification.reason}"

    def test_council_to_executor_chain(self) -> None:
        """Full chain: Planning Council → PlanContract → MainlineExecutor."""
        council = build_default_council()
        plan = council.create_plan(
            "Add helper functions to src/utils.py with tests",
            task_size="medium",
            run_mode="controlled",
            risk_level="low",
        )
        plan.blocking_concerns = []
        plan.approve()

        executor = MainlineExecutor(REPO_ROOT)
        result = executor.execute(plan, worker_mode="fake")

        assert result.plan_id == plan.plan_id
        assert result.status == "completed"
        assert result.report_path
        assert result.evidence_path
        assert result.worker_packet_path

    def test_blocking_concerns_prevent_execution(self) -> None:
        """Plan with unresolved blocking concerns cannot be approved."""
        plan = PlanContract(
            objective="Delete the production database",
            blocking_concerns=["BLOCKING: Destructive operation needs human review"],
        )
        with pytest.raises(ValueError, match="blocking"):
            plan.approve()

    def test_planned_worker_task_converts_to_packet(self) -> None:
        council = build_default_council()
        plan = council.create_plan(
            "Refactor src/errors.py src/middleware.py to use new error types",
            task_size="large",
            run_mode="controlled",
            risk_level="medium",
        )
        plan.blocking_concerns = []
        plan.approve()

        assert len(plan.planned_worker_tasks) > 0
        pwt = plan.planned_worker_tasks[0]
        assert pwt.title
        assert pwt.objective
        assert pwt.has_boundaries


# ---------------------------------------------------------------------------
# Test 6 — Audit report generation
# ---------------------------------------------------------------------------


class TestAuditReport:
    def test_report_contains_required_sections(self) -> None:
        executor = MainlineExecutor(REPO_ROOT)
        plan = _build_plan("Update src/handler.py with better error messages")
        result = executor.execute(plan, worker_mode="fake")

        report_data = json.loads(Path(result.report_path).read_text())
        assert report_data["report_type"] == "mainline_audit"
        assert "execution_summary" in report_data
        assert "control_decisions" in report_data
        assert "evidence_summary" in report_data
        assert "plan_snapshot" in report_data
        assert "artifact_summary" in report_data

    def test_report_includes_evidence_summary(self) -> None:
        executor = MainlineExecutor(REPO_ROOT)
        plan = _build_plan("Add tests for src/service.py")
        result = executor.execute(plan, worker_mode="fake")

        report_data = json.loads(Path(result.report_path).read_text())
        evidence = report_data["evidence_summary"]
        assert "total_items" in evidence
        assert "observed" in evidence
        assert "missing" in evidence
        assert evidence["observed"] >= 1

    def test_report_includes_control_decisions(self) -> None:
        executor = MainlineExecutor(REPO_ROOT)
        plan = _build_plan("Refactor src/config.py")
        result = executor.execute(plan, worker_mode="fake")

        report_data = json.loads(Path(result.report_path).read_text())
        decisions = report_data["control_decisions"]
        assert len(decisions) >= 1
        for d in decisions:
            assert "action" in d
            assert "passed" in d
            assert "reason" in d

    def test_report_includes_artifact_paths(self) -> None:
        executor = MainlineExecutor(REPO_ROOT)
        plan = _build_plan("Implement feature in src/feature.py")
        result = executor.execute(plan, worker_mode="fake")

        report_data = json.loads(Path(result.report_path).read_text())
        artifacts = report_data["artifact_summary"]
        assert "report_path" in artifacts
        assert "evidence_path" in artifacts
        assert "worker_packet_path" in artifacts

    def test_report_does_not_claim_success_without_evidence(self) -> None:
        """Report must be honest — if evidence is missing, don't claim success."""
        executor = MainlineExecutor(REPO_ROOT)
        plan = _build_plan(
            "Fix quickly with missing evidence and no proof of work",
        )
        result = executor.execute(plan, worker_mode="fake")

        report_data = json.loads(Path(result.report_path).read_text())
        summary = report_data["execution_summary"]
        has_missing = report_data["evidence_summary"]["missing"] > 0

        assert has_missing, "Expected missing evidence in report"
        assert summary["has_missing_evidence"] is True

    def test_evidence_pack_is_valid_json(self) -> None:
        executor = MainlineExecutor(REPO_ROOT)
        plan = _build_plan("Update src/utils.py")
        result = executor.execute(plan, worker_mode="fake")

        evidence_data = json.loads(Path(result.evidence_path).read_text())
        assert "task_id" in evidence_data
        assert "plan_id" in evidence_data
        assert "evidence_status" in evidence_data
        assert "observed_files" in evidence_data


# ---------------------------------------------------------------------------
# Cross-cutting tests
# ---------------------------------------------------------------------------


class TestMainlineResult:
    def test_result_to_dict_contains_all_keys(self) -> None:
        executor = MainlineExecutor(REPO_ROOT)
        plan = _build_plan("Add a function to src/helpers.py")
        result = executor.execute(plan, worker_mode="fake")

        d = result.to_dict()
        required_keys = [
            "run_id", "task_id", "plan_id", "status", "worker_mode",
            "worker_result", "evidence_status", "control_decisions",
            "report_path", "evidence_path", "worker_packet_path",
            "changed_files", "summary",
        ]
        for key in required_keys:
            assert key in d, f"Missing key: {key}"

    def test_packet_mode_creates_directory(self) -> None:
        executor = MainlineExecutor(REPO_ROOT)
        plan = _build_plan("Research the best approach for caching")
        result = executor.execute(plan, worker_mode="packet")

        packet_path = Path(result.worker_packet_path)
        assert packet_path.exists()
        assert packet_path.is_dir()
        # Manifest should exist
        manifest = packet_path / "manifest.json"
        assert manifest.exists()

    def test_fake_mode_writes_observed_files(self) -> None:
        executor = MainlineExecutor(REPO_ROOT)
        plan = _build_plan("Implement a new API endpoint")
        result = executor.execute(plan, worker_mode="fake")

        observed_dir = Path(result.worker_packet_path) / "observed"
        assert observed_dir.exists()
        observed_files = list(observed_dir.iterdir())
        assert len(observed_files) > 0
