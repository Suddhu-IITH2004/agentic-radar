"""LangGraph state definition for the per-app research pipeline."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages

from ctie.models.app import AppInput, Document, SearchResult
from ctie.models.enums import AppStatus
from ctie.models.result import AppResearchResult


class AppPipelineState(TypedDict, total=False):
    """State for processing a single app through the research graph.
    
    Note: 'app' can be either an AppInput instance or a dict to support serialization.
    Agents should convert to AppInput when needed using AppInput(**state['app']).
    """

    app: AppInput | dict[str, Any] | None
    run_id: str
    search_results: list[SearchResult]
    documents: list[Document]
    result: AppResearchResult | None
    status: AppStatus
    error: str | None
    messages: Annotated[list[Any], add_messages]
