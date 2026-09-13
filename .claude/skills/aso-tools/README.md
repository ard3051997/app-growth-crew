# ASO Skills (MCP-GC fork)

40 App Store Optimization / mobile growth skills for Claude Code, covering ASO core,
creative, reviews & ratings, growth & launch, paid UA, revenue & retention, and
analytics & market intel.

**Source:** adapted from [Eronred/aso-skills](https://github.com/Eronred/aso-skills)
(MIT License — see [LICENSE](LICENSE)).

## What's different from upstream

Upstream binds every skill to the paid [Appeeky](https://appeeky.com) API for live
App Store data. This fork rebinds every skill to **MCP-GC's own MCP servers**
(`src/*_mcp/` — Play Store, App Store Connect, RevenueCat, GA4, AdMob, funnel-engine,
Firebase, plus the project's own `aso_keyword_mcp` keyword server) instead. No
Appeeky account, API key, or per-request credits anywhere in this fork.

- [`REGISTRY.md`](REGISTRY.md) — capability matrix and skill → tool mapping, rewritten for MCP-GC's tools
- [`integrations/mcp-gc.md`](integrations/mcp-gc.md) — the full Appeeky → MCP-GC capability mapping, plus an honest list of things with **no free substitute** (competitor download/revenue estimates, market-mover/trending feeds) — those skills (`market-movers`, `market-pulse`, and parts of `competitor-tracking`, `category-positioning`, `seasonal-aso`) fall back to a manual weekly-snapshot-diff method instead of a live feed
- `asc-metrics` was rewritten to pull first-party downloads/revenue/subscriptions directly from App Store Connect + RevenueCat via MCP-GC's own pipeline, rather than through a third-party sync

Docs-site scaffolding from upstream (Mintlify pages, `docs.json`, `install/`,
`guides/`, `reference/*.mdx`) was not carried over — only the functional
`<skill-name>/SKILL.md` files and this tool registry are here.

## Layout

```
.claude/skills/
├── aso-router/SKILL.md          # entry point — routes to the right specialist skill
├── keyword-research/SKILL.md    # ...39 more specialist skills, flat, one dir each
├── ...
└── aso-tools/                   # not a skill itself — shared registry + docs (this dir)
    ├── REGISTRY.md
    ├── integrations/
    │   ├── mcp-gc.md             # Appeeky → MCP-GC tool mapping + gaps
    │   ├── revenuecat.md
    │   ├── app-store-connect.md
    │   └── firebase.md
    ├── README.md                 # this file
    └── LICENSE
```

Every skill directory sits flat under `.claude/skills/`, matching the Agent Skills
convention (`.claude/skills/<skill-name>/SKILL.md`) — nothing is nested under an
extra `skills/` folder, so Claude Code discovers all 40 automatically.

## Usage

Start with the router — it reads your request and loads the right specialist skill:

```
/aso-router
```

Or invoke a specific skill directly, e.g. `/keyword-research`, `/aso-audit`,
`/competitor-analysis`. See [`../aso-router/SKILL.md`](../aso-router/SKILL.md)
for the full routing table.

Most skills expect a `package_name` (Android) or bundle ID (iOS) from
`config/apps.json` — this project manages a multi-app portfolio, so there's no
implicit "current app."
