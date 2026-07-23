"""CTIE configuration loaded from environment variables and .env files."""

from enum import StrEnum
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(StrEnum):
    """Supported LLM providers."""

    AZURE_OPENAI = "azure_openai"
    BEDROCK = "bedrock"


class Settings(BaseSettings):
    """Application settings.

    Values are loaded from environment variables and an optional `.env` file.
    All secrets are optional at import time so the CLI can print help without
    credentials, but runtime commands validate their presence before use.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Composio (required for search and fetch)
    composio_api_key: str | None = Field(default=None, description="Composio API key for search, fetch, and toolkit enrichment.")

    # LLM provider selection
    llm_provider: LLMProvider = Field(default=LLMProvider.BEDROCK, description="Primary LLM provider.")

    # Azure OpenAI
    azure_openai_api_key: str | None = Field(default=None, description="Azure OpenAI API key.")
    azure_openai_endpoint: str | None = Field(default=None, description="Azure OpenAI resource endpoint.")
    azure_openai_deployment: str = Field(default="gpt-4o", description="Azure OpenAI deployment name.")
    azure_openai_api_version: str = Field(default="2024-08-01-preview", description="Azure OpenAI API version.")

    # AWS Bedrock
    aws_access_key_id: str | None = Field(default=None, description="AWS access key ID.")
    aws_secret_access_key: str | None = Field(default=None, description="AWS secret access key.")
    aws_session_token: str | None = Field(default=None, description="AWS session token (for temporary credentials).")
    aws_bearer_token_bedrock: str | None = Field(default=None, description="AWS Bedrock Bearer token (alternative to traditional credentials).")
    aws_region: str = Field(default="us-east-1", description="AWS region.")
    bedrock_model: str = Field(
        default="anthropic.claude-3-5-sonnet-20241022-v2:0",
        description="Bedrock model ID.",
    )

    # Pipeline behavior
    ctie_concurrency: int = Field(default=5, ge=1, le=20, description="Max parallel apps.")
    ctie_db_path: Path = Field(default=Path("outputs/ctie.db"), description="SQLite database path.")
    ctie_max_retries: int = Field(default=3, ge=0, le=10, description="Max retries for transient failures.")
    ctie_force_fresh: bool = Field(default=False, description="Force a fresh run ignoring existing state.")
    ctie_fetch_timeout: int = Field(default=30, ge=5, description="HTTP fetch timeout in seconds.")
    ctie_max_fetch_size: int = Field(
        default=2_000_000,
        ge=100_000,
        description="Max cleaned document size in bytes to store.",
    )
    ctie_documents_per_app: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Number of top search results to fetch per app.",
    )

    @field_validator("ctie_db_path", mode="before")
    @classmethod
    def _resolve_db_path(cls, value: str | Path) -> Path:
        return Path(value).expanduser().resolve()

    def db_url(self) -> str:
        """Return the SQLite database URL."""
        return f"sqlite+aiosqlite:///{self.ctie_db_path}"
    
    def validate_required_credentials(self) -> dict[str, list[str] | str]:
        """Validate that required API keys are present for the selected provider.

        Returns:
            Dict with ``status`` (``"ok"`` or ``"error"``), ``errors``, and
            ``warnings`` lists.
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Composio is required for search and fetch
        if not self.composio_api_key:
            errors.append("COMPOSIO_API_KEY is required for search and fetch")

        # Validate primary LLM provider
        if self.llm_provider == LLMProvider.AZURE_OPENAI:
            if not self.azure_openai_api_key:
                errors.append("AZURE_OPENAI_API_KEY is required")
            if not self.azure_openai_endpoint:
                errors.append("AZURE_OPENAI_ENDPOINT is required")
        elif self.llm_provider == LLMProvider.BEDROCK:
            # Support either bearer token OR traditional AWS credentials
            has_bearer_token = bool(self.aws_bearer_token_bedrock)
            has_traditional_creds = self.aws_access_key_id and self.aws_secret_access_key
            if not (has_bearer_token or has_traditional_creds):
                errors.append(
                    "Bedrock requires either AWS_BEARER_TOKEN_BEDROCK or "
                    "(AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY)"
                )
            if has_bearer_token and has_traditional_creds:
                warnings.append(
                    "Both AWS_BEARER_TOKEN_BEDROCK and traditional credentials are set; "
                    "using bearer token."
                )

        return {
            "status": "ok" if not errors else "error",
            "errors": errors,
            "warnings": warnings,
        }


def get_settings() -> Settings:
    """Return the application settings singleton."""
    return Settings()
