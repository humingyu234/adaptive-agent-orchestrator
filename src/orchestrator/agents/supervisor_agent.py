from .base import BaseAgent
from ..models import AgentConfig, EvalCriteriaItem, WriteSpec
from ..registry import register


@register("supervisor")
class SupervisorAgent(BaseAgent):
    config = AgentConfig(
        name="supervisor",
        reads=[
            "query",
            "plan",
            "raw_documents",
            "summary",
            "execution_trace",
            "retry_counters",
            "global_step",
            "status",
            "failure_reason",
        ],
        writes=[WriteSpec(field="supervisor_report", schema_name="SupervisorReportSchema")],
        guardrails=["require_non_empty_query", "block_sensitive_output_terms"],
        eval_criteria=[
            EvalCriteriaItem(
                path="supervisor_report",
                expected_type="dict",
                action="fail",
                reason="supervisor 必须输出 supervisor_report",
            ),
            EvalCriteriaItem(
                path="supervisor_report.next_action",
                expected_type="str",
                action="fail",
                reason="supervisor_report.next_action 必须是 accept 或 revise",
                allowed_values={"accept", "revise"},
            ),
        ],
        model_profile="orchestrator",
        max_tokens=2500,
        max_retries=1,
    )

    def run(self, context_view: dict) -> dict:
        query = str(context_view.get("query", "")).strip()
        plan = context_view.get("plan", {})
        summary = context_view.get("summary", {})
        raw_documents = context_view.get("raw_documents", [])
        execution_trace = context_view.get("execution_trace", [])
        retry_counters = context_view.get("retry_counters", {})
        global_step = int(context_view.get("global_step", 0) or 0)
        status = str(context_view.get("status", "running"))
        failure_reason = str(context_view.get("failure_reason", "")).strip()

        sub_questions = plan.get("sub_questions", []) if isinstance(plan, dict) else []
        conclusion = summary.get("conclusion", "") if isinstance(summary, dict) else ""

        total_retries = sum(retry_counters.values()) if isinstance(retry_counters, dict) else 0
        planner_retries = int(retry_counters.get("planner", 0)) if isinstance(retry_counters, dict) else 0

        evaluation_events = [
            event
            for event in execution_trace
            if isinstance(event, dict) and event.get("event") == "evaluation"
        ]
        failed_evaluations = [
            event
            for event in evaluation_events
            if event.get("passed") is False or event.get("action") == "fail"
        ]
        planner_failed = any(event.get("agent_name") == "planner" for event in failed_evaluations)

        concerns: list[str] = []
        review_reason = "流程完整，结果可接受"
        suggested_target = "none"
        suggested_action = "accept"

        if not sub_questions:
            concerns.append("缺少清晰的任务拆解")
            review_reason = "规划阶段没有形成清晰可执行的子问题，需要重新规划"
            suggested_target = "planner"
            suggested_action = "re_plan"
        elif planner_retries > 0 or planner_failed:
            concerns.append("规划阶段曾出现重试或失败评估")
            review_reason = "规划阶段稳定性不足，建议回到 planner 重新规划"
            suggested_target = "planner"
            suggested_action = "re_plan"
        elif not raw_documents:
            concerns.append("缺少资料支撑")
            review_reason = "检索阶段没有带回足够资料，后续总结缺少依据"
            suggested_target = "search"
            suggested_action = "gather_more_evidence"
        elif not conclusion:
            concerns.append("最终总结为空")
            review_reason = "总结阶段没有形成有效结论"
            suggested_target = "summarizer"
            suggested_action = "rewrite_summary"

        if total_retries > 0:
            concerns.append(f"流程中发生过 {total_retries} 次重试")
            if suggested_target == "none":
                review_reason = "流程虽然完成，但中间发生过重试，稳定性一般"
                suggested_target = "supervisor"
                suggested_action = "review_process"

        if failed_evaluations:
            concerns.append("流程中出现过未通过的评估结果")
            if suggested_target == "none":
                review_reason = "流程中出现过未通过的评估结果，需要进一步复查"
                suggested_target = "supervisor"
                suggested_action = "review_process"

        if failure_reason:
            concerns.append(f"系统记录了失败原因：{failure_reason}")
            if suggested_target == "none":
                review_reason = "系统记录了失败原因，建议先复查问题来源"
                suggested_target = "supervisor"
                suggested_action = "review_process"

        process_review = {
            "steps_seen": global_step + 1,
            "trace_events": len(execution_trace) if isinstance(execution_trace, list) else 0,
            "evaluation_events": len(evaluation_events),
            "failed_evaluations": len(failed_evaluations),
            "planner_retries": planner_retries,
        }

        report = self.complete_structured(
            "supervise",
            query=query,
            status=status,
            process_review=process_review,
            concerns=concerns,
            review_reason=review_reason,
            suggested_target=suggested_target,
            suggested_action=suggested_action,
        )
        return {"supervisor_report": report}
