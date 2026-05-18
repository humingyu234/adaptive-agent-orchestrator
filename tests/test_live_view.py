import unittest
from pathlib import Path

from orchestrator.live_view import build_live_view, is_terminal, render_live_view
from orchestrator.models import RunResult
from orchestrator.state_center import StateCenter


class BuildLiveViewTest(unittest.TestCase):
    """Tests for build_live_view — structured view dict."""

    def test_returns_expected_keys(self):
        state = StateCenter(query="test query")
        view = build_live_view(state)

        expected_keys = {
            "task_id", "status", "run_mode", "query", "current_step",
            "current_worker", "progress", "steps_total", "steps_completed",
            "last_decision", "last_decision_reason",
            "last_evaluator_decision", "last_guardrail_decision",
            "last_policy_decision", "last_failure", "last_failure_origin",
            "last_recovery_hint", "evidence_status", "human_review_required",
            "human_review_state", "report_path", "evidence_path",
            "started_at", "updated_at", "elapsed",
        }
        self.assertTrue(expected_keys.issubset(set(view.keys())))

    def test_completed_run_shows_correct_counts(self):
        state = StateCenter(query="research task")
        state.write("plan", {"sub_questions": ["Q1"]}, "planner")
        state.execution_trace.append({
            "event": "evaluation", "agent_name": "planner",
            "passed": True, "action": "continue", "reason": "", "timestamp": "t1",
        })
        state.write("summary", {"conclusion": "done"}, "summarizer")
        state.execution_trace.append({
            "event": "evaluation", "agent_name": "summarizer",
            "passed": True, "action": "continue", "reason": "", "timestamp": "t2",
        })
        state.set_status("completed", "done")

        result = RunResult(
            task_id=state.metadata.task_id,
            status="completed",
            final_node="summarizer",
            reason="done",
            state_version=state.version,
            convergence_report_path="outputs/reports/test.json",
            evidence_path="outputs/evidence/test.json",
        )

        view = build_live_view(state, result=result)

        self.assertEqual(view["status"], "completed")
        self.assertEqual(view["steps_completed"], 2)
        self.assertEqual(view["steps_total"], 2)
        self.assertEqual(view["progress"], "2/2")
        self.assertEqual(view["current_step"], "summarizer")
        self.assertEqual(view["last_decision"], "continue")
        self.assertFalse(view["human_review_required"])
        self.assertEqual(view["report_path"], "outputs/reports/test.json")
        self.assertEqual(view["evidence_path"], "outputs/evidence/test.json")

    def test_failed_run_shows_failure_reason(self):
        state = StateCenter(query="failing task")
        state.execution_trace.append({
            "event": "guardrail_violation",
            "agent_name": "summarizer",
            "guardrail_name": "block_secret",
            "stage": "output",
            "reason": "blocked api_key",
            "failure_category": "guardrail_blocked",
            "timestamp": "t1",
        })
        state.execution_trace.append({
            "event": "failure_classified",
            "category": "guardrail_blocked",
            "severity": "high",
            "agent_name": "summarizer",
            "reason": "blocked api_key",
            "timestamp": "t2",
        })
        state.set_status("failed", "blocked api_key")

        view = build_live_view(state)

        self.assertEqual(view["status"], "failed")
        self.assertIsNotNone(view["last_failure"])
        self.assertEqual(view["last_failure"]["category"], "guardrail_blocked")
        self.assertEqual(view["last_failure"]["severity"], "high")
        self.assertEqual(view["last_failure"]["agent_name"], "summarizer")
        self.assertEqual(view["last_failure"]["reason"], "blocked api_key")

    def test_needs_human_review_from_status(self):
        state = StateCenter(query="needs approval")
        state.set_status("needs_human_review", "waiting for human")

        view = build_live_view(state)

        self.assertEqual(view["status"], "needs_human_review")
        self.assertTrue(view["human_review_required"])

    def test_needs_human_review_from_gate(self):
        state = StateCenter(query="needs approval")
        state.data_pool.intermediate["human_review_gate"] = {
            "decision": "await_human",
            "status": "awaiting_human_review",
        }

        view = build_live_view(state)

        self.assertTrue(view["human_review_required"])

    def test_missing_optional_paths_does_not_crash(self):
        state = StateCenter(query="test")
        state.set_status("running", "")

        # no result passed — paths should be None, no crash
        view = build_live_view(state)

        self.assertIsNone(view["report_path"])
        self.assertIsNone(view["evidence_path"])

    def test_empty_trace_yields_safe_defaults(self):
        state = StateCenter(query="no events yet")
        state.set_status("running", "")

        view = build_live_view(state)

        self.assertEqual(view["steps_completed"], 0)
        self.assertEqual(view["steps_total"], 0)
        self.assertEqual(view["progress"], "0/0")
        self.assertIsNone(view["current_step"])
        self.assertIsNone(view["last_decision"])
        self.assertEqual(view["last_decision_reason"], "")

    def test_timed_out_status(self):
        state = StateCenter(query="timeout")
        state.set_status("timed_out", "max steps reached")

        view = build_live_view(state)

        self.assertEqual(view["status"], "timed_out")


class RenderLiveViewTest(unittest.TestCase):
    """Tests for render_live_view — terminal-safe text output."""

    def test_renders_completed_status(self):
        view = {
            "task_id": "abc-123",
            "status": "completed",
            "query": "research task",
            "current_step": "summarizer",
            "progress": "3/3",
            "steps_total": 3,
            "steps_completed": 3,
            "last_decision": "continue",
            "last_decision_reason": "",
            "last_failure": None,
            "human_review_required": False,
            "report_path": "outputs/reports/test.json",
            "evidence_path": None,
            "created_at": "2026-01-01T00:00:00Z",
        }

        text = render_live_view(view)

        self.assertIn("OK completed", text)
        self.assertIn("abc-123", text)
        self.assertIn("research task", text)
        self.assertIn("summarizer", text)
        self.assertIn("3/3", text)
        self.assertIn("continue", text)

    def test_renders_failed_status_with_failure_info(self):
        view = {
            "task_id": "xyz-456",
            "status": "failed",
            "query": "broken task",
            "current_step": "planner",
            "progress": "1/2",
            "steps_total": 2,
            "steps_completed": 1,
            "last_decision": "fail",
            "last_decision_reason": "evaluation failed at plan",
            "last_failure": {
                "category": "evaluation_failed",
                "severity": "critical",
                "agent_name": "planner",
                "reason": "missing sub_questions",
            },
            "human_review_required": False,
            "report_path": "outputs/reports/test.json",
            "evidence_path": None,
            "created_at": "2026-01-01T00:00:00Z",
        }

        text = render_live_view(view)

        self.assertIn("!! FAILED", text)
        self.assertIn("evaluation_failed", text)
        self.assertIn("critical", text)
        self.assertIn("missing sub_questions", text)

    def test_renders_human_review_required(self):
        view = {
            "task_id": "hr-789",
            "status": "needs_human_review",
            "query": "sensitive task",
            "current_step": "human_review",
            "progress": "3/4",
            "steps_total": 4,
            "steps_completed": 3,
            "last_decision": "continue",
            "last_decision_reason": "",
            "last_failure": None,
            "human_review_required": True,
            "report_path": None,
            "evidence_path": None,
            "created_at": "2026-01-01T00:00:00Z",
        }

        text = render_live_view(view)

        self.assertIn("?? WAIT", text)
        self.assertIn("ACTION REQUIRED", text)
        self.assertIn("resume --task-id hr-789", text)

    def test_renders_running_status(self):
        view = {
            "task_id": "run-001",
            "status": "running",
            "query": "in progress task",
            "current_step": "search",
            "progress": "1/4",
            "steps_total": 4,
            "steps_completed": 1,
            "last_decision": "continue",
            "last_decision_reason": "",
            "last_failure": None,
            "human_review_required": False,
            "report_path": None,
            "evidence_path": None,
            "created_at": "2026-01-01T00:00:00Z",
        }

        text = render_live_view(view)

        self.assertIn("... running", text)
        self.assertIn("search", text)
        self.assertIn("1/4", text)

    def test_renders_timed_out_status(self):
        view = {
            "task_id": "to-001",
            "status": "timed_out",
            "query": "slow task",
            "current_step": "summarizer",
            "progress": "2/4",
            "steps_total": 4,
            "steps_completed": 2,
            "last_decision": "retry",
            "last_decision_reason": "timeout",
            "last_failure": None,
            "human_review_required": False,
            "report_path": None,
            "evidence_path": None,
            "created_at": "2026-01-01T00:00:00Z",
        }

        text = render_live_view(view)

        self.assertIn("!! TIMED OUT", text)

    def test_renders_minimal_view_without_crash(self):
        view = {
            "task_id": "",
            "status": "",
            "query": "",
            "current_step": None,
            "progress": "0/0",
            "steps_total": 0,
            "steps_completed": 0,
            "last_decision": None,
            "last_decision_reason": "",
            "last_failure": None,
            "human_review_required": False,
            "report_path": None,
            "evidence_path": None,
            "created_at": "",
        }

        text = render_live_view(view)

        self.assertIsInstance(text, str)
        self.assertTrue(len(text) > 0)

    def test_rendered_output_is_ascii_safe(self):
        view = {
            "task_id": "test-001",
            "status": "completed",
            "query": "test",
            "current_step": "planner",
            "progress": "1/1",
            "steps_total": 1,
            "steps_completed": 1,
            "last_decision": "continue",
            "last_decision_reason": "",
            "last_failure": None,
            "human_review_required": False,
            "report_path": "out/test.json",
            "evidence_path": None,
            "created_at": "2026-01-01T00:00:00Z",
        }

        text = render_live_view(view)

        # Must be pure ASCII
        text.encode("ascii")


if __name__ == "__main__":
    unittest.main()

class BuildLiveViewProgressTest(unittest.TestCase):
    """Phase 7A Fix 4 — live view progress honest and useful."""

    def test_progress_uses_workflow_total_when_available(self):
        state = StateCenter(query="test")
        state.write("plan", {"sub_questions": ["Q1"]}, "planner")
        state.execution_trace.append({
            "event": "evaluation", "agent_name": "planner",
            "passed": True, "action": "continue", "reason": "", "timestamp": "t1",
        })
        state.set_status("running", "")

        view = build_live_view(state, workflow_total=3)
        self.assertEqual(view["steps_total"], 3)
        self.assertEqual(view["progress"], "1/3")

    def test_progress_has_honest_fallback_without_workflow(self):
        state = StateCenter(query="test")
        state.write("plan", {"sub_questions": ["Q1"]}, "planner")
        state.execution_trace.append({
            "event": "evaluation", "agent_name": "planner",
            "passed": True, "action": "continue", "reason": "", "timestamp": "t1",
        })
        state.set_status("running", "")

        view = build_live_view(state)
        self.assertEqual(view["steps_total"], 1)
        # Non-terminal + no workflow_total → unknown total to avoid fake progress
        self.assertEqual(view["progress"], "1/?")

    def test_reports_current_step_for_failed_run(self):
        state = StateCenter(query="failing task")
        state.execution_trace.append({
            "event": "evaluation", "agent_name": "planner",
            "passed": True, "action": "continue", "reason": "", "timestamp": "t1",
        })
        state.execution_trace.append({
            "event": "guardrail_violation",
            "agent_name": "summarizer",
            "guardrail_name": "block_secret",
            "stage": "output",
            "reason": "blocked",
            "failure_category": "guardrail_blocked",
            "timestamp": "t2",
        })
        state.execution_trace.append({
            "event": "failure_classified",
            "category": "guardrail_blocked",
            "severity": "high",
            "agent_name": "summarizer",
            "reason": "blocked",
            "timestamp": "t3",
        })
        state.set_status("failed", "blocked")

        view = build_live_view(state)
        self.assertEqual(view["status"], "failed")
        self.assertIsNotNone(view["current_step"])
        self.assertIn(view["current_step"], ("summarizer", "planner"))

    def test_reports_current_step_for_human_review_run(self):
        state = StateCenter(query="needs approval")
        state.execution_trace.append({
            "event": "evaluation", "agent_name": "planner",
            "passed": True, "action": "continue", "reason": "", "timestamp": "t1",
        })
        state.execution_trace.append({
            "event": "evaluation", "agent_name": "human_review",
            "passed": True, "action": "continue", "reason": "", "timestamp": "t2",
        })
        state.set_status("needs_human_review", "awaiting human")
        state.data_pool.intermediate["human_review_gate"] = {
            "decision": "await_human",
        }

        view = build_live_view(state)
        self.assertEqual(view["status"], "needs_human_review")
        self.assertTrue(view["human_review_required"])
        self.assertIsNotNone(view["current_step"])


# =============================================================================
# Phase 8 — New spec fields
# =============================================================================

class BuildLiveViewNewFieldsTest(unittest.TestCase):
    """Phase 8: build_live_view includes all spec-required fields."""

    def test_includes_run_mode(self):
        state = StateCenter(query="test")
        view = build_live_view(state)
        self.assertEqual(view["run_mode"], "controlled")

    def test_includes_current_worker_from_write_events(self):
        state = StateCenter(query="test")
        state.write("plan", {"sub_questions": ["Q1"]}, "planner")
        view = build_live_view(state)
        self.assertEqual(view["current_worker"], "planner")

    def test_current_worker_skips_memory_manager(self):
        state = StateCenter(query="test")
        state.write("memory_bundle", {"v": 1}, "memory_manager")
        state.write("plan", {"sub_questions": ["Q1"]}, "planner")
        view = build_live_view(state)
        self.assertEqual(view["current_worker"], "planner")

    def test_includes_failure_origin_from_classified_event(self):
        state = StateCenter(query="failing")
        state.execution_trace.append({
            "event": "failure_classified",
            "category": "guardrail_blocked",
            "severity": "high",
            "agent_name": "summarizer",
            "reason": "blocked secret",
            "origin": "control_plane",
            "recovery_hint": "fail",
            "timestamp": "t1",
        })
        state.set_status("failed", "blocked")
        view = build_live_view(state)
        self.assertEqual(view["last_failure_origin"], "control_plane")
        self.assertEqual(view["last_recovery_hint"], "fail")

    def test_includes_evaluator_decision(self):
        state = StateCenter(query="test")
        state.execution_trace.append({
            "event": "evaluation", "agent_name": "planner",
            "passed": True, "action": "continue", "reason": "all good",
            "timestamp": "t1",
        })
        view = build_live_view(state)
        self.assertIsNotNone(view["last_evaluator_decision"])
        self.assertEqual(view["last_evaluator_decision"]["action"], "continue")
        self.assertEqual(view["last_evaluator_decision"]["passed"], True)

    def test_includes_guardrail_decision(self):
        state = StateCenter(query="test")
        state.execution_trace.append({
            "event": "guardrail_violation",
            "agent_name": "summarizer",
            "guardrail_name": "block_sensitive",
            "stage": "output",
            "reason": "api_key found",
            "timestamp": "t1",
        })
        view = build_live_view(state)
        self.assertIsNotNone(view["last_guardrail_decision"])
        self.assertEqual(view["last_guardrail_decision"]["guardrail_name"], "block_sensitive")
        self.assertEqual(view["last_guardrail_decision"]["stage"], "output")

    def test_includes_policy_decision(self):
        state = StateCenter(query="test")
        state.execution_trace.append({
            "event": "checkpoint_replan",
            "target": "planner",
            "action": "re_plan",
            "reason": "Need stronger plan",
            "timestamp": "t1",
        })
        view = build_live_view(state)
        self.assertIsNotNone(view["last_policy_decision"])
        self.assertEqual(view["last_policy_decision"]["action"], "re_plan")
        self.assertEqual(view["last_policy_decision"]["target"], "planner")

    def test_includes_evidence_status_missing(self):
        state = StateCenter(query="test")
        view = build_live_view(state)
        self.assertEqual(view["evidence_status"], "missing")

    def test_includes_evidence_status_available(self):
        state = StateCenter(query="test")
        result = RunResult(
            task_id=state.metadata.task_id,
            status="completed",
            final_node="summarizer",
            reason="done",
            state_version=0,
            evidence_path="outputs/evidence/test.json",
        )
        view = build_live_view(state, result=result)
        self.assertEqual(view["evidence_status"], "available")

    def test_includes_human_review_state(self):
        state = StateCenter(query="test")
        state.set_status("needs_human_review", "awaiting human")
        view = build_live_view(state)
        self.assertEqual(view["human_review_state"], "awaiting_human")

    def test_human_review_state_none_when_not_required(self):
        state = StateCenter(query="test")
        state.set_status("running", "")
        view = build_live_view(state)
        self.assertEqual(view["human_review_state"], "none")

    def test_includes_elapsed_time(self):
        state = StateCenter(query="test")
        view = build_live_view(state)
        self.assertIn("elapsed", view)
        self.assertIsNotNone(view["elapsed"])

    def test_includes_started_at_and_updated_at(self):
        state = StateCenter(query="test")
        view = build_live_view(state)
        self.assertIn("started_at", view)
        self.assertIn("updated_at", view)
        self.assertTrue(len(view["started_at"]) > 0)


class BuildLiveViewBackwardCompatTest(unittest.TestCase):
    """Phase 8: backward compatibility — missing optional fields must not crash."""

    def test_handles_missing_optional_fields_in_failure_classified(self):
        """Old failure_classified events without origin/recovery_hint must work."""
        state = StateCenter(query="test")
        state.execution_trace.append({
            "event": "failure_classified",
            "category": "provider_error",
            "severity": "medium",
            "agent_name": "planner",
            "reason": "timeout",
            "timestamp": "t1",
        })
        state.set_status("failed", "timeout")
        view = build_live_view(state)
        self.assertIsNotNone(view["last_failure"])
        self.assertEqual(view["last_failure"]["category"], "provider_error")
        # Missing origin/recovery_hint → None
        self.assertIsNone(view["last_failure_origin"])
        self.assertIsNone(view["last_recovery_hint"])

    def test_handles_old_state_without_run_mode(self):
        """StateMetadata without run_mode should default to 'controlled'."""
        state = StateCenter(query="test")
        # Simulate old state: delete run_mode attribute
        if hasattr(state.metadata, "run_mode"):
            delattr(state.metadata, "run_mode")
        view = build_live_view(state)
        self.assertEqual(view["run_mode"], "controlled")

    def test_handles_old_state_without_updated_at(self):
        """StateMetadata without updated_at should return empty string."""
        state = StateCenter(query="test")
        if hasattr(state.metadata, "updated_at"):
            delattr(state.metadata, "updated_at")
        view = build_live_view(state)
        self.assertEqual(view["updated_at"], "")

    def test_empty_trace_handles_all_optional_cleanly(self):
        """No trace events at all — every optional field must be safe."""
        state = StateCenter(query="minimal")
        state.set_status("running", "")
        view = build_live_view(state)
        # All optional fields should be None or safe defaults
        self.assertIsNone(view["current_worker"])
        self.assertIsNone(view["last_evaluator_decision"])
        self.assertIsNone(view["last_guardrail_decision"])
        self.assertIsNone(view["last_policy_decision"])
        self.assertIsNone(view["last_failure"])
        self.assertIsNone(view["last_failure_origin"])
        self.assertIsNone(view["last_recovery_hint"])
        self.assertEqual(view["evidence_status"], "missing")
        self.assertEqual(view["human_review_state"], "none")

    def test_does_not_fake_progress_when_step_fields_are_missing(self):
        """When there are no eval events, progress must be 0/0, not guessed."""
        state = StateCenter(query="test")
        state.set_status("running", "")
        view = build_live_view(state)
        self.assertEqual(view["steps_total"], 0)
        self.assertEqual(view["steps_completed"], 0)
        self.assertEqual(view["progress"], "0/0")

    def test_non_terminal_without_workflow_total_shows_unknown_total(self):
        """P2: running state without workflow_total must show ? not fake 1/1."""
        state = StateCenter(query="test")
        state.write("plan", {"sub_questions": ["Q1"]}, "planner")
        state.execution_trace.append({
            "event": "evaluation", "agent_name": "planner",
            "passed": True, "action": "continue", "reason": "", "timestamp": "t1",
        })
        state.set_status("running", "")
        view = build_live_view(state)
        self.assertEqual(view["progress"], "1/?")

    def test_terminal_state_without_workflow_total_shows_known_total(self):
        """Terminal state: agent count is trustworthy, show real numbers."""
        state = StateCenter(query="test")
        state.write("plan", {"sub_questions": ["Q1"]}, "planner")
        state.execution_trace.append({
            "event": "evaluation", "agent_name": "planner",
            "passed": True, "action": "continue", "reason": "", "timestamp": "t1",
        })
        state.set_status("completed", "done")
        view = build_live_view(state)
        self.assertEqual(view["progress"], "1/1")

    def test_renders_without_crash_when_all_optional_missing(self):
        """render_live_view must not crash with a view missing new optional fields."""
        minimal_view = {
            "task_id": "t1",
            "status": "running",
            "run_mode": "controlled",
            "query": "test",
            "current_step": None,
            "current_worker": None,
            "progress": "0/0",
            "steps_total": 0,
            "steps_completed": 0,
            "last_decision": None,
            "last_decision_reason": "",
            "last_evaluator_decision": None,
            "last_guardrail_decision": None,
            "last_policy_decision": None,
            "last_failure": None,
            "last_failure_origin": None,
            "last_recovery_hint": None,
            "evidence_status": "missing",
            "human_review_required": False,
            "human_review_state": "none",
            "report_path": None,
            "evidence_path": None,
            "started_at": "",
            "updated_at": "",
            "elapsed": "",
        }
        text = render_live_view(minimal_view)
        self.assertIsInstance(text, str)
        self.assertTrue(len(text) > 0)
        text.encode("ascii")


# =============================================================================
# Phase 8 — is_terminal
# =============================================================================

class IsTerminalTest(unittest.TestCase):
    """Phase 8: is_terminal correctly identifies terminal states."""

    def test_running_is_not_terminal(self):
        self.assertFalse(is_terminal("running"))

    def test_completed_is_terminal(self):
        self.assertTrue(is_terminal("completed"))

    def test_failed_is_terminal(self):
        self.assertTrue(is_terminal("failed"))

    def test_timed_out_is_terminal(self):
        self.assertTrue(is_terminal("timed_out"))

    def test_guardrail_blocked_is_terminal(self):
        self.assertTrue(is_terminal("guardrail_blocked"))

    def test_cancelled_is_terminal(self):
        self.assertTrue(is_terminal("cancelled"))

    def test_human_rejected_is_terminal(self):
        self.assertTrue(is_terminal("human_rejected"))

    def test_needs_human_review_is_terminal(self):
        """needs_human_review is terminal — run waits for human input."""
        self.assertTrue(is_terminal("needs_human_review"))


# =============================================================================
# Phase 8 — Render includes new fields
# =============================================================================

class RenderLiveViewNewFieldsTest(unittest.TestCase):
    """Phase 8: render_live_view shows new spec-required fields."""

    def _base_view(self) -> dict:
        return {
            "task_id": "abc-123",
            "status": "running",
            "run_mode": "orchestrated",
            "query": "research task",
            "current_step": "planner",
            "current_worker": "planner",
            "progress": "1/3",
            "steps_total": 3,
            "steps_completed": 1,
            "last_decision": "continue",
            "last_decision_reason": "",
            "last_evaluator_decision": None,
            "last_guardrail_decision": None,
            "last_policy_decision": None,
            "last_failure": None,
            "last_failure_origin": None,
            "last_recovery_hint": None,
            "evidence_status": "missing",
            "human_review_required": False,
            "human_review_state": "none",
            "report_path": None,
            "evidence_path": None,
            "started_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:01:00Z",
            "elapsed": "1m 0s",
        }

    def test_renders_run_mode(self):
        view = self._base_view()
        text = render_live_view(view)
        self.assertIn("orchestrated", text)

    def test_renders_worker(self):
        view = self._base_view()
        text = render_live_view(view)
        self.assertIn("Worker:", text)
        self.assertIn("planner", text)

    def test_renders_evaluator_decision(self):
        view = self._base_view()
        view["last_evaluator_decision"] = {
            "action": "continue", "reason": "all good", "passed": True,
        }
        text = render_live_view(view)
        self.assertIn("Evaluator:", text)
        self.assertIn("PASS", text)
        self.assertIn("continue", text)

    def test_renders_guardrail_decision(self):
        view = self._base_view()
        view["last_guardrail_decision"] = {
            "guardrail_name": "block_sensitive", "stage": "output",
            "reason": "api_key found",
        }
        text = render_live_view(view)
        self.assertIn("Guardrail:", text)
        self.assertIn("block_sensitive", text)

    def test_renders_policy_decision(self):
        view = self._base_view()
        view["last_policy_decision"] = {
            "target": "planner", "action": "re_plan",
            "reason": "Need stronger plan",
        }
        text = render_live_view(view)
        self.assertIn("Policy:", text)
        self.assertIn("re_plan", text)

    def test_renders_failure_with_origin_and_recovery(self):
        view = self._base_view()
        view["status"] = "failed"
        view["last_failure"] = {
            "category": "guardrail_blocked", "severity": "high",
            "agent_name": "summarizer", "reason": "blocked secret",
        }
        view["last_failure_origin"] = "control_plane"
        view["last_recovery_hint"] = "fail"
        text = render_live_view(view)
        self.assertIn("Origin:", text)
        self.assertIn("control_plane", text)
        self.assertIn("Recovery:", text)
        self.assertIn("fail", text)

    def test_renders_human_review_state(self):
        view = self._base_view()
        view["status"] = "needs_human_review"
        view["human_review_required"] = True
        view["human_review_state"] = "awaiting_human"
        text = render_live_view(view)
        self.assertIn("Human Review:", text)
        self.assertIn("awaiting_human", text)
        self.assertIn("ACTION REQUIRED", text)

    def test_renders_elapsed_time(self):
        view = self._base_view()
        text = render_live_view(view)
        self.assertIn("Elapsed:", text)
        self.assertIn("1m 0s", text)

    def test_renders_evidence_status(self):
        view = self._base_view()
        text = render_live_view(view)
        self.assertIn("Evidence:", text)
        self.assertIn("missing", text)

    def test_renders_guardrail_blocked_status(self):
        view = self._base_view()
        view["status"] = "guardrail_blocked"
        text = render_live_view(view)
        self.assertIn("BLOCKED", text)
