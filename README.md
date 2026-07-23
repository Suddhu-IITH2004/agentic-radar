# 🚀 Composio Toolkit Intelligence Engine (CTIE)

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **Your autonomous AI researcher for SaaS app evaluation** — Discovers, researches, and scores 100+ SaaS applications for Composio toolkit readiness in one go. No manual digging required! 🎯

---

## 🎯 What Does CTIE Do?

Think of CTIE as your tireless AI research assistant. Point it at a list of SaaS apps, kick back, and it will:

✅ **Search** for official documentation and developer resources across the web  
✅ **Extract** structured intelligence: auth methods, API coverage, MCP support, blockers  
✅ **Verify** facts across multiple sources to catch hallucinations  
✅ **Score** confidence levels per field so you know what to trust  
✅ **Cluster** insights into patterns and trends  
✅ **Generate** a beautiful interactive HTML report with visualizations  
✅ **Resume** automatically if anything crashes (zero data loss!)  

For each app, you get:

- 📋 **Category** and quick one-line description
- 🔐 **Authentication methods** (OAuth, API Key, JWT, etc.)
- 🏢 **Developer access**: self-serve or gated?
- 🛠️ **API type & coverage**: REST, GraphQL, gRPC, or hybrid?
- 🔗 **Toolkit support**: does Composio, MCP, or an SDK already exist?
- 🚧 **Buildability verdict**: can we integrate this? What are the blockers?
- 🔗 **Evidence links** & confidence scores for every claim

Everything is stored in an interactive report you can share with stakeholders.

---

## 📊 Sample Report

See what CTIE produces: [Interactive Report Example](https://composio-research.example.com/report.html)  
*(A sample of 100 apps analyzed and visualized in one report)*

---

## 🏗️ Architecture & Deep Dive

Want to understand the internals and potentially extend or debug CTIE?  
→ See [**ARCHITECTURE.md**](ARCHITECTURE.md) for the complete technical breakdown.

**In a nutshell:**

```
🎮 Coordinator
  ↓ (distributes work)
🔎 Research Agent (web search)
  ↓
📄 Fetcher (downloads docs)
  ↓
🧠 Extraction Agent (LLM analysis)
  ↓
✓ Verification Agent (cross-check facts)
  ↓
⭐ Scoring Agent (confidence levels)
  ↓
📚 Enrichment Agent (Composio SDK lookup)
  ↓
💡 Insights Agent (pattern detection)
  ↓
📊 Report Generator (interactive HTML)
```

- **Orchestration**: LangGraph state machine (like a smart workflow engine)
- **Storage**: SQLite for state + checkpointing (crash recovery built-in)
- **Search**: Composio Search Toolkit + fallback to DuckDuckGo
- **LLM**: Azure OpenAI (primary) → AWS Bedrock (fallback)
- **Resume**: Every app's progress is saved; only incomplete apps re-run

---

## 🚀 Getting Started in 5 Minutes

### Step 1️⃣: Clone & Install

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/composio-toolkit-intel.git
cd composio-toolkit-intel

# Install dependencies (using uv for speed)
uv sync

# Install browser dependencies (Playwright)
uv run playwright install chromium
```

### Step 2️⃣: Configure Your Environment

```bash
# Copy the example environment file
cp .env.example .env

# Open .env in your editor and fill in your credentials
```

**Required API Keys** (choose at least one LLM provider):

| Variable | What It Does | Where to Get It |
|----------|-------------|------------------|
| **COMPOSIO_API_KEY** | Powers web search & doc fetching | [Composio Dashboard](https://dashboard.composio.dev) |
| **AZURE_OPENAI_API_KEY** | Primary reasoning AI | [Azure OpenAI](https://azure.microsoft.com/en-us/products/openai) |
| **AZURE_OPENAI_ENDPOINT** | Your Azure OpenAI resource URL | From Azure portal |
| **AZURE_OPENAI_DEPLOYMENT** | Model name (e.g., `gpt-4o`) | Deployment name in Azure |

**Optional Fallback Keys** (used if Azure is rate-limited):

| Variable | Purpose |
|----------|---------|
| **AWS_ACCESS_KEY_ID** + **AWS_SECRET_ACCESS_KEY** | AWS Bedrock LLM fallback |
| **AWS_REGION** | AWS region (e.g., `us-east-1`) |

**Example `.env`:**
```bash
# LLM Configuration
LLM_PROVIDER=azure_openai
AZURE_OPENAI_API_KEY=sk-...
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-08-01-preview

# Fallback (optional, for redundancy)
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=xxx...
AWS_REGION=us-east-1

# Search & Enrichment
COMPOSIO_API_KEY=xxx...
```

### Step 3️⃣: Verify Setup

```bash
# Quick health check of all services
uv run ctie healthcheck
```

**Expected output:**
```
✅ Configuration OK
✅ LLM Provider (azure_openai): OK
✅ Search Provider: duckduckgo
✅ Database: outputs/ctie.db (will be created on first run)
```

### Step 4️⃣: Run the Pipeline

```bash
# Run research on ALL apps in data/apps.json
uv run ctie run

# Resume if interrupted (only processes failed/incomplete apps)
uv run ctie run --resume

# Fresh run (ignore previous results, start over)
uv run ctie run --fresh

# Just regenerate the HTML report from existing data
uv run ctie report

# Export results for archival/audit
uv run ctie export-db --output my_results_2026_07_23.db
```

---

## 📁 Input Data Format

Prepare your app list as `data/apps.json`:

```json
{
  "apps": [
    {
      "id": "slack-001",
      "name": "Slack",
      "website": "https://slack.com",
      "category_hint": "Communication"
    },
    {
      "id": "stripe-001",
      "name": "Stripe",
      "website": "https://stripe.com",
      "category_hint": "Payment Processing"
    }
  ]
}
```

Or just a simple array:
```json
[
  { "id": "app-1", "name": "App Name", "website": "https://...", "category_hint": "Category" },
  ...
]
```

---

## 📊 Output Files

After running, you'll get:

| File | Contents |
|------|----------|
| `outputs/report.html` | 🎨 Beautiful interactive dashboard with charts, filters, search |
| `outputs/results.json` | 📋 All raw structured data (JSON) for programmatic access |
| `outputs/ctie.db` | 💾 SQLite database with full state, logs, and evidence |
| `logs/` | 📝 Detailed execution logs per run |

---

## 🎮 Advanced Commands

```bash
# Check health of all integrations
uv run ctie healthcheck

# Export results to CSV for Excel
uv run ctie export --format csv --output results.csv

# List all apps and their current status
uv run ctie status

# Clear all results and start fresh
uv run ctie reset-db

# Run with verbose logging
uv run ctie run --debug
```

---

## 🐛 Troubleshooting

**Issue: "Missing COMPOSIO_API_KEY"**  
→ Get it from [Composio Dashboard](https://dashboard.composio.dev) and add to `.env`

**Issue: "Azure OpenAI rate limited"**  
→ Ensure `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` are set for Bedrock fallback

**Issue: "Database locked error"**  
→ Make sure only one instance of CTIE is running; SQLite doesn't like concurrent writes

**Issue: "Playwright browser not found"**  
→ Run `uv run playwright install chromium`

---

## 🏗️ Project Structure

```
composio-toolkit-intel/
├── README.md                    # This file
├── ARCHITECTURE.md              # Technical deep-dive
├── QUICKSTART.md                # Setup instructions
├── pyproject.toml               # Dependencies & metadata
├── .env.example                 # Example environment config
│
├── src/ctie/
│   ├── cli.py                   # Typer CLI entrypoint
│   ├── config.py                # Settings & validation
│   ├── agents/                  # Specialist agents (research, extract, verify, etc.)
│   ├── graph/                   # LangGraph orchestration
│   ├── llm/                     # LLM providers (Azure, Bedrock)
│   ├── models/                  # Pydantic data models
│   ├── prompts/                 # LLM prompt templates
│   ├── search/                  # Search providers (Composio, DuckDuckGo)
│   ├── retrieval/               # Document fetching
│   ├── report/                  # HTML report generation
│   └── storage/                 # Database layer (SQLite)
│
├── data/
│   ├── apps.json                # Input: list of apps to research (100+ apps)
│   └── apps_test.json           # Test dataset (small)
│
└── outputs/
    ├── report.html              # Generated interactive report 📊
    ├── results.json             # Raw results
    └── ctie.db                  # SQLite state database
```

---

## 💡 How It Works (Simple Version)

1. **You provide** a list of SaaS apps (name, website, category)
2. **CTIE searches** the web for documentation & developer info
3. **CTIE extracts** facts using AI (auth, API, blockers, support)
4. **CTIE verifies** findings across multiple sources
5. **CTIE scores** confidence per field (80% confident? 99%? 20%?)
6. **CTIE enriches** with Composio toolkit metadata
7. **CTIE clusters** results to find patterns (e.g., "75% use OAuth")
8. **CTIE generates** a beautiful HTML report with charts & evidence links
9. **You review** the report and make informed decisions 🎉

---

## 🔧 Extending CTIE

Want to customize the research? CTIE is built modularly:

- **Add a new LLM provider**: Add a class in `src/ctie/llm/`
- **Add a new search engine**: Add a class in `src/ctie/search/`
- **Modify extraction logic**: Edit `src/ctie/agents/extraction.py`
- **Customize the HTML report**: Edit `src/ctie/report/template.html`
- **Add new scoring rules**: Edit `src/ctie/agents/scoring.py`

See [ARCHITECTURE.md](ARCHITECTURE.md) for full extensibility guide.

---

## 📄 License

MIT License — use freely for personal and commercial projects.

---

## 🤝 Contributing

Found a bug? Have an idea? Open an issue or PR!

---

## 📞 Support

For issues or questions:
1. Check [ARCHITECTURE.md](ARCHITECTURE.md) for technical details
2. Check [QUICKSTART.md](QUICKSTART.md) for setup help
3. Review logs in `logs/` directory
4. Open a GitHub issue with your error logs

---

**Made with ❤️ for researchers and AI enthusiasts.**  
*Last updated: July 2026*
uv run ctie import-db --input run_2026_07_23.db
```

The SQLite database at `outputs/ctie.db` stores per-app state, cached documents, and evidence. It is ignored by git and can be exported with `ctie export-db`. If the process stops, rerun `uv run ctie run` and it will continue from the last saved state.

### 4. View

Open `outputs/report.html` in a browser, or visit the GitHub Pages link once deployed.

---

## Repository structure

```
.
├── src/ctie/           # Pipeline source code
├── data/               # Input app list (committed)
├── outputs/            # report.html, results.csv, summary.json (committed); ctie.db ignored
├── tests/              # Unit tests
├── ARCHITECTURE.md     # System design
└── README.md           # This file
```

---

## Verification

We randomly sample apps and manually verify the agent’s outputs against official documentation.

---

## License

MIT.
