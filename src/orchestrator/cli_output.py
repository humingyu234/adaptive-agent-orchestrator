"""CLI output shaping for demo-friendly runtime summaries."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import RunResult
from .state_center import StateCenter


def build_run_payload(
    *,
    query: str,
    workflow_name: str,
    state: StateCenter,
    result: RunResult,
    project_root: str | Path | None = None,
    extra_preview: dict[str, Any] | None = None,
    routing_reason: str = "",
    llm_overrides: dict[str, dict[str, str | None]] | None = None,
) -> dict[str, Any]:
    """Build the default CLI payload focused on runtime control signals."""

    payload: dict[str, Any] = {
        "task": _build_task_summary(
            query=query,
            workflow_name=workflow_name,
            state=state,
            result=result,
            routing_reason=routing_reason,
        ),
        "timeline": _build_timeline(state, llm_overrides=llm_overrides),
        "evaluations": _build_evaluations(state),
        "control": _build_control_summary(state),
        "supervisor": _build_supervisor_summary(state),
        "failure": _build_failure_summary(state, result),
        "safety": _build_safety_summary(state),
        "next_action": _build_next_action(result),
        "artifacts": _build_artifacts(result, state=state, project_root=project_root),
        "memory_retrieval": _build_memory_summary(state),
        "routing": _build_routing_summary(state),
    }
    narrative = _build_narrative(payload)
    if narrative:
        payload["narrative"] = narrative
    preview = _build_preview(state, extra_preview=extra_preview)
    if preview:
        payload["preview"] = preview
    return payload


def build_raw_payload(*, state: StateCenter, result: RunResult, extra_preview: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the legacy internal payload for scripts that still need it."""

    payload = {"result": result.model_dump(), "state": state.metadata.to_dict()}
    if extra_preview:
        payload["preview"] = extra_preview
    return payload


def _build_task_summary(
    *,
    query: str,
    workflow_name: str,
    state: StateCenter,
    result: RunResult,
    routing_reason: str = "",
) -> dict[str, Any]:
    total_duration_ms = _calc_total_duration_ms(state)
    return {
        "task_id": result.task_id,
        "query": query,
        "workflow": workflow_name,
        "routing_reason": routing_reason,
        "run_mode": state.metadata.run_mode,
        "status": result.status,
        "final_node": result.final_node,
        "steps_executed": state.convergence.global_step,
        "state_version": result.state_version,
        "reason": result.reason,
        "failure_reason": result.failure_reason,
        "completion_reason": result.completion_reason,
        "duration_ms": total_duration_ms,
    }


def _build_timeline(
    state: StateCenter,
    llm_overrides: dict[str, dict[str, str | None]] | None = None,
) -> list[dict[str, Any]]:
    attempts_by_agent: dict[str, int] = {}
    timeline: list[dict[str, Any]] = []
    intermediates = state.data_pool.intermediate
    overrides = llm_overrides or {}

    write_events = [
        (i, e) for i, e in enumerate(state.execution_trace) if e.get("event") == "write"
    ]

    for idx, (trace_idx, event) in enumerate(write_events):
        agent_name = str(event.get("agent_name", "unknown"))
        field = str(event.get("field", ""))
        attempts_by_agent[agent_name] = attempts_by_agent.get(agent_name, 0) + 1
        evaluation = _next_evaluation_for_write(state.execution_trace, trace_idx, agent_name)

        provider, model = _resolve_agent_provider(
            agent_name=agent_name,
            field=field,
            intermediates=intermediates,
            overrides=overrides,
        )

        ts_current = event.get("timestamp", "")
        ts_prev = write_events[idx - 1][1].get("timestamp", "") if idx > 0 else state.execution_trace[0].get("timestamp", "") if state.execution_trace else ""
        duration_ms = _calc_duration_between(ts_prev, ts_current)

        timeline.append(
            {
                "agent": agent_name,
                "field": field,
                "status": "passed" if evaluation.get("passed", True) else "needs_attention",
                "action": evaluation.get("action", "continue"),
                "reason": evaluation.get("reason", ""),
                "attempt": attempts_by_agent[agent_name],
                "timestamp": ts_current,
                "provider": provider,
                "model": model,
                "duration_ms": duration_ms,
            }
        )

    if timeline:
        return timeline

    for event in state.execution_trace:
        if event.get("event") != "evaluation":
            continue
        timeline.append(
            {
                "agent": event.get("agent_name", "unknown"),
                "field": "",
                "status": "passed" if event.get("passed") else "needs_attention",
                "action": event.get("action", ""),
                "reason": event.get("reason", ""),
                "attempt": 1,
                "timestamp": event.get("timestamp", ""),
                "provider": "",
                "model": "",
                "duration_ms": 0,
            }
        )
    return timeline


def _build_evaluations(state: StateCenter) -> list[dict[str, Any]]:
    evaluations: list[dict[str, Any]] = []
    for event in state.execution_trace:
        if event.get("event") != "evaluation":
            continue
        evaluations.append(
            {
                "agent": event.get("agent_name", "unknown"),
                "passed": bool(event.get("passed", False)),
                "action": event.get("action", ""),
                "reason": event.get("reason", ""),
                "timestamp": event.get("timestamp", ""),
            }
        )
    return evaluations


def _build_control_summary(state: StateCenter) -> dict[str, Any]:
    checkpoint_events = _events(state.execution_trace, "checkpoint")
    rollback_events = _events(state.execution_trace, "rollback")
    replan_events = [
        event
        for event in state.execution_trace
        if event.get("event") in {"checkpoint_replan", "orchestrator_replan", "supervisor_guidance"}
    ]
    live_interrupt_events = _events(state.execution_trace, "live_interrupt")
    human_decisions = _events(state.execution_trace, "human_review_decision")
    retry_events = [
        event
        for event in state.execution_trace
        if event.get("event") == "evaluation" and event.get("action") == "retry"
    ]

    return {
        "checkpoints": len(checkpoint_events),
        "rollbacks": len(rollback_events),
        "replans": len(replan_events),
        "retries": len(retry_events),
        "live_interrupts": len(live_interrupt_events),
        "human_review_decisions": len(human_decisions),
        "replan_details": [
            {
                "event": event.get("event", ""),
                "target": event.get("target") or event.get("suggested_target") or event.get("agent_name", ""),
                "action": event.get("action") or event.get("suggested_action", ""),
                "reason": event.get("reason", ""),
                "timestamp": event.get("timestamp", ""),
            }
            for event in replan_events
        ],
    }


def _build_supervisor_summary(state: StateCenter) -> dict[str, Any] | None:
    report = state.data_pool.intermediate.get("supervisor_report")
    if not isinstance(report, dict):
        return None
    return {
        "next_action": report.get("next_action", ""),
        "status": report.get("status", ""),
        "concerns": report.get("concerns", []),
        "review_reason": report.get("review_reason", ""),
        "suggested_target": report.get("suggested_target", ""),
        "suggested_action": report.get("suggested_action", ""),
        "process_review": report.get("process_review", {}),
    }


def _build_failure_summary(state: StateCenter, result: RunResult) -> dict[str, Any] | None:
    failure_events = _events(state.execution_trace, "failure_classified")
    if failure_events:
        event = failure_events[-1]
        return {
            "category": event.get("category", ""),
            "severity": event.get("severity", ""),
            "agent": event.get("agent_name", result.final_node),
            "reason": event.get("reason", result.failure_reason or result.reason),
            "timestamp": event.get("timestamp", ""),
        }
    if result.status in {"failed", "timed_out"}:
        return {
            "category": "",
            "severity": "",
            "agent": result.final_node,
            "reason": result.failure_reason or result.reason,
            "timestamp": "",
        }
    return None


def _build_safety_summary(state: StateCenter) -> list[dict[str, Any]]:
    return [
        {
            "agent": event.get("agent_name", ""),
            "guardrail": event.get("guardrail_name", ""),
            "stage": event.get("stage", ""),
            "reason": event.get("reason", ""),
            "failure_category": event.get("failure_category", ""),
            "timestamp": event.get("timestamp", ""),
        }
        for event in _events(state.execution_trace, "guardrail_violation")
    ]


def _build_next_action(result: RunResult) -> dict[str, Any]:
    if result.status == "needs_human_review":
        return {
            "status": "waiting_for_human_review",
            "message": "Runtime paused for human confirmation.",
            "approve": f"PYTHONPATH=src python -m orchestrator resume --task-id {result.task_id} --decision approve",
            "reject": f"PYTHONPATH=src python -m orchestrator resume --task-id {result.task_id} --decision reject --reason \"...\"",
        }
    if result.status == "completed":
        return {
            "status": "completed",
            "message": "Run completed. Inspect the convergence report or analyze command for details.",
            "inspect": f"PYTHONPATH=src python -m orchestrator analyze show --task-id {result.task_id}",
        }
    return {
        "status": result.status,
        "message": result.failure_reason or result.reason or "Run stopped before completion.",
        "inspect": f"PYTHONPATH=src python -m orchestrator analyze show --task-id {result.task_id}",
    }


def _build_artifacts(
    result: RunResult,
    *,
    state: StateCenter,
    project_root: str | Path | None,
) -> dict[str, Any]:
    root = Path(project_root) if project_root else None
    state_path = str(root / "outputs" / "states" / f"{result.task_id}.json") if root else ""
    log_path = str(root / "outputs" / "logs" / f"{result.task_id}.jsonl") if root else ""
    return {
        "checkpoint_dir": result.checkpoint_dir,
        "convergence_report_path": result.convergence_report_path,
        "memory_path": result.memory_path,
        "state_path": state_path,
        "log_path": log_path,
        "state_version": state.version,
    }


def _build_preview(state: StateCenter, *, extra_preview: dict[str, Any] | None) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    plan = state.data_pool.intermediate.get("plan")
    if isinstance(plan, dict):
        preview["plan"] = {
            "plan_type": plan.get("plan_type", ""),
            "sub_questions": plan.get("sub_questions", []),
            "confidence": plan.get("confidence", None),
            "model_profile": plan.get("model_profile", ""),
            "memory_hints_used": plan.get("memory_hints_used", 0),
        }
    summary = state.data_pool.intermediate.get("summary")
    if isinstance(summary, dict):
        preview["summary"] = {
            "conclusion": _truncate(str(summary.get("conclusion", "")), 500),
            "sections": summary.get("sections", [])[:3] if isinstance(summary.get("sections"), list) else [],
            "plan_type": summary.get("plan_type", ""),
            "model_profile": summary.get("model_profile", ""),
        }
    human_review_gate = state.data_pool.intermediate.get("human_review_gate")
    if isinstance(human_review_gate, dict):
        preview["human_review"] = {
            "decision": human_review_gate.get("decision", ""),
            "status": human_review_gate.get("status", ""),
            "review_reason": human_review_gate.get("review_reason", ""),
            "recommended_target": human_review_gate.get("recommended_target", ""),
            "recommended_action": human_review_gate.get("recommended_action", ""),
            "summary_preview": _truncate(str(human_review_gate.get("summary_preview", "")), 500),
        }
    if extra_preview:
        preview.update(extra_preview)
    return preview


def _events(trace: list[dict[str, Any]], event_name: str) -> list[dict[str, Any]]:
    return [event for event in trace if event.get("event") == event_name]


def _next_evaluation_for_write(trace: list[dict[str, Any]], write_index: int, agent_name: str) -> dict[str, Any]:
    """Find the evaluation produced by the same agent after one write event."""

    for event in trace[write_index + 1 :]:
        if event.get("event") == "write" and event.get("agent_name") == agent_name:
            return {}
        if event.get("event") != "evaluation":
            continue
        if str(event.get("agent_name", "unknown")) == agent_name:
            return event
    return {}


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


# ---------------------------------------------------------------------------
# Provider / model resolution for timeline entries
# ---------------------------------------------------------------------------

_AGENT_OUTPUT_FIELD: dict[str, str] = {
    "planner": "plan",
    "summarizer": "summary",
    "supervisor": "supervisor_report",
    "human_review": "human_review_gate",
}


def _resolve_agent_provider(
    *,
    agent_name: str,
    field: str,
    intermediates: dict[str, Any],
    overrides: dict[str, dict[str, str | None]],
) -> tuple[str, str]:
    """Return (provider, model) for an agent step.

    Looks first in the agent's intermediate output, then in llm_overrides,
    then falls back to agent config heuristics.
    """
    output_key = _AGENT_OUTPUT_FIELD.get(agent_name, field)
    output = intermediates.get(output_key)
    if isinstance(output, dict):
        provider = str(output.get("provider", "") or "")
        model = str(output.get("model_profile", "") or output.get("model", "") or "")
        if provider or model:
            return provider, model

    # Try overrides
    override = overrides.get(agent_name) or overrides.get("*")
    if override:
        p = override.get("provider") or ""
        m = override.get("model") or ""
        if p or m:
            return p or "", m or ""

    # Heuristic fallback for known agents
    if agent_name == "search":
        return "tool", ""
    if agent_name == "human_review":
        return "human", ""

    return "", ""


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------


def _calc_total_duration_ms(state: StateCenter) -> int:
    trace = state.execution_trace
    if not trace:
        return 0
    first_ts = trace[0].get("timestamp", "")
    last_ts = trace[-1].get("timestamp", "")
    return _calc_duration_between(first_ts, last_ts)


def _calc_duration_between(from_ts: str, to_ts: str) -> int:
    if not from_ts or not to_ts:
        return 0
    try:
        # Handle ISO timestamps with or without timezone
        fmt = "%Y-%m-%dT%H:%M:%S"
        a_str = from_ts[:19]
        b_str = to_ts[:19]
        a = datetime.strptime(a_str, fmt)
        b = datetime.strptime(b_str, fmt)
        # Handle Z suffix
        if from_ts.endswith("Z"):
            a = a.replace(tzinfo=timezone.utc)
        if to_ts.endswith("Z"):
            b = b.replace(tzinfo=timezone.utc)
        delta = abs((b - a).total_seconds()) * 1000
        return int(delta)
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# Memory retrieval summary
# ---------------------------------------------------------------------------


def _build_memory_summary(state: StateCenter) -> dict[str, Any] | None:
    retrieved = state.data_pool.intermediate.get("retrieved_memories")
    if not isinstance(retrieved, list) or len(retrieved) == 0:
        return None
    entries: list[dict[str, Any]] = []
    for mem in retrieved:
        if not isinstance(mem, dict):
            continue
        entries.append(
            {
                "query": str(mem.get("query", "")),
                "summary": str(mem.get("summary", "")),
                "task_id": str(mem.get("task_id", "")),
                "captured_at": str(mem.get("captured_at", "")),
            }
        )
    if not entries:
        return None
    return {"total_retrieved": len(entries), "entries": entries[:3]}


def _build_routing_summary(state: StateCenter) -> dict[str, Any] | None:
    """Extract route_decision from state metadata, if present."""
    rd = state.metadata.route_decision
    if not rd:
        return None
    return {
        "task_size": rd.get("task_size", ""),
        "run_mode": rd.get("run_mode", ""),
        "risk_level": rd.get("risk_level", ""),
        "task_type": rd.get("task_type", ""),
        "confidence": rd.get("confidence", ""),
        "reasons": rd.get("reasons", []),
        "user_override": rd.get("user_override", False),
        "runtime_support": rd.get("runtime_support", ""),
        "workflow_hint": rd.get("workflow_hint"),
    }


# ---------------------------------------------------------------------------
# Natural-language narrative
# ---------------------------------------------------------------------------


def _build_narrative(payload: dict[str, Any]) -> str | None:
    """Build a 3-5 sentence natural-language summary of the run."""
    task = payload.get("task", {})
    timeline = _display_timeline(payload.get("timeline", []))
    supervisor = payload.get("supervisor")
    status = task.get("status", "")

    if not timeline:
        return None

    workflow = task.get("workflow", "unknown")
    routing = task.get("routing_reason", "")

    parts: list[str] = []

    # Opening: what the system did
    agents_seen = [e["agent"] for e in timeline]
    unique_agents = list(dict.fromkeys(agents_seen))
    agent_list = " -> ".join(unique_agents)

    parts.append(f"system auto-selected workflow '{workflow}'")
    if routing:
        parts.append(f"({routing})")

    parts.append(f"and executed: {agent_list}.")

    # Add evaluation summary
    total_evals = len(payload.get("evaluations", []))
    failed_evals = sum(1 for e in payload.get("evaluations", []) if not e.get("passed"))
    retries = sum(1 for e in timeline if e.get("action") == "retry")
    if failed_evals > 0 or retries > 0:
        parts.append(f"{total_evals} evaluations, {failed_evals} failed, {retries} retries.")
    else:
        dur = task.get("duration_ms", 0)
        parts.append(f"All {total_evals} evaluations passed in {dur / 1000:.1f}s.")

    # Supervisor decision
    if isinstance(supervisor, dict):
        action = supervisor.get("next_action", "")
        review = supervisor.get("review_reason", "")
        if action == "revise":
            parts.append(f"Supervisor requested revision: {review}")
        elif action == "accept":
            parts.append(f"Supervisor accepted: {review}")

    # Closing based on status
    if status == "needs_human_review":
        parts.append("Runtime is now paused, waiting for human confirmation.")
    elif status == "completed":
        parts.append("Run completed successfully.")
    elif status == "failed":
        failure_reason = task.get("failure_reason", "")
        parts.append(f"Run failed: {failure_reason}")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Text-mode formatter
# ---------------------------------------------------------------------------


def format_run_text(payload: dict[str, Any]) -> str:
    """Render a build_run_payload dict as human-readable terminal text."""
    task = payload.get("task", {})
    timeline = _display_timeline(payload.get("timeline", []))
    supervisor = payload.get("supervisor")
    control = payload.get("control", {})
    artifacts = payload.get("artifacts", {})
    next_action = payload.get("next_action", {})
    narrative = payload.get("narrative", "")
    memory_retrieval = payload.get("memory_retrieval")
    evaluations = payload.get("evaluations", [])

    wid = 68
    lines: list[str] = []

    # ═══ header ═══
    status_icon = _status_icon(task.get("status", ""))
    dur_s = (task.get("duration_ms", 0) or 0) / 1000
    checkpoints = control.get("checkpoints", 0)
    rollbacks = control.get("rollbacks", 0)
    steps = task.get("steps_executed", 0)
    workflow = task.get("workflow", "")
    status_str = task.get("status", "")

    lines.append("=" * wid)
    for hdr in _wrap_line(f"  Task: {task.get('query', '')}", wid):
        lines.append(hdr)
    lines.append(f"  Workflow: {workflow} | Status: {status_icon} {status_str}")
    lines.append(f"  Duration: {_format_duration(dur_s)} | Steps: {steps} | Checkpoints: {checkpoints} | Rollbacks: {rollbacks}")
    lines.append("=" * wid)
    lines.append("")

    # Narrative
    if narrative:
        for nar in _wrap_line(f"  {narrative}", wid):
            lines.append(nar)
        lines.append("")

    # Memory
    if memory_retrieval:
        total = memory_retrieval.get("total_retrieved", 0)
        entries = memory_retrieval.get("entries", [])
        lines.append(f"  Memory: {total} past record(s) matched")
        for entry in entries[:2]:
            title = entry.get("query", "") or entry.get("summary", "")
            if title:
                for mem in _wrap_line(f"    --> \"{_truncate(title, 60)}\"", wid):
                    lines.append(mem)
        lines.append("")

    # Execution timeline
    lines.append("  Execution:")
    for entry in timeline:
        agent = entry.get("agent", "")
        field = entry.get("field", "")
        passed = entry.get("status") == "passed"
        action = entry.get("action", "")
        reason = entry.get("reason", "")
        attempt = entry.get("attempt", 1)
        dur = (entry.get("duration_ms", 0) or 0) / 1000
        provider = entry.get("provider", "")
        model = entry.get("model", "")

        mark = "pass" if passed else "fail"
        detail = ""
        if not passed and action == "retry":
            detail = f"retry -> {reason}" if reason else "retry"
        elif not passed:
            detail = reason if reason else action
        if attempt > 1 and not detail:
            detail = f"attempt #{attempt}"

        provider_str = ""
        if provider:
            pm = f"{provider}/{model}" if model else provider
            provider_str = f"({pm})"

        dur_str = _format_duration(dur)
        what = _agent_action(agent, field, passed)
        parts = [f"    {agent:<12} {mark:<6}"]
        if dur_str:
            parts.append(f"{dur_str:<6}")
        parts.append(what)
        if provider_str:
            parts.append(f"  {provider_str}")
        if detail:
            parts.append(f"  {detail}")
        lines.append("".join(parts).rstrip())

    lines.append("")

    # Evaluations summary
    total_evals = len(evaluations)
    failed_evals = sum(1 for e in evaluations if not e.get("passed"))
    retries = sum(1 for e in timeline if e.get("action") == "retry")
    lines.append(f"  Evaluations: {total_evals} total | {failed_evals} failed | {retries} retries")
    lines.append("")

    # Supervisor
    if isinstance(supervisor, dict):
        sa = supervisor.get("next_action", "")
        s_reason = supervisor.get("review_reason", "")
        s_target = supervisor.get("suggested_target", "")
        s_action = supervisor.get("suggested_action", "")
        lines.append(f"  Supervisor: {sa} -- \"{s_reason}\"")
        if sa == "revise" and s_target:
            lines.append(f"    -> target: {s_target}, action: {s_action}")
        lines.append("")

    # Safety (only if violations)
    safety = payload.get("safety", [])
    if safety:
        lines.append(f"  Safety: {len(safety)} guardrail violation(s)")
        for v in safety:
            lines.append(f"    - {v.get('agent', '')}: {v.get('guardrail', '')} ({v.get('stage', '')})")
        lines.append("")
    else:
        lines.append("  Safety: 0 guardrail violations")
        lines.append("")

    # Artifacts
    lines.append("  Artifacts:")
    for key, label in [
        ("convergence_report_path", "report"),
        ("state_path", "state"),
        ("memory_path", "memory"),
        ("log_path", "log"),
    ]:
        path = artifacts.get(key, "")
        if path:
            lines.append(f"    {label}: {path}")
    lines.append("")

    # Next action
    na_status = next_action.get("status", "")
    na_message = next_action.get("message", "")
    lines.append(f"  Next: {na_status} -- {na_message}")
    for cmd_key in ("approve", "reject", "inspect"):
        cmd = next_action.get(cmd_key, "")
        if cmd:
            lines.append(f"    {cmd}")
    lines.append("")
    lines.append("=" * wid)

    return "\n".join(lines)


def _agent_action(agent: str, field: str, passed: bool) -> str:
    """Return a short human-readable description of what this agent step did."""
    if agent == "planner":
        return "generated plan" if passed else "plan failed"
    if agent == "search":
        return "collected sources" if passed else "search failed"
    if agent == "summarizer":
        return "produced synthesis" if passed else "synthesis failed"
    if agent == "supervisor":
        return "reviewed and accepted" if passed else "review flagged issues"
    if agent == "human_review":
        return "prepared review package" if passed else "review pending"
    # Generic fallback based on field name
    if field:
        return f"wrote {field}" if passed else f"failed on {field}"
    return "completed" if passed else "failed"


def _format_duration(dur_s: float) -> str:
    """Format a duration in seconds for human display."""
    if dur_s <= 0:
        return "<0.1s"
    if dur_s < 1:
        return f"{dur_s:.2f}s"
    if dur_s < 10:
        return f"{dur_s:.1f}s"
    return f"{int(dur_s)}s"


def _status_icon(status: str) -> str:
    if status == "completed":
        return "OK"
    if status == "needs_human_review":
        return "WAIT"
    if status in ("failed", "timed_out"):
        return "FAIL"
    return status.upper()


def _display_timeline(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hide runtime bookkeeping writers from the human-facing execution story."""

    return [entry for entry in timeline if entry.get("agent") not in {"memory_manager"}]


def _wrap_line(text: str, width: int) -> list[str]:
    """Wrap long text to fit within width, breaking at word boundaries."""
    if len(text) <= width:
        return [text]
    # Simple: just truncate long headers for now
    # For the narrative, break into multiple lines
    result: list[str] = []
    remaining = text
    while len(remaining) > width:
        # Find last space within width
        cut = remaining.rfind(" ", 0, width)
        if cut < 20:  # fallback: hard cut
            cut = width
        result.append(remaining[:cut].rstrip())
        remaining = "  " + remaining[cut:].lstrip()
    if remaining.strip():
        result.append(remaining)
    return result
