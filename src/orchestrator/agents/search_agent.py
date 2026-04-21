from .base import BaseAgent
from ..models import AgentConfig, EvalCriteriaItem, WriteSpec
from ..registry import register


@register("search")
class SearchAgent(BaseAgent):
    config = AgentConfig(
        name="search",
        reads=["query", "plan"],
        writes=[WriteSpec(field="raw_documents", schema_name="SearchResultSet")],
        tools=["mock_search_context"],  # 默认使用 mock，可被覆盖
        guardrails=["require_non_empty_query", "block_sensitive_output_terms"],
        eval_criteria=[
            EvalCriteriaItem(
                path="raw_documents",
                expected_type="list",
                action="retry",
                reason="search 必须输出 raw_documents 列表",
            ),
            EvalCriteriaItem(
                path="raw_documents",
                expected_type="list",
                action="retry",
                reason="search 至少需要返回 1 条结果",
                min_items=1,
            ),
        ],
        trust_level="low",
        max_tokens=4000,
        max_retries=2,
    )

    def run(self, context_view: dict) -> dict:
        query = str(context_view.get("query", "")).strip()
        plan = context_view.get("plan", {})
        sub_questions = plan.get("sub_questions", []) if isinstance(plan, dict) else []
        plan_type = plan.get("plan_type", "general") if isinstance(plan, dict) else "general"

        # 根据配置的工具选择搜索方式
        tool_name = self.config.tools[0] if self.config.tools else "mock_search_context"

        if tool_name == "mock_search_context":
            # 使用 mock 搜索
            documents = self.run_tool(
                "mock_search_context",
                query=query,
                sub_questions=sub_questions,
                plan_type=plan_type,
            )
        else:
            # 使用真实搜索
            documents = self._run_real_search(query=query, tool_name=tool_name)

        return {"raw_documents": documents}

    def _run_real_search(self, query: str, tool_name: str = "web_search") -> list[dict]:
        """执行真实搜索"""
        try:
            return self.run_tool(tool_name, query=query, top_k=5)
        except Exception as e:
            # 如果真实搜索失败，fallback 到 mock
            print(f"Warning: Real search failed ({e}), falling back to mock")
            return self.run_tool(
                "mock_search_context",
                query=query,
                sub_questions=[],
                plan_type="research",
            )


@register("real_search")
class RealSearchAgent(BaseAgent):
    """使用真实搜索的 Agent"""

    config = AgentConfig(
        name="real_search",
        reads=["query", "plan"],
        writes=[WriteSpec(field="raw_documents", schema_name="SearchResultSet")],
        tools=["web_search", "tavily", "duckduckgo"],  # 真实搜索工具
        guardrails=["require_non_empty_query", "block_sensitive_output_terms"],
        eval_criteria=[
            EvalCriteriaItem(
                path="raw_documents",
                expected_type="list",
                action="retry",
                reason="search 必须输出 raw_documents 列表",
            ),
            EvalCriteriaItem(
                path="raw_documents",
                expected_type="list",
                action="retry",
                reason="search 至少需要返回 1 条结果",
                min_items=1,
            ),
        ],
        trust_level="low",
        max_tokens=4000,
        max_retries=2,
    )

    def __init__(self, **kwargs):
        # 强制使用真实工具
        super().__init__(use_real_tools=True, **kwargs)

    def run(self, context_view: dict) -> dict:
        query = str(context_view.get("query", "")).strip()
        import os

        # 优先使用 Tavily（如果有 key），否则用 DuckDuckGo
        if os.environ.get("TAVILY_API_KEY"):
            documents = self.run_tool("tavily", query=query, top_k=5)
        else:
            documents = self.run_tool("duckduckgo", query=query, top_k=5)

        return {"raw_documents": documents}
