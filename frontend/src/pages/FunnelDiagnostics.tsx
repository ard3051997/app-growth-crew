import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  RefreshCw,
  TrendingDown,
  MessageSquare,
  Sparkles,
  ArrowRight,
  Coins,
  Star,
  Info,
  Layers,
  Activity,
  CheckCircle2,
  Database,
  Clock3
} from 'lucide-react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid
} from 'recharts';
import { api, type Experiment, type FunnelResponse, type ReviewsAnalysis } from '../api';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { getErrorMessage } from '../utils';

export default function FunnelDiagnostics() {
  const { packageId } = useParams<{ packageId: string }>() as { packageId: string };
  const navigate = useNavigate();
  const [funnelData, setFunnelData] = useState<FunnelResponse | null>(null);
  const [diagnostic, setDiagnostic] = useState<string>('');
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [reviewsAnalysis, setReviewsAnalysis] = useState<ReviewsAnalysis | null>(null);
  const [reviewsLoading, setReviewsLoading] = useState(true);
  const [reviewsError, setReviewsError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [period, setPeriod] = useState('30d');
  const [error, setError] = useState<string | null>(null);

  // Track selected funnel stage for detail views & review correlation
  const [selectedStageIndex, setSelectedStageIndex] = useState<number>(0);

  const loadAllData = () => {
    setLoading(true);
    setError(null);
    setReviewsLoading(true);
    setReviewsError(null);
    setReviewsAnalysis(null);
    Promise.all([
      api.getAppFunnel(packageId, period),
      api.getAppDiagnostic(packageId),
      api.getExperiments(packageId),
    ])
      .then(([funnel, diag, exps]) => {
        setFunnelData(funnel);
        setDiagnostic(diag.diagnostic || '');
        setExperiments(exps.experiments || []);

        const stepsList = funnel.all_steps || [];
        const bottleneckIdx = funnel.ranked_leaks?.[0]
          ? stepsList.findIndex(step => step.name === funnel.ranked_leaks?.[0].stage)
          : -1;
        setSelectedStageIndex(bottleneckIdx !== -1 ? bottleneckIdx : 0);

        setLoading(false);
      })
      .catch(err => {
        console.error(err);
        setError(getErrorMessage(err, 'Failed to load funnel diagnostics data'));
        setLoading(false);
      });
    api.getAppReviewsAnalysis(packageId)
      .then(reviews => setReviewsAnalysis(reviews))
      .catch(err => setReviewsError(getErrorMessage(err, 'Review source unavailable')))
      .finally(() => setReviewsLoading(false));
  };

  useEffect(() => {
    let active = true;
    // Route/period changes invalidate the package-bound review snapshot immediately.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setReviewsLoading(true);
    setReviewsError(null);
    setReviewsAnalysis(null);
    Promise.all([
      api.getAppFunnel(packageId, period),
      api.getAppDiagnostic(packageId),
      api.getExperiments(packageId),
    ]).then(([funnel, diag, exps]) => {
      if (!active) return;
      setFunnelData(funnel);
      setDiagnostic(diag.diagnostic || '');
      setExperiments(exps.experiments || []);
      const bottleneckIdx = funnel.ranked_leaks?.[0]
        ? (funnel.all_steps || []).findIndex(step => step.name === funnel.ranked_leaks?.[0].stage)
        : -1;
      setSelectedStageIndex(bottleneckIdx === -1 ? 0 : bottleneckIdx);
      setLoading(false);
    }).catch(err => {
      if (!active) return;
      setError(getErrorMessage(err, 'Failed to load funnel diagnostics data'));
      setLoading(false);
    });
    api.getAppReviewsAnalysis(packageId)
      .then(reviews => {
        if (active) setReviewsAnalysis(reviews);
      })
      .catch(err => {
        if (active) setReviewsError(getErrorMessage(err, 'Review source unavailable'));
      })
      .finally(() => {
        if (active) setReviewsLoading(false);
      });
    return () => { active = false; };
  }, [packageId, period]);

  if (loading) {
    return (
      <div className="p-8 flex flex-col justify-center items-center h-[80vh] gap-4">
        <div className="animate-spin w-10 h-10 border-4 border-accent-primary border-t-transparent rounded-full" />
        <p className="text-text-secondary font-mono text-sm">Crunching telemetry & review sentiment...</p>
      </div>
    );
  }

  if (error || !funnelData) {
    return (
      <div className="p-8 text-center text-danger h-[80vh] flex flex-col justify-center items-center">
        <AlertTriangle className="w-16 h-16 mx-auto mb-4 animate-bounce" />
        <p className="font-heading font-bold text-xl">{error || 'No funnel data found for this app'}</p>
        <button onClick={loadAllData} className="mt-6 bg-accent-primary hover:bg-accent-primary/80 text-white px-6 py-2.5 rounded-lg text-sm transition-all font-semibold">
          Try Again
        </button>
      </div>
    );
  }

  const steps = funnelData.all_steps || [];
  const healthScore = funnelData.funnel_health_score;
  const revImpact = funnelData.total_monthly_revenue_impact;
  const rankedLeaks = funnelData.ranked_leaks || [];

  const topLeak = rankedLeaks[0];
  const bottleneckStage = topLeak?.stage || 'No ranked leak supplied';
  const bottleneckInsight = topLeak?.insight || 'The backend has not supplied a ranked leak narrative.';

  // Helper to map funnel step names to review stage keys
  const getStageKey = (stepName: string): string => {
    const name = stepName.toLowerCase();
    if (name.includes('onboarding')) return 'onboarding';
    if (name.includes('dashboard')) return 'dashboard';
    if (name.includes('calculator') || name.includes('calculate') || name.includes('core')) return 'core_calculator';
    if (name.includes('paywall') || name.includes('purchase') || name.includes('subscribe') || name.includes('subscription')) return 'paywall';
    return 'other';
  };

  const currentStage = steps[selectedStageIndex];
  const stageKey = currentStage ? getStageKey(currentStage.name) : 'other';
  const stageReviewData = reviewsAnalysis?.stage_correlation?.[stageKey] || null;
  const reviewStatus = reviewsAnalysis?.status?.toLowerCase() || null;
  const reviewStatusUnavailable = Boolean(reviewStatus && ['unavailable', 'error', 'failed', 'failure'].includes(reviewStatus));
  const reviewSourceExplicit = Boolean(reviewsAnalysis?.provenance)
    || Boolean(reviewStatus && ['available', 'success', 'ok', 'empty', 'observed'].includes(reviewStatus));
  const hasReviewSample = (reviewsAnalysis?.total_reviews || 0) > 0;
  const reviewSourceUsable = !reviewsError && !reviewStatusUnavailable && (hasReviewSample || reviewSourceExplicit);

  return (
    <div className="p-6 max-w-[1600px] mx-auto min-h-screen flex flex-col relative overflow-hidden space-y-6 pb-12">
      {/* Background glows */}
      <div className="absolute top-[-10%] left-[-15%] w-[45%] h-[45%] bg-accent-primary/5 rounded-full blur-[140px] pointer-events-none" />
      <div className="absolute bottom-[-10%] right-[-15%] w-[45%] h-[45%] bg-accent-secondary/5 rounded-full blur-[140px] pointer-events-none" />

      {/* Header */}
      <header className="flex justify-between items-end z-10 border-b border-border-subtle pb-4">
        <div>
          <div className="flex items-center gap-2 mb-1.5">
            <span className="bg-accent-primary/20 text-accent-primary text-[10px] px-2 py-0.5 rounded font-mono font-bold uppercase">Diagnostics Hub</span>
          </div>
          <h1 className="text-3xl font-heading font-bold mb-1.5 flex items-center gap-3">
            <Layers className="w-8 h-8 text-accent-primary" /> Funnel & Diagnostics
          </h1>
          <p className="text-text-secondary font-mono text-xs">{packageId}</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={loadAllData}
            className="p-2.5 bg-surface hover:bg-white/5 border border-border-subtle text-text-primary rounded-xl text-sm transition-all"
            title="Refresh Data"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
          <div className="flex bg-surface border border-border-subtle rounded-xl p-1">
            <button
              onClick={() => {
                if (period !== '30d') {
                  setLoading(true);
                  setError(null);
                  setPeriod('30d');
                }
              }}
              className={`px-4 py-1.5 text-xs font-semibold rounded-lg transition-all ${period === '30d' ? 'bg-accent-primary text-white shadow-lg' : 'text-text-muted hover:text-text-primary'}`}
            >
              30 Days
            </button>
            <button
              onClick={() => {
                if (period !== '7d') {
                  setLoading(true);
                  setError(null);
                  setPeriod('7d');
                }
              }}
              className={`px-4 py-1.5 text-xs font-semibold rounded-lg transition-all ${period === '7d' ? 'bg-accent-primary text-white shadow-lg' : 'text-text-muted hover:text-text-primary'}`}
            >
              7 Days
            </button>
          </div>
        </div>
      </header>

      {/* Top Cards Section - Key Stats */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-6 z-10">
        {/* Health Score Circle */}
        <div className="glass-card p-5 flex items-center gap-5 justify-between">
          <div className="space-y-1">
            <span className="text-text-muted text-xs font-mono uppercase tracking-wider">Funnel Health</span>
            <h3 className="text-2xl font-bold font-heading">Overall Score</h3>
            <p className="text-xs text-text-secondary">Composite conversion rating</p>
          </div>
          <div className="relative w-20 h-20 shrink-0">
            <svg className="w-full h-full transform -rotate-90" viewBox="0 0 36 36">
              <path
                className="text-white/5"
                strokeWidth="3.5"
                stroke="currentColor"
                fill="none"
                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
              />
              {healthScore != null && (
                <path
                  className={`transition-all duration-1000 ${healthScore >= 85 ? 'text-success' : healthScore >= 65 ? 'text-warning' : 'text-danger'}`}
                  strokeDasharray={`${healthScore}, 100`}
                  strokeWidth="3.5"
                  strokeLinecap="round"
                  stroke="currentColor"
                  fill="none"
                  d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                />
              )}
            </svg>
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="text-lg font-mono font-bold">{healthScore ?? '—'}</span>
            </div>
          </div>
        </div>

        {/* Revenue Leak */}
        <div className="glass-card p-5 flex items-center gap-4 border-l-4 border-l-danger">
          <div className="p-3 bg-danger/10 text-danger rounded-xl">
            <Coins className="w-6 h-6" />
          </div>
          <div className="space-y-0.5">
            <span className="text-text-muted text-xs font-mono uppercase tracking-wider">Est. Monthly Leak</span>
            <h3 className="text-2xl font-bold font-heading text-danger">
              {revImpact == null ? 'Unavailable' : `$${revImpact.toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0})}`}
            </h3>
            <p className="text-xs text-text-secondary">Backend-ranked impact estimate</p>
          </div>
        </div>

        {/* Bottleneck Flag */}
        <div className="glass-card p-5 flex items-center gap-4 border-l-4 border-l-warning">
          <div className="p-3 bg-warning/10 text-warning rounded-xl">
            <AlertTriangle className="w-6 h-6 animate-pulse" />
          </div>
          <div className="space-y-0.5">
            <span className="text-text-muted text-xs font-mono uppercase tracking-wider">Active Bottleneck</span>
            <h3 className="text-base font-bold font-heading truncate max-w-[280px]">
              {bottleneckStage}
            </h3>
            <p className="text-xs text-text-secondary truncate">
              {bottleneckInsight.length > 40 ? `${bottleneckInsight.substring(0, 40)}...` : bottleneckInsight}
            </p>
          </div>
        </div>
      </section>

      <section className="glass-card p-5 z-10">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 mb-4">
          <div>
            <h2 className="font-heading font-bold flex items-center gap-2"><TrendingDown className="w-5 h-5 text-danger" /> Ranked Leaks</h2>
            <p className="text-xs text-text-secondary mt-1">Priority and impact are supplied by the funnel analysis service, not inferred in the browser.</p>
          </div>
          <div className="flex flex-wrap gap-2 text-[10px] font-mono">
            <span className="bg-info/10 text-info border border-info/20 rounded px-2 py-1 flex items-center gap-1"><Database className="w-3 h-3" /> {funnelData.provenance?.source || 'Source unavailable'}</span>
            <span className="bg-white/5 text-text-muted border border-border-subtle rounded px-2 py-1 flex items-center gap-1"><Clock3 className="w-3 h-3" /> {funnelData.provenance?.captured_at ? new Date(funnelData.provenance.captured_at).toLocaleString() : 'Capture time unavailable'}</span>
          </div>
        </div>
        {rankedLeaks.length > 0 ? (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            {rankedLeaks.map(leak => (
              <button
                key={`${leak.rank}-${leak.stage}`}
                onClick={() => {
                  const index = steps.findIndex(step => step.name === leak.stage);
                  if (index >= 0) setSelectedStageIndex(index);
                }}
                className="text-left bg-black/20 border border-border-subtle hover:border-danger/40 rounded-xl p-4 transition-colors"
              >
                <div className="flex items-center justify-between gap-2 mb-2">
                  <span className="text-[10px] font-mono text-danger uppercase tracking-wider">#{leak.rank} leak</span>
                  <span className="text-[10px] font-mono text-text-muted">Score {leak.score ?? 'unavailable'}</span>
                </div>
                <div className="font-semibold text-sm">{leak.stage}</div>
                <div className="flex gap-3 mt-2 text-[10px] font-mono text-text-secondary">
                  <span>Gap {leak.gap == null ? '—' : `${(leak.gap * 100).toFixed(1)}%`}</span>
                  <span>Impact {leak.estimated_monthly_impact == null ? '—' : `$${leak.estimated_monthly_impact.toLocaleString()}/mo`}</span>
                </div>
                {leak.evidence && leak.evidence.length > 0 && <div className="text-[10px] text-info mt-3">{leak.evidence.length} evidence item{leak.evidence.length === 1 ? '' : 's'} attached</div>}
              </button>
            ))}
          </div>
        ) : (
          <div className="border border-dashed border-border-subtle rounded-xl p-6 text-xs text-text-muted font-mono text-center">No backend-ranked leaks are available for this period.</div>
        )}
      </section>

      {/* Main Interactive Funnel Pipeline */}
      <section className="glass-card p-6 z-10 space-y-6">
        <div className="flex justify-between items-center">
          <h2 className="text-lg font-heading font-bold flex items-center gap-2">
            <Activity className="w-5 h-5 text-accent-primary" /> Interactive Pipeline & Funnel Map
          </h2>
          <p className="text-xs text-text-muted font-mono">Click a stage card to analyze qualitative review data & metrics</p>
        </div>

        {/* Custom Funnel Flow Blocks */}
        <div className="flex gap-4 items-stretch relative overflow-x-auto pb-3">
          {steps.map((step, index: number) => {
            const isLeak = rankedLeaks.some(leak => leak.stage === step.name);
            const isAbove = step.conversion_rate >= step.benchmark_rate;
            const convRateVal = step.conversion_rate * 100;

            // Calculate step-to-step dropoff
            let dropoffRate = null;
            if (index > 0) {
              const prev = steps[index - 1];
              if (prev.users_completed > 0) {
                dropoffRate = 100 - (step.users_completed / prev.users_completed * 100);
              }
            }

            const isSelected = selectedStageIndex === index;

            return (
              <div key={index} className="flex flex-row items-center gap-4 shrink-0">
                {/* Stage Block Card */}
                <div
                  onClick={() => setSelectedStageIndex(index)}
                  className={`w-[190px] glass-card p-4 cursor-pointer transition-all border relative flex flex-col justify-between min-h-[160px] ${
                    isSelected ? 'border-accent-primary ring-1 ring-accent-primary/20 bg-accent-primary/5 shadow-lg' : ''
                  } hover:scale-[1.02]`}
                >
                  {/* Badge */}
                  <div className="flex justify-between items-start mb-2">
                    <span className="text-[10px] font-mono bg-white/5 border border-border-subtle text-text-muted px-2 py-0.5 rounded">
                      Stage {index + 1}
                    </span>
                    {isLeak && (
                      <span className="bg-danger/10 text-danger border border-danger/20 text-[9px] px-1.5 py-0.5 rounded uppercase font-bold tracking-wider animate-pulse">
                        Leak
                      </span>
                    )}
                    {!isLeak && isAbove && (
                      <span className="bg-success/10 text-success border border-success/20 text-[9px] px-1.5 py-0.5 rounded uppercase font-bold tracking-wider">
                        Healthy
                      </span>
                    )}
                  </div>

                  {/* Name */}
                  <h4 className="text-sm font-semibold font-heading text-text-primary mb-3 line-clamp-1">
                    {step.name}
                  </h4>

                  {/* Telemetry Progress Bar */}
                  <div className="space-y-1.5">
                    <div className="flex justify-between text-xs font-mono">
                      <span className="text-text-muted">CVR:</span>
                      <span className={`font-bold ${isLeak ? 'text-danger' : isAbove ? 'text-success' : 'text-warning'}`}>
                        {convRateVal.toFixed(1)}%
                      </span>
                    </div>
                    <div className="w-full bg-white/5 rounded-full h-1.5 overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-500 ${
                          isLeak ? 'bg-danger' : isAbove ? 'bg-success' : 'bg-warning'
                        }`}
                        style={{ width: `${Math.min(convRateVal, 100)}%` }}
                      />
                    </div>
                  </div>

                  {/* Volume Summary */}
                  <div className="flex justify-between items-center text-[10px] font-mono text-text-secondary mt-3 pt-2.5 border-t border-white/5">
                    <span>Entered: {step.users_entered.toLocaleString()}</span>
                    <span>Completed: {step.users_completed.toLocaleString()}</span>
                  </div>
                </div>

                {/* SVG/Badge Connection Link */}
                {index < steps.length - 1 && (
                  <div className="flex justify-center items-center shrink-0 w-8 h-8 font-mono text-xs">
                    {dropoffRate !== null ? (
                      <div
                        className={`px-2 py-1 rounded-md text-[9px] font-bold border whitespace-nowrap shadow-sm transform xl:rotate-0 flex items-center gap-1 ${
                          dropoffRate >= 35
                            ? 'bg-danger/10 text-danger border-danger/25'
                            : 'bg-white/5 text-text-muted border-border-subtle'
                        }`}
                        title="Leak between stages"
                      >
                        <TrendingDown className="w-3.5 h-3.5" />
                        -{dropoffRate.toFixed(0)}%
                      </div>
                    ) : (
                      <ArrowRight className="w-4 h-4 text-text-muted" />
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* Grid: Benchmark chart (left 60%) & Action panel (right 40%) */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6 z-10">

        {/* Historical/Benchmark Area Chart */}
        <div className="lg:col-span-3 glass-card p-6 flex flex-col justify-between min-h-[400px]">
          <div className="flex justify-between items-center mb-6">
            <div>
              <h3 className="text-lg font-heading font-bold">Benchmark Correlation</h3>
              <p className="text-xs text-text-secondary mt-0.5">Telemetry gaps vs baseline performance</p>
            </div>
            <div className="flex items-center gap-4 text-xs font-mono">
              <span className="flex items-center gap-1.5"><div className="w-3 h-3 bg-accent-primary/20 border border-accent-primary rounded-sm" /> Current</span>
              <span className="flex items-center gap-1.5"><div className="w-3 h-0.5 border-t-2 border-dashed border-accent-secondary" /> Benchmark</span>
            </div>
          </div>

          <div className="flex-1 min-h-[250px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={steps} margin={{ top: 10, right: 10, left: -25, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorConv" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--accent-primary)" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="var(--accent-primary)" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.03)" vertical={false} />
                <XAxis
                  dataKey="name"
                  tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(val) => val.split(' ')[0] || val}
                />
                <YAxis
                  tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(val) => `${(val * 100).toFixed(0)}%`}
                />
                <Tooltip
                  content={({ active, payload }) => {
                    if (active && payload && payload.length) {
                      const data = payload[0].payload;
                      return (
                        <div className="bg-background-base/95 border border-border-subtle p-3 rounded-lg shadow-xl font-mono text-xs max-w-[240px] backdrop-blur-sm">
                          <h4 className="font-bold text-text-primary text-sm font-sans mb-1.5">{data.name}</h4>
                          <div className="space-y-1">
                            <div className="flex justify-between gap-4"><span className="text-text-muted">Actual CVR:</span><span className="text-text-primary font-bold">{(data.conversion_rate * 100).toFixed(1)}%</span></div>
                            <div className="flex justify-between gap-4"><span className="text-text-muted">Benchmark:</span><span className="text-text-secondary">{(data.benchmark_rate * 100).toFixed(1)}%</span></div>
                            {data.gap !== null && (
                              <div className="flex justify-between gap-4 pt-1.5 border-t border-white/5">
                                <span className="text-text-muted">Gap:</span>
                                <span className={`font-bold ${data.gap >= 0 ? 'text-success' : 'text-danger'}`}>
                                  {(data.gap * 100).toFixed(1)}%
                                </span>
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="conversion_rate"
                  stroke="var(--accent-primary)"
                  strokeWidth={2}
                  fillOpacity={1}
                  fill="url(#colorConv)"
                />
                <Area
                  type="monotone"
                  dataKey="benchmark_rate"
                  stroke="var(--accent-secondary)"
                  strokeWidth={1.5}
                  strokeDasharray="4 4"
                  fill="none"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Narrative & Recommendation Panel */}
        <div className="lg:col-span-2 glass-card p-6 flex flex-col justify-between border-l-4 border-l-danger min-h-[400px]">
          <div className="space-y-4">
            <div className="flex items-center gap-2.5 text-danger font-bold font-heading">
              <AlertTriangle className="w-5 h-5 animate-pulse" /> Ranked Diagnostic & Actions
            </div>

            <div className="bg-white/5 border border-border-subtle p-4 rounded-xl space-y-2">
              <span className="text-[10px] font-mono text-text-muted uppercase tracking-wider">Backend Rank #1</span>
              <h4 className="text-sm font-bold font-heading">{bottleneckStage}</h4>
              <p className="text-xs text-text-secondary leading-relaxed font-mono">
                {bottleneckInsight}
              </p>
            </div>

            <div className="space-y-2">
              <span className="text-[10px] font-mono text-text-muted uppercase tracking-wider block">AI Generated Insight Summary</span>
              <p className="text-xs text-text-primary leading-relaxed font-mono max-h-[160px] overflow-y-auto pr-2 bg-black/10 p-3 rounded-lg border border-white/5">
                {diagnostic || 'No diagnostic statement was supplied.'}
              </p>
            </div>

            <div className="space-y-2">
              <span className="text-[10px] font-mono text-text-muted uppercase tracking-wider block">Evidence & provenance</span>
              {(topLeak?.evidence || funnelData.evidence || []).length > 0 ? (
                <div className="space-y-2">
                  {(topLeak?.evidence || funnelData.evidence || []).slice(0, 3).map((item, index) => (
                    <div key={item.id || `${item.label}-${index}`} className="bg-info/5 border border-info/15 rounded-lg p-2.5 text-[10px] font-mono">
                      <div className="flex justify-between gap-3"><span className="text-info">{item.label}</span><span className="text-text-primary">{item.value ?? '—'}</span></div>
                      <div className="text-text-muted mt-1">{item.source || 'Source unavailable'}{item.observed_at ? ` - ${new Date(item.observed_at).toLocaleString()}` : ''}</div>
                    </div>
                  ))}
                </div>
              ) : <div className="text-xs text-text-muted">No evidence payload attached.</div>}
            </div>
          </div>

          <div className="pt-4 flex gap-3">
            <button
              onClick={() => navigate(`/app/${packageId}/aso`)}
              className="flex-1 bg-accent-primary hover:bg-accent-primary/85 text-white py-2.5 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors"
            >
              <Sparkles className="w-4 h-4" /> Optimize metadata
            </button>
            <button
              onClick={() => navigate(`/app/${packageId}/journey`)}
              className="flex-1 bg-surface border border-border-subtle hover:bg-white/5 text-text-primary py-2.5 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors"
            >
              Trace Journeys <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Review Sentiment Analysis Section - Side by Side */}
      <section className="grid grid-cols-1 lg:grid-cols-5 gap-6 z-10">

        {/* Sentiment Analysis Metrics */}
        <div className="lg:col-span-2 glass-card p-6 flex flex-col justify-between space-y-6">
          <div>
            <h3 className="text-lg font-heading font-bold flex items-center gap-2">
              <MessageSquare className="w-5 h-5 text-accent-secondary" /> Play Store Review Analytics
            </h3>
             <p className="text-xs text-text-secondary mt-0.5">Rating buckets and lexical term matches from up to 50 recent reviews</p>
          </div>

          {reviewsLoading ? (
            <div className="text-text-muted text-xs italic text-center p-8 bg-surface/30 rounded-lg">Loading review source...</div>
          ) : reviewsError || reviewStatusUnavailable ? (
            <div className="text-danger text-xs p-5 bg-danger/5 border border-danger/20 rounded-lg">
              <div className="font-semibold">Review source unavailable</div>
              <div className="mt-1 text-text-secondary">{reviewsError || `The server reported review status “${reviewsAnalysis?.status}”.`}</div>
            </div>
          ) : reviewsAnalysis && !reviewSourceUsable ? (
            <div className="text-warning text-xs p-5 bg-warning/5 border border-warning/20 rounded-lg">
              <div className="font-semibold">Review source status unavailable</div>
              <div className="mt-1 text-text-secondary">The API returned zero reviews without status or provenance, so zero is not presented as an observed measurement.</div>
            </div>
          ) : reviewsAnalysis && hasReviewSample ? (
            <div className="space-y-5">
              {(reviewsAnalysis.provenance || reviewsAnalysis.status) && <div className="flex items-center justify-between gap-2"><span className="text-[10px] font-mono uppercase text-text-muted">Source status: {reviewsAnalysis.status || 'available'}</span><ProvenanceBadge provenance={reviewsAnalysis.provenance} /></div>}
              {/* Average Rating Score */}
              <div className="flex items-center justify-between bg-white/5 p-4 rounded-xl border border-border-subtle">
                <div className="space-y-0.5">
                  <span className="text-text-muted text-[10px] font-mono uppercase tracking-wider">Average Rating</span>
                  <div className="flex items-center gap-2">
                    <span className="text-2xl font-bold font-mono">{reviewsAnalysis.average_rating}</span>
                    <div className="flex text-warning">
                      {Array.from({ length: 5 }).map((_, i) => (
                        <Star
                          key={i}
                          className={`w-4 h-4 ${i < Math.round(reviewsAnalysis.average_rating) ? 'fill-current' : 'opacity-20'}`}
                        />
                      ))}
                    </div>
                  </div>
                </div>
                <div className="text-right font-mono text-xs text-text-secondary">
                  <span>Total Analysed:</span>
                  <div className="text-text-primary font-bold text-sm">{reviewsAnalysis.total_reviews}</div>
                </div>
              </div>

              {/* Sentiment Proportions */}
              <div className="space-y-2">
                <div className="flex justify-between text-xs font-mono">
                  <span className="text-text-muted">Sentiment Ratio</span>
                  <span className="text-success font-bold">{reviewsAnalysis.sentiment.positive}% Positive</span>
                </div>
                <div className="flex w-full h-3 rounded-full overflow-hidden bg-white/5 font-mono text-[9px] font-semibold text-center text-white">
                  <div
                    className="bg-success h-full flex items-center justify-center transition-all"
                    style={{ width: `${reviewsAnalysis.sentiment.positive}%` }}
                    title="Positive Reviews"
                  />
                  <div
                    className="bg-warning h-full flex items-center justify-center transition-all"
                    style={{ width: `${reviewsAnalysis.sentiment.neutral}%` }}
                    title="Neutral Reviews"
                  />
                  <div
                    className="bg-danger h-full flex items-center justify-center transition-all"
                    style={{ width: `${reviewsAnalysis.sentiment.negative}%` }}
                    title="Negative Reviews"
                  />
                </div>
                <div className="flex justify-between text-[10px] font-mono text-text-secondary pt-1">
                  <span className="flex items-center gap-1"><div className="w-2.5 h-2.5 bg-success rounded-sm" /> Pos ({reviewsAnalysis.sentiment.positive}%)</span>
                  <span className="flex items-center gap-1"><div className="w-2.5 h-2.5 bg-warning rounded-sm" /> Neu ({reviewsAnalysis.sentiment.neutral}%)</span>
                  <span className="flex items-center gap-1"><div className="w-2.5 h-2.5 bg-danger rounded-sm" /> Neg ({reviewsAnalysis.sentiment.negative}%)</span>
                </div>
              </div>

              {/* Keyword Cloud */}
              <div className="space-y-2.5">
                <span className="text-[10px] font-mono text-text-muted uppercase tracking-wider block">Frequent Review Terms</span>
                <div className="flex flex-wrap gap-2">
                  {reviewsAnalysis.keywords.map((kw, i: number) => (
                    <span
                      key={i}
                      className={`text-xs px-2.5 py-1 rounded-lg border font-mono flex items-center gap-1 ${
                        kw.sentiment === 'negative'
                          ? 'bg-danger/10 text-danger border-danger/20'
                          : 'bg-success/10 text-success border-success/20'
                      }`}
                    >
                      {kw.keyword}
                      <span className="text-[9px] opacity-60 bg-white/5 px-1 rounded font-bold">{kw.count}</span>
                    </span>
                  ))}
                  {reviewsAnalysis.keywords.length === 0 && (
                    <div className="text-text-muted text-xs italic font-mono p-2">No recurrent terms detected.</div>
                  )}
                </div>
              </div>
            </div>
          ) : reviewsAnalysis && reviewSourceExplicit ? (
            <div className="text-text-muted text-xs p-5 bg-surface/30 border border-border-subtle rounded-lg">
              <div className="font-semibold text-text-primary">Observed review sample: 0</div>
              <div className="mt-1">The source explicitly reported an empty sample for this request.</div>
              {reviewsAnalysis.provenance && <div className="mt-3"><ProvenanceBadge provenance={reviewsAnalysis.provenance} /></div>}
            </div>
          ) : (
            <div className="text-danger text-xs p-5 bg-danger/5 border border-danger/20 rounded-lg">
              Review source unavailable.
            </div>
          )}
        </div>

        {/* Selected Stage Correlation & Reviews */}
        <div className="lg:col-span-3 glass-card p-6 flex flex-col justify-between space-y-4">
          <div>
            <h3 className="text-lg font-heading font-bold flex items-center justify-between">
              <span>Feedback Correlation: {currentStage?.name}</span>
              {stageReviewData && stageReviewData.count > 0 && (
                <span className="text-xs font-mono bg-accent-primary/20 text-accent-primary px-2.5 py-0.5 rounded-full font-bold">
                  {stageReviewData.count} stage matches
                </span>
              )}
            </h3>
            <p className="text-xs text-text-secondary mt-0.5">Reviews containing words related to this funnel step</p>
          </div>

          <div className="flex-1 space-y-3 overflow-y-auto max-h-[300px] pr-2">
            {reviewsLoading ? (
              <div className="h-full flex items-center justify-center p-8 text-text-muted font-mono text-xs">Loading review source...</div>
            ) : !reviewSourceUsable ? (
              <div className="h-full flex flex-col items-center justify-center text-center p-8 bg-danger/5 border border-dashed border-danger/20 rounded-xl text-danger font-mono text-xs">
                <AlertTriangle className="w-8 h-8 mb-2 opacity-60" />
                {reviewsError || (reviewStatusUnavailable ? 'The server reported that the review source is unavailable.' : 'No source status or provenance confirms that zero stage matches were observed.')}
              </div>
            ) : !hasReviewSample ? (
              <div className="h-full flex flex-col items-center justify-center text-center p-8 bg-black/10 border border-dashed border-border-subtle rounded-xl text-text-muted font-mono text-xs">
                The review source explicitly reported an empty sample, so no stage matching was performed.
              </div>
            ) : !stageReviewData ? (
              <div className="h-full flex flex-col items-center justify-center text-center p-8 bg-warning/5 border border-dashed border-warning/20 rounded-xl text-warning font-mono text-xs">
                The review response did not include analysis for this stage, so a zero-match result cannot be inferred.
              </div>
            ) : stageReviewData.reviews.length > 0 ? (
              stageReviewData.reviews.map((r, i: number) => (
                <div key={i} className="bg-white/5 border border-border-subtle p-3.5 rounded-xl space-y-2 text-xs">
                  <div className="flex justify-between items-center">
                    <span className="font-semibold text-text-primary font-mono">{r.author_name || 'Anonymous User'}</span>
                    <div className="flex text-warning">
                      {Array.from({ length: 5 }).map((_, idx) => (
                        <Star
                          key={idx}
                          className={`w-3.5 h-3.5 ${idx < (r.rating ?? 0) ? 'fill-current' : 'opacity-10'}`}
                        />
                      ))}
                    </div>
                  </div>
                  <p className="text-text-secondary font-mono italic leading-relaxed">
                    "{r.comment}"
                  </p>
                </div>
              ))
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-center p-8 bg-black/10 border border-dashed border-border-subtle rounded-xl text-text-muted font-mono text-xs">
                <CheckCircle2 className="w-8 h-8 mb-2 text-success opacity-40" />
                 No lexical matches were found among the {reviewsAnalysis?.total_reviews} source reviews analysed. This does not establish that negative feedback is absent.
              </div>
            )}
          </div>

          {/* Quick correlation narrative */}
          {stageReviewData && stageReviewData.count > 0 && (
            <div className="bg-warning/10 border border-warning/20 p-3 rounded-lg text-xs font-mono text-warning flex items-start gap-2">
              <Info className="w-4 h-4 shrink-0 mt-0.5" />
              <span>
                 {stageReviewData.count} lexical stage match{stageReviewData.count === 1 ? '' : 'es'} average {stageReviewData.rating}/5. Review matches and funnel drop-offs are shown together as evidence, not as a causal correlation.
              </span>
            </div>
          )}
        </div>
      </section>

      {/* Active Experiments Sidebar (Full Width horizontal) */}
      <section className="glass-card p-6 z-10 space-y-4">
        <h3 className="text-lg font-heading font-bold flex items-center gap-2">
          <Layers className="w-5 h-5 text-accent-primary" /> Experiment Records
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {experiments.slice(0, 3).map((exp) => (
            <div key={exp.id} className="bg-surface border border-border-subtle p-4 rounded-xl flex flex-col justify-between min-h-[140px]">
              <div>
                <div className="flex justify-between items-start mb-2">
                  <span className="text-[9px] font-mono bg-info/20 text-info px-2 py-0.5 rounded uppercase font-semibold border border-info/10">
                    {exp.experiment_type}
                  </span>
                  <span className="text-[10px] text-text-muted font-mono">{exp.days_active || 0}d active</span>
                </div>
                <p className="text-xs text-text-primary leading-relaxed font-mono line-clamp-2 mb-2">
                  {exp.hypothesis}
                </p>
              </div>
              <div className="flex items-center justify-between text-[10px] font-mono pt-2 border-t border-white/5">
                <span className="text-accent-secondary font-bold uppercase">{exp.status}</span>
                {exp.confidence && (
                  <span className="text-success font-bold">Conf: {(exp.confidence * 100).toFixed(0)}%</span>
                )}
              </div>
            </div>
          ))}
          {experiments.length === 0 && (
            <div className="col-span-3 text-text-muted text-xs italic text-center p-8 bg-surface/30 rounded-xl font-mono">
              No active test campaigns or proposed metadata experiments.
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
