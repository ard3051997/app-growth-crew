# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MCP-GC is an AI-powered mobile app portfolio management system. It has three layers:
1. **MCP servers** (`src/*_mcp/`) — expose Google Play, RevenueCat, GA4, AdMob, ASO, FCM, GCS, Apple App Store, mobile device automation, Meta Ads, and SEO APIs as MCP tools
2. **App management support code** (`src/app_manager/`) — deterministic experiment lifecycle/rollback/statistics engine, per-app credential resolution, and domain personas. There is no bespoke agent runtime: interactive use is driven directly by whichever coding-agent CLI you run (Claude Code, Codex, etc.) against the MCP servers in `.mcp.json`, using the per-domain subagent definitions in `.claude/agents/*.md` (generated from `personas.py`) where the CLI supports native subagent spawning
3. **Frontend** (`frontend/`) — React/Vite/Tailwind dashboard backed by a FastAPI server (`src/api_server/`)

## Commands

All Python commands use `uv run`.

```bash
# Install all dependencies
uv sync --all-extras

# Run tests
uv run pytest
uv run pytest tests/test_play_store_server.py   # single file
uv run pytest -k "test_get_app_reviews"          # single test
uv run pytest --cov=src/ --cov-report=html

# Lint & format
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run mypy src/play_store_mcp/   # mypy is only enforced on play_store_mcp

# Run the FastAPI backend (serves the React frontend at http://localhost:8000)
uv run uvicorn src.api_server.main:app --reload

# Run the React frontend dev server (http://localhost:5173)
cd frontend && npm run dev

# Regenerate .claude/agents/*.md subagent definitions from personas.py
uv run python scripts/generate_claude_agents.py

# Run individual MCP servers (stdio transport, for MCP client integration)
uv run play-store-mcp | uv run revenuecat-mcp | uv run analytics-mcp
uv run admob-mcp | uv run aso-keyword-mcp | uv run funnel-engine-mcp
uv run gcs-mcp | uv run journey-map-mcp | uv run fcm-push-mcp | uv run app-store-mcp

# Run the autonomous scheduling loop
uv run python src/run_autonomous_loop.py
```

## Architecture

### MCP Server Pattern

Every server under `src/*_mcp/` follows the same structure:

```
src/<name>_mcp/
├── __init__.py       # re-exports main()
├── __main__.py       # entry point
├── client.py         # API client — all outbound calls wrapped with @retry_on_transient
├── models.py         # Pydantic v2 models
└── server.py         # FastMCP server — tools registered via @mcp.tool()
```

Critical conventions:
- The `lifespan()` async context manager initializes the API client and stores it in `ctx.request_context.lifespan_context`. Tool functions always retrieve the client via `get_client_from_context(ctx)` — never instantiate clients inside tool functions.
- `structlog` goes to **stderr only**; stdout is the MCP JSON-RPC channel.
- Retry logic lives in `src/mcp_gc_shared/retry.py` (`retry_on_transient` decorator). Import from there rather than re-implementing.
- `.env` is auto-loaded by the `mcp_gc_shared.env.load_dotenv()` helper, which walks up 5 parent directories.

### All MCP Servers

| Server | Entry Point | Data Source |
|--------|-------------|-------------|
| `play_store_mcp` | `play-store-mcp` | Google Play Developer API |
| `revenuecat_mcp` | `revenuecat-mcp` | RevenueCat REST v2 |
| `analytics_mcp` | `analytics-mcp` | Google Analytics 4 |
| `admob_mcp` | `admob-mcp` | AdMob API |
| `aso_keyword_mcp` | `aso-keyword-mcp` | Play Store scraping |
| `funnel_engine_mcp` | `funnel-engine-mcp` | Cross-source funnel DB |
| `gcs_mcp` | `gcs-mcp` | GCS Play Console exports |
| `journey_map_mcp` | `journey-map-mcp` | HTML journey map generator |
| `fcm_push_mcp` | `fcm-push-mcp` | Firebase Cloud Messaging |
| `app_store_mcp` | `app-store-mcp` | Apple App Store Connect |

### App Management Support Code (`src/app_manager/`)

There is no bespoke agent runtime here — interactive use goes directly through your coding-agent CLI (Claude Code, Codex, etc.) driving the MCP servers in `.mcp.json`, optionally routed by the per-domain subagent definitions in `.claude/agents/*.md`. This directory holds the deterministic support code that any agent (or the unattended autonomous loop) calls as tools:

- **`config.py`** — `AppManagerConfig` dataclass; reads env vars, detects which services are configured
- **`credential_store.py`** — resolves per-app credentials from `config/apps.json`, falls back to `.env`
- **`personas.py`** — canonical source of truth for every domain persona; `scripts/generate_claude_agents.py` renders these into `.claude/agents/*.md`. Also used by `AGENTS.md`'s routing table for CLIs without native subagent spawning
- **`llm_provider.py`** — small provider-agnostic single-completion call (Anthropic/Gemini/OpenAI, chosen via `HYPOTHESIS_LLM_PROVIDER`) used only by the autonomous loop's hypothesis generator — the one place in this codebase that still makes a direct LLM API call
- **`experiment_engine.py`** — `ExperimentEvaluator` runs Welch's t-test for statistical significance (pure Python, no LLM); `HypothesisGenerator` turns a funnel snapshot into a proposed experiment via `llm_provider.complete_json()`
- **`experiment_lifecycle.py`** — full experiment state machine (PROPOSED → ACTIVE → CONCLUDED); types: ASO metadata, creatives, paywall, ad unit, push campaign, UA budget, remote config. Deterministic — never re-derive this logic from a persona/skill
- **`rollback_manager.py`** — captures pre-experiment snapshots via `PlayStoreClient`/`RevenueCatClient`; enables automated reverts
- **`tools.py`** — fixed-prompt generators (`generate_daily_report_prompt`, `compare_revenue_prompt`, `suggest_actions_prompt`) and `get_system_status()`, wrapped by the `.claude/commands/status|report|revenue|actions.md` slash commands

The FastAPI backend's `/api/apps/{package}/chat`, `/diagnostic`, and `/events_md/generate` endpoints no longer call an LLM directly — they return guidance pointing the user at their coding-agent CLI instead (it already has the MCP servers configured to pull the same data and produce an artifact).

**Onboarding a new app**: add it to `config/apps.json`, then call the `funnel-engine` MCP server's `generate_app_rulebook` tool to auto-generate a conservative starting `rulebooks/<package_name>.yaml` (metadata limits and ASO keywords seeded from the live listing; safety rules default to requiring Telegram approval on every mutating action until reviewed and loosened by hand).

### FastAPI Backend (`src/api_server/`)

Thin REST wrapper consumed by the React frontend. Routers map to frontend API calls 1:1:

| Router | Prefix | Purpose |
|--------|--------|---------|
| `portfolio.py` | `/api/portfolio` | Portfolio-level metrics and summary |
| `apps.py` | `/api/apps` | Per-app funnel, revenue, storefront, keywords, reviews |
| `experiments.py` | `/api/experiments` | Experiment CRUD and evaluation |
| `actions.py` | `/api/actions` | Action log |
| `system.py` | `/api/system` | Health, config status |
| `webhooks.py` | `/api/webhooks` | RevenueCat webhook → FCM re-engagement pipeline |

The webhook handler resolves per-app credentials from `credential_store`, selects the `ask_fcm_push` specialist tool, and logs all outcomes to the funnel engine SQLite DB via `funnel_engine.db.log_db_action`.

### Frontend (`frontend/`)

React 19 + Vite + Tailwind CSS 4. Pages are under `frontend/src/pages/`:
- `PortfolioCommandCenter.tsx` — main dashboard
- `ASOWorkspace.tsx`, `ExperimentCenter.tsx`, `FunnelDiagnostics.tsx`, `JourneyMap.tsx`, `RevenueMonetization.tsx`, `ActionLog.tsx`, `Settings.tsx`

All backend calls go through `frontend/src/api/index.ts`. The API base URL defaults to `http://localhost:8000/api` and is overridden via `VITE_API_BASE_URL`.

### Multi-App Configuration

`config/apps.json` stores per-app credentials. Each entry has `package_name`, `display_name`, `app_category`, and optional fields for each service (`revenuecat_api_key`, `google_credentials_path`, `admob_account_id`, `gcs_play_console_bucket`, `google_ads_customer_id`). A `null` field means "fall back to the global `.env` value." iOS apps use App Store bundle ID conventions as `package_name`.

### Key Environment Variables

```
GOOGLE_APPLICATION_CREDENTIALS  # Service account JSON path (Play, Analytics, AdMob)
REVENUECAT_API_KEY + REVENUECAT_PROJECT_ID
GA4_PROPERTY_ID
ADMOB_ACCOUNT_ID
GCS_PLAY_CONSOLE_BUCKET
TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID  # Required for the autonomous loop's approval gate

# Autonomous loop's hypothesis-generation LLM (one of these three, selected by HYPOTHESIS_LLM_PROVIDER)
HYPOTHESIS_LLM_PROVIDER     # anthropic | gemini | openai (default: gemini)
GEMINI_API_KEY
ANTHROPIC_API_KEY
OPENAI_API_KEY

# Optional third-party MCP servers (.mcp.json)
PIPEBOARD_API_TOKEN         # meta-ads server
OPENSEO_API_KEY             # openseo server
```

### External MCP Servers

Beyond this repo's own `src/*_mcp/` packages, `.mcp.json.example` also wires in third-party MCP servers — add credentials and uncomment/copy the block into `.mcp.json` as needed:

| Server | Source | Requires |
|--------|--------|----------|
| `firebase` | `firebase-tools mcp` (npx) | Firebase CLI login |
| `mobile-mcp` | [mobile-next/mobile-mcp](https://github.com/mobile-next/mobile-mcp) (npx) | None — device/simulator automation |
| `google-ads` | [googleads/google-ads-mcp](https://github.com/googleads/google-ads-mcp) (uvx) | `GOOGLE_ADS_CONFIG_PATH` |
| `atlassian` | `mcp-atlassian` (uvx) | Jira/Confluence credentials |
| `meta-ads` | [pipeboard-co/meta-ads-mcp](https://github.com/pipeboard-co/meta-ads-mcp) (remote) | `PIPEBOARD_API_TOKEN` |
| `openseo` | [OpenSEO MCP](https://openseo.so/docs/mcp) (remote) | `OPENSEO_API_KEY` |

### Testing

All Google API calls are mocked with `unittest.mock` — no real network calls. Test files follow `test_<server_name>_server.py` / `test_<server_name>_client.py`. Shared fixtures are in `tests/conftest.py`. `asyncio_mode = "auto"` is set in `pyproject.toml`, so async test functions work without explicit decorators.

## Git Flow

Always create a feature branch (`feature/…`) or bugfix branch (`bugfix/…`). Do not commit directly to `main`.

