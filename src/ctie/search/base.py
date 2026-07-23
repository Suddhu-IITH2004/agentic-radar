"""Base types and protocol for search providers."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ctie.models.app import SearchResult


class SearchError(Exception):
    """Base exception for search provider failures."""


@runtime_checkable
class SearchProvider(Protocol):
    """Async search provider protocol."""

    provider_name: str

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Return search results for ``query``.

        Args:
            query: Search query string.
            max_results: Maximum number of results to return.

        Returns:
            Deduplicated list of ``SearchResult`` objects.

        Raises:
            SearchError: On provider failure.
        """
        ...


def classify_source_type(url: str, title: str | None = None) -> str:
    """Classify a URL into a ``SourceType`` heuristic value.

    The returned value is a string so callers can cast it to ``SourceType`` or
    fall back safely without importing the enum here.
    """
    url_l = url.lower()
    title_l = (title or "").lower()

    if "github.com" in url_l or "github" in title_l:
        return "github"
    if any(k in url_l for k in ("/docs/api", "/api-reference", "api-reference", "api docs")):
        return "api_ref"
    if any(k in url_l for k in ("/docs", "/documentation", "developers", "developer docs")):
        return "official_docs"
    if any(k in url_l for k in ("blog.", "/blog/", "medium.com")) or "blog" in title_l:
        return "blog"
    if any(k in url_l for k in ("stackoverflow", "reddit.com", "forum", "discuss")):
        return "community"
    if any(k in title_l for k in ("api reference", "api documentation", "rest api")):
        return "api_ref"
    if any(k in title_l for k in ("documentation", "docs", "developer")):
        return "official_docs"
    return "unknown"
