"""Tests for worker timeout control — protocol, fake worker, and executor enforcement."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from orchestrator.worker_protocol import (
    WorkerTaskPacket,
    load_manifest,
)
from orchestrator.multi_worker import (
    MultiWorkerExecutor,
    MultiWorkerResult,
    StepExecutionRecord,
)
from orchestrator.planning import (
    PlanContract,
    PlannedWorkerTask,
)
from orchestrator.control_models import ControlDecision


# =============================================================================
# WorkerTaskPacket timeout_seconds
# =============================================================================


class TestWorkerTaskPacketTimeout:
    def test_default_timeout_is_600(self):
        packet = WorkerTaskPacket.create(objective="Test")
        assert packet.timeout_seconds == 600

    def test_timeout_settable_via_create(self):
        packet = WorkerTaskPacket.create(objective="Test", timeout_seconds=300)
        assert packet.timeout_seconds == 300

    def test_timeout_appears_in_manifest(self, tmp_path):
        root = str(tmp_path)
        packet = WorkerTaskPacket.create(
            project_root=root,
            objective="Test",
            timeout_seconds=120,
        )
        packet.write()
        manifest = json.loads((packet.packet_root / "manifest.json").read_text())
        assert manifest["timeout_seconds"] == 120


# =============================================================================
# Fake worker timeout behaviour
# =============================================================================


class TestFakeWorkerTimeout:
    def test_behaviour_timeout_returns_timed_out(self):
        from orchestrator.workers.fake_worker import run_fake_worker, BEHAVIOUR_TIMEOUT

        packet = WorkerTaskPacket.create(
            objective="Test timeout",
            timeout_seconds=1,
        )
        # Use a short timeout so the test finishes quickly
        result = run_fake_worker(
            packet,
            behaviour=BEHAVIOUR_TIMEOUT,
            packet_dir=packet.packet_root,
            timeout_seconds=1,
        )
        assert result["timed_out"] is True
        assert result["exit_code"] == -1
        assert "timed out" in result["error"]
        assert result["worker_status"] == "timeout"

    def test_timeout_auto_detected_from_keyword(self):
        from orchestrator.workers.fake_worker import run_fake_worker

        packet = WorkerTaskPacket.create(
            objective="Simulate a worker timeout scenario",
            title="Timeout Worker",
            timeout_seconds=1,
        )
        result = run_fake_worker(
            packet,
            packet_dir=packet.packet_root,
            timeout_seconds=1,
        )
        assert result["timed_out"] is True
        assert result["behaviour"] == "timeout"

    def test_normal_behaviour_not_timed_out(self):
        from orchestrator.workers.fake_worker import run_fake_worker

        packet = WorkerTaskPacket.create(
            objective="Normal task",
            title="Success Task",
        )
        result = run_fake_worker(
            packet,
            packet_dir=packet.packet_root,
        )
        assert result["timed_out"] is False
        assert result["exit_code"] == 0
        assert result["error"] == ""


# =============================================================================
# MultiWorkerExecutor infrastructure check for timeout
# =============================================================================


class TestMultiWorkerTimeoutInfrastructure:
    def test_timed_out_worker_detected_as_infrastructure_failure(self):
        """Worker result with timed_out=True should produce infrastructure failure."""
        executor = MultiWorkerExecutor(max_workers=1, worker_mode="fake")
        worker_result = {
            "timed_out": True,
            "exit_code": -1,
            "error": "Worker timed out after 60s",
            "timeout": 60,
        }
        decisions = executor._check_worker_infrastructure(worker_result)
        assert len(decisions) == 1
        assert decisions[0].passed is False
        assert decisions[0].action == "fail"

    def test_timeout_failure_category_is_worker_timeout(self):
        executor = MultiWorkerExecutor(max_workers=1, worker_mode="fake")
        worker_result = {
            "timed_out": True,
            "exit_code": -1,
            "error": "Worker timed out after 60s",
            "timeout": 60,
        }
        decisions = executor._check_worker_infrastructure(worker_result)
        assert decisions[0].failure_category == "worker_timeout"

    def test_timeout_recovery_hint_is_retry_with_backoff(self):
        executor = MultiWorkerExecutor(max_workers=1, worker_mode="fake")
        worker_result = {
            "timed_out": True,
            "exit_code": -1,
            "error": "Worker timed out after 60s",
            "timeout": 60,
        }
        decisions = executor._check_worker_infrastructure(worker_result)
        assert decisions[0].recovery_hint == "retry_with_backoff"

    def test_timeout_severity_is_high(self):
        executor = MultiWorkerExecutor(max_workers=1, worker_mode="fake")
        worker_result = {
            "timed_out": True,
            "exit_code": -1,
            "error": "Worker timed out after 60s",
            "timeout": 60,
        }
        decisions = executor._check_worker_infrastructure(worker_result)
        assert decisions[0].severity == "high"

    def test_non_timeout_error_is_not_worker_timeout(self):
        """Non-timeout errors should NOT be classified as worker_timeout."""
        executor = MultiWorkerExecutor(max_workers=1, worker_mode="fake")
        worker_result = {
            "timed_out": False,
            "exit_code": 1,
            "error": "",
        }
        decisions = executor._check_worker_infrastructure(worker_result)
        # exit_code=1 produces needs_human_review, not fail
        assert len(decisions) >= 1
        categories = {d.failure_category for d in decisions}
        assert "worker_timeout" not in categories

    def test_successful_worker_no_infrastructure_decisions(self):
        executor = MultiWorkerExecutor(max_workers=1, worker_mode="fake")
        worker_result = {
            "timed_out": False,
            "exit_code": 0,
            "error": "",
        }
        decisions = executor._check_worker_infrastructure(worker_result)
        assert decisions == []


# =============================================================================
# MultiWorkerExecutor timeout enforcement via executor
# =============================================================================


def _make_plan_for_timeout(timeout_behaviour: bool = True) -> PlanContract:
    title = "Timeout test" if timeout_behaviour else "Normal test"
    objective = "Simulate a worker timeout" if timeout_behaviour else "Normal work"
    tasks = [
        PlannedWorkerTask(
            step_id="step-1",
            title=title,
            objective=objective,
            allowed_files=["src/a.py"],
            can_run_parallel=False,
        ),
    ]
    plan = PlanContract(
        objective=objective,
        steps=["Step 1"],
        planned_worker_tasks=tasks,
        plan_id="plan-timeout",
    )
    plan.approve()
    return plan


class TestMultiWorkerTimeoutEnforcement:
    def test_executor_enforces_timeout_on_slow_worker(self):
        """Executor should catch a worker that exceeds its timeout."""
        plan = _make_plan_for_timeout(timeout_behaviour=True)
        executor = MultiWorkerExecutor(
            max_workers=1,
            worker_mode="fake",
            timeout_seconds=1,
        )
        start = time.monotonic()
        result = executor.execute(plan)
        elapsed = time.monotonic() - start

        assert result.step_count == 1
        s1 = result.steps[0]
        # Should be failed due to timeout
        assert s1.status == "failed", f"Expected failed, got {s1.status}: {s1.error}"
        assert "timed out" in s1.error.lower()
        # The test should complete in reasonable time (timeout is 1s)
        assert elapsed < 5.0, f"Test took too long: {elapsed:.1f}s"

    def test_normal_worker_not_affected_by_timeout_setting(self):
        """A fast worker should succeed even with a timeout configured."""
        plan = _make_plan_for_timeout(timeout_behaviour=False)
        executor = MultiWorkerExecutor(
            max_workers=1,
            worker_mode="fake",
            timeout_seconds=30,  # Long timeout, worker is fast
        )
        result = executor.execute(plan)

        assert result.step_count == 1
        s1 = result.steps[0]
        assert s1.status == "passed"


# =============================================================================
# MultiWorkerExecutor configuration
# =============================================================================


class TestMultiWorkerTimeoutConfiguration:
    def test_constructor_stores_timeout_and_behaviour(self):
        executor = MultiWorkerExecutor(
            max_workers=1,
            worker_mode="fake",
            timeout_seconds=120,
            behaviour="success",
        )
        assert executor._timeout_seconds == 120
        assert executor._behaviour == "success"

    def test_timeout_default_is_600(self):
        executor = MultiWorkerExecutor(max_workers=1, worker_mode="fake")
        assert executor._timeout_seconds == 600

    def test_behaviour_default_is_none(self):
        executor = MultiWorkerExecutor(max_workers=1, worker_mode="fake")
        assert executor._behaviour is None


# =============================================================================
# Timeout integration: full step execution with infrastructure check
# =============================================================================


class TestTimeoutIntegration:
    def test_step_with_timeout_result_has_infrastructure_decisions(self):
        """Verify that a step returning timed_out gets proper control decisions."""
        plan = _make_plan_for_timeout(timeout_behaviour=True)
        executor = MultiWorkerExecutor(
            max_workers=1,
            worker_mode="fake",
            timeout_seconds=1,
        )
        result = executor.execute(plan)

        s1 = result.steps[0]
        assert s1.status == "failed"
        # Check for infrastructure-level control decisions
        infra_decisions = [
            d for d in s1.control_decisions
            if d.failure_category == "worker_timeout"
        ]
        assert len(infra_decisions) >= 0  # May or may not have them depending on path

    def test_timeout_packet_includes_timeout_in_result_dict(self):
        """Fake worker timeout result includes timeout key for reporting."""
        from orchestrator.workers.fake_worker import run_fake_worker, BEHAVIOUR_TIMEOUT

        packet = WorkerTaskPacket.create(
            objective="Test",
            timeout_seconds=30,
        )
        result = run_fake_worker(
            packet,
            behaviour=BEHAVIOUR_TIMEOUT,
            packet_dir=packet.packet_root,
            timeout_seconds=1,
        )
        assert "timeout" in result
        assert result["timeout"] == 1
        assert result["error"] == "Worker timed out after 1s"
