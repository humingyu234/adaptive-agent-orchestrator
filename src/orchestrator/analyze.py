"""Utilities for inspecting historical orchestrator runs."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any] | None:
    """Safely load a JSON file."""
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def _format_datetime(dt_str: str | None) -> str:
    """Format an ISO timestamp for CLI display."""
    if not dt_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return dt_str


def _truncate(text: str, max_len: int = 50) -> str:
    """Truncate text for compact CLI table output."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


class RunAnalyzer:
    """Analyze runtime reports, failures, memory and agent health."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.reports_dir = project_root / "outputs" / "reports"
        self.memory_index_path = project_root / "outputs" / "memory" / "index.json"

    def list_recent_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        """List recent runs."""
        runs: list[dict[str, Any]] = []
        if not self.reports_dir.exists():
            return runs

        report_files = sorted(
            self.reports_dir.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:limit]

        for report_file in report_files:
            report = _load_json(report_file)
            if not report:
                continue
            runs.append(
                {
                    "task_id": report.get("task_id", "unknown"),
                    "workflow": report.get("workflow_name", "unknown"),
                    "query": _truncate(report.get("query", ""), 40),
                    "status": report.get("status", "unknown"),
                    "created_at": _format_datetime(report.get("timeline", {}).get("created_at")),
                    "steps": report.get("timeline", {}).get("steps_executed", 0),
                    "final_node": report.get("final_node", "unknown"),
                }
            )

        return runs

    def get_run_detail(self, task_id: str) -> dict[str, Any] | None:
        """Get one run detail by task id."""
        return _load_json(self.reports_dir / f"{task_id}.json")

    def get_failure_statistics(self, limit: int = 50) -> dict[str, Any]:
        """Summarize failure distribution."""
        stats: dict[str, Any] = {
            "total_runs": 0,
            "failed_runs": 0,
            "failure_categories": {},
            "failure_severities": {},
            "failures_by_agent": {},
            "recent_failures": [],
        }

        if not self.reports_dir.exists():
            return stats

        report_files = sorted(
            self.reports_dir.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:limit]

        for report_file in report_files:
            report = _load_json(report_file)
            if not report:
                continue

            stats["total_runs"] += 1
            failure_summary = report.get("failure_summary", {})
            if not failure_summary.get("has_failure"):
                continue

            stats["failed_runs"] += 1
            category = failure_summary.get("category") or "unknown"
            severity = failure_summary.get("severity") or "unknown"
            agent_name = failure_summary.get("agent_name") or "unknown"

            stats["failure_categories"][category] = stats["failure_categories"].get(category, 0) + 1
            stats["failure_severities"][severity] = stats["failure_severities"].get(severity, 0) + 1
            stats["failures_by_agent"][agent_name] = stats["failures_by_agent"].get(agent_name, 0) + 1
            stats["recent_failures"].append(
                {
                    "task_id": report.get("task_id", "unknown"),
                    "category": category,
                    "severity": severity,
                    "agent": agent_name,
                    "reason": _truncate(failure_summary.get("reason", ""), 60),
                }
            )

        return stats

    def get_agent_performance(self, limit: int = 50) -> dict[str, Any]:
        """Summarize agent performance from reports."""
        stats: dict[str, Any] = {
            "agents": {},
            "total_evaluations": 0,
            "total_failed_evaluations": 0,
        }

        if not self.reports_dir.exists():
            return stats

        report_files = sorted(
            self.reports_dir.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:limit]

        for report_file in report_files:
            report = _load_json(report_file)
            if not report:
                continue

            flow = report.get("flow_summary", {})
            agents_seen = flow.get("agents_seen", [])
            for agent_name in agents_seen:
                stats["agents"].setdefault(agent_name, {"runs": 0, "tools_used": set()})
                stats["agents"][agent_name]["runs"] += 1

            declared_tools = flow.get("declared_tools_by_agent", {})
            for agent_name, tools in declared_tools.items():
                if agent_name in stats["agents"]:
                    stats["agents"][agent_name]["tools_used"].update(tools)

            quality = report.get("quality_summary", {})
            stats["total_evaluations"] += quality.get("evaluation_events", 0)
            stats["total_failed_evaluations"] += quality.get("failed_evaluations", 0)

        for agent_data in stats["agents"].values():
            agent_data["tools_used"] = list(agent_data["tools_used"])

        return stats

    def get_memory_summary(self) -> dict[str, Any]:
        """Summarize memory index contents."""
        summary: dict[str, Any] = {
            "total_memories": 0,
            "by_plan_type": {},
            "recent_memories": [],
        }

        index = _load_json(self.memory_index_path)
        if not index or not isinstance(index, list):
            return summary

        summary["total_memories"] = len(index)

        for entry in index:
            plan_type = entry.get("plan_type") or "unknown"
            summary["by_plan_type"][plan_type] = summary["by_plan_type"].get(plan_type, 0) + 1

        summary["recent_memories"] = [
            {
                "task_id": entry.get("task_id", "unknown"),
                "query": _truncate(entry.get("query", ""), 40),
                "plan_type": entry.get("plan_type") or "unknown",
                "captured_at": _format_datetime(entry.get("captured_at")),
            }
            for entry in index[:10]
        ]
        return summary

    def get_agent_health(self, agent_name: str, days: int = 7) -> dict[str, Any]:
        """Get health metrics for one agent."""
        health: dict[str, Any] = {
            "agent": agent_name,
            "period_days": days,
            "total_runs": 0,
            "success_runs": 0,
            "failed_runs": 0,
            "success_rate": 0.0,
            "health_score": 0,
            "health_level": "unknown",
            "recent_failures": [],
        }

        if not self.reports_dir.exists():
            return health

        cutoff = datetime.now() - timedelta(days=days)
        report_files = sorted(
            self.reports_dir.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

        for report_file in report_files:
            report = _load_json(report_file)
            if not report:
                continue

            created_at_str = report.get("timeline", {}).get("created_at", "")
            try:
                created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                if created_at.tzinfo is not None:
                    cutoff_aware = cutoff.replace(tzinfo=timezone.utc)
                    if created_at < cutoff_aware:
                        continue
                elif created_at < cutoff:
                    continue
            except ValueError:
                continue

            flow = report.get("flow_summary", {})
            agents_seen = flow.get("agents_seen", [])
            if agent_name not in agents_seen:
                continue

            health["total_runs"] += 1

            failure_summary = report.get("failure_summary", {})
            if failure_summary.get("has_failure"):
                failed_agent = failure_summary.get("agent_name")
                if failed_agent == agent_name:
                    health["failed_runs"] += 1
                    health["recent_failures"].append(
                        {
                            "task_id": report.get("task_id", "unknown"),
                            "reason": _truncate(failure_summary.get("reason", ""), 60),
                            "category": failure_summary.get("category", "unknown"),
                            "timestamp": created_at_str,
                        }
                    )
                else:
                    health["success_runs"] += 1
            else:
                health["success_runs"] += 1

        if health["total_runs"] > 0:
            health["success_rate"] = health["success_runs"] / health["total_runs"]
            health["health_score"] = int(health["success_rate"] * 100)
            score = health["health_score"]
            if score >= 90:
                health["health_level"] = "excellent"
            elif score >= 80:
                health["health_level"] = "good"
            elif score >= 70:
                health["health_level"] = "fair"
            elif score >= 60:
                health["health_level"] = "poor"
            else:
                health["health_level"] = "critical"

        health["recent_failures"] = health["recent_failures"][:10]
        return health

    def get_all_agents_health(self, days: int = 7) -> dict[str, dict[str, Any]]:
        """Get health reports for all registered agents."""
        from .registry import REGISTRY

        return {agent_name: self.get_agent_health(agent_name, days) for agent_name in REGISTRY.keys()}

    def get_agent_failures(self, agent_name: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent failure cases for one agent."""
        failures: list[dict[str, Any]] = []
        if not self.reports_dir.exists():
            return failures

        report_files = sorted(
            self.reports_dir.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

        for report_file in report_files:
            if len(failures) >= limit:
                break

            report = _load_json(report_file)
            if not report:
                continue

            failure_summary = report.get("failure_summary", {})
            if not failure_summary.get("has_failure"):
                continue
            if failure_summary.get("agent_name") != agent_name:
                continue

            failures.append(
                {
                    "task_id": report.get("task_id", "unknown"),
                    "query": _truncate(report.get("query", ""), 50),
                    "reason": failure_summary.get("reason", ""),
                    "category": failure_summary.get("category", "unknown"),
                    "severity": failure_summary.get("severity", "unknown"),
                    "timestamp": report.get("timeline", {}).get("created_at", ""),
                    "report_path": str(report_file),
                }
            )

        return failures


def format_table(rows: list[list[str]], headers: list[str]) -> str:
    """Render rows as a simple CLI table."""
    if not rows:
        return "No data."

    col_widths = [len(header) for header in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            if idx < len(col_widths):
                col_widths[idx] = max(col_widths[idx], len(str(cell)))

    lines: list[str] = []
    header_line = " | ".join(header.ljust(col_widths[idx]) for idx, header in enumerate(headers))
    lines.append(header_line)
    lines.append("-" * len(header_line))

    for row in rows:
        line = " | ".join(
            str(cell).ljust(col_widths[idx]) if idx < len(col_widths) else str(cell)
            for idx, cell in enumerate(row)
        )
        lines.append(line)

    return "\n".join(lines)
