"""Document fetcher backed exclusively by Composio v3."""

from __future__ import annotations

from datetime import UTC, datetime
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

from ctie.config import Settings
from ctie.models.app import Document, SearchResult
from ctie.storage.sqlite import SQLiteStore

logger = structlog.get_logger()

FETCH_TOOL = "COMPOSIO_SEARCH_FETCH_URL_CONTENT"
USER_ID = "ctie-research-pipeline"


class FetchError(Exception):
    """Base exception for fetch failures."""


class Fetcher:
    """Fetch and clean documents from URLs using Composio v3.

    Fetch order:

    1. SQLite document cache.
    2. Composio ``COMPOSIO_SEARCH_FETCH_URL_CONTENT`` tool.
    """

    def __init__(
        self,
        settings: Settings,
        store: SQLiteStore | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.max_size = settings.ctie_max_fetch_size
        self.composio_api_key = settings.composio_api_key

        if not self.composio_api_key:
            raise FetchError("COMPOSIO_API_KEY is required for fetch.")

        try:
            from composio import Composio
        except ImportError as exc:
            raise FetchError("composio package is not installed.") from exc

        self._client = Composio(api_key=self.composio_api_key)
        self._session = self._client.create(user_id=USER_ID)
        logger.info(
            "composio_fetch_initialized",
            session_id=self._session.session_id,
        )

    async def fetch(
        self,
        url: str,
        app_id: int,
        search_result: SearchResult | None = None,
        use_cache: bool = True,
    ) -> Document:
        """Fetch and clean ``url`` for ``app_id`` via Composio.

        Args:
            url: Target URL.
            app_id: App identifier for cache association.
            search_result: Optional source search result metadata.
            use_cache: Whether to return a cached document if available.

        Returns:
            A cleaned ``Document``.

        Raises:
            FetchError: If Composio fetch fails or returns no content.
        """
        if use_cache and self.store is not None:
            cached = await self.store.get_document(url, app_id=app_id)
            if cached is not None:
                logger.debug("fetch_cache_hit", url=url, app_id=app_id)
                return cached

        text, title = await self._fetch_composio(url)
        if not text:
            raise FetchError(f"Composio returned no content for {url}.")

        # Truncate to configured max size.
        encoded = text.encode("utf-8")
        if len(encoded) > self.max_size:
            text = encoded[: self.max_size].decode("utf-8", errors="ignore")

        document = Document(
            url=HttpUrl(url),
            cleaned_text=text,
            title=title or search_result.title if search_result else title,
            fetch_method="composio",
            status_code=200,
            fetched_at=datetime.now(UTC).isoformat(),
            content_length=len(text.encode("utf-8")),
        )

        if self.store is not None:
            await self.store.upsert_document(app_id, document, search_result=search_result)

        return document

    @circuit(failure_threshold=5, recovery_timeout=60, name="composio_fetch_circuit")
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((FetchError,)),
        reraise=True,
    )
    async def _fetch_composio(self, url: str) -> tuple[str, str | None]:
        """Fetch URL content via the Composio v3 fetch tool."""
        logger.debug("composio_fetch_start", url=url)

        try:
            response = self._session.execute(
                FETCH_TOOL,
                arguments={
                    "urls": [url],
                    "text": True,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "composio_fetch_request_failed",
                url=url,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise FetchError(f"Composio fetch request failed for {url}: {exc}") from exc

        if response.error is not None:
            logger.warning(
                "composio_fetch_tool_error",
                url=url,
                error=response.error,
            )
            raise FetchError(f"Composio fetch returned error: {response.error}")

        data = response.data or {}
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list) or not results:
            logger.warning("composio_fetch_no_results", url=url, data_keys=list(data.keys()) if isinstance(data, dict) else type(data).__name__)
            raise FetchError(f"Composio fetch returned no results for {url}.")

        item = results[0]
        if not isinstance(item, dict):
            raise FetchError(f"Unexpected Composio fetch result type for {url}.")

        text = item.get("text") or ""
        title = item.get("title") or None
        status = next(
            (s for s in data.get("statuses", []) if isinstance(s, dict) and s.get("id") == url),
            None,
        )
        if status and status.get("status") != "success":
            logger.warning(
                "composio_fetch_status_not_success",
                url=url,
                status=status.get("status"),
                source=status.get("source"),
            )

        logger.debug(
            "composio_fetch_success",
            url=url,
            title=title,
            length=len(text),
            status=status.get("status") if status else None,
        )
        return str(text), title
