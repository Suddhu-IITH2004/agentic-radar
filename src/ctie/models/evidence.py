"""Evidence and citation models."""

from pydantic import BaseModel, Field, HttpUrl

from ctie.models.enums import SourceType, VerificationStatus


class Evidence(BaseModel):
    """A quote-level citation supporting an extracted fact."""

    field: str = Field(..., description="Result field this evidence supports.")
    quote: str = Field(..., min_length=1, description="Direct quote or excerpt from the source.")
    url: HttpUrl = Field(..., description="URL where the quote was found.")
    source_type: SourceType = Field(default=SourceType.UNKNOWN, description="Type of source.")


class FieldVerification(BaseModel):
    """Verification outcome for a single result field."""

    field: str = Field(..., description="Field name.")
    status: VerificationStatus = Field(..., description="Verification status.")
    evidence_count: int = Field(default=0, ge=0, description="Number of supporting evidence items.")
    conflicts: list[str] = Field(default_factory=list, description="Conflicting claims if any.")
