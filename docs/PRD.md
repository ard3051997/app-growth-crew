# Product Requirements Document (PRD)
**Project Name:** MCP-GC Autonomous App Management & Growth System
**Target:** Company-wide Deployment

## 1. Product Vision & Objective
To evolve the **MCP-GC** system from a reactive, human-triggered REPL into a fully **Autonomous App Management & Growth System**. This engine will operate independently of core app development, focusing purely on organic acquisition (ASO), paid acquisition (Meta Ads), and lifecycle marketing (Push Notifications). By utilizing a unified, daily autonomous execution loop, the system will scale across a large portfolio of apps while minimizing operational overhead and inference costs.

## 2. Core Architecture: The PRAO Loop
The agent will function via a continuous execution loop called the **Perception-Reasoning-Action-Observation (PRAO)** loop:
1. **Perception:** The agent ingests a consolidated daily snapshot of structured metrics across storefronts, analytics, and revenue dashboards.
2. **Reasoning:** It processes the context to diagnose root causes and run predictions against target portfolio goals (e.g., maximizing ROAS, fixing onboarding funnels).
3. **Action:** The agent autonomously deploys changes (metadata, bidding budgets, remote configuration prices).
4. **Observation:** Over a rolling window, the agent measures the delta in key performance metrics to confirm if the action succeeded.

### Tech Stack
* **Orchestration Layer:** Google Antigravity SDK
* **Tool Layer:** FastMCP
* **Safety & Review:** Slack/Discord webhook for human-in-the-loop interactive approvals.

## 3. The Consolidated Daily Loop Model
To heavily optimize Large Language Model (LLM) token inference costs, the system departs from an hourly trigger model and instead uses a **Consolidated Daily Fetch (1x/day)**.
* **Mechanism:** Every 24 hours, the coordinator agent fetches vitals, ASO metrics, ad campaigns, and RevenueCat MRR/churn stats for the entire portfolio in a single large prompt.
* **Cost Strategy:** By processing a comprehensive daily context snapshot, the LLM footprint is reduced by 80-90%. 
* **Model Approach:** A **Blended LLM Strategy** utilizes Gemini 1.5 Flash for routine log parsing and Gemini 1.5 Pro/Claude 3.5 Sonnet for deep optimization and planning tasks.

## 4. Rollout Roadmap (4 Phases)

### Phase 1: Core Organic Engine (ASO & Storefronts)
* **Goal:** Autonomous optimization of Apple App Store and Google Play Store metadata with database-driven historical conversion tracking.
* **Integrations:** `play-store-mcp`, `app-store-connect-mcp-server`, the local `AutoASO` python engine, `gcs-mcp` (Play Store GCS report exporter), and a local SQLite database storage layer.
* **Loop Actions:** The agent periodically ingests store performance CSVs from GCS into a local SQLite database using SQLModel ORM models. It calculates optimal keyword scores, maps country-level, traffic-source-level, and search-term-level conversion metrics over time, predicts rank improvements, and autonomously deploys metadata (titles, subtitles, keywords) to the storefronts.

### Phase 2: Lifecycle & Re-engagement Automation
* **Goal:** Reducing churn and re-engaging users who drop out of the trial or payment funnels.
* **Integrations:** `mcp-fcm-push` and `revenuecat-mcp`.
* **Loop Actions:** Detecting churn/trial-drop events via RevenueCat (often streamlined via Webhooks) and autonomously crafting + dispatching targeted re-engagement push notifications via Firebase Cloud Messaging.

### Phase 3: Paid User Acquisition & Ads
* **Goal:** Autonomous bidding and campaign budget management to maximize LTV:CAC ratios.
* **Integrations:** `Facebook Business Marketing API` (Meta Ads).
* **Loop Actions:** The agent monitors LTV/CAC dynamically, autonomously pausing underperforming ad campaigns while scaling budgets on high-performing ad sets.

### Phase 4: Ecosystem Diagnostics & Pricing Parity
* **Goal:** Automatic crash response and global pricing optimization.
* **Integrations:** `Firebase AI Assistance MCP`.
* **Loop Actions:** 
  1. If Firebase detects an anomaly/crash spike, the agent immediately pauses Phase 3 (Meta Ads) to prevent wasted acquisition spend.
  2. The agent utilizes Remote Config / RevenueCat Offerings to dynamically adjust base subscription pricing and run price sensitivity (Gabor-Granger) A/B tests to achieve geographic pricing parity.

## 5. Security & Safety Guardrails
* **Interactive Approvals:** Destructive actions (e.g., CI/CD code pushes, budget increases >20%) trigger a mandatory Slack interactive button prompt (`[Approve Update]`).
* **Hard Caps:** The agent operates under hard-coded constraints for daily budget allocation and metadata character limits.
