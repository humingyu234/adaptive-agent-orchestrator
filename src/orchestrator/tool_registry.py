"""工具注册表

管理所有可用工具，支持 mock 工具和真实工具。
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk_level: str
    handler: Callable[..., Any]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        description: str,
        handler: Callable[..., Any],
        risk_level: str = "medium",
    ) -> None:
        if name in self._tools:
            raise ValueError(f"Tool '{name}' is already registered")
        self._tools[name] = ToolSpec(
            name=name,
            description=description,
            risk_level=risk_level,
            handler=handler,
        )

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' is not registered")
        return self._tools[name]

    def run(self, name: str, **kwargs):
        tool = self.get(name)
        return tool.handler(**kwargs)

    def list_names(self) -> list[str]:
        return sorted(self._tools)


def build_default_tool_registry() -> ToolRegistry:
    """构建默认工具注册表（包含 mock 工具）"""
    registry = ToolRegistry()
    registry.register(
        name="mock_search_context",
        description="Return mock context documents for the current runtime workflow.",
        handler=_mock_search_context,
        risk_level="low",
    )
    return registry


def build_real_tool_registry() -> ToolRegistry:
    """构建真实工具注册表

    根据环境变量自动注册可用的搜索工具：
    - DuckDuckGo：免费，无需 API Key
    - Tavily：需要 TAVILY_API_KEY
    - Serper：需要 SERPER_API_KEY
    """
    from .real_tools import (
        web_search_duckduckgo_sync,
        web_search_serper_sync,
        web_search_tavily_sync,
    )

    registry = ToolRegistry()

    # DuckDuckGo（免费，总是注册）
    registry.register(
        name="web_search",
        description="Web search using DuckDuckGo (free, no API key required).",
        handler=lambda query, **kwargs: web_search_duckduckgo_sync(
            query=query,
            top_k=kwargs.get("top_k", 5),
        ),
        risk_level="low",
    )

    registry.register(
        name="duckduckgo",
        description="DuckDuckGo web search (free).",
        handler=lambda query, **kwargs: web_search_duckduckgo_sync(
            query=query,
            top_k=kwargs.get("top_k", 5),
        ),
        risk_level="low",
    )

    # Tavily（需要 API Key）
    import os
    if os.environ.get("TAVILY_API_KEY"):
        registry.register(
            name="tavily",
            description="Tavily web search (optimized for AI agents).",
            handler=lambda query, **kwargs: web_search_tavily_sync(
                query=query,
                top_k=kwargs.get("top_k", 5),
            ),
            risk_level="low",
        )

    # Serper（需要 API Key）
    if os.environ.get("SERPER_API_KEY"):
        registry.register(
            name="serper",
            description="Serper web search (Google API).",
            handler=lambda query, **kwargs: web_search_serper_sync(
                query=query,
                top_k=kwargs.get("top_k", 5),
            ),
            risk_level="low",
        )

    return registry


def build_tool_registry(use_real_tools: bool = False) -> ToolRegistry:
    """构建工具注册表

    Args:
        use_real_tools: 是否使用真实工具

    Returns:
        ToolRegistry 实例
    """
    if use_real_tools:
        return build_real_tool_registry()
    return build_default_tool_registry()


def _mock_search_context(*, query: str, sub_questions: list[str], plan_type: str) -> list[dict]:
    documents = []
    for index, sub_question in enumerate(sub_questions or [query], start=1):
        documents.append(
            {
                "title": f"{plan_type.title()} Context {index}",
                "url": f"https://example.com/context-{index}",
                "snippet": f"Mock context for: {sub_question}",
                "source_type": "mock_context",
                "tool_name": "mock_search_context",
            }
        )
    return documents
