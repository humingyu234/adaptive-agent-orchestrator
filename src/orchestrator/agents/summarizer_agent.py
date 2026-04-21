from .base import BaseAgent
from ..models import AgentConfig, EvalCriteriaItem, WriteSpec
from ..registry import register


@register("summarizer")
class SummarizerAgent(BaseAgent):
    config = AgentConfig(
        name="summarizer",
        reads=["query", "plan", "raw_documents"],
        writes=[WriteSpec(field="summary", schema_name="SummarySchema")],
        guardrails=["require_non_empty_query", "block_sensitive_output_terms"],
        eval_criteria=[
            EvalCriteriaItem(
                path="summary",
                expected_type="dict",
                action="retry",
                reason="summarizer 必须输出 summary 字段",
            ),
            EvalCriteriaItem(
                path="summary.conclusion",
                expected_type="non_empty_str",
                action="retry",
                reason="summary.conclusion 不能为空",
            ),
        ],
        model_profile="worker",
        max_tokens=3000,
        max_retries=2,
    )

    def run(self, context_view: dict) -> dict:
        query = str(context_view.get("query", "")).strip()
        plan = context_view.get("plan", {})
        raw_documents = context_view.get("raw_documents", [])
        sub_questions = plan.get("sub_questions", []) if isinstance(plan, dict) else []
        plan_type = plan.get("plan_type", "general") if isinstance(plan, dict) else "general"

        summary = self.complete_structured(
            "summarize",
            query=query,
            plan_type=plan_type,
            sub_questions=sub_questions,
            raw_documents=raw_documents,
        )
        return {"summary": summary}
