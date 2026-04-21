"""代码审查 Agent 示例

演示如何添加新的可插拔 Agent。
"""

from orchestrator.agents.base import BaseAgent
from orchestrator.models import AgentConfig, EvalCriteriaItem, WriteSpec
from orchestrator.registry import register


@register("code_reviewer")
class CodeReviewerAgent(BaseAgent):
    """代码审查 Agent

    输入：代码片段
    输出：审查报告
    """

    config = AgentConfig(
        name="code_reviewer",
        reads=["query", "code_snippet"],
        writes=[WriteSpec(field="code_review", schema_name="CodeReviewSchema")],
        tools=[],
        guardrails=["require_non_empty_query"],
        eval_criteria=[
            EvalCriteriaItem(
                path="code_review",
                expected_type="dict",
                action="retry",
                reason="code_reviewer 必须输出 code_review 字段",
            ),
            EvalCriteriaItem(
                path="code_review.issues",
                expected_type="list",
                action="continue",
                reason="issues 应该是列表",
            ),
        ],
        llm_provider="glm",
        llm_model="GLM-5.1",
        trust_level="medium",
        max_tokens=2000,
        max_retries=2,
    )

    def run(self, context_view: dict) -> dict:
        query = context_view.get("query", "")
        code = context_view.get("code_snippet", "")

        # 实际应该调用 LLM
        # 这里用 mock 演示
        return {
            "code_review": {
                "summary": f"审查了 {len(code)} 字符的代码",
                "issues": [
                    {"line": 1, "severity": "info", "message": "示例问题"},
                ],
                "suggestions": ["建议1", "建议2"],
                "approved": True,
            }
        }
