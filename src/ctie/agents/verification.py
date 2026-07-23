"""Verification agent: cross-check extracted facts against source documents."""

from __future__ import annotations

import structlog

from ctie.llm.base import LLMClient, LLMMessage
from ctie.models.app import Document
from ctie.models.evidence import FieldVerification
from ctie.models.result import AppResearchResult
from ctie.prompts.verify import (
    VERIFICATION_SYSTEM_PROMPT,
    build_verification_user_prompt,
)

logger = structlog.get_logger()


class VerificationAgent:
    """Verify extracted facts against source documents."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def verify(
        self,
        result: AppResearchResult,
        documents: list[Document],
    ) -> list[FieldVerification]:
        """Return per-field verification records.

        If there are no documents or the result already has verifications,
        return the existing verifications.
        """
        if not documents:
            return result.verifications

        documents_text = self._format_documents(documents)
        messages = [
            LLMMessage(role="system", content=VERIFICATION_SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=build_verification_user_prompt(
                    app_name=result.app_name,
                    result_json=result.model_dump_json(exclude={"verifications"}),
                    documents_text=documents_text,
                ),
            ),
        ]

        try:
            verifications = await self.llm.complete(
                messages,
                response_model=list[FieldVerification],
                temperature=0.2,
            )
            logger.info(
                "verification_complete",
                app_id=result.app_id,
                app_name=result.app_name,
                count=len(verifications),
            )
            return verifications
        except Exception:
            logger.exception("verification_failed", app_id=result.app_id, app_name=result.app_name)
            return result.verifications

    @staticmethod
    def _format_documents(documents: list[Document]) -> str:
        parts: list[str] = []
        for idx, doc in enumerate(documents, start=1):
            parts.append(
                f"""--- Document {idx} ---
URL: {doc.url}
{doc.cleaned_text[:4000]}
"""
            )
        return "\n".join(parts)
