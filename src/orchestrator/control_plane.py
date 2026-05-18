"""ControlPlane — runner-independent facade over evaluator, guardrails, and failure taxonomy.

All runner-agnostic control decisions flow through this single entry point.
"""

from __future__ import annotations

from typing import Any, Literal

from .control_models import ControlAction, ControlDecision, RecoveryHint
from .evaluator import Evaluator
from .failure_taxonomy import (
    DEFAULT_SEVERITY_MAP,
    RECOVERY_HINT_MAP,
    FailureCategory,
    FailureReason,
    FailureRecord,
    FailureSeverity,
    classify_failure,
    create_failure_record,
)
from .guardrails import GuardrailManager, GuardrailViolation, build_default_guardrail_manager
from .models import EvalCriteriaItem, EvalResult

# EvalResult.action uses "re_plan" (with underscore); ControlAction uses "replan"
_EVAL_ACTION_TO_CONTROL: dict[str, ControlAction] = {
    "continue": "continue",
    "retry": "retry",
    "re_plan": "replan",
    "fail": "fail",
}

_CONTROL_TO_RECOVERY: dict[ControlAction, RecoveryHint] = {
    "continue": "continue",
    "retry": "retry",
    "replan": "replan",
    "fail": "fail",
}

_LEVEL_TO_SEVERITY: dict[str, str] = {
    "L1": "low",
    "L2": "medium",
    "L3": "high",
}


class ControlPlane:
    """Runner-independent control entry point.

    Wraps Evaluator, GuardrailManager, and failure_taxonomy so that every
    runner (native scheduler, LangGraph, or future backends) gets identical
    control decisions.
    """

    def __init__(
        self,
        evaluator: Evaluator | None = None,
        guardrail_manager: GuardrailManager | None = None,
    ) -> None:
        self._evaluator = evaluator or Evaluator()
        self._guardrail = guardrail_manager or build_default_guardrail_manager()

    # ------------------------------------------------------------------
    # evaluate_output
    # ------------------------------------------------------------------

    def evaluate_output(
        self,
        criteria: list[EvalCriteriaItem],
        output: dict[str, Any],
        *,
        agent_name: str | None = None,
        context: dict[str, Any] | None = None,
        l2_criteria: list[Any] | None = None,
    ) -> ControlDecision:
        """Run L1 (and optionally L2) evaluation and return a ControlDecision."""
        result: EvalResult = self._evaluator.evaluate(
            criteria,
            output,
            context=context,
            l2_criteria=l2_criteria,
            agent_name=agent_name,
        )
        return self._eval_result_to_decision(result)

    # ------------------------------------------------------------------
    # guard_input / guard_output
    # ------------------------------------------------------------------

    def guard_input(
        self,
        *,
        agent_name: str,
        payload: dict[str, Any],
        guardrail_names: list[str] | None = None,
    ) -> ControlDecision:
        """Run input-stage guardrails against *payload*."""
        return self._run_guardrails(
            stage="input",
            agent_name=agent_name,
            payload=payload,
            guardrail_names=guardrail_names,
        )

    def guard_output(
        self,
        *,
        agent_name: str,
        payload: dict[str, Any],
        guardrail_names: list[str] | None = None,
    ) -> ControlDecision:
        """Run output-stage guardrails against *payload*."""
        return self._run_guardrails(
            stage="output",
            agent_name=agent_name,
            payload=payload,
            guardrail_names=guardrail_names,
        )

    # ------------------------------------------------------------------
    # classify_failure
    # ------------------------------------------------------------------

    def classify_failure(
        self,
        *,
        status: str,
        reason: str,
        agent_name: str | None = None,
        event_type: str | None = None,
        eval_action: str | None = None,
    ) -> FailureRecord:
        """Classify a failure into a structured FailureRecord.

        Uses infer_failure_category as a fallback path for unknown failures.
        Prefer create_failure_record() for failures whose category is already
        known at the point of failure.
        """
        return classify_failure(
            status=status,
            reason=reason,
            agent_name=agent_name,
            event_type=event_type,
            eval_action=eval_action,
        )

    # ------------------------------------------------------------------
    # create_failure_record — explicit category, no inference
    # ------------------------------------------------------------------

    def create_failure_record(
        self,
        *,
        category: FailureCategory,
        agent_name: str | None = None,
        reason: str = "",
        severity: FailureSeverity | None = None,
        context: dict[str, Any] | None = None,
    ) -> FailureRecord:
        """Create a FailureRecord with an explicit, caller-known category.

        This path does NOT call infer_failure_category.  Use it when the
        failure site already knows the right FailureCategory.
        """
        return create_failure_record(
            category=category,
            agent_name=agent_name,
            reason=reason,
            severity=severity,
            context=context,
        )

    # ------------------------------------------------------------------
    # make_decision — composite check (evaluate + guard)
    # ------------------------------------------------------------------

    def make_decision(
        self,
        *,
        criteria: list[EvalCriteriaItem],
        output: dict[str, Any],
        agent_name: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
        l2_criteria: list[Any] | None = None,
        run_input_guard: bool = True,
    ) -> ControlDecision:
        """Composite: input guard → evaluate → output guard.  First failure wins.

        Set *run_input_guard* to False only when the caller has already
        performed input guarding upstream.
        """
        if run_input_guard:
            input_decision = self.guard_input(agent_name=agent_name, payload=payload)
            if not input_decision.passed:
                return input_decision

        eval_decision = self.evaluate_output(
            criteria,
            output,
            agent_name=agent_name,
            context=context,
            l2_criteria=l2_criteria,
        )
        if not eval_decision.passed:
            return eval_decision

        guard_decision = self.guard_output(agent_name=agent_name, payload=output)
        if not guard_decision.passed:
            return guard_decision

        return ControlDecision(passed=True, action="continue")

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _eval_result_to_decision(self, result: EvalResult) -> ControlDecision:
        if result.passed:
            return ControlDecision(
                passed=True,
                action="continue",
                reason=result.reason,
            )
        action = _EVAL_ACTION_TO_CONTROL.get(result.action, "fail")
        return ControlDecision(
            passed=False,
            action=action,
            reason=result.reason,
            severity=_LEVEL_TO_SEVERITY.get(result.level_triggered, "medium"),
            failure_category=FailureCategory.TASK_QUALITY_ERROR.value,
            failure_origin="control_plane",
            recovery_hint=_CONTROL_TO_RECOVERY.get(action, "fail"),
        )

    def _run_guardrails(
        self,
        *,
        stage: Literal["input", "output"],
        agent_name: str,
        payload: dict[str, Any],
        guardrail_names: list[str] | None = None,
    ) -> ControlDecision:
        if stage not in ("input", "output"):
            raise ValueError(
                f"Invalid guardrail stage: {stage!r}. Must be 'input' or 'output'."
            )
        names = guardrail_names or self._guardrail.list_names()
        try:
            self._guardrail.run_many(
                names=names,
                stage=stage,  # type: ignore[arg-type]
                agent_name=agent_name,
                payload=payload,
            )
        except GuardrailViolation as violation:
            return self._violation_to_decision(violation)
        return ControlDecision(passed=True, action="continue")

    def _violation_to_decision(self, violation: GuardrailViolation) -> ControlDecision:
        sev_entry = DEFAULT_SEVERITY_MAP.get(
            violation.failure_category, FailureSeverity.MEDIUM
        )
        severity_str = sev_entry.value if isinstance(sev_entry, FailureSeverity) else str(sev_entry)
        return ControlDecision(
            passed=False,
            action="fail",
            reason=violation.message,
            severity=severity_str,  # type: ignore[arg-type]
            failure_category=violation.failure_category.value,
            failure_origin="control_plane",
            recovery_hint="fail",
            guardrail_name=violation.guardrail_name,
            stage=violation.stage,  # type: ignore[arg-type]
        )
