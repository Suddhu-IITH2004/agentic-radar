"""Insight and summary models."""

from pydantic import BaseModel, Field


class InsightBlock(BaseModel):
    """A single narrative insight backed by data."""

    headline: str = Field(..., description="Short insight headline.")
    body: str = Field(..., description="Detailed explanation.")
    category: str = Field(default="general", description="Insight category.")
    evidence_app_ids: list[int] = Field(default_factory=list, description="Supporting app IDs.")
    chart_hint: str | None = Field(default=None, description="Suggested chart type.")


class PipelineSummary(BaseModel):
    """Aggregate statistics for the full research run."""

    run_id: str = Field(..., description="Unique run identifier.")
    run_at: str = Field(..., description="ISO timestamp when the run started.")
    total_apps: int = Field(..., ge=0, description="Total apps researched.")
    completed_apps: int = Field(..., ge=0, description="Apps that completed successfully.")
    failed_apps: int = Field(..., ge=0, description="Apps that failed terminally.")
    avg_confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Average overall confidence.")
    auth_distribution: dict[str, int] = Field(default_factory=dict, description="Auth method counts.")
    api_type_distribution: dict[str, int] = Field(default_factory=dict, description="API type counts.")
    self_serve_distribution: dict[str, int] = Field(default_factory=dict, description="Self-serve vs gated counts.")
    category_distribution: dict[str, int] = Field(default_factory=dict, description="Category counts.")
    mcp_count: int = Field(default=0, ge=0, description="Apps with known MCP support.")
    composio_supported_count: int = Field(default=0, ge=0, description="Apps already in Composio catalog.")
    top_blockers: list[tuple[str, int]] = Field(default_factory=list, description="Most common blockers.")
    insights: list[InsightBlock] = Field(default_factory=list, description="Narrative insights.")
    verification_sample_size: int = Field(default=0, ge=0, description="Human-verified sample size.")
    verification_accuracy_before: float | None = Field(default=None, description="Accuracy before fixes.")
    verification_accuracy_after: float | None = Field(default=None, description="Accuracy after fixes.")
