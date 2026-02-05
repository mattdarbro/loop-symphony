"""Tavily web search API wrapper."""

import logging
from dataclasses import dataclass

import httpx

from loop_symphony.config import get_settings
from loop_symphony.tools.base import ToolManifest

logger = logging.getLogger(__name__)

TAVILY_API_URL = "https://api.tavily.com/search"


@dataclass
class SearchResult:
    """A single search result from Tavily."""

    title: str
    url: str
    content: str
    score: float


@dataclass
class SearchResponse:
    """Response from Tavily search."""

    query: str
    results: list[SearchResult]
    answer: str | None = None


class TavilyClient:
    """Wrapper for Tavily web search API."""

    name: str = "tavily"
    capabilities: frozenset[str] = frozenset({"web_search"})

    def manifest(self) -> ToolManifest:
        """Return static metadata about this tool."""
        return ToolManifest(
            name=self.name,
            version="0.1.0",
            description="Tavily web search API wrapper",
            capabilities=self.capabilities,
            config_keys=frozenset({"TAVILY_API_KEY"}),
        )

    async def health_check(self) -> bool:
        """Check connectivity to the Tavily API with a minimal search."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    TAVILY_API_URL,
                    json={
                        "api_key": self.api_key,
                        "query": "ping",
                        "max_results": 1,
                        "include_answer": False,
                    },
                )
                response.raise_for_status()
            return True
        except Exception:
            return False

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.tavily_api_key
        self.timeout = 30.0

    async def search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        include_answer: bool = True,
    ) -> SearchResponse:
        """Execute a web search using Tavily.

        Args:
            query: The search query
            max_results: Maximum number of results to return
            search_depth: "basic" or "advanced"
            include_answer: Whether to include AI-generated answer

        Returns:
            SearchResponse with results

        Raises:
            httpx.HTTPError: If the request fails
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                TAVILY_API_URL,
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": search_depth,
                    "include_answer": include_answer,
                },
            )
            response.raise_for_status()
            data = response.json()

        results = [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                content=r.get("content", ""),
                score=r.get("score", 0.0),
            )
            for r in data.get("results", [])
        ]

        return SearchResponse(
            query=query,
            results=results,
            answer=data.get("answer"),
        )

    async def search_multiple(
        self,
        queries: list[str],
        max_results_per_query: int = 3,
    ) -> list[SearchResponse]:
        """Execute multiple searches in parallel.

        Args:
            queries: List of search queries
            max_results_per_query: Max results per query

        Returns:
            List of SearchResponses
        """
        import asyncio

        tasks = [
            self.search(query, max_results=max_results_per_query) for query in queries
        ]
        return await asyncio.gather(*tasks, return_exceptions=False)
