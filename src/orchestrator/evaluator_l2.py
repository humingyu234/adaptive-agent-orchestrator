"""L2 evaluator for lightweight semantic quality checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import EvalResult


@dataclass(frozen=True)
class L2Criterion:
    dimension: str
    check_type: str
    params: dict[str, Any]
    weight: float = 1.0
    action_on_fail: str = "warn"
    reason: str = ""


@dataclass
class L2Score:
    dimension: str
    score: float
    passed: bool
    details: dict[str, Any]


class EvaluatorL2:
    def __init__(self, pass_threshold: float = 0.6) -> None:
        self.pass_threshold = pass_threshold
        self._check_handlers = {
            "min_length": self._check_min_length,
            "min_items": self._check_min_items,
            "has_keywords": self._check_has_keywords,
            "field_match": self._check_field_match,
            "not_empty": self._check_not_empty,
            "score_threshold": self._check_score_threshold,
            "coverage": self._check_coverage,
        }

    def evaluate(
        self,
        criteria: list[L2Criterion],
        output: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> EvalResult:
        if not criteria:
            return EvalResult(passed=True, level_triggered="L2")

        scores = [self._evaluate_criterion(c, output, context or {}) for c in criteria]
        total_weight = sum(c.weight for c in criteria)
        weighted_score = (
            sum(score.score * criterion.weight for score, criterion in zip(scores, criteria)) / total_weight
            if total_weight > 0
            else 0.0
        )
        passed = weighted_score >= self.pass_threshold

        failed_pairs = [
            (score, criterion)
            for score, criterion in zip(scores, criteria)
            if not score.passed
        ]
        action = "continue"
        reason = ""
        if failed_pairs:
            failed_score, failed_criterion = failed_pairs[0]
            action = failed_criterion.action_on_fail
            reason = failed_criterion.reason or (
                f"L2 check failed: {failed_score.dimension} ({failed_score.score:.2f})"
            )

        if not passed:
            if action in {"warn", "continue"}:
                action = "retry"
            if not reason:
                reason = f"L2 weighted score below threshold: {weighted_score:.2f} < {self.pass_threshold:.2f}"
        elif action == "warn":
            action = "continue"

        return EvalResult(
            passed=passed,
            action=action,
            reason=reason,
            level_triggered="L2",
        )

    def _evaluate_criterion(
        self,
        criterion: L2Criterion,
        output: dict[str, Any],
        context: dict[str, Any],
    ) -> L2Score:
        handler = self._check_handlers.get(criterion.check_type)
        if handler is None:
            return L2Score(
                dimension=criterion.dimension,
                score=0.0,
                passed=False,
                details={"error": f"Unknown check type: {criterion.check_type}"},
            )
        try:
            score, passed, details = handler(criterion.params, output, context)
            return L2Score(criterion.dimension, score, passed, details)
        except Exception as exc:  # pragma: no cover - defensive path
            return L2Score(
                dimension=criterion.dimension,
                score=0.0,
                passed=False,
                details={"error": str(exc)},
            )

    def _check_min_length(self, params, output, context):
        path = params.get("path", "")
        min_length = params.get("min_length", 0)
        value, found = self._resolve_path(output, path)
        if not found:
            return 0.0, False, {"error": f"Path not found: {path}"}
        text = str(value) if value is not None else ""
        actual_length = len(text)
        score = min(1.0, actual_length / min_length) if min_length > 0 else 1.0
        return score, actual_length >= min_length, {"actual_length": actual_length, "min_length": min_length}

    def _check_min_items(self, params, output, context):
        path = params.get("path", "")
        min_items = params.get("min_items", 0)
        value, found = self._resolve_path(output, path)
        if not found:
            return 0.0, False, {"error": f"Path not found: {path}"}
        if not isinstance(value, list):
            return 0.0, False, {"error": f"Path is not a list: {path}"}
        actual_count = len(value)
        score = min(1.0, actual_count / min_items) if min_items > 0 else 1.0
        return score, actual_count >= min_items, {"actual_count": actual_count, "min_items": min_items}

    def _check_has_keywords(self, params, output, context):
        path = params.get("path", "")
        keywords = params.get("keywords", [])
        min_match = params.get("min_match", 1)
        value, found = self._resolve_path(output, path)
        if not found:
            return 0.0, False, {"error": f"Path not found: {path}"}
        text = str(value).lower() if value is not None else ""
        matched = [kw for kw in keywords if kw.lower() in text]
        score = len(matched) / len(keywords) if keywords else 1.0
        return score, len(matched) >= min_match, {"matched_keywords": matched, "total_keywords": len(keywords)}

    def _check_field_match(self, params, output, context):
        output_path = params.get("output_path", "")
        context_path = params.get("context_path", "")
        output_value, output_found = self._resolve_path(output, output_path)
        context_value, context_found = self._resolve_path(context, context_path)
        if not output_found or not context_found:
            return 0.0, False, {"error": "Path not found"}
        passed = output_value == context_value
        return (1.0 if passed else 0.0), passed, {"output_value": output_value, "context_value": context_value}

    def _check_not_empty(self, params, output, context):
        path = params.get("path", "")
        value, found = self._resolve_path(output, path)
        if not found:
            return 0.0, False, {"error": f"Path not found: {path}"}
        if value is None:
            passed = False
        elif isinstance(value, str):
            passed = bool(value.strip())
        elif isinstance(value, (list, dict)):
            passed = bool(value)
        else:
            passed = True
        return (1.0 if passed else 0.0), passed, {"value_type": type(value).__name__}

    def _check_score_threshold(self, params, output, context):
        path = params.get("path", "")
        threshold = params.get("threshold", 0.5)
        value, found = self._resolve_path(output, path)
        if not found:
            return 0.0, False, {"error": f"Path not found: {path}"}
        try:
            score_value = float(value)
        except (TypeError, ValueError):
            return 0.0, False, {"error": f"Cannot convert to float: {value}"}
        return score_value, score_value >= threshold, {"score_value": score_value, "threshold": threshold}

    def _check_coverage(self, params, output, context):
        output_path = params.get("output_path", "")
        context_path = params.get("context_path", "")
        key_field = params.get("key_field", "")
        output_value, output_found = self._resolve_path(output, output_path)
        context_value, context_found = self._resolve_path(context, context_path)
        if not output_found or not context_found:
            return 0.0, False, {"error": "Path not found"}
        if not isinstance(output_value, list) or not isinstance(context_value, list):
            return 0.0, False, {"error": "Both paths must be lists"}
        covered_keys = {str(item[key_field]) for item in output_value if isinstance(item, dict) and key_field in item}
        context_keys = {str(value) for value in context_value}
        coverage = 1.0 if not context_keys else len(covered_keys & context_keys) / len(context_keys)
        threshold = params.get("threshold", 0.5)
        return coverage, coverage >= threshold, {"covered": len(covered_keys & context_keys), "total": len(context_keys), "coverage": coverage}

    def _resolve_path(self, payload: dict[str, Any], path: str) -> tuple[Any, bool]:
        if not path:
            return payload, True
        current: Any = payload
        for segment in path.split("."):
            if isinstance(current, dict) and segment in current:
                current = current[segment]
            else:
                return None, False
        return current, True


def make_planner_l2_criteria() -> list[L2Criterion]:
    return [
        L2Criterion(
            dimension="completeness",
            check_type="min_items",
            params={"path": "sub_questions", "min_items": 2},
            weight=1.0,
            action_on_fail="retry",
            reason="Planner must produce at least 2 sub-questions",
        ),
        L2Criterion(
            dimension="quality",
            check_type="score_threshold",
            params={"path": "confidence", "threshold": 0.5},
            weight=0.5,
            action_on_fail="warn",
            reason="Planner confidence is too low",
        ),
    ]


def make_summarizer_l2_criteria() -> list[L2Criterion]:
    return [
        L2Criterion(
            dimension="completeness",
            check_type="min_length",
            params={"path": "conclusion", "min_length": 20},
            weight=1.0,
            action_on_fail="retry",
            reason="Summary conclusion is too short",
        ),
        L2Criterion(
            dimension="relevance",
            check_type="coverage",
            params={
                "output_path": "sections",
                "context_path": "plan.sub_questions",
                "key_field": "sub_question",
                "threshold": 0.5,
            },
            weight=0.8,
            action_on_fail="warn",
            reason="Summary coverage is too low",
        ),
    ]


def make_supervisor_l2_criteria() -> list[L2Criterion]:
    return [
        L2Criterion(
            dimension="completeness",
            check_type="not_empty",
            params={"path": "review_reason"},
            weight=1.0,
            action_on_fail="warn",
            reason="Supervisor review_reason should not be empty",
        ),
        L2Criterion(
            dimension="consistency",
            check_type="has_keywords",
            params={"path": "next_action", "keywords": ["accept", "revise"], "min_match": 1},
            weight=1.0,
            action_on_fail="fail",
            reason="next_action must be accept or revise",
        ),
    ]
