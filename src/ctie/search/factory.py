"""Factory for creating the Composio search provider."""

from __future__ import annotations

import structlog

from ctie.config import Settings
from ctie.search.base import SearchError, SearchProvider
from ctie.search.composio import ComposioSearchProvider

logger = structlog.get_logger()


def create_search_provider(settings: Settings) -> SearchProvider:
    """Create a Composio-only search provider from settings.

    Args:
        settings: Application settings.

    Returns:
        A ``SearchProvider`` backed by Composio.

    Raises:
        SearchError: If Composio search cannot be configured.
    """
    if not settings.composio_api_key:
        raise SearchError("COMPOSIO_API_KEY is required for search.")

    provider = ComposioSearchProvider(api_key=settings.composio_api_key)
    logger.info("search_provider_registered", provider="composio_search")
    return provider
