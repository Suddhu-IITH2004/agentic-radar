"""Factory for creating the configured LLM client with fallback support."""

from __future__ import annotations

import structlog

from ctie.config import LLMProvider, Settings
from ctie.llm.azure_openai import AzureOpenAIClient
from ctie.llm.base import LLMClient, LLMError
from ctie.llm.bedrock import BedrockClient
from ctie.llm.fallback import FallbackLLMClient

logger = structlog.get_logger()


def create_llm_client(
    settings: Settings,
    *,
    provider: LLMProvider | None = None,
    enable_fallback: bool = True,
) -> LLMClient:
    """Create an LLM client from settings.

    Args:
        settings: Application settings.
        provider: Optional provider override. Defaults to ``settings.llm_provider``.
        enable_fallback: If True and a fallback provider is configured, build a
            ``FallbackLLMClient`` with the requested provider first.

    Returns:
        A configured ``LLMClient``.

    Raises:
        LLMError: If no usable provider can be constructed.
    """
    requested = provider or settings.llm_provider
    clients: list[LLMClient] = []

    def _try_build(p: LLMProvider) -> LLMClient | None:
        try:
            if p == LLMProvider.AZURE_OPENAI:
                return AzureOpenAIClient(settings)
            if p == LLMProvider.BEDROCK:
                return BedrockClient(settings)
        except LLMError as exc:
            logger.warning("llm_provider_build_failed", provider=p.value, error=str(exc))
        return None

    primary = _try_build(requested)
    if primary is None:
        raise LLMError(f"Requested LLM provider '{requested.value}' could not be built.")
    clients.append(primary)

    if enable_fallback:
        fallback_order = [
            p for p in LLMProvider if p != requested
        ]
        for p in fallback_order:
            client = _try_build(p)
            if client is not None:
                clients.append(client)

    if len(clients) == 1:
        return clients[0]
    return FallbackLLMClient(clients)
