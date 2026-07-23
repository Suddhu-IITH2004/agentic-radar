"""Composio toolkit catalog enrichment agent using the v3 SDK."""

from __future__ import annotations

import structlog

from ctie.config import Settings
from ctie.models.result import AppResearchResult, ComposioEnrichment

logger = structlog.get_logger()

USER_ID = "ctie-research-pipeline"


class ComposioEnrichmentAgent:
    """Look up whether Composio already supports a given app/toolkit."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.api_key = settings.composio_api_key
        self._client = None
        self._session = None

        if self.api_key:
            try:
                from composio import Composio

                self._client = Composio(api_key=self.api_key)
                self._session = self._client.create(user_id=USER_ID)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "composio_enrichment_init_failed",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )

    async def enrich(self, result: AppResearchResult) -> AppResearchResult:
        """Populate ``result.composio`` from the Composio toolkit catalog.

        If no API key is configured or the SDK cannot be initialized, the
        enrichment is marked as not checked without raising an error.
        """
        if not self.api_key or self._session is None:
            logger.debug("composio_enrichment_skipped", app_id=result.app_id)
            return result

        try:
            search = self._session.search(query=result.app_name)
            if search.error is not None:
                logger.warning(
                    "composio_enrichment_search_error",
                    app_id=result.app_id,
                    error=search.error,
                )
                result.composio = ComposioEnrichment(
                    checked=False,
                    supported=False,
                    error=f"Catalog search error: {search.error}",
                )
                return result

            toolkits: set[str] = set()
            tool_slugs: list[str] = []
            for item in search.results or []:
                for tk in getattr(item, "toolkits", []) or []:
                    toolkits.add(tk)
                for slug in getattr(item, "primary_tool_slugs", []) or []:
                    tool_slugs.append(slug)
                for slug in getattr(item, "related_tool_slugs", []) or []:
                    tool_slugs.append(slug)

            if not toolkits:
                result.composio = ComposioEnrichment(checked=True, supported=False)
                logger.info(
                    "composio_enrichment_not_supported",
                    app_id=result.app_id,
                    app_name=result.app_name,
                )
                return result

            # Pick the best toolkit match (prefer exact name match).
            normalized_app = result.app_name.lower().replace(" ", "")
            toolkit_slug = next(
                (tk for tk in toolkits if normalized_app in tk.lower().replace("_", "")),
                min(toolkits, key=len),
            )

            # Look up display name and auth requirement from the toolkit list.
            toolkit_name = toolkit_slug
            auth_schemes: list[str] = []
            try:
                toolkit_details = self._session.toolkits()
                for tk in toolkit_details.items or []:
                    if tk.slug == toolkit_slug:
                        toolkit_name = tk.name or toolkit_slug
                        auth_schemes = ["no_auth"] if tk.is_no_auth else []
                        break
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "composio_enrichment_toolkit_lookup_failed",
                    app_id=result.app_id,
                    error=str(exc),
                )

            result.composio = ComposioEnrichment(
                checked=True,
                supported=True,
                toolkit_slug=toolkit_slug,
                toolkit_name=toolkit_name,
                auth_schemes=auth_schemes,
                tool_count=len(tool_slugs) if tool_slugs else None,
            )
            logger.info(
                "composio_enrichment_complete",
                app_id=result.app_id,
                app_name=result.app_name,
                toolkit=toolkit_slug,
                tool_count=len(tool_slugs),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("composio_enrichment_failed", app_id=result.app_id)
            result.composio = ComposioEnrichment(
                checked=True,
                supported=False,
                error=str(exc),
            )
        return result
