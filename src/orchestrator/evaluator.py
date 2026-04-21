"""Evaluator with L1 structural checks and optional L2 semantic checks."""

from typing import Any

from .models import EvalCriteriaItem, EvalResult


class Evaluator:
    """Evaluate agent output against declared criteria."""

    def __init__(self, enable_l2: bool = True) -> None:
        self.enable_l2 = enable_l2
        self._l2_evaluator = None
        self._default_l2_criteria: dict[str, list[Any]] = {}

        if enable_l2:
            from .evaluator_l2 import (
                EvaluatorL2,
                make_planner_l2_criteria,
                make_summarizer_l2_criteria,
                make_supervisor_l2_criteria,
            )

            self._l2_evaluator = EvaluatorL2()
            self._default_l2_criteria = {
                "planner": make_planner_l2_criteria(),
                "summarizer": make_summarizer_l2_criteria(),
                "supervisor": make_supervisor_l2_criteria(),
            }

    def evaluate(
        self,
        criteria: list[EvalCriteriaItem],
        output: dict[str, Any],
        context: dict[str, Any] | None = None,
        l2_criteria: list[Any] | None = None,
        agent_name: str | None = None,
    ) -> EvalResult:
        for criterion in criteria:
            result = self._evaluate_l1_criterion(output=output, criterion=criterion)
            if result is not None:
                return result

        resolved_l2_criteria = l2_criteria
        if resolved_l2_criteria is None and agent_name is not None:
            resolved_l2_criteria = self._default_l2_criteria.get(agent_name, [])

        if self.enable_l2 and self._l2_evaluator and resolved_l2_criteria:
            l2_output = self._resolve_l2_output(agent_name=agent_name, output=output)
            return self._l2_evaluator.evaluate(
                criteria=resolved_l2_criteria,
                output=l2_output,
                context=context or {},
            )

        return EvalResult(passed=True)

    def _resolve_l2_output(
        self,
        *,
        agent_name: str | None,
        output: dict[str, Any],
    ) -> dict[str, Any]:
        l2_root_by_agent = {
            "planner": "plan",
            "summarizer": "summary",
            "supervisor": "supervisor_report",
        }
        if agent_name is None:
            return output
        root_field = l2_root_by_agent.get(agent_name)
        if not root_field:
            return output
        candidate = output.get(root_field)
        if isinstance(candidate, dict):
            return candidate
        return output

    def _evaluate_l1_criterion(
        self,
        *,
        output: dict[str, Any],
        criterion: EvalCriteriaItem,
    ) -> EvalResult | None:
        value, found = self._resolve_path(output, criterion.path)
        if not found:
            return self._fail_result(criterion)

        if not self._matches_expected_type(value=value, expected_type=criterion.expected_type):
            return self._fail_result(criterion)

        if isinstance(value, list):
            if criterion.min_items is not None and len(value) < criterion.min_items:
                return self._fail_result(criterion)
            if criterion.max_items is not None and len(value) > criterion.max_items:
                return self._fail_result(criterion)

        if criterion.allowed_values is not None and value not in criterion.allowed_values:
            return self._fail_result(criterion)

        return None

    def _resolve_path(self, payload: dict[str, Any], path: str) -> tuple[Any, bool]:
        current: Any = payload
        for segment in path.split("."):
            if not isinstance(current, dict) or segment not in current:
                return None, False
            current = current[segment]
        return current, True

    def _matches_expected_type(self, *, value: Any, expected_type: str) -> bool:
        if expected_type == "dict":
            return isinstance(value, dict)
        if expected_type == "list":
            return isinstance(value, list)
        if expected_type == "str":
            return isinstance(value, str)
        if expected_type == "non_empty_str":
            return isinstance(value, str) and bool(value.strip())
        return True

    def _fail_result(self, criterion: EvalCriteriaItem) -> EvalResult:
        return EvalResult(
            passed=False,
            action=criterion.action,
            reason=criterion.reason or f"evaluation failed at {criterion.path}",
        )
