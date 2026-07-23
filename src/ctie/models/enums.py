"""Enumerations used across CTIE models."""

from enum import StrEnum


class AuthMethod(StrEnum):
    """Authentication methods supported by SaaS APIs."""

    OAUTH2 = "OAuth2"
    API_KEY = "API Key"
    BASIC = "Basic"
    TOKEN = "Token"
    JWT = "JWT"
    SAML = "SAML"
    OTHER = "Other"
    UNKNOWN = "Unknown"


class APIType(StrEnum):
    """API surface types."""

    REST = "REST"
    GRAPHQL = "GraphQL"
    SOAP = "SOAP"
    GRPC = "gRPC"
    WEBHOOK = "Webhook"
    SDK_ONLY = "SDK Only"
    CLI = "CLI"
    NONE = "None"
    UNKNOWN = "Unknown"


class SelfServeStatus(StrEnum):
    """Developer credential access model."""

    SELF_SERVE = "Self-serve"
    GATED = "Gated"
    PARTNER_ONLY = "Partner-only"
    PAID_REQUIRED = "Paid required"
    UNKNOWN = "Unknown"


class Confidence(StrEnum):
    """Confidence levels for extracted facts."""

    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    UNKNOWN = "Unknown"


class SourceType(StrEnum):
    """Types of evidence sources."""

    OFFICIAL_DOCS = "official_docs"
    API_REFERENCE = "api_ref"
    GITHUB = "github"
    BLOG = "blog"
    COMMUNITY = "community"
    COMPOSIO = "composio"
    UNKNOWN = "unknown"


class VerificationStatus(StrEnum):
    """Per-field verification outcomes."""

    CONFIRMED = "Confirmed"
    CONFLICT = "Conflict"
    UNVERIFIED = "Unverified"


class AppStatus(StrEnum):
    """Pipeline states for an individual app."""

    PENDING = "pending"
    QUEUED = "queued"
    SEARCHING = "searching"
    FETCHING = "fetching"
    EXTRACTING = "extracting"
    VERIFYING = "verifying"
    SCORING = "scoring"
    ENRICHING = "enriching"
    COMPLETED = "completed"
    FAILED = "failed"
