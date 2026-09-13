# MCP-GC

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

MCP-GC is a set of MCP (Model Context Protocol) servers for managing a
portfolio of mobile apps: Google Play, Apple App Store Connect, RevenueCat,
Google Analytics 4, AdMob, ASO keyword research, Firebase Cloud Messaging,
and a cross-source funnel analysis engine. Point any MCP-compatible
coding-agent CLI (Claude Code, Codex, or similar) at these servers and it can
read your app's real data and make changes directly, with no separate
orchestration layer in between.

There is no bespoke agent runtime here. The coding-agent CLI you already use
drives the MCP servers directly, optionally using the per-domain subagent
definitions in `.claude/agents/`. The only place this project makes its own
LLM call is a small, provider-agnostic hypothesis-generation step inside the
optional unattended daily loop (`src/run_autonomous_loop.py`) -- everything
else is deterministic Python or a direct API call.

## Getting started

```bash
git clone <this-repo>
cd MCP-GC
./scripts/setup.sh
```

This installs `uv`, syncs dependencies, and creates `.env`, `config/apps.json`,
and `.mcp.json` from their templates. See [SETUP.md](SETUP.md) for the full
walkthrough, written so a coding agent can follow it step by step, including
where it needs to stop and ask you for credentials.

## MCP servers

| Server | Data source |
|---|---|
| `play-store` | Google Play Developer API |
| `app-store` | Apple App Store Connect |
| `revenuecat` | RevenueCat REST v2 |
| `analytics` | Google Analytics 4 |
| `admob` | AdMob API |
| `aso-keyword` | Play Store listing scraping |
| `funnel-engine` | Cross-source funnel database |
| `gcs` | GCS Play Console exports |
| `journey-map` | HTML journey map generator |
| `fcm-push` | Firebase Cloud Messaging |

`.mcp.json.example` also wires in a few third-party MCP servers --
`firebase`, `mobile-mcp` (device automation), `google-ads`, `atlassian`,
`meta-ads`, and `openseo` -- add credentials for the ones you use. See
`CLAUDE.md` for the full list and what each one requires.

## Configuration

- `.env` -- global credentials, copied from `.env.example`
- `config/apps.json` -- per-app credential overrides, copied from
  `config/apps.json.example`; any field left `null` falls back to `.env`
- `.mcp.json` -- MCP server registrations, copied from `.mcp.json.example`

Full reference for every variable is in `.env.example` and `CLAUDE.md`.

## Onboarding a new app

Add the app to `config/apps.json`, then ask your coding agent to call the
`generate_app_rulebook` tool (on the `funnel-engine` server) with that app's
package name. It writes a starting `rulebooks/<package>.yaml` seeded from the
live listing, keywords, and monetization state, defaulting to requiring
manual approval on every mutating action. Review the file before loosening
anything.

## Autonomous loop

An optional unattended daily loop (perception, reasoning, action,
observation) that ingests metrics, evaluates running experiments, and
proposes new ones:

```bash
uv run python src/run_autonomous_loop.py
```

Mutating actions require approval through a Telegram bot
(`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`) -- the loop fails closed without
it. The one LLM call it makes (experiment hypothesis generation) is
provider-agnostic: set `HYPOTHESIS_LLM_PROVIDER` to `anthropic`, `gemini`, or
`openai`, with the matching API key.

## Development

```bash
uv run pytest
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run mypy src/play_store_mcp/
```

Frontend dashboard (optional):

```bash
uv run uvicorn src.api_server.main:app --reload   # backend, localhost:8000
npm --prefix frontend ci && npm --prefix frontend run dev   # UI, localhost:5173
```

## License

MIT -- see [LICENSE](LICENSE).
