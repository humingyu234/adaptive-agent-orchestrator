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
from .policy import Policy
from .recovery import RecoveryDecision, RecoveryPlaybook, build_default_playbook

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
        policy: Policy | None = None,
        recovery_playbook: RecoveryPlaybook | None = None,
    ) -> None:
        self._evaluator = evaluator or Evaluator()
        self._guardrail = guardrail_manager or build_default_guardrail_manager()
        self._policy: Policy | None = policy
        self._playbook = recovery_playbook or build_default_playbook()

    def set_policy(self, policy: Policy) -> None:
        """Set the active policy for runtime enforcement."""
        self._policy = policy

    def set_playbook(self, playbook: RecoveryPlaybook) -> None:
        """Set the active recovery playbook."""
        self._playbook = playbook

    def _get_policy(self) -> Policy:
        """Return the active policy or a permissive default."""
        return self._policy or Policy.defaults()

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
    # policy enforcement — runtime gates driven by declarative Policy
    # ------------------------------------------------------------------

    def check_policy_for_reviewer_result(
        self,
        *,
        worker_name: str = "",
        worker_role: str = "",
        files_changed: list[str] | None = None,
    ) -> ControlDecision:
        """Reviewer workers must not write files."""
        policy = self._get_policy()
        if policy.mode == "off":
            return ControlDecision(passed=True, action="continue")

        is_reviewer = "reviewer" in worker_role.lower() or "reviewer" in worker_name.lower()
        if not is_reviewer:
            return ControlDecision(passed=True, action="continue")

        files = files_changed or []
        if not files:
            return ControlDecision(passed=True, action="continue")

        decision = ControlDecision(
            passed=False,
            action="needs_human_review",
            reason=f"Reviewer worker '{worker_name}' attempted to modify files: {files}",
            failure_category="policy_error",
            failure_origin="policy",
            recovery_hint="needs_human_review",
        )
        if policy.mode == "log":
            decision.passed = True
            decision.action = "continue"
        return decision

    def check_policy_for_file_changes(
        self, *, files_changed: list[str] | None = None
    ) -> ControlDecision:
        """Check whether any changed files are protected by policy."""
        policy = self._get_policy()
        if policy.mode == "off":
            return ControlDecision(passed=True, action="continue")

        files = files_changed or []
        protected = [f for f in files if policy.is_file_protected(f)]
        if not protected:
            return ControlDecision(passed=True, action="continue")

        if not policy.requires_human_review_for_file(protected[0]):
            return ControlDecision(passed=True, action="continue")

        decision = ControlDecision(
            passed=False,
            action="needs_human_review",
            reason=f"Protected files changed: {protected}",
            failure_category="policy_error",
            failure_origin="policy",
            recovery_hint="needs_human_review",
        )
        if policy.mode == "log":
            decision.passed = True
            decision.action = "continue"
        return decision

    def check_policy_for_tool_use(self, *, tool_name: str) -> ControlDecision:
        """Check whether a high-risk tool requires human review."""
        policy = self._get_policy()
        if policy.mode == "off":
            return ControlDecision(passed=True, action="continue")

        if not policy.requires_human_review_for_tool(tool_name):
            return ControlDecision(passed=True, action="continue")

        decision = ControlDecision(
            passed=False,
            action="needs_human_review",
            reason=f"High-risk tool '{tool_name}' requires human review",
            failure_category="policy_error",
            failure_origin="policy",
            recovery_hint="needs_human_review",
        )
        if policy.mode == "log":
            decision.passed = True
            decision.action = "continue"
        return decision

    def check_policy_for_required_checks(
        self,
        *,
        observed_check_results: dict[str, bool] | None = None,
    ) -> ControlDecision:
        """Block success when required checks have failed."""
        policy = self._get_policy()
        if policy.mode == "off":
            return ControlDecision(passed=True, action="continue")

        required = policy.get_required_checks()
        if not required:
            return ControlDecision(passed=True, action="continue")

        results = observed_check_results or {}
        failed = [c for c in required if not results.get(c, False)]

        if not failed:
            return ControlDecision(passed=True, action="continue")

        return ControlDecision(
            passed=False,
            action="fail",
            reason=f"Required checks failed: {failed}",
            failure_category="policy_error",
            failure_origin="policy",
            recovery_hint="needs_human_review",
        )

    def check_policy_for_required_evidence(
        self,
        *,
        required_evidence_keys: set[str] | None = None,
        observed_evidence_keys: set[str] | None = None,
    ) -> ControlDecision:
        """Block completion when required evidence is missing."""
        policy = self._get_policy()
        if policy.mode == "off":
            return ControlDecision(passed=True, action="continue")

        required = required_evidence_keys or set()
        if not required:
            return ControlDecision(passed=True, action="continue")

        observed = observed_evidence_keys or set()
        missing = required - observed

        if not missing:
            return ControlDecision(passed=True, action="continue")

        return ControlDecision(
            passed=False,
            action="needs_human_review",
            reason=f"Required evidence missing: {sorted(missing)}",
            failure_category="evidence_error",
            failure_origin="policy",
            recovery_hint="request_evidence",
            evidence_required=True,
        )

    # ------------------------------------------------------------------
    # recovery — bounded recovery decisions
    # ------------------------------------------------------------------

    def decide_recovery(
        self,
        failure_record: FailureRecord,
        *,
        attempt_count: int = 0,
        run_mode: str = "controlled",
        task_id: str = "",
        step_name: str = "",
    ) -> RecoveryDecision:
        """Produce a bounded recovery decision from a FailureRecord.

        Runner-agnostic entry point.  The playbook owns the matrix;
        this method just routes.
        """
        return self._playbook.decide(
            failure_record,
            attempt_count=attempt_count,
            run_mode=run_mode,
            task_id=task_id,
            step_name=step_name,
        )

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
