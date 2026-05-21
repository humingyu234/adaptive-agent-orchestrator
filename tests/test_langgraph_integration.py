"""Phase 29 — LangGraph integration tests.

Proves that MainlineExecutor correctly delegates to LangGraphRunner and
converts results.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orchestrator.planning import PlanContract, PlannedWorkerTask
from orchestrator.mainline_executor import MainlineExecutor, MainlineResult


def _make_plan(task_count: int = 2):
    tasks = [
        PlannedWorkerTask(
            step_id=f"step-{i}",
            title=f"Step {i}",
            objective=f"Work {i}",
            allowed_files=["src/utils.py"],
        )
        for i in range(task_count)
    ]
    plan = PlanContract(
        objective="Test plan",
        steps=[f"Step {i}" for i in range(task_count)],
        planned_worker_tasks=tasks,
        plan_id="lg-integration-plan",
    )
    plan.approve()
    return plan


class TestLangGraphIntegration:
    """Proves MainlineExecutor ↔ LangGraphRunner integration correctness."""

    def test_execute_calls_langgraph_for_langgraph_backend(self):
        """MainlineExecutor.execute(execution_backend='langgraph') routes to _execute_langgraph."""
        plan = _make_plan(task_count=1)
        executor = MainlineExecutor()

        with patch.object(executor, "_execute_langgraph",
                          wraps=executor._execute_langgraph) as spy:
            executor.execute(plan, worker_mode="fake", execution_backend="langgraph")
            spy.assert_called_once()

    def test_native_backend_skips_langgraph_path(self):
        """MainlineExecutor.execute(execution_backend='native') does NOT call _execute_langgraph."""
        plan = _make_plan(task_count=1)
        executor = MainlineExecutor()

        with patch.object(executor, "_execute_langgraph",
                          wraps=executor._execute_langgraph) as spy:
            executor.execute(plan, worker_mode="fake", execution_backend="native")
            spy.assert_not_called()

    def test_execute_langgraph_calls_runner_run(self):
        """_execute_langgraph correctly instantiates and calls LangGraphRunner.run()."""
        plan = _make_plan(task_count=1)
        executor = MainlineExecutor()

        from orchestrator.runners.langgraph_runner import _LANGGRAPH_AVAILABLE
        if not _LANGGRAPH_AVAILABLE:
            pytest.skip("LangGraph not installed")

        with patch("orchestrator.runners.langgraph_runner.LangGraphRunner.run",
                   return_value=MagicMock(
                       run_id="test-run",
                       status="completed",
                       steps_completed=1,
                       evidence_paths=[],
                       control_events=[],
                   )) as mock_run:
            result = executor._execute_langgraph(plan, worker_mode="fake")
            mock_run.assert_called_once()
            # worker_mode and worker_registry must propagate to the runner call
            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs.get("worker_mode") == "fake"
            assert "worker_registry" in call_kwargs, "worker_registry must be passed to runner.run()"
            assert len(call_kwargs["worker_registry"]) == 1, \
                "worker_registry must have one entry per planned task"

    def test_convert_langgraph_result_maps_statuses(self):
        """_convert_langgraph_result correctly maps RunnerResult → MainlineResult."""
        from orchestrator.runners.langgraph_runner import RunnerResult

        plan = _make_plan(task_count=2)
        executor = MainlineExecutor()

        # Test completed mapping
        completed = RunnerResult(
            run_id="r1", status="completed", steps_completed=2,
            evidence_paths=["/tmp/ev1.json", "/tmp/ev2.json"],
            control_events=[{"event": "test", "passed": True}],
        )
        mr = executor._convert_langgraph_result(completed, plan, "fake")
        assert mr.status == "completed"
        assert mr.run_id == "r1"
        assert "/tmp/ev1.json" in mr.evidence_path
        assert "/tmp/ev2.json" in mr.evidence_path
        assert len(mr.control_decisions) == 1

        # Test failed mapping
        failed = RunnerResult(
            run_id="r2", status="failed", steps_completed=0,
            evidence_paths=[], control_events=[],
        )
        mr2 = executor._convert_langgraph_result(failed, plan, "claude-code")
        assert mr2.status == "blocked_failed"

        # Test needs_human_review mapping
        review = RunnerResult(
            run_id="r3", status="needs_human_review", steps_completed=1,
            evidence_paths=[], control_events=[],
        )
        mr3 = executor._convert_langgraph_result(review, plan, "packet")
        assert mr3.status == "blocked_needs_review"

    def test_native_backend_runs_multi_worker_for_multiple_tasks(self):
        """Native backend dispatches to _execute_multi_worker for >1 tasks."""
        plan = _make_plan(task_count=3)
        executor = MainlineExecutor()

        with patch.object(executor, "_execute_multi_worker",
                          wraps=executor._execute_multi_worker) as spy:
            result = executor.execute(plan, worker_mode="fake", execution_backend="native")
            spy.assert_called_once()
            assert result.status == "completed"

    def test_worker_registry_dispatches_to_execute_worker(self):
        """Each entry in worker_registry calls _execute_worker with a valid packet."""
        plan = _make_plan(task_count=1)
        executor = MainlineExecutor()

        from orchestrator.runners.langgraph_runner import _LANGGRAPH_AVAILABLE
        if not _LANGGRAPH_AVAILABLE:
            pytest.skip("LangGraph not installed")

        # Execute through _execute_langgraph with a spy on _execute_worker
        with patch.object(executor, "_execute_worker",
                          wraps=executor._execute_worker) as spy:
            result = executor._execute_langgraph(plan, worker_mode="fake")
            # The worker_registry callable must have been invoked
            spy.assert_called()
            call_args = spy.call_args
            packet = call_args.kwargs.get("packet") or (call_args.args[0] if call_args.args else None)
            assert packet is not None, "worker_registry must pass a WorkerTaskPacket"
            assert packet.task_id == "step-0"
            assert result.status == "completed"

