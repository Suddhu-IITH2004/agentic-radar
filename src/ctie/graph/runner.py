"""Pipeline runner that orchestrates the per-app research graph."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog

from ctie.config import Settings
from ctie.graph.builder import build_research_graph
from ctie.graph.state import AppPipelineState
from ctie.llm.base import LLMClient
from ctie.models.app import AppInput
from ctie.models.enums import AppStatus
from ctie.models.result import AppResearchResult
from ctie.retrieval.fetcher import Fetcher
from ctie.search.base import SearchProvider
from ctie.storage.sqlite import SQLiteStore

logger = structlog.get_logger()


def _result_for_error(app: AppInput, error: Exception) -> AppResearchResult:
    """Return a failed result for an unhandled exception."""
    return AppResearchResult(
        app_id=app.id,
        app_name=app.name,
        category=app.category_hint,
        error=f"Unhandled pipeline error: {error}",
    )


class ResearchPipeline:
    """End-to-end research pipeline with checkpoint/resume support."""

    def __init__(
        self,
        settings: Settings,
        llm: LLMClient,
        search_provider: SearchProvider,
        fetcher: Fetcher,
        store: SQLiteStore,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.search_provider = search_provider
        self.fetcher = fetcher
        self.store = store
        self.run_id = f"run-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

    async def run(
        self,
        apps: list[AppInput],
        *,
        max_concurrency: int | None = None,
        resume: bool = True,
    ) -> list[AppResearchResult]:
        """Run the pipeline for all apps.

        Args:
            apps: List of apps to research.
            max_concurrency: Max parallel apps. Defaults to ``settings.ctie_concurrency``.
            resume: If True, skip apps already in a completed or in-progress state.

        Returns:
            List of research results (one per app).
        """
        await self.store.initialize()
        await self.store.create_run(self.run_id, total_apps=len(apps))

        for app in apps:
            await self.store.upsert_app(app, self.run_id, status=AppStatus.PENDING.value)

        semaphore = asyncio.Semaphore(max_concurrency or self.settings.ctie_concurrency)

        async def _process_one(app: AppInput) -> AppResearchResult:
            async with semaphore:
                try:
                    return await self._process_app(app, resume=resume)
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "process_app_unhandled_exception",
                        app_id=app.id,
                        app_name=app.name,
                        error=str(exc),
                    )
                    return _result_for_error(app, exc)

        results = await asyncio.gather(*[_process_one(app) for app in apps])

        completed = sum(1 for r in results if r and not r.error)
        failed = len(results) - completed
        summary = {
            "run_id": self.run_id,
            "completed": completed,
            "failed": failed,
            "total": len(apps),
        }
        await self.store.update_run_summary(
            self.run_id,
            completed_apps=completed,
            failed_apps=failed,
            summary_json=__import__("json").dumps(summary),
        )
        logger.info("pipeline_finished", run_id=self.run_id, completed=completed, failed=failed)
        return results

    async def _process_app(self, app: AppInput, resume: bool = True) -> AppResearchResult:
        stored = await self.store.get_app(app.id)

        # Always skip apps that already have a completed result in the database.
        if stored and stored.status == AppStatus.COMPLETED.value and stored.result is not None:
            logger.info(
                "app_already_completed",
                app_id=app.id,
                app_name=app.name,
                run_id=stored.run_id,
            )
            return stored.result

        # When resuming, also reuse successful results from previous runs.
        if resume and stored and stored.result is not None and not stored.result.error:
            logger.info(
                "app_resume_completed",
                app_id=app.id,
                app_name=app.name,
                run_id=stored.run_id,
            )
            return stored.result

        await self.store.update_app_status(app.id, AppStatus.QUEUED.value)

        graph = build_research_graph(
            self.settings,
            self.llm,
            self.search_provider,
            self.fetcher,
            self.store,
        )
        # Convert Pydantic models to dicts for serialization compatibility
        initial_state: AppPipelineState = {
            "app": app.model_dump() if hasattr(app, "model_dump") else app,
            "run_id": self.run_id,
            "search_results": [],
            "documents": [],
            "result": None,
            "status": AppStatus.PENDING,
            "error": None,
            "messages": [],
        }

        try:
            # Compile without checkpointer to avoid serialization issues
            # State is already persisted in SQLite via the store
            compiled = graph.compile()
            final_state = await compiled.ainvoke(initial_state)
        except Exception as exc:
            logger.exception("graph_invoke_failed", app_id=app.id, app_name=app.name)
            error_msg = f"Graph invocation failed: {exc}"
            await self.store.update_app_status(app.id, AppStatus.FAILED.value, error=error_msg)
            return AppResearchResult(
                app_id=app.id,
                app_name=app.name,
                category=app.category_hint,
                error=error_msg,
            )

        result = final_state.get("result")
        status = final_state.get("status", AppStatus.FAILED)
        error = final_state.get("error")

        if result is None:
            result = AppResearchResult(
                app_id=app.id,
                app_name=app.name,
                category=app.category_hint,
                error=error or "No result produced.",
            )

        # Persist final state explicitly in case save node was skipped.
        await self.store.update_app_status(
            app.id,
            status.value if isinstance(status, AppStatus) else str(status),
            error=error,
            result=result,
        )
        return result
