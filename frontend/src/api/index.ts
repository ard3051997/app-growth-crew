/**
 * API Integration Layer for JMIP (Journey Map Intelligence Platform) React Frontend.
 * Maps 1:1 to FastAPI backend routes in src/api_server.
 */

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');

export interface PortfolioApp {
  package_name: string;
  display_name: string;
  funnel_health_score: number;
  revenue_30d: number;
  revenue_change_pct: number;
  profit_30d: number;
  installs_7d: number[];
  active_experiments: number;
  worst_stage?: { name: string; value: number; benchmark?: number } | null;
  top_opportunity?: Opportunity | null;
}

export interface Provenance {
  source: string;
  captured_at?: string | null;
  retrieved_at?: string | null;
  period?: string | null;
  locale?: string | null;
  reference?: string | null;
  is_live?: boolean | null;
  live?: boolean | null;
}

export interface Evidence {
  id?: string | null;
  label: string;
  value?: string | number | null;
  detail?: string | null;
  source?: string | null;
  observed_at?: string | null;
  url?: string | null;
}

export interface Opportunity {
  id: string;
  app_package?: string | null;
  title: string;
  summary?: string | null;
  impact?: number | null;
  impact_unit?: string | null;
  freshness?: string | null;
  rank?: number | null;
  evidence?: Evidence[];
  provenance?: Provenance | null;
}

export interface PortfolioSummary {
  total_revenue_30d: number;
  total_profit_30d: number;
  total_ad_revenue_30d: number;
  active_experiments: number;
  pending_approvals: number;
  trust_tier: string;
  last_prao_cycle?: string | null;
}

export interface Experiment {
  id: string;
  app_package: string;
  experiment_type: string;
  hypothesis: string;
  status: string;
  success_metric: string;
  baseline_value?: number | null;
  current_value?: number | null;
  result_value?: number | null;
  target_value?: number | null;
  confidence?: number | null;
  days_active?: number | null;
  min_observation_days?: number | null;
  result_verdict?: string | null;
  autonomy_mode?: AutonomyMode | null;
  locale?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  failure_reason?: string | null;
  proposal?: ExperimentProposal | null;
  evidence?: Evidence[];
  validation?: ProposalValidation | null;
  provenance?: Provenance | null;
  available_actions?: ExperimentSemanticAction[];
  action_links?: ExperimentActionLink[];
  observations?: ExperimentObservation[];
  evaluation?: ExperimentEvaluation | null;
  raw_evidence?: Record<string, unknown> | null;
  effective_autonomy_mode?: AutonomyMode | null;
  requires_review?: boolean;
  recommendation?: ExperimentDesignRecommendation | null;
}

export interface FunnelStep {
  name: string;
  priority?: string | null;
  gap?: number | null;
  insight?: string | null;
  conversion_rate: number;
  benchmark_rate: number;
  users_entered: number;
  users_completed: number;
  evidence?: Evidence[];
  provenance?: Provenance | null;
}

export interface RankedLeak {
  rank: number;
  stage: string;
  score: number | null;
  conversion_rate?: number | null;
  benchmark_rate?: number | null;
  gap?: number | null;
  estimated_monthly_impact?: number | null;
  insight?: string | null;
  evidence?: Evidence[];
  provenance?: Provenance | null;
}

export interface FunnelResponse {
  all_steps: FunnelStep[];
  funnel_health_score: number | null;
  total_monthly_revenue_impact: number | null;
  ranked_leaks?: RankedLeak[];
  evidence?: Evidence[];
  provenance?: Provenance | null;
}

export interface Review {
  author_name?: string;
  comment: string;
  rating?: number;
  star_rating?: number;
  developer_reply?: string | null;
}

export interface ReviewsAnalysis {
  average_rating: number;
  total_reviews: number;
  sentiment: { positive: number; neutral: number; negative: number };
  keywords: Array<{ keyword: string; count: number; sentiment: string }>;
  stage_correlation: Record<string, { count: number; rating: number; reviews: Review[] }>;
  status?: string | null;
  provenance?: Provenance | null;
}

export interface ReviewsResponse {
  reviews: Review[];
  status?: string | null;
  provenance?: Provenance | null;
}

export type JourneyRow = Record<string, string>;
export interface JourneyDefinition {
  title: string;
  description?: string;
  sections?: Array<{ section_title?: string; rows?: JourneyRow[] }>;
}

export interface Keyword {
  keyword: string;
  volume: number;
  difficulty: number;
  found: boolean;
  rank?: number | null;
}

export interface StoreListing {
  title?: string;
  short_description?: string;
  full_description?: string;
  default_language?: string;
  locale?: string;
  version?: string | null;
  fetched_at?: string | null;
  provenance?: Provenance | null;
}

export interface RulebookFieldConstraint {
  max_length?: number | null;
  min_length?: number | null;
  required?: boolean;
  required_terms?: string[];
  prohibited_terms?: string[];
}

export interface AppRulebook {
  package_name: string;
  version?: string | null;
  updated_at?: string | null;
  target_keywords?: string[];
  constraints?: Partial<Record<ListingField, RulebookFieldConstraint>>;
  forbidden_terms?: string[];
  allowed_autonomy_modes?: AutonomyMode[];
  provenance?: Provenance | null;
  raw_rulebook?: Record<string, unknown>;
}

export type ListingField = 'title' | 'short_description' | 'full_description';
export type AutonomyMode = 'recommend_only' | 'manual' | 'auto_low_risk';

export interface ListingSnapshot {
  title: string;
  short_description: string;
  full_description: string;
}

export interface FieldChange {
  field: ListingField;
  before: string | null;
  after: string | null;
}

export interface ValidationIssue {
  field?: ListingField | null;
  code: string;
  message: string;
  severity: 'error' | 'warning' | 'info';
}

export interface ProposalValidation {
  valid: boolean;
  checked_at?: string | null;
  issues: ValidationIssue[];
  effective_execution_mode?: AutonomyMode | null;
}

export interface ExperimentProposal {
  id?: string | null;
  current?: Partial<ListingSnapshot> | null;
  proposed?: Partial<ListingSnapshot> | null;
  changes?: FieldChange[];
  rulebook_version?: string | null;
  listing_version?: string | null;
}

export interface StoreConversionProposalInput {
  language?: 'en-US';
  country?: string;
  baseline_window_days?: number;
  max_source_age_days?: number;
  target_improvement_pct?: number;
  rollback_degradation_pct?: number;
  min_observation_days?: number;
  max_observation_days?: number;
  proposed_listing: ListingSnapshot;
  execution_mode: AutonomyMode;
}

export interface StoreConversionProposalResponse {
  experiment: Experiment;
  proposal: Record<string, unknown>;
  validation: ProposalValidation | null;
  auto_executed: boolean;
  requires_review: boolean;
}

export interface StorefrontRow {
  country?: string;
  traffic_source?: string;
  visitors: number;
  installs: number;
  conversion_rate: number;
}

export interface RevenueResponse {
  admob?: { ad_revenue_30d?: number };
  revenuecat?: { revenue?: number; mrr?: number; active_subscriptions?: number } | null;
  gcs_iap?: { iap_revenue_30d?: number } | null;
  app_store?: { iap_revenue_30d?: number } | null;
}

export interface ActionEntry {
  id: string | number;
  timestamp: string;
  app_package?: string | null;
  action_type: string;
  tool_name?: string | null;
  arguments?: unknown;
  result?: string | null;
  reasoning?: string | null;
  experiment_id?: string | null;
  safety_decision?: string | null;
  policy_name?: string | null;
  correlation_id?: string | null;
}

export interface SafetyStatus {
  emergency_brake?: string | null;
  crash_rate?: number | null;
  crash_threshold?: number | null;
  anr_rate?: number | null;
  anr_threshold?: number | null;
  last_scan?: string | null;
  provenance?: Provenance | null;
}

export interface SystemStatus {
  status?: string;
  services?: Record<string, string>;
  trust_tier?: string;
  last_prao_cycle?: string | null;
  scheduler?: {
    state: 'running' | 'stale' | 'unavailable' | string;
    heartbeat_at?: string | null;
    process_started_at?: string | null;
    last_cycle_started_at?: string | null;
    last_cycle_completed_at?: string | null;
    last_cycle_status?: string | null;
    error?: string | null;
  };
  latest_snapshot?: {
    package_name: string;
    snapshot_date?: string | null;
    captured_at?: string | null;
    state: string;
    partial: boolean;
  } | null;
}

export type AppConfig = Record<string, string | number | boolean | null>;

export interface ExperimentObservation {
  id?: number;
  experiment_id?: string;
  observed_at?: string;
  metric_value: number;
  source?: string | null;
  sample_size?: number | null;
  notes?: string | null;
  visitors?: number | null;
  installs?: number | null;
  provenance?: Provenance | null;
}

export type ExperimentSemanticAction =
  | 'approve'
  | 'reject'
  | 'execute'
  | 'evaluate'
  | 'retain'
  | 'rollback';

export interface ExperimentActionLink {
  action: ExperimentSemanticAction;
  method?: 'POST' | 'GET';
  href: string;
  enabled?: boolean;
  disabled_reason?: string | null;
}

export interface ExperimentActionInput {
  reason: string;
}

export interface ExperimentEvaluation {
  verdict?: string | null;
  confidence?: number | null;
  observed_change?: number | null;
  treatment_rate?: number | null;
  observation_days?: number | null;
  reason?: string | null;
  evaluated_at?: string | null;
}

export interface ExperimentActionResult {
  experiment: Experiment;
  message: string;
  evaluation?: ExperimentEvaluation;
}

export interface ExperimentTypeDefinition {
  id: string;
  label: string;
  description: string;
  default_metric: string;
  capability: 'executable' | 'planning_only';
  builder?: 'aso';
}

export interface PlannedExperimentInput {
  app_package: string;
  experiment_type: string;
  hypothesis: string;
  success_metric?: string;
  min_observation_days: number;
  max_observation_days: number;
  notes?: string;
  recommendation?: ExperimentDesignRecommendation;
}

export type ExperimentRecommendationFocus = 'auto' | 'acquisition' | 'activation' | 'monetization' | 'retention';

export interface ExperimentDesignRecommendation {
  id: string;
  rank: number;
  app_package: string;
  experiment_type: string;
  label: string;
  focus: Exclude<ExperimentRecommendationFocus, 'auto'>;
  hypothesis: string;
  rationale: string;
  success_metric: string;
  suggested_min_observation_days: number;
  suggested_max_observation_days: number;
  target_improvement_pct: number;
  estimated_monthly_impact: number;
  conflicts_with_active_experiment: boolean;
  capability: 'executable' | 'planning_only';
  design: {
    method: string;
    control: string;
    treatment: string;
    primary_metric: string;
    guardrail_metrics: string[];
    analysis_plan: string;
    sample_guidance: string;
  };
  evidence: {
    stage: string;
    actual_rate: number;
    benchmark_rate: number;
    gap: number;
    users_entered?: number | null;
    users_completed?: number | null;
    estimated_monthly_impact: number;
    priority?: string | null;
    sources: string[];
    captured_at?: string | null;
    freshness: 'fresh' | 'stale';
  };
}

export interface ExperimentRecommendationResponse {
  app_package: string;
  generated_at: string;
  source_status: 'fresh' | 'stale';
  snapshot_source: 'cached_mcp_snapshot' | 'live_mcp_refresh';
  data_sources: string[];
  recommendations: ExperimentDesignRecommendation[];
  message?: string;
}

const appPath = (packageId: string) => `/apps/${encodeURIComponent(packageId)}`;

async function apiRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      'Content-Type': 'application/json',
    },
    ...options,
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    const detail = errorBody.detail;
    throw new Error(
      typeof detail === 'string'
        ? detail
        : detail?.message || `API error: ${response.statusText}`,
    );
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  // --- Portfolio Command Center ---
  getPortfolio: (period = '30d') => apiRequest<{ apps: PortfolioApp[]; opportunities?: Opportunity[]; top_opportunity?: Opportunity | null }>(`/portfolio/?period=${encodeURIComponent(period)}`),
  getPortfolioSummary: (period = '30d') => apiRequest<{ portfolio_summary: PortfolioSummary }>(`/portfolio/summary?period=${encodeURIComponent(period)}`),
  getPortfolioCosts: () => apiRequest<{ costs: Record<string, number | null> }>('/portfolio/costs'),

  // --- App Details & Diagnostics ---
  getAppFunnel: (packageId: string, period = '30d') =>
    apiRequest<FunnelResponse>(`${appPath(packageId)}/funnel?period=${encodeURIComponent(period)}`),

  getAppJourneys: (packageId: string, signal?: AbortSignal) =>
    apiRequest<{ journeys: Record<string, JourneyDefinition> }>(`${appPath(packageId)}/journeys`, { signal }),

  getAppEvents: (packageId: string, period = '30d', signal?: AbortSignal) =>
    apiRequest<{ events?: Array<{ event_name: string; event_count: number; total_users: number }>; rows?: Array<{ dimensionValues?: Array<{ value?: string }>; metricValues?: Array<{ value?: string }>; name?: string; value?: string | number }> }>(`${appPath(packageId)}/events?period=${encodeURIComponent(period)}`, { signal }),

  getAppRevenue: (packageId: string, period = '30d') =>
    apiRequest<RevenueResponse>(`${appPath(packageId)}/revenue?period=${encodeURIComponent(period)}`),

  getAppStorefront: (packageId: string, period = '30d') =>
    apiRequest<{ country?: StorefrontRow[]; traffic_source?: StorefrontRow[] }>(`${appPath(packageId)}/storefront?period=${encodeURIComponent(period)}`),

  getAppReviews: (packageId: string, stage?: string, signal?: AbortSignal) =>
    apiRequest<Review[] | ReviewsResponse>(`${appPath(packageId)}/reviews${stage ? `?stage=${encodeURIComponent(stage)}` : ''}`, { signal }),

  getAppReviewsAnalysis: (packageId: string) =>
    apiRequest<ReviewsAnalysis>(`${appPath(packageId)}/reviews/analysis`),

  getAppKeywords: (packageId: string, signal?: AbortSignal) =>
    apiRequest<Keyword[]>(`${appPath(packageId)}/keywords`, { signal }),

  getAppListing: (packageId: string, language: string, signal?: AbortSignal) =>
    apiRequest<StoreListing>(`${appPath(packageId)}/listing/${encodeURIComponent(language)}`, { signal }),

  getAppRulebook: (packageId: string, signal?: AbortSignal) =>
    apiRequest<AppRulebook>(`${appPath(packageId)}/rulebook`, { signal }),

  getAppDiagnostic: (packageId: string) =>
    apiRequest<{ diagnostic?: string }>(`${appPath(packageId)}/diagnostic`),

  getAppRetention: (packageId: string, days = 30) =>
    apiRequest<unknown>(`${appPath(packageId)}/retention?days=${days}`),

  askAppChat: (packageId: string, question: string, signal?: AbortSignal) =>
    apiRequest<{ answer: string }>(`${appPath(packageId)}/chat`, {
      method: 'POST',
      body: JSON.stringify({ question }),
      signal,
    }),

  generateEventsFromZip: async (packageId: string, zipFile: File, signal?: AbortSignal) => {
    const form = new FormData();
    form.append('zip_file', zipFile);
    const response = await fetch(`${API_BASE_URL}${appPath(packageId)}/events_md/generate`, {
      method: 'POST',
      body: form,
      signal,
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || 'Generation failed');
    }
    return response.json() as Promise<{ path: string; journey_count: number }>;
  },

  // --- Experiment Center ---
  getExperiments: (app?: string, status?: string) => {
    const params = new URLSearchParams();
    if (app) params.append('app', app);
    if (status) params.append('status', status);
    const query = params.toString();
    return apiRequest<{ experiments: Experiment[] }>(`/experiments/${query ? `?${query}` : ''}`);
  },

  getExperimentTypes: () =>
    apiRequest<{ experiment_types: ExperimentTypeDefinition[] }>('/experiments/types'),

  createPlannedExperiment: (spec: PlannedExperimentInput) =>
    apiRequest<{ experiment: Experiment; message: string }>('/experiments/planned', {
      method: 'POST',
      body: JSON.stringify(spec),
    }),

  recommendExperimentDesigns: (
    packageId: string,
    input: { focus: ExperimentRecommendationFocus; max_results?: number; refresh_live?: boolean },
  ) => apiRequest<ExperimentRecommendationResponse>(`${appPath(packageId)}/experiment-recommendations`, {
    method: 'POST',
    body: JSON.stringify(input),
  }),

  getExperiment: (id: string, signal?: AbortSignal) =>
    apiRequest<Experiment>(`/experiments/${encodeURIComponent(id)}`, { signal }),

  createStoreConversionProposal: (packageId: string, spec: StoreConversionProposalInput, signal?: AbortSignal) =>
    apiRequest<StoreConversionProposalResponse>(`${appPath(packageId)}/store-conversion/proposals`, {
      method: 'POST',
      body: JSON.stringify(spec),
      signal,
    }),

  runExperimentAction: (id: string, action: ExperimentSemanticAction, input?: ExperimentActionInput) => {
    const requiresAttribution = ['approve', 'reject', 'retain', 'rollback'].includes(action);
    return apiRequest<ExperimentActionResult>(`/experiments/${encodeURIComponent(id)}/${action}`, {
      method: 'POST',
      ...(requiresAttribution ? { body: JSON.stringify({ reason: input?.reason }) } : {}),
    });
  },

  getExperimentObservations: (id: string) =>
    apiRequest<{ observations: ExperimentObservation[] }>(`/experiments/${encodeURIComponent(id)}/observations`),

  // --- Action Log ---
  getActions: (app?: string, type?: string, limit = 50, experimentId?: string) => {
    const params = new URLSearchParams();
    if (app) params.append('app', app);
    if (type) params.append('type', type);
    if (experimentId) params.append('experiment_id', experimentId);
    params.append('limit', String(limit));
    return apiRequest<{ actions: ActionEntry[] }>(`/actions/?${params.toString()}`);
  },

  // --- Google Ads ---
  getAppAds: (packageId: string, period = '30d') =>
    apiRequest<{ google_ads?: { cost_usd?: number } | null }>(`${appPath(packageId)}/ads?period=${encodeURIComponent(period)}`),

  // --- AdMob daily timeline ---
  getAppAdmobTimeline: (packageId: string, days = 30) =>
    apiRequest<{ daily?: Array<{ date: string; revenue: number }> }>(`${appPath(packageId)}/admob_timeline?days=${days}`),

  // --- Per-App Configuration ---
  getAppConfig: (packageId: string, signal?: AbortSignal) =>
    apiRequest<AppConfig>(`${appPath(packageId)}/config`, { signal }),

  updateAppConfig: (packageId: string, fields: AppConfig, signal?: AbortSignal) =>
    apiRequest<{ success: boolean; message: string }>(`${appPath(packageId)}/config`, {
      method: 'PUT',
      body: JSON.stringify({ fields }),
      signal,
    }),

  updateAppKeywords: (packageId: string, keywords: string[]) =>
    apiRequest<{ success: boolean; keywords: string[] }>(`${appPath(packageId)}/keywords`, {
      method: 'PUT',
      body: JSON.stringify({ keywords }),
    }),

  // --- System Configuration & Safety ---
  getSystemStatus: () => apiRequest<SystemStatus>('/system/status'),
  getSystemSafety: () => apiRequest<SafetyStatus>('/system/safety'),
  getSystemConfig: () => apiRequest<{ configs: Record<string, string> }>('/system/config'),
  updateSystemConfig: (configs: Record<string, string>) => apiRequest<{ configs?: Record<string, string> }>('/system/config', {
    method: 'POST',
    body: JSON.stringify({ configs }),
  }),
};
