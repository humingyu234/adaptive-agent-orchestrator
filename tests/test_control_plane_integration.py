"""Integration tests for Phase 3 - Scheduler uses ControlPlane.

Proves that wiring ControlPlane into Scheduler does not break existing
runtime behavior, and that control-plane-level events are produced.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator import agents as _agents  # noqa: F401
from orchestrator.agents.base import BaseAgent
from orchestrator.control_plane import ControlPlane
from orchestrator.models import AgentConfig, WriteSpec
from orchestrator.registry import register
from orchestrator.scheduler import Scheduler
from orchestrator.workflow import load_workflow


@register("noop_writer")
class NoopWriterAgent(BaseAgent):
    config = AgentConfig(
        name="noop_writer",
        reads=["query"],
        writes=[WriteSpec(field="summary", schema_name="SummarySchema")],
        max_retries=1,
    )

    def run(self, context_view: dict) -> dict:
        return {"summary": {"conclusion": "done", "plan_type": "research"}}


@register("sensitive_writer")
class SensitiveWriterAgent(BaseAgent):
    config = AgentConfig(
        name="sensitive_writer",
        reads=["query"],
        writes=[WriteSpec(field="summary", schema_name="SummarySchema")],
        guardrails=["require_non_empty_query", "block_sensitive_output_terms"],
        max_retries=1,
    )

    def run(self, context_view: dict) -> dict:
        return {
            "summary": {
                "conclusion": "do not expose api_key in final output",
            }
        }


class TestStandardWorkflow:
    def test_completes_with_evaluation_trace(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(project_root / "workflows" / "deep_research.yaml")

        with tempfile.TemporaryDirectory() as tmp:
            scheduler = Scheduler(workflow=workflow, project_root=tmp)
            state, result = scheduler.run(query="solid-state battery progress")

            assert result.status == "completed"
            assert Path(result.convergence_report_path).exists()

            evaluations = [
                e for e in state.execution_trace if e.get("event") == "evaluation"
            ]
            assert len(evaluations) >= 1
            assert all("passed" in e for e in evaluations)
            assert all("action" in e for e in evaluations)

    def test_evidence_generated_and_live_view_renders(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(project_root / "workflows" / "deep_research.yaml")

        with tempfile.TemporaryDirectory() as tmp:
            scheduler = Scheduler(workflow=workflow, project_root=tmp)
            state, result = scheduler.run(query="solid-state battery progress")

            assert result.status == "completed"

            # evidence file exists
            if result.evidence_path:
                assert Path(result.evidence_path).exists()

            # live view renders without crashing
            from orchestrator.live_view import build_live_view, render_live_view

            view = build_live_view(state, result=result)
            assert view["status"] == "completed"
            assert view["task_id"] == state.metadata.task_id
            text = render_live_view(view)
            assert "OK completed" in text
            assert isinstance(text, str) and len(text) > 0

    def test_control_plane_is_wired_in_scheduler(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(project_root / "workflows" / "deep_research.yaml")

        with tempfile.TemporaryDirectory() as tmp:
            scheduler = Scheduler(workflow=workflow, project_root=tmp)
            assert isinstance(scheduler.control_plane, ControlPlane)


class TestHumanReviewWorkflow:
    def test_pauses_with_needs_human_review_status(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(
            project_root / "workflows" / "deep_research_human_review.yaml"
        )

        with tempfile.TemporaryDirectory() as tmp:
            scheduler = Scheduler(workflow=workflow, project_root=tmp)
            state, result = scheduler.run(query="solid-state battery progress")

            assert result.status == "needs_human_review"
            assert result.final_node == "human_review"
            assert "human_review_gate" in state.data_pool.intermediate

            gate = state.data_pool.intermediate["human_review_gate"]
            assert gate["decision"] == "await_human"
            assert gate["approval_required"] is True

    def test_live_view_reports_human_review_required(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(
            project_root / "workflows" / "deep_research_human_review.yaml"
        )

        with tempfile.TemporaryDirectory() as tmp:
            scheduler = Scheduler(workflow=workflow, project_root=tmp)
            state, result = scheduler.run(query="solid-state battery progress")

            from orchestrator.live_view import build_live_view, render_live_view

            view = build_live_view(state, result=result)
            assert view["status"] == "needs_human_review"
            assert view["human_review_required"] is True

            text = render_live_view(view)
            assert "WAIT" in text
            assert "ACTION REQUIRED" in text

    def test_resume_approve_completes_after_human_gate(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(
            project_root / "workflows" / "deep_research_human_review.yaml"
        )

        with tempfile.TemporaryDirectory() as tmp:
            scheduler = Scheduler(workflow=workflow, project_root=tmp)
            state, result = scheduler.run(query="solid-state battery progress")

            assert result.status == "needs_human_review"

            state2, result2 = scheduler.resume_human_review(
                state=state, decision="approve", reason="looks good"
            )
            assert result2.status == "completed"


class TestGuardrailViolation:
    def test_empty_query_fails_with_guardrail_trace(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(project_root / "workflows" / "deep_research.yaml")

        with tempfile.TemporaryDirectory() as tmp:
            scheduler = Scheduler(workflow=workflow, project_root=tmp)
            state, result = scheduler.run(query="   ")

            assert result.status == "failed"
            violations = [
                e
                for e in state.execution_trace
                if e.get("event") == "guardrail_violation"
            ]
            assert len(violations) == 1
            assert violations[0]["stage"] == "input"
            assert "failure_category" in violations[0]

    def test_sensitive_output_fails_with_guardrail_trace(self):
        workflow = {
            "name": "sensitive_guardrail_integration",
            "max_steps": 2,
            "agents": [{"name": "sensitive_writer"}],
        }

        with tempfile.TemporaryDirectory() as tmp:
            scheduler = Scheduler(workflow=workflow, project_root=tmp)
            state, result = scheduler.run(query="safe query")

            assert result.status == "failed"
            assert result.final_node == "sensitive_writer"

            violations = [
                e
                for e in state.execution_trace
                if e.get("event") == "guardrail_violation"
            ]
            assert len(violations) == 1
            assert violations[0]["stage"] == "output"

            classified = [
                e
                for e in state.execution_trace
                if e.get("event") == "failure_classified"
            ]
            assert len(classified) == 1
            assert classified[0]["category"] == "guardrail_blocked"


class TestFailureClassifiedEvent:
    def test_failure_classified_trace_present_on_failed_run(self):
        workflow = {
            "name": "failing_flow",
            "max_steps": 5,
            "agents": [{"name": "sensitive_writer"}],
        }

        with tempfile.TemporaryDirectory() as tmp:
            scheduler = Scheduler(workflow=workflow, project_root=tmp)
            state, result = scheduler.run(query="safe query")

            assert result.status == "failed"

            classified = [
                e
                for e in state.execution_trace
                if e.get("event") == "failure_classified"
            ]
            assert len(classified) == 1
            assert "category" in classified[0]
            assert "severity" in classified[0]
            assert classified[0]["severity"] in ("low", "medium", "high", "critical")

    def test_failure_classified_not_present_on_successful_run(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(project_root / "workflows" / "deep_research.yaml")

        with tempfile.TemporaryDirectory() as tmp:
            scheduler = Scheduler(workflow=workflow, project_root=tmp)
            state, result = scheduler.run(query="solid-state battery progress")

            assert result.status == "completed"

            classified = [
                e
                for e in state.execution_trace
                if e.get("event") == "failure_classified"
            ]
            assert len(classified) == 0

    def test_timed_out_run_has_failure_classified(self):
        workflow = {
            "name": "timeout_flow",
            "max_steps": 1,
            "agents": [
                {"name": "planner"},
                {"name": "search"},
                {"name": "summarizer"},
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            scheduler = Scheduler(workflow=workflow, project_root=tmp)
            state, result = scheduler.run(query="test query")

            assert result.status == "timed_out", (
                f"Expected timed_out, got {result.status}"
            )
            classified = [
                e
                for e in state.execution_trace
                if e.get("event") == "failure_classified"
            ]
            assert len(classified) == 1


class TestEvaluatorFailure:
    def test_missing_field_output_produces_non_continue_decision(self):
        from orchestrator.control_plane import ControlPlane
        from orchestrator.evaluator import Evaluator
        from orchestrator.models import EvalCriteriaItem

        evaluator = Evaluator(enable_l2=False)
        cp = ControlPlane(evaluator=evaluator)

        criteria = [
            EvalCriteriaItem(
                path="required_summary",
                expected_type="non_empty_str",
                action="fail",
                reason="missing required field",
            )
        ]

        decision = cp.evaluate_output(
            criteria=criteria,
            output={"wrong_field": "some value"},
            context={},
        )

        assert decision.passed is False
        assert decision.action != "continue"

    def test_valid_output_produces_continue_decision(self):
        from orchestrator.control_plane import ControlPlane
        from orchestrator.evaluator import Evaluator
        from orchestrator.models import EvalCriteriaItem

        evaluator = Evaluator(enable_l2=False)
        cp = ControlPlane(evaluator=evaluator)

        criteria = [
            EvalCriteriaItem(
                path="my_field",
                expected_type="non_empty_str",
                action="fail",
                reason="missing required field",
            )
        ]

        decision = cp.evaluate_output(
            criteria=criteria,
            output={"my_field": "valid content"},
            context={},
        )

        assert decision.passed is True
        assert decision.action == "continue"

    def test_list_min_items_violation_produces_fail(self):
        from orchestrator.control_plane import ControlPlane
        from orchestrator.evaluator import Evaluator
        from orchestrator.models import EvalCriteriaItem

        evaluator = Evaluator(enable_l2=False)
        cp = ControlPlane(evaluator=evaluator)

        criteria = [
            EvalCriteriaItem(
                path="items",
                expected_type="list",
                min_items=3,
                action="retry",
                reason="too few items",
            )
        ]

        decision = cp.evaluate_output(
            criteria=criteria,
            output={"items": [1]},
            context={},
        )

        assert decision.passed is False
        assert decision.action == "retry"

class TestSchedulerControlPlaneRouting:
    """Phase 7A Fix 2 — Scheduler guardrails route through ControlPlane."""

    def test_scheduler_uses_control_plane_for_input_guardrail(self):
        """Empty query fails via ControlPlane, not agent method."""
        project_root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(project_root / "workflows" / "deep_research.yaml")

        with tempfile.TemporaryDirectory() as tmp:
            scheduler = Scheduler(workflow=workflow, project_root=tmp)
            state, result = scheduler.run(query="   ")

            assert result.status == "failed"
            violations = [
                e for e in state.execution_trace
                if e.get("event") == "guardrail_violation"
            ]
            assert len(violations) == 1
            assert violations[0]["stage"] == "input"
            assert "failure_category" in violations[0]

    def test_scheduler_uses_control_plane_for_output_guardrail(self):
        """Sensitive output fails via ControlPlane output guard."""
        workflow = {
            "name": "cp_output_guard_test",
            "max_steps": 2,
            "agents": [{"name": "sensitive_writer"}],
        }

        with tempfile.TemporaryDirectory() as tmp:
            scheduler = Scheduler(workflow=workflow, project_root=tmp)
            state, result = scheduler.run(query="safe query")

            assert result.status == "failed"
            violations = [
                e for e in state.execution_trace
                if e.get("event") == "guardrail_violation"
            ]
            assert len(violations) >= 1
            output_violations = [v for v in violations if v.get("stage") == "output"]
            assert len(output_violations) >= 1

    def test_scheduler_preserves_guardrail_violation_trace_shape(self):
        """Guardrail violation trace has all required fields."""
        project_root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(project_root / "workflows" / "deep_research.yaml")

        with tempfile.TemporaryDirectory() as tmp:
            scheduler = Scheduler(workflow=workflow, project_root=tmp)
            state, result = scheduler.run(query="   ")

            assert result.status == "failed"
            violations = [
                e for e in state.execution_trace
                if e.get("event") == "guardrail_violation"
            ]
            assert len(violations) == 1
            v = violations[0]
            for key in ("event", "agent_name", "stage", "reason", "failure_category", "timestamp"):
                assert key in v, f"Missing key {key} in guardrail_violation trace"

    def test_scheduler_preserves_human_review_pause_after_control_plane_guardrails(self):
        """Human review pause/resume still works with ControlPlane routing."""
        project_root = Path(__file__).resolve().parents[1]
        workflow = load_workflow(
            project_root / "workflows" / "deep_research_human_review.yaml"
        )

        with tempfile.TemporaryDirectory() as tmp:
            scheduler = Scheduler(workflow=workflow, project_root=tmp)
            state, result = scheduler.run(query="solid-state battery progress")

            assert result.status == "needs_human_review"
            assert "human_review_gate" in state.data_pool.intermediate

            state2, result2 = scheduler.resume_human_review(
                state=state, decision="approve", reason="looks good"
            )
            assert result2.status == "completed"


class TestExplicitFailureCategory:
    """Prove explicit categories skip infer_failure_category fallback."""

    @staticmethod
    def _run_with_mocked_infer(workflow, query, project_root):
        """Run a workflow with infer_failure_category mocked to raise."""
        import orchestrator.failure_taxonomy as _ft
        import orchestrator.control_plane as _cp

        original_infer = _ft.infer_failure_category
        original_classify = _ft.classify_failure

        def _explosive_infer(*, status, reason, **__):
            raise AssertionError(
                f"infer_failure_category was called for known failure: "
                f"status={status!r} reason={reason!r}"
            )

        def _explosive_classify(*, status, reason, **__):
            raise AssertionError(
                f"classify_failure was called for known failure: "
                f"status={status!r} reason={reason!r}"
            )

        _ft.infer_failure_category = _explosive_infer
        _ft.classify_failure = _explosive_classify
        _cp.classify_failure = _explosive_classify
        try:
            scheduler = Scheduler(workflow=workflow, project_root=project_root)
            return scheduler.run(query=query)
        finally:
            _ft.infer_failure_category = original_infer
            _ft.classify_failure = original_classify
            _cp.classify_failure = original_classify

    def test_guardrail_failure_does_not_call_infer(self):
        """Guardrail blocked by ControlPlane must not call infer_failure_category."""
        workflow = {
            "name": "guardrail_no_infer",
            "max_steps": 2,
            "agents": [{"name": "sensitive_writer"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            state, result = self._run_with_mocked_infer(
                workflow=workflow, query="safe query", project_root=tmp
            )
            assert result.status == "failed"
            classified = [
                e for e in state.execution_trace
                if e.get("event") == "failure_classified"
            ]
            assert len(classified) == 1
            assert classified[0]["category"] == "guardrail_blocked"

    def test_max_steps_failure_does_not_call_infer(self):
        """Max-steps exceeded must not call infer_failure_category."""
        workflow = {
            "name": "max_steps_no_infer",
            "max_steps": 1,
            "agents": [
                {"name": "planner"},
                {"name": "search"},
                {"name": "summarizer"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            state, result = self._run_with_mocked_infer(
                workflow=workflow, query="test query", project_root=tmp
            )
            assert result.status == "timed_out"
            classified = [
                e for e in state.execution_trace
                if e.get("event") == "failure_classified"
            ]
            assert len(classified) == 1
            assert classified[0]["category"] == "policy_error"

    def test_retry_exhausted_does_not_call_infer(self):
        """Retry exhaustion must not call infer_failure_category."""
        from orchestrator.agents.base import BaseAgent
        from orchestrator.models import AgentConfig, WriteSpec

        @register("retry_exhausted_agent")
        class RetryExhaustedAgent(BaseAgent):
            config = AgentConfig(
                name="retry_exhausted_agent",
                reads=["query"],
                writes=[WriteSpec(field="summary", schema_name="SummarySchema")],
                eval_criteria=[{
                    "path": "required_field",
                    "expected_type": "non_empty_str",
                    "action": "retry",
                    "reason": "missing required field",
                }],
                max_retries=2,
            )

            def run(self, context_view: dict) -> dict:
                return {"summary": {"conclusion": "done"}}

        workflow = {
            "name": "retry_exhausted_no_infer",
            "max_steps": 10,
            "agents": [{"name": "retry_exhausted_agent"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            state, result = self._run_with_mocked_infer(
                workflow=workflow, query="test query", project_root=tmp
            )
            assert result.status == "failed"
            classified = [
                e for e in state.execution_trace
                if e.get("event") == "failure_classified"
            ]
            assert len(classified) == 1
            assert classified[0]["category"] == "tool_error"

    def test_evaluation_failed_does_not_call_infer(self):
        """Evaluation failure must not call infer_failure_category."""
        from orchestrator.agents.base import BaseAgent
        from orchestrator.models import AgentConfig, WriteSpec

        @register("eval_fail_agent")
        class EvalFailAgent(BaseAgent):
            config = AgentConfig(
                name="eval_fail_agent",
                reads=["query"],
                writes=[WriteSpec(field="summary", schema_name="SummarySchema")],
                eval_criteria=[{
                    "path": "required_field",
                    "expected_type": "non_empty_str",
                    "action": "fail",
                    "reason": "missing required field",
                }],
                max_retries=1,
            )

            def run(self, context_view: dict) -> dict:
                return {"summary": {"conclusion": "done"}}

        workflow = {
            "name": "eval_fail_no_infer",
            "max_steps": 10,
            "agents": [{"name": "eval_fail_agent"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            state, result = self._run_with_mocked_infer(
                workflow=workflow, query="test query", project_root=tmp
            )
            assert result.status == "failed"
            classified = [
                e for e in state.execution_trace
                if e.get("event") == "failure_classified"
            ]
            assert len(classified) == 1
            assert classified[0]["category"] == "task_quality_error"

    def test_unknown_runtime_error_still_may_use_infer_fallback(self):
        """Unknown exception path is allowed to call infer_failure_category."""
        from orchestrator.agents.base import BaseAgent
        from orchestrator.models import AgentConfig, WriteSpec

        @register("crash_agent")
        class CrashAgent(BaseAgent):
            config = AgentConfig(
                name="crash_agent",
                reads=["query"],
                writes=[WriteSpec(field="summary", schema_name="SummarySchema")],
                max_retries=1,
            )

            def run(self, context_view: dict) -> dict:
                raise RuntimeError("unexpected worker crash")

        workflow = {
            "name": "crash_no_explicit_category",
            "max_steps": 10,
            "agents": [{"name": "crash_agent"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = Scheduler(workflow=workflow, project_root=tmp)
            state, result = scheduler.run(query="test query")

            assert result.status == "failed"
            classified = [
                e for e in state.execution_trace
                if e.get("event") == "failure_classified"
            ]
            assert len(classified) == 1
            assert "category" in classified[0]
            assert "severity" in classified[0]

    def test_orchestrator_fail_does_not_call_infer(self):
        """Orchestrator fail decision must not call infer_failure_category."""
        import orchestrator.failure_taxonomy as _ft
        import orchestrator.control_plane as _cp
        from orchestrator.agents.base import BaseAgent
        from orchestrator.models import AgentConfig, WriteSpec
        from orchestrator.supervisor_orchestrator import OrchestrationDecision

        @register("orch_fail_agent")
        class OrchFailAgent(BaseAgent):
            config = AgentConfig(
                name="orch_fail_agent",
                reads=["query"],
                writes=[WriteSpec(field="plan", schema_name="PlanSchema")],
                eval_criteria=[{
                    "path": "plan",
                    "expected_type": "dict",
                    "action": "continue",
                }],
                max_retries=1,
            )

            def run(self, context_view: dict) -> dict:
                return {"plan": {"directions": ["task A"]}}

        workflow = {
            "name": "orch_fail_no_infer",
            "max_steps": 10,
            "agents": [{"name": "orch_fail_agent"}],
        }

        original_infer = _ft.infer_failure_category
        original_classify = _ft.classify_failure
        original_cp_classify = _cp.classify_failure

        def _explosive(*, status, reason, **__):
            raise AssertionError(
                f"fallback was called for known failure: "
                f"status={status!r} reason={reason!r}"
            )

        _ft.infer_failure_category = _explosive
        _ft.classify_failure = _explosive
        _cp.classify_failure = _explosive
        try:
            with tempfile.TemporaryDirectory() as tmp:
                scheduler = Scheduler(
                    workflow=workflow, project_root=tmp, use_orchestrator=True,
                )
                scheduler.orchestrator.decide_next_step = (
                    lambda **__: OrchestrationDecision(
                        action="fail", reason="too many iterations",
                    )
                )
                state, result = scheduler.run(query="test query")

                assert result.status == "failed"
                classified = [
                    e for e in state.execution_trace
                    if e.get("event") == "failure_classified"
                ]
                assert len(classified) == 1
                assert classified[0]["category"] == "policy_error"
        finally:
            _ft.infer_failure_category = original_infer
            _ft.classify_failure = original_classify
            _cp.classify_failure = original_cp_classify

