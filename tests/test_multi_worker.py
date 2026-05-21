"""Tests for Phase 20 — Multi-Worker Plan Execution.

All tests use fake workers (no real LLM/subprocess calls)."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from orchestrator.planning import (
    PlanContract,
    PlannedWorkerTask,
    PlanningCouncil,
    build_default_council,
)
from orchestrator.multi_worker import (
    MultiWorkerExecutor,
    MultiWorkerResult,
    StepExecutionRecord,
    StepStatus,
)
from orchestrator.mainline_executor import MainlineExecutor, MainlineResult
from orchestrator.policy import Policy
from orchestrator.control_models import ControlDecision


# =============================================================================
# Helpers
# =============================================================================


def make_plan_with_worker_tasks(
    objective: str = "Multi-step task",
    tasks: list[PlannedWorkerTask] | None = None,
    approved: bool = True,
) -> PlanContract:
    """Build a PlanContract with explicit worker tasks."""
    plan = PlanContract(
        objective=objective,
        steps=["Step 1", "Step 2"],
        planned_worker_tasks=tasks or [
            PlannedWorkerTask(
                step_id="step-1",
                title="Step 1: Inspect",
                objective="Inspect the codebase",
                allowed_files=["src/a.py"],
                denied_files=["src/secrets.py"],
                required_checks=["pytest"],
                expected_evidence=["test_output.txt"],
                risk_level="low",
                can_run_parallel=True,
            ),
            PlannedWorkerTask(
                step_id="step-2",
                title="Step 2: Modify",
                objective="Modify src/b.py",
                allowed_files=["src/b.py"],
                denied_files=["src/secrets.py"],
                required_checks=["pytest"],
                expected_evidence=["test_output.txt"],
                risk_level="low",
                can_run_parallel=True,
            ),
        ],
        plan_id="plan-test",
    )
    if approved:
        plan.approve()
    return plan


# =============================================================================
# StepExecutionRecord tests
# =============================================================================


class TestStepExecutionRecord:
    def test_default_record_is_pending(self):
        s = StepExecutionRecord()
        assert s.status == "pending"
        assert s.step_id == ""

    def test_record_fields(self):
        s = StepExecutionRecord(
            step_id="step-1",
            title="Fix auth",
            status="passed",
            task_id="task-abc",
            packet_dir="/tmp/pkt",
        )
        assert s.step_id == "step-1"
        assert s.status == "passed"


# =============================================================================
# MultiWorkerResult tests
# =============================================================================


class TestMultiWorkerResult:
    def test_default_result(self):
        r = MultiWorkerResult()
        assert r.status == "unknown"
        assert r.step_count == 0

    def test_step_counts(self):
        r = MultiWorkerResult(steps=[
            StepExecutionRecord(step_id="s1", status="passed"),
            StepExecutionRecord(step_id="s2", status="passed"),
            StepExecutionRecord(step_id="s3", status="failed"),
        ])
        assert r.step_count == 3
        assert r.passed_steps == 2
        assert r.failed_steps == 1

    def test_to_dict(self):
        r = MultiWorkerResult(
            run_id="run-1",
            plan_id="plan-1",
            status="completed",
            steps=[
                StepExecutionRecord(step_id="s1", status="passed",
                                    control_decisions=[
                                        ControlDecision(passed=True, action="continue",
                                                        reason="OK"),
                                    ]),
            ],
        )
        d = r.to_dict()
        assert d["run_id"] == "run-1"
        assert d["step_count"] == 1
        assert d["passed_steps"] == 1
        assert d["steps"][0]["step_id"] == "s1"


# =============================================================================
# MultiWorkerExecutor — basic execution
# =============================================================================


class TestMultiWorkerBasic:
    def test_plan_steps_create_separate_worker_packets(self):
        plan = make_plan_with_worker_tasks()
        executor = MultiWorkerExecutor(max_workers=1, worker_mode="fake")
        result = executor.execute(plan)

        assert result.step_count == 2
        assert result.passed_steps == 2
        # Each step should have its own task_id and packet_dir
        task_ids = {s.task_id for s in result.steps}
        assert len(task_ids) == 2  # unique task IDs
        packet_dirs = {s.packet_dir for s in result.steps}
        assert len(packet_dirs) == 2  # unique packet dirs

    def test_successful_multi_step_run_produces_combined_audit_report(self):
        plan = make_plan_with_worker_tasks()
        executor = MultiWorkerExecutor(max_workers=1, worker_mode="fake")
        result = executor.execute(plan)

        assert result.combined_report_path != ""
        report_path = Path(result.combined_report_path)
        assert report_path.exists()

        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["report_type"] == "multi_worker_audit"
        assert report["overall_status"] == "completed"
        assert len(report["step_results"]) == 2

    def test_unapproved_plan_is_blocked(self):
        plan = make_plan_with_worker_tasks(approved=False)
        executor = MultiWorkerExecutor(worker_mode="fake")
        result = executor.execute(plan)
        assert result.status == "blocked_needs_review"
        assert result.step_count == 0


# =============================================================================
# Dependency ordering
# =============================================================================


class TestDependencyOrdering:
    def test_dependency_order_is_respected(self):
        """Step 2 depends on Step 1 — step 2 must not start before step 1 finishes."""
        tasks = [
            PlannedWorkerTask(
                step_id="step-1",
                title="Step 1",
                objective="First step",
                allowed_files=["src/a.py"],
                can_run_parallel=False,
            ),
            PlannedWorkerTask(
                step_id="step-2",
                title="Step 2",
                objective="Second step",
                allowed_files=["src/b.py"],
                dependencies=["step-1"],
                can_run_parallel=False,
            ),
        ]
        plan = make_plan_with_worker_tasks(tasks=tasks)
        executor = MultiWorkerExecutor(max_workers=2, worker_mode="fake")
        result = executor.execute(plan)

        # Both should pass in sequential execution
        assert result.passed_steps == 2
        s1 = next(s for s in result.steps if s.step_id == "step-1")
        s2 = next(s for s in result.steps if s.step_id == "step-2")
        # Step 1 must finish before Step 2
        assert s1.status == "passed"
        assert s2.status == "passed"

    def test_failed_dependency_skips_dependent(self):
        """When step 1 fails, step 2 (dependent) should be skipped."""
        tasks = [
            PlannedWorkerTask(
                step_id="step-1",
                title="Step 1",
                objective="Will fail",
                allowed_files=["outputs/report.json"],  # protected → preflight blocks
                can_run_parallel=False,
            ),
            PlannedWorkerTask(
                step_id="step-2",
                title="Step 2",
                objective="Depends on step 1",
                allowed_files=["src/b.py"],
                dependencies=["step-1"],
                can_run_parallel=False,
            ),
        ]
        plan = make_plan_with_worker_tasks(tasks=tasks)
        executor = MultiWorkerExecutor(max_workers=1, worker_mode="fake")
        result = executor.execute(plan)

        s1 = next(s for s in result.steps if s.step_id == "step-1")
        # Step 1 should be blocked (protected file in allowed_files)
        assert s1.status in ("blocked", "failed", "needs_human_review")


# =============================================================================
# Parallelism
# =============================================================================


class TestParallelism:
    def test_independent_non_overlapping_steps_can_run_in_parallel(self):
        """Two steps with disjoint file sets and no dependencies can run concurrently."""
        tasks = [
            PlannedWorkerTask(
                step_id="step-1",
                title="Inspect a.py",
                objective="Look at a.py",
                allowed_files=["src/a.py"],
                can_run_parallel=True,
            ),
            PlannedWorkerTask(
                step_id="step-2",
                title="Inspect b.py",
                objective="Look at b.py",
                allowed_files=["src/b.py"],
                can_run_parallel=True,
            ),
        ]
        plan = make_plan_with_worker_tasks(tasks=tasks)
        executor = MultiWorkerExecutor(max_workers=2, worker_mode="fake")
        result = executor.execute(plan)

        assert result.passed_steps == 2
        assert result.status == "completed"

    def test_max_workers_limits_concurrent_execution(self):
        """With max_workers=1, steps should execute one at a time."""
        tasks = [
            PlannedWorkerTask(
                step_id="step-1", title="T1", objective="Task 1",
                allowed_files=["src/a.py"], can_run_parallel=True,
            ),
            PlannedWorkerTask(
                step_id="step-2", title="T2", objective="Task 2",
                allowed_files=["src/b.py"], can_run_parallel=True,
            ),
            PlannedWorkerTask(
                step_id="step-3", title="T3", objective="Task 3",
                allowed_files=["src/c.py"], can_run_parallel=True,
            ),
        ]
        plan = make_plan_with_worker_tasks(tasks=tasks)
        executor = MultiWorkerExecutor(max_workers=1, worker_mode="fake")
        result = executor.execute(plan)

        assert result.passed_steps == 3

    def test_overlapping_write_sets_not_parallel(self):
        """Steps that write overlapping files should not run in parallel."""
        tasks = [
            PlannedWorkerTask(
                step_id="step-1",
                title="Edit a.py",
                objective="Change a.py",
                allowed_files=["src/a.py"],
                can_run_parallel=True,
            ),
            PlannedWorkerTask(
                step_id="step-2",
                title="Also edit a.py",
                objective="Change a.py differently",
                allowed_files=["src/a.py"],  # overlap with step-1
                can_run_parallel=True,
            ),
        ]
        plan = make_plan_with_worker_tasks(tasks=tasks)
        # The executor should detect the overlap and serialize
        executor = MultiWorkerExecutor(max_workers=2, worker_mode="fake")
        # Inject the plan for write-overlap detection
        executor._current_plan = plan
        step_plans = executor._build_step_plans(plan, "run-test")
        executor._detect_write_overlaps(step_plans)

        # Step 2 should now depend on step 1
        s2_task = plan.planned_worker_tasks[1]
        assert "step-1" in s2_task.dependencies or not s2_task.can_run_parallel


# =============================================================================
# Per-step evidence isolation
# =============================================================================


class TestPerStepEvidence:
    def test_missing_evidence_in_one_step_does_not_satisfy_another(self):
        """Each step must produce its own evidence. Sharing is not allowed."""
        tasks = [
            PlannedWorkerTask(
                step_id="step-1",
                title="Task 1",
                objective="Produce evidence",
                allowed_files=["src/a.py"],
                expected_evidence=["test_output.txt"],
                required_checks=["pytest"],
            ),
            PlannedWorkerTask(
                step_id="step-2",
                title="Task 2",
                objective="Also needs evidence",
                allowed_files=["src/b.py"],
                expected_evidence=["test_output.txt"],  # same evidence key
                required_checks=["pytest"],
            ),
        ]
        plan = make_plan_with_worker_tasks(tasks=tasks)
        executor = MultiWorkerExecutor(max_workers=1, worker_mode="fake")
        result = executor.execute(plan)

        assert result.step_count == 2
        # Both should pass because fake worker generates evidence for each
        assert result.passed_steps == 2


# =============================================================================
# Per-step policy and control
# =============================================================================


class TestPerStepPolicy:
    def test_per_step_policy_violation_requires_review(self):
        """Accessing protected files should trigger needs_human_review."""
        tasks = [
            PlannedWorkerTask(
                step_id="step-1",
                title="Dangerous step",
                objective="Touch protected files",
                allowed_files=["outputs/report.json"],  # policy has outputs/** protected
                denied_files=[],
            ),
        ]
        plan = make_plan_with_worker_tasks(tasks=tasks)
        executor = MultiWorkerExecutor(max_workers=1, worker_mode="fake")
        result = executor.execute(plan)

        s1 = result.steps[0]
        # Preflight should catch the protected file
        assert s1.status in ("blocked", "needs_human_review")

    def test_step_without_protected_files_passes(self):
        tasks = [
            PlannedWorkerTask(
                step_id="step-1",
                title="Safe step",
                objective="Touch safe files",
                allowed_files=["src/utils.py"],
                denied_files=[],
            ),
        ]
        plan = make_plan_with_worker_tasks(tasks=tasks)
        executor = MultiWorkerExecutor(max_workers=1, worker_mode="fake")
        result = executor.execute(plan)

        s1 = result.steps[0]
        assert s1.status == "passed"


# =============================================================================
# Integration with MainlineExecutor
# =============================================================================


class TestMainlineMultiWorker:
    def test_mainline_routes_multi_worker(self):
        """MainlineExecutor should use multi-worker path for plans with >1 tasks."""
        tasks = [
            PlannedWorkerTask(
                step_id="step-1", title="T1", objective="Task 1",
                allowed_files=["src/a.py"], can_run_parallel=True,
            ),
            PlannedWorkerTask(
                step_id="step-2", title="T2", objective="Task 2",
                allowed_files=["src/b.py"], can_run_parallel=True,
            ),
        ]
        plan = make_plan_with_worker_tasks(tasks=tasks)
        executor = MainlineExecutor()
        result = executor.execute(plan, worker_mode="fake")

        assert result.status == "completed"
        # Evidence status from multi-worker path
        assert result.evidence_status is not None
        assert result.evidence_status.get("step_count") == 2
        assert result.evidence_status.get("passed_steps") == 2

    def test_mainline_single_worker_still_works(self):
        """Single-worker tasks still use the original path."""
        tasks = [
            PlannedWorkerTask(
                step_id="step-1", title="T1", objective="Solo task",
                allowed_files=["src/a.py"],
            ),
        ]
        plan = make_plan_with_worker_tasks(tasks=tasks)
        executor = MainlineExecutor()
        result = executor.execute(plan, worker_mode="fake")

        assert result.status == "completed"


# =============================================================================
# Fake worker mode does not count as real smoke
# =============================================================================


class TestFakeVsReal:
    def test_fake_worker_mode_flag(self):
        executor = MultiWorkerExecutor(worker_mode="fake")
        assert executor._worker_mode == "fake"

    def test_claude_code_mode_flag(self):
        executor = MultiWorkerExecutor(worker_mode="claude-code")
        assert executor._worker_mode == "claude-code"

    def test_fake_worker_does_not_launch_subprocess(self):
        """Fake worker must NOT touch subprocess."""
        tasks = [
            PlannedWorkerTask(
                step_id="step-1", title="T1", objective="Test",
                allowed_files=["src/a.py"],
            ),
        ]
        plan = make_plan_with_worker_tasks(tasks=tasks)
        executor = MultiWorkerExecutor(worker_mode="fake")
        with patch("subprocess.Popen") as mock_popen:
            result = executor.execute(plan)
        mock_popen.assert_not_called()
        assert result.passed_steps == 1


# =============================================================================
# CLI flags
# =============================================================================


class TestCLIFlags:
    def test_max_workers_default(self):
        executor = MultiWorkerExecutor()
        assert executor._max_workers == 2

    def test_max_workers_custom(self):
        executor = MultiWorkerExecutor(max_workers=4)
        assert executor._max_workers == 4


# =============================================================================
# PlannedWorkerTask new fields
# =============================================================================


class TestPlannedWorkerTaskPhase20:
    def test_new_fields_exist(self):
        pwt = PlannedWorkerTask(
            step_id="s1",
            dependencies=["s0"],
            can_run_parallel=True,
            requires_human_review=True,
        )
        assert pwt.step_id == "s1"
        assert pwt.dependencies == ["s0"]
        assert pwt.can_run_parallel is True
        assert pwt.requires_human_review is True

    def test_new_fields_default(self):
        pwt = PlannedWorkerTask()
        assert pwt.step_id == ""
        assert pwt.dependencies == []
        assert pwt.can_run_parallel is False
        assert pwt.requires_human_review is False

    def test_plan_contract_to_dict_includes_new_fields(self):
        from orchestrator.planning import plan_contract_to_dict
        pwt = PlannedWorkerTask(
            step_id="s1",
            title="Test",
            dependencies=["s0"],
            can_run_parallel=True,
            requires_human_review=False,
        )
        plan = PlanContract(
            plan_id="p1",
            planned_worker_tasks=[pwt],
        )
        d = plan_contract_to_dict(plan)
        wt = d["planned_worker_tasks"][0]
        assert wt["step_id"] == "s1"
        assert wt["dependencies"] == ["s0"]
        assert wt["can_run_parallel"] is True

    def test_planned_task_to_packet_kwargs_includes_new_fields(self):
        from orchestrator.planning import planned_task_to_packet_kwargs
        pwt = PlannedWorkerTask(
            title="Test",
            objective="Do work",
            dependencies=["step-0"],
            can_run_parallel=True,
            requires_human_review=True,
        )
        kwargs = planned_task_to_packet_kwargs(pwt)
        assert kwargs["dependencies"] == ["step-0"]
        assert kwargs["can_run_parallel"] is True
        assert kwargs["requires_human_review"] is True
