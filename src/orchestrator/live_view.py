"""Live run view — structured status and human-readable rendering.

Provides a lightweight, terminal-safe view of a task run that both Claude Code
and humans can read.  No web dashboard, no extra dependencies.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from .models import RunResult
from .state_center import StateCenter

# Terminal states — watch stops polling when any of these are seen.
_TERMINAL_STATES: frozenset[str] = frozenset({
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "guardrail_blocked",
    "human_rejected",
    "needs_human_review",
})


def is_terminal(status: str) -> bool:
    """Return True if *status* is a terminal (non-running) state."""
    return status in _TERMINAL_STATES


def build_live_view(
    state: StateCenter,
    result: RunResult | None = None,
    *,
    workflow_total: int | None = None,
    report_path: str | None = None,
    evidence_path: str | None = None,
) -> dict[str, Any]:
    """Build a structured live-view dictionary from runtime state.

    The returned dict includes every field the CLI / human reader needs to
    understand the current run status.  Missing optional data is represented as
    None or empty strings rather than crashing.

    *workflow_total*, when provided, is used as the total step count.
    Otherwise the total is derived from evaluation events (a best-effort
    fallback that may undercount).

    *report_path* and *evidence_path*, when provided, override paths derived
    from *result*.  Use these when reading a real report JSON that does not
    contain a serialised RunResult.
    """
    trace = state.execution_trace

    # ---- evaluation-derived fields -------------------------------------------
    eval_events = [e for e in trace if e.get("event") == "evaluation"]
    agents_seen: set[str] = set()
    for e in eval_events:
        agent = e.get("agent_name")
        if isinstance(agent, str) and agent:
            agents_seen.add(agent)

    steps_completed = sum(1 for e in eval_events if e.get("passed"))
    if workflow_total is not None:
        steps_total = workflow_total
    elif agents_seen:
        steps_total = len(agents_seen)
    else:
        steps_total = 0

    last_eval = eval_events[-1] if eval_events else None
    # current_step: prefer last failed/human_review/guardrail event for
    # failed/paused runs, otherwise fall back to last eval agent
    current_step: str | None = None
    if state.metadata.status in ("failed", "timed_out", "needs_human_review"):
        for e in reversed(trace):
            if e.get("event") in ("guardrail_violation", "evaluation", "failure_classified"):
                current_step = e.get("agent_name")
                if current_step:
                    break
        if not current_step:
            current_step = last_eval.get("agent_name") if last_eval else None
    else:
        current_step = last_eval.get("agent_name") if last_eval else None

    last_decision = last_eval.get("action") if last_eval else None
    last_decision_reason = last_eval.get("reason", "") if last_eval else ""

    # ---- current worker (last agent that produced output) --------------------
    current_worker: str | None = None
    for e in reversed(trace):
        if e.get("event") == "write" and e.get("agent_name") != "memory_manager":
            current_worker = e.get("agent_name")
            break

    # ---- evaluator decision --------------------------------------------------
    last_evaluator_decision: dict[str, Any] | None = None
    if last_eval:
        last_evaluator_decision = {
            "action": last_eval.get("action", ""),
            "reason": last_eval.get("reason", ""),
            "passed": last_eval.get("passed"),
        }

    # ---- guardrail decision --------------------------------------------------
    last_guardrail_decision: dict[str, Any] | None = None
    for e in reversed(trace):
        if e.get("event") == "guardrail_violation":
            last_guardrail_decision = {
                "guardrail_name": str(e.get("guardrail_name", "")),
                "stage": str(e.get("stage", "")),
                "reason": str(e.get("reason", "")),
            }
            break

    # ---- policy decision (policy_decision event, checkpoint_replan fallback) ---
    last_policy_decision: dict[str, Any] | None = None
    for e in reversed(trace):
        if e.get("event") == "policy_decision":
            last_policy_decision = {
                "type": str(e.get("decision_type", "")),
                "action": str(e.get("action", "")),
                "reason": str(e.get("reason", "")),
                "passed": e.get("passed"),
                "failure_category": str(e.get("failure_category", "")) or None,
                "recovery_hint": str(e.get("recovery_hint", "")) or None,
            }
            break
    if last_policy_decision is None:
        for e in reversed(trace):
            if e.get("event") == "checkpoint_replan":
                last_policy_decision = {
                    "target": str(e.get("target", "")),
                    "action": str(e.get("action", "")),
                    "reason": str(e.get("reason", "")),
                }
                break

    # ---- recovery decision ----------------------------------------------------
    last_recovery_decision: dict[str, Any] | None = None
    for e in reversed(trace):
        if e.get("event") == "recovery_decision":
            last_recovery_decision = {
                "action": str(e.get("action", "")),
                "reason": str(e.get("reason", "")),
                "failure_category": str(e.get("failure_category", "")),
                "failure_reason": str(e.get("failure_reason", "")),
                "attempt_count": e.get("attempt_count", 0),
                "max_attempts": e.get("max_attempts", 0),
                "terminal": e.get("terminal"),
                "runtime_supported": e.get("runtime_supported"),
                "next_step_hint": str(e.get("next_step_hint", "")) or None,
            }
            break

    # ---- failure-derived fields ----------------------------------------------
    last_failure: dict[str, str] | None = None
    last_failure_origin: str | None = None
    last_recovery_hint: str | None = None
    for e in reversed(trace):
        if e.get("event") == "failure_classified":
            last_failure = {
                "category": str(e.get("category", "")),
                "severity": str(e.get("severity", "")),
                "agent_name": str(e.get("agent_name", "")),
                "reason": str(e.get("reason", "")),
            }
            origin = e.get("origin")
            if origin:
                last_failure_origin = str(origin)
            recovery = e.get("recovery_hint")
            if recovery:
                last_recovery_hint = str(recovery)
            break

    # ---- human-review check --------------------------------------------------
    gate = state.data_pool.intermediate.get("human_review_gate")
    human_review_required = state.metadata.status == "needs_human_review" or (
        isinstance(gate, dict) and gate.get("decision") == "await_human"
    )
    human_review_state: str | None = None
    if human_review_required:
        human_review_state = "awaiting_human"
    elif state.metadata.status == "human_rejected":
        human_review_state = "rejected"
    else:
        human_review_state = "none"

    # ---- result-derived paths ------------------------------------------------
    # Keyword overrides take priority (used when reading real report JSON).
    # Fall back to result attributes when available (backward compat for tests).
    _report_path: str | None = report_path
    _evidence_path: str | None = evidence_path
    if _report_path is None and result is not None:
        _report_path = result.convergence_report_path or None
    if _evidence_path is None and result is not None:
        _evidence_path = result.evidence_path or None

    # ---- evidence status -----------------------------------------------------
    evidence_status = "available" if _evidence_path else "missing"

    # ---- progress string -----------------------------------------------------
    if steps_total > 0:
        if workflow_total is not None or is_terminal(state.metadata.status):
            progress = f"{steps_completed}/{steps_total}"
        else:
            # Non-terminal run without workflow_total: agent count may be
            # incomplete, so show unknown total to avoid fake progress.
            progress = f"{steps_completed}/?"
    else:
        progress = "0/0"

    # ---- elapsed time --------------------------------------------------------
    updated_at = getattr(state.metadata, "updated_at", "") or ""
    elapsed = _compute_elapsed(state.metadata.created_at, updated_at)

    return {
        "task_id": state.metadata.task_id,
        "status": state.metadata.status,
        "run_mode": getattr(state.metadata, "run_mode", "controlled") or "controlled",
        "query": state.data_pool.query,
        "current_step": current_step,
        "current_worker": current_worker,
        "progress": progress,
        "steps_total": steps_total,
        "steps_completed": steps_completed,
        "last_decision": last_decision,
        "last_decision_reason": last_decision_reason,
        "last_evaluator_decision": last_evaluator_decision,
        "last_guardrail_decision": last_guardrail_decision,
        "last_policy_decision": last_policy_decision,
        "last_recovery_decision": last_recovery_decision,
        "last_failure": last_failure,
        "last_failure_origin": last_failure_origin,
        "last_recovery_hint": last_recovery_hint,
        "evidence_status": evidence_status,
        "human_review_required": human_review_required,
        "human_review_state": human_review_state,
        "report_path": _report_path,
        "evidence_path": _evidence_path,
        "started_at": state.metadata.created_at,
        "updated_at": getattr(state.metadata, "updated_at", "") or "",
        "elapsed": elapsed,
    }


def render_live_view(view: dict[str, Any]) -> str:
    """Render a live-view dict as terminal-safe, human-readable text.

    Uses only ASCII characters so it renders correctly in any terminal.
    """
    lines: list[str] = []
    sep = "=" * 64

    lines.append(sep)
    lines.append(_fmt_line("Task", view.get("task_id", "")))
    lines.append(_fmt_line("Mode", view.get("run_mode", "")))
    lines.append(_fmt_line("Status", _status_label(view.get("status", ""))))
    lines.append(_fmt_line("Query", view.get("query", "")))
    lines.append(sep)

    # ---- progress ------------------------------------------------------------
    lines.append("Progress")
    lines.append(
        f"  Step:       {view.get('current_step') or '-'}"
    )
    lines.append(
        f"  Progress:   {view.get('progress', '-')}  "
        f"(completed={view.get('steps_completed', 0)}, total={view.get('steps_total', 0)})"
    )
    worker = view.get("current_worker")
    if worker:
        lines.append(f"  Worker:     {worker}")

    # ---- control decisions ---------------------------------------------------
    eval_dec = view.get("last_evaluator_decision")
    if eval_dec:
        passed = "PASS" if eval_dec.get("passed") else "FAIL"
        lines.append(
            f"  Evaluator:  {passed} action={eval_dec.get('action', '')}"
            + (f" ({eval_dec.get('reason', '')})" if eval_dec.get('reason') else "")
        )

    guard_dec = view.get("last_guardrail_decision")
    if guard_dec:
        lines.append(
            f"  Guardrail:  {guard_dec.get('guardrail_name', '')}"
            f" stage={guard_dec.get('stage', '')}"
            + (f" ({guard_dec.get('reason', '')})" if guard_dec.get('reason') else "")
        )

    policy_dec = view.get("last_policy_decision")
    if policy_dec:
        lines.append(
            f"  Policy:     {policy_dec.get('action', '')}"
            + (f" type={policy_dec.get('type', '')}" if policy_dec.get('type') else "")
            + (f" target={policy_dec.get('target', '')}" if policy_dec.get('target') else "")
            + (f" ({policy_dec.get('reason', '')})" if policy_dec.get('reason') else "")
        )

    recovery_dec = view.get("last_recovery_decision")
    if recovery_dec:
        lines.append(
            f"  Recovery:   {recovery_dec.get('action', '')}"
            f" attempt={recovery_dec.get('attempt_count', 0)}/{recovery_dec.get('max_attempts', 0)}"
            + (f" ({recovery_dec.get('reason', '')})" if recovery_dec.get('reason') else "")
        )
        if not recovery_dec.get("runtime_supported", True):
            lines.append(f"             !! runtime does not support this action")

    # ---- last decision (legacy / summary) ------------------------------------
    decision = view.get("last_decision")
    reason = view.get("last_decision_reason", "")
    if decision:
        lines.append(f"  Decision:   {decision}" + (f" ({reason})" if reason else ""))

    # ---- failure -------------------------------------------------------------
    failure = view.get("last_failure")
    if failure:
        lines.append("")
        lines.append("Last Failure")
        lines.append(f"  Origin:     {view.get('last_failure_origin') or '-'}")
        lines.append(f"  Category:   {failure.get('category', '-')}")
        lines.append(f"  Severity:   {failure.get('severity', '-')}")
        lines.append(f"  Agent:      {failure.get('agent_name', '-')}")
        lines.append(f"  Reason:     {failure.get('reason', '-')}")
        hint = view.get("last_recovery_hint")
        if hint:
            lines.append(f"  Recovery:   {hint}")

    # ---- evidence ------------------------------------------------------------
    lines.append("")
    lines.append(f"  Evidence:   {view.get('evidence_status', '-')}")

    # ---- human review --------------------------------------------------------
    hr_state = view.get("human_review_state", "none")
    if hr_state and hr_state != "none":
        lines.append(f"  Human Review: {hr_state}")
    if view.get("human_review_required"):
        lines.append("")
        lines.append("ACTION REQUIRED: Human review is waiting for your decision.")
        if view.get("task_id"):
            lines.append(f"  resume: python -m orchestrator resume --task-id {view['task_id']}")

    # ---- artifacts -----------------------------------------------------------
    lines.append("")
    lines.append("Artifacts")
    lines.append(f"  report:   {view.get('report_path') or '-'}")
    lines.append(f"  evidence: {view.get('evidence_path') or '-'}")

    # ---- timing --------------------------------------------------------------
    elapsed = view.get("elapsed", "")
    if elapsed:
        lines.append("")
        lines.append(f"  Started:  {view.get('started_at', '-')}")
        lines.append(f"  Updated:  {view.get('updated_at', '-')}")
        lines.append(f"  Elapsed:  {elapsed}")

    lines.append(sep)
    return "\n".join(lines)


def _fmt_line(label: str, value: str) -> str:
    return f"  {label}:{' ' * (12 - len(label))}{value}"


def _status_label(status: str) -> str:
    status = status or ""
    if status == "completed":
        return "OK completed"
    if status == "failed":
        return "!! FAILED"
    if status == "needs_human_review":
        return "?? WAIT (needs human review)"
    if status == "running":
        return "... running"
    if status == "timed_out":
        return "!! TIMED OUT"
    if status == "guardrail_blocked":
        return "!! BLOCKED (guardrail)"
    if status == "cancelled":
        return "!! CANCELLED"
    if status == "human_rejected":
        return "!! REJECTED (human)"
    return status


def _compute_elapsed(started_at: str, updated_at: str) -> str:
    """Compute a human-readable elapsed time string."""
    end = updated_at or datetime.now(timezone.utc).isoformat()
    try:
        t0 = datetime.fromisoformat(started_at)
        t1 = datetime.fromisoformat(end)
    except (ValueError, TypeError):
        return ""
    delta = t1 - t0
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return ""
    if total_seconds < 60:
        return f"{total_seconds}s"
    if total_seconds < 3600:
        m, s = divmod(total_seconds, 60)
        return f"{m}m {s}s"
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"
