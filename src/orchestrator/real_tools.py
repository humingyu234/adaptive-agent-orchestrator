"""真实工具实现

提供真实的外部工具能力：搜索、代码执行等。
支持多种搜索后端：DuckDuckGo（免费）、Tavily、Serper 等。
"""

from __future__ import annotations

import os
from typing import Any


async def web_search_duckduckgo(
    query: str,
    *,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """DuckDuckGo 搜索（免费，无需 API Key）

    Args:
        query: 搜索关键词
        top_k: 返回结果数量

    Returns:
        文档列表，每个包含 title/url/snippet
    """
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        try:
            from ddgs import DDGS
        except ImportError:
            raise ImportError(
                "duckduckgo-search or ddgs not installed. Run: pip install ddgs"
            )

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=top_k))
    except Exception as e:
        # 如果 DuckDuckGo 失败，返回空结果而不是抛出异常
        print(f"Warning: DuckDuckGo search failed: {e}")
        return []

    return [
        {
            "title": r.get("title", ""),
            "url": r.get("href", "") or r.get("url", ""),
            "snippet": r.get("body", "") or r.get("snippet", ""),
            "source_type": "web_search",
            "tool_name": "duckduckgo",
        }
        for r in results
    ]


async def web_search_tavily(
    query: str,
    *,
    top_k: int = 5,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Tavily 搜索（专为 AI Agent 设计）

    Args:
        query: 搜索关键词
        top_k: 返回结果数量
        api_key: Tavily API Key（可从环境变量 TAVILY_API_KEY 获取）

    Returns:
        文档列表，每个包含 title/url/snippet
    """
    import httpx

    key = api_key or os.environ.get("TAVILY_API_KEY")
    if not key:
        raise ValueError("Tavily API key not found. Set TAVILY_API_KEY environment variable.")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "query": query,
                "max_results": top_k,
                "include_answer": False,
                "include_raw_content": False,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()

    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("content", ""),
            "source_type": "web_search",
            "tool_name": "tavily",
        }
        for r in data.get("results", [])
    ]


async def web_search_serper(
    query: str,
    *,
    top_k: int = 5,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Serper 搜索（Google 搜索 API）

    Args:
        query: 搜索关键词
        top_k: 返回结果数量
        api_key: Serper API Key（可从环境变量 SERPER_API_KEY 获取）

    Returns:
        文档列表，每个包含 title/url/snippet
    """
    import httpx

    key = api_key or os.environ.get("SERPER_API_KEY")
    if not key:
        raise ValueError("Serper API key not found. Set SERPER_API_KEY environment variable.")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key},
            json={"q": query, "num": top_k},
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()

    return [
        {
            "title": r.get("title", ""),
            "url": r.get("link", ""),
            "snippet": r.get("snippet", ""),
            "source_type": "web_search",
            "tool_name": "serper",
        }
        for r in data.get("organic", [])
    ]


# =============================================================================
# 同步包装器（兼容现有 ToolRegistry）
# =============================================================================

def web_search_duckduckgo_sync(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """DuckDuckGo 搜索同步版本"""
    import asyncio
    return asyncio.run(web_search_duckduckgo(query, top_k=top_k))


def web_search_tavily_sync(query: str, top_k: int = 5, api_key: str | None = None) -> list[dict[str, Any]]:
    """Tavily 搜索同步版本"""
    import asyncio
    return asyncio.run(web_search_tavily(query, top_k=top_k, api_key=api_key))


def web_search_serper_sync(query: str, top_k: int = 5, api_key: str | None = None) -> list[dict[str, Any]]:
    """Serper 搜索同步版本"""
    import asyncio
    return asyncio.run(web_search_serper(query, top_k=top_k, api_key=api_key))


# =============================================================================
# 工具注册辅助函数
# =============================================================================

def get_available_search_tools() -> list[str]:
    """获取当前可用的搜索工具列表

    根据环境变量自动检测哪些工具可用。
    """
    tools = []

    # DuckDuckGo 总是可用（免费）
    tools.append("duckduckgo")

    # Tavily
    if os.environ.get("TAVILY_API_KEY"):
        tools.append("tavily")

    # Serper
    if os.environ.get("SERPER_API_KEY"):
        tools.append("serper")

    return tools


def get_default_search_tool() -> str:
    """获取默认搜索工具

    优先级：Tavily > Serper > DuckDuckGo
    """
    if os.environ.get("TAVILY_API_KEY"):
        return "tavily"
    if os.environ.get("SERPER_API_KEY"):
        return "serper"
    return "duckduckgo"
