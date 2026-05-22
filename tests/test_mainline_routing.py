"""Phase 29 — Task Router → MainlineExecutor routing tests.

Proves the router decision automatically selects the right execution path.
_resolve_execution_path() returns a 3-tuple:
(path, effective_worker_mode, execution_backend).
"""

from __future__ import annotations


class TestP01RouterMainlineAutoConnect:
    """Proves the router decision automatically selects the right execution path.

    execution_backend is:
      "native" for controlled mode (MultiWorkerExecutor)
      "langgraph" for orchestrated mode (LangGraphRunner)
      None for legacy / noop / blocked paths
    """

    @staticmethod
    def _make_decision(**overrides):
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

    @staticmethod
    def _resolve(decision, explicit_worker_mode=None, force_run=False):
        from orchestrator.__main__ import _resolve_execution_path

        return _resolve_execution_path(decision, explicit_worker_mode, force_run)

    def test_controlled_route_auto_mainline(self):
        decision = self._make_decision(run_mode="controlled")
        path, worker, backend = self._resolve(decision)
        assert path == "mainline"
        assert worker == "fake"
        assert backend == "native"

    def test_orchestrated_route_to_langgraph_backend(self):
        decision = self._make_decision(run_mode="orchestrated")
        path, worker, backend = self._resolve(decision)
        assert path == "mainline"
        assert worker == "fake"
        from orchestrator.runners.langgraph_runner import _LANGGRAPH_AVAILABLE
        if _LANGGRAPH_AVAILABLE:
            assert backend == "langgraph"
        else:
            assert path == "blocked"
            assert backend is None

    def test_orchestrated_route_with_force_run_falls_back_native(self):
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

    def test_explicit_worker_mode_overrides_off_route(self):
        decision = self._make_decision(run_mode="off")
        path, worker, backend = self._resolve(decision, explicit_worker_mode="fake")
        assert path == "mainline"
        assert worker == "fake"
        assert backend == "native"

    def test_explicit_worker_mode_overrides_log_route(self):
        decision = self._make_decision(run_mode="log")
        path, worker, backend = self._resolve(decision, explicit_worker_mode="claude-code")
        assert path == "mainline"
        assert worker == "claude-code"
        assert backend == "native"

    def test_explicit_worker_mode_overrides_controlled_default(self):
        decision = self._make_decision(run_mode="controlled")
        path, worker, backend = self._resolve(decision, explicit_worker_mode="packet")
        assert path == "mainline"
        assert worker == "packet"
        assert backend == "native"

    def test_force_run_off_route_falls_through_to_mainline(self):
        decision = self._make_decision(run_mode="off")
        path, worker, backend = self._resolve(decision, force_run=True)
        assert path == "legacy"
        assert worker is None
        assert backend is None

    def test_orchestrated_without_langgraph_is_blocked(self):
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

    def test_non_standard_run_mode_falls_to_legacy(self):
        decision = self._make_decision(run_mode="custom_mode")
        path, worker, backend = self._resolve(decision)
        assert path == "legacy"
        assert worker is None
        assert backend is None
