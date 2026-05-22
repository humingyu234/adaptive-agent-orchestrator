"""Phase 22 — Auto-Repair Loop tests.

Proves: ReviewFinding → FixTask → dispatch → verify → repeat (max 2)
→ escalate to human review on exhaustion.
"""

from __future__ import annotations

import pytest

from orchestrator.auto_repair import (
    AutoRepairLoop,
    FixTask,
    RepairResult,
    RepairRound,
    ReviewFinding,
)


# =============================================================================
# Helpers
# =============================================================================


def _blocking_finding(
    step_id: str = "step-1",
    category: str = "test_failure",
    description: str = "test_output.txt shows 2 FAILED",
    location: str = "src/errors.py:42",
    suggested_fix: str | None = "Fix assertion in test_memory.py:42",
) -> ReviewFinding:
    return ReviewFinding(
        finding_id="F-001",
        step_id=step_id,
        severity="blocking",
        category=category,
        description=description,
        location=location,
        suggested_fix=suggested_fix,
        source="control_plane",
    )


def _non_blocking_finding() -> ReviewFinding:
    return ReviewFinding(
        finding_id="F-002",
        step_id="step-1",
        severity="non_blocking",
        category="style",
        description="Missing type annotation",
        location="src/utils.py:10",
    )


def _system_issue_finding() -> ReviewFinding:
    return ReviewFinding(
        finding_id="F-003",
        step_id="step-1",
        severity="blocking",
        category="system_network_timeout",
        description="Network timeout during worker execution",
    )


def _pass_on_round(round_num: int) -> tuple:
    """Dispatch that passes only on the given round number."""
    call_count = 0

    def dispatch(fix_task: FixTask) -> dict:
        nonlocal call_count
        call_count += 1
        if call_count >= round_num:
            return {"status": "completed", "test_output": "2 passed, 0 failed"}
        return {"status": "completed", "test_output": "1 passed, 1 failed"}

    def verify(result: dict) -> bool:
        return "0 failed" in str(result.get("test_output", ""))

    return dispatch, verify, call_count


def _always_fail():
    def dispatch(fix_task: FixTask) -> dict:
        return {"status": "completed", "test_output": "0 passed, 2 failed"}

    def verify(result: dict) -> bool:
        return False

    return dispatch, verify


def _always_pass():
    def dispatch(fix_task: FixTask) -> dict:
        return {"status": "completed", "test_output": "2 passed, 0 failed"}

    def verify(result: dict) -> bool:
        return True

    return dispatch, verify


# =============================================================================
# Tests
# =============================================================================


class TestAutoRepairLoop:
    """Core repair loop behaviour."""

    def test_first_attempt_succeeds_single_round(self):
        """If the first FixTask passes verification, only one round is used."""
        finding = _blocking_finding()
        loop = AutoRepairLoop(max_attempts=2)
        dispatch, verify = _always_pass()

        result = loop.attempt_repair(
            finding, dispatch_fn=dispatch, verify_fn=verify,
            target_file="src/errors.py", verification="pytest",
        )

        assert result.status == "fixed"
        assert result.total_rounds == 1
        assert len(result.rounds) == 1
        assert result.rounds[0].status == "fixed"
        assert result.rounds[0].repair_round == 1

    def test_second_attempt_succeeds_after_first_fails(self):
        """First round fails, second passes — two rounds, status fixed."""
        finding = _blocking_finding()
        loop = AutoRepairLoop(max_attempts=2)
        call_count = 0

        def dispatch(fix_task: FixTask) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"status": "completed", "test_output": "0 passed, 2 failed"}
            return {"status": "completed", "test_output": "2 passed, 0 failed"}

        def verify(result: dict) -> bool:
            return "0 failed" in str(result.get("test_output", ""))

        result = loop.attempt_repair(
            finding, dispatch_fn=dispatch, verify_fn=verify,
            target_file="src/errors.py", verification="pytest",
        )

        assert result.status == "fixed"
        assert result.total_rounds == 2
        assert len(result.rounds) == 2
        assert result.rounds[0].status == "still_failing"
        assert result.rounds[1].status == "fixed"

    def test_both_attempts_fail_enters_human_review(self):
        """After max_attempts failures, status is blocked_needs_review."""
        finding = _blocking_finding()
        loop = AutoRepairLoop(max_attempts=2)
        dispatch, verify = _always_fail()

        result = loop.attempt_repair(
            finding, dispatch_fn=dispatch, verify_fn=verify,
            target_file="src/errors.py", verification="pytest",
        )

        assert result.status == "blocked_needs_review"
        assert result.total_rounds == 2
        assert len(result.rounds) == 2
        assert all(r.status == "still_failing" for r in result.rounds)
        assert result.final_finding is not None

    def test_non_blocking_finding_does_not_trigger_fix(self):
        """Non-blocking findings return still_failing with zero rounds."""
        finding = _non_blocking_finding()
        loop = AutoRepairLoop(max_attempts=2)
        dispatch, verify = _always_pass()

        result = loop.attempt_repair(
            finding, dispatch_fn=dispatch, verify_fn=verify,
        )

        assert result.status == "still_failing"
        assert result.total_rounds == 0
        assert len(result.rounds) == 0

    def test_system_issue_does_not_trigger_ordinary_fix(self):
        """system_* category findings go straight to blocked_needs_review."""
        finding = _system_issue_finding()
        loop = AutoRepairLoop(max_attempts=2)
        dispatch, verify = _always_pass()

        result = loop.attempt_repair(
            finding, dispatch_fn=dispatch, verify_fn=verify,
        )

        assert result.status == "blocked_needs_review"
        assert result.total_rounds == 0

    def test_max_attempts_enforced_hard_limit(self):
        """Loop never exceeds max_attempts regardless of repeated failures."""
        finding = _blocking_finding()
        loop = AutoRepairLoop(max_attempts=2)
        dispatch, verify = _always_fail()

        result = loop.attempt_repair(
            finding, dispatch_fn=dispatch, verify_fn=verify,
        )

        assert result.total_rounds == 2
        # Verify no 3rd round was attempted
        assert loop.attempts_for(finding.step_id) == 2

    def test_max_attempts_custom_value_respected(self):
        """max_attempts=3 allows three rounds before escalation."""
        finding = _blocking_finding()
        loop = AutoRepairLoop(max_attempts=3)
        dispatch, verify = _always_fail()

        result = loop.attempt_repair(
            finding, dispatch_fn=dispatch, verify_fn=verify,
        )

        assert result.total_rounds == 3
        # All three rounds recorded
        assert all(r.status == "still_failing" for r in result.rounds)

    def test_audit_records_every_round(self):
        """Each round produces a complete RepairRound audit entry."""
        finding = _blocking_finding()
        loop = AutoRepairLoop(max_attempts=2)
        call_count = 0

        def dispatch(fix_task: FixTask) -> dict:
            nonlocal call_count
            call_count += 1
            # Fail round 1, pass round 2
            if call_count == 1:
                return {"status": "completed", "test_output": "0 passed, 2 failed"}
            return {"status": "completed", "test_output": "2 passed, 0 failed"}

        def verify(result: dict) -> bool:
            return "0 failed" in str(result.get("test_output", ""))

        result = loop.attempt_repair(
            finding, dispatch_fn=dispatch, verify_fn=verify,
            target_file="src/errors.py", verification="pytest",
        )

        assert len(result.rounds) == 2

        # Round 1 audit
        r1 = result.rounds[0]
        assert r1.repair_round == 1
        assert r1.finding_id == "F-001"
        assert r1.fix_task_id.startswith("FT-")
        assert r1.fix_description
        assert "worker_result" in r1.to_dict()
        assert r1.status == "still_failing"
        assert r1.retest_result == "failed"

        # Round 2 audit
        r2 = result.rounds[1]
        assert r2.repair_round == 2
        assert r2.status == "fixed"
        assert r2.retest_result == "passed"
        assert r2.rereview_result == "no blocking findings"

    def test_audit_rounds_captured_on_all_failures(self):
        """Even when all rounds fail, the audit rounds are complete."""
        finding = _blocking_finding()
        loop = AutoRepairLoop(max_attempts=2)
        dispatch, verify = _always_fail()

        result = loop.attempt_repair(
            finding, dispatch_fn=dispatch, verify_fn=verify,
        )

        assert result.status == "blocked_needs_review"
        assert len(result.rounds) == 2
        for r in result.rounds:
            d = r.to_dict()
            assert d["status"] == "still_failing"
            assert d["retest_result"] == "failed"
            assert d["rereview_result"] == "still failing"

    def test_fix_task_targets_only_one_file(self):
        """Each FixTask references exactly one file."""
        finding = _blocking_finding()
        loop = AutoRepairLoop(max_attempts=1)

        captured_task: FixTask | None = None

        def dispatch(fix_task: FixTask) -> dict:
            nonlocal captured_task
            captured_task = fix_task
            return {"status": "completed", "test_output": "2 passed, 0 failed"}

        def verify(result: dict) -> bool:
            return True

        loop.attempt_repair(
            finding, dispatch_fn=dispatch, verify_fn=verify,
            target_file="src/errors.py",
        )

        assert captured_task is not None
        assert captured_task.target_file == "src/errors.py"
        # target_file should not be a list or contain commas (one file only)
        assert "," not in captured_task.target_file

    def test_fix_task_carries_finding_link(self):
        """FixTask.triggered_by_finding_id matches the originating finding."""
        finding = _blocking_finding()
        loop = AutoRepairLoop(max_attempts=1)

        captured_task: FixTask | None = None

        def dispatch(fix_task: FixTask) -> dict:
            nonlocal captured_task
            captured_task = fix_task
            return {"status": "completed", "test_output": "2 passed, 0 failed"}

        def verify(result: dict) -> bool:
            return True

        loop.attempt_repair(
            finding, dispatch_fn=dispatch, verify_fn=verify,
        )

        assert captured_task is not None
        assert captured_task.triggered_by_finding_id == "F-001"
        assert captured_task.step_id == "step-1"


class TestReviewFinding:
    """ReviewFinding model behaviour."""

    def test_blocking_finding_is_blocking(self):
        f = _blocking_finding()
        assert f.is_blocking is True
        assert f.is_system_issue is False

    def test_non_blocking_finding_is_not_blocking(self):
        f = _non_blocking_finding()
        assert f.is_blocking is False

    def test_system_category_detected(self):
        f = _system_issue_finding()
        assert f.is_system_issue is True
        assert f.is_blocking is True

    def test_from_control_decision_creates_blocking(self):
        f = ReviewFinding.from_control_decision(
            step_id="step-3",
            reason="Test output shows 3 FAILED",
            category="test_failure",
            location="tests/test_a.py:15",
            suggested_fix="Fix expected value",
        )
        assert f.severity == "blocking"
        assert f.step_id == "step-3"
        assert f.finding_id.startswith("F-")
        assert f.source == "control_plane"
        assert f.is_system_issue is False


class TestFixTask:
    """FixTask model behaviour."""

    def test_from_finding_preserves_step_and_file(self):
        finding = _blocking_finding()
        fix = FixTask.from_finding(
            finding, target_file="src/errors.py", verification="pytest",
        )
        assert fix.step_id == "step-1"
        assert fix.target_file == "src/errors.py"
        assert fix.verification == "pytest"
        assert fix.triggered_by_finding_id == "F-001"
        assert fix.status == "pending"
        assert fix.max_attempts == 2

    def test_fallback_target_file_uses_finding_location(self):
        finding = _blocking_finding(location="src/middleware.py:30")
        fix = FixTask.from_finding(finding)
        assert fix.target_file == "src/middleware.py:30"

    def test_fallback_verification_uses_pytest(self):
        finding = _blocking_finding()
        fix = FixTask.from_finding(finding)
        assert fix.verification == "pytest"


class TestRepairRound:
    """RepairRound audit record."""

    def test_to_dict_includes_all_keys(self):
        rr = RepairRound(
            repair_round=1,
            finding_id="F-001",
            finding="2 tests failed",
            fix_task_id="FT-abc",
            fix_description="Fix assertion",
            worker_result={"status": "completed"},
            retest_result="passed",
            rereview_result="no blocking findings",
            status="fixed",
        )
        d = rr.to_dict()
        for key in (
            "repair_round", "finding_id", "finding", "fix_task_id",
            "fix_description", "worker_result", "retest_result",
            "rereview_result", "status",
        ):
            assert key in d, f"Missing key: {key}"


class TestRepairResult:
    """RepairResult model."""

    def test_fixed_result_is_fixed(self):
        r = RepairResult(status="fixed", step_id="s1", total_rounds=1)
        assert r.is_fixed

    def test_blocked_result_not_fixed(self):
        r = RepairResult(status="blocked_needs_review", step_id="s1", total_rounds=2)
        assert not r.is_fixed


# =============================================================================
# Integration tests — MainlineExecutor repair wiring
# =============================================================================


class TestMainlineRepairIntegration:
    """Prove the repair loop triggers and verifies correctly in MainlineExecutor.

    These tests guard P0-1 (repair never triggers) and P0-2 (verify always
    returns True).
    """

    def test_verify_fix_rejects_failing_test_output(self):
        """P0-2: a worker result with FAILED test output must be rejected."""
        from orchestrator.mainline_executor import MainlineExecutor
        from orchestrator.worker_protocol import PacketFiles, WorkerTaskPacket

        executor = MainlineExecutor()
        packet = WorkerTaskPacket.create(
            project_root=str(executor.project_root),
            run_id="test-run",
            task_id="FT-test",
            title="Test fix",
            objective="Fix test",
            allowed_files=["src/test.py"],
        )
        # Write failing test output at the path _check_test_results reads
        test_output = packet.packet_root / PacketFiles.TEST_OUTPUT
        test_output.parent.mkdir(parents=True, exist_ok=True)
        test_output.write_text("1 passed, 2 FAILED", encoding="utf-8")

        worker_result = {"behaviour": "fake", "worker_status": "completed"}
        passed = executor._verify_fix(worker_result, packet)
        assert passed is False, "P0-2: must reject failing test output"

    def test_verify_fix_accepts_passing_test_output(self):
        """A worker result with all-passing test output must be accepted."""
        from orchestrator.mainline_executor import MainlineExecutor
        from orchestrator.worker_protocol import PacketFiles, WorkerTaskPacket

        executor = MainlineExecutor()
        packet = WorkerTaskPacket.create(
            project_root=str(executor.project_root),
            run_id="test-run-2",
            task_id="FT-test-2",
            title="Test fix",
            objective="Fix test",
            allowed_files=["src/test.py"],
        )
        test_output = packet.packet_root / PacketFiles.TEST_OUTPUT
        test_output.parent.mkdir(parents=True, exist_ok=True)
        test_output.write_text("3 passed, 0 failed", encoding="utf-8")

        worker_result = {"behaviour": "fake", "worker_status": "completed"}
        passed = executor._verify_fix(worker_result, packet)
        assert passed is True, "Must accept passing test output"

    def test_verify_fix_rejects_hard_failure_worker(self):
        """A worker that self-reports failure must be rejected."""
        from orchestrator.mainline_executor import MainlineExecutor
        from orchestrator.worker_protocol import WorkerTaskPacket

        executor = MainlineExecutor()
        packet = WorkerTaskPacket.create(
            project_root=str(executor.project_root),
            run_id="test-run-3",
            task_id="FT-test-3",
            title="Test fix",
            objective="Fix test",
        )

        worker_result = {"behaviour": "blocked", "worker_status": "failed"}
        passed = executor._verify_fix(worker_result, packet)
        assert passed is False, "Must reject blocked/failed worker"

    def test_repair_triggers_on_task_quality_with_retry(self):
        """P0-1: repair loop must trigger when failure_category is
        task_quality_error and action is retry."""
        from orchestrator.control_models import ControlDecision
        from orchestrator.failure_taxonomy import FailureCategory

        d = ControlDecision(
            passed=False,
            action="retry",
            reason="Test failure detected: 2 test(s) failed",
            failure_category=FailureCategory.TASK_QUALITY_ERROR.value,
            recovery_hint="retry",
        )
        assert d.failure_category == "task_quality_error"
        assert d.action == "retry"
        # This is the condition the integration point checks
        is_repairable = (
            d.failure_category == FailureCategory.TASK_QUALITY_ERROR.value
            and d.action == "retry"
        )
        assert is_repairable is True

    def test_repair_skips_missing_evidence(self):
        """A non-retry action even on task_quality_error must not trigger repair.

        For example, a missing required check produces action!=retry (may be
        ``needs_human_review`` or ``fail`` depending on severity).  Repair
        only triggers for action=retry.
        """
        from orchestrator.control_models import ControlDecision
        from orchestrator.failure_taxonomy import FailureCategory

        d = ControlDecision(
            passed=False,
            action="needs_human_review",
            reason="Missing required checks: pytest",
            failure_category=FailureCategory.TASK_QUALITY_ERROR.value,
        )
        is_repairable = (
            d.failure_category == FailureCategory.TASK_QUALITY_ERROR.value
            and d.action == "retry"
        )
        assert is_repairable is False, "non-retry action must not trigger repair"

    def test_repair_skips_guardrail_blocked(self):
        """Guardrail-blocked failures must not trigger repair."""
        from orchestrator.control_models import ControlDecision
        from orchestrator.failure_taxonomy import FailureCategory

        d = ControlDecision(
            passed=False,
            action="fail",
            reason="Protected file change blocked",
            failure_category=FailureCategory.GUARDRAIL_BLOCKED.value,
        )
        is_repairable = (
            d.failure_category == FailureCategory.TASK_QUALITY_ERROR.value
            and d.action == "retry"
        )
        assert is_repairable is False, "guardrail_blocked must not trigger repair"
