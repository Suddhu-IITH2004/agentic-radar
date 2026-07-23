"""Extraction agent: documents → structured AppResearchResult."""

from __future__ import annotations

import structlog

from ctie.llm.base import LLMClient, LLMMessage
from ctie.models.app import AppInput, Document
from ctie.models.result import AppResearchResult
from ctie.prompts.extract import (
    EXTRACTION_SYSTEM_PROMPT,
    build_extraction_user_prompt,
)

logger = structlog.get_logger()


class ExtractionAgent:
    """Extract structured facts from fetched documents."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def extract(self, app: AppInput, documents: list[Document]) -> AppResearchResult:
        """Extract an ``AppResearchResult`` from ``documents``.

        Args:
            app: The app being researched.
            documents: Fetched and cleaned documents.

        Returns:
            Structured extraction result.
        """
        if not documents:
            logger.warning("extraction_no_documents", app_id=app.id, app_name=app.name)
            return AppResearchResult(
                app_id=app.id,
                app_name=app.name,
                category=app.category_hint,
                error="No documents available for extraction.",
            )

        documents_text = self._format_documents(documents)
        messages = [
            LLMMessage(role="system", content=EXTRACTION_SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=build_extraction_user_prompt(
                    app_name=app.name,
                    documents_text=documents_text,
                    category_hint=app.category_hint,
                ),
            ),
        ]

        try:
            result = await self.llm.complete(
                messages,
                response_model=AppResearchResult,
                temperature=0.2,
            )
            # Ensure IDs are set correctly even if the model ignored them.
            result.app_id = app.id
            result.app_name = app.name
            if not result.category:
                result.category = app.category_hint
            logger.info(
                "extraction_complete",
                app_id=app.id,
                app_name=app.name,
                evidence_count=len(result.evidence),
            )
            return result
        except Exception as exc:
            logger.exception("extraction_failed", app_id=app.id, app_name=app.name)
            return AppResearchResult(
                app_id=app.id,
                app_name=app.name,
                category=app.category_hint,
                error=f"Extraction failed: {exc}",
            )

    @staticmethod
    def _format_documents(documents: list[Document]) -> str:
        parts: list[str] = []
        for idx, doc in enumerate(documents, start=1):
            parts.append(
                f"""--- Document {idx} ---
URL: {doc.url}
Title: {doc.title or 'Untitled'}
{doc.cleaned_text[:8000]}
"""
            )
        return "\n".join(parts)
