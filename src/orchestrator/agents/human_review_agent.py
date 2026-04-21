from .base import BaseAgent
from ..models import AgentConfig, EvalCriteriaItem, WriteSpec
from ..registry import register


@register("human_review")
class HumanReviewAgent(BaseAgent):
    config = AgentConfig(
        name="human_review",
        reads=["query", "summary", "supervisor_report", "execution_trace", "status", "failure_reason"],
        writes=[WriteSpec(field="human_review_gate", schema_name="HumanReviewGateSchema")],
        guardrails=["require_non_empty_query", "block_sensitive_output_terms"],
        eval_criteria=[
            EvalCriteriaItem(
                path="human_review_gate",
                expected_type="dict",
                action="fail",
                reason="human_review 必须输出 human_review_gate",
            ),
            EvalCriteriaItem(
                path="human_review_gate.decision",
                expected_type="str",
                action="fail",
                reason="human_review_gate.decision 必须是 await_human / approved / rejected",
                allowed_values={"await_human", "approved", "rejected"},
            ),
        ],
        terminal_behavior="pause_for_human",
        max_tokens=1200,
        max_retries=1,
    )

    def run(self, context_view: dict) -> dict:
        query = str(context_view.get("query", "")).strip()
        summary = context_view.get("summary", {})
        supervisor_report = context_view.get("supervisor_report", {})
        execution_trace = context_view.get("execution_trace", [])
        status = str(context_view.get("status", "running"))
        failure_reason = str(context_view.get("failure_reason", "")).strip()

        conclusion = ""
        if isinstance(summary, dict):
            conclusion = str(summary.get("conclusion", "")).strip()

        suggested_target = "none"
        suggested_action = "accept"
        review_reason = "等待人工确认最终结果。"
        if isinstance(supervisor_report, dict):
            suggested_target = str(supervisor_report.get("suggested_target", "none") or "none")
            suggested_action = str(supervisor_report.get("suggested_action", "accept") or "accept")
            review_reason = str(supervisor_report.get("review_reason", review_reason) or review_reason)

        packet = {
            "decision": "await_human",
            "approval_required": True,
            "status": "awaiting_human_review",
            "query": query,
            "review_reason": review_reason,
            "recommended_target": suggested_target,
            "recommended_action": suggested_action,
            "summary_preview": conclusion[:280],
            "trace_events_seen": len(execution_trace) if isinstance(execution_trace, list) else 0,
            "runtime_status_seen": status,
            "failure_reason_seen": failure_reason,
        }
        return {"human_review_gate": packet}
