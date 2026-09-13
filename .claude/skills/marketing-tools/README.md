# Marketing Skills (MCP-GC fork)

37 general marketing skills for Claude Code, covering paid ads, subscriptions/paywalls,
CRO, analytics/attribution, content, copy, growth loops, launch, PR, community,
research, and strategy — the broader marketing-skills counterpart to
[`aso-tools/`](../aso-tools/), which covers App Store Optimization specifically.

**Source:** adapted from [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills)
(MIT License — see [LICENSE](LICENSE)).

## What's different from upstream

Upstream is written for websites, SaaS, and B2B marketing, and binds several skills
to two "Verified Partners" (Converly for conversion tracking, Ploy for an AI website
builder) plus a `tools/` directory of ~90 third-party integrations. This fork rebinds
every vendored skill to **MCP-GC's own MCP servers** instead — RevenueCat, GA4/Firebase
analytics, the funnel-engine, App Store/Play Store review and listing tools, FCM push,
image generation, and (once live elsewhere in this branch) Meta Ads, OpenSEO, and
mobile device automation. No Converly/Ploy account, no third-party tool was invented
to fill the gap — see [`integrations/mcp-gc.md`](integrations/mcp-gc.md)'s Gaps table
for the handful of things (ESP email sending, SMS, social scheduling, AI video
generation, website hosting) that have no free MCP-GC substitute; those skills say so
plainly instead of guessing.

- [`REGISTRY.md`](REGISTRY.md) — capability matrix and skill → tool mapping
- [`integrations/mcp-gc.md`](integrations/mcp-gc.md) — the full upstream-tool → MCP-GC
  capability mapping, the honest Gaps table, and a note on reconciling this library's
  `.agents/product-marketing.md` convention with the ASO-tools fork's
  `app-marketing-context.md`

## What was excluded, and why

The upstream repo ships ~49 skills. Two exclusion rules were applied to decide what
to vendor here:

1. **`aso`** was skipped outright — it's superseded by the much more thorough
   `aso-audit` + the rest of the `aso-tools` fork already in this repo. Vendoring it
   would just create a weaker duplicate.
2. **Pure website/B2B-sales-process skills with no relevance to a mobile-app-only
   portfolio tool** were skipped: `schema`, `programmatic-seo`, `site-architecture`,
   `directory-submissions`, `revops`, `sales-enablement`, `prospecting`, `cold-email`,
   `events`, `co-marketing`, `competitors` (web comparison/alternatives pages), and
   `competitor-profiling` (website-scraping-based competitive dossiers — MCP-GC apps
   don't have marketing websites to scrape, and this overlaps with the ASO-tools
   fork's `competitor-analysis`/`competitor-tracking` anyway). MCP-GC apps don't run
   a B2B sales process or maintain a marketing website in the way these skills assume.

Everything else — 37 skills — was vendored and rebound. `marketing-psychology` (not
in the original scoping list this task started from) was found in the upstream repo
during a fresh listing and included, since it's general behavioral-science content
with no website/B2B dependency and applies cleanly to app pricing, paywalls, and copy.

## Layout

```
.claude/skills/
├── ab-testing/SKILL.md          # ...36 more specialist skills, flat, one dir each
├── paywalls/SKILL.md
├── ...
└── marketing-tools/              # not a skill itself — shared registry + docs (this dir)
    ├── REGISTRY.md
    ├── integrations/
    │   └── mcp-gc.md              # upstream-tool → MCP-GC mapping + gaps
    ├── README.md                  # this file
    └── LICENSE
```

Every skill directory sits flat under `.claude/skills/`, matching the Agent Skills
convention (`.claude/skills/<skill-name>/SKILL.md`) — same layout `aso-tools`' 40
skills use. Several skills also carry a `references/` subdirectory (and, in one case,
`ad-creative`, an `assets/` subdirectory) of supporting deep-dive material the
`SKILL.md` links out to — those were vendored unmodified alongside each `SKILL.md`.
Upstream's own `evals/` test-rubric directories were not carried over — same call
`aso-tools` made for its own doc-scaffolding, since they're not part of the
functional skill.

## Overlap with `aso-tools`

A handful of these skills cover ground the ASO-tools fork already has a
mobile-specific specialist for. Where that's the case, both skills say so and
cross-reference each other inline:

| This library | ASO-tools equivalent | When to prefer which |
|---|---|---|
| `paywalls` | `paywall-optimization` | `paywall-optimization` has the deeper conversion-funnel/placement playbook; `paywalls` is a lighter general pass. Both use the same RevenueCat tools. |
| `attribution` | `attribution-setup` | `attribution-setup` is the mobile-specific specialist (SKAdNetwork, MMPs, deep links) — prefer it for install attribution. `attribution` is better for the model-choice/reconciliation problem in general. |
| `onboarding` | `onboarding-optimization` | Use together — `onboarding` for activation-model theory, `onboarding-optimization` for App Store-context specifics. |
| `referrals` | `referral-program` | `referral-program` is scoped to in-app invite mechanics; `referrals` is the broader affiliate/ambassador-program version. |
| `launch` | `app-launch` | `app-launch` is the dedicated specialist for a **new app's** App Store submission/launch; `launch` is better for feature launches and general GTM sequencing. |
| `video` | `app-preview-video` | `app-preview-video` covers App Store/Play Store promo-video strategy specifically; `video` is the general production/tooling layer. |
| `influencer-marketing` | `creator-ugc-marketing` | `creator-ugc-marketing` has an app-specific lens (TikTok/Reels creators, UGC ad creative); `influencer-marketing` covers structured paid-partnership/ambassador mechanics in more depth. |
| `public-relations` | `press-and-pr` | `press-and-pr` is the App Store-editorial-featuring specialist; `public-relations` covers general earned-media/journalist-pitching this library doesn't otherwise have. |
| `ads` | `apple-search-ads` | `apple-search-ads` is the dedicated Apple Search Ads specialist; `ads` covers Meta/other paid platforms. |

No directory-name collisions exist between the two libraries — every skill above
lives at a distinct path — so nothing was overwritten.

## Usage

Invoke a skill directly, e.g. `/paywalls`, `/copywriting`, `/marketing-plan`. There is
no dedicated router for this library the way `aso-router` covers `aso-tools` — for
ambiguous app-marketing requests, start with `aso-router` anyway (it can hand off to
these skills' upstream category if relevant), or invoke the specific skill by name.

Most skills expect app context from `app-marketing-context.md` (this project's own
convention) or `.agents/product-marketing.md` (this library's upstream convention) —
see the reconciliation note in [`integrations/mcp-gc.md`](integrations/mcp-gc.md).
This project manages a multi-app portfolio (`config/apps.json`), so skills should ask
which app they're operating on rather than assume a single "current app."
