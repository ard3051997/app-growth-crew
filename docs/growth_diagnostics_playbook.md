# Growth Diagnostics Playbook

A symptom → root cause → diagnostic action reference for every growth lever this
portfolio manages, so a metric problem gets mapped to the *right* fix instead of
a guess. This is general, cross-app knowledge — not a per-app config (those live
in `rulebooks/<package>.yaml`). `src/funnel_engine/benchmarks.py`'s
`LEAK_INSIGHTS` encodes the short-form version of the ASO/creative sections
below directly into the automated funnel analysis (`run_funnel_analysis`).

Each section: **Symptom** (what the metric shows) → **Root cause** (what's
actually broken) → **Diagnostic action** (how to confirm it before proposing a
fix) → **Fix pattern** (what actually moves the metric).

---

## 1. ASO / Store Discoverability

The acquisition funnel has two genuinely different failure modes that look
similar in a dashboard but need opposite fixes. Don't treat them as one thing:

### 1a. Raw impressions are low (in absolute terms, not just the ratio)

**Symptom:** Total store impressions (search + browse appearances) are low —
the app just isn't showing up.

**Root cause:** This is a *reach/ranking* problem, not a creative problem.
Apple only shows an app for a search when its title, subtitle, or keyword
field actually indexes for that term. Low absolute impressions means the
title/subtitle/keyword targeting isn't covering enough real search demand —
wrong keywords, too narrow, or targeting terms with too little volume.

**Diagnostic action:** `aso-keyword` specialist — `get_keyword_volume` /
`get_advanced_keyword_difficulty` on the target keywords already in the
listing (or the app's category) to check they have real search volume and the
app is realistically competitive for them. `get_competitor_keywords` on the
top 3-5 category competitors to find volume the current listing isn't
targeting at all.

**Fix pattern:** Rework title/subtitle/keyword field to cover higher-volume,
winnable terms — not a screenshot or description change. This is exactly
Pomodori's current situation: near-zero installs and (as of this session)
zero recorded impressions; the one active experiment adds "pomodoro" to the
title for exactly this reason.

**Operational fact, verified against real App Store Connect behavior this
session:** **App name and subtitle are editable at (almost) any time** — no
new binary needed, confirmed by `AppStoreClient.update_listing` succeeding
live for Pomodori without a version bump. **The keywords field and the full
description are version-scoped** — Apple ties them to a specific app version
localization object, and if the live version is `READY_FOR_SALE` (locked),
editing them fails with a real API error ("field can not be modified in the
current state") until a new draft version exists (`_ensure_editable_version`
now creates one automatically). **In practice this means a keyword-field
change needs a version bump to actually take effect** — the standard ASO
practice of doing a "keyword-only" or otherwise code-unchanged ("blank")
release exists specifically because Apple won't let you edit keywords on an
already-live version. Title/subtitle changes don't have this constraint.

### 1b. Impressions are fine, but store-page-view / install conversion is low

**Symptom:** `Impression → Store View` or `Store View → Install` (in
`STEP_TRANSITIONS`) is below category benchmark, even though raw impression
volume is healthy.

**Root cause:** People are seeing the listing and not being convinced —
that's a *creative/listing content* problem, not a targeting problem. Icon
and title drive the tap-through from impression to page view; screenshots,
preview video, description, and star rating drive the page-view-to-install
decision.

**Diagnostic action:** Pull the current live listing
(`get_asc_listing`/`play-store get_listing`) and screenshots, and compare
against category-leading competitors — see §3 (Creative Benchmarking via
Mobbin) below. Check `get_reviews`/star rating too: a low rating is a real,
common install-blocker independent of the listing copy.

**Fix pattern:** Screenshot/icon/description changes, not keyword changes.
Never propose a keyword-field change to fix a conversion-rate problem, and
never propose a screenshot change to fix a raw-reach problem — they're
different levers and this codebase's rulebook validation already rejects
mismatched `target_tool`/experiment combinations for exactly this reason.

---

## 2. Paywall / Monetization

**Symptom:** `Onboarding → Paywall View`, `Paywall View → Trial Start`, or
`Trial Start → Paid Conversion` is below benchmark.

**Root cause candidates, in likely order:**
1. Paywall is shown at the wrong moment (too early, before any value moment) —
   check `Onboarding → Paywall View` timing against `EVENTS.md`.
2. Pricing/trial structure is off-market for the category (see
   `BENCHMARKS[category]["trial_to_paid"]` and RevenueCat's own real
   `get_charts`/`get_overview_metrics` data once configured).
3. The paywall screen itself under-sells relative to what users expect from
   comparable apps in the category — a real, comparable design problem.

**Diagnostic action — competitor paywall comparison via Mobbin MCP:**
Mobbin (`mcp__mobbin__search_screens` / `search_flows`, `platform: "ios"`) is
a real, live, semantic search over real shipped app UI — not a mockup
library. Query pattern:
- `search_screens(query="subscription paywall screen with pricing plans", platform="ios")`
  — general category baseline.
- Name specific, known category leaders directly in the query for a tighter
  comparison, e.g. `"Forest paywall screen"` or `"Focus To-Do subscription paywall"`
  for a productivity/focus-timer app like Pomodori.
- `search_flows(query="onboarding into subscription paywall", platform="ios")`
  to see *when* and *how* comparable apps introduce the paywall, not just
  what it looks like.

Compare the real screens returned against the app's own current paywall on:
value-prop clarity, social proof (ratings/testimonials on the paywall
itself), plan framing (annual-first vs monthly-first, savings badges), and
trial framing. Cite the actual `mobbin_url` for anything referenced.

**Known real gap:** there is no automated way in this codebase to capture a
*screenshot of the app's own live paywall* (no simulator/device-automation
tool in this stack) — that side of the comparison needs a manually-provided
screenshot from whoever has the build, or a real device/simulator capture
step outside MCP-GC. Don't fabricate a description of the paywall from
metadata alone.

**Fix pattern:** A `paywall_variant` experiment — but note **this experiment
type has no working rollback anywhere in this codebase today**
(`rollback_manager.py` explicitly returns `"not implemented"` for it). Don't
propose auto-execution for a paywall change; it's manual-only until real
rollback exists, same principle already applied to everything else here.

---

## 3. Store Listing Creative (Screenshots, Icon, Video)

Covered by §1b's fix pattern. Concretely:
- Use Mobbin the same way as §2 (`search_screens`/`search_flows`) but query
  for the app's category + "app store screenshots" or the specific named
  competitor, to see how category leaders sequence their screenshot story
  (first-frame hook, feature order, overlay copy density).
- `pomodori/aso.md` (this app's own real screenshot plan) is a good template
  for the *structure* a screenshot plan should have: ordered table of
  asset → overlay copy → "product evidence" (what the screenshot must
  actually show from the real, submitted build — never a mockup or claim the
  build doesn't support).
- Screenshot changes are version-scoped the same way keywords are (§1a) —
  budget for a version bump when proposing one.
- **[before.click](https://before.click)** — recommended tool for turning a
  raw, real app screenshot into a polished, device-framed App Store
  screenshot with overlay copy, matching the structure Mobbin comparison
  surfaces (first-frame hook, benefit headline, consistent overlay style
  across the set). No MCP/API access to it exists in this codebase today —
  it's a manual step for whoever owns the actual screenshot assets, not
  something this system executes. If a real API key/account becomes
  available later, wire it in the same way `image_gen_mcp` was built.

---

## 4. Onboarding / Activation

**Symptom:** `Install → Day 1 Active` or `Day 1 → Onboarding Complete` below
benchmark.

**Root cause candidates:** too many permission requests up front, no visible
value before the first required action, broken/confusing first-run flow.

**Diagnostic action:** `analytics` specialist — `get_events`/`get_screen_views`
funneled by onboarding step to find the exact screen where users stop, not
just the aggregate rate. A single bad screen (e.g. a permission prompt with
no context) usually explains most of the drop.

**Fix pattern:** This is a product/code change, not a store-listing or
paywall change — outside what this codebase can execute directly (no
code-fix automation here, see the earlier conversation about that boundary).
Surface the finding; the fix happens in the app's own repo.

---

## 5. Retention / Re-engagement

**Symptom:** `Install → Day 7/30 Retained` below benchmark.

**Root cause candidates:** no habit-forming trigger, no re-engagement outreach,
or the app's core loop doesn't have a natural weekly cadence for this
category.

**Diagnostic action:** `fcm-push` specialist to check whether re-engagement
push is even configured and firing (`google_credentials_path` must be set —
Pomodori's isn't yet, so push runs in mock mode and can't actually reach
anyone). `analytics get_retention` cohort-by-cohort to see if a specific
release regressed retention (correlates with `firebase crashlytics_get_report`
once real crash volume exists).

**Fix pattern:** Push re-engagement campaigns (`fcm-push send_push_*`) for
lapsed users, or a product-side habit hook — the latter is a code change
outside this system's reach, same as §4.

---

## 6. Reviews & Ratings

**Symptom:** Low average rating, or a spike in negative reviews after a
release.

**Root cause candidates:** a real regression in that release (check
Crashlytics `topIssues`/`topVersions` filtered to the release date), or an
accumulation of a specific, fixable complaint pattern.

**Diagnostic action:** `app-store get_reviews` (now backed by the real,
authenticated ASC API — see the earlier fix in this session), grouped by
`app_version_name`/date to correlate with releases. `firebase
crashlytics_get_report` (`topVersions`) for the same window.

**Fix pattern:** `app-store reply_to_review` for individual, addressable
complaints — real, public, and irreversible (can only be edited/deleted
after, not silently undone), so this stays a manual/reviewed action, not
something the autonomous loop posts unattended. A rating problem driven by a
real bug isn't fixed by a review reply; it needs the underlying issue fixed
in the app's own code first.

---

## Cross-cutting rule

Never propose a fix on a lever that doesn't match the diagnosed root cause —
this is the actual purpose of this playbook. A keyword-field change doesn't
fix low conversion; a screenshot change doesn't fix low reach; a review reply
doesn't fix a real crash. Match the fix to the diagnosis, and diagnose with
real tool calls (Mobbin, analytics, Crashlytics, keyword volume/difficulty),
not assumption.
