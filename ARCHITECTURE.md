# Composio Toolkit Intelligence Engine (CTIE)

## High-Level Architecture v0.1

> **Design posture:** This is a production research platform, not a script. Every decision below prioritizes observability, recoverability, verifiability, and extensibility over brevity.

---

## 1. System Purpose

Build an autonomous, auditable research pipeline that evaluates 100+ SaaS applications for Composio toolkit readiness. The system must:

- Discover official documentation and developer resources.
- Extract structured facts about auth, API surface, MCP support, self-serve access, blockers, and evidence.
- Cross-verify facts across multiple sources.
- Score confidence per field.
- Detect uncertainty and hallucinations explicitly.
- Generate interactive HTML reports with clustering, insights, and verification evidence.
- Resume from crashes and be reproducible end-to-end.

---

## 2. Architectural Layers

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Interface Layer                              │
│   Typer CLI  │  Optional FastAPI API  │  Jupyter Notebook Hooks      │
└──────────────────────┬──────────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────────────┐
│                       Orchestration Layer                            │
│   LangGraph State Machine  │  Checkpointing  │  Cost / Token Budget  │
└──────────────────────┬──────────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────────────┐
│                         Agent Layer                                  │
│   Coordinator → Research → Retrieval → Extraction → Verification    │
│   → Consistency → Confidence → Insight → Report                      │
└──────────────────────┬──────────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────────────┐
│                       Retrieval Layer                                │
│   Web Search (Serper/Tavily)  │  Browser (Playwright)  │  Crawler   │
│   GitHub API  │  RSS / Blog  │  Caching Layer (SQLite + disk)       │
└──────────────────────┬──────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Storage Layer                                 │
│   SQLite (state + cache + evidence)  │  JSONL (raw facts)            │
│   CSV (tabular exports)  │  Parquet (analytics)  │  HTML reports    │
└──────────────────────────────────────────────────────────────────────┘
                       ▲
┌──────────────────────┴──────────────────────────────────────────────┐
│                      Verification Layer                              │
│   Self-Consistency  │  Cross-Source Voting  │  Human Sampling       │
│   Before/After Metrics  │  Hallucination Detection                 │
└──────────────────────────────────────────────────────────────────────┘
                       ▲
┌──────────────────────┴──────────────────────────────────────────────┐
│                      Observability Layer                             │
│   Structured Logging  │  Cost Tracking  │  Token Usage  │  Traces   │
│   Per-App Audit Logs  │  Retry Histograms  │  Rate-Limit Telemetry  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Agent Topology

We model the pipeline as a **directed graph of specialized agents (LangGraph nodes)**. Each agent is a Pydantic-configured, async Python class with a single responsibility.

### 3.1 Coordinator Agent

- **Responsibility:** Entry point, workload distribution, crash recovery, global budget enforcement.
- **Inputs:** App list, config (concurrency, model, budget), resume checkpoint ID.
- **Outputs:** Job manifests, per-app state transitions.
- **Key behaviors:**
  - Loads checkpoint from SQLite on startup.
  - Enqueues apps not yet in `COMPLETED` or `FAILED` state.
  - Applies global token/cost budget; pauses if exceeded.
  - Handles graceful shutdown and resume.

### 3.2 Research Agent

- **Responsibility:** Formulate search queries and discover candidate documentation URLs.
- **Inputs:** App metadata (name, website, hints).
- **Outputs:** Ranked list of candidate URLs with source type tags (`official_docs`, `api_ref`, `github`, `blog`, `community`).
- **Key behaviors:**
  - Generates multiple query variants (e.g., "{app} API authentication", "{app} developer docs", "{app} MCP server").
  - Uses web search + optional LLM re-ranking.
  - Filters out SEO spam and affiliate pages via domain allowlist + heuristic scoring.
  - Deduplicates URLs via normalized canonicalization.

### 3.3 Documentation Retrieval Agent

- **Responsibility:** Fetch and cache raw content from discovered URLs.
- **Inputs:** Candidate URLs.
- **Outputs:** Cleaned text/markdown, HTTP metadata, fetch status, cache keys.
- **Key behaviors:**
  - Selects fetch strategy: `static_http` (httpx) for docs, `browser` (Playwright) for JS-heavy pages.
  - Respects `robots.txt` and per-domain rate limits.
  - Extracts main content using readability-lxml / BeautifulSoup / markdownify.
  - Stores raw + cleaned content in SQLite with TTL.
  - Falls back to cached content if live fetch fails.

### 3.4 Evidence Extraction Agent

- **Responsibility:** Convert retrieved documents into structured, schema-validated facts.
- **Inputs:** Cleaned documents, app schema.
- **Outputs:** `AppResearchResult` Pydantic object with per-field confidence.
- **Key behaviors:**
  - Uses LLM with constrained JSON schema output (OpenAI-compatible `response_format` or instructor).
  - Extracts: category, one-liner, auth methods, self-serve/gated, API type, coverage, MCP, SDK, blockers, docs URLs.
  - Cites exact source snippets and URLs for every extracted fact.
  - Marks `UNKNOWN` rather than hallucinating.
  - Runs multiple extraction passes with different prompts for difficult fields.

### 3.5 Verification Agent

- **Responsibility:** Cross-check extracted facts against independent sources.
- **Inputs:** Primary `AppResearchResult`, retrieved documents.
- **Outputs:** Verification report per field: `CONFIRMED`, `CONFLICT`, `UNVERIFIED`.
- **Key behaviors:**
  - Requires at least two independent sources for `CONFIRMED`.
  - Flags contradictions for human review.
  - Uses LLM to compare claim texts across sources.
  - Generates quote-level evidence snippets.

### 3.6 Fact Consistency Agent

- **Responsibility:** Resolve conflicts and merge multi-source evidence.
- **Inputs:** Verification report, raw facts.
- **Outputs:** Consolidated `AppResearchResult` with conflict annotations.
- **Key behaviors:**
  - Applies source hierarchy: official docs > API reference > GitHub README > blog/community.
  - When sources conflict, preserves all claims and downgrades confidence.
  - Never silently discards minority evidence.

### 3.7 Confidence Scoring Agent

- **Responsibility:** Assign per-field and per-app confidence scores.
- **Inputs:** Consolidated result, verification status, source quality.
- **Outputs:** `Confidence` enum (`HIGH`, `MEDIUM`, `LOW`) plus 0-1 score with reasoning.
- **Scoring rubric:**
  - **HIGH:** Confirmed by official docs or two+ independent authoritative sources, no conflicts, recent content.
  - **MEDIUM:** Single authoritative source or multiple weaker sources, minor ambiguity.
  - **LOW:** Sparse evidence, conflicting sources, inferred indirectly, stale content.

### 3.8 Insight Generation Agent

- **Responsibility:** Detect patterns, clusters, and strategic recommendations.
- **Inputs:** All `AppResearchResult` objects.
- **Outputs:** Insights: auth distribution, category/gating patterns, top blockers, easy wins, outreach targets, trend text.
- **Key behaviors:**
  - Uses deterministic aggregations (Pandas/Polars) + LLM narrative synthesis.
  - Identifies outliers and surprising findings.
  - Suggests priority tiering for toolkit development.

### 3.9 HTML Report Generator

- **Responsibility:** Produce the final interactive dashboard.
- **Inputs:** Research results, insights, verification sample, pipeline metadata.
- **Outputs:** Single self-contained HTML file with embedded JS/CSS.
- **Key behaviors:**
  - Dark mode, responsive, searchable table, collapsible evidence.
  - Mermaid architecture diagram, Chart.js visualizations.
  - Before/after verification metrics.
  - Evidence links open in new tabs.

---

## 4. State Machine

Each app moves through the following states, persisted in SQLite:

```
PENDING → QUEUED → SEARCHING → RETRIEVING → EXTRACTING → VERIFYING
    → CONSOLIDATING → SCORING → COMPLETED
                         ↓
                      FAILED (retryable / terminal)
                         ↓
                      MANUAL_REVIEW (on conflict / low confidence)
```

Transitions are logged with timestamp, retry count, and checkpoint ID.

---

## 5. Concurrency & Rate Limiting

- **Per-app concurrency:** Configurable (default 8 parallel apps).
- **Per-domain rate limiting:** Token-bucket limiter keyed by hostname (e.g., `developers.facebook.com` gets its own bucket).
- **LLM RPM/TPM limits:** Global async semaphore + token-budget window.
- **Browser pool:** Reused Playwright browser contexts with max 4 concurrent pages.
- **Retry policy:** Exponential backoff with jitter, max 3 retries for transient failures, terminal for 4xx content errors.

---

## 6. Storage Schema (SQLite)

### 6.1 Tables

- `apps`: input metadata and current state.
- `checkpoints`: full pipeline state snapshots for resume.
- `documents`: fetched URLs, raw content, cleaned text, fetch metadata, TTL.
- `facts`: extracted structured facts per app per field.
- `evidence`: quote-level citations linking facts to documents.
- `verifications`: cross-source verification outcomes.
- `confidence`: per-field confidence scores and reasoning.
- `insights`: generated insight records.
- `logs`: structured audit logs.
- `token_usage`: cost and token tracking per call.

### 6.2 Caching Strategy

- Search results cached for 7 days.
- Fetched documents cached for 14 days (with ETag/Last-Modified revalidation).
- LLM extractions cached by content hash + model + prompt version.

---

## 7. Data Models

Core Pydantic models (summary):

- `AppInput`: name, website, hints, category hint, priority.
- `SearchResult`: title, url, source_type, relevance_score.
- `Document`: url, content, cleaned_text, fetch_method, status.
- `AuthMethod`, `APITypes`, `SelfServeStatus`, `Confidence`: enums.
- `AppResearchResult`: full per-app structured output with evidence.
- `VerificationReport`: per-field verification status and conflicts.
- `InsightBlock`: headline, body, chart_hint, evidence_apps.
- `PipelineRun`: metadata, config, cost, timestamps, version.

---

## 8. Verification Strategy

### 8.1 Automated Verification

- **Source diversity:** Require >=2 distinct source types for high-confidence facts.
- **Quote grounding:** Every fact must include one or more direct quotes or URL anchors.
- **Schema validation:** Pydantic rejects malformed LLM outputs; failed outputs trigger retry.
- **Self-consistency:** Run extraction with N prompts; majority vote for ambiguous fields.
- **Hallucination guard:** LLM-as-judge compares extracted claim to raw source text.

### 8.2 Human Sampling

- Randomly sample 20 apps (20% of 100).
- Manual review against official docs.
- Measure per-field precision, recall, hallucination rate.
- Report before-verification and after-verification accuracy deltas.

---

## 9. Observability

- **Structured logging:** JSONL logs with correlation IDs (app_id, run_id, agent_name).
- **Cost tracking:** Per-app and aggregate LLM token/cost usage.
- **Metrics:** Success rate, retry rate, cache hit rate, rate-limit waits, per-domain fetch latency.
- **Tracing:** Optional OpenTelemetry spans across agent boundaries.

---

## 10. Reproducibility

- All random sampling uses seeded RNG.
- Model name, prompt versions, and config hash stored in `PipelineRun`.
- Lockfile via `uv` and `requirements.txt`.
- README documents exact run command and env variables.
- SQLite DB + JSONL artifacts committed as pipeline outputs (not source code).

---

## 11. Technology Stack

| Layer | Tool |
|---|---|
| Language | Python 3.12+ |
| Package manager | `uv` |
| Orchestration | LangGraph |
| HTTP | `httpx` |
| Browser | Playwright |
| Parsing | BeautifulSoup4, readability-lxml, markdownify |
| Search | Tavily / Serper.dev |
| LLM | OpenAI-compatible (GPT-4o / Claude via API) |
| Structured output | Pydantic + instructor |
| DB | SQLite (aiosqlite) |
| Dataframes | Polars |
| CLI | Typer |
| Optional API | FastAPI |
| Logging | structlog |
| HTML | Jinja2 + Chart.js + Mermaid.js |

---

## 12. Failure Modes & Mitigations

| Failure | Mitigation |
|---|---|
| Search returns no official docs | Escalate to manual review; mark as low confidence. |
| Docs require JS rendering | Switch to Playwright fetch path. |
| LLM outputs invalid JSON | Retry with stricter schema + error feedback. |
| Sources conflict | Preserve all claims, downgrade confidence, annotate conflict. |
| Rate limit hit | Token bucket + exponential backoff + cache fallback. |
| Crash mid-run | SQLite checkpoint + resume on restart. |
| Hallucinated evidence | Quote grounding + LLM-as-judge verification. |

---

## 13. Non-Goals (Out of Scope for v0.1)

- Real-time streaming UI.
- Multi-user concurrency / auth.
- Persistent cloud deployment.
- Automatic toolkit code generation.
- OAuth flow execution (we only research, do not obtain credentials).

---

## 14. Open Questions

1. Which search provider do you prefer? (Tavily has higher quality for dev docs; Serper is cheaper.)
2. Which LLM provider should be primary? (GPT-4o is cost-effective; Claude 3.5/3.7 Sonnet is stronger at reasoning.)
3. Do you want a FastAPI service, or is Typer CLI sufficient for the deliverable?
4. Should we commit the resulting SQLite/JSONL/CSV/HTML to the repo, or keep them in `.gitignore`?
5. Do you want me to include a `docker-compose.yml` for reproducibility?

---

## 15. Next Steps (Pending Your Approval)

1. Approve this architecture or request changes.
2. I will generate the repository folder structure and `pyproject.toml`.
3. Then implement each module iteratively: storage, models, agents, retrieval, verification, report generator.
4. Finally run the pipeline on the 100 apps, verify a sample, and produce the HTML report.
