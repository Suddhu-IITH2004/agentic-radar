"""Composio Search Toolkit provider using the v3 SDK."""

from __future__ import annotations

from typing import Any

import structlog
from circuitbreaker import circuit
from pydantic import HttpUrl
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ctie.models.app import SearchResult
from ctie.models.enums import SourceType
from ctie.search.base import SearchError, SearchProvider, classify_source_type

logger = structlog.get_logger()

SEARCH_TOOL = "COMPOSIO_SEARCH_WEB"
USER_ID = "ctie-research-pipeline"


class ComposioSearchProvider(SearchProvider):
    """Search provider backed by the Composio v3 Search toolkit.

    Uses the official ``composio`` SDK to execute ``COMPOSIO_SEARCH_WEB``
    within a persistent session. A circuit breaker and tenacity retry wrapper
    provide production-grade resilience.
    """

    provider_name = "composio_search"

    def __init__(self, api_key: str | None, max_retries: int = 3) -> None:
        if not api_key:
            raise SearchError("Composio API key is required for search.")

        self.api_key = api_key
        self.max_retries = max_retries

        try:
            from composio import Composio
        except ImportError as exc:
            raise SearchError("composio package is not installed.") from exc

        self._client = Composio(api_key=api_key)
        self._session = self._client.create(user_id=USER_ID)
        logger.info(
            "composio_search_initialized",
            session_id=self._session.session_id,
            provider=self.provider_name,
        )

    @circuit(failure_threshold=5, recovery_timeout=60, name="composio_search_circuit")
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((SearchError,)),
        reraise=True,
    )
    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Search the web using Composio's ``COMPOSIO_SEARCH_WEB`` tool.

        The tool returns a narrative answer plus a ``citations`` list. We
        treat the citations as the canonical search results.
        """
        if not query or not query.strip():
            raise SearchError("Search query cannot be empty.")

        logger.debug("composio_search_start", query=query, max_results=max_results)

        try:
            response = self._session.execute(
                SEARCH_TOOL,
                arguments={"query": query.strip()},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "composio_search_failed",
                query=query,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise SearchError(f"Composio search failed for '{query}': {exc}") from exc

        if response.error is not None:
            logger.warning(
                "composio_search_tool_error",
                query=query,
                error=response.error,
            )
            raise SearchError(f"Composio search returned error: {response.error}")

        data = response.data or {}
        results = self._parse_results(data, query, max_results)

        logger.info(
            "composio_search_success",
            query=query,
            citations_found=len(data.get("citations", [])),
            returned=len(results),
        )
        return results

    def _parse_results(
        self, data: dict[str, Any], query: str, max_results: int
    ) -> list[SearchResult]:
        """Parse a Composio ``COMPOSIO_SEARCH_WEB`` response.

        The response contains ``answer`` and ``citations``. We prefer
        ``citations`` because they carry auditable URLs and titles.
        """
        citations = data.get("citations") if isinstance(data, dict) else None
        if not isinstance(citations, list):
            citations = []

        results: list[SearchResult] = []
        seen: set[str] = set()
        for idx, item in enumerate(citations[:max_results], start=1):
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("id") or ""
            title = item.get("title") or ""
            if not url:
                continue
            try:
                HttpUrl(url)
            except Exception:  # noqa: BLE001
                logger.debug("composio_search_skipped_invalid_url", url=url)
                continue
            if url in seen:
                continue
            seen.add(url)
            results.append(
                SearchResult(
                    title=title or None,
                    url=url,
                    source_type=SourceType(classify_source_type(url, title)),
                    position=idx,
                    query=query,
                )
            )
        return results

