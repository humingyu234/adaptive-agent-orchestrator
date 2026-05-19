"""Golden scenario data models — small, serializable, deterministic."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class GoldenScenario:
    """A single staged incident for AAO's control layer to catch.

    Each scenario describes a known worker behavior (good or bad) and the
    expected control decisions AAO should make in response.
    """

    id: str
    title: str
    purpose: str
    task_input: str = ""
    run_mode: str = "controlled"
    setup: dict[str, Any] = field(default_factory=dict)
    fake_worker_output: dict[str, Any] = field(default_factory=dict)
    fake_worker_name: str = "test_worker"
    fake_worker_role: str = "worker"
    expected_control_actions: list[str] = field(default_factory=list)
    expected_control_passed: list[bool] = field(default_factory=list)
    expected_failure_category: str | None = None
    expected_recovery_action: str | None = None
    expected_evidence_keys: list[str] = field(default_factory=list)
    must_not_happen: list[str] = field(default_factory=list)
    contract: str = ""


@dataclass
class GoldenScenarioResult:
    """Output of running one golden scenario through AAO's control layer.

    Includes all control decisions, failure/recovery records, and evidence
    so tests can assert on the full control path, not just final text.
    """

    scenario_id: str
    status: str = ""  # passed, failed, blocked, needs_human_review
    control_decisions: list[dict[str, Any]] = field(default_factory=list)
    failure_record: dict[str, Any] | None = None
    recovery_decision: dict[str, Any] | None = None
    evidence_items: list[dict[str, Any]] = field(default_factory=list)
    report_sections: list[str] = field(default_factory=list)
    plan_verification: dict[str, Any] | None = None
    assertions: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def make_worker_output(
    *,
    status: str = "completed",
    test_output: str = "",
    files_changed: list[str] | None = None,
    tools_called: list[str] | None = None,
    errors: list[str] | None = None,
    summary: str = "",
) -> dict[str, Any]:
    """Build a deterministic fake worker output dict."""
    return {
        "status": status,
        "test_output": test_output,
        "files_changed": files_changed or [],
        "tools_called": tools_called or [],
        "errors": errors or [],
        "summary": summary,
    }
