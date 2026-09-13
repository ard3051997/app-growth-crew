# Tool Registry

Tools and integrations that the marketing skills in this library use for real app,
revenue, and analytics data.

> **Fork note:** this is MCP-GC's adaptation of [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills)
> (MIT licensed — see [LICENSE](LICENSE)). The upstream library is written for
> websites/SaaS/B2B and binds a handful of skills to two "Verified Partners" —
> **Converly** (conversion tracking) and **Ploy** (AI website builder) — via a
> separate `tools/` directory of CLI wrappers and integration docs that was not
> carried over. Neither partner has an MCP-GC equivalent and none was fabricated;
> where a skill needed one of them, the vendored `SKILL.md` says so plainly instead
> (see the Gaps table in [mcp-gc.md](integrations/mcp-gc.md)). See
> [README.md](README.md) for what was excluded from the ~49-skill upstream set and why.

## MCP-GC — Primary Integration

All real app, revenue, and analytics data comes from the MCP servers already running
in this project (`src/*_mcp/`), the same ones the [`aso-tools`](../aso-tools/) fork
uses. Full details: [mcp-gc.md](integrations/mcp-gc.md).

### Capability Matrix

| Capability | MCP-GC Tool | Integration Guide |
|-----------|-------------|-------------------|
| Subscription/paywall data & mutation | `mcp__revenuecat__get_overview_metrics`, `list_offerings`, `get_offering`, `get_subscriber`, `get_transaction_history`, `create_offering`, `update_offering`, `create_package`, `attach_product`, `grant_entitlement`, `revoke_entitlement`, `refund_purchase` | [mcp-gc.md](integrations/mcp-gc.md) |
| Paid ads (Meta) | `mcp__meta-ads__*` (being added elsewhere in this branch) | [mcp-gc.md](integrations/mcp-gc.md) |
| ASO-adjacent keyword research | `mcp__aso-keyword__search_keywords`, `get_keyword_volume`, `get_keyword_difficulty`, `get_app_keywords`, `get_competitor_keywords`, `get_category_top_apps` | [mcp-gc.md](integrations/mcp-gc.md) |
| In-app analytics (GA4/Firebase) | `mcp__analytics__run_report`, `get_events`, `get_active_users`, `get_retention`, `get_user_acquisition`, `get_realtime_report`, `get_revenue_report`, `get_screen_views`, `get_user_demographics` | [mcp-gc.md](integrations/mcp-gc.md) |
| Cross-source funnel / benchmarking | `mcp__funnel-engine__run_funnel_analysis`, `get_funnel_health_score`, `get_benchmark_comparison`, `get_historical_listing_conversion`, `get_retention_analysis` | [mcp-gc.md](integrations/mcp-gc.md) |
| Device/screen automation (onboarding, signup, screenshots, screen recording) | `mcp__mobile-mcp__mobile_take_screenshot`, `mobile_list_elements_on_screen`, `mobile_start_screen_recording`, `mobile_stop_screen_recording`, `mobile_type_keys`, `mobile_click_on_screen_at_coordinates` | [mcp-gc.md](integrations/mcp-gc.md) |
| Image generation | `mcp__image-gen__generate_image` | [mcp-gc.md](integrations/mcp-gc.md) |
| AI-search / site SEO (companion website) | `mcp__openseo__research_keywords`, `get_serp_results`, `run_site_audit`, `get_search_console_performance`, `get_domain_overview`, `get_ranked_keywords`, `get_backlinks_overview`, `find_serp_competitors` (being added elsewhere in this branch) | [mcp-gc.md](integrations/mcp-gc.md) |
| Push / re-engagement | `mcp__fcm-push__send_push_notification`, `send_push_to_condition`, `send_push_to_token` | [mcp-gc.md](integrations/mcp-gc.md) |
| App reviews (voice of customer, community, PR) | `mcp__app-store__get_reviews`, `reply_to_review`; `mcp__play-store__get_reviews`, `reply_to_review` | [mcp-gc.md](integrations/mcp-gc.md) |
| Store listing data | `mcp__app-store__get_app_details`; `mcp__play-store__get_listing` | [mcp-gc.md](integrations/mcp-gc.md) |
| Experiment lifecycle (A/B tests) | `src/app_manager/experiment_engine.py` (PROPOSED → ACTIVE → CONCLUDED, Welch's t-test); `mcp__play-store__create_store_listing_experiment` | [mcp-gc.md](integrations/mcp-gc.md) |

> **No free substitute:** competitor website scraping/G2/backlink-profile depth,
> journalist/media-list databases, ESP (email) sending, SMS/MMS sending, social
> platform posting/scheduling/listening, and AI video/avatar generation all require
> a paid third-party provider this fork deliberately does not bundle. See the Gaps
> table in [mcp-gc.md](integrations/mcp-gc.md) — skills say so explicitly rather
> than guessing or inventing a tool.

### Skill → Tool Mapping

| Skill | Primary Tools Used |
|-------|-------------------|
| `paywalls` | `mcp__revenuecat__list_offerings`, `get_offering`, `get_overview_metrics`, `get_transaction_history`, `create_offering`, `update_offering`, `create_package`; `mcp__mobile-mcp__mobile_take_screenshot` |
| `pricing` | `mcp__revenuecat__list_offerings`, `get_offering`, `get_overview_metrics`, `get_charts`, `create_offering`, `update_offering`, `create_package` |
| `churn-prevention` | `mcp__revenuecat__get_subscriber`, `get_transaction_history`, `get_overview_metrics`, `refund_purchase`, `revoke_entitlement`, `grant_entitlement`; `mcp__fcm-push__send_push_to_condition` |
| `offers` | `mcp__revenuecat__list_offerings`, `create_offering`, `create_package`, `get_overview_metrics` |
| `ads` | `mcp__meta-ads__*` (pending); `mcp__aso-keyword__get_keyword_volume`, `search_keywords`; `mcp__analytics__get_user_acquisition`; `mcp__funnel-engine__run_funnel_analysis`, `get_benchmark_comparison` |
| `ad-creative` | `mcp__image-gen__generate_image`; `mcp__meta-ads__*` (pending); `mcp__mobile-mcp__mobile_take_screenshot`, `mobile_start_screen_recording` |
| `analytics` | `mcp__analytics__run_report`, `get_events`, `get_active_users`, `get_retention`, `get_user_acquisition`, `get_realtime_report` |
| `attribution` | `mcp__analytics__get_user_acquisition`; `mcp__funnel-engine__run_funnel_analysis`, `get_historical_listing_conversion`; `mcp__revenuecat__get_overview_metrics` |
| `cro` | `mcp__mobile-mcp__mobile_take_screenshot`, `mobile_list_elements_on_screen`; `mcp__funnel-engine__run_funnel_analysis`; `mcp__analytics__get_retention`; `mcp__play-store__create_store_listing_experiment` |
| `onboarding` | `mcp__mobile-mcp__mobile_take_screenshot`, `mobile_list_elements_on_screen`; `mcp__analytics__get_retention`, `get_events`; `mcp__funnel-engine__run_funnel_analysis` |
| `signup` | `mcp__mobile-mcp__mobile_take_screenshot`, `mobile_list_elements_on_screen`, `mobile_type_keys`; `mcp__funnel-engine__run_funnel_analysis`; `mcp__analytics__get_events`; `mcp__revenuecat__get_overview_metrics` |
| `popups` | `mcp__mobile-mcp__mobile_take_screenshot`, `mobile_list_elements_on_screen`; `mcp__funnel-engine__run_funnel_analysis` (defers to `paywalls` / `rating-prompt-strategy` for the actual UI) |
| `ai-seo` | `mcp__openseo__get_search_console_performance`, `get_serp_results`, `find_serp_competitors`, `research_keywords`, `run_site_audit` (pending) |
| `seo-audit` | `mcp__openseo__run_site_audit`, `get_audit_status`, `get_audit_issues`, `get_audit_pages`, `get_search_console_performance`, `inspect_urls`, `get_domain_overview`, `get_ranked_keywords`, `get_backlinks_overview` (pending) |
| `referrals` | `mcp__analytics__get_user_acquisition`; `mcp__revenuecat__get_overview_metrics`, `grant_entitlement`; `mcp__fcm-push__send_push_to_condition` |
| `lead-magnets` | `mcp__fcm-push__send_push_to_condition`; `mcp__aso-keyword__search_keywords`, `get_keyword_volume` |
| `community-marketing` | `mcp__app-store__get_reviews`, `reply_to_review`; `mcp__play-store__get_reviews`, `reply_to_review`; `mcp__fcm-push__send_push_to_condition`; `mcp__analytics__get_active_users`, `get_retention` |
| `public-relations` | `mcp__app-store__get_reviews`, `get_app_details`; `mcp__play-store__get_reviews`, `get_listing`; `mcp__revenuecat__get_overview_metrics` |
| `image` | `mcp__image-gen__generate_image` |
| `video` | `mcp__mobile-mcp__mobile_start_screen_recording`, `mobile_stop_screen_recording`; `mcp__image-gen__generate_image` |
| `social` | `mcp__image-gen__generate_image`; `mcp__mobile-mcp__mobile_start_screen_recording`, `mobile_take_screenshot`; `mcp__app-store__get_reviews`; `mcp__play-store__get_reviews`; `mcp__revenuecat__get_overview_metrics` |
| `ab-testing` | `src/app_manager/experiment_engine.py`; `mcp__play-store__create_store_listing_experiment`; `mcp__revenuecat__create_offering`, `update_offering`; `mcp__funnel-engine__run_funnel_analysis`, `get_benchmark_comparison` |
| `content-strategy` | `mcp__openseo__research_keywords`, `get_search_opportunities` (pending); `mcp__aso-keyword__search_keywords`, `get_keyword_volume`; `mcp__app-store__get_reviews`; `mcp__play-store__get_reviews` |
| `copy-editing` | `mcp__app-store__get_app_details`; `mcp__play-store__get_listing`; `mcp__aso-keyword__score_auto_aso_metadata` |
| `copywriting` | `mcp__app-store__get_reviews`; `mcp__play-store__get_reviews`; `mcp__revenuecat__get_overview_metrics` |
| `customer-research` | `mcp__app-store__get_reviews`; `mcp__play-store__get_reviews`; `mcp__analytics__get_user_demographics`, `get_events`, `get_screen_views`; `mcp__funnel-engine__run_funnel_analysis` |
| `emails` | No sending tool (bring your own ESP) — `mcp__revenuecat__get_subscriber`, `get_overview_metrics`; `mcp__analytics__get_events`, `get_retention` inform segmentation/triggers |
| `free-tools` | `mcp__openseo__research_keywords`, `get_search_opportunities` (pending); mostly out of scope (no website-hosting tool) |
| `influencer-marketing` | `mcp__app-store__get_reviews`; `mcp__play-store__get_reviews`; `mcp__analytics__get_user_acquisition`; `mcp__revenuecat__get_overview_metrics` |
| `launch` | `mcp__aso-keyword__get_category_top_apps`, `search_keywords`; `mcp__fcm-push__send_push_to_condition`; `mcp__analytics__get_realtime_report`, `get_user_acquisition`; `mcp__revenuecat__get_overview_metrics` |
| `marketing-council` | No dedicated tool (persona-simulation skill) — pulls whatever tool the question at hand needs (e.g. `mcp__revenuecat__get_overview_metrics`, `mcp__analytics__get_retention`) |
| `marketing-ideas` | `mcp__funnel-engine__get_funnel_health_score`; `mcp__analytics__get_retention` (to target idea selection at the real bottleneck) |
| `marketing-loops` | Orchestrates other skills' tools; scheduling via `src/run_autonomous_loop.py` or the `/loop` Claude Code skill |
| `marketing-plan` | `mcp__analytics__get_user_acquisition`, `get_events`, `get_retention`, `get_active_users`; `mcp__aso-keyword__get_keyword_volume`; `mcp__funnel-engine__run_funnel_analysis`; `mcp__revenuecat__get_overview_metrics`; `mcp__admob__get_earnings_summary` |
| `marketing-psychology` | `mcp__revenuecat__get_overview_metrics`, `create_offering`, `update_offering`; `mcp__funnel-engine__run_funnel_analysis` (to validate a model actually moved behavior) |
| `product-marketing` | Reconciles with MCP-GC's own `app-marketing-context` skill/doc — no separate tool of its own |
| `sms` | No MCP-GC tool (bring your own Twilio/Postscript/Attentive) — see `mcp__fcm-push__*` for the mobile-native alternative |

## Other Useful Tools

| Tool | Purpose | Integration |
|------|---------|-------------|
| **RevenueCat** | Subscription analytics, paywall/pricing experiments — already integrated as `mcp__revenuecat__*` | [../aso-tools/integrations/revenuecat.md](../aso-tools/integrations/revenuecat.md) |
| **Firebase** | In-app analytics, crash reporting — already integrated as `mcp__firebase__*` | [../aso-tools/integrations/firebase.md](../aso-tools/integrations/firebase.md) |
| **App Store Connect** | Reviews, listing data, metrics — already integrated as `mcp__app-store__*` | [../aso-tools/integrations/app-store-connect.md](../aso-tools/integrations/app-store-connect.md) |

See [`../aso-tools/REGISTRY.md`](../aso-tools/REGISTRY.md) for the ASO-specific skill
library's own (larger) capability matrix — the two registries share the same
underlying MCP servers and are meant to be used together.
