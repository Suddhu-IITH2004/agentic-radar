# 🏗️ CTIE Architecture — Complete Technical Guide

**Composio Toolkit Intelligence Engine (CTIE) — Architectural Deep Dive**

> This document explains how CTIE works internally. If you're interested in debugging, extending, or understanding the system design, this is your guide.

---

## Table of Contents

1. [System Purpose](#1-system-purpose)
2. [High-Level Architecture](#2-high-level-architecture)
3. [The Agent Pipeline](#3-the-agent-pipeline)
4. [Data Flow & State Machine](#4-data-flow--state-machine)
5. [Crash Recovery & Resume Logic](#5-crash-recovery--resume-logic)
6. [Concurrency & Rate Limiting](#6-concurrency--rate-limiting)
7. [Database Schema](#7-database-schema)
8. [Data Models](#8-data-models)
9. [Verification Strategy](#9-verification-strategy)
10. [LLM Providers & Fallbacks](#10-llm-providers--fallbacks)
11. [Search & Document Retrieval](#11-search--document-retrieval)
12. [Failure Modes & Recovery](#12-failure-modes--recovery)
13. [Technology Stack](#13-technology-stack)
14. [How to Extend & Debug](#14-how-to-extend--debug)
15. [Performance & Scalability](#15-performance--scalability)

---

## 1. System Purpose

CTIE is an **autonomous research pipeline** that evaluates 100+ SaaS applications to determine:

✅ **Composio Toolkit Readiness** — Can we build a Composio toolkit for this app?  
✅ **Authentication & Access** — How do developers authenticate? Is access self-serve or gated?  
✅ **API Coverage** — What's the API surface? REST, GraphQL, gRPC, or hybrid?  
✅ **Existing Support** — Does an MCP server, SDK, or Composio toolkit already exist?  
✅ **Blockers & Risks** — What might prevent toolkit development?  
✅ **Confidence Levels** — How certain are we about each finding?  

The pipeline must:
- 🤖 Run **autonomously** without human intervention
- 🔍 **Verify findings** across multiple sources
- 💾 **Resume from crashes** without re-researching completed apps
- 📊 **Generate actionable reports** with visualizations and evidence
- 🎯 **Be auditable** — every claim has a source URL and evidence snippet

---

## 2. High-Level Architecture

### 2.1 Layered Design

```
┌──────────────────────────────────────────────────────────────────┐
│  🎮 CLI Interface                                                 │
│  (Typer commands: run, resume, report, export-db)                │
└───────────────────────┬──────────────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────────────┐
│  🎛️  Orchestration (LangGraph)                                    │
│  State machine, checkpointing, resume logic                       │
└───────────────────────┬──────────────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────────────┐
│  🤖 Agent Layer (Specialist Nodes)                                │
│                                                                    │
│  Coordinator → Research → Fetcher → Extractor → Verifier         │
│             → Scorer → Enricher → Insights → Reporter             │
└───────────────────────┬──────────────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────────────┐
│  🛠️  Tool Layer                                                    │
│                                                                    │
│  Search:  Composio SDK → DuckDuckGo → Google PSE (fallback)       │
│  Fetch:   Composio SDK → httpx (static) → Playwright (JS)         │
│  Enrich:  Composio Toolkit Catalog lookup                         │
└───────────────────────┬──────────────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────────────┐
│  🧠 LLM Layer                                                      │
│                                                                    │
│  Primary:  Azure OpenAI (gpt-4o)                                  │
│  Fallback: AWS Bedrock (Claude 3.5 Sonnet)                        │
└───────────────────────┬──────────────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────────────┐
│  💾 Storage Layer                                                  │
│                                                                    │
│  SQLite (state, cache, evidence) + JSONL logs + HTML output       │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 Data Flow

```
Input (apps.json)
        ↓
   🎯 Coordinator picks app
        ↓
   🔍 Research Agent → searches web for docs URLs
        ↓ (cache URLs)
   📥 Fetcher Agent → downloads & cleans doc content
        ↓ (cache documents)
   🧠 Extraction Agent → LLM extracts structured facts
        ↓ (cache result)
   ✓ Verification Agent → cross-verifies facts
        ↓
   ⭐ Scoring Agent → assigns confidence scores
        ↓
   📚 Enrichment Agent → checks Composio toolkit catalog
        ↓
   💡 Insights Agent → detects patterns across all apps
        ↓
   📊 Report Generator → creates interactive HTML
        ↓
Output (report.html + results.json)
```

---

## 3. The Agent Pipeline

Each agent is a standalone Python class that processes app data and transitions it to the next state. Agents are designed to be:
- **Async-first** for concurrency
- **Deterministic** for reproducibility
- **Fault-tolerant** with retry logic
- **Observable** with structured logging

### 3.1 🎯 Coordinator Agent

**Purpose:** Entry point. Distributes work, tracks progress, enforces budgets.

**Responsibilities:**
- Load app list from `data/apps.json`
- Check SQLite for crashed/incomplete apps (resume logic)
- Enqueue apps that need processing
- Track global token/cost budget
- Handle graceful shutdown and error aggregation

**Key Flow:**
```python
1. Load apps + config
2. Query SQLite: app_status != 'COMPLETED'
3. Enqueue non-completed apps
4. For each app:
   - Dispatch to Research Agent
   - Wait for result
   - Write final status to SQLite
5. Report aggregate statistics
```

**Configuration Options:**
- `CTIE_MAX_RETRIES`: max retries per app (default: 3)
- `CTIE_CONCURRENCY`: parallel apps (default: 5)
- `CTIE_FORCE_FRESH`: ignore SQLite state (default: false)
- `CTIE_TOKEN_BUDGET`: max tokens for entire run (default: 500K)
- `CTIE_COST_BUDGET`: max cost in USD (default: $50)

---

### 3.2 🔍 Research Agent

**Purpose:** Find candidate documentation URLs via web search.

**Inputs:**
- App name, website, category hint
- Any previous search results (to avoid re-searching)

**Outputs:**
- Ranked list of URLs: `[SearchResult(...), ...]`
- Source type tags: `official_docs`, `api_ref`, `github`, `blog`, `community`
- Relevance scores (0-1)

**How It Works:**

```python
# 1. Generate search queries
queries = [
    "{app} API authentication",
    "{app} developer documentation",
    "{app} MCP server",
    "{app} REST API",
    "site:{app_domain} API reference"
]

# 2. Execute searches
for query in queries:
    results = search_provider.search(query)  # Composio → DuckDuckGo → Google PSE
    
# 3. Filter spam + deduplicate
safe_urls = filter_spam(results)  # Remove affiliate, SEO spam
unique_urls = deduplicate(safe_urls)

# 4. Rank by source type
ranked = rank_by_source_type(unique_urls)
# official_docs > api_ref > github > blog > community

# 5. Cache & return
cache_search_results(ranked)
return ranked[:N]  # Top N URLs
```

**Search Providers (Fallback Chain):**

| Provider | Free Tier | Auth Required | Speed | Quality |
|----------|-----------|---------------|-------|---------|
| **Composio Search** | ✅ 20K/month | `COMPOSIO_API_KEY` | Fast | Excellent |
| **DuckDuckGo** | ✅ Unlimited | None | Medium | Good |
| **Google PSE** | ✅ 100/day | `GOOGLE_PSE_API_KEY` | Fast | Excellent |

If Composio fails → fall back to DuckDuckGo. If DuckDuckGo rate-limits → try Google PSE.

---

### 3.3 📥 Fetcher Agent

**Purpose:** Download, parse, and clean documentation content from URLs.

**Inputs:**
- List of URLs from Research Agent
- Cached documents (if resume)

**Outputs:**
- Cleaned text/markdown content
- HTTP status, headers, fetch method
- Cache metadata (timestamp, TTL)

**How It Works:**

```python
for url in urls:
    # 1. Check cache first
    cached = db.get_cached_document(url)
    if cached and not expired(cached):
        documents.append(cached)
        continue
    
    # 2. Try Composio fetch (fastest)
    if COMPOSIO_API_KEY:
        content = composio.fetch_url_content(url)
        if content and len(content) > MIN_LENGTH:
            documents.append(clean_and_parse(content))
            continue
    
    # 3. Fallback to httpx (static HTML only)
    response = httpx.get(url, timeout=10)
    content = response.text
    
    # 4. If mostly JavaScript, escalate to Playwright
    if is_js_heavy(content):
        content = playwright.render(url)
    
    # 5. Clean & extract main text
    cleaned = clean_html(content)
    markdown = convert_to_markdown(cleaned)
    
    # 6. Cache & store
    db.cache_document(url, markdown, "httpx" or "playwright")
    documents.append(Document(...))
```

**Fetch Strategy:**
- **Fast path:** Composio Fetch URL Content (pre-rendered content)
- **Static path:** `httpx` with user agent rotation (handles most pages)
- **Dynamic path:** Playwright (for JS-heavy sites like Single Page Apps)
- **Fallback:** Return cached version if live fetch fails

**Content Cleaning:**
- Remove HTML boilerplate (nav, footer, ads)
- Extract main article/docs content
- Convert HTML to markdown for LLM parsing
- Skip binary files and pages >2 MB
- Extract page title, metadata, publish date

---

### 3.4 🧠 Extraction Agent

**Purpose:** Convert documents into structured, schema-validated facts using the LLM.

**Inputs:**
- Cleaned documents (from Fetcher)
- App metadata
- Extraction schema (Pydantic model)

**Outputs:**
- `AppResearchResult` with all fields filled or marked `UNKNOWN`
- Per-field evidence (URL + quote snippet)
- Extraction confidence (before verification)

**How It Works:**

```python
system_prompt = """
You are an expert API researcher. Extract facts from documentation.
For each field, return:
- value: the extracted fact
- confidence: HIGH/MEDIUM/LOW
- evidence_url: where you found it
- quote: direct quote from the source
If not found, return null or UNKNOWN, not a guess.
"""

user_prompt = f"""
Research app: {app.name}
Website: {app.website}

Documentation (cleaned from multiple pages):
{documents_text}

Extract: {SCHEMA}
Return valid JSON.
"""

# Call LLM with constrained output
response = llm.generate(
    system_prompt,
    user_prompt,
    response_format=AppResearchResult,  # Pydantic schema
    temperature=0.3  # Low temp for factual extraction
)

result = AppResearchResult.model_validate(response)
```

**Schema (AppResearchResult):**
```python
class AppResearchResult(BaseModel):
    app_id: str
    app_name: str
    one_liner: str  # e.g., "Payment processing SaaS"
    category: str  # e.g., "Payment"
    
    # Auth & Access
    auth_methods: list[str]  # e.g., ["OAuth 2.0", "API Key"]
    self_serve_access: Enum  # SELF_SERVE | GATED | UNKNOWN
    api_type: str  # "REST", "GraphQL", "gRPC", "Hybrid"
    api_coverage: str  # "Comprehensive", "Partial", "Limited"
    
    # Existing Support
    mcp_server_exists: bool
    sdk_exists: bool
    composio_toolkit_exists: bool
    
    # Blockers
    blockers: list[str]  # Why we can't build a toolkit
    
    # Evidence
    evidence_urls: list[str]  # URLs where facts came from
    error: str | None  # If extraction failed
```

**Multi-Pass Extraction:**
- First pass with general prompt
- If key fields are UNKNOWN, second pass with targeted prompt for that field
- Majority voting on ambiguous fields

---

### 3.5 ✓ Verification Agent

**Purpose:** Cross-check extracted facts against independent sources (fact-checking).

**Inputs:**
- Extracted result from Extraction Agent
- All fetched documents (raw)

**Outputs:**
- Verification report: per field status (`CONFIRMED`, `CONFLICT`, `UNVERIFIED`)
- Conflicting claims preserved with quotes
- Verification confidence

**How It Works:**

```python
for field in result.fields:
    fact = result[field]
    
    # Find mentions of this fact in documents
    quotes = find_quotes_in_documents(fact, documents)
    
    # Count independent sources
    unique_sources = count_unique_urls(quotes)
    
    if unique_sources >= 2:
        # Multiple sources agree
        status = "CONFIRMED"
        confidence = "HIGH"
    elif unique_sources == 1:
        # Only one source mentioned it
        status = "UNVERIFIED"
        confidence = "MEDIUM"
    else:
        # Not found in any document
        status = "UNVERIFIED"
        confidence = "LOW"
    
    # Check for contradictions
    contradictions = find_contradicting_claims(fact, documents)
    if contradictions:
        status = "CONFLICT"
        # Store all conflicting claims with quotes
        
    verification_report[field] = {
        "status": status,
        "confidence": confidence,
        "source_count": unique_sources,
        "evidence_quotes": quotes,
        "contradictions": contradictions
    }
```

**Verification Rules:**
- **CONFIRMED:** ≥2 independent authoritative sources agree, no contradictions, recent content
- **UNVERIFIED:** 1 source or sparse evidence, no contradictions
- **CONFLICT:** Multiple sources disagree; preserve all claims

---

### 3.6 ⭐ Scoring Agent

**Purpose:** Assign per-field and per-app confidence scores.

**Inputs:**
- Verification report
- Source quality metrics
- Document freshness

**Outputs:**
- `Confidence` enum: `HIGH`, `MEDIUM`, `LOW`
- Numerical score (0-1)
- Reasoning text

**Scoring Rubric:**

```
HIGH (0.8-1.0):
  - CONFIRMED by 2+ official sources
  - Recent content (< 1 year)
  - No conflicting claims
  - From official docs/API reference

MEDIUM (0.5-0.8):
  - CONFIRMED by 1 authoritative source OR 2+ weaker sources
  - Content is current
  - Minor ambiguity but resolvable
  - From blog/community if consistent with other signals

LOW (0-0.5):
  - UNVERIFIED or only community sources
  - Conflicting claims exist
  - Stale content (> 2 years)
  - Inferred indirectly, not explicitly stated
```

**Implementation:**
```python
score_components = {
    "verification_status": {"CONFIRMED": 1.0, "UNVERIFIED": 0.5, "CONFLICT": 0.2}[status],
    "source_count": min(unique_sources / 2, 1.0),  # 2+ sources = 1.0
    "content_freshness": 1.0 if age_days < 365 else 0.5 if age_days < 730 else 0.2,
    "source_authority": 1.0 if from_official else 0.7 if from_api_ref else 0.5
}

confidence_score = mean(score_components.values())
confidence_level = "HIGH" if score > 0.75 else "MEDIUM" if score > 0.5 else "LOW"
```

---

### 3.7 📚 Enrichment Agent

**Purpose:** Cross-reference the Composio toolkit catalog to check if support already exists.

**Inputs:**
- App name and metadata
- Extracted auth & API info

**Outputs:**
- `composio_support`: Enum (`SUPPORTED`, `UNSUPPORTED`, `UNKNOWN`)
- `composio_toolkit_name`: Name of the toolkit if found
- `composio_auth_schemes`: Auth methods supported by toolkit
- `composio_tool_count`: Number of exposed tools
- `composio_toolkit_url`: Link to toolkit documentation

**How It Works:**

```python
# Only runs if COMPOSIO_API_KEY is set
if not COMPOSIO_API_KEY:
    return {"composio_support": "UNKNOWN"}

# Query Composio catalog
toolkits = composio.toolkits.list()

# Search for matching toolkit
for toolkit in toolkits:
    if similarity(app.name, toolkit.name) > 0.8:
        # Found a matching toolkit
        toolkit_details = composio.toolkits.get(toolkit.id)
        return {
            "composio_support": "SUPPORTED",
            "toolkit_name": toolkit.name,
            "auth_schemes": toolkit_details.auth_schemes,
            "tool_count": len(toolkit_details.tools),
            "toolkit_url": toolkit_details.docs_url
        }

# Not found
return {
    "composio_support": "UNSUPPORTED",
    "toolkit_name": None,
    "auth_schemes": [],
    "tool_count": 0
}
```

**Why This Matters:**
- Validates our extracted auth methods (Composio toolkit reveals what's actually supported)
- Avoids duplicating existing work
- Demonstrates deep Composio ecosystem knowledge
- Free tier allows ~20K toolkit calls/month

---

### 3.8 💡 Insights Agent

**Purpose:** Aggregate findings across all apps and detect patterns, clusters, recommendations.

**Inputs:**
- All `AppResearchResult` objects (100 apps)
- Verification & scoring reports

**Outputs:**
- Insight blocks: headlines, evidence, visualizations
- Auth distribution charts
- Category breakdowns
- Blocker frequency ranking
- Recommendation tiers

**Sample Insights Generated:**

```
🔐 Authentication Landscape:
  - 68% use OAuth 2.0 (industry standard)
  - 45% also accept API keys
  - 12% require enterprise contracts
  
🚧 Top Blockers:
  1. Rate limiting (27 apps) — need concurrency strategies
  2. Webhook-only events (15 apps) — harder to poll
  3. IP allowlisting (11 apps) — need public IP
  
🎯 Easy Wins (high API coverage + self-serve access):
  - Stripe, GitHub, Slack, OpenAI, Google Workspace
  
⚠️ High-Risk Integrations:
  - Enterprise-only APIs (Salesforce, SAP, Oracle)
  - Rapidly changing SDKs (new startups)
```

---

### 3.9 📊 Report Generator

**Purpose:** Produce the final interactive HTML dashboard.

**Inputs:**
- All app results
- Insights
- Verification sample
- Pipeline metadata (config, run time, cost)

**Outputs:**
- Single self-contained `report.html` file
- Embedded JavaScript, CSS, JSON data
- Responsive design, dark mode

**Report Sections:**

1. **Dashboard Summary**
   - Key metrics: total apps, completion %, avg confidence
   - Aggregate stats: auth types, API types, blockers

2. **Interactive Results Table**
   - Sortable, filterable columns
   - Search by app name, category, blockers
   - Click row to expand evidence

3. **Charts & Visualizations**
   - Auth method distribution (pie chart)
   - API type breakdown (bar chart)
   - Self-serve vs gated (donut chart)
   - Blocker frequency (horizontal bar)
   - Confidence distribution (histogram)

4. **Evidence Panel**
   - Source URLs and direct quotes
   - Verification status per field
   - Conflicting claims (if any)

5. **Metadata Section**
   - Run timestamp, duration, cost
   - Model used, prompt version
   - 20-app sample verification results

---

## 4. Data Flow & State Machine

### 4.1 Per-App State Transitions

Each app moves through the following states, with **every transition persisted to SQLite**:

```
PENDING
    ↓
QUEUED (in coordinator's queue)
    ↓
SEARCHING (web search in progress)
    ↓ (cache URLs)
FETCHING (downloading documents)
    ↓ (cache documents)
EXTRACTING (LLM extraction in progress)
    ↓ (cache structured result)
VERIFYING (cross-checking facts)
    ↓
SCORING (confidence assignment)
    ↓
ENRICHING (Composio catalog lookup)
    ↓
COMPLETED ✅
         (or)
FAILED ❌ (retryable until CTIE_MAX_RETRIES)
       ↓
FAILED_TERMINAL (permanently failed, skipped on resume)
```

### 4.2 State Transitions in Code

```python
class AppPipelineState(TypedDict):
    app: AppInput
    run_id: str
    search_results: list[SearchResult]
    documents: list[Document]
    result: AppResearchResult | None
    status: AppStatus  # PENDING, QUEUED, SEARCHING, ...
    error: str | None
    retry_count: int

# State transitions
async def research_agent(state: AppPipelineState) -> AppPipelineState:
    state["status"] = "SEARCHING"
    db.write_state(state)  # ← Persist immediately!
    
    try:
        state["search_results"] = await search(state["app"])
        state["status"] = "FETCHING"
        db.write_state(state)
    except Exception as e:
        state["error"] = str(e)
        state["status"] = "FAILED"
        state["retry_count"] += 1
        db.write_state(state)
        raise
```

### 4.3 Resume Semantics

On startup, the Coordinator checks SQLite:

```python
# On resume
incomplete_apps = db.query("SELECT * FROM apps WHERE status != 'COMPLETED'")

for app in incomplete_apps:
    if app.status == "FAILED" and app.retry_count >= MAX_RETRIES:
        # Skip terminal failures
        continue
    elif app.status == "FAILED":
        # Retryable: start over from QUEUED
        app.status = "QUEUED"
        app.retry_count += 1
    elif app.status in ("SEARCHING", "FETCHING"):
        # Check if we have cached results
        if app.search_results:
            # Skip to next step
            app.status = "EXTRACTING"
        else:
            # Restart from this step
            app.status = "SEARCHING"
    # ... continue for other states
    
    db.write_state(app)
    enqueue(app)
```

**Guarantee:** A crash at any point can be resumed without repeating work for completed apps.

---

## 5. Crash Recovery & Resume Logic

### 5.1 Checkpoint Strategy

- **Granularity:** Per-app, per-step
- **Trigger:** After every state transition
- **Storage:** SQLite (local, not committed)
- **Durability:** Fsync on every write (no data loss)

### 5.2 Resume After Crash

```bash
# Pipeline crashes after researching 30 apps
^C

# Resume: only reprocesses 70 incomplete apps
uv run ctie run --resume

# All 30 completed apps are reused from cache
# Only 70 continue from where they left off
```

### 5.3 Fresh Run (Ignoring Previous Results)

```bash
# Start over, ignoring SQLite
uv run ctie run --fresh

# Or set env var
CTIE_FORCE_FRESH=true uv run ctie run
```

---

## 6. Concurrency & Rate Limiting

### 6.1 Per-App Concurrency

Default: 5 apps processed in parallel.

```python
# Coordinator uses asyncio.gather with semaphore
semaphore = asyncio.Semaphore(5)

async def process_app(app):
    async with semaphore:
        await research_pipeline(app)

tasks = [process_app(app) for app in apps]
await asyncio.gather(*tasks)
```

### 6.2 Per-Domain Rate Limiting

Each domain (e.g., `developers.stripe.com`) has a token bucket:

```python
rate_limits = {
    "stripe.com": TokenBucket(rate=2/sec, burst=4),
    "github.com": TokenBucket(rate=3/sec, burst=8),
    ...
}

# Before fetching URL
domain = urlparse(url).domain
await rate_limits[domain].acquire()
response = await httpx.get(url)
```

### 6.3 LLM Concurrency

Global semaphore respecting Azure OpenAI RPM (requests per minute):

```python
# Azure OpenAI: 300 RPM on free tier
llm_semaphore = asyncio.Semaphore(5)  # ~5 concurrent requests

async def llm_call(prompt):
    async with llm_semaphore:
        return await azure_openai.complete(prompt)
```

### 6.4 Browser Pool

Playwright browser context reused, max 3 concurrent pages:

```python
browser = await playwright.chromium.launch()
context = await browser.new_context()
page_semaphore = asyncio.Semaphore(3)

async def render_page(url):
    async with page_semaphore:
        page = await context.new_page()
        await page.goto(url)
        # ... render
        await page.close()
```

### 6.5 Retry Policy

Exponential backoff with jitter:

```python
async def retry_with_backoff(fn, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await fn()
        except TransientError as e:
            wait_time = 2 ** attempt + random(0, 2 ** attempt)
            await asyncio.sleep(wait_time)
        except TerminalError:
            raise  # Don't retry 4xx errors
    raise
```

### 6.6 LLM Fallback Chain

If Azure OpenAI fails:

```python
async def llm_call_with_fallback(prompt):
    try:
        # Primary
        return await azure_openai.complete(prompt)
    except RateLimitError:
        logger.warn("Azure rate limit, trying Bedrock")
        # Fallback
        return await bedrock.complete(prompt)
    except Exception as e:
        logger.error(f"Both LLM providers failed: {e}")
        raise
```

---

## 7. Database Schema

### 7.1 SQLite Tables

```sql
-- Input metadata and current state
CREATE TABLE apps (
    id TEXT PRIMARY KEY,
    name TEXT,
    website TEXT,
    category_hint TEXT,
    status TEXT,  -- PENDING, QUEUED, SEARCHING, FETCHING, ...
    result_json JSON,  -- Full AppResearchResult
    error TEXT,
    retry_count INTEGER,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- Fetched documents (cached)
CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    url TEXT UNIQUE,
    app_id TEXT,
    content TEXT,  -- Raw HTML
    cleaned_text TEXT,  -- Markdown
    fetch_method TEXT,  -- "composio", "httpx", "playwright"
    status TEXT,  -- "success", "failed"
    fetch_timestamp TIMESTAMP,
    ttl_hours INTEGER DEFAULT 336,  -- 14 days
    FOREIGN KEY(app_id) REFERENCES apps(id)
);

-- Search results (cached)
CREATE TABLE search_cache (
    id TEXT PRIMARY KEY,
    app_id TEXT,
    query TEXT,
    results JSON,  -- List of SearchResult
    cached_at TIMESTAMP,
    ttl_hours INTEGER DEFAULT 168,  -- 7 days
    FOREIGN KEY(app_id) REFERENCES apps(id)
);

-- Verification evidence (for audit)
CREATE TABLE evidence (
    id TEXT PRIMARY KEY,
    app_id TEXT,
    field TEXT,  -- e.g., "auth_methods"
    claim TEXT,
    url TEXT,
    quote TEXT,
    confidence TEXT,  -- HIGH, MEDIUM, LOW
    FOREIGN KEY(app_id) REFERENCES apps(id)
);

-- Run metadata
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    config_hash TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    llm_provider TEXT,
    total_apps INTEGER,
    successful_apps INTEGER,
    failed_apps INTEGER,
    total_tokens INTEGER,
    total_cost_usd REAL,
    avg_confidence REAL
);

-- Structured logs (rotated, not committed)
CREATE TABLE logs (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP,
    level TEXT,  -- INFO, WARN, ERROR
    app_id TEXT,
    agent TEXT,  -- "research", "extractor", "verifier", ...
    message TEXT,
    metadata JSON  -- { "tokens": 500, "latency_ms": 1234, ... }
);
```

### 7.2 Caching Strategy

| Data | TTL | How It's Used |
|------|-----|---------------|
| Search results | 7 days | Skip re-searching if cached |
| Fetched documents | 14 days | Skip re-fetching if cached |
| LLM extractions | Forever | Reuse extraction if content hash matches |
| Per-app state | Forever | Resume from checkpoint |

---

## 8. Data Models

Core Pydantic models (schema):

### 8.1 AppInput
```python
class AppInput(BaseModel):
    id: str
    name: str
    website: str
    category_hint: str | None = None
    priority: int = 0  # For weighted scheduling
```

### 8.2 SearchResult
```python
class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str | None
    source_type: Literal[
        "official_docs", "api_ref", "github", "blog", "community"
    ]
    relevance_score: float  # 0-1
```

### 8.3 Document
```python
class Document(BaseModel):
    url: str
    content: str  # Raw HTML
    cleaned_text: str  # Markdown
    fetch_method: Literal["composio", "httpx", "playwright"]
    status: Literal["success", "failed"]
    fetch_timestamp: datetime
    content_hash: str  # SHA256 of content
```

### 8.4 AppResearchResult (Output Schema)
```python
class AppResearchResult(BaseModel):
    app_id: str
    app_name: str
    one_liner: str
    category: str
    
    # Authentication
    auth_methods: list[str]  # ["OAuth 2.0", "API Key", "JWT"]
    self_serve_access: Literal["SELF_SERVE", "GATED", "UNKNOWN"]
    
    # API
    api_type: str  # "REST", "GraphQL", "gRPC", "Hybrid"
    api_coverage: str  # "Comprehensive", "Partial", "Limited"
    
    # Existing support
    mcp_server_exists: bool
    sdk_exists: bool
    composio_toolkit_exists: bool
    
    # Blockers
    blockers: list[str]
    
    # Evidence
    evidence_urls: list[str]
    
    # Confidence (added after verification/scoring)
    field_confidences: dict[str, Literal["HIGH", "MEDIUM", "LOW"]]
    overall_confidence: float  # 0-1
    
    error: str | None = None
```

---

## 9. Verification Strategy

### 9.1 Multi-Source Verification

For each extracted fact:

```python
def verify_fact(fact, all_documents):
    # Find quotes supporting this fact
    supporting_quotes = []
    for doc in all_documents:
        quotes = find_matching_quotes(fact, doc.cleaned_text)
        if quotes:
            supporting_quotes.append((doc.url, quotes))
    
    # Determine verification status
    unique_sources = len(set(url for url, _ in supporting_quotes))
    
    if unique_sources >= 2:
        return VerificationStatus.CONFIRMED, "HIGH"
    elif unique_sources == 1:
        return VerificationStatus.UNVERIFIED, "MEDIUM"
    else:
        return VerificationStatus.UNVERIFIED, "LOW"
```

### 9.2 Hallucination Detection

```python
def detect_hallucination(extracted_claim, source_text):
    """Check if claim is grounded in source_text."""
    
    # Exact match
    if extracted_claim in source_text:
        return False  # Not hallucinated
    
    # Fuzzy match
    if fuzz.ratio(extracted_claim, source_text) > 0.8:
        return False
    
    # LLM judge
    is_grounded = llm_judge.judge(
        f"Claim: {extracted_claim}\nSource: {source_text}\n" +
        "Is the claim explicitly stated in the source?"
    )
    
    return not is_grounded  # Return True if hallucinated
```

### 9.3 Human Verification Sample

- **Sample size:** 20 apps (20% of 100)
- **Method:** Random stratified sampling (by category)
- **Manual review:** Check top 5 results against official docs
- **Metrics:** Per-field precision, recall, F1-score
- **Before/after:** Report accuracy before + after verification

---

## 10. LLM Providers & Fallbacks

### 10.1 Azure OpenAI (Primary)

```python
class AzureOpenAIClient(LLMClient):
    async def generate(self, messages, response_format=None):
        response = await client.chat.completions.create(
            model=self.deployment_name,  # "gpt-4o"
            messages=messages,
            response_format=response_format,  # Pydantic JSON mode
            temperature=0.3  # Low temp for factual extraction
        )
        return response.choices[0].message.content
```

**Config:**
```env
AZURE_OPENAI_API_KEY=sk-...
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-08-01-preview
```

### 10.2 AWS Bedrock (Fallback)

```python
class BedrockClient(LLMClient):
    async def generate(self, messages):
        response = await bedrock_client.invoke_model(
            modelId="anthropic.claude-3-5-sonnet-20241022-v2:0",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-06-01",
                "max_tokens": 2048,
                "messages": messages,
            })
        )
        return response["content"][0]["text"]
```

**Config:**
```env
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
```

### 10.3 Fallback Strategy

```python
async def llm_call_with_fallback(prompt, response_format):
    try:
        return await azure_openai.generate(prompt, response_format)
    except (RateLimitError, AuthenticationError):
        logger.warn("Azure failed, trying Bedrock")
        return await bedrock.generate(prompt)
    except Exception as e:
        logger.error(f"All LLM providers failed: {e}")
        raise
```

**When fallback triggers:**
- Rate limit (429)
- Authentication failure (401)
- Temporary outage (5xx)
- Model timeout (>60s)

---

## 11. Search & Document Retrieval

### 11.1 Search Provider Chain

```python
async def search(query: str):
    # Try Composio first
    if COMPOSIO_API_KEY:
        try:
            results = await composio_search.web_search(query)
            logger.info(f"Search via Composio: {len(results)} results")
            return results
        except Exception as e:
            logger.warn(f"Composio search failed: {e}")
    
    # Fallback to DuckDuckGo
    try:
        results = await duckduckgo_search.search(query)
        logger.info(f"Search via DuckDuckGo: {len(results)} results")
        return results
    except Exception as e:
        logger.warn(f"DuckDuckGo failed: {e}")
    
    # Fallback to Google PSE (limited, 100/day)
    if GOOGLE_PSE_API_KEY:
        try:
            results = await google_pse.search(query, num=10)
            logger.info(f"Search via Google PSE: {len(results)} results")
            return results
        except Exception as e:
            logger.error(f"All search providers failed: {e}")
            raise
```

### 11.2 Document Fetch Chain

```python
async def fetch_url(url: str):
    # Try Composio Fetch URL Content first
    if COMPOSIO_API_KEY:
        try:
            content = await composio.fetch_url_content(url)
            if content and len(content) > MIN_LENGTH:
                logger.info(f"Fetched via Composio: {url}")
                return content, "composio"
        except Exception as e:
            logger.warn(f"Composio fetch failed: {e}")
    
    # Try httpx (static HTML)
    try:
        response = await httpx.get(url, timeout=10)
        if response.status_code == 200 and len(response.text) > MIN_LENGTH:
            logger.info(f"Fetched via httpx: {url}")
            return response.text, "httpx"
    except Exception as e:
        logger.warn(f"httpx failed: {e}")
    
    # Escalate to Playwright (JS rendering)
    try:
        content = await playwright.render(url)
        if len(content) > MIN_LENGTH:
            logger.info(f"Fetched via Playwright: {url}")
            return content, "playwright"
    except Exception as e:
        logger.error(f"All fetch methods failed: {e}")
        raise
```

---

## 12. Failure Modes & Recovery

### 12.1 Search Failures

| Failure | Cause | Mitigation |
|---------|-------|-----------|
| No results found | App too niche or new | Mark as low confidence, manual review flag |
| All results irrelevant | SEO spam inflating results | Improve domain allowlist, manual sampling |
| Search provider down | DuckDuckGo/Composio outage | Fall back to Google PSE or cache |

### 12.2 Document Retrieval Failures

| Failure | Cause | Mitigation |
|---------|-------|-----------|
| 404 or 403 | URL changed or deprecated | Log as stale content, downgrade confidence |
| Timeout | Slow or down host | Retry with longer timeout, use cached version |
| Cloudflare/bot detection | Anti-scraping measure | Use Playwright with browser fingerprint |
| Page is mostly JS | SPA with no server rendering | Escalate to Playwright, wait for JS load |

### 12.3 LLM Failures

| Failure | Cause | Mitigation |
|---------|-------|-----------|
| Rate limit (429) | Quota exhausted | Exponential backoff, fall back to Bedrock |
| Invalid JSON | LLM hallucination in JSON | Retry with stricter schema, error feedback |
| Timeout | Model slow or hung | Retry, reduce context window |
| Token limit | Too much source text | Truncate documents, summarize, re-extract |

### 12.4 Database Failures

| Failure | Cause | Mitigation |
|---------|-------|-----------|
| Database locked | Concurrent writes | Use Semaphore to serialize writes |
| Disk full | Output files too large | Compress, archive, or skip large documents |
| Corruption | Ungraceful shutdown | PRAGMA integrity_check, VACUUM, restore backup |

---

## 13. Technology Stack

### 13.1 Core

| Component | Technology | Version | Why |
|-----------|-----------|---------|-----|
| Language | Python | 3.12+ | Async-first, type hints, ecosystem |
| Package manager | `uv` | latest | Fast, deterministic, lockfile support |
| Async | asyncio | built-in | Standard for Python concurrency |

### 13.2 Orchestration & State

| Component | Technology | Why |
|-----------|-----------|-----|
| Workflow | LangGraph | State machine, checkpoint/resume, agent topology |
| Storage | SQLite + aiosqlite | Local, serverless, no auth, async support |
| State | Pydantic | Schema validation, JSON serialization |

### 13.3 Data Fetching

| Component | Technology | Why |
|-----------|-----------|-----|
| HTTP (sync) | httpx[http2] | Modern, HTTP/2, async, timeouts |
| Browser | Playwright | Headless Chromium, JS rendering, screenshots |
| Parsing | BeautifulSoup4, lxml | HTML extraction, fast |
| Markdown | markdownify | HTML to Markdown for LLM parsing |
| Content | readability-lxml | Extract main article text |

### 13.4 Search

| Component | Technology | Free Tier | Cost |
|-----------|-----------|-----------|------|
| Primary | Composio SDK | ✅ 20K calls/month | $0 |
| Fallback 1 | duckduckgo-search | ✅ Unlimited | $0 |
| Fallback 2 | Google PSE | ✅ 100 queries/day | $0 (free tier only) |

### 13.5 LLM

| Component | Technology | Free Tier | Cost |
|-----------|-----------|-----------|------|
| Primary | Azure OpenAI | ❌ Free tier limited | $0.15 per 1M input tokens |
| Fallback | AWS Bedrock | ❌ Free tier limited | $0.003 per 1K input tokens |
| JSON output | Pydantic JSON mode | Built-in | No extra cost |

### 13.6 CLI & Logging

| Component | Technology | Why |
|-----------|-----------|-----|
| CLI | Typer | Decorators, type hints, auto --help |
| Logging | structlog | Structured JSONL output, context |
| Terminal UI | Rich | Colors, tables, progress bars |

### 13.7 Data Processing

| Component | Technology | Why |
|-----------|-----------|-----|
| Dataframes | Polars | Fast, type-safe, SQL queries |
| JSON | pydantic | Schema, validation, serialization |
| Env config | pydantic-settings | Type-safe environment variables |
| Retry logic | tenacity | Exponential backoff, jitter |
| Circuit breaker | circuitbreaker | Fail-fast for cascading failures |

### 13.8 Report Generation

| Component | Technology | Why |
|-----------|-----------|-----|
| Templating | Jinja2 | Dynamic HTML generation |
| Charts | Chart.js | Interactive visualizations |
| Diagrams | Mermaid.js | System architecture diagrams |
| Styling | Bootstrap 5 | Responsive, dark mode |

---

## 14. How to Extend & Debug

### 14.1 Adding a New Agent

1. **Define the agent class** in `src/ctie/agents/`:
```python
class MyAgent:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm
    
    async def process(self, app: AppInput, state: AppPipelineState) -> AppPipelineState:
        logger.info("my_agent_start", app_id=app.id)
        try:
            # Do work
            result = await self.do_work(app)
            state["my_field"] = result
            state["status"] = "NEXT_STATE"
            return state
        except Exception as e:
            logger.error("my_agent_error", error=str(e))
            raise
```

2. **Register in LangGraph** in `src/ctie/graph/builder.py`:
```python
graph.add_node("my_agent", my_agent_node)
graph.add_edge("PREVIOUS_STATE", "my_agent")
graph.add_edge("my_agent", "NEXT_STATE")
```

3. **Test it**:
```bash
uv run pytest tests/test_my_agent.py
```

### 14.2 Adding a New Search Provider

1. **Implement** in `src/ctie/search/providers/`:
```python
class MySearchProvider(SearchProvider):
    async def search(self, query: str, num_results: int = 10) -> list[SearchResult]:
        # Call your search API
        # Return list of SearchResult
        pass
```

2. **Register in factory** in `src/ctie/search/factory.py`:
```python
if provider_name == "my_search":
    return MySearchProvider(api_key)
```

3. **Test**:
```bash
uv run pytest tests/test_search_providers.py
```

### 14.3 Debugging a Failed App

```bash
# Check logs for the app
grep "app-id-123" logs/*.jsonl

# Query SQLite
sqlite3 outputs/ctie.db
> SELECT status, error, retry_count FROM apps WHERE id = 'app-id-123';

# Inspect cached documents
> SELECT url, fetch_method FROM documents WHERE app_id = 'app-id-123';

# Re-run just this app with debug logging
export CTIE_DEBUG=1
export CTIE_DEBUG_APP=app-id-123
uv run ctie run --fresh
```

### 14.4 Tracing LLM Calls

```bash
# Enable LLM tracing
export CTIE_LLM_TRACE=1
uv run ctie run

# View prompts and responses
tail -f logs/llm_trace.jsonl | jq .
```

### 14.5 Profiling Performance

```bash
# Profile pipeline
export CTIE_PROFILE=1
uv run ctie run --limit 5  # Run only 5 apps

# Analyze
python -m pstats outputs/ctie.prof
```

---

## 15. Performance & Scalability

### 15.1 Bottlenecks

| Bottleneck | Cause | Solution |
|-----------|-------|----------|
| **Search latency** | Network, provider slowness | Composio (pre-cached results) or cached results |
| **Document fetch** | Large docs, JS rendering | Parallel fetch, Playwright pool |
| **LLM latency** | Model inference time | Smaller context, fewer extraction passes |
| **LLM cost** | Token usage | Cache results, fewer retries |
| **Database I/O** | SQLite is single-writer | Use Semaphore, write batching |

### 15.2 Scaling Strategies

**To run 1000+ apps:**

1. **Parallel instance sharding** — split apps across multiple processes
   ```python
   # Process apps 0-100 on worker 1
   uv run ctie run --shard 1/10
   ```

2. **Cache layer** — add Redis for search/document cache
   ```python
   cache = RedisCache("redis://localhost")
   ```

3. **Database sharding** — split SQLite by app category
   ```python
   db = SQLiteStore(f"outputs/{category}.db")
   ```

4. **Async streaming** — stream results to file instead of buffering
   ```python
   with open("outputs/streaming_results.jsonl", "w") as f:
       for app_result in results:
           f.write(json.dumps(app_result) + "\n")
   ```

### 15.3 Cost Optimization

| Action | Savings | Trade-off |
|--------|---------|-----------|
| Increase cache TTL | 30-40% fewer LLM calls | Stale data |
| Reduce extraction passes | 50% LLM tokens | Some facts UNKNOWN |
| Batch LLM requests | Better TPM usage | Slower per-request |
| Use Bedrock instead of Azure | 5x cheaper | Slower, less capable |

---

## Epilogue

CTIE is designed to be **production-grade, auditable, and reproducible**. Every design decision prioritizes:

- ✅ **Transparency:** Evidence links, verification status, source quotes
- ✅ **Fault tolerance:** Checkpoint/resume, fallback chains, graceful degradation
- ✅ **Cost efficiency:** Cache aggressively, reuse results, pay-as-you-go LLMs
- ✅ **Extensibility:** Modular agents, pluggable providers, clear interfaces
- ✅ **Explainability:** Structured logging, audit trails, confidence scores

Happy debugging! 🚀
