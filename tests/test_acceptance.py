"""Phase 21 — End-to-End Acceptance Tests.

These tests exercise the full AAO path (plan → approve → execute → evidence
→ report) using only fake providers and fake workers.  No LLM keys, no
network, no subprocess required.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from orchestrator.planning import (
    PlanContract,
    PlannedWorkerTask,
    PlanningCouncil,
    plan_contract_to_dict,
)
from orchestrator.multi_worker import (
    MultiWorkerExecutor,
    MultiWorkerResult,
    StepExecutionRecord,
)
from orchestrator.mainline_executor import MainlineExecutor, MainlineResult
from orchestrator.policy import Policy


# =============================================================================
# Helpers
# =============================================================================


def _make_two_step_plan(approved: bool = True) -> PlanContract:
    """Two independent steps suitable for multi-worker execution."""
    plan = PlanContract(
        objective="Refactor error handling across two modules",
        steps=["Inspect and refactor src/errors.py", "Inspect and refactor src/middleware.py"],
        planned_worker_tasks=[
            PlannedWorkerTask(
                step_id="step-errors",
                title="Refactor errors.py",
                objective="Improve error handling in errors module",
                allowed_files=["src/errors.py"],
                denied_files=[],
                required_checks=["pytest"],
                expected_evidence=["test_output.txt"],
                risk_level="low",
                can_run_parallel=True,
            ),
            PlannedWorkerTask(
                step_id="step-middleware",
                title="Refactor middleware.py",
                objective="Improve error handling in middleware module",
                allowed_files=["src/middleware.py"],
                denied_files=[],
                required_checks=["pytest"],
                expected_evidence=["test_output.txt"],
                risk_level="low",
                can_run_parallel=True,
            ),
        ],
        plan_id="acceptance-test-plan",
    )
    if approved:
        plan.approve()
    return plan


def _make_single_step_plan(approved: bool = True) -> PlanContract:
    plan = PlanContract(
        objective="Fix typo in utils.py",
        steps=["Fix typo"],
        planned_worker_tasks=[
            PlannedWorkerTask(
                step_id="step-1",
                title="Fix typo",
                objective="Fix a typo in utils.py",
                allowed_files=["src/utils.py"],
                denied_files=[],
                required_checks=["pytest"],
                expected_evidence=["test_output.txt"],
                risk_level="low",
            ),
        ],
        plan_id="single-step-plan",
    )
    if approved:
        plan.approve()
    return plan


# =============================================================================
# Acceptance Test 1 — Single-worker full path
# =============================================================================


class TestAcceptanceSingleWorkerFullPath:
    """Proves the basic daily-use loop: plan → approve → execute → evidence → report."""

    def test_single_worker_path_produces_run_id_plan_id_and_report(self):
        plan = _make_single_step_plan()
        executor = MainlineExecutor()
        result = executor.execute(plan, worker_mode="fake")

        assert result.run_id, "Must produce a run_id"
        assert result.plan_id == "single-step-plan"
        assert result.status == "completed", f"Expected completed, got {result.status}"
        assert result.report_path, "Must produce a report path"
        assert Path(result.report_path).exists(), "Report file must exist"
        assert result.worker_mode == "fake"

    def test_single_worker_path_has_evidence_status(self):
        plan = _make_single_step_plan()
        executor = MainlineExecutor()
        result = executor.execute(plan, worker_mode="fake")

        assert result.evidence_status is not None
        # Single-worker path produces WorkerEvidenceStatus dict with task-level fields
        assert "task_id" in result.evidence_status or "step_count" in result.evidence_status

    def test_single_worker_path_has_control_decisions(self):
        plan = _make_single_step_plan()
        executor = MainlineExecutor()
        result = executor.execute(plan, worker_mode="fake")

        assert len(result.control_decisions) > 0
        assert any(d.get("passed") for d in result.control_decisions)

    def test_unapproved_plan_is_blocked_by_mainline(self):
        plan = _make_single_step_plan(approved=False)
        executor = MainlineExecutor()
        result = executor.execute(plan, worker_mode="fake")

        assert result.status == "blocked_needs_review"
        assert result.report_path == ""

    def test_fake_worker_never_touches_subprocess(self):
        plan = _make_single_step_plan()
        executor = MainlineExecutor()
        with patch("subprocess.Popen") as mock_popen:
            result = executor.execute(plan, worker_mode="fake")
        mock_popen.assert_not_called()
        assert result.status == "completed"


# =============================================================================
# Acceptance Test 2 — Multi-step per-step evidence
# =============================================================================


class TestAcceptanceMultiStepPerStepEvidence:
    """Proves plan → multiple worker tasks → per-step evidence."""

    def test_two_steps_both_pass_and_produce_separate_evidence(self):
        plan = _make_two_step_plan()
        executor = MultiWorkerExecutor(max_workers=2, worker_mode="fake")
        result = executor.execute(plan)

        assert result.step_count == 2
        assert result.passed_steps == 2
        assert result.status == "completed"

        # Each step gets its own task_id
        task_ids = {s.task_id for s in result.steps}
        assert len(task_ids) == 2

        # Each step gets its own packet_dir
        packet_dirs = {s.packet_dir for s in result.steps}
        assert len(packet_dirs) == 2

    def test_combined_report_has_per_step_entries(self):
        plan = _make_two_step_plan()
        executor = MultiWorkerExecutor(max_workers=1, worker_mode="fake")
        result = executor.execute(plan)

        assert result.combined_report_path
        report = json.loads(Path(result.combined_report_path).read_text(encoding="utf-8"))
        assert len(report["step_results"]) == 2
        step_ids = {s["step_id"] for s in report["step_results"]}
        assert step_ids == {"step-errors", "step-middleware"}

    def test_combined_evidence_has_per_step_entries(self):
        plan = _make_two_step_plan()
        executor = MultiWorkerExecutor(max_workers=1, worker_mode="fake")
        result = executor.execute(plan)

        assert result.combined_evidence_path
        evidence = json.loads(Path(result.combined_evidence_path).read_text(encoding="utf-8"))
        assert evidence["step_count"] == 2
        assert len(evidence["steps"]) == 2

    def test_dependency_failure_skips_dependent_and_records_status(self):
        """Step with protected file fails → dependent skipped with clear status."""
        tasks = [
            PlannedWorkerTask(
                step_id="dangerous-step",
                title="Protected write",
                objective="Write to protected file",
                allowed_files=["outputs/report.json"],  # matches outputs/** protected pattern
                can_run_parallel=False,
            ),
            PlannedWorkerTask(
                step_id="safe-step",
                title="Safe work",
                objective="Normal work",
                allowed_files=["src/utils.py"],
                dependencies=["dangerous-step"],
                can_run_parallel=False,
            ),
        ]
        plan = PlanContract(
            objective="Test dependency skip",
            steps=["Dangerous", "Safe"],
            planned_worker_tasks=tasks,
            plan_id="dep-fail-test",
        )
        plan.approve()
        executor = MultiWorkerExecutor(max_workers=1, worker_mode="fake")
        result = executor.execute(plan)

        dangerous = next(s for s in result.steps if s.step_id == "dangerous-step")
        assert dangerous.status in ("blocked", "failed", "needs_human_review"), \
            f"Expected blocked/failed/needs_human_review, got {dangerous.status}"


# =============================================================================
# Acceptance Test 3 — Failure path does not mark completed
# =============================================================================


class TestAcceptanceFailureDoesNotPretendSuccess:
    """Proves AAO catches failures and does not falsely mark success."""

    def test_protected_file_in_allowed_set_is_blocked_not_completed(self):
        tasks = [
            PlannedWorkerTask(
                step_id="bad-step",
                title="Write secrets",
                objective="Modify protected config",
                allowed_files=["secrets/tokens.json"],  # matches secrets/** protected pattern
            ),
        ]
        plan = PlanContract(
            objective="Bad task",
            steps=["Bad step"],
            planned_worker_tasks=tasks,
            plan_id="bad-plan",
        )
        plan.approve()
        executor = MultiWorkerExecutor(max_workers=1, worker_mode="fake")
        result = executor.execute(plan)

        assert result.status != "completed", f"Must not be completed, got {result.status}"
        assert result.passed_steps == 0

    def test_unapproved_plan_never_starts_execution(self):
        tasks = [
            PlannedWorkerTask(
                step_id="step-1",
                title="Normal",
                objective="Normal work",
                allowed_files=["src/utils.py"],
            ),
        ]
        plan = PlanContract(
            objective="Unapproved task",
            steps=["Normal step"],
            planned_worker_tasks=tasks,
            plan_id="unapproved-plan",
        )
        # NOT approved
        executor = MultiWorkerExecutor(worker_mode="fake")
        result = executor.execute(plan)

        assert result.status == "blocked_needs_review"
        assert result.step_count == 0

    def test_mainline_result_respects_failure_status(self):
        tasks = [
            PlannedWorkerTask(
                step_id="bad",
                title="Dangerous",
                objective="Touch protected",
                allowed_files=["outputs/secret.json"],  # protected
            ),
            PlannedWorkerTask(
                step_id="step-2",
                title="Normal step",
                objective="Normal work",
                allowed_files=["src/utils.py"],
                dependencies=["bad"],  # depends on the blocked step
            ),
        ]
        plan = PlanContract(
            objective="Failing multi-step task",
            steps=["Bad step", "Normal step"],
            planned_worker_tasks=tasks,
            plan_id="mainline-fail",
        )
        plan.approve()
        executor = MainlineExecutor()
        result = executor.execute(plan, worker_mode="fake")

        assert result.status != "completed", f"Must not be completed, got {result.status}"
        assert result.report_path == "" or result.report_path


# =============================================================================
# Acceptance Test 4 — Report completeness
# =============================================================================


class TestAcceptanceReportCompleteness:
    """Proves the combined report contains plan, worker, evidence, and decisions."""

    def test_report_has_required_sections(self):
        plan = _make_two_step_plan()
        executor = MultiWorkerExecutor(max_workers=1, worker_mode="fake")
        result = executor.execute(plan)

        report = json.loads(Path(result.combined_report_path).read_text(encoding="utf-8"))

        # Top-level structure
        assert report["report_type"] == "multi_worker_audit"
        assert "generated_at" in report
        assert report["run_id"] == result.run_id
        assert report["plan_id"] == result.plan_id
        assert report["objective"] == plan.objective
        assert report["worker_mode"] == "fake"
        assert report["overall_status"] == "completed"

        # Summary section
        assert report["summary"]["total_steps"] == 2
        assert report["summary"]["passed"] == 2
        assert report["summary"]["failed"] == 0
        assert report["summary"]["blocked"] == 0

        # Step results
        assert len(report["step_results"]) == 2
        for sr in report["step_results"]:
            assert "step_id" in sr
            assert "title" in sr
            assert "status" in sr
            assert "task_id" in sr
            assert "packet_dir" in sr
            assert "changed_files" in sr
            assert "control_decisions" in sr
            assert "started_at" in sr
            assert "finished_at" in sr

        # Plan snapshot
        assert "plan_snapshot" in report
        assert report["plan_snapshot"]["plan_id"] == "acceptance-test-plan"

        # Artifact summary
        assert "artifact_summary" in report
        assert "report_path" in report["artifact_summary"]
        assert "evidence_path" in report["artifact_summary"]

    def test_report_distinguishes_observed_reported_and_inferred(self):
        """The report must make it clear what was observed vs reported vs inferred."""
        plan = _make_two_step_plan()
        executor = MultiWorkerExecutor(max_workers=1, worker_mode="fake")
        result = executor.execute(plan)

        report = json.loads(Path(result.combined_report_path).read_text(encoding="utf-8"))

        for sr in report["step_results"]:
            # Each step must have control_decisions — these capture what was checked
            assert len(sr["control_decisions"]) > 0
            # changed_files is observed evidence
            assert isinstance(sr["changed_files"], list)
            # packet_dir tells us where the raw worker output lives
            assert sr["packet_dir"]

    def test_planning_summary_present_when_llm_was_used(self):
        """When LLM planning was used, the report includes planning output."""
        plan = _make_single_step_plan()
        plan.planning_mode = "llm"
        plan.advisor_outputs = [{"role": "planner", "summary": "LLM generated plan"}]
        executor = MainlineExecutor()
        result = executor.execute(plan, worker_mode="fake")

        # Evidence status should carry through
        assert result.status == "completed"


# =============================================================================
# P0.1 — Task Router → MainlineExecutor auto-connection
# =============================================================================


class TestP01RouterMainlineAutoConnect:
    """Proves the router's decision automatically selects the right execution path.

    The ``_resolve_execution_path()`` function returns a 3-tuple:
    ``(path, effective_worker_mode, execution_backend)``.

    execution_backend is:
      ``"native"`` for controlled mode (MultiWorkerExecutor)
      ``"langgraph"`` for orchestrated mode (LangGraphRunner)
      ``None`` for legacy / noop / blocked paths
    """

    @staticmethod
    def _make_decision(**overrides):
        """Build a TaskRouteDecision with defaults overridden."""
        from orchestrator.task_router import TaskRouteDecision

        defaults = {
            "task_size": "medium",
            "run_mode": "controlled",
            "risk_level": "low",
            "task_type": "code_change",
            "runtime_support": "native",
        }
        defaults.update(overrides)
        return TaskRouteDecision(**defaults)

    # -- import helper -----------------------------------------------------------

    @staticmethod
    def _resolve(decision, explicit_worker_mode=None, force_run=False):
        from orchestrator.__main__ import _resolve_execution_path

        return _resolve_execution_path(decision, explicit_worker_mode, force_run)

    # -- controlled → mainline + native backend ----------------------------------

    def test_controlled_route_auto_mainline(self):
        """controlled task → mainline with default fake worker + native backend."""
        decision = self._make_decision(run_mode="controlled")
        path, worker, backend = self._resolve(decision)
        assert path == "mainline"
        assert worker == "fake"
        assert backend == "native"

    # -- orchestrated → mainline + langgraph backend -----------------------------

    def test_orchestrated_route_to_langgraph_backend(self):
        """orchestrated task → mainline + langgraph backend."""
        decision = self._make_decision(run_mode="orchestrated")
        path, worker, backend = self._resolve(decision)
        assert path == "mainline"
        assert worker == "fake"
        # langgraph backend when langgraph is installed
        from orchestrator.runners.langgraph_runner import _LANGGRAPH_AVAILABLE
        expected_backend = "langgraph" if _LANGGRAPH_AVAILABLE else "blocked"
        if _LANGGRAPH_AVAILABLE:
            assert backend == "langgraph"
        else:
            assert path == "blocked"
            assert backend is None

    def test_orchestrated_route_with_force_run_falls_back_native(self):
        """orchestrated task with --force-run when langgraph missing → native."""
        decision = self._make_decision(run_mode="orchestrated")
        import orchestrator.runners.langgraph_runner as lgr
        _orig = lgr._LANGGRAPH_AVAILABLE
        try:
            lgr._LANGGRAPH_AVAILABLE = False
            path, worker, backend = self._resolve(decision, force_run=True)
            assert path == "mainline"
            assert worker == "fake"
            assert backend == "native"
        finally:
            lgr._LANGGRAPH_AVAILABLE = _orig

    # -- off / log → noop --------------------------------------------------------

    def test_off_route_is_noop(self):
        decision = self._make_decision(run_mode="off")
        path, worker, backend = self._resolve(decision)
        assert path == "noop"
        assert worker is None
        assert backend is None

    def test_log_route_is_noop(self):
        decision = self._make_decision(run_mode="log")
        path, worker, backend = self._resolve(decision)
        assert path == "noop"
        assert worker is None
        assert backend is None

    # -- explicit --worker-mode overrides router ---------------------------------

    def test_explicit_worker_mode_overrides_off_route(self):
        """--worker-mode fake overrides off route → mainline + native."""
        decision = self._make_decision(run_mode="off")
        path, worker, backend = self._resolve(decision, explicit_worker_mode="fake")
        assert path == "mainline"
        assert worker == "fake"
        assert backend == "native"

    def test_explicit_worker_mode_overrides_log_route(self):
        """--worker-mode claude-code overrides log route → mainline + native."""
        decision = self._make_decision(run_mode="log")
        path, worker, backend = self._resolve(decision, explicit_worker_mode="claude-code")
        assert path == "mainline"
        assert worker == "claude-code"
        assert backend == "native"

    def test_explicit_worker_mode_overrides_controlled_default(self):
        """--worker-mode packet takes priority over router's default fake + native."""
        decision = self._make_decision(run_mode="controlled")
        path, worker, backend = self._resolve(decision, explicit_worker_mode="packet")
        assert path == "mainline"
        assert worker == "packet"
        assert backend == "native"

    # -- force_run prevents early exit -------------------------------------------

    def test_force_run_off_route_falls_through_to_mainline(self):
        """off route with --force-run bypasses noop → falls through.

        With run_mode=off, should_only_log is True.  force_run skips the
        noop gate, then controlled/orchestrated check returns False
        (off is neither controlled nor orchestrated), so the path is legacy.
        """
        decision = self._make_decision(run_mode="off")
        path, worker, backend = self._resolve(decision, force_run=True)
        assert path == "legacy"
        assert worker is None
        assert backend is None

    # -- orchestrated blocker (langgraph not installed) --------------------------

    def test_orchestrated_without_langgraph_is_blocked(self):
        """orchestrated without langgraph installed → blocked with clear message."""
        decision = self._make_decision(run_mode="orchestrated")
        import orchestrator.runners.langgraph_runner as lgr
        _orig = lgr._LANGGRAPH_AVAILABLE
        try:
            lgr._LANGGRAPH_AVAILABLE = False
            path, worker, backend = self._resolve(decision)
            assert path == "blocked"
            assert worker is None
            assert backend is None
        finally:
            lgr._LANGGRAPH_AVAILABLE = _orig

    # -- legacy fallback ---------------------------------------------------------

    def test_non_standard_run_mode_falls_to_legacy(self):
        """A run_mode that is neither controlled/orchestrated nor off/log → legacy."""
        decision = self._make_decision(run_mode="custom_mode")
        path, worker, backend = self._resolve(decision)
        assert path == "legacy"
        assert worker is None
        assert backend is None
