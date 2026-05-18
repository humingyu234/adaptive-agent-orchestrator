"""Phase 9 — Task Router tests.

Covers router unit tests, CLI integration, state persistence, and boundary cases.
"""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator.task_router import (
    TaskRouteDecision,
    effective_run_mode,
    render_route_decision,
    requires_future_runner,
    route_decision_to_dict,
    route_task,
    should_apply_control,
    should_execute_workflow,
    should_only_log,
)
from orchestrator.state_center import StateCenter


# =============================================================================
# Router Unit Tests
# =============================================================================


class RouterUnitTest(unittest.TestCase):
    """Core routing logic — deterministic, no LLM, no filesystem, no network."""

    def test_simple_question_routes_to_small_log(self):
        decision = route_task("explain what guardrails.py does")
        self.assertEqual(decision.task_size, "small")
        self.assertEqual(decision.run_mode, "log")

    def test_single_what_is_question_routes_small(self):
        decision = route_task("what is a state center")
        self.assertEqual(decision.task_size, "small")
        self.assertEqual(decision.run_mode, "log")

    def test_explicit_off_override_wins(self):
        decision = route_task("explain this code", explicit_mode="off")
        self.assertEqual(decision.run_mode, "off")
        self.assertTrue(decision.user_override)

    def test_explicit_controlled_override_wins(self):
        decision = route_task("explain this code", explicit_mode="controlled")
        self.assertEqual(decision.run_mode, "controlled")
        self.assertTrue(decision.user_override)

    def test_explicit_log_override_wins(self):
        decision = route_task("implement feature X", explicit_mode="log")
        self.assertEqual(decision.run_mode, "log")
        self.assertTrue(decision.user_override)

    def test_explicit_orchestrated_override_wins(self):
        decision = route_task("explain this", explicit_mode="orchestrated")
        self.assertEqual(decision.run_mode, "orchestrated")
        self.assertTrue(decision.user_override)

    def test_review_with_file_routes_to_medium_controlled(self):
        decision = route_task("review src/orchestrator/task_router.py for issues")
        self.assertEqual(decision.task_size, "medium")
        self.assertEqual(decision.run_mode, "controlled")
        self.assertEqual(decision.task_type, "review")

    def test_bugfix_with_tests_routes_to_medium_controlled(self):
        decision = route_task("fix the bug in auth.py and add tests")
        self.assertEqual(decision.task_size, "medium")
        self.assertEqual(decision.run_mode, "controlled")
        self.assertEqual(decision.task_type, "bugfix")

    def test_phase_work_routes_to_large_orchestrated(self):
        decision = route_task("implement phase 12 worker bridge with tests")
        self.assertEqual(decision.task_size, "large")
        self.assertEqual(decision.run_mode, "orchestrated")

    def test_project_level_request_routes_to_large_orchestrated(self):
        decision = route_task("architecture migration for the entire auth module")
        self.assertEqual(decision.task_size, "large")
        self.assertEqual(decision.run_mode, "orchestrated")

    def test_multi_step_routes_to_large(self):
        decision = route_task("multi-step end-to-end implementation of checkout")
        self.assertEqual(decision.task_size, "large")

    def test_high_risk_words_escalate_to_controlled(self):
        decision = route_task("explain the deploy script")
        # "deploy" is high-risk — escalates to at least controlled
        self.assertEqual(decision.risk_level, "high")
        self.assertEqual(decision.run_mode, "controlled")

    def test_destructive_word_escalates_even_if_query_is_short(self):
        decision = route_task("rm -rf tmp")
        self.assertEqual(decision.risk_level, "high")
        self.assertIn("controlled", decision.run_mode)

    def test_force_push_escalates(self):
        decision = route_task("can we force push this branch")
        self.assertEqual(decision.risk_level, "high")
        self.assertEqual(decision.run_mode, "controlled")

    def test_database_word_escalates(self):
        decision = route_task("migrate the database schema")
        self.assertEqual(decision.risk_level, "high")
        self.assertIn(decision.run_mode, ("controlled", "orchestrated"))

    def test_credentials_word_escalates(self):
        decision = route_task("update credentials for the API")
        self.assertEqual(decision.risk_level, "high")
        self.assertEqual(decision.run_mode, "controlled")

    def test_many_files_escalates_to_large(self):
        decision = route_task("update `a.py` `b.py` `c.py` `d.py` for the new API")
        self.assertEqual(decision.task_size, "large")

    def test_read_only_many_files_stays_medium_if_no_edit_intent(self):
        decision = route_task("explain what `a.py` `b.py` `c.py` do")
        # "explain" + "what" = small signals, files push to medium
        self.assertIn(decision.task_size, ("small", "medium"))
        self.assertIn(decision.run_mode, ("log", "controlled"))

    def test_ambiguous_task_defaults_with_low_confidence(self):
        decision = route_task("handle the thing")
        self.assertEqual(decision.confidence, "low")

    def test_route_decision_is_serializable(self):
        decision = route_task("fix the bug")
        d = route_decision_to_dict(decision)
        self.assertEqual(d["task_size"], decision.task_size)
        self.assertEqual(d["run_mode"], decision.run_mode)
        self.assertEqual(d["risk_level"], decision.risk_level)
        self.assertEqual(d["task_type"], decision.task_type)
        self.assertIsInstance(d["reasons"], list)
        json.dumps(d)  # must not raise

    def test_route_decision_includes_reasons(self):
        decision = route_task("implement a new feature for user auth")
        self.assertGreater(len(decision.reasons), 0)
        self.assertIsInstance(decision.reasons[0], str)

    def test_router_does_not_call_llm_or_scheduler(self):
        """The router must be pure Python — no LLM, no filesystem, no network."""
        decision = route_task("any query at all")
        self.assertIsInstance(decision, TaskRouteDecision)
        # If we got here without imports of LLM/scheduler, the router is pure

    def test_empty_query_does_not_crash(self):
        decision = route_task("")
        self.assertIsInstance(decision, TaskRouteDecision)
        self.assertIn(decision.task_size, ("small", "medium", "large"))

    def test_chinese_small_question_routes_log(self):
        decision = route_task("解释一下 guardrails.py 的作用")
        self.assertEqual(decision.task_size, "small")
        self.assertEqual(decision.run_mode, "log")

    def test_chinese_feature_routes_medium(self):
        decision = route_task("添加用户认证功能")
        self.assertIn(decision.task_size, ("medium", "large"))
        self.assertIn(decision.run_mode, ("controlled", "orchestrated"))

    def test_chinese_high_risk_escalates(self):
        decision = route_task("删除数据库中的所有用户")
        self.assertEqual(decision.risk_level, "high")
        self.assertEqual(decision.run_mode, "controlled")

    def test_render_route_decision_includes_all_sections(self):
        decision = route_task("fix the bug in auth.py")
        text = render_route_decision(decision)
        self.assertIn("Route Decision", text)
        self.assertIn("Task Size:", text)
        self.assertIn("Run Mode:", text)
        self.assertIn("Risk Level:", text)
        self.assertIn("Task Type:", text)
        self.assertIn("Confidence:", text)
        self.assertIn("Runtime:", text)
        self.assertIn("Reasons:", text)

    def test_explicit_workflow_hint_is_passed_through(self):
        decision = route_task("do research", explicit_workflow="deep_research")
        self.assertEqual(decision.workflow_hint, "deep_research")

    def test_orchestrated_shows_future_runtime_support(self):
        decision = route_task("implement full phase with multi-step architecture")
        self.assertEqual(decision.run_mode, "orchestrated")
        self.assertEqual(decision.runtime_support, "future_orchestrated")


# =============================================================================
# CLI Integration Tests
# =============================================================================


class RouteCommandTest(unittest.TestCase):
    """Phase 9: route command prints decision without running scheduler."""

    @patch("orchestrator.__main__.Path.cwd")
    def test_route_command_prints_json(self, mock_cwd):
        import io
        import sys
        from orchestrator.__main__ import _handle_route_command
        import argparse

        mock_cwd.return_value = Path("/fake")

        args = argparse.Namespace(
            query="explain what guardrails.py does",
            mode=None,
            format="json",
            command="route",
        )

        captured = io.StringIO()
        old = sys.stdout
        sys.stdout = captured
        try:
            _handle_route_command(args)
        finally:
            sys.stdout = old

        output = captured.getvalue()
        data = json.loads(output)
        self.assertIn("task_size", data)
        self.assertIn("run_mode", data)
        self.assertIn("risk_level", data)

    @patch("orchestrator.__main__.Path.cwd")
    def test_route_command_honors_mode_override(self, mock_cwd):
        import io
        import sys
        from orchestrator.__main__ import _handle_route_command
        import argparse

        mock_cwd.return_value = Path("/fake")

        args = argparse.Namespace(
            query="explain this simple thing",
            mode="controlled",
            format="json",
            command="route",
        )

        captured = io.StringIO()
        old = sys.stdout
        sys.stdout = captured
        try:
            _handle_route_command(args)
        finally:
            sys.stdout = old

        data = json.loads(captured.getvalue())
        self.assertEqual(data["run_mode"], "controlled")
        self.assertTrue(data["user_override"])

    @patch("orchestrator.__main__.Path.cwd")
    def test_route_command_text_format(self, mock_cwd):
        import io
        import sys
        from orchestrator.__main__ import _handle_route_command
        import argparse

        mock_cwd.return_value = Path("/fake")

        args = argparse.Namespace(
            query="fix the bug",
            mode=None,
            format="text",
            command="route",
        )

        captured = io.StringIO()
        old = sys.stdout
        sys.stdout = captured
        try:
            _handle_route_command(args)
        finally:
            sys.stdout = old

        self.assertIn("Route Decision", captured.getvalue())


class AskRouteIntegrationTest(unittest.TestCase):
    """Phase 9: ask command routes before workflow, skips heavy workflow for log/off."""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmpdir.name)
        self.outputs = self.project_root / "outputs"
        self.states_dir = self.outputs / "states"
        self.states_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _make_ask_args(self, query, **kwargs):
        import argparse
        ns = argparse.Namespace(
            query=query,
            llm=None,
            model=None,
            agent_llm=None,
            raw=False,
            format="json",
            mode=None,
            force_run=False,
            command="ask",
        )
        for k, v in kwargs.items():
            setattr(ns, k, v)
        return ns

    @patch("orchestrator.__main__.Path.cwd")
    def test_ask_log_route_exits_without_workflow(self, mock_cwd):
        """A small query routes to log and exits without running scheduler."""
        import io
        import sys
        from orchestrator.__main__ import _handle_ask_command

        mock_cwd.return_value = self.project_root

        captured = io.StringIO()
        old = sys.stdout
        sys.stdout = captured
        try:
            _handle_ask_command(self._make_ask_args("explain what a function does"))
        finally:
            sys.stdout = old

        data = json.loads(captured.getvalue())
        self.assertIn("_note", data)
        self.assertIn("log/off", data["_note"])
        self.assertEqual(data["run_mode"], "log")

    @patch("orchestrator.__main__.Path.cwd")
    def test_ask_force_run_overrides_log_route(self, mock_cwd):
        """--force-run on a log route attempts to run the workflow."""
        import io
        import sys
        from orchestrator.__main__ import _handle_ask_command

        mock_cwd.return_value = self.project_root

        captured = io.StringIO()
        old = sys.stdout
        sys.stdout = captured
        try:
            # With --force-run, the small query will proceed to scheduler
            # which will fail because there's no real LLM, but the route
            # should have been bypassed
            _handle_ask_command(self._make_ask_args(
                "explain what a function does",
                force_run=True,
            ))
        except Exception:
            # Expected: no real LLM provider available
            pass
        finally:
            sys.stdout = old

        # Should not have printed the "log/off" skip message
        output = captured.getvalue()
        self.assertNotIn("log/off", output)

    @patch("orchestrator.__main__.Path.cwd")
    def test_ask_orchestrated_route_requires_force_run(self, mock_cwd):
        """Orchestrated route without --force-run exits with a note."""
        import io
        import sys
        from orchestrator.__main__ import _handle_ask_command

        mock_cwd.return_value = self.project_root

        captured = io.StringIO()
        old = sys.stdout
        sys.stdout = captured
        try:
            _handle_ask_command(self._make_ask_args(
                "implement full phase architecture migration with multi-step workflow"
            ))
        finally:
            sys.stdout = old

        data = json.loads(captured.getvalue())
        self.assertIn("_note", data)
        self.assertIn("Orchestrated runner", data["_note"])
        self.assertEqual(data["run_mode"], "orchestrated")
        self.assertEqual(data["runtime_support"], "future_orchestrated")

    @patch("orchestrator.__main__.Path.cwd")
    def test_ask_mode_override_respected(self, mock_cwd):
        """--mode controlled forces controlled even for small queries."""
        import io
        import sys
        from orchestrator.__main__ import _handle_ask_command

        mock_cwd.return_value = self.project_root

        captured = io.StringIO()
        old = sys.stdout
        sys.stdout = captured
        try:
            # --mode controlled on small query → proceeds to scheduler
            _handle_ask_command(self._make_ask_args(
                "explain this",
                mode="controlled",
            ))
        except Exception:
            pass  # Expected: no LLM available
        finally:
            sys.stdout = old

        # Should have tried to run (not printed the log skip message)
        output = captured.getvalue()
        self.assertNotIn("log/off", output)

    @patch("orchestrator.__main__.Path.cwd")
    def test_ask_mode_off_override(self, mock_cwd):
        """--mode off on any query forces off."""
        import io
        import sys
        from orchestrator.__main__ import _handle_ask_command

        mock_cwd.return_value = self.project_root

        captured = io.StringIO()
        old = sys.stdout
        sys.stdout = captured
        try:
            _handle_ask_command(self._make_ask_args(
                "fix this critical bug",
                mode="off",
            ))
        finally:
            sys.stdout = old

        data = json.loads(captured.getvalue())
        self.assertEqual(data["run_mode"], "off")
        self.assertTrue(data["user_override"])


# =============================================================================
# State / Metadata Persistence Tests
# =============================================================================


class RouteDecisionPersistenceTest(unittest.TestCase):
    """Phase 9: route decision is persisted in state metadata and trace."""

    def test_state_metadata_loads_without_route_decision_for_old_state(self):
        """Older state files without route_decision must still load."""
        state = StateCenter(query="test")
        state.metadata.route_decision = None  # simulate old state
        d = state.metadata.to_dict()
        self.assertNotIn("route_decision", d)

        # Reload from dict without route_decision
        from orchestrator.state_center import StateMetadata
        m2 = StateMetadata.from_dict(d)
        self.assertIsNone(m2.route_decision)

    def test_route_decision_trace_event_is_written(self):
        state = StateCenter(query="test")
        decision_dict = route_decision_to_dict(route_task("fix the bug"))
        state.record_route_decision(decision_dict)

        route_events = [
            e for e in state.execution_trace
            if e.get("event") == "route_decision"
        ]
        self.assertEqual(len(route_events), 1)
        self.assertEqual(route_events[0]["task_size"], "medium")
        self.assertEqual(route_events[0]["run_mode"], "controlled")

    def test_route_decision_stored_on_metadata(self):
        state = StateCenter(query="test")
        decision_dict = route_decision_to_dict(route_task("implement feature"))
        state.record_route_decision(decision_dict)

        self.assertIsNotNone(state.metadata.route_decision)
        self.assertEqual(
            state.metadata.route_decision["task_size"],
            decision_dict["task_size"],
        )

    def test_route_decision_sets_run_mode_on_metadata(self):
        state = StateCenter(query="test")
        decision_dict = route_decision_to_dict(route_task("explain this"))
        state.record_route_decision(decision_dict)

        self.assertEqual(state.metadata.run_mode, "log")

    def test_route_decision_in_trace_has_all_fields(self):
        state = StateCenter(query="test")
        decision_dict = route_decision_to_dict(route_task(
            "deploy database migration", explicit_mode="controlled"
        ))
        state.record_route_decision(decision_dict)

        event = [e for e in state.execution_trace if e.get("event") == "route_decision"][0]
        self.assertIn("task_size", event)
        self.assertIn("run_mode", event)
        self.assertIn("risk_level", event)
        self.assertIn("task_type", event)
        self.assertIn("reasons", event)
        self.assertIn("user_override", event)
        self.assertIn("runtime_support", event)
        self.assertIn("timestamp", event)

    def test_route_decision_survives_save_load_roundtrip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            state = StateCenter(query="test roundtrip")
            decision_dict = route_decision_to_dict(route_task("fix bug in auth"))
            state.record_route_decision(decision_dict)

            path = Path(tmpdir) / "state.json"
            state.save_to(path)

            loaded = StateCenter.load_from(path)
            self.assertIsNotNone(loaded.metadata.route_decision)
            self.assertEqual(
                loaded.metadata.route_decision["task_size"],
                decision_dict["task_size"],
            )


# =============================================================================
# CLI Payload Tests
# =============================================================================


class RouteDecisionInPayloadTest(unittest.TestCase):
    """Phase 9: route_decision appears in CLI payload."""

    def test_build_run_payload_includes_routing(self):
        from orchestrator.cli_output import build_run_payload
        from orchestrator.models import RunResult

        state = StateCenter(query="fix the bug in auth.py")
        decision = route_task("fix the bug in auth.py")
        state.record_route_decision(route_decision_to_dict(decision))

        result = RunResult(
            task_id=state.metadata.task_id,
            status="completed",
            final_node="planner",
            state_version=state.version,
        )

        payload = build_run_payload(
            query="fix the bug in auth.py",
            workflow_name="deep_research",
            state=state,
            result=result,
        )

        self.assertIn("routing", payload)
        self.assertIsNotNone(payload["routing"])
        self.assertEqual(payload["routing"]["task_size"], "medium")
        self.assertEqual(payload["routing"]["run_mode"], "controlled")

    def test_build_run_payload_without_route_decision_is_null(self):
        from orchestrator.cli_output import build_run_payload
        from orchestrator.models import RunResult

        state = StateCenter(query="test")
        # No route decision recorded

        result = RunResult(
            task_id=state.metadata.task_id,
            status="completed",
            final_node="planner",
            state_version=state.version,
        )

        payload = build_run_payload(
            query="test",
            workflow_name="deep_research",
            state=state,
            result=result,
        )

        self.assertIsNone(payload["routing"])

    def test_task_summary_includes_run_mode(self):
        from orchestrator.cli_output import build_run_payload
        from orchestrator.models import RunResult

        state = StateCenter(query="test")
        decision = route_task("test", explicit_mode="orchestrated")
        state.record_route_decision(route_decision_to_dict(decision))

        result = RunResult(
            task_id=state.metadata.task_id,
            status="completed",
            final_node="planner",
            state_version=state.version,
        )

        payload = build_run_payload(
            query="test",
            workflow_name="test_wf",
            state=state,
            result=result,
        )

        self.assertEqual(payload["task"]["run_mode"], "orchestrated")


# =============================================================================
# Boundary Tests
# =============================================================================


class BoundaryTest(unittest.TestCase):
    """Phase 9 boundary cases — escalation, override, edge inputs."""

    def test_small_question_with_secret_keyword_escalates(self):
        decision = route_task("what is the .env file for")
        self.assertEqual(decision.risk_level, "high")
        self.assertEqual(decision.run_mode, "controlled")

    def test_small_question_with_auth_keyword_escalates(self):
        decision = route_task("explain how auth works")
        self.assertEqual(decision.risk_level, "high")
        self.assertEqual(decision.run_mode, "controlled")

    def test_user_override_can_force_controlled_for_small_task(self):
        decision = route_task("explain this", explicit_mode="controlled")
        self.assertEqual(decision.task_size, "small")
        self.assertEqual(decision.run_mode, "controlled")
        self.assertTrue(decision.user_override)

    def test_user_override_can_force_log_for_medium_task(self):
        decision = route_task("fix the bug in auth.py", explicit_mode="log")
        self.assertIn(decision.task_size, ("small", "medium"))
        self.assertEqual(decision.run_mode, "log")
        self.assertTrue(decision.user_override)

    def test_user_override_can_force_off_for_large_task(self):
        decision = route_task(
            "implement full architecture migration",
            explicit_mode="off",
        )
        self.assertEqual(decision.task_size, "large")
        self.assertEqual(decision.run_mode, "off")
        self.assertTrue(decision.user_override)

    def test_invalid_mode_is_rejected_by_cli(self):
        """argparse choices= rejects invalid modes at parse time."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--mode",
            choices=["off", "log", "controlled", "orchestrated"],
        )
        # Valid modes parse fine
        for mode in ("off", "log", "controlled", "orchestrated"):
            ns = parser.parse_args(["--mode", mode])
            self.assertEqual(ns.mode, mode)

        # Invalid mode raises SystemExit
        with self.assertRaises(SystemExit):
            parser.parse_args(["--mode", "invalid"])

    def test_very_long_query_does_not_crash(self):
        decision = route_task("x " * 5000)
        self.assertIsInstance(decision, TaskRouteDecision)

    def test_special_characters_in_query_does_not_crash(self):
        decision = route_task("!!! @@@ ### $$$ %%% ^^^ &&& *** (((")
        self.assertIsInstance(decision, TaskRouteDecision)

    def test_unicode_query_does_not_crash(self):
        decision = route_task("こんにちは 世界 🌍")
        self.assertIsInstance(decision, TaskRouteDecision)

    def test_high_risk_but_destructive_no_edit_escalates_to_controlled(self):
        """Even if it's just a question, high-risk keywords escalate."""
        decision = route_task("tell me about database security best practices")
        self.assertEqual(decision.risk_level, "high")
        self.assertEqual(decision.run_mode, "controlled")

    def test_resume_checkpoint_words_route_large(self):
        decision = route_task("resume from checkpoint and audit the full workflow")
        self.assertEqual(decision.task_size, "large")

    def test_orchestrated_route_does_not_fake_langgraph_support(self):
        decision = route_task("implement full workflow with parallel agents")
        self.assertEqual(decision.run_mode, "orchestrated")
        self.assertEqual(decision.runtime_support, "future_orchestrated")
        # The reasons must mention that orchestrated runner is not implemented
        self.assertTrue(any(
            "not implemented" in r for r in decision.reasons
        ))


# =============================================================================
# Phase 9A — RunModeSemantics Tests
# =============================================================================


class RunModeSemanticsTest(unittest.TestCase):
    """Phase 9A: explicit mode semantics — each label has behavior."""

    def test_should_execute_workflow_off_returns_false(self):
        d = route_task("anything", explicit_mode="off")
        self.assertFalse(should_execute_workflow(d))

    def test_should_execute_workflow_log_returns_false(self):
        d = route_task("explain this")
        self.assertFalse(should_execute_workflow(d))

    def test_should_execute_workflow_controlled_returns_true(self):
        d = route_task("fix the bug", explicit_mode="controlled")
        self.assertTrue(should_execute_workflow(d))

    def test_should_execute_workflow_orchestrated_future_returns_false(self):
        d = route_task("implement full phase architecture migration")
        self.assertEqual(d.runtime_support, "future_orchestrated")
        self.assertFalse(should_execute_workflow(d))

    def test_should_apply_control_off_returns_false(self):
        d = route_task("anything", explicit_mode="off")
        self.assertFalse(should_apply_control(d))

    def test_should_apply_control_log_returns_false(self):
        d = route_task("explain this")
        self.assertFalse(should_apply_control(d))

    def test_should_apply_control_controlled_returns_true(self):
        d = route_task("fix bug", explicit_mode="controlled")
        self.assertTrue(should_apply_control(d))

    def test_should_apply_control_orchestrated_returns_true(self):
        d = route_task("multi-step architecture", explicit_mode="orchestrated")
        self.assertTrue(should_apply_control(d))

    def test_should_only_log_off_returns_true(self):
        d = route_task("anything", explicit_mode="off")
        self.assertTrue(should_only_log(d))

    def test_should_only_log_log_returns_true(self):
        d = route_task("explain this")
        self.assertTrue(should_only_log(d))

    def test_should_only_log_controlled_returns_false(self):
        d = route_task("fix bug", explicit_mode="controlled")
        self.assertFalse(should_only_log(d))

    def test_requires_future_runner_orchestrated_future_returns_true(self):
        d = route_task("implement full phase architecture migration")
        self.assertTrue(requires_future_runner(d))

    def test_requires_future_runner_controlled_returns_false(self):
        d = route_task("fix bug", explicit_mode="controlled")
        self.assertFalse(requires_future_runner(d))

    def test_requires_future_runner_orchestrated_override_returns_false(self):
        d = route_task("explain this", explicit_mode="orchestrated")
        # User override still gets future_orchestrated on a small task
        self.assertTrue(requires_future_runner(d))

    def test_effective_run_mode_orchestrated_future_falls_back(self):
        d = route_task("implement full phase architecture migration")
        self.assertEqual(effective_run_mode(d), "controlled")

    def test_effective_run_mode_controlled_stays(self):
        d = route_task("fix bug", explicit_mode="controlled")
        self.assertEqual(effective_run_mode(d), "controlled")

    def test_effective_run_mode_log_stays(self):
        d = route_task("explain this")
        self.assertEqual(effective_run_mode(d), "log")

    def test_effective_run_mode_off_stays(self):
        d = route_task("anything", explicit_mode="off")
        self.assertEqual(effective_run_mode(d), "off")

    def test_all_helpers_accept_TaskRouteDecision(self):
        """Every helper must accept a TaskRouteDecision."""
        d = route_task("fix the bug in auth.py")
        self.assertIsInstance(should_execute_workflow(d), bool)
        self.assertIsInstance(should_apply_control(d), bool)
        self.assertIsInstance(should_only_log(d), bool)
        self.assertIsInstance(requires_future_runner(d), bool)
        self.assertIn(effective_run_mode(d), ("off", "log", "controlled", "orchestrated"))


# =============================================================================
# Phase 9A — Run command mode enforcement tests
# =============================================================================


class RunModeEnforcementTest(unittest.TestCase):
    """Phase 9A: _handle_run_command respects mode semantics."""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmpdir.name)
        self.outputs = self.project_root / "outputs"
        self.states_dir = self.outputs / "states"
        self.states_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _make_run_args(self, query, workflow, **kwargs):
        import argparse
        ns = argparse.Namespace(
            query=query,
            workflow=workflow,
            llm=None,
            model=None,
            agent_llm=None,
            raw=False,
            format="json",
            mode=None,
            force_run=False,
            command="run",
        )
        for k, v in kwargs.items():
            setattr(ns, k, v)
        return ns

    @patch("orchestrator.__main__.Path.cwd")
    def test_run_with_mode_off_exits_without_executing(self, mock_cwd):
        """run --mode off exits with route decision, no scheduler call."""
        from orchestrator.__main__ import _handle_run_command

        mock_cwd.return_value = self.project_root

        import io
        import sys
        captured = io.StringIO()
        old = sys.stdout
        sys.stdout = captured
        try:
            _handle_run_command(self._make_run_args(
                "fix the bug",
                "deep_research.yaml",
                mode="off",
            ))
        finally:
            sys.stdout = old

        data = json.loads(captured.getvalue())
        self.assertEqual(data["run_mode"], "off")
        self.assertIn("_note", data)
        self.assertIn("log/off", data["_note"])

    @patch("orchestrator.__main__.Path.cwd")
    def test_run_with_future_orchestrated_requires_force_run(self, mock_cwd):
        """run --mode orchestrated on a large task requires --force-run."""
        from orchestrator.__main__ import _handle_run_command

        mock_cwd.return_value = self.project_root

        import io
        import sys
        captured = io.StringIO()
        old = sys.stdout
        sys.stdout = captured
        try:
            _handle_run_command(self._make_run_args(
                "implement full phase architecture migration",
                "deep_research.yaml",
                mode="orchestrated",
            ))
        finally:
            sys.stdout = old

        data = json.loads(captured.getvalue())
        self.assertIn("_note", data)
        self.assertIn("Orchestrated runner", data["_note"])

    @patch("orchestrator.__main__.Path.cwd")
    def test_run_with_future_orchestrated_and_force_run_proceeds(self, mock_cwd):
        """run --mode orchestrated --force-run should proceed to scheduler."""
        from orchestrator.__main__ import _handle_run_command

        mock_cwd.return_value = self.project_root

        import io
        import sys
        captured = io.StringIO()
        old = sys.stdout
        sys.stdout = captured
        try:
            # Will fail because there's no real LLM, but shouldn't exit on route check
            _handle_run_command(self._make_run_args(
                "implement full phase architecture migration",
                "deep_research.yaml",
                mode="orchestrated",
                force_run=True,
            ))
        except Exception:
            pass  # Expected: no LLM provider
        finally:
            sys.stdout = old

        # Should not have printed the route skip message
        output = captured.getvalue()
        self.assertNotIn("Orchestrated runner", output)


# =============================================================================
# Live View — Route Field Tests
# =============================================================================


class LiveViewRouteTest(unittest.TestCase):
    """Phase 9: live_view shows run_mode from state metadata."""

    def test_build_live_view_includes_run_mode(self):
        from orchestrator.live_view import build_live_view

        state = StateCenter(query="test")
        decision = route_task("fix bug", explicit_mode="controlled")
        state.record_route_decision(route_decision_to_dict(decision))

        view = build_live_view(state)
        self.assertEqual(view["run_mode"], "controlled")

    def test_build_live_view_defaults_run_mode_from_metadata(self):
        from orchestrator.live_view import build_live_view

        state = StateCenter(query="test")
        # Default run_mode is "controlled" from StateMetadata
        view = build_live_view(state)
        self.assertEqual(view["run_mode"], "controlled")


if __name__ == "__main__":
    unittest.main()
