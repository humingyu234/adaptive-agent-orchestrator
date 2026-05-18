"""Tests for ControlPlane — the runner-independent control facade."""

from __future__ import annotations

import pytest

from src.orchestrator.control_models import ControlDecision
from src.orchestrator.control_plane import ControlPlane
from src.orchestrator.evaluator import Evaluator
from src.orchestrator.failure_taxonomy import FailureCategory, FailureRecord
from src.orchestrator.guardrails import GuardrailManager, GuardrailViolation
from src.orchestrator.models import EvalCriteriaItem


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _cp() -> ControlPlane:
    return ControlPlane()


# ===========================================================================
# 1. valid output produces a continue decision
# ===========================================================================

class TestEvaluateOutputValid:
    def test_passes_when_output_matches_criteria(self):
        cp = _cp()
        criteria = [EvalCriteriaItem(path="value", expected_type="str")]
        output = {"value": "hello"}
        decision = cp.evaluate_output(criteria, output)
        assert decision.passed is True
        assert decision.action == "continue"

    def test_passes_when_all_criteria_met(self):
        cp = _cp()
        criteria = [
            EvalCriteriaItem(path="name", expected_type="str"),
            EvalCriteriaItem(path="count", expected_type="str"),
        ]
        output = {"name": "task1", "count": "3"}
        decision = cp.evaluate_output(criteria, output)
        assert decision.passed is True
        assert decision.action == "continue"


# ===========================================================================
# 2. evaluator failure produces a non-continue decision
# ===========================================================================

class TestEvaluateOutputFailure:
    def test_fails_on_missing_path(self):
        cp = _cp()
        criteria = [EvalCriteriaItem(path="required_field", expected_type="str", action="retry")]
        output = {}
        decision = cp.evaluate_output(criteria, output)
        assert decision.passed is False
        assert decision.action != "continue"
        assert decision.failure_category == FailureCategory.TASK_QUALITY_ERROR.value

    def test_maps_re_plan_to_replan_action(self):
        cp = _cp()
        criteria = [EvalCriteriaItem(path="x", expected_type="str", action="re_plan")]
        output = {}
        decision = cp.evaluate_output(criteria, output)
        assert decision.passed is False
        assert decision.action == "replan"

    def test_maps_fail_action(self):
        cp = _cp()
        criteria = [EvalCriteriaItem(path="x", expected_type="str", action="fail")]
        output = {}
        decision = cp.evaluate_output(criteria, output)
        assert decision.passed is False
        assert decision.action == "fail"

    def test_includes_severity_from_eval_level(self):
        cp = _cp()
        criteria = [EvalCriteriaItem(path="x", expected_type="str")]
        output = {}
        decision = cp.evaluate_output(criteria, output)
        assert decision.passed is False
        assert decision.severity is not None
        assert decision.severity in ("low", "medium", "high", "critical")

    def test_evaluation_failure_includes_recovery_hint(self):
        cp = _cp()
        criteria = [EvalCriteriaItem(path="x", expected_type="str", action="retry")]
        output = {}
        decision = cp.evaluate_output(criteria, output)
        assert decision.passed is False
        assert decision.recovery_hint is not None
        assert decision.recovery_hint == "retry"

    def test_evaluation_failure_includes_failure_origin(self):
        cp = _cp()
        criteria = [EvalCriteriaItem(path="x", expected_type="str")]
        output = {}
        decision = cp.evaluate_output(criteria, output)
        assert decision.passed is False
        assert decision.failure_origin == "control_plane"


# ===========================================================================
# 3. input guardrail violation produces fail + guardrail category
# ===========================================================================

class TestGuardInputViolation:
    def test_empty_query_triggers_input_guardrail(self):
        cp = _cp()
        decision = cp.guard_input(
            agent_name="test_agent",
            payload={"query": ""},
        )
        assert decision.passed is False
        assert decision.action == "fail"
        assert decision.failure_category == FailureCategory.GUARDRAIL_BLOCKED.value

    def test_whitespace_only_query_triggers_input_guardrail(self):
        cp = _cp()
        decision = cp.guard_input(
            agent_name="test_agent",
            payload={"query": "   "},
        )
        assert decision.passed is False
        assert decision.action == "fail"

    def test_input_guardrail_includes_recovery_hint_and_origin(self):
        cp = _cp()
        decision = cp.guard_input(
            agent_name="test_agent",
            payload={"query": ""},
        )
        assert decision.passed is False
        assert decision.recovery_hint == "fail"
        assert decision.failure_origin == "control_plane"

    def test_valid_query_passes_input_guardrail(self):
        cp = _cp()
        decision = cp.guard_input(
            agent_name="test_agent",
            payload={"query": "real question"},
        )
        assert decision.passed is True
        assert decision.action == "continue"


# ===========================================================================
# 4. output guardrail violation produces fail + guardrail category
# ===========================================================================

class TestGuardOutputViolation:
    def test_sensitive_term_triggers_output_guardrail(self):
        cp = _cp()
        decision = cp.guard_output(
            agent_name="test_agent",
            payload={"text": "here is an api_key: abc123"},
        )
        assert decision.passed is False
        assert decision.action == "fail"
        assert decision.failure_category == FailureCategory.GUARDRAIL_BLOCKED.value

    def test_password_term_triggers_output_guardrail(self):
        cp = _cp()
        decision = cp.guard_output(
            agent_name="test_agent",
            payload={"text": "password=secret"},
        )
        assert decision.passed is False
        assert decision.action == "fail"

    def test_clean_output_passes_guardrail(self):
        cp = _cp()
        decision = cp.guard_output(
            agent_name="test_agent",
            payload={"text": "all clear"},
        )
        assert decision.passed is True
        assert decision.action == "continue"


# ===========================================================================
# 5. failure classification returns a structured failure record/category
# ===========================================================================

class TestClassifyFailure:
    def test_returns_failure_record(self):
        cp = _cp()
        record = cp.classify_failure(
            status="timed_out",
            reason="timed out waiting",
        )
        assert isinstance(record, FailureRecord)
        assert record.category == FailureCategory.PROVIDER_ERROR

    def test_guardrail_status_maps_to_guardrail_blocked(self):
        cp = _cp()
        record = cp.classify_failure(
            status="guardrail_blocked",
            reason="blocked by guard",
        )
        assert record.category == FailureCategory.GUARDRAIL_BLOCKED

    def test_includes_agent_name_when_provided(self):
        cp = _cp()
        record = cp.classify_failure(
            status="failed",
            reason="something broke",
            agent_name="planner",
        )
        assert record.agent_name == "planner"


# ===========================================================================
# 6. make_decision composite
# ===========================================================================

class TestMakeDecision:
    def test_returns_continue_when_both_pass(self):
        cp = _cp()
        criteria = [EvalCriteriaItem(path="val", expected_type="str")]
        output = {"val": "ok"}
        payload = {"query": "real query", "val": "ok"}
        decision = cp.make_decision(
            criteria=criteria,
            output=output,
            agent_name="test_agent",
            payload=payload,
        )
        assert decision.passed is True
        assert decision.action == "continue"

    def test_eval_failure_takes_priority(self):
        cp = _cp()
        criteria = [EvalCriteriaItem(path="missing", expected_type="str", action="retry")]
        output = {}
        payload = {"query": "real query"}
        decision = cp.make_decision(
            criteria=criteria,
            output=output,
            agent_name="test_agent",
            payload=payload,
        )
        assert decision.passed is False
        assert decision.action == "retry"

    def test_output_guard_failure_after_eval_pass(self):
        cp = _cp()
        criteria = [EvalCriteriaItem(path="val", expected_type="str")]
        output = {"val": "ok", "text": "contains api_key secret"}
        payload = {"query": "real query", "val": "ok"}
        decision = cp.make_decision(
            criteria=criteria,
            output=output,
            agent_name="test_agent",
            payload=payload,
        )
        assert decision.passed is False
        assert decision.failure_category == FailureCategory.GUARDRAIL_BLOCKED.value

    def test_input_guard_runs_first_in_make_decision(self):
        cp = _cp()
        criteria = [EvalCriteriaItem(path="val", expected_type="str")]
        output = {"val": "ok"}
        payload = {"query": ""}
        decision = cp.make_decision(
            criteria=criteria,
            output=output,
            agent_name="test_agent",
            payload=payload,
        )
        assert decision.passed is False
        assert decision.failure_category == FailureCategory.GUARDRAIL_BLOCKED.value

    def test_skip_input_guard_when_run_input_guard_is_false(self):
        cp = _cp()
        criteria = [EvalCriteriaItem(path="val", expected_type="str")]
        output = {"val": "ok"}
        payload = {"query": "", "val": "ok"}
        decision = cp.make_decision(
            criteria=criteria,
            output=output,
            agent_name="test_agent",
            payload=payload,
            run_input_guard=False,
        )
        assert decision.passed is True
        assert decision.action == "continue"


# ===========================================================================
# 7. guardrail stage validation (P1 #2 fix)
# ===========================================================================

class TestGuardrailStageValidation:
    def test_invalid_stage_raises_value_error(self):
        cp = _cp()
        with pytest.raises(ValueError, match="Invalid guardrail stage"):
            cp._run_guardrails(
                stage="pre_execution",
                agent_name="test_agent",
                payload={"query": "hello"},
            )

    def test_valid_input_stage_runs_guardrails(self):
        cp = _cp()
        decision = cp._run_guardrails(
            stage="input",
            agent_name="test_agent",
            payload={"query": "valid query"},
        )
        assert decision.passed is True

    def test_valid_output_stage_runs_guardrails(self):
        cp = _cp()
        decision = cp._run_guardrails(
            stage="output",
            agent_name="test_agent",
            payload={"text": "clean output"},
        )
        assert decision.passed is True

# ===========================================================================
# 8. make_decision guards output not input payload (Phase 7A Fix 1)
# ===========================================================================

class TestMakeDecisionOutputGuard:
    def test_blocks_sensitive_output_even_when_input_payload_is_clean(self):
        """Output guard checks actual output, not the input payload."""
        cp = _cp()
        criteria = [EvalCriteriaItem(path="val", expected_type="str")]
        output = {"val": "ok", "text": "here is an api_key secret in output"}
        payload = {"query": "clean query", "val": "ok"}
        decision = cp.make_decision(
            criteria=criteria,
            output=output,
            agent_name="test_agent",
            payload=payload,
        )
        assert decision.passed is False
        assert decision.failure_category == FailureCategory.GUARDRAIL_BLOCKED.value
        assert decision.stage == "output"

    def test_allows_clean_input_and_clean_output(self):
        """Both input and output are clean — pass through."""
        cp = _cp()
        criteria = [EvalCriteriaItem(path="val", expected_type="str")]
        output = {"val": "clean result"}
        payload = {"query": "clean query", "val": "ok"}
        decision = cp.make_decision(
            criteria=criteria,
            output=output,
            agent_name="test_agent",
            payload=payload,
        )
        assert decision.passed is True
        assert decision.action == "continue"

