"""Core structured research result for a single app."""

from pydantic import BaseModel, Field, HttpUrl, field_validator
from typing import Any

from ctie.models.enums import APIType, AuthMethod, Confidence, SelfServeStatus
from ctie.models.evidence import Evidence, FieldVerification


class FieldConfidence(BaseModel):
    """Confidence score and reasoning for a single field."""

    confidence: Confidence = Field(default=Confidence.UNKNOWN, description="Confidence level.")
    score: float = Field(default=0.0, ge=0.0, le=1.0, description="Numeric confidence score.")
    reasoning: str = Field(default="", description="One-line explanation for the score.")


class ComposioEnrichment(BaseModel):
    """Optional enrichment data from the Composio SDK."""

    checked: bool = Field(default=False, description="Whether a lookup was attempted.")
    supported: bool = Field(default=False, description="Whether Composio supports this app.")
    toolkit_slug: str | None = Field(default=None, description="Composio toolkit slug if supported.")
    toolkit_name: str | None = Field(default=None, description="Composio toolkit display name.")
    auth_schemes: list[str] = Field(default_factory=list, description="Auth schemes reported by Composio.")
    tool_count: int | None = Field(default=None, description="Number of tools in the toolkit.")
    error: str | None = Field(default=None, description="Error message if lookup failed.")

    @field_validator("auth_schemes", mode="before")
    @classmethod
    def _coerce_none_auth_schemes(cls, value: Any) -> Any:
        return value if value is not None else []


class AppResearchResult(BaseModel):
    """Full structured output for one app."""

    app_id: int = Field(..., description="App identifier.")
    app_name: str = Field(..., description="App name.")
    category: str = Field(default="", description="Final category.")
    description: str = Field(default="", description="One-line description of what the app does.")
    auth_methods: list[AuthMethod] = Field(default_factory=list, description="Authentication methods.")
    self_serve: SelfServeStatus = Field(default=SelfServeStatus.UNKNOWN, description="Self-serve vs gated.")
    api_type: APIType = Field(default=APIType.UNKNOWN, description="Primary API type.")
    api_coverage: str = Field(default="", description="Rough API coverage description.")
    has_mcp: bool | None = Field(default=None, description="Whether an MCP server exists.")
    has_sdk: bool | None = Field(default=None, description="Whether an official SDK exists.")
    sdk_languages: list[str] = Field(default_factory=list, description="SDK languages if known.")
    buildable: bool | None = Field(default=None, description="Could this be a toolkit today?")
    blockers: list[str] = Field(default_factory=list, description="Main blockers if not buildable.")
    documentation_urls: list[HttpUrl] = Field(default_factory=list, description="Key documentation URLs.")
    evidence: list[Evidence] = Field(default_factory=list, description="Quote-level evidence.")
    verifications: list[FieldVerification] = Field(default_factory=list, description="Per-field verification.")
    field_confidence: dict[str, FieldConfidence] = Field(
        default_factory=dict,
        description="Confidence per field.",
    )
    overall_confidence: FieldConfidence = Field(
        default_factory=FieldConfidence,
        description="Overall result confidence.",
    )
    composio: ComposioEnrichment = Field(
        default_factory=ComposioEnrichment,
        description="Composio toolkit enrichment.",
    )
    error: str | None = Field(default=None, description="Processing error if the app failed.")

    def verification_for(self, field: str) -> FieldVerification | None:
        """Return the verification record for a field, if present."""
        for v in self.verifications:
            if v.field == field:
                return v
        return None

    def evidence_for(self, field: str) -> list[Evidence]:
        """Return all evidence items for a field."""
        return [e for e in self.evidence if e.field == field]
