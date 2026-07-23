"""Confidence scoring helpers."""

from __future__ import annotations

from ctie.models.enums import Confidence, VerificationStatus
from ctie.models.result import AppResearchResult, FieldConfidence


class ConfidenceScorer:
    """Score confidence deterministically from evidence and verification."""

    @staticmethod
    def score_result(result: AppResearchResult) -> AppResearchResult:
        """Recompute field and overall confidence for ``result`` in place."""
        fields = [
            "category",
            "auth_methods",
            "self_serve",
            "api_type",
            "has_mcp",
            "has_sdk",
            "buildable",
        ]
        total_score = 0.0
        scored_fields = 0

        for field in fields:
            score = ConfidenceScorer._score_field(result, field)
            result.field_confidence[field] = score
            total_score += score.score
            scored_fields += 1

        if scored_fields:
            overall = total_score / scored_fields
            result.overall_confidence.score = round(overall, 2)
            result.overall_confidence.confidence = ConfidenceScorer._numeric_to_confidence(overall)
            result.overall_confidence.reasoning = (
                f"Average confidence across {scored_fields} fields."
            )
        else:
            result.overall_confidence.confidence = Confidence.UNKNOWN
            result.overall_confidence.score = 0.0
            result.overall_confidence.reasoning = "No fields scored."

        return result

    @staticmethod
    def _score_field(result: AppResearchResult, field: str) -> FieldConfidence:
        evidence = result.evidence_for(field)
        verification = result.verification_for(field)

        base = 0.0
        if evidence:
            base = min(0.7, 0.2 + 0.15 * len(evidence))
            if any(e.source_type.value == "official_docs" for e in evidence):
                base += 0.15

        if verification:
            if verification.status == VerificationStatus.CONFIRMED:
                base += 0.2
            elif verification.status == VerificationStatus.CONFLICT:
                base = max(0.0, base - 0.3)

        score = min(1.0, max(0.0, base))
        return FieldConfidence(
            confidence=ConfidenceScorer._numeric_to_confidence(score),
            score=round(score, 2),
            reasoning=f"{len(evidence)} evidence items; verification={verification.status if verification else 'none'}.",
        )

    @staticmethod
    def _numeric_to_confidence(score: float) -> Confidence:
        if score >= 0.7:
            return Confidence.HIGH
        if score >= 0.4:
            return Confidence.MEDIUM
        if score > 0.0:
            return Confidence.LOW
        return Confidence.UNKNOWN
