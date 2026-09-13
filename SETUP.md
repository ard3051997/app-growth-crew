# MCP-GC Setup Playbook

This file is written for a **coding agent** (Claude Code, Codex, Cursor, or any
other MCP-capable CLI) to follow step by step to bring this repository from a
fresh clone to a working state — MCP servers registered, credentials
collected, subagents generated, and the test suite green. A human should be
present to supply secrets and approve anything destructive, but the agent
should drive every step below in order.

If you are that agent: work through the numbered steps, stop and ask the
human wherever a step says **ASK THE HUMAN**, and don't skip the verification
step at the end. Nothing here requires internet access beyond package
installs and the API calls the human's own credentials authorize.

## Step 0 — Orient

```bash
cd <repo-root>
git status                 # confirm a clean or expected working tree
git branch --show-current  # confirm you're not on main (create a feature/... branch if asked to change anything)
python3 --version          # need 3.11+
```

Read `AGENTS.md` now if you haven't — it has the domain-routing table you'll
need later, and it's the tool-agnostic counterpart to this file.

## Step 1 — Bootstrap dependencies and config files

Run the existing bootstrap script — it is idempotent (every write is
existence-gated, safe to re-run):

```bash
./scripts/setup.sh
```

This installs `uv` if missing, runs `uv sync --all-extras`, creates `.env`,
`config/apps.json`, and `.mcp.json` from their `.example` templates (only if
they don't already exist), creates `data/`, and runs the mocked test suite
(no live credentials needed for this to pass).

If `uv sync` or the test run fails, stop and diagnose before continuing —
don't proceed on a broken install.

## Step 2 — Collect credentials (ASK THE HUMAN)

Nothing below can be guessed or invented — ask the human which services they
actually use, then fill in `.env` for global/default credentials. Present
this table and ask them to tell you which rows apply:

| Service | Env vars (in `.env`) | Where to get them | Needed for |
|---|---|---|---|
| Google Cloud (Play Store, GA4, AdMob) | `GOOGLE_APPLICATION_CREDENTIALS` | Service account JSON from GCP Console with Play Developer API + Analytics Data API + AdMob API access | `play-store`, `analytics`, `admob` subagents |
| RevenueCat | `REVENUECAT_API_KEY`, `REVENUECAT_PROJECT_ID` | RevenueCat Dashboard → API Keys / Project Settings | `revenuecat` subagent, subscription experiments |
| Google Analytics 4 | `GA4_PROPERTY_ID` | GA4 Admin → Property Settings | `analytics` subagent |
| AdMob | `ADMOB_ACCOUNT_ID` | AdMob Dashboard → Account | `admob` subagent |
| GCS (Play Console bulk exports) | `GCS_PLAY_CONSOLE_BUCKET` | Play Console's linked GCS bucket name | `gcs` subagent |
| Google Ads | `GOOGLE_ADS_CONFIGURATION_FILE_PATH` (points at a `google-ads.yaml`) | Google Ads API developer token + OAuth credentials | `google-ads` subagent |
| App Store Connect (per app, in `config/apps.json`) | `app_store_connect_key_id`, `app_store_connect_issuer_id`, `app_store_connect_private_key_path` | App Store Connect → Users and Access → Keys | `app-store-connect` subagent (iOS apps) |
| Jira/Confluence | `JIRA_URL`, `JIRA_USERNAME`, `JIRA_API_TOKEN`, `CONFLUENCE_URL` | Atlassian account settings → API tokens | `atlassian` subagent |
| Meta Ads (Pipeboard) | `PIPEBOARD_API_TOKEN` | https://pipeboard.co account | `meta-ads` subagent |
| OpenSEO | `OPENSEO_API_KEY` | https://openseo.so/docs/mcp | `seo` subagent |
| Telegram approval gate | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Telegram `@BotFather` for the token; message the bot once and check `getUpdates` for the chat ID | Required before the autonomous loop (`run_autonomous_loop.py`) can make any live write — it fails closed without this |
| Hypothesis-generation LLM (autonomous loop only) | `HYPOTHESIS_LLM_PROVIDER` + matching key (`ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY`) | Whichever provider's console | The loop's one daily LLM call; has nothing to do with which coding-agent CLI you're running right now |

Skip any row the human doesn't need — missing credentials degrade gracefully
(a subagent with no credentials just can't do anything, it won't crash the
others). `firebase` and `mobile-mcp` need no API key at all (Firebase CLI
login / local device access respectively).

After editing `.env`, re-run the validation block to confirm what's picked up:

```bash
./scripts/setup.sh   # safe to re-run; re-validates .env without making live calls
```

## Step 3 — Add real apps to `config/apps.json`

For each app the human wants managed, add an entry (copy the shape already in
`config/apps.json.example`). Leave any field `null` to fall back to the
global `.env` value — only set per-app fields where an app's credentials
genuinely differ (e.g. a second Apple Developer team, a different RevenueCat
project).

## Step 4 — Regenerate subagent definitions (only if you edited personas)

`.claude/agents/*.md` are generated from `src/app_manager/personas.py` and
are already committed — you don't need to do this on a normal setup. Only
re-run it if you changed a persona:

```bash
uv run python scripts/generate_claude_agents.py
```

## Step 5 — Reload MCP servers

`.mcp.json` changes are only picked up on (re)connect — editing it mid-session
does not hot-reload. After Step 2/3 change which servers have real
credentials:

- **Claude Code**: restart the session, or run its MCP-reload command if one
  is available in this session.
- **Other CLIs**: restart the CLI process.

Confirm the reload worked by listing available MCP tools and checking that
the servers matching the credentials you just added are present (e.g. if you
configured RevenueCat, you should see `mcp__revenuecat__*` tools).

## Step 6 — Verify

```bash
uv run pytest
uv run ruff check src/ tests/
uv run mypy src/app_manager/ src/play_store_mcp/
```

Then do one live smoke test per configured service — ask a domain-specific
question and confirm it routes to the right subagent (see `AGENTS.md`'s
routing table) and returns real data, not an error. A good first one: ask
about Play Store vitals or App Store reviews for one of the apps added in
Step 3.

## Step 7 — Onboard each app's rulebook

For every app added in Step 3, generate its safety rulebook instead of
hand-writing one:

```
Call the generate_app_rulebook tool (mcp__funnel-engine__generate_app_rulebook)
with that app's package_name.
```

This writes `rulebooks/<package_name>.yaml`, seeded from the live listing and
monetization state, defaulting to requiring human approval on every mutating
action. **Review the generated file with the human before loosening
anything** — especially before enabling any `auto_low_risk` execution mode.

## Step 8 — Optional: autonomous loop and frontend

Only if the human wants the unattended daily PRAO cron (requires the
Telegram approval gate from Step 2):

```bash
uv run python src/run_autonomous_loop.py
```

This is a long-running daemon — run it under a process manager or `cron`,
not inside an interactive agent session.

Optional dashboard:

```bash
uv run uvicorn src.api_server.main:app --reload   # backend, localhost:8000
npm --prefix frontend ci && npm --prefix frontend run dev  # UI, localhost:5173
```

## Troubleshooting

- **A subagent reports "not configured"**: expected if you skipped that
  row in Step 2 — not a bug.
- **`uv sync` fails**: usually a Python version mismatch; confirm
  `python3 --version` is 3.11+.
- **MCP tools for a server don't appear**: you likely need the reload from
  Step 5, or that server's command (`npx`, `uvx`) isn't on `PATH`.
- **Autonomous loop won't write anything**: check `TELEGRAM_BOT_TOKEN`/
  `TELEGRAM_CHAT_ID` are set — the write-guard fails closed without them.
- For anything not covered here, read `README.md` (architecture + full env
  var reference) and `CLAUDE.md` (repo conventions, commands, MCP server
  table).
