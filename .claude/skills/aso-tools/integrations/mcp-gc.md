# MCP-GC — Own-Portfolio Tool Substitute for Appeeky

This library was adapted to run entirely on MCP-GC's own MCP servers instead of the
paid Appeeky API. Every skill in `.claude/skills/` that originally called an Appeeky
REST endpoint or MCP tool has been repointed at one of the tools below. There is no
Appeeky account, API key, or credit budget involved anywhere in this fork.

**Where these tools live in the codebase:** `src/aso_keyword_mcp`, `src/app_store_mcp`,
`src/play_store_mcp`, `src/revenuecat_mcp`, `src/analytics_mcp`, `src/admob_mcp`,
`src/funnel_engine_mcp`. See the project's `CLAUDE.md` for the full server list.

## Capability Matrix

| Capability | MCP-GC Tool | Notes |
|---|---|---|
| App metadata (title, description, screenshots, rating) — **our own apps** | `mcp__app-store__get_app_details`, `mcp__play-store__get_listing` | First-party, exact. |
| App metadata — **any App Store app incl. competitors** | `mcp__aso-keyword__analyze_listing_aso` (Play Store scrape-backed `ASOClient`) | Covers Play Store listings well. iOS competitor metadata: use iTunes Lookup API via `WebFetch` (`https://itunes.apple.com/lookup?id=...`) — free, no key. |
| Keyword search volume & difficulty | `mcp__aso-keyword__get_keyword_volume`, `mcp__aso-keyword__get_keyword_difficulty`, `mcp__aso-keyword__get_advanced_keyword_difficulty` | Backed by `APPFOLLOW_API_KEY` (already configured) with heuristic fallback if unset. |
| Keyword suggestions / seed expansion | `mcp__aso-keyword__search_keywords` | |
| App's current ranked keywords | `mcp__aso-keyword__get_app_keywords` | |
| Keyword rank tracking over time | `mcp__aso-keyword__track_keyword_ranking` | Persists to the funnel-engine DB for trend charts. |
| Single-keyword rank lookup (iOS) | `mcp__app-store__get_keyword_rank` | Exact App Store Search rank for one keyword/country. |
| Competitor keyword gap | `mcp__aso-keyword__get_competitor_keywords` | |
| Category top charts | `mcp__aso-keyword__get_category_top_apps` | |
| Full ASO audit / scoring | `mcp__aso-keyword__analyze_listing_aso` + `mcp__aso-keyword__score_auto_aso_metadata` | Combine both for the equivalent of Appeeky's `aso_full_audit`. |
| Metadata suggestions / rewrite | `mcp__aso-keyword__generate_optimized_listing`, `mcp__aso-keyword__prepare_auto_aso_keywords` | |
| Metadata validation (char limits, keyword stuffing) | `mcp__aso-keyword__score_auto_aso_metadata` | |
| Publish a metadata change | `mcp__app-store__update_listing` (iOS), `mcp__play-store__update_listing` / `update_listing_images` (Android) | **Mutating** — respect the same approval flow as `src/app_manager/safety_policies.py`; never call directly without user confirmation. |
| User reviews — our own apps | `mcp__app-store__get_reviews`, `mcp__play-store__get_reviews` | |
| Reply to a review | `mcp__app-store__reply_to_review`, `mcp__play-store__reply_to_review` | Mutating. |
| Crash / ANR stability data | `mcp__play-store__get_vitals_overview`, `mcp__play-store__get_vitals_metrics`, `mcp__firebase__crashlytics_get_report`, `mcp__firebase__crashlytics_list_events` | Matches the same crash-rate signal the autonomous loop's safety scan already watches. |
| Our own downloads / revenue / MRR / subscriptions | `mcp__revenuecat__get_overview_metrics`, `get_charts`, `get_subscriber`, `get_transaction_history`; `mcp__analytics__get_revenue_report`; `mcp__admob__get_earnings_summary` | Exact first-party data — strictly better than Appeeky Connect's synced estimate, and already wired into the nightly snapshot pipeline (`src/run_autonomous_loop.py`). |
| Funnel health / storefront conversion / benchmarks | `mcp__funnel-engine__run_funnel_analysis`, `get_funnel_health_score`, `get_benchmark_comparison`, `get_historical_listing_conversion`, `get_retention_analysis` | Category benchmarks already live in `funnel_engine.benchmarks`. |
| Retention / DAU-MAU / cohort data | `mcp__analytics__get_retention`, `get_active_users`, `get_user_acquisition` | |
| Push / re-engagement campaigns | `mcp__fcm-push__send_push_notification`, `send_push_to_condition`, `send_push_to_token` | |
| UI/UX pattern research (paywalls, onboarding, screenshots) | `mcp__mobbin__search_flows`, `search_screens`, `search_sections` | This is the closest free substitute for Appeeky's competitor-screenshot endpoint — search by app category or flow type instead of pulling one competitor's exact screenshots. |
| Mockup / hero image generation | `mcp__image-gen__generate_image` | For screenshot and App Preview video concepting. |
| Offering / paywall config | `mcp__revenuecat__list_offerings`, `get_offering`, `create_offering`, `update_offering`, `create_package`, `attach_product` | |

## Gaps — no free equivalent, be upfront about it

Appeeky's estimate-based endpoints have no honest substitute in this project. When a
skill needs one of these, say so plainly and offer a manual alternative — do not
fabricate a number.

| Appeeky capability | Why there's no substitute | Fallback |
|---|---|---|
| `get_app_intelligence` — estimated downloads/revenue for **any** app (esp. competitors) | We only have first-party RevenueCat/AdMob/GA4 data for *our own* apps. There is no free, reliable download/revenue estimator for third-party apps. | Use public signals instead: chart rank (via `get_category_top_apps`), review velocity, rating count trend. State explicitly that the number is a rank-based proxy, not a revenue estimate. |
| `get_market_movers` / `get_market_activity` / `get_new_releases` / `discover` / `get_new_number_1` | No free market-wide movement feed exists. | Track manually: snapshot `get_category_top_apps` weekly yourself and diff it (see `competitor-tracking` skill). |
| `get_trending_keywords` | No free trending-keyword feed. | Use `search_keywords` seeded from current news/season + `get_keyword_volume` to confirm real demand before committing. |
| `get_downloads_to_top` (est. installs/day to rank #1) | Same estimation problem as above. | Approximate qualitatively from category churn observed via weekly `get_category_top_apps` snapshots. |
| Competitor screenshots (pixel images) | No scraping tool for a competitor's actual screenshot assets is wired up. | Use `mcp__mobbin__search_screens`/`search_flows` for comparable-category screenshot patterns, or ask the user to paste competitor screenshots for direct visual review. |

## Multi-App Note

MCP-GC manages a **portfolio**, not a single app. Every skill should ask (or infer from
`config/apps.json` context) which `package_name` / bundle ID it's operating on before
calling any tool above — there is no implicit "current app."
