"""Generate aggregate insights from a set of research results."""

from __future__ import annotations

from collections import Counter
from typing import Any

from ctie.models.enums import APIType, AuthMethod, SelfServeStatus
from ctie.models.insights import InsightBlock
from ctie.models.result import AppResearchResult


def generate_insights(results: list[AppResearchResult]) -> list[InsightBlock]:
    """Return a list of high-level insight blocks derived from ``results``."""
    insights: list[InsightBlock] = []
    total = len(results)
    if total == 0:
        return insights

    completed = [r for r in results if not r.error]
    failed = [r for r in results if r.error]

    auth_counter: Counter[AuthMethod] = Counter()
    api_counter: Counter[APIType] = Counter()
    self_serve_counter: Counter[SelfServeStatus] = Counter()
    confidence_scores: list[float] = []
    buildable_count = 0
    mcp_count = 0
    composio_supported = 0

    for r in completed:
        auth_counter.update(r.auth_methods)
        api_counter[r.api_type] += 1
        self_serve_counter[r.self_serve] += 1
        confidence_scores.append(r.overall_confidence.score)
        if r.buildable:
            buildable_count += 1
        if r.has_mcp:
            mcp_count += 1
        if r.composio.supported:
            composio_supported += 1

    insights.append(
        InsightBlock(
            headline="Pipeline completion",
            body=f"{len(completed)} of {total} apps completed successfully; {len(failed)} failed.",
            category="overview",
        )
    )

    if auth_counter:
        top_auth = auth_counter.most_common(1)[0]
        insights.append(
            InsightBlock(
                headline=f"Most common auth method: {top_auth[0].value}",
                body=f"{top_auth[1]} apps ({round(100 * top_auth[1] / len(completed))}%) use {top_auth[0].value}.",
                category="auth",
            )
        )

    if api_counter:
        top_api = api_counter.most_common(1)[0]
        insights.append(
            InsightBlock(
                headline=f"Most common API type: {top_api[0].value}",
                body=f"{top_api[1]} apps ({round(100 * top_api[1] / len(completed))}%) expose a {top_api[0].value} API.",
                category="api",
            )
        )

    if self_serve_counter:
        self_serve = self_serve_counter.get(SelfServeStatus.SELF_SERVE, 0)
        gated = self_serve_counter.get(SelfServeStatus.GATED, 0)
        insights.append(
            InsightBlock(
                headline="Developer access model",
                body=f"{self_serve} self-serve, {gated} gated, {len(completed) - self_serve - gated} other.",
                category="access",
            )
        )

    if confidence_scores:
        avg_confidence = sum(confidence_scores) / len(confidence_scores)
        insights.append(
            InsightBlock(
                headline=f"Average overall confidence: {round(avg_confidence, 2)}",
                body="Higher scores indicate more evidence-backed extractions.",
                category="confidence",
            )
        )

    insights.append(
        InsightBlock(
            headline="Buildability",
            body=f"{buildable_count} apps appear buildable as toolkits today; {mcp_count} have an MCP server; {composio_supported} are already in the Composio catalog.",
            category="buildability",
        )
    )

    return insights


def compute_distribution(results: list[AppResearchResult]) -> dict[str, Any]:
    """Return a JSON-serializable distribution dict for charts."""
    auth_counter: Counter[str] = Counter()
    api_counter: Counter[str] = Counter()
    self_serve_counter: Counter[str] = Counter()
    confidence_counter: Counter[str] = Counter()

    for r in results:
        if not r.error:
            for a in r.auth_methods:
                auth_counter[a.value] += 1
            api_counter[r.api_type.value] += 1
            self_serve_counter[r.self_serve.value] += 1
            confidence_counter[r.overall_confidence.confidence.value] += 1

    return {
        "auth": dict(auth_counter),
        "api_type": dict(api_counter),
        "self_serve": dict(self_serve_counter),
        "confidence": dict(confidence_counter),
    }
