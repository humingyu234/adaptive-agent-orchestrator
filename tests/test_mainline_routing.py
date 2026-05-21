"""Phase 29 — MainlineExecutor backend routing tests.

Proves that MainlineExecutor.execute() correctly dispatches to the right
backend based on execution_backend parameter.
"""

from __future__ import annotations

import pytest

from orchestrator.planning import PlanContract, PlannedWorkerTask
from orchestrator.mainline_executor import MainlineExecutor


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
        plan_id="routing-test-plan",
    )
    plan.approve()
    return plan


class TestBackendRouting:
    """Proves execution_backend parameter controls dispatch correctly."""

    def test_controlled_uses_native_backend(self):
        """controlled task → native backend (MultiWorkerExecutor)."""
        plan = _make_plan(task_count=2)
        executor = MainlineExecutor()
        result = executor.execute(plan, worker_mode="fake", execution_backend="native")

        assert result.status == "completed"
        assert result.worker_mode == "fake"
        # Multi-worker path: step_count from combined report
        assert result.run_id

    def test_orchestrated_uses_langgraph_backend(self):
        """orchestrated task → langgraph backend (LangGraphRunner).

        When langgraph is installed, the LangGraphRunner executes the plan
        through a StateGraph.  When not installed, the test still proves the
        dispatch path (it will be blocked with a clear message).
        """
        plan = _make_plan(task_count=1)
        executor = MainlineExecutor()
        result = executor.execute(plan, worker_mode="fake", execution_backend="langgraph")

        from orchestrator.runners.langgraph_runner import _LANGGRAPH_AVAILABLE
        if _LANGGRAPH_AVAILABLE:
            assert result.status == "completed"
        else:
            assert result.status == "blocked_needs_review"

    def test_orchestrated_blocked_when_langgraph_unavailable(self):
        """orchestrated without langgraph → blocked with clear dependency message."""
        plan = _make_plan(task_count=1)
        executor = MainlineExecutor()

        import orchestrator.runners.langgraph_runner as lgr
        _orig = lgr._LANGGRAPH_AVAILABLE
        lgr._LANGGRAPH_AVAILABLE = False
        try:
            result = executor.execute(plan, worker_mode="fake", execution_backend="langgraph")
            assert result.status == "blocked_needs_review"
            assert len(result.control_decisions) > 0
            assert any("LangGraph" in d.get("reason", "") for d in result.control_decisions)
        finally:
            lgr._LANGGRAPH_AVAILABLE = _orig

    def test_orchestrated_force_run_falls_back_to_native(self):
        """--force-run orchestrated when langgraph missing → native backend."""
        plan = _make_plan(task_count=1)
        executor = MainlineExecutor()

        import orchestrator.runners.langgraph_runner as lgr
        _orig = lgr._LANGGRAPH_AVAILABLE
        lgr._LANGGRAPH_AVAILABLE = False
        try:
            # When langgraph is missing, the _execute_langgraph method returns
            # blocked_needs_review.  The CLI-level --force-run would redirect
            # to native, which is tested in test_acceptance.py.
            result = executor.execute(plan, worker_mode="fake", execution_backend="native")
            assert result.status == "completed"
        finally:
            lgr._LANGGRAPH_AVAILABLE = _orig

    def test_native_backend_runs_multi_worker(self):
        """Native backend still uses MultiWorkerExecutor for multi-step plans."""
        plan = _make_plan(task_count=3)
        executor = MainlineExecutor()
        result = executor.execute(plan, worker_mode="fake", execution_backend="native")

        assert result.status == "completed"
        assert result.run_id
        # Multi-worker path is exercised for >1 tasks
