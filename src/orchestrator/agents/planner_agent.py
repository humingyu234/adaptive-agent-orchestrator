from .base import BaseAgent
from ..models import AgentConfig, EvalCriteriaItem, WriteSpec
from ..registry import register


@register("planner")
class PlannerAgent(BaseAgent):
    config = AgentConfig(
        name="planner",
        reads=["query", "retrieved_memories"],
        writes=[WriteSpec(field="plan", schema_name="PlanSchema")],
        guardrails=["require_non_empty_query", "block_sensitive_output_terms"],
        eval_criteria=[
            EvalCriteriaItem(
                path="plan",
                expected_type="dict",
                action="retry",
                reason="planner 必须输出 plan 字段",
            ),
            EvalCriteriaItem(
                path="plan.sub_questions",
                expected_type="list",
                action="retry",
                reason="planner 的 sub_questions 必须是非空列表",
                min_items=1,
            ),
            EvalCriteriaItem(
                path="plan.sub_questions",
                expected_type="list",
                action="retry",
                reason="planner 的 sub_questions 数量必须在 2 到 6 之间",
                min_items=2,
                max_items=6,
            ),
        ],
        model_profile="worker",
        max_tokens=2000,
        max_retries=2,
    )

    def run(self, context_view: dict) -> dict:
        query = str(context_view.get("query", "")).strip()
        retrieved_memories = context_view.get("retrieved_memories", [])
        plan_type = self._infer_plan_type(query)
        plan = self.complete_structured(
            "plan",
            query=query,
            plan_type=plan_type,
            retrieved_memories=retrieved_memories,
        )
        return {"plan": plan}

    def _infer_plan_type(self, query: str) -> str:
        lowered = query.lower()
        if any(keyword in lowered for keyword in ["support", "客服", "回复", "答复", "邮件"]):
            return "service"
        if any(keyword in lowered for keyword in ["write", "写", "brief", "文案", "内容"]):
            return "content"
        if any(keyword in lowered for keyword in ["code", "bug", "debug", "修复", "开发"]):
            return "coding"
        return "research"
