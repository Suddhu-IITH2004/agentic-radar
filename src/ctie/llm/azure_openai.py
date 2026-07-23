"""Azure OpenAI LLM client with structured-output support and retry logic."""

from __future__ import annotations

from typing import Any

import structlog
from openai import APIError, AsyncAzureOpenAI, AuthenticationError, RateLimitError
from pydantic import ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ctie.config import Settings
from ctie.llm.base import (
    LLMClient,
    LLMError,
    LLMMessage,
    LLMResponseError,
    ModelT,
    messages_to_dicts,
)

logger = structlog.get_logger()


class AzureOpenAIClient(LLMClient):
    """Azure OpenAI client implementing the ``LLMClient`` protocol.
    
    Features:
    - Automatic retry with exponential backoff for rate limits and transient errors
    - Circuit breaker integration ready
    - Structured output parsing with validation
    - Health check support
    """

    provider_name = "azure_openai"

    def __init__(self, settings: Settings) -> None:
        if not settings.azure_openai_api_key or not settings.azure_openai_endpoint:
            raise LLMError(
                "Azure OpenAI requires AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT."
            )
        self.settings = settings
        self.deployment = str(settings.azure_openai_deployment).strip()
        self.client = AsyncAzureOpenAI(
            api_key=settings.azure_openai_api_key,
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
            timeout=120.0,
            max_retries=2,
        )
        logger.info("azure_openai_client_initialized", deployment=self.deployment)

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type((RateLimitError, APIError, ConnectionError)),
        reraise=True,
    )
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        response_model: type[ModelT] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        timeout: float = 120.0,
    ) -> ModelT | str:
        """Complete a chat request with automatic retry on rate limits and transient errors.
        
        Retries up to 5 times with exponential backoff (2s, 4s, 8s, 16s, 32s).
        Raises the original exception after all retries are exhausted.
        """
        extra: dict[str, Any] = {}
        if response_model is not None:
            # Recent openai SDK supports Pydantic models directly.
            extra["response_format"] = response_model

        completion_kwargs: dict[str, Any] = {
            "model": self.deployment,
            "messages": messages_to_dicts(messages),
            "temperature": temperature,
            "timeout": timeout,
            **extra,
        }
        if max_tokens is not None:
            completion_kwargs["max_tokens"] = max_tokens

        try:
            response = await self.client.beta.chat.completions.parse(**completion_kwargs)
        except AttributeError:
            # Fallback for older SDK versions without beta.parse support.
            logger.debug("azure_openai_using_legacy_completion")
            response = await self.client.chat.completions.create(**completion_kwargs)
        except RateLimitError as exc:
            logger.warning(
                "azure_openai_rate_limited",
                deployment=self.deployment,
                error=str(exc),
            )
            raise  # Let tenacity handle the retry
        except APIError as exc:
            logger.warning(
                "azure_openai_api_error",
                deployment=self.deployment,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise  # Let tenacity handle the retry
        except Exception as exc:
            logger.error(
                "azure_openai_unexpected_error",
                deployment=self.deployment,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise LLMError(f"Azure OpenAI completion failed: {exc}") from exc

        content = response.choices[0].message.content or ""
        if response_model is None:
            return content

        # If the SDK already parsed the Pydantic model, return it.
        parsed = getattr(response.choices[0].message, "parsed", None)
        if parsed is not None:
            logger.debug("azure_openai_structured_output_parsed")
            return parsed  # type: ignore[return-value]

        # Otherwise parse JSON manually.
        cleaned = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        if not cleaned:
            raise LLMResponseError("Azure OpenAI returned empty structured output.")
        try:
            return response_model.model_validate_json(cleaned)
        except ValidationError as exc:
            logger.error(
                "azure_openai_structured_parse_failed",
                content=cleaned[:1000],
                error=str(exc),
            )
            raise LLMResponseError(f"Failed to parse Azure OpenAI response: {exc}") from exc

    async def healthcheck(self) -> dict[str, Any]:
        """Return provider status with a tiny chat completion."""
        try:
            await self.client.chat.completions.create(
                model=self.deployment,
                messages=[{"role": "user", "content": "Ping"}],
                max_tokens=1,
                timeout=10.0,
            )
            logger.info("azure_openai_healthcheck_ok", deployment=self.deployment)
            return {"provider": self.provider_name, "status": "ok", "deployment": self.deployment}
        except AuthenticationError as exc:
            logger.error("azure_openai_healthcheck_auth_failed", error=str(exc))
            return {"provider": self.provider_name, "status": "auth_error", "error": str(exc)}
        except RateLimitError as exc:
            logger.warning("azure_openai_healthcheck_rate_limited", error=str(exc))
            return {"provider": self.provider_name, "status": "rate_limited", "error": str(exc)}
        except APIError as exc:
            logger.error("azure_openai_healthcheck_api_error", error=str(exc))
            return {"provider": self.provider_name, "status": "api_error", "error": str(exc)}
        except Exception as exc:
            logger.error("azure_openai_healthcheck_unexpected", error=str(exc), error_type=type(exc).__name__)
            return {"provider": self.provider_name, "status": "error", "error": str(exc)}
