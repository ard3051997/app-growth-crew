# app-growth-crew

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A persona-driven crew of AI specialists for running a portfolio of mobile
apps: releases, subscriptions, analytics, ad monetization, ASO, paid
acquisition, push, and cross-source funnel analysis. Each specialist is a
domain persona with its own scoped tools; any MCP-compatible coding-agent CLI
(Claude Code, Codex, or similar) can load them and use them directly, with no
separate orchestrator process in between.

This is not "an MCP server." MCP is just the tool-calling layer underneath.
What this project actually provides is:

- **Personas** (`src/app_manager/personas.py`, rendered into
  `.claude/agents/*.md`) -- one specialist per domain, each scoped to exactly
  the tools it needs.
- **Skills** (`.claude/skills/`) -- reusable playbooks for ASO and broader
  marketing tasks, each bound to the real tools below instead of a paid
  third-party API.
- **MCP servers** (`src/*_mcp/`, wired in `.mcp.json`) -- the actual data and
  write access: Google Play, App Store Connect, RevenueCat, GA4, AdMob, ASO
  keyword research, Firebase Cloud Messaging, a cross-source funnel engine,
  and a few third-party servers (device automation, Meta Ads, SEO).
- **Rulebooks** (`rulebooks/<package>.yaml`) -- per-app safety limits
  (metadata constraints, budget caps, approval requirements) that gate every
  mutating action, generated automatically for a new app rather than
  hand-written.
- **An optional autonomous loop** (`src/run_autonomous_loop.py`) -- a daily
  perception/reasoning/action/observation cycle that proposes and (with
  approval) runs experiments unattended. It makes exactly one LLM call per
  day (experiment hypothesis generation), and that call is provider-agnostic.

## Getting started

```bash
git clone git@github.com:ard3051997/app-growth-crew.git
cd app-growth-crew
./scripts/setup.sh
```

This installs `uv`, syncs dependencies, and creates `.env`, `config/apps.json`,
and `.mcp.json` from their templates. [SETUP.md](SETUP.md) is a full
walkthrough written so a coding agent can follow it step by step, including
where it needs to stop and ask you for credentials.

## How it fits together

1. You (or your coding agent) add an app to `config/apps.json`.
2. The agent calls `generate_app_rulebook` (on the `funnel-engine` MCP
   server) to seed that app's safety rulebook from its live listing and
   monetization state -- defaulting to requiring your approval on every
   mutating action.
3. You ask a question or give an instruction. Your coding-agent CLI picks the
   matching persona (`.claude/agents/play-store.md`, `revenuecat.md`,
   `aso-keywords.md`, etc.) and it works with only that domain's MCP tools.
4. Optionally, `run_autonomous_loop.py` runs unattended on a schedule,
   proposing experiments that still need your approval (via Telegram) before
   anything mutates.

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

`.mcp.json.example` also wires in `firebase`, `mobile-mcp` (device
automation), `google-ads`, `atlassian`, `meta-ads`, and `openseo` -- add
credentials for whichever of these you use. See `CLAUDE.md` for what each one
requires.

## Configuration

- `.env` -- global credentials, copied from `.env.example`
- `config/apps.json` -- per-app credential overrides, copied from
  `config/apps.json.example`; any field left `null` falls back to `.env`
- `.mcp.json` -- MCP server registrations, copied from `.mcp.json.example`

Full reference for every variable is in `.env.example` and `CLAUDE.md`.

## Development

```bash
uv run pytest
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run mypy src/play_store_mcp/
```

Optional frontend dashboard:

```bash
uv run uvicorn src.api_server.main:app --reload   # backend, localhost:8000
npm --prefix frontend ci && npm --prefix frontend run dev   # UI, localhost:5173
```

## Contributing

See [.github/CONTRIBUTING.md](.github/CONTRIBUTING.md). Security issues go
through [GitHub Security Advisories](https://github.com/ard3051997/app-growth-crew/security/advisories),
not public issues -- see [.github/SECURITY.md](.github/SECURITY.md).

## License

MIT -- see [LICENSE](LICENSE).
