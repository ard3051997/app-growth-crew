#!/usr/bin/env bash
# One-shot setup for running the MCP-GC autonomous loop (and all MCP servers)
# on a fresh machine. Safe to re-run: every write is existence-gated.
#
# Usage: ./scripts/setup.sh [--dev]
#   --dev   also install the dev dependency group + Playwright browsers
#           (only needed for the standalone scraping scripts in scripts/,
#           not for the autonomous loop or any MCP server itself)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

WITH_DEV=false
for arg in "$@"; do
  case "$arg" in
    --dev) WITH_DEV=true ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RESET="\033[0m"

step() { printf "\n${BOLD}==> %s${RESET}\n" "$1"; }
ok()   { printf "  ${GREEN}✅ %s${RESET}\n" "$1"; }
warn() { printf "  ${YELLOW}⚠️  %s${RESET}\n" "$1"; }

# ---------------------------------------------------------------------------
step "Checking for uv"
if command -v uv >/dev/null 2>&1; then
  ok "uv already installed ($(uv --version))"
else
  warn "uv not found, installing..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  if ! command -v uv >/dev/null 2>&1; then
    echo "uv install failed — install manually: https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
  fi
  ok "uv installed ($(uv --version))"
fi

# ---------------------------------------------------------------------------
step "Installing Python dependencies"
uv sync --all-extras
ok "Core + analytics + aso + gcs extras installed"

if [ "$WITH_DEV" = true ]; then
  uv sync --all-extras --group dev
  uv run playwright install --with-deps chromium
  ok "Dev group + Playwright chromium installed"
fi

# ---------------------------------------------------------------------------
step "Bootstrapping .env"
if [ -f .env ]; then
  ok ".env already exists, leaving it untouched"
else
  cp .env.example .env
  ok "Created .env from .env.example — fill in your credentials before running the loop"
fi

# ---------------------------------------------------------------------------
step "Bootstrapping config/apps.json"
if [ -f config/apps.json ]; then
  ok "config/apps.json already exists, leaving it untouched"
else
  cp config/apps.json.example config/apps.json
  ok "Created config/apps.json from config/apps.json.example — add your real apps before running the loop"
fi

# ---------------------------------------------------------------------------
step "Bootstrapping .mcp.json (MCP server registrations)"
if [ -f .mcp.json ]; then
  ok ".mcp.json already exists, leaving it untouched"
else
  cp .mcp.json.example .mcp.json
  ok "Created .mcp.json from .mcp.json.example — registers all MCP servers via 'uv run'"
fi

# ---------------------------------------------------------------------------
step "Ensuring data/ directory exists"
mkdir -p data
ok "data/ ready for the SQLite funnel-engine DB"

# ---------------------------------------------------------------------------
step "Running smoke tests (mocked, no real credentials needed)"
uv run pytest -q
ok "Test suite passed"

# ---------------------------------------------------------------------------
step "Validating .env configuration (no live API calls)"

check_group() {
  local label="$1"; shift
  local missing=()
  for var in "$@"; do
    if [ -z "${!var:-}" ]; then
      missing+=("$var")
    fi
  done
  if [ "${#missing[@]}" -eq 0 ]; then
    ok "$label: all set"
  else
    warn "$label: missing ${missing[*]}"
  fi
}

# Sourced in a subshell so real credentials never leak into this process's
# environment (would otherwise change behavior of anything run afterward).
(
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a

  check_group "Core (Google Cloud)" GOOGLE_APPLICATION_CREDENTIALS
  check_group "Hypothesis LLM (autonomous loop)" HYPOTHESIS_LLM_PROVIDER
  check_group "RevenueCat" REVENUECAT_API_KEY REVENUECAT_PROJECT_ID
  check_group "Google Analytics 4" GA4_PROPERTY_ID
  check_group "AdMob" ADMOB_ACCOUNT_ID
  check_group "GCS (Play Console exports)" GCS_PLAY_CONSOLE_BUCKET
  check_group "Google Ads" GOOGLE_ADS_CONFIGURATION_FILE_PATH GOOGLE_ADS_CUSTOMER_ID
  check_group "App Store Connect" APP_STORE_CONNECT_KEY_ID APP_STORE_CONNECT_ISSUER_ID
  check_group "ASO (AppFollow)" APPFOLLOW_API_KEY
  check_group "Telegram approval gate (required for autonomous writes)" TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID
  check_group "Autonomous loop scope" AUTONOMOUS_LOOP_PACKAGES
)

# ---------------------------------------------------------------------------
step "Setup complete"
cat <<EOF

Next steps:
  1. Edit .env and config/apps.json with your real credentials/apps.
  2. Drive the MCP servers in .mcp.json directly from your coding-agent
     CLI (Claude Code, Codex, etc.) -- see AGENTS.md for the domain
     routing table, or SETUP.md for the full one-shot walkthrough.
  3. Autonomous scheduling daemon:     uv run python src/run_autonomous_loop.py
  4. Individual MCP servers:          uv run play-store-mcp   (etc. -- see .mcp.json)

Missing values reported above degrade gracefully -- a subagent with no
credentials for its domain simply can't do anything, it won't affect the
others -- but the Telegram approval gate must be set for the autonomous
loop to make any live write (it fails closed otherwise).
EOF
