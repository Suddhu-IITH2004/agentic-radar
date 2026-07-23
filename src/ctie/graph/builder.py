"""LangGraph builder for the per-app research pipeline."""

from __future__ import annotations

from typing import Any

import structlog
from langgraph.graph import END, StateGraph

from ctie.agents.enrichment import ComposioEnrichmentAgent
from ctie.agents.extraction import ExtractionAgent
from ctie.agents.scoring import ConfidenceScorer
from ctie.agents.verification import VerificationAgent
from ctie.config import Settings
from ctie.graph.state import AppPipelineState
from ctie.llm.base import LLMClient
from ctie.models.app import AppInput
from ctie.models.enums import AppStatus
from ctie.retrieval.fetcher import Fetcher
from ctie.search.base import SearchProvider
from ctie.storage.sqlite import SQLiteStore

logger = structlog.get_logger()


def _get_app(state: AppPipelineState) -> AppInput | None:
    """Extract AppInput from state, handling both dict and instance formats.
    
    Args:
        state: The pipeline state.
        
    Returns:
        AppInput instance or None if not available.
    """
    app = state.get("app")
    if app is None:
        return None
    if isinstance(app, dict):
        return AppInput(**app)
    return app


def _get_app_id(state: AppPipelineState) -> int | None:
    """Extract app ID from state safely.
    
    Args:
        state: The pipeline state.
        
    Returns:
        App ID or None if not available.
    """
    app = state.get("app")
    if app is None:
        return None
    if isinstance(app, dict):
        return app.get("id")
    return app.id


async def _search_node(state: AppPipelineState, search_provider: SearchProvider, settings: Settings) -> AppPipelineState:
    """Execute search queries for the app.
    
    Args:
        state: Current pipeline state.
        search_provider: Search provider to use.
        settings: Application settings.
        
    Returns:
        Updated state with search results.
    """
    import asyncio
    
    app = _get_app(state)
    if app is None:
        return {**state, "status": AppStatus.FAILED, "error": "No app in state."}

    queries = _build_queries(app)
    results: list[Any] = []
    failed_queries = 0
    
    for idx, query in enumerate(queries):
        try:
            logger.info("executing_search_query", app_id=app.id, query=query, query_num=idx+1, total=len(queries))
            batch = await search_provider.search(query, max_results=settings.ctie_documents_per_app)
            results.extend(batch)
            logger.debug("search_query_success", app_id=app.id, query=query, results_count=len(batch))
            
            # Add delay between queries to avoid overwhelming the provider
            if idx < len(queries) - 1:  # Don't delay after last query
                await asyncio.sleep(1.0)
        except Exception as exc:  # noqa: BLE001
            failed_queries += 1
            logger.warning(
                "search_query_failed", 
                app_id=app.id, 
                query=query, 
                error=str(exc),
                error_type=type(exc).__name__,
                failed_count=failed_queries,
                total_queries=len(queries),
            )
            # Continue with other queries even if one fails

    seen = set()
    unique = []
    for r in results:
        key = str(r.url)
        if key not in seen:
            seen.add(key)
            unique.append(r)

    if not unique:
        error_msg = (
            f"No search results found after {len(queries)} queries "
            f"({failed_queries} failed, {len(queries) - failed_queries} succeeded with no results)."
        )
        logger.error(
            "search_node_no_results",
            app_id=app.id,
            app_name=app.name,
            total_queries=len(queries),
            failed_queries=failed_queries,
        )
        return {
            **state,
            "status": AppStatus.FAILED,
            "error": error_msg,
        }

    logger.info(
        "search_node_success",
        app_id=app.id,
        app_name=app.name,
        unique_results=len(unique),
        total_results=len(results),
        queries_executed=len(queries),
        queries_failed=failed_queries,
    )

    return {
        **state,
        "search_results": unique[: settings.ctie_documents_per_app],
        "status": AppStatus.SEARCHING,
    }


async def _fetch_node(state: AppPipelineState, fetcher: Fetcher, settings: Settings) -> AppPipelineState:
    """Fetch documents from search results.
    
    Args:
        state: Current pipeline state.
        fetcher: Document fetcher to use.
        settings: Application settings.
        
    Returns:
        Updated state with fetched documents.
    """
    app = _get_app(state)
    results = state.get("search_results", [])
    if app is None:
        return {**state, "status": AppStatus.FAILED, "error": "No app in state."}

    documents = []
    failed_fetches = 0
    
    logger.info(
        "fetch_node_starting",
        app_id=app.id,
        app_name=app.name,
        urls_to_fetch=len(results[: settings.ctie_documents_per_app]),
    )
    
    for idx, sr in enumerate(results[: settings.ctie_documents_per_app]):
        try:
            logger.debug(
                "fetching_document",
                app_id=app.id,
                url=str(sr.url),
                position=idx + 1,
                total=len(results[: settings.ctie_documents_per_app]),
            )
            doc = await fetcher.fetch(str(sr.url), app_id=app.id, search_result=sr)
            documents.append(doc)
        except Exception as exc:  # noqa: BLE001
            failed_fetches += 1
            logger.warning(
                "fetch_failed",
                app_id=app.id,
                url=str(sr.url),
                error=str(exc),
                error_type=type(exc).__name__,
                failed_count=failed_fetches,
            )

    if not documents:
        error_msg = (
            f"No documents could be fetched. "
            f"Tried {len(results[: settings.ctie_documents_per_app])} URLs, all failed."
        )
        logger.error(
            "fetch_node_no_documents",
            app_id=app.id,
            app_name=app.name,
            urls_tried=len(results[: settings.ctie_documents_per_app]),
            failed_fetches=failed_fetches,
        )
        return {
            **state,
            "status": AppStatus.FAILED,
            "error": error_msg,
        }

    logger.info(
        "fetch_node_success",
        app_id=app.id,
        app_name=app.name,
        documents_fetched=len(documents),
        urls_tried=len(results[: settings.ctie_documents_per_app]),
        failed_fetches=failed_fetches,
    )

    return {
        **state,
        "documents": documents,
        "status": AppStatus.FETCHING,
    }


async def _extract_node(state: AppPipelineState, extraction_agent: ExtractionAgent) -> AppPipelineState:
    app = _get_app(state)
    documents = state.get("documents", [])
    if app is None:
        return {**state, "status": AppStatus.FAILED, "error": "No app in state."}

    try:
        result = await extraction_agent.extract(app, documents)
    except Exception as exc:  # noqa: BLE001
        logger.exception("extract_node_failed", app_id=app.id)
        return {
            **state,
            "status": AppStatus.FAILED,
            "error": f"Extraction failed: {exc}",
        }

    return {
        **state,
        "result": result,
        "status": AppStatus.EXTRACTING,
    }


async def _verify_node(state: AppPipelineState, verification_agent: VerificationAgent) -> AppPipelineState:
    result = state.get("result")
    documents = state.get("documents", [])
    if result is None:
        return {**state, "status": AppStatus.FAILED, "error": "No result to verify."}

    try:
        verifications = await verification_agent.verify(result, documents)
        result.verifications = verifications
    except Exception as exc:  # noqa: BLE001
        logger.warning("verify_node_failed", app_id=result.app_id, error=str(exc))

    return {
        **state,
        "result": result,
        "status": AppStatus.VERIFYING,
    }


async def _score_node(state: AppPipelineState) -> AppPipelineState:
    result = state.get("result")
    if result is None:
        return {**state, "status": AppStatus.FAILED, "error": "No result to score."}
    ConfidenceScorer.score_result(result)
    return {
        **state,
        "result": result,
        "status": AppStatus.SCORING,
    }


async def _enrich_node(state: AppPipelineState, enrichment_agent: ComposioEnrichmentAgent) -> AppPipelineState:
    result = state.get("result")
    if result is None:
        return {**state, "status": AppStatus.FAILED, "error": "No result to enrich."}

    try:
        result = await enrichment_agent.enrich(result)
    except Exception as exc:  # noqa: BLE001
        logger.warning("enrich_node_failed", app_id=result.app_id, error=str(exc))

    return {
        **state,
        "result": result,
        "status": AppStatus.ENRICHING,
    }


async def _save_node(state: AppPipelineState, store: SQLiteStore) -> AppPipelineState:
    app = _get_app(state)
    result = state.get("result")
    error = state.get("error")
    if app is None:
        return {**state, "status": AppStatus.FAILED, "error": "No app in state."}

    status = AppStatus.COMPLETED if result and not result.error else AppStatus.FAILED
    try:
        await store.update_app_status(app.id, status.value, error=error, result=result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("save_node_failed", app_id=app.id)
        return {
            **state,
            "status": AppStatus.FAILED,
            "error": f"Save failed: {exc}",
        }

    return {
        **state,
        "status": status,
    }


def _route_after_search(state: AppPipelineState) -> str:
    status = state.get("status")
    if status == AppStatus.FAILED:
        return "save"
    return "fetch"


def _route_after_fetch(state: AppPipelineState) -> str:
    status = state.get("status")
    if status == AppStatus.FAILED:
        return "save"
    return "extract"


def _route_after_extract(state: AppPipelineState) -> str:
    status = state.get("status")
    if status == AppStatus.FAILED:
        return "save"
    return "verify"


def _build_queries(app: Any) -> list[str]:
    queries = [
        f"{app.name} API authentication",
        f"{app.name} developer docs",
        f"{app.name} REST API reference",
        f"{app.name} MCP server",
    ]
    for hint in app.hints:
        queries.append(f"{app.name} {hint}")
    return queries


def build_research_graph(
    settings: Settings,
    llm: LLMClient,
    search_provider: SearchProvider,
    fetcher: Fetcher,
    store: SQLiteStore,
) -> StateGraph:
    """Build a LangGraph state graph for researching one app."""
    extraction_agent = ExtractionAgent(llm)
    verification_agent = VerificationAgent(llm)
    enrichment_agent = ComposioEnrichmentAgent(settings)

    from functools import partial

    workflow = StateGraph(AppPipelineState)

    workflow.add_node("search", partial(_search_node, search_provider=search_provider, settings=settings))
    workflow.add_node("fetch", partial(_fetch_node, fetcher=fetcher, settings=settings))
    workflow.add_node("extract", partial(_extract_node, extraction_agent=extraction_agent))
    workflow.add_node("verify", partial(_verify_node, verification_agent=verification_agent))
    workflow.add_node("score", _score_node)
    workflow.add_node("enrich", partial(_enrich_node, enrichment_agent=enrichment_agent))
    workflow.add_node("save", partial(_save_node, store=store))

    workflow.set_entry_point("search")
    workflow.add_conditional_edges("search", _route_after_search, {"fetch": "fetch", "save": "save"})
    workflow.add_conditional_edges("fetch", _route_after_fetch, {"extract": "extract", "save": "save"})
    workflow.add_conditional_edges("extract", _route_after_extract, {"verify": "verify", "save": "save"})
    workflow.add_edge("verify", "score")
    workflow.add_edge("score", "enrich")
    workflow.add_edge("enrich", "save")
    workflow.add_edge("save", END)

    return workflow
