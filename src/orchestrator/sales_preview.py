"""Sales-agent-specific CLI preview builder.

Moved out of __main__.py per Phase 9A cleanup contract.
Business preview logic lives here; the CLI only calls it.
"""

from __future__ import annotations

from typing import Any

from .state_center import StateCenter


def build_sales_preview(state: StateCenter) -> dict[str, Any] | None:
    """Build a sales-agent preview dict from state intermediates.

    Returns None if no sales-related intermediate data is present.
    """
    intermediate = state.data_pool.intermediate
    sales_profile = intermediate.get("sales_profile")
    sales_strategy = intermediate.get("sales_strategy")
    sales_reply = intermediate.get("sales_reply")
    runtime_summary = intermediate.get("sales_runtime_summary")
    if not any(
        isinstance(item, dict)
        for item in (sales_profile, sales_strategy, sales_reply, runtime_summary)
    ):
        return None

    preview: dict[str, Any] = {}
    if isinstance(sales_profile, dict):
        industry = str(sales_profile.get("industry", "")).strip()
        company_type = str(sales_profile.get("company_type", "")).strip()
        pain_points = sales_profile.get("pain_points", [])
        pressure = sales_profile.get("decision_pressure", [])
        preview["sales_profile_preview"] = {
            "industry": industry,
            "company_type": company_type,
            "pain_points": pain_points[:3] if isinstance(pain_points, list) else [],
            "decision_pressure": pressure[:3] if isinstance(pressure, list) else [],
        }
    if isinstance(sales_strategy, dict):
        preview["sales_strategy_preview"] = {
            "positioning": sales_strategy.get("positioning", ""),
            "next_action": sales_strategy.get("next_action", ""),
            "risk_notes": (
                sales_strategy.get("risk_notes", [])[:3]
                if isinstance(sales_strategy.get("risk_notes"), list)
                else []
            ),
            "generation_mode": sales_strategy.get("generation_mode", "unknown"),
            "provider": sales_strategy.get("provider", ""),
            "fallback_reason": sales_strategy.get("fallback_reason", ""),
        }
    if isinstance(sales_reply, dict):
        preview["reply_draft_preview"] = {
            "message": sales_reply.get("message", ""),
            "cta": sales_reply.get("cta", ""),
            "send_policy": sales_reply.get("send_policy", ""),
            "generation_mode": sales_reply.get("generation_mode", "unknown"),
            "provider": sales_reply.get("provider", ""),
            "fallback_reason": sales_reply.get("fallback_reason", ""),
        }
    if isinstance(runtime_summary, dict):
        preview["risk_decision_preview"] = {
            "risk_level": runtime_summary.get("risk_level_label")
            or runtime_summary.get("risk_level", ""),
            "risk_flags": runtime_summary.get("risk_flags", []),
            "decision": runtime_summary.get("decision_label")
            or runtime_summary.get("decision", ""),
            "reason": runtime_summary.get("reason", ""),
        }
    return preview or None
