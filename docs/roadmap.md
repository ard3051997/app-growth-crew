# Autonomous App Management Roadmap

## Goal
To build a fully autonomous App Management System (PRAO loop: Perception, Reasoning, Action, Observation) that operates independently of the core codebase. This system handles organic acquisition (ASO), paid acquisition (Meta Ads), and lifecycle marketing (Push Notifications).

## Key Integrations
- **App Store Connect MCP:** iOS app management, TestFlight, and metadata deployment (`JoshuaRileyDev/app-store-connect-mcp-server`).
- **Play Store MCP:** Android app management and vitals.
- **AutoASO (AppFollow/OpenTrends):** Autonomous organic keyword optimization and metadata experiments.
- **FCM Push MCP:** Lifecycle marketing and re-engagement via push notifications (`kibotu/mcp-fcm-push`).
- **Facebook Marketing API:** Paid user acquisition, campaign scaling, and ad management.
- **Firebase AI Assistance MCP:** Deep Firebase context, troubleshooting, and querying.
- **RevenueCat MCP:** Subscription state, MRR monitoring, and entitlement checks.

---

## Phase 1: Core Organic Engine (ASO & Storefronts)
*Status: Complete*
- **Integration:** Expose the existing local `AutoASO` python engine (`/Volumes/Crucial X9/Code/AutoASO`) to the agent.
- **Integration:** Deploy **App Store Connect MCP** alongside the existing **Play Store MCP**.
- **Integration [NEW]:** Implement a local **SQLite database layer** (`store_performance.db`) and a **Storefront Ingest Subagent** that regularly downloads, parses, and logs detailed Play Store CSV metrics from GCS (Visitor volume, Installs, Search Query Conversions).
- **Autonomous Loop:** 
  1. Agent polls GCS reports and AppFollow/OpenTrends for live keyword volumes.
  2. Ingests GCS store performance files to record conversion rates per country, traffic source, and search term in the SQLite DB.
  3. Generates metadata hypotheses and tests them against the AutoASO scoring engine.
  4. Deploys winning metadata configurations (Titles, Subtitles, Keywords) directly to Apple and Google storefronts without human intervention.


## Phase 2: Lifecycle & Re-engagement Automation
*Status: Complete*
- **Integration:** Connect **FCM Push MCP**.
- **Integration:** Utilize **RevenueCat MCP** to listen for subscription lifecycle events (e.g., churn, trial started, billing issue).
- **Autonomous Loop:** 
  1. Agent monitors for users entering a high-churn-risk state or dropping a trial.
  2. Automatically crafts a targeted, personalized push notification.
  3. Dispatches via FCM and analyzes open/conversion rates over time to optimize future messaging.

## Phase 3: Paid User Acquisition
*Status: Planned*
- **Integration:** Connect **Facebook Business Marketing API**.
- **Autonomous Loop:** 
  1. Agent allocates daily advertising budget based on RevenueCat LTV (Life Time Value) and CAC (Customer Acquisition Cost) data.
  2. Pauses underperforming Meta ad sets autonomously.
  3. Boosts high-performing campaigns to maximize ROAS (Return on Ad Spend).

## Phase 4: Diagnostics, Pricing Parity, and Safety
*Status: Planned*
- **Integration:** Connect **Firebase AI Assistance MCP**.
- **Autonomous Loop (Safety):** 
  1. Agent autonomously queries crash logs, remote config states, and performance vitals.
  2. If a severe issue is detected (e.g., crash rate spikes), the agent autonomously pauses Phase 3 (Meta Ads) to prevent wasting spend on broken flows.
- **Autonomous Loop (Pricing Parity):**
  1. Agent utilizes Remote Config / RevenueCat Offerings to adjust subscription prices dynamically based on geographic parity and A/B test conversion results.
