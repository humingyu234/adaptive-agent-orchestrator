"""Regression comparison helpers."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class RegressionSignal(str, Enum):
    NO_REGRESSION = "no_regression"
    MINOR_REGRESSION = "minor_regression"
    MAJOR_REGRESSION = "major_regression"
    IMPROVEMENT = "improvement"


@dataclass
class MetricDiff:
    name: str
    old_value: float | int
    new_value: float | int
    diff: float
    diff_percent: float
    is_regression: bool
    severity: str = "minor"


@dataclass
class RegressionReport:
    signal: RegressionSignal
    old_task_id: str
    new_task_id: str
    workflow_name: str | None = None
    metrics_diffs: list[MetricDiff] = field(default_factory=list)
    regression_reasons: list[str] = field(default_factory=list)
    improvement_reasons: list[str] = field(default_factory=list)
    summary: str = ""
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class RegressionCompare:
    MINOR_THRESHOLD = 0.1
    MAJOR_THRESHOLD = 0.3

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.reports_dir = project_root / "outputs" / "reports"
        self.states_dir = project_root / "outputs" / "states"

    def compare(self, old_task_id: str, new_task_id: str, workflow_name: str | None = None) -> RegressionReport:
        old_report = self._load_report(old_task_id)
        new_report = self._load_report(new_task_id)
        if old_report is None or new_report is None:
            return RegressionReport(
                signal=RegressionSignal.NO_REGRESSION,
                old_task_id=old_task_id,
                new_task_id=new_task_id,
                workflow_name=workflow_name,
                summary="??????????",
            )

        old_workflow = old_report.get("workflow_name")
        new_workflow = new_report.get("workflow_name")
        resolved_workflow = workflow_name or old_workflow or new_workflow
        if old_workflow != new_workflow:
            return RegressionReport(
                signal=RegressionSignal.NO_REGRESSION,
                old_task_id=old_task_id,
                new_task_id=new_task_id,
                workflow_name=resolved_workflow,
                summary=f"??? workflow ???{old_workflow} vs {new_workflow}",
            )

        metrics_diffs = self._compute_metrics_diffs(old_task_id, new_task_id, old_report, new_report)
        signal = self._determine_signal(metrics_diffs)
        regression_reasons = [
            f"{self._label_metric(diff.name)}: {diff.old_value} -> {diff.new_value} ({diff.diff_percent:+.1%})"
            for diff in metrics_diffs
            if diff.is_regression
        ]
        improvement_reasons = [
            f"{self._label_metric(diff.name)}: {diff.old_value} -> {diff.new_value} ({diff.diff_percent:+.1%})"
            for diff in metrics_diffs
            if not diff.is_regression and diff.diff != 0
        ]
        summary = self._generate_summary(signal, metrics_diffs)

        return RegressionReport(
            signal=signal,
            old_task_id=old_task_id,
            new_task_id=new_task_id,
            workflow_name=resolved_workflow,
            metrics_diffs=metrics_diffs,
            regression_reasons=regression_reasons,
            improvement_reasons=improvement_reasons,
            summary=summary,
        )

    def compare_recent(self, limit: int = 10, workflow_name: str | None = None) -> list[RegressionReport]:
        if not self.reports_dir.exists():
            return []

        report_files = sorted(
            self.reports_dir.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[: max(limit * 3, limit + 1)]
        reports: list[dict[str, Any]] = []
        for report_file in report_files:
            report = self._load_json(report_file)
            if not report:
                continue
            if workflow_name and report.get("workflow_name") != workflow_name:
                continue
            reports.append(report)

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for report in reports:
            grouped[report.get("workflow_name") or "unknown"].append(report)

        comparisons: list[RegressionReport] = []
        for group_name, group_reports in grouped.items():
            for index in range(len(group_reports) - 1):
                comparisons.append(
                    self.compare(
                        group_reports[index + 1]["task_id"],
                        group_reports[index]["task_id"],
                        workflow_name=group_name,
                    )
                )
                if len(comparisons) >= limit:
                    return comparisons
        return comparisons

    def find_regressions(
        self,
        threshold: RegressionSignal = RegressionSignal.MINOR_REGRESSION,
        workflow_name: str | None = None,
        limit: int = 20,
    ) -> list[RegressionReport]:
        recent_reports = self.compare_recent(limit, workflow_name)
        regressions: list[RegressionReport] = []
        for report in recent_reports:
            if not self._is_actionable(report):
                continue
            if report.signal == RegressionSignal.MAJOR_REGRESSION:
                regressions.append(report)
            elif threshold == RegressionSignal.MINOR_REGRESSION and report.signal == RegressionSignal.MINOR_REGRESSION:
                regressions.append(report)
        return regressions

    def _load_report(self, task_id: str) -> dict[str, Any] | None:
        return self._load_json(self.reports_dir / f"{task_id}.json")

    def _load_state(self, task_id: str) -> dict[str, Any] | None:
        return self._load_json(self.states_dir / f"{task_id}.json")

    def _load_json(self, path: Path) -> dict[str, Any] | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _compute_metrics_diffs(
        self,
        old_task_id: str,
        new_task_id: str,
        old_report: dict[str, Any],
        new_report: dict[str, Any],
    ) -> list[MetricDiff]:
        diffs: list[MetricDiff] = []
        old_steps = old_report.get("timeline", {}).get("steps_executed", 0)
        new_steps = new_report.get("timeline", {}).get("steps_executed", 0)
        diffs.append(self._create_diff("steps_executed", old_steps, new_steps, lower_is_better=True))

        old_failed_evals = old_report.get("quality_summary", {}).get("failed_evaluations", 0)
        new_failed_evals = new_report.get("quality_summary", {}).get("failed_evaluations", 0)
        diffs.append(self._create_diff("failed_evaluations", old_failed_evals, new_failed_evals, lower_is_better=True))

        old_retries = self._count_retries(old_report)
        new_retries = self._count_retries(new_report)
        diffs.append(self._create_diff("retry_count", old_retries, new_retries, lower_is_better=True))

        old_success = self._is_success_like(old_report)
        new_success = self._is_success_like(new_report)
        diffs.append(self._create_diff("success_rate", int(old_success), int(new_success), lower_is_better=False))

        old_confidence = self._extract_confidence(old_task_id)
        new_confidence = self._extract_confidence(new_task_id)
        if old_confidence is not None and new_confidence is not None:
            diffs.append(self._create_diff("confidence", old_confidence, new_confidence, lower_is_better=False))

        return diffs

    def _create_diff(self, name: str, old_value: float | int, new_value: float | int, lower_is_better: bool = True) -> MetricDiff:
        if old_value == 0:
            diff = new_value
            diff_percent = 1.0 if new_value > 0 else 0.0
        else:
            diff = new_value - old_value
            diff_percent = diff / old_value

        is_regression = new_value > old_value if lower_is_better else new_value < old_value
        severity = "major" if abs(diff_percent) >= self.MAJOR_THRESHOLD else "minor"
        return MetricDiff(name, old_value, new_value, diff, diff_percent, is_regression, severity)

    def _determine_signal(self, diffs: list[MetricDiff]) -> RegressionSignal:
        has_major_regression = any(diff.is_regression and diff.severity == "major" for diff in diffs)
        has_minor_regression = any(diff.is_regression and diff.severity == "minor" for diff in diffs)
        has_improvement = any(not diff.is_regression and diff.diff != 0 for diff in diffs)

        if has_major_regression:
            return RegressionSignal.MAJOR_REGRESSION
        if has_minor_regression and not has_improvement:
            return RegressionSignal.MINOR_REGRESSION
        if has_improvement and not has_minor_regression and not has_major_regression:
            return RegressionSignal.IMPROVEMENT
        return RegressionSignal.NO_REGRESSION

    def _generate_summary(self, signal: RegressionSignal, diffs: list[MetricDiff]) -> str:
        if signal == RegressionSignal.NO_REGRESSION:
            return "No meaningful regression detected"
        if signal == RegressionSignal.IMPROVEMENT:
            improvements = [self._label_metric(diff.name) for diff in diffs if not diff.is_regression and diff.diff != 0]
            return f"Improvement detected: {', '.join(improvements)}" if improvements else "Improvement detected"
        regressions = [
            self._label_metric(diff.name)
            for diff in diffs
            if diff.is_regression and (signal == RegressionSignal.MINOR_REGRESSION or diff.severity == "major")
        ]
        if signal == RegressionSignal.MINOR_REGRESSION:
            return f"Minor regression detected: {', '.join(regressions)}"
        return f"Major regression detected: {', '.join(regressions)}"

    def _count_retries(self, report: dict[str, Any]) -> int:
        counters = report.get("control_summary", {}).get("retry_counters", {})
        if not isinstance(counters, dict):
            return 0
        return sum(value for value in counters.values() if isinstance(value, int))

    def _extract_confidence(self, task_id: str) -> float | None:
        state = self._load_state(task_id)
        if not state:
            return None
        plan = state.get("data_pool", {}).get("intermediate", {}).get("plan", {})
        if isinstance(plan, dict):
            confidence = plan.get("confidence")
            if isinstance(confidence, (int, float)):
                return float(confidence)
        return None

    def _is_success_like(self, report: dict[str, Any]) -> bool:
        return report.get("status") in {"completed", "needs_human_review"}

    def _is_actionable(self, report: RegressionReport) -> bool:
        if report.signal not in {RegressionSignal.MINOR_REGRESSION, RegressionSignal.MAJOR_REGRESSION}:
            return False
        old_report = self._load_report(report.old_task_id)
        new_report = self._load_report(report.new_task_id)
        if not old_report or not new_report:
            return False
        ignored_categories = {"guardrail_blocked"}
        old_category = old_report.get("failure_summary", {}).get("category")
        new_category = new_report.get("failure_summary", {}).get("category")
        return old_category not in ignored_categories and new_category not in ignored_categories

    def _label_metric(self, metric_name: str) -> str:
        labels = {
            "steps_executed": "steps_executed",
            "failed_evaluations": "failed_evaluations",
            "retry_count": "retry_count",
            "success_rate": "success_rate",
            "confidence": "confidence",
        }
        return labels.get(metric_name, metric_name)


def format_regression_report(report: RegressionReport) -> str:
    lines = [
        "Regression Report",
        "=" * 40,
        f"Old task: {report.old_task_id}",
        f"New task: {report.new_task_id}",
        f"Workflow: {report.workflow_name or 'unknown'}",
        f"Signal: {report.signal.value}",
        "",
    ]

    if report.metrics_diffs:
        lines.append("Metrics:")
        for diff in report.metrics_diffs:
            arrow = "+" if diff.diff > 0 else "-" if diff.diff < 0 else "="
            status = "regression" if diff.is_regression else "improvement"
            lines.append(f"  {diff.name}: {diff.old_value} -> {diff.new_value} ({arrow} {diff.diff_percent:+.1%}) {status}")

    if report.regression_reasons:
        lines.append("")
        lines.append("Regression reasons:")
        for reason in report.regression_reasons:
            lines.append(f"  - {reason}")

    if report.improvement_reasons:
        lines.append("")
        lines.append("Improvement reasons:")
        for reason in report.improvement_reasons:
            lines.append(f"  - {reason}")

    lines.append("")
    lines.append(f"Summary: {report.summary}")
    return "\n".join(lines)
