"""Fallback LLM client that chains a primary provider with one or more backups."""

from __future__ import annotations

from typing import Any

import structlog

from ctie.llm.base import LLMClient, LLMError, LLMMessage, ModelT

logger = structlog.get_logger()


class FallbackLLMClient(LLMClient):
    """Try a list of clients in order until one succeeds.

    The first configured client is the primary. If it raises ``LLMError``,
    the next client is attempted. Health-check failures do not count as
    LLM errors and are not used for fallback here.
    """

    provider_name = "fallback"

    def __init__(self, clients: list[LLMClient]) -> None:
        if not clients:
            raise LLMError("FallbackLLMClient requires at least one client.")
        self.clients = clients

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        response_model: type[ModelT] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        timeout: float = 120.0,
    ) -> ModelT | str:
        last_error: Exception | None = None
        for idx, client in enumerate(self.clients):
            try:
                result = await client.complete(
                    messages,
                    response_model=response_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                )
                if idx > 0:
                    logger.warning(
                        "llm_fallback_succeeded",
                        provider=client.provider_name,
                        attempt=idx + 1,
                    )
                return result
            except LLMError as exc:
                last_error = exc
                logger.warning(
                    "llm_provider_failed",
                    provider=client.provider_name,
                    attempt=idx + 1,
                    error=str(exc),
                )

        raise LLMError(f"All LLM providers failed. Last error: {last_error}")

    async def healthcheck(self) -> dict[str, Any]:
        """Return health status for every configured client."""
        statuses = []
        for client in self.clients:
            try:
                status = await client.healthcheck()
            except Exception as exc:  # noqa: BLE001
                status = {"provider": client.provider_name, "status": "exception", "error": str(exc)}
            statuses.append(status)
        return {"provider": self.provider_name, "statuses": statuses}
