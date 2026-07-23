"""Base types and protocol for LLM clients."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel


@dataclass(frozen=True)
class LLMMessage:
    """A single chat message."""

    role: str
    content: str


class LLMError(Exception):
    """Base exception for LLM client failures."""


class LLMResponseError(LLMError):
    """Raised when the model returns content that cannot be parsed."""


ModelT = TypeVar("ModelT", bound=BaseModel)


@runtime_checkable
class LLMClient(Protocol):
    """Async LLM client protocol.

    Implementations must support both free-form text completion and structured
    Pydantic output. The structured path is the default for extraction agents.
    """

    provider_name: str

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        response_model: type[ModelT] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        timeout: float = 120.0,
    ) -> ModelT | str:
        """Complete a conversation.

        Args:
            messages: Conversation history in user/assistant/system order.
            response_model: Optional Pydantic model. When provided, the model is
                instructed to emit JSON matching the model schema and the result
                is validated and returned as an instance.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            timeout: Per-call timeout in seconds.

        Returns:
            An instance of ``response_model`` if provided, otherwise raw text.

        Raises:
            LLMError: On network, API, or parse failures.
        """
        ...

    async def healthcheck(self) -> dict[str, Any]:
        """Return a lightweight status dict for this provider."""
        ...


def messages_to_dicts(messages: list[LLMMessage]) -> list[dict[str, str]]:
    """Convert internal messages to provider-native dictionaries."""
    return [{"role": m.role, "content": m.content} for m in messages]
