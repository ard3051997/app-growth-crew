# Tool Registry

Tools and integrations that ASO skills in this library use for real-time App Store /
Play Store data.

> **Fork note:** this is MCP-GC's adaptation of [Eronred/aso-skills](https://github.com/Eronred/aso-skills)
> (MIT licensed). The upstream library binds every skill to the paid **Appeeky** API.
> This fork rebinds every skill to MCP-GC's own MCP servers instead — no external
> API key, no per-request credits. See [mcp-gc.md](integrations/mcp-gc.md) for the
> full capability mapping and the honest list of things we can't replicate for free.

## MCP-GC — Primary Integration

All real-time App Store / Play Store / revenue / funnel data comes from the MCP
servers already running in this project (`src/*_mcp/`). Full details:
[mcp-gc.md](integrations/mcp-gc.md).

### Capability Matrix

| Capability | MCP-GC Tool | Integration Guide |
|-----------|-------------|-------------------|
| App metadata & lookup (own apps) | `mcp__app-store__get_app_details`, `mcp__play-store__get_listing` | [mcp-gc.md](integrations/mcp-gc.md) |
| App metadata (any app / competitors) | `mcp__aso-keyword__analyze_listing_aso`, iTunes Lookup via `WebFetch` | [mcp-gc.md](integrations/mcp-gc.md) |
| User reviews | `mcp__app-store__get_reviews`, `mcp__play-store__get_reviews` | [mcp-gc.md](integrations/mcp-gc.md) |
| App keyword rankings | `mcp__aso-keyword__get_app_keywords` | [mcp-gc.md](integrations/mcp-gc.md) |
| Keyword rank tracking over time | `mcp__aso-keyword__track_keyword_ranking` | [mcp-gc.md](integrations/mcp-gc.md) |
| Single-keyword rank (iOS) | `mcp__app-store__get_keyword_rank` | [mcp-gc.md](integrations/mcp-gc.md) |
| Keyword search volume & difficulty | `mcp__aso-keyword__get_keyword_volume`, `get_keyword_difficulty`, `get_advanced_keyword_difficulty` | [mcp-gc.md](integrations/mcp-gc.md) |
| Keyword suggestions / seed expansion | `mcp__aso-keyword__search_keywords` | [mcp-gc.md](integrations/mcp-gc.md) |
| Competitor keyword gap | `mcp__aso-keyword__get_competitor_keywords` | [mcp-gc.md](integrations/mcp-gc.md) |
| Category top charts | `mcp__aso-keyword__get_category_top_apps` | [mcp-gc.md](integrations/mcp-gc.md) |
| Full ASO audit | `mcp__aso-keyword__analyze_listing_aso` + `score_auto_aso_metadata` | [mcp-gc.md](integrations/mcp-gc.md) |
| Metadata validation | `mcp__aso-keyword__score_auto_aso_metadata` | [mcp-gc.md](integrations/mcp-gc.md) |
| Metadata suggestions | `mcp__aso-keyword__generate_optimized_listing`, `prepare_auto_aso_keywords` | [mcp-gc.md](integrations/mcp-gc.md) |
| Publish a metadata change (mutating) | `mcp__app-store__update_listing`, `mcp__play-store__update_listing` | [mcp-gc.md](integrations/mcp-gc.md) |
| Crash / ANR / stability | `mcp__play-store__get_vitals_overview`, `mcp__firebase__crashlytics_get_report` | [mcp-gc.md](integrations/mcp-gc.md) |
| Own downloads / revenue / MRR / subs | `mcp__revenuecat__get_overview_metrics`, `mcp__analytics__get_revenue_report`, `mcp__admob__get_earnings_summary` | [mcp-gc.md](integrations/mcp-gc.md) |
| Funnel health / conversion / benchmarks | `mcp__funnel-engine__run_funnel_analysis`, `get_funnel_health_score`, `get_benchmark_comparison` | [mcp-gc.md](integrations/mcp-gc.md) |
| Retention / DAU-MAU / cohorts | `mcp__analytics__get_retention`, `get_active_users` | [mcp-gc.md](integrations/mcp-gc.md) |
| Push / re-engagement | `mcp__fcm-push__send_push_notification`, `send_push_to_condition` | [mcp-gc.md](integrations/mcp-gc.md) |
| Competitor UI/UX & screenshot patterns | `mcp__mobbin__search_flows`, `search_screens`, `search_sections` | [mcp-gc.md](integrations/mcp-gc.md) |
| Mockup / hero image generation | `mcp__image-gen__generate_image` | [mcp-gc.md](integrations/mcp-gc.md) |
| Paywall / offering config | `mcp__revenuecat__list_offerings`, `get_offering`, `create_offering`, `create_package` | [mcp-gc.md](integrations/mcp-gc.md) |

> **No free substitute:** competitor download/revenue estimates, market movers/trending
> feeds, and "downloads to reach #1" all require a paid estimation provider (Appeeky
> or similar) that this fork deliberately does not use. See the Gaps table in
> [mcp-gc.md](integrations/mcp-gc.md) — skills should say so explicitly rather than
> guessing a number.

### Skill → Tool Mapping

| Skill | Primary Tools Used |
|-------|-------------------|
| `aso-audit` | `mcp__aso-keyword__analyze_listing_aso`, `score_auto_aso_metadata`, `get_app_keywords` |
| `keyword-research` | `mcp__aso-keyword__search_keywords`, `get_keyword_volume`, `get_keyword_difficulty`, `get_app_keywords` |
| `metadata-optimization` | `mcp__aso-keyword__score_auto_aso_metadata`, `generate_optimized_listing`, `mcp__app-store__get_app_details` |
| `competitor-analysis` | `mcp__aso-keyword__get_competitor_keywords`, `analyze_listing_aso`, `mcp__mobbin__search_screens` |
| `screenshot-optimization` | `mcp__app-store__get_app_details` (own screenshots), `mcp__mobbin__search_screens`, `mcp__image-gen__generate_image` |
| `review-management` | `mcp__app-store__get_reviews`, `mcp__play-store__get_reviews`, `reply_to_review` |
| `localization` | `mcp__aso-keyword__search_keywords`, `get_keyword_volume` (per country) |
| `app-launch` | `mcp__aso-keyword__get_category_top_apps`, `search_keywords`, iTunes Lookup via `WebFetch` |
| `ua-campaign` | `mcp__aso-keyword__get_keyword_volume`, `mcp__analytics__get_user_acquisition` |
| `app-store-featured` | `mcp__app-store__get_app_details`; no automated "featured" feed — manual/editorial research |
| `retention-optimization` | `mcp__analytics__get_retention`, `mcp__app-store__get_reviews` |
| `monetization-strategy` | `mcp__revenuecat__get_overview_metrics`, `mcp__admob__get_earnings_summary` |
| `app-analytics` | `mcp__analytics__run_report`, `mcp__funnel-engine__get_funnel_health_score` |
| `ab-test-store-listing` | `mcp__play-store__create_store_listing_experiment`, `mcp__app-store__get_app_details` |
| `app-marketing-context` | `mcp__app-store__get_app_details`, `mcp__aso-keyword__get_app_keywords` |
| `market-movers` | No free substitute — manual weekly `get_category_top_apps` diffing (see skill for method) |
| `market-pulse` | No free substitute — same manual-diffing approach |
| `asc-metrics` | `mcp__app-store__get_app_details`, `mcp__revenuecat__get_overview_metrics`, `mcp__funnel-engine__run_funnel_analysis` (first-party, exact — see rewritten skill) |
| `seasonal-aso` | `mcp__aso-keyword__search_keywords`, `get_keyword_volume` |
| `in-app-events` | `mcp__aso-keyword__search_keywords`, `mcp__app-store__get_app_details` |
| `android-aso` | `mcp__aso-keyword__search_keywords`, `get_keyword_volume`, `mcp__play-store__get_reviews`, `get_listing` |
| `onboarding-optimization` | `mcp__analytics__get_retention`, `mcp__app-store__get_reviews`, `mcp__mobbin__search_flows` |
| `rating-prompt-strategy` | `mcp__app-store__get_reviews`, `mcp__play-store__get_reviews` |
| `app-icon-optimization` | `mcp__mobbin__search_screens`, `mcp__image-gen__generate_image` |
| `subscription-lifecycle` | `mcp__revenuecat__get_subscriber`, `get_transaction_history` |
| `app-clips` | `mcp__aso-keyword__track_keyword_ranking`, `mcp__app-store__get_app_details` |
| `apple-search-ads` | `mcp__aso-keyword__get_keyword_volume`, `search_keywords` |
| `press-and-pr` | `mcp__app-store__get_app_details`; press-list research is manual |
| `competitor-tracking` | `mcp__aso-keyword__get_competitor_keywords`, `mcp__app-store__get_reviews`, `mcp__aso-keyword__get_category_top_apps` (manual weekly diff) |
| `crash-analytics` | `mcp__play-store__get_vitals_overview`, `mcp__firebase__crashlytics_get_report`, `list_events` |
| `paywall-optimization` | `mcp__revenuecat__get_overview_metrics`, `list_offerings`, `mcp__app-store__get_reviews` |
| `app-preview-video` | `mcp__image-gen__generate_image`, `mcp__mobbin__search_flows` |
| `attribution-setup` | — (configuration skill, not data-driven) |
| `custom-product-pages` | `mcp__app-store__get_app_details`, `mcp__play-store__create_store_listing_experiment` |
| `app-rejection-recovery` | — (Apple/Google reviewer-facing, no external data) |
| `referral-program` | `mcp__analytics__get_user_acquisition`, `mcp__revenuecat__get_overview_metrics` |
| `creator-ugc-marketing` | `mcp__app-store__get_reviews`, `mcp__mobbin__search_flows` |
| `web-to-app-funnel` | `mcp__funnel-engine__run_funnel_analysis`, `mcp__analytics__get_user_acquisition` |
| `category-positioning` | `mcp__aso-keyword__get_category_top_apps`, `mcp__app-store__get_app_details` |
| `aso-router` | — (router; loads other skills) |

## Other Useful Tools

| Tool | Purpose | Integration |
|------|---------|-------------|
| **App Store Connect** | Official Apple analytics, releases, IAP management | [app-store-connect.md](integrations/app-store-connect.md) |
| **RevenueCat** | Subscription analytics, paywall A/B testing — already integrated as `mcp__revenuecat__*` | [revenuecat.md](integrations/revenuecat.md) |
| **Firebase** | In-app analytics, crash reporting, A/B testing — Crashlytics already integrated as `mcp__firebase__*` | [firebase.md](integrations/firebase.md) |
