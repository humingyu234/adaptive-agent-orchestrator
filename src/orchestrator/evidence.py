"""Evidence builder — maps runtime data into EvidencePack.

Only records what the runtime actually captures. Never invents evidence.
"""

from __future__ import annotations

from typing import Any

from .control_models import EvidencePack


def build_evidence_pack(
    *,
    task_id: str,
    step_name: str,
    status: str,
    duration_ms: int = 0,
    timestamp: str = "",
    evaluation: dict[str, Any] | None = None,
    failure_reason: str = "",
    output_summary: str = "",
    report_path: str = "",
    files_changed: list[str] | None = None,
    commands_run: list[str] | None = None,
    test_results: dict[str, Any] | None = None,
    notes: str = "",
) -> EvidencePack:
    """Build an EvidencePack from what the runtime actually recorded.

    Args:
        task_id: Workflow task identifier.
        step_name: Agent name or step label.
        status: Step status (success, error, guardrail_blocked, etc.).
        duration_ms: Wall-clock duration of the step in milliseconds.
        timestamp: ISO-8601 timestamp when the step completed.
        evaluation: Serialized ControlDecision or EvalResult, when available.
        failure_reason: Error message or failure description.
        output_summary: Human-readable summary of agent output.
        report_path: Path to the convergence report (set per-task, not per-step).
        files_changed: Files touched (only when the runtime captures them).
        commands_run: Commands executed (only when the runtime captures them).
        test_results: Test output mapped by test name (only when captured).
        notes: Free-text annotations.

    Returns:
        EvidencePack with every field explicitly populated or defaulted.
    """
    return EvidencePack(
        task_id=task_id,
        step_name=step_name,
        status=status,
        duration_ms=duration_ms,
        timestamp=timestamp,
        evaluation=evaluation,
        failure_reason=failure_reason,
        output_summary=output_summary,
        report_path=report_path,
        files_changed=files_changed or [],
        commands_run=commands_run or [],
        test_results=test_results or {},
        notes=notes,
    )


def build_evidence_pack_from_log_record(
    *,
    log_record: dict[str, Any],
    report_path: str = "",
) -> EvidencePack:
    """Build an EvidencePack from a scheduler log record.

    This is the primary integration point for Phase 4: the scheduler's
    _append_execution_log already captures task_id, agent, step, status,
    duration_ms, timestamp, and evaluation.  We map those fields directly
    and leave artifacts (files_changed, commands_run, etc.) empty because
    the current runtime does not capture them.
    """
    raw_summary = str(log_record.get("output_summary", ""))
    return EvidencePack(
        task_id=str(log_record.get("task_id", "")),
        step_name=str(log_record.get("agent", "")),
        status=str(log_record.get("status", "")),
        duration_ms=int(log_record.get("duration_ms", 0) or 0),
        timestamp=str(log_record.get("timestamp", "")),
        evaluation=log_record.get("evaluation"),
        failure_reason=str(log_record.get("error", "")),
        output_summary=raw_summary[:500],
        report_path=report_path,
        files_changed=[],
        commands_run=[],
        test_results={},
        diff_summary="",
        notes="",
    )


def evidence_packs_from_logs(
    *,
    log_records: list[dict[str, Any]],
    report_path: str = "",
) -> list[EvidencePack]:
    """Convert every log record into an EvidencePack."""
    return [
        build_evidence_pack_from_log_record(
            log_record=record,
            report_path=report_path,
        )
        for record in log_records
    ]
