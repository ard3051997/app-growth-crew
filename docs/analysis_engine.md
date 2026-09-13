# Analysis Engine - Detailed

## Product Requirements Document: Mobile App Growth Analysis Engine

### Executive Summary

A SaaS platform that connects to app store consoles, ad platforms, and analytics to automatically identify funnel leaks and prioritize growth opportunities for mobile app developers.

---

## PRD 1: Data Integration Layer

### Overview

The foundational layer that connects to all external data sources, normalizes data, and stores it for analysis.

### Problem Statement

Mobile app growth data lives in 5-10 different platforms. Developers spend hours manually exporting CSVs, building spreadsheets, and trying to correlate data across sources. By the time they have insights, the data is stale.

### Target Users

**Primary:** Indie developers with 1-5 apps, limited time, need automated insights
**Secondary:** Growth teams at startups (2-10 people), need granular data and custom views

### User Stories

| **ID** | **As a…** | **I want to…** | **So that…** |
| --- | --- | --- | --- |
| U1 | Developer | Connect my Play Console in 2 clicks | I don't need to figure out complex API setups |
| U2 | Developer | See all my apps in one dashboard | I don't switch between 5 tabs |
| U3 | Growth lead | Connect multiple ad accounts | I can see unified CAC across channels |
| U4 | Developer | Have data refresh automatically | I always see current numbers |
| U5 | Developer | Trust the data accuracy | I can make decisions confidently |

### Integrations Specification

### Phase 1 Integrations (MVP)

**1. Google Play Console**

```json
Authentication: OAuth 2.0 (Google Cloud Project)
API: Google Play Developer Reporting API v1
Data Points:
  - Store listing performance (impressions, visitors, installers)
  - Acquisition reports (by country, source, device)
  - Ratings and reviews
  - Crash and ANR rates
  - Revenue and subscriptions (if applicable)
Sync Frequency: Every 6 hours
Historical Data: Last 12 months on first sync
```

**2. App Store Connect**

```json
Authentication: App Store Connect API Key (JWT)
API: App Store Connect API v2
Data Points:
  - App Analytics (impressions, product page views, downloads)
  - Sales and Trends (units, proceeds, subscriptions)
  - Source type breakdown (App Store Browse, Search, Web Referrer)
Sync Frequency: Every 6 hours (Apple has 24-48hr data lag)
Historical Data: Last 12 months on first sync
```

**3. Google Ads**

```json
Authentication: OAuth 2.0 (Google Ads API)
API: Google Ads API v15
Data Points:
  - Campaign performance (impressions, clicks, conversions, cost)
  - Ad group and ad creative performance
  - App campaign specific metrics (installs, in-app actions)
  - Audience and demographic breakdowns
Sync Frequency: Every 4 hours
Historical Data: Last 12 months on first sync
```

**4. Google Analytics 4 (Firebase)**

```json
Authentication: OAuth 2.0 (Google Cloud)
API: GA4 Data API v1
Data Points:
  - User acquisition (first_open, source/medium)
  - Engagement (session duration, screens per session)
  - Retention cohorts
  - Custom events (onboarding steps, paywall views, purchases)
  - Funnel analysis data
Sync Frequency: Every 4 hours
Historical Data: Last 12 months on first sync
```

### Phase 2 Integrations (Post-MVP)

- Meta Ads API
- Apple Search Ads
- Adjust / AppsFlyer
- RevenueCat
- Mixpanel / Amplitude

### Data Schema

SQL

### **1. Core Entities**

**Apps**

```
apps (
  id,
  user_id,
  name,
  platform,              -- iOS, Android, Cross-platform
  bundle_id,
  play_store_id,
  app_store_id,
  category,
  created_at
)

```

---

### **2. Connections**

**Integrations**

```
integrations (
  id,
  user_id,
  platform,              -- 'play_console', 'app_store', 'google_ads', 'ga4'
  credentials_encrypted,
  status,                -- 'active', 'error', 'expired'
  last_sync_at,
  error_message
)

```

---

### **3. Normalized Metrics (Daily Grain)**

**Daily Metrics**

```
daily_metrics (
  id,
  app_id,
  date,
  source_platform,

  -- Acquisition (TOFU)
  impressions,
  store_views,
  installs,
  organic_installs,
  paid_installs,

  -- Advertising
  ad_spend,
  ad_impressions,
  ad_clicks,
  ad_installs,
  cpi,

  -- Engagement (MOFU / BOFU)
  dau,
  wau,
  mau,
  sessions,
  avg_session_duration,

  -- Revenue
  revenue,
  paying_users,
  arpu,
  arppu,

  -- Retention
  d1_retention,
  d7_retention,
  d30_retention
)

```

---

### **4. Funnel Events (Onboarding / Paywall / Subscription)**

**Funnel Events**

```
funnel_events (
  id,
  app_id,
  date,
  funnel_name,           -- 'onboarding', 'paywall', 'subscription'
  step_name,
  step_order,
  users_entered,
  users_completed,
  conversion_rate
)

```

---

### **5. Ad Creative Performance**

**Ad Creatives**

```
ad_creatives (
  id,
  app_id,
  integration_id,
  campaign_id,
  campaign_name,
  ad_group_id,
  ad_group_name,
  creative_id,
  creative_type,         -- 'image', 'video', 'html5'
  creative_url,
  date,
  impressions,
  clicks,
  installs,
  spend,
  cpi
)

```

---

### **Technical Architecture**

```
┌─────────────────────────────────────────────────────────┐
│                     User Browser                         │
└───────────────────────┬──────────────────────────────────┘
                ▼
┌─────────────────────────────────────────────────────────┐
│                 Next.js Frontend (Vercel)               │
│  Dashboard, Connections, Visualizations                 │
└───────────────────────┬──────────────────────────────────┘
                ▼
┌─────────────────────────────────────────────────────────┐
│                     Supabase Backend                    │
│ ┌─────────────┐  ┌─────────────┐  ┌──────────────┐     │
│ │ Auth (OAuth)│  │ Postgres DB │  │ Edge Functions│     │
│ └─────────────┘  └─────────────┘  └──────────────┘     │
└───────────────────────┬──────────────────────────────────┘
                ▼
┌─────────────────────────────────────────────────────────┐
│          Background Sync Workers (Cloudflare)           │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌─────────┐ │
│  │ Play Store│ │ App Store │ │Google Ads │ │  GA4    │ │
│  │  Syncer   │ │  Syncer   │ │  Syncer   │ │ Syncer  │ │
│  └─────┬─────┘ └─────┬─────┘ └─────┬─────┘ └────┬────┘ │
└────────┼──────────────┼─────────────┼────────────┼──────┘
         ▼              ▼             ▼            ▼
   Google Play      Apple API     Google Ads     GA4 API
      API              API           API

```

---

### **Non-Functional Requirements**

| Requirement | Target |
| --- | --- |
| Data freshness | **< 6 hours** for all sources |
| Sync reliability | **99.5% successful syncs** |
| Historical backfill | **< 1 hour** on new connection |
| API rate limits | **Never hit limits** (smart backoff) |
| Data accuracy | **99.9%** match with source data |
| Credential security | **AES-256 encrypted**, no plaintext |

---

### **Success Metrics**

- **Time to first connection:** < 3 minutes
- **Connection success rate:** > 90% on first attempt
- **Data sync success rate:** > 99%
- **User activation:** > 60% connect 2+ sources

---

# **PRD 2: Funnel Analysis Engine**

## **Overview**

The intelligence layer that transforms raw data into actionable insights—highlighting funnel leaks, prioritizing issues, and quantifying impact.

## **Problem Statement**

Developers can see metrics but not meaning. They don’t know:

- whether their paywall conversion is good or bad,
- which part of the funnel is broken,
- where to focus for maximum revenue lift.

---

## **Core Analysis Modules**

### **Module 1: Funnel Leak Detection**

**Inputs:**

- Daily metrics
- Funnel events

**Output:**

- Ranked list of funnel leaks with revenue impact

**Logic:**

```
1. Define master funnel:
   Impression → Store View → Install → Day 1 Active →
   Onboarding Complete → Paywall View → Trial Start →
   Paid Conversion → Day 7 Retained → Day 30 Retained

2. Calculate conversion rate between each step.

3. Benchmark each step (category, region, platform).

4. Compute leak_cost:
   leak_cost = (benchmark_rate - actual_rate)
               × users_at_step
               × LTV

5. Rank leaks by descending leak_cost.

```

**Output Format:**

json

`{
  "analysis_date": "2025-11-27",
  "app_id": "com.example.app",
  "funnel_health_score": 62,
  "leaks": [
    {
      "rank": 1,
      "stage": "Onboarding Step 3 → Step 4",
      "your_rate": "34%",
      "benchmark_rate": "67%",
      "gap": "-33%",
      "users_lost_daily": 1240,
      "monthly_revenue_impact": "₹3,72,000",
      "priority": "critical",
      "insight": "Users drop off at the permission request screen. Consider delaying permissions or explaining value better."
    },
    {
      "rank": 2,
      "stage": "Store View → Install",
      "your_rate": "28%",
      "benchmark_rate": "35%",
      "gap": "-7%",
      "users_lost_daily": 890,
      "monthly_revenue_impact": "₹1,45,000",
      "priority": "high",
      "insight": "Store conversion below category average. Screenshots and description may need optimization."
    }
  ]
}
````

### Module 2: Channel Efficiency Analysis

`**Input:** Ad creative data + install attribution + downstream metrics
**Output:** True CAC and ROAS by channel, campaign, creative
```

**Analysis Logic:**

1. For each channel/campaign/creative:
   - Calculate CPI (Cost per Install)
   - Track cohort through funnel
   - Calculate true CAC (Cost per Paying User)
   - Calculate LTV:CAC ratio
   - Calculate payback period

2. Identify:
   - Best performing creatives (scale these)
   - Worst performing creatives (pause these)
   - Channels with best unit economics`

**Output Format:**

json

`{
  "channels": [
    {
      "channel": "Google Ads - UAC",
      "spend_30d": "₹2,50,000",
      "installs": 8500,
      "cpi": "₹29.41",
      "paying_users": 127,
      "true_cac": "₹1,968",
      "avg_ltv": "₹2,400",
      "ltv_cac_ratio": 1.22,
      "payback_days": 45,
      "recommendation": "Profitable but thin margins. Optimize creatives to improve CPI."
    }
  ],
  "top_creatives": [...],
  "creatives_to_pause": [...]
}`

`#### Module 3: Retention & Cohort Analysis

**Input:** GA4 retention data, daily active users
**Output:** Retention curves, cohort comparisons, churn prediction
```
Analysis Logic:

1. Build retention curves (D1, D7, D14, D30, D60, D90)
2. Compare cohorts:
   - By acquisition source
   - By time period (week over week)
   - By user segment (if available)
3. Identify:
   - Which sources have best retention
   - Whether retention is improving or declining
   - Critical drop-off days
```

#### Module 4: Benchmark Comparison

**Input:** All metrics
**Output:** Percentile ranking vs category benchmarks
```
Benchmark Data Sources:
- Public reports (Adjust, AppsFlyer, Liftoff annual reports)
- Aggregated anonymous data from platform users (with consent)
- Category-specific benchmarks (Games vs Productivity vs Health)

Metrics Benchmarked:
- Store conversion rate
- CPI by channel
- D1, D7, D30 retention
- Paywall conversion rate
- Trial to paid conversion
- ARPU
```

### Insight Generation (AI Layer)

For each analysis output, generate human-readable insights:
```
Prompt Template:

Given this mobile app funnel data:
{metrics_json}

Category: {app_category}
Region: {primary_region}

Generate 3 actionable insights that:
1. Explain what the data means in plain English
2. Prioritize by revenue impact
3. Suggest specific actions to improve

Keep tone friendly but direct. Assume reader is a busy developer.
```

### Dashboard Views

**1. Health Score Overview**
- Single score (0-100) representing overall funnel health
- Trend over time
- Top 3 issues to fix

**2. Funnel Visualization**
- Visual funnel with conversion rates at each step
- Red/yellow/green indicators vs benchmarks
- Click to drill down

**3. Channel Performance**
- Table view of all channels
- Sortable by CPI, CAC, ROAS
- Creative thumbnails with performance

**4. Retention Curves**
- Interactive retention chart
- Compare by cohort, source, time period

**5. Recommendations Feed**
- Prioritized list of actions
- Mark as done / dismissed
- Track impact after implementation

### Success Metrics

- Time to first insight: < 30 seconds after data sync
- Insight accuracy: > 80% user agreement (via feedback)
- Action rate: > 40% of recommendations acted on
- Retention impact: Users who act on insights retain better

---

## PRD 3: User Interface & Experience

### Overview

The interface layer that makes complex data accessible to both indie developers and growth teams.

### Design Principles

1. **Progressive disclosure** - Simple view by default, details on demand
2. **Insight-first** - Lead with "what to do" not "here's data"
3. **Mobile-friendly** - Developers check metrics on their phone
4. **Fast** - Dashboard loads in < 2 seconds

### Information Architecture
```
├── Dashboard (Home)
│   ├── Health Score
│   ├── Key Metrics (Today vs Yesterday)
│   ├── Top Issues
│   └── Quick Actions
│
├── Funnel Analysis
│   ├── Full Funnel View
│   ├── Stage Deep Dives
│   └── Historical Trends
│
├── Acquisition
│   ├── Channel Overview
│   ├── Campaign Drilldown
│   ├── Creative Performance
│   └── ASO Metrics
│
├── Engagement
│   ├── Retention Cohorts
│   ├── User Segments
│   └── Feature Adoption
│
├── Revenue
│   ├── Overview
│   ├── Subscription Analytics
│   └── LTV Analysis
│
├── Recommendations
│   ├── Active
│   ├── Completed
│   └── Dismissed
│
├── Settings
│   ├── Integrations
│   ├── Apps
│   ├── Team
│   └── Billing
```

### Key Screens

**1. Onboarding Flow**
```
Step 1: "What's your app?"
  - Search Play Store / App Store
  - Auto-detect bundle ID

Step 2: "Connect your data"
  - Play Console (OAuth button)
  - App Store Connect (API key upload)
  - Google Ads (OAuth button)
  - GA4 (OAuth button)
  - Show which data each provides

Step 3: "We're syncing"
  - Progress indicator
  - "Takes 2-5 minutes"
  - Email notification when ready

Step 4: "Your first insights"
  - Show health score
  - Highlight #1 issue
  - CTA to explore
```

**2. Dashboard**
```
┌─────────────────────────────────────────────────────────┐
│  [App Selector ▼]              [Date Range ▼]  []     │
├─────────────────────────────────────────────────────────┤
│                                                         │
│   HEALTH SCORE        TODAY'S METRICS                   │
│   ┌─────────┐        ┌───────────────────────┐         │
│   │         │        │ Installs    1,247 ↑12%│         │
│   │   68    │        │ Revenue    ₹34,500 ↑8%│         │
│   │  /100   │        │ DAU         8,432 ↓2% │         │
│   │         │        │ D1 Ret.       34% ━   │         │
│   └─────────┘        └───────────────────────┘         │
│   ↑ 4 pts this week                                     │
│                                                         │
├─────────────────────────────────────────────────────────┤
│    TOP ISSUES                                         │
│   ┌─────────────────────────────────────────────┐      │
│   │ 1. Onboarding drop-off costing ₹3.7L/month  │      │
│   │    34% complete vs 67% benchmark            │ →    │
│   ├─────────────────────────────────────────────┤      │
│   │ 2. Google Ads CPI up 23% this week          │      │
│   │    Consider pausing underperforming ads     │ →    │
│   └─────────────────────────────────────────────┘      │
│                                                         │
├─────────────────────────────────────────────────────────┤
│    FUNNEL SNAPSHOT                                    │
│                                                         │
│   Impressions → Views → Installs → D1 → Paywall → Paid │
│   [100K]      [32K]   [9.2K]    [3.1K] [890]    [127]  │
│      ↓ 32%      ↓ 29%    ↓ 34%   ↓ 29%   ↓ 14%        │
│                                 ━       ━           │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**3. Integration Setup**
```
┌─────────────────────────────────────────────────────────┐
│   CONNECTED ACCOUNTS                                    │
│                                                         │
│   ┌─────────────────────────────────────────────┐      │
│   │ ▶ Google Play Console           Connected  │      │
│   │   Last sync: 2 hours ago                    │      │
│   │   Apps: MyApp, MyApp Pro                    │      │
│   └─────────────────────────────────────────────┘      │
│                                                         │
│   ┌─────────────────────────────────────────────┐      │
│   │ ▶ App Store Connect             Connected  │      │
│   │   Last sync: 3 hours ago                    │      │
│   │   Apps: MyApp iOS                           │      │
│   └─────────────────────────────────────────────┘      │
│                                                         │
│   ┌─────────────────────────────────────────────┐      │
│   │ ► Google Ads                   + Connect    │      │
│   │   Get campaign and creative performance     │      │
│   └─────────────────────────────────────────────┘      │
│                                                         │
│   ┌─────────────────────────────────────────────┐      │
│   │ ► Google Analytics 4           + Connect    │      │
│   │   Get retention and engagement data         │      │
│   └─────────────────────────────────────────────┘      │
│                                                         │
└─────────────────────────────────────────────────────────┘`

### User Personas & Journeys

**Persona 1: Indie Dev (Sparsh)**

- Has 5 apps, checks metrics daily on phone
- Wants to know "is my app growing?"
- Needs actionable advice, not raw data
- Journey: Glance at health score → Check if anything urgent → Move on

**Persona 2: Growth Lead (Abhishek)**

- Manages growth for a 10-person startup
- Needs to report to CEO weekly
- Wants granular data to optimize campaigns
- Journey: Deep dive into channels → Export for presentation → Set up alerts