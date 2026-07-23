"""AWS Bedrock LLM client with structured-output support via tool use."""

from __future__ import annotations

import json
import typing
from typing import Any

import boto3
import structlog
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ValidationError

from ctie.config import Settings
from ctie.llm.base import (
    LLMClient,
    LLMError,
    LLMMessage,
    LLMResponseError,
    ModelT,
)

logger = structlog.get_logger()


class BedrockClient(LLMClient):
    """AWS Bedrock client implementing the ``LLMClient`` protocol.

    Structured output is implemented with a single required tool whose input
    schema matches the Pydantic model. This is the recommended pattern for
    Anthropic Claude models on Bedrock and works for other tool-supported
    models as well.
    """

    provider_name = "bedrock"

    def __init__(self, settings: Settings) -> None:
        # Support either Bearer token OR traditional AWS credentials
        self.settings = settings
        self.model_id = settings.bedrock_model
        self.bearer_token = settings.aws_bearer_token_bedrock
        
        if self.bearer_token:
            # Use Bearer token authentication
            # Create client with minimal dummy credentials (required by boto3)
            self.client = boto3.client(
                "bedrock-runtime",
                aws_access_key_id="dummy",
                aws_secret_access_key="dummy",
                region_name=settings.aws_region,
            )
            # Register event handler to inject Bearer token into Authorization header
            self.client.meta.events.register("before-send", self._inject_bearer_token)
        else:
            # Use traditional AWS credentials
            if not settings.aws_access_key_id or not settings.aws_secret_access_key:
                raise LLMError(
                    "AWS Bedrock requires either AWS_BEARER_TOKEN_BEDROCK or (AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY)."
                )
            
            # Build boto3 client with optional session token for temporary credentials
            client_kwargs = {
                "aws_access_key_id": settings.aws_access_key_id,
                "aws_secret_access_key": settings.aws_secret_access_key,
                "region_name": settings.aws_region,
            }
            if settings.aws_session_token:
                client_kwargs["aws_session_token"] = settings.aws_session_token
            
            self.client = boto3.client("bedrock-runtime", **client_kwargs)
    
    def _inject_bearer_token(self, request, **kwargs):
        """Inject Bearer token into Authorization header for all requests."""
        request.headers["Authorization"] = f"Bearer {self.bearer_token}"

    def _to_bedrock_messages(self, messages: list[LLMMessage]) -> list[dict[str, Any]]:
        """Convert internal messages to Bedrock converse message format."""
        converted: list[dict[str, Any]] = []
        for m in messages:
            role = m.role
            if role not in ("user", "assistant"):
                # Bedrock converse only accepts user/assistant roles.
                role = "user"
            converted.append({"role": role, "content": [{"text": m.content}]})
        return converted

    @staticmethod
    def _normalize_response_model(model_cls: type[ModelT]) -> type[BaseModel]:
        """Return a concrete Pydantic model for ``model_cls``.

        Bedrock's tool input schema requires a top-level object. When callers
        request a ``list[T]`` response, wrap it in a temporary model so the
        tool schema is valid and unwrap the result before returning it.
        """
        import typing

        origin = typing.get_origin(model_cls)
        if origin is list:
            item_type = typing.get_args(model_cls)[0]

            class _ListWrapper(BaseModel):
                items: list[item_type]  # type: ignore[valid-type]

            _ListWrapper.__name__ = f"{getattr(item_type, '__name__', 'Item')}List"
            return _ListWrapper, True
        return model_cls, False  # type: ignore[return-value]

    @staticmethod
    def _pydantic_to_tool_schema(model_cls: type[BaseModel]) -> dict[str, Any]:
        """Convert a Pydantic model schema to Bedrock tool input schema."""
        schema = model_cls.model_json_schema()
        # Bedrock requires top-level type object and no $defs references.
        schema["type"] = "object"
        schema["additionalProperties"] = False
        return {
            "toolSpec": {
                "name": "structured_response",
                "description": schema.get("description", "Structured response"),
                "inputSchema": {"json": schema},
            }
        }

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        response_model: type[ModelT] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        timeout: float = 120.0,
    ) -> ModelT | str:
        # Normalize generic ``list[T]`` into a concrete object schema for Bedrock.
        tool_model: type[BaseModel] | None = None
        is_list_wrapper = False
        if response_model is not None:
            tool_model, is_list_wrapper = self._normalize_response_model(response_model)

        converse_input: dict[str, Any] = {
            "modelId": self.model_id,
            "messages": self._to_bedrock_messages(messages),
            "inferenceConfig": {
                "temperature": max(0.0, min(1.0, temperature)),
                "maxTokens": max_tokens or 4096,
            },
        }

        if tool_model is not None:
            converse_input["toolConfig"] = {
                "tools": [self._pydantic_to_tool_schema(tool_model)],
                "toolChoice": {"tool": {"name": "structured_response"}},
            }

        try:
            response = self.client.converse(**converse_input)
        except (BotoCoreError, ClientError) as exc:
            raise LLMError(f"Bedrock converse failed: {exc}") from exc

        output_message = response.get("output", {}).get("message", {})
        content_blocks = output_message.get("content", [])

        if response_model is None:
            for block in content_blocks:
                text = block.get("text")
                if text:
                    return text
            return ""

        for block in content_blocks:
            tool_use = block.get("toolUse")
            if tool_use and tool_use.get("name") == "structured_response":
                raw_input = tool_use.get("input")
                if isinstance(raw_input, str):
                    try:
                        parsed = json.loads(raw_input)
                    except json.JSONDecodeError as exc:
                        raise LLMResponseError(f"Bedrock toolUse input is not valid JSON: {exc}") from exc
                elif isinstance(raw_input, dict):
                    parsed = raw_input
                else:
                    raise LLMResponseError("Bedrock toolUse input has unexpected type.")
                try:
                    validated = tool_model.model_validate(parsed) if tool_model else parsed
                except ValidationError as exc:
                    # Surface exactly what failed so callers can fix schemas/prompts.
                    logger.error(
                        "bedrock_structured_parse_failed",
                        content=json.dumps(parsed)[:2000],
                        error=str(exc),
                    )
                    raise LLMResponseError(f"Failed to parse Bedrock response: {exc}") from exc
                if is_list_wrapper:
                    return validated.items  # type: ignore[union-attr]
                return validated  # type: ignore[return-value]

        # Some models may return text JSON instead of a tool call; attempt to parse it.
        for block in content_blocks:
            text = block.get("text", "")
            cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            if cleaned:
                try:
                    validated = (
                        tool_model.model_validate_json(cleaned) if tool_model else json.loads(cleaned)
                    )
                    if is_list_wrapper:
                        return validated.items  # type: ignore[union-attr]
                    return validated  # type: ignore[return-value]
                except ValidationError:
                    logger.warning("bedrock_text_block_parse_failed", content=cleaned[:500])

        raise LLMResponseError("Bedrock returned no structured toolUse content.")

    async def healthcheck(self) -> dict[str, Any]:
        """Return provider status by invoking a trivial completion."""
        try:
            response = self.client.converse(
                modelId=self.model_id,
                messages=[
                    {"role": "user", "content": [{"text": "Respond with the word ok."}]},
                ],
                inferenceConfig={"temperature": 0.0, "maxTokens": 10},
            )
            text = ""
            for block in response.get("output", {}).get("message", {}).get("content", []):
                text = block.get("text", "")
            return {"provider": self.provider_name, "status": "ok", "ping_response": text.strip()}
        except ClientError as exc:
            return {"provider": self.provider_name, "status": "client_error", "error": str(exc)}
        except BotoCoreError as exc:
            return {"provider": self.provider_name, "status": "boto_error", "error": str(exc)}
