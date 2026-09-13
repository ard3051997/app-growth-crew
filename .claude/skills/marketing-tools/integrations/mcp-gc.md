# MCP-GC — Tool Substitute for Converly / Ploy and the Upstream `tools/` Directory

This library was adapted from [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills)
to run on MCP-GC's own MCP servers. Upstream ships a separate `tools/` directory
(CLI wrappers + `integrations/*.md` docs) covering ~90 third-party marketing/sales
platforms, plus two "Verified Partners" — **Converly** (conversion tracking) and
**Ploy** (AI website builder) — that specific skills lean on. None of that `tools/`
directory was carried over. MCP-GC has no equivalent for Converly or Ploy and none
was invented; where a vendored skill needed one, its `SKILL.md` says so plainly
instead of fabricating a binding (see the Gaps table below).

**Where these tools live in the codebase:** `src/revenuecat_mcp`, `src/analytics_mcp`,
`src/aso_keyword_mcp`, `src/funnel_engine_mcp`, `src/app_store_mcp`, `src/play_store_mcp`,
`src/fcm_push_mcp`, `src/admob_mcp`. `mcp__meta-ads__*`, `mcp__openseo__*`, and
`mcp__mobile-mcp__*` are new servers being added elsewhere in this branch — referenced
here the same way the rest of this library references its bound tools, even though
they may not be live in every worktree yet. See the project's `CLAUDE.md` for the
full server list.

## Capability Matrix

| Capability | MCP-GC Tool | Notes |
|---|---|---|
| Subscription/paywall/offering data | `mcp__revenuecat__get_overview_metrics`, `get_charts`, `list_offerings`, `get_offering`, `get_subscriber`, `get_transaction_history` | First-party, exact — the `paywalls`, `pricing`, `churn-prevention`, `offers` skills all read here first. |
| Subscription/paywall mutation | `mcp__revenuecat__create_offering`, `update_offering`, `create_package`, `attach_product`, `grant_entitlement`, `revoke_entitlement`, `refund_purchase` | **Mutating** — route through the approval gate in `src/app_manager/safety_policies.py`, same as any other MCP-GC write. |
| Paid ads (Meta) | `mcp__meta-ads__*` | Being added elsewhere in this branch. No MCP-GC tool for Google Ads, LinkedIn Ads, or Twitter/X Ads specifically — `ads`/`ad-creative` note this plainly for those platforms. |
| Apple Search Ads | — | Covered by the ASO-tools fork's `apple-search-ads` skill, not this library — prefer it for that channel. |
| ASO-adjacent keyword research | `mcp__aso-keyword__search_keywords`, `get_keyword_volume`, `get_keyword_difficulty`, `get_advanced_keyword_difficulty`, `get_app_keywords`, `get_competitor_keywords`, `get_category_top_apps` | Used by `ads`, `content-strategy`, `launch`, `lead-magnets` for demand validation, not full ASO (see `aso-tools` for that). |
| In-app analytics (GA4/Firebase) | `mcp__analytics__run_report`, `get_events`, `get_active_users`, `get_retention`, `get_user_acquisition`, `get_realtime_report`, `get_revenue_report`, `get_screen_views`, `get_user_demographics` | The mobile equivalent of this library's assumed GTM/Segment/Mixpanel stack. |
| Cross-source funnel health / benchmarks | `mcp__funnel-engine__run_funnel_analysis`, `get_funnel_health_score`, `get_benchmark_comparison`, `get_historical_listing_conversion`, `get_retention_analysis` | Category benchmarks live in `funnel_engine.benchmarks`, same as `aso-tools`. |
| Device/screen automation | `mcp__mobile-mcp__mobile_take_screenshot`, `mobile_list_elements_on_screen`, `mobile_start_screen_recording`, `mobile_stop_screen_recording`, `mobile_type_keys`, `mobile_click_on_screen_at_coordinates`, `mobile_open_url` | Being added elsewhere in this branch. This is the closest thing MCP-GC has to a browser-automation/screenshot tool for the *in-app* flows this library assumes are websites (`cro`, `onboarding`, `signup`, `popups`, `video`, `social`). |
| Image generation | `mcp__image-gen__generate_image` | Used by `image`, `ad-creative`, `video` (for stills/storyboards), `social`. |
| AI-search / site SEO | `mcp__openseo__research_keywords`, `get_serp_results`, `find_serp_competitors`, `run_site_audit`, `get_audit_status`, `get_audit_issues`, `get_audit_pages`, `get_search_console_performance`, `inspect_urls`, `get_domain_overview`, `get_ranked_keywords`, `get_backlinks_overview`, `get_search_opportunities` | Being added elsewhere in this branch. Relevant only for a companion marketing/support website — not the app store listing (that's `aso-tools`' job). |
| Push / re-engagement | `mcp__fcm-push__send_push_notification`, `send_push_to_condition`, `send_push_to_token` | The mobile-native substitute this library uses in place of email/SMS sending wherever one will do. |
| App reviews | `mcp__app-store__get_reviews`, `reply_to_review`; `mcp__play-store__get_reviews`, `reply_to_review` | MCP-GC's primary voice-of-customer source — used by `customer-research`, `copywriting`, `community-marketing`, `public-relations`, `social`. `reply_to_review` is mutating. |
| Store listing data | `mcp__app-store__get_app_details`; `mcp__play-store__get_listing` | Used by `copy-editing`, `public-relations` for exact current published text. |
| Experiment lifecycle | `src/app_manager/experiment_engine.py` (PROPOSED → ACTIVE → CONCLUDED, Welch's t-test, rollback via `rollback_manager.py`); `mcp__play-store__create_store_listing_experiment` | `ab-testing` should route real experiment execution through the engine rather than reinventing significance testing. |

## Gaps — no free equivalent, be upfront about it

Some of what this upstream library assumes (a marketing website, an ESP, an SMS
provider, a social scheduler, a competitor-intelligence database) has no honest
MCP-GC substitute. When a vendored skill needs one of these, its `SKILL.md` says so
plainly and offers the closest available alternative — it does not fabricate a tool.

| Upstream capability | Why there's no substitute | Fallback |
|---|---|---|
| Email sending (`emails`, and the email-delivery half of `lead-magnets`) | No ESP (Klaviyo/Customer.io/Mailchimp/SendGrid) is integrated. | Sequence strategy and copy stay fully usable; bring your own ESP and credentials for delivery. For mobile lifecycle messaging specifically, `mcp__fcm-push__*` often replaces the need for email entirely. |
| SMS/MMS sending (`sms`) | No carrier-connected provider (Twilio/Postscript/Attentive) is integrated. | Strategy and compliance guidance stay usable; bring your own provider. `mcp__fcm-push__*` covers most of the same lifecycle use cases without a third-party account. |
| Social platform posting, scheduling, and listening (`social`) | No Buffer/Hootsuite/native-platform-API binding exists. | Content creation is fully usable; publishing/scheduling/listening are manual or bring-your-own-scheduler. |
| Website building/hosting (`free-tools`, and the "companion website" framing throughout this library) | MCP-GC has no site-building or hosting tool — the portfolio is apps, not websites. | Demand-validation via `mcp__openseo__*`/`mcp__aso-keyword__*` still works; building and hosting the actual tool/page is out of scope. |
| Competitor website scraping, G2/Capterra review mining, backlink-profile depth | No scraping/SEO-data-provider tool of that depth is wired up (the `competitor-profiling` and `competitors` upstream skills were excluded from this fork for exactly this reason — see `../README.md`). | Use `mcp__openseo__get_backlinks_overview` for basic backlink data where relevant; otherwise ask the user to paste competitor pages/screenshots for manual review. |
| Journalist/media-list databases, HARO/Qwoted queries (`public-relations`) | No PR-CRM or journalist database is integrated. | Use `WebSearch`/`WebFetch` for ad hoc research, or bring your own PR tool. |
| AI video generation, AI avatars, and video editing/rendering (`video`, and the video half of `ad-creative`) | No Runway/Veo/Sora/HeyGen/Remotion-class tool is integrated. | `mcp__mobile-mcp__mobile_start_screen_recording` + `mcp__image-gen__generate_image` supply raw screen capture and stills; actual generation/editing is bring-your-own-tool. |
| Design-tool integration (Canva, Figma) referenced by `image` | No dedicated MCP-GC binding here beyond whatever the user's own environment has configured. | Use `mcp__image-gen__generate_image` for AI generation; use a configured Canva/Figma MCP connector directly if present, otherwise treat as manual. |
| Payment-plan/invoicing infrastructure for services/coaching offers (`offers`) | Out of scope for an app-only portfolio — MCP-GC bills through Apple/Google IAP via RevenueCat, not Stripe payment links. | Bring your own tool for offers sold outside the app. |

## Multi-App Note

Same as `aso-tools`: MCP-GC manages a **portfolio**, not a single app. Every skill in
this library should ask (or infer from `config/apps.json` context) which
`package_name` / bundle ID it's operating on before calling any tool above.

## Product/App Marketing Context — two conventions, one source of truth

Every skill in this library checks for `.agents/product-marketing.md` (or
`.claude/product-marketing.md`, or the legacy `product-marketing-context.md`) before
asking questions — that's the upstream convention, created by this library's own
`product-marketing` skill. The `aso-tools` fork has its own, differently-named
equivalent: `app-marketing-context.md` (project root or `.claude/`), created by the
`app-marketing-context` skill, with app-store-specific sections this library's
generic template doesn't have.

Every vendored `SKILL.md` in this library has been updated to check for either file.
If both exist, prefer `app-marketing-context.md` as the source of truth for
MCP-GC apps — don't maintain two independently-edited context docs for the same app.
See `product-marketing/SKILL.md`'s "MCP-GC note" for the reconciliation workflow.
