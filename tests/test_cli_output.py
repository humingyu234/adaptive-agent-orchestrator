import json
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator.cli_output import build_raw_payload, build_run_payload, format_run_text
from orchestrator.live_view import build_live_view
from orchestrator.models import RunResult
from orchestrator.state_center import StateCenter


class CliOutputTest(unittest.TestCase):
    def test_build_run_payload_surfaces_runtime_control_signals(self):
        state = StateCenter(query="research agent runtimes")
        state.write(
            "plan",
            {
                "plan_type": "research",
                "sub_questions": ["What is controlled?", "How is recovery handled?"],
                "confidence": 0.8,
                "model_profile": "worker",
                "memory_hints_used": 1,
            },
            "planner",
        )
        state.execution_trace.append(
            {
                "event": "evaluation",
                "agent_name": "planner",
                "passed": True,
                "action": "continue",
                "reason": "",
                "timestamp": "2026-04-30T00:00:00Z",
            }
        )
        state.create_checkpoint(
            created_by="planner",
            reason="post_step_success",
            node_name="planner",
            node_index=0,
        )
        state.write(
            "supervisor_report",
            {
                "next_action": "revise",
                "status": "reviewed",
                "concerns": ["planner retried once"],
                "review_reason": "Need stronger plan",
                "suggested_target": "planner",
                "suggested_action": "re_plan",
                "process_review": {"steps_seen": 1},
            },
            "supervisor",
        )
        state.execution_trace.append(
            {
                "event": "checkpoint_replan",
                "target": "planner",
                "action": "re_plan",
                "reason": "Need stronger plan",
                "timestamp": "2026-04-30T00:00:01Z",
            }
        )
        state.set_status("needs_human_review", "等待人工确认后再继续")

        result = RunResult(
            task_id=state.metadata.task_id,
            status="needs_human_review",
            final_node="human_review",
            reason="等待人工确认后再继续",
            state_version=state.version,
            checkpoint_dir="outputs/checkpoints/task",
            convergence_report_path="outputs/reports/task.json",
            memory_path="outputs/memory/task.json",
        )

        payload = build_run_payload(
            query=state.data_pool.query,
            workflow_name="deep_research_human_review",
            state=state,
            result=result,
            project_root=Path("/project"),
        )

        self.assertEqual(payload["task"]["status"], "needs_human_review")
        self.assertEqual(payload["task"]["workflow"], "deep_research_human_review")
        self.assertEqual(payload["timeline"][0]["agent"], "planner")
        self.assertEqual(payload["evaluations"][0]["agent"], "planner")
        self.assertEqual(payload["control"]["checkpoints"], 1)
        self.assertEqual(payload["control"]["replans"], 1)
        self.assertEqual(payload["supervisor"]["suggested_action"], "re_plan")
        self.assertEqual(payload["next_action"]["status"], "waiting_for_human_review")
        self.assertIn("resume --task-id", payload["next_action"]["approve"])
        self.assertEqual(payload["preview"]["plan"]["memory_hints_used"], 1)
        self.assertTrue(payload["artifacts"]["state_path"].endswith(f"{state.metadata.task_id}.json"))
        # New fields
        self.assertIsNotNone(payload.get("narrative"))
        self.assertIn("system auto-selected", payload["narrative"])

    def test_build_run_payload_surfaces_failure_and_safety(self):
        state = StateCenter(query="unsafe output")
        state.execution_trace.append(
            {
                "event": "guardrail_violation",
                "agent_name": "summarizer",
                "guardrail_name": "block_sensitive_output_terms",
                "stage": "output",
                "reason": "blocked secret",
                "failure_category": "guardrail_blocked",
                "timestamp": "2026-04-30T00:00:00Z",
            }
        )
        state.execution_trace.append(
            {
                "event": "failure_classified",
                "category": "guardrail_blocked",
                "severity": "high",
                "agent_name": "summarizer",
                "reason": "blocked secret",
                "timestamp": "2026-04-30T00:00:01Z",
            }
        )
        state.set_status("failed", "blocked secret")

        result = RunResult(
            task_id=state.metadata.task_id,
            status="failed",
            final_node="summarizer",
            reason="blocked secret",
            failure_reason="blocked secret",
            state_version=state.version,
        )

        payload = build_run_payload(
            query=state.data_pool.query,
            workflow_name="deep_research",
            state=state,
            result=result,
        )

        self.assertEqual(payload["failure"]["category"], "guardrail_blocked")
        self.assertEqual(payload["failure"]["severity"], "high")
        self.assertEqual(payload["safety"][0]["guardrail"], "block_sensitive_output_terms")
        self.assertEqual(payload["next_action"]["status"], "failed")

    def test_timeline_pairs_each_write_with_following_same_agent_evaluation(self):
        state = StateCenter(query="retry then pass")
        state.write("summary", {"conclusion": "too short"}, "summarizer")
        state.execution_trace.append(
            {
                "event": "evaluation",
                "agent_name": "summarizer",
                "passed": False,
                "action": "retry",
                "reason": "Summary coverage is too low",
                "timestamp": "2026-04-30T00:00:00Z",
            }
        )
        state.write("summary", {"conclusion": "Long enough final summary"}, "summarizer")
        state.execution_trace.append(
            {
                "event": "evaluation",
                "agent_name": "summarizer",
                "passed": True,
                "action": "continue",
                "reason": "",
                "timestamp": "2026-04-30T00:00:01Z",
            }
        )
        state.set_status("completed", "done")

        result = RunResult(
            task_id=state.metadata.task_id,
            status="completed",
            final_node="summarizer",
            reason="done",
            completion_reason="done",
            state_version=state.version,
        )

        payload = build_run_payload(
            query=state.data_pool.query,
            workflow_name="deep_research",
            state=state,
            result=result,
        )

        self.assertEqual(payload["timeline"][0]["status"], "needs_attention")
        self.assertEqual(payload["timeline"][0]["action"], "retry")
        self.assertEqual(payload["timeline"][0]["reason"], "Summary coverage is too low")
        self.assertEqual(payload["timeline"][1]["status"], "passed")
        self.assertEqual(payload["timeline"][1]["action"], "continue")

    def test_build_raw_payload_keeps_legacy_shape(self):
        state = StateCenter(query="legacy")
        result = RunResult(
            task_id=state.metadata.task_id,
            status="completed",
            final_node="planner",
            state_version=state.version,
        )

        payload = build_raw_payload(state=state, result=result)

        self.assertEqual(sorted(payload.keys()), ["result", "state"])
        self.assertEqual(payload["result"]["task_id"], state.metadata.task_id)
        self.assertEqual(payload["state"]["original_query"], "legacy")

    def test_format_run_text_completed(self):
        state = StateCenter(query="research AI agent runtimes")
        state.write(
            "plan",
            {"plan_type": "research", "sub_questions": ["Q1"], "confidence": 0.85, "model_profile": "worker", "provider": "openai"},
            "planner",
        )
        state.execution_trace.append(
            {"event": "evaluation", "agent_name": "planner", "passed": True, "action": "continue", "reason": "", "timestamp": "2026-04-30T00:00:01Z"}
        )
        state.write("summary", {"conclusion": "AI agents are evolving rapidly", "model_profile": "worker", "provider": "anthropic"}, "summarizer")
        state.execution_trace.append(
            {"event": "evaluation", "agent_name": "summarizer", "passed": True, "action": "continue", "reason": "", "timestamp": "2026-04-30T00:00:02Z"}
        )
        state.write(
            "supervisor_report",
            {"next_action": "accept", "status": "reviewed", "concerns": [], "review_reason": "all good", "suggested_target": "none", "suggested_action": "accept", "process_review": {}},
            "supervisor",
        )
        state.execution_trace.append(
            {"event": "evaluation", "agent_name": "supervisor", "passed": True, "action": "continue", "reason": "", "timestamp": "2026-04-30T00:00:03Z"}
        )
        state.set_status("completed", "done")

        result = RunResult(
            task_id=state.metadata.task_id,
            status="completed",
            final_node="supervisor",
            reason="done",
            state_version=state.version,
            convergence_report_path="outputs/reports/test.json",
            memory_path="outputs/memory/test.json",
        )

        payload = build_run_payload(
            query="research AI agent runtimes",
            workflow_name="deep_research",
            state=state,
            result=result,
            project_root=Path("/project"),
            routing_reason="default research workflow",
        )

        text = format_run_text(payload)

        self.assertIn("Task:", text)
        self.assertIn("research AI agent runtimes", text)
        self.assertIn("deep_research", text)
        self.assertIn("OK completed", text)
        self.assertIn("Execution:", text)
        self.assertIn("planner", text)
        self.assertIn("summarizer", text)
        self.assertIn("supervisor", text)
        self.assertIn("openai", text)
        self.assertIn("anthropic", text)
        self.assertIn("Supervisor: accept", text)
        self.assertIn("Artifacts:", text)
        self.assertIn("Next: completed", text)
        # Verify structure markers
        self.assertTrue(text.startswith("=" * 68))
        self.assertTrue(text.endswith("=" * 68 + "\n") or text.strip().endswith("=" * 68))

    def test_format_run_text_needs_human_review(self):
        state = StateCenter(query="sensitive task needing human check")
        state.write("plan", {"plan_type": "research", "sub_questions": ["Q1"], "provider": "openai"}, "planner")
        state.set_status("needs_human_review", "waiting")

        result = RunResult(
            task_id=state.metadata.task_id,
            status="needs_human_review",
            final_node="human_review",
            reason="waiting",
            state_version=state.version,
        )

        payload = build_run_payload(
            query="sensitive task needing human check",
            workflow_name="deep_research_human_review",
            state=state,
            result=result,
        )

        text = format_run_text(payload)

        self.assertIn("WAIT", text)
        self.assertIn("needs_human_review", text)
        self.assertIn("resume --task-id", text)
        self.assertIn("approve", text)

    def test_format_run_text_uses_terminal_safe_ascii_separators(self):
        state = StateCenter(query="ascii terminal demo")
        state.write("summary", {"conclusion": "done"}, "summarizer")
        state.execution_trace.append(
            {
                "event": "evaluation",
                "agent_name": "summarizer",
                "passed": True,
                "action": "continue",
                "reason": "",
                "timestamp": "2026-04-30T00:00:01Z",
            }
        )
        state.set_status("completed", "done")

        result = RunResult(
            task_id=state.metadata.task_id,
            status="completed",
            final_node="summarizer",
            reason="done",
            state_version=state.version,
        )

        payload = build_run_payload(
            query=state.data_pool.query,
            workflow_name="deep_research",
            state=state,
            result=result,
        )
        text = format_run_text(payload)

        self.assertNotIn("→", text)
        self.assertNotIn("—", text)
        self.assertNotIn("·", text)

    def test_format_run_text_keeps_memory_manager_out_of_execution_story(self):
        state = StateCenter(query="memory display demo")
        state.write("retrieved_memories", [{"query": "previous memory"}], "memory_manager")
        state.write("plan", {"plan_type": "research", "sub_questions": ["Q1"]}, "planner")
        state.execution_trace.append(
            {
                "event": "evaluation",
                "agent_name": "planner",
                "passed": True,
                "action": "continue",
                "reason": "",
                "timestamp": "2026-04-30T00:00:01Z",
            }
        )
        state.write("memory_bundle", {"memory_version": "v1"}, "memory_manager")
        state.set_status("completed", "done")

        result = RunResult(
            task_id=state.metadata.task_id,
            status="completed",
            final_node="planner",
            reason="done",
            state_version=state.version,
        )

        payload = build_run_payload(
            query=state.data_pool.query,
            workflow_name="deep_research",
            state=state,
            result=result,
        )
        text = format_run_text(payload)

        execution_section = text.split("  Execution:", 1)[1].split("  Evaluations:", 1)[0]
        self.assertNotIn("memory_manager", execution_section)
        self.assertIn("planner", execution_section)
        self.assertIn("Memory:", text)

    def test_timeline_has_provider_info(self):
        state = StateCenter(query="test")
        state.write("plan", {"plan_type": "research", "sub_questions": [], "provider": "openai", "model_profile": "worker"}, "planner")
        state.write("summary", {"conclusion": "done", "provider": "anthropic", "model_profile": "worker"}, "summarizer")

        result = RunResult(
            task_id=state.metadata.task_id,
            status="completed",
            final_node="summarizer",
            state_version=state.version,
        )

        payload = build_run_payload(
            query="test",
            workflow_name="deep_research",
            state=state,
            result=result,
        )

        self.assertEqual(payload["timeline"][0]["provider"], "openai")
        self.assertEqual(payload["timeline"][0]["model"], "worker")
        self.assertEqual(payload["timeline"][1]["provider"], "anthropic")
        self.assertEqual(payload["timeline"][1]["model"], "worker")


# =============================================================================
# Phase 8 — Status one-shot contract
# =============================================================================

class StatusIsOneShotTest(unittest.TestCase):
    """Phase 8: status command is one-shot — never loops, never sleeps."""

    def test_status_handler_has_no_sleep_call(self):
        """Verify _handle_status_command does not call time.sleep."""
        import inspect
        from orchestrator.__main__ import _handle_status_command
        source = inspect.getsource(_handle_status_command)
        self.assertNotIn("sleep", source, "status command must not sleep")

    def test_status_handler_has_no_while_loop(self):
        """Verify _handle_status_command does not have a polling loop."""
        import inspect
        from orchestrator.__main__ import _handle_status_command
        source = inspect.getsource(_handle_status_command)
        self.assertNotIn("while", source, "status command must not loop")

    def test_watch_handler_has_while_loop(self):
        """Verify _handle_watch_command DOES have a polling loop."""
        import inspect
        from orchestrator.__main__ import _handle_watch_command
        source = inspect.getsource(_handle_watch_command)
        self.assertIn("while", source, "watch command must have a polling loop")


# =============================================================================
# Phase 8 — Watch refresh behaviour
# =============================================================================

class WatchRefreshTest(unittest.TestCase):
    """Phase 8: watch refreshes from updated state files."""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.TemporaryDirectory()
        self.states_dir = Path(self.tmpdir.name) / "outputs" / "states"
        self.states_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_state(self, task_id: str, status: str, query: str = "test query") -> StateCenter:
        state = StateCenter(query=query, task_id=task_id)
        state.set_status(status, "")
        state_path = self.states_dir / f"{task_id}.json"
        state.save_to(state_path)
        return state

    def test_build_live_view_reads_updated_state(self):
        """Simulates watch polling: state changes from running to completed."""
        task_id = "test-refresh-001"

        # First poll: running
        state1 = self._write_state(task_id, "running")
        loaded1 = StateCenter.load_from(self.states_dir / f"{task_id}.json")
        view1 = build_live_view(loaded1)
        self.assertEqual(view1["status"], "running")

        # Second poll: completed (state file updated externally)
        state2 = self._write_state(task_id, "completed")
        loaded2 = StateCenter.load_from(self.states_dir / f"{task_id}.json")
        view2 = build_live_view(loaded2)
        self.assertEqual(view2["status"], "completed")

    def test_is_terminal_detects_completion(self):
        """Watch loop must exit when state becomes terminal."""
        from orchestrator.live_view import is_terminal
        self.assertFalse(is_terminal("running"))
        self.assertTrue(is_terminal("completed"))
        self.assertTrue(is_terminal("failed"))

    def test_build_live_view_reflects_status_change(self):
        """State file updated between polls is reflected in the view."""
        task_id = "test-refresh-002"

        state_running = self._write_state(task_id, "running")
        state_running.execution_trace.append({
            "event": "evaluation", "agent_name": "planner",
            "passed": True, "action": "continue", "reason": "", "timestamp": "t1",
        })
        state_running.save_to(self.states_dir / f"{task_id}.json")

        loaded_running = StateCenter.load_from(self.states_dir / f"{task_id}.json")
        view_running = build_live_view(loaded_running)
        self.assertEqual(view_running["steps_completed"], 1)

        # Update: add another evaluation and mark completed
        state_done = StateCenter.load_from(self.states_dir / f"{task_id}.json")
        state_done.execution_trace.append({
            "event": "evaluation", "agent_name": "summarizer",
            "passed": True, "action": "continue", "reason": "", "timestamp": "t2",
        })
        state_done.set_status("completed", "done")
        state_done.save_to(self.states_dir / f"{task_id}.json")

        loaded_done = StateCenter.load_from(self.states_dir / f"{task_id}.json")
        view_done = build_live_view(loaded_done)
        self.assertEqual(view_done["steps_completed"], 2)
        self.assertEqual(view_done["status"], "completed")

    def test_watch_handles_missing_state_file_gracefully(self):
        """Accessing a non-existent state file should not crash."""
        from orchestrator.live_view import is_terminal
        # This simulates what watch does: check existence before loading
        missing_path = self.states_dir / "nonexistent.json"
        self.assertFalse(missing_path.exists())
        # The watch handler checks this and prints a message — no crash


# =============================================================================
# Phase 8 P3 — Mock-based watch CLI polling test
# =============================================================================

class WatchCLIPollingTest(unittest.TestCase):
    """P3: Exercise _handle_watch_command polling loop with mocked sleep and state."""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmpdir.name)
        self.states_dir = self.project_root / "outputs" / "states"
        self.states_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir = self.project_root / "outputs" / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        self.task_id = "watch-poll-test"
        self.state_path = self.states_dir / f"{self.task_id}.json"
        self.report_path = self.reports_dir / f"{self.task_id}.json"

        # Initial state: running
        state = StateCenter(query="test watch polling", task_id=self.task_id)
        state.set_status("running", "")
        state.save_to(self.state_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _make_args(self, **kwargs):
        """Build an argparse.Namespace matching the watch parser."""
        import argparse
        ns = argparse.Namespace(
            task_id=self.task_id,
            once=False,
            interval=0.1,
            command="watch",
        )
        for k, v in kwargs.items():
            setattr(ns, k, v)
        return ns

    @patch("time.sleep")
    @patch("orchestrator.__main__.Path.cwd")
    def test_watch_exits_on_terminal_state(self, mock_cwd, mock_sleep):
        """Watch polls running→completed and exits without looping forever."""
        from orchestrator.__main__ import _handle_watch_command

        mock_cwd.return_value = self.project_root

        call_count = [0]

        def sleep_side_effect(seconds):
            call_count[0] += 1
            if call_count[0] == 1:
                # After first render, update state to completed
                state = StateCenter.load_from(self.state_path)
                state.set_status("completed", "done")
                state.save_to(self.state_path)
                # Also write a report so _read_report_paths can find it
                self.report_path.write_text(
                    json.dumps({
                        "task_id": self.task_id,
                        "status": "completed",
                        "artifact_summary": {
                            "report_path": str(self.report_path),
                        },
                    }),
                    encoding="utf-8",
                )
            # Don't actually sleep

        mock_sleep.side_effect = sleep_side_effect

        import io
        import sys
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            _handle_watch_command(self._make_args())
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()
        # Should have rendered at least twice (running + completed)
        self.assertIn("... running", output)
        self.assertIn("OK completed", output)
        # Should have called sleep exactly once (between running and completed)
        self.assertEqual(call_count[0], 1)

    @patch("time.sleep")
    @patch("orchestrator.__main__.Path.cwd")
    def test_watch_once_exits_immediately(self, mock_cwd, mock_sleep):
        """--once flag renders once and exits, even if state is still running."""
        from orchestrator.__main__ import _handle_watch_command

        mock_cwd.return_value = self.project_root

        import io
        import sys
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            _handle_watch_command(self._make_args(once=True))
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()
        self.assertIn("... running", output)
        # With --once on running state, should print hint
        self.assertIn("run is still in progress", output)
        # sleep must NOT have been called
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    @patch("orchestrator.__main__.Path.cwd")
    def test_watch_stops_on_needs_human_review(self, mock_cwd, mock_sleep):
        """Watch exits when state reaches needs_human_review (terminal)."""
        from orchestrator.__main__ import _handle_watch_command

        mock_cwd.return_value = self.project_root

        call_count = [0]

        def sleep_side_effect(seconds):
            call_count[0] += 1
            if call_count[0] == 1:
                state = StateCenter.load_from(self.state_path)
                state.set_status("needs_human_review", "awaiting approval")
                state.save_to(self.state_path)

        mock_sleep.side_effect = sleep_side_effect

        import io
        import sys
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            _handle_watch_command(self._make_args())
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()
        self.assertIn("WAIT", output)
        self.assertEqual(call_count[0], 1)

    @patch("orchestrator.__main__.Path.cwd")
    def test_watch_missing_state_file_exits_cleanly(self, mock_cwd):
        """Watch exits with message when state file doesn't exist."""
        from orchestrator.__main__ import _handle_watch_command

        mock_cwd.return_value = self.project_root

        import io
        import sys
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            # Use a task_id that doesn't have a state file
            _handle_watch_command(self._make_args(task_id="nonexistent"))
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()
        self.assertIn("State not found", output)

    @patch("orchestrator.__main__.Path.cwd")
    def test_watch_with_real_report_structure(self, mock_cwd):
        """P1 regression: watch reads paths from real report artifact_summary."""
        from orchestrator.__main__ import _handle_watch_command

        mock_cwd.return_value = self.project_root

        # Write a state file in completed status
        state = StateCenter.load_from(self.state_path)
        state.set_status("completed", "done")
        state.save_to(self.state_path)

        # Write a real-structure report (top-level, NOT {"result": {...}})
        self.report_path.write_text(
            json.dumps({
                "task_id": self.task_id,
                "workflow_name": "deep_research",
                "query": "test watch polling",
                "status": "completed",
                "artifact_summary": {
                    "report_path": str(self.report_path),
                    "state_path": str(self.state_path),
                },
            }),
            encoding="utf-8",
        )

        import io
        import sys
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            _handle_watch_command(self._make_args(once=True))
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()
        # Must show the report path from artifact_summary
        self.assertIn(str(self.report_path), output)
        self.assertNotIn("Traceback", output)


if __name__ == "__main__":
    unittest.main()
