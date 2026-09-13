import { useEffect, useId, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowUpRight,
  ArrowDownRight,
  ShieldAlert,
  TrendingDown,
  Search,
  Layers,
  ArrowRight,
  TrendingUp,
  Cpu,
  Zap,
  Clock3
} from 'lucide-react';

import { api, type Opportunity, type PortfolioApp, type PortfolioSummary, type SystemStatus } from '../api';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { getErrorMessage } from '../utils';

// Premium Custom SVG Sparkline Component with Filled Gradient Area
function CustomSparkline({ data }: { data: number[] }) {
  const gradId = useId();
  if (!data || data.length === 0) {
    return <div className="text-[10px] text-text-muted">No data</div>;
  }
  const width = 120;
  const height = 32;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const points = data.map((val, index) => {
    const x = data.length === 1 ? width / 2 : (index / (data.length - 1)) * width;
    const y = height - ((val - min) / range) * (height - 6) - 3;
    return { x, y };
  });

  const pathData = points.reduce((acc, p, i) => {
    if (i === 0) return `M ${p.x} ${p.y}`;
    return `${acc} L ${p.x} ${p.y}`;
  }, '');

  const areaData = `${pathData} L ${width} ${height} L 0 ${height} Z`;

  return (
    <div className="w-full h-8 relative">
      <svg width="100%" height="100%" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent-secondary)" stopOpacity={0.25} />
            <stop offset="100%" stopColor="var(--accent-secondary)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <path d={areaData} fill={`url(#${gradId})`} />
        <path d={pathData} fill="none" stroke="var(--accent-secondary)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  );
}

// Circular SVG Progress Ring for Funnel Health
function HealthIndicator({ score }: { score: number }) {
  const isHealthy = score >= 80;
  const isWarning = score >= 60 && score < 80;
  const color = isHealthy ? '#10b981' : isWarning ? '#f59e0b' : '#ef4444';

  const radius = 16;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (score / 100) * circumference;

  return (
    <div className="relative flex items-center justify-center w-12 h-12 select-none">
      <svg className="w-full h-full transform -rotate-90" viewBox="0 0 40 40">
        {/* Track */}
        <circle cx="20" cy="20" r={radius} fill="transparent" stroke="rgba(255, 255, 255, 0.03)" strokeWidth="3" />
        {/* Progress */}
        <circle
          cx="20"
          cy="20"
          r={radius}
          fill="transparent"
          stroke={color}
          strokeWidth="3.5"
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          strokeLinecap="round"
          className="transition-all duration-700 ease-out"
          style={{ filter: `drop-shadow(0 0 2px ${color}55)` }}
        />
      </svg>
      <span className="absolute text-[11px] font-mono font-bold" style={{ color }}>{score}</span>
    </div>
  );
}

export default function PortfolioCommandCenter() {
  const [data, setData] = useState<{
    apps: PortfolioApp[];
    portfolio_summary: PortfolioSummary;
    opportunities: Opportunity[];
    topOpportunity: Opportunity | null;
    systemStatus: SystemStatus;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [costs, setCosts] = useState<Record<string, number | null> | null>(null);
  const [period, setPeriod] = useState<'30d' | '7d'>('30d');
  const [refreshTick, setRefreshTick] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState<'opportunity' | 'health' | 'revenue'>('opportunity');
  const navigate = useNavigate();

  useEffect(() => {
    let active = true;
    Promise.all([
      api.getPortfolio(period),
      api.getPortfolioSummary(period),
      api.getSystemStatus().catch(() => ({ scheduler: { state: 'unavailable' } })),
    ])
      .then(([portfolio, summary, systemStatus]) => {
        if (!active) return;
        setData({
          apps: portfolio.apps,
          portfolio_summary: summary.portfolio_summary,
          opportunities: portfolio.opportunities || [],
          topOpportunity: portfolio.top_opportunity || null,
          systemStatus,
        });
        setLoading(false);
      })
      .catch(err => {
        if (!active) return;
        console.error(err);
        setError(getErrorMessage(err, 'Failed to load portfolio data'));
        setLoading(false);
      });
    return () => { active = false; };
  }, [period, refreshTick]);

  useEffect(() => {
    const refreshWhenVisible = () => {
      if (document.visibilityState === 'visible') setRefreshTick(tick => tick + 1);
    };
    const interval = window.setInterval(refreshWhenVisible, 5 * 60_000);
    document.addEventListener('visibilitychange', refreshWhenVisible);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', refreshWhenVisible);
    };
  }, []);

  // Fetch Google Ads costs independently
  useEffect(() => {
    api.getPortfolioCosts()
      .then(res => setCosts(res.costs || {}))
      .catch(() => setCosts({}));
  }, []);

  if (error) {
    return (
      <div className="p-8 text-center text-danger flex flex-col items-center justify-center min-h-[500px]">
        <ShieldAlert className="w-16 h-16 mb-4 text-danger animate-pulse" />
        <h2 className="font-heading font-bold text-xl mb-2">Portfolio Data Error</h2>
        <p className="text-text-secondary text-sm max-w-md">{error}</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="p-8 flex flex-col gap-4 items-center justify-center min-h-[500px]">
        <div className="w-10 h-10 border-4 border-accent-primary border-t-transparent rounded-full animate-spin" />
        <span className="text-xs text-text-muted font-mono tracking-widest uppercase animate-pulse">Syncing metrics hub...</span>
      </div>
    );
  }

  if (!data) return null;
  const { apps, portfolio_summary: summary } = data;
  const schedulerState = data.systemStatus.scheduler?.state || 'unavailable';
  const schedulerTone = schedulerState === 'running' ? 'text-success' : schedulerState === 'stale' ? 'text-warning' : 'text-danger';
  const schedulerDot = schedulerState === 'running' ? 'bg-success' : schedulerState === 'stale' ? 'bg-warning' : 'bg-danger';

  // Compute portfolio-level spend and ROAS from the costs dict
  const totalSpend = costs
    ? Object.values(costs).reduce((sum: number, v) => sum + (v ?? 0), 0)
    : 0;

  const portfolioRoas = totalSpend > 0 ? summary.total_revenue_30d / totalSpend : null;
  const hasSpend = costs !== null && totalSpend > 0;


  // Filter apps based on search query
  const backendOpportunities = [
    ...(data.topOpportunity ? [data.topOpportunity] : []),
    ...data.opportunities,
    ...apps.flatMap(app => app.top_opportunity ? [app.top_opportunity] : []),
  ].filter((opportunity, index, all) => all.findIndex(item => item.id === opportunity.id) === index);
  const topOpportunity = [...backendOpportunities].sort((a, b) => {
    const impactDelta = (b.impact ?? Number.NEGATIVE_INFINITY) - (a.impact ?? Number.NEGATIVE_INFINITY);
    if (impactDelta !== 0) return impactDelta;
    return Date.parse(b.freshness || '') - Date.parse(a.freshness || '');
  })[0] || null;

  const filteredApps = apps
    .filter((app) => {
      const q = searchQuery.toLowerCase();
      return app.display_name.toLowerCase().includes(q) || app.package_name.toLowerCase().includes(q);
    })
    .sort((a, b) => {
      if (sortBy === 'revenue') return b.revenue_30d - a.revenue_30d;
      if (sortBy === 'health') return a.funnel_health_score - b.funnel_health_score;
      const impactDelta = (b.top_opportunity?.impact ?? Number.NEGATIVE_INFINITY)
        - (a.top_opportunity?.impact ?? Number.NEGATIVE_INFINITY);
      if (impactDelta !== 0) return impactDelta;
      return Date.parse(b.top_opportunity?.freshness || '') - Date.parse(a.top_opportunity?.freshness || '');
    });

  return (
    <div className="p-8 max-w-7xl mx-auto min-h-screen relative">
      {/* Dynamic Background Glows */}
      <div className="absolute top-[-10%] right-[-5%] w-[450px] h-[450px] bg-accent-primary/5 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute bottom-[20%] left-[-10%] w-[350px] h-[350px] bg-accent-secondary/5 rounded-full blur-[100px] pointer-events-none" />

      {/* Header section */}
      <header className="mb-10 flex flex-col md:flex-row md:items-end justify-between gap-6 z-10 relative">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="relative flex h-2 w-2">
              {schedulerState === 'running' && <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-success opacity-75"></span>}
              <span className={`relative inline-flex rounded-full h-2 w-2 ${schedulerDot}`}></span>
            </span>
            <span className={`text-[10px] font-mono tracking-wider uppercase font-semibold ${schedulerTone}`}>Scheduler {schedulerState.replaceAll('_', ' ')}</span>
          </div>
          <h1 className="text-4xl font-heading font-black tracking-tight text-white mb-2 bg-gradient-to-r from-white via-white to-text-secondary bg-clip-text">
            Portfolio Command Center
          </h1>
          <p className="text-text-secondary text-sm max-w-2xl">
            Persisted portfolio snapshots, source status, and optimization controls across your application ecosystem.
          </p>
        </div>

        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
          {/* Search bar */}
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
            <input
              type="text"
              placeholder="Search apps..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="bg-surface/40 hover:bg-surface/60 focus:bg-surface/80 border border-border-subtle focus:border-accent-primary rounded-xl pl-9 pr-4 py-2 text-xs text-text-primary focus:outline-none transition-all w-full sm:w-[220px]"
            />
          </div>

          {/* Period Toggle */}
          <div className="flex items-center gap-1 bg-surface/40 border border-border-subtle rounded-xl p-1">
            {(['7d', '30d'] as const).map(p => (
              <button
                key={p}
                onClick={() => {
                  if (p !== period) {
                    setLoading(true);
                    setError(null);
                    setPeriod(p);
                  }
                }}
                className={`px-4 py-1.5 rounded-lg text-xs font-mono font-bold uppercase transition-all ${
                  period === p
                    ? 'bg-accent-primary text-white shadow-lg shadow-accent-primary/20'
                    : 'text-text-secondary hover:text-text-primary'
                }`}
              >
                {p}
              </button>
            ))}
          </div>
        </div>
      </header>

      {/* Summary Hub Cards */}
      <section className="mb-10 z-10 relative">
        <h2 className="text-xs font-mono uppercase tracking-wider text-text-muted mb-4 font-bold flex items-center gap-2">
          <Layers className="w-3.5 h-3.5" /> Aggregated Performance Metrics
        </h2>

        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-4">

          <div className="glass-card p-4 flex flex-col justify-between border-t-2 border-t-success/60 bg-gradient-to-b from-success/5 via-transparent to-transparent">
            <div>
              <div className="text-[10px] text-text-muted font-bold uppercase tracking-wider mb-1">Total Revenue</div>
              <div className="text-xl font-mono font-bold text-success">${(summary.total_revenue_30d || 0).toLocaleString(undefined, {maximumFractionDigits: 0})}</div>
            </div>
            <div className="text-[9px] text-text-muted mt-2 font-mono flex items-center gap-1">
              <TrendingUp className="w-2.5 h-2.5 text-success" /> blended 30d
            </div>
          </div>

          <div className="glass-card p-4 flex flex-col justify-between border-t-2 border-t-accent-secondary/60 bg-gradient-to-b from-accent-secondary/5 via-transparent to-transparent">
            <div>
              <div className="text-[10px] text-text-muted font-bold uppercase tracking-wider mb-1">Total Profit</div>
              <div className="text-xl font-mono font-bold text-accent-secondary">${(summary.total_profit_30d || 0).toLocaleString(undefined, {maximumFractionDigits: 0})}</div>
            </div>
            <div className="text-[9px] text-text-muted mt-2 font-mono">net payload</div>
          </div>

          <div className="glass-card p-4 flex flex-col justify-between border-t-2 border-t-info/60 bg-gradient-to-b from-info/5 via-transparent to-transparent">
            <div>
              <div className="text-[10px] text-text-muted font-bold uppercase tracking-wider mb-1">Ad Revenue</div>
              <div className="text-xl font-mono font-bold text-info">${(summary.total_ad_revenue_30d || 0).toLocaleString(undefined, {maximumFractionDigits: 0})}</div>
            </div>
            <div className="text-[9px] text-text-muted mt-2 font-mono">AdMob streams</div>
          </div>

          <div className="glass-card p-4 flex flex-col justify-between border-t-2 border-t-accent-primary/60 bg-gradient-to-b from-accent-primary/5 via-transparent to-transparent">
            <div>
              <div className="text-[10px] text-text-muted font-bold uppercase tracking-wider mb-1">Active Exps</div>
              <div className="text-xl font-mono font-bold text-accent-primary">{summary.active_experiments}</div>
            </div>
            <div className="text-[9px] text-text-muted mt-2 font-mono">Live variant tests</div>
          </div>

          <div className="glass-card p-4 flex flex-col justify-between">
            <div>
              <div className="text-[10px] text-text-muted font-bold uppercase tracking-wider mb-1">Approvals</div>
              <div className={`text-xl font-mono font-bold ${summary.pending_approvals > 0 ? 'text-warning' : 'text-text-primary'}`}>{summary.pending_approvals}</div>
            </div>
            <div className="text-[9px] text-text-muted mt-2 font-mono">Awaiting rollouts</div>
          </div>

          <div className="glass-card p-4 flex flex-col justify-between">
            <div>
              <div className="text-[10px] text-text-muted font-bold uppercase tracking-wider mb-1">Trust Tier</div>
              <div className="text-sm font-heading font-black uppercase tracking-widest text-accent-secondary mt-1">{summary.trust_tier}</div>
            </div>
            <div className="text-[9px] text-text-muted mt-2 font-mono">Autonomous limit</div>
          </div>

          <div className="glass-card p-4 flex flex-col justify-between border-t-2 border-t-danger/60 bg-gradient-to-b from-danger/5 via-transparent to-transparent">
            <div>
              <div className="text-[10px] text-text-muted font-bold uppercase tracking-wider mb-1">Total Spend</div>
              <div className="text-xl font-mono font-bold text-danger">
                {hasSpend ? `$${totalSpend.toLocaleString(undefined, {maximumFractionDigits: 0})}` : '—'}
              </div>
            </div>
            <div className="text-[9px] text-text-muted mt-2 font-mono">Campaign expenses</div>
          </div>

          <div className="glass-card p-4 flex flex-col justify-between border-t-2 border-t-warning/60 bg-gradient-to-b from-warning/5 via-transparent to-transparent">
            <div>
              <div className="text-[10px] text-text-muted font-bold uppercase tracking-wider mb-1">Portfolio ROAS</div>
              <div className="text-xl font-mono font-bold text-warning">
                {portfolioRoas != null ? `${portfolioRoas.toFixed(2)}x` : '—'}
              </div>
            </div>
            <div className="text-[9px] text-text-muted mt-2 font-mono">Efficiency index</div>
          </div>

        </div>
      </section>

      {topOpportunity && (
        <section className="mb-8 z-10 relative glass-card overflow-hidden border-accent-primary/30">
          <div className="absolute inset-y-0 left-0 w-1 bg-gradient-to-b from-accent-primary to-accent-secondary" />
          <div className="p-5 md:p-6 flex flex-col md:flex-row md:items-center gap-5">
            <div className="p-3 rounded-xl bg-accent-primary/10 text-accent-primary self-start">
              <Zap className="w-6 h-6" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-accent-secondary mb-1">Top ranked opportunity</div>
              <h2 className="text-lg font-heading font-bold text-white">{topOpportunity.title}</h2>
              {topOpportunity.summary && <p className="text-xs text-text-secondary mt-1 max-w-3xl">{topOpportunity.summary}</p>}
              <div className="flex flex-wrap gap-3 mt-3 text-[10px] font-mono">
                {topOpportunity.app_package && <span className="text-text-muted">{topOpportunity.app_package}</span>}
                <ProvenanceBadge provenance={topOpportunity.provenance} />
              </div>
            </div>
            <div className="flex gap-3 shrink-0">
              <div className="bg-black/20 border border-border-subtle rounded-lg px-4 py-3">
                <div className="text-[9px] uppercase text-text-muted font-mono">Impact</div>
                <div className="text-sm font-bold font-mono text-success">
                  {topOpportunity.impact == null ? 'Unavailable' : `${topOpportunity.impact.toLocaleString()}${topOpportunity.impact_unit ? ` ${topOpportunity.impact_unit}` : ''}`}
                </div>
              </div>
              <div className="bg-black/20 border border-border-subtle rounded-lg px-4 py-3">
                <div className="text-[9px] uppercase text-text-muted font-mono">Freshness</div>
                <div className="text-sm font-bold font-mono flex items-center gap-1.5">
                  <Clock3 className="w-3.5 h-3.5 text-accent-secondary" />
                  {topOpportunity.freshness ? new Date(topOpportunity.freshness).toLocaleDateString() : 'Unavailable'}
                </div>
              </div>
            </div>
          </div>
        </section>
      )}

      {/* App Grid */}
      <section className="z-10 relative">
        <div className="mb-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <h2 className="text-xs font-mono uppercase tracking-wider text-text-muted font-bold">
            Individual Application Nodes ({filteredApps.length})
            {searchQuery && <span className="ml-2 text-accent-secondary normal-case font-sans">Filtered from {apps.length} total</span>}
          </h2>
          <label className="flex items-center gap-2 text-[10px] font-mono uppercase text-text-muted">
            Sort
            <select value={sortBy} onChange={event => setSortBy(event.target.value as typeof sortBy)} className="bg-surface border border-border-subtle rounded-lg px-2.5 py-1.5 text-xs text-text-primary normal-case outline-none focus:border-accent-primary">
              <option value="opportunity">Opportunity impact</option>
              <option value="health">Lowest health</option>
              <option value="revenue">Revenue</option>
            </select>
          </label>
        </div>

        {filteredApps.length === 0 ? (
          <div className="glass-card p-12 text-center text-text-secondary flex flex-col items-center justify-center">
            <Cpu className="w-10 h-10 mb-3 text-text-muted animate-pulse" />
            <p className="font-heading font-medium text-base mb-1">No matching apps found</p>
            <p className="text-xs text-text-muted">Refine your search parameter or select another filter.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredApps.map((app) => {
              const isIos = app.package_name.includes('-id') || !app.package_name.startsWith('com.');


              // Get cost & roas metrics
              const appCost: number | null | undefined = costs?.[app.package_name];
              const appRoas = appCost != null && appCost > 0 && app.revenue_30d > 0
                ? app.revenue_30d / appCost
                : null;

              return (
                <div
                  key={app.package_name}
                  className="glass-card p-6 cursor-pointer group relative overflow-hidden flex flex-col justify-between hover:scale-[1.01] hover:border-white/15 transition-all duration-300 shadow-lg hover:shadow-accent-primary/5"
                  onClick={() => navigate(`/app/${encodeURIComponent(app.package_name)}/funnel`)}
                >
                  {/* Glowing background card element */}
                  <div className="absolute top-0 right-0 w-24 h-24 bg-gradient-to-bl from-white/5 via-transparent to-transparent opacity-30 pointer-events-none" />

                  <div>
                    {/* Header: Title, platform badge, health indicator */}
                    <div className="flex justify-between items-start gap-4 mb-4">
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5 mb-1 flex-wrap">
                          <h3 className="text-base font-heading font-bold text-white group-hover:text-accent-secondary transition-colors duration-200 truncate">
                            {app.display_name}
                          </h3>
                          <span className={`text-[8px] font-mono font-black uppercase px-1.5 py-0.5 rounded ${isIos ? 'bg-indigo-500/10 text-indigo-400 border border-indigo-500/20' : 'bg-success/10 text-success border border-success/20'}`}>
                            {isIos ? 'iOS' : 'Android'}
                          </span>
                        </div>
                        <div className="text-[10px] text-text-muted font-mono truncate">{app.package_name}</div>
                      </div>
                      <HealthIndicator score={app.funnel_health_score} />
                    </div>

                    {/* Performance metrics grid */}
                    <div className="grid grid-cols-4 gap-2 py-4 border-y border-border-subtle/50 my-4 text-xs">
                      <div>
                        <div className="text-[9px] text-text-muted font-mono uppercase tracking-wider mb-1">Revenue</div>
                        <div className="font-mono font-bold text-white text-xs truncate">
                          ${(app.revenue_30d || 0).toLocaleString(undefined, {maximumFractionDigits: 0})}
                        </div>
                        <div className={`text-[8px] font-mono flex items-center mt-0.5 ${app.revenue_change_pct >= 0 ? 'text-success' : 'text-danger'}`}>
                          {app.revenue_change_pct >= 0 ? <ArrowUpRight className="w-2 h-2" /> : <ArrowDownRight className="w-2 h-2" />}
                          {Math.abs(app.revenue_change_pct)}%
                        </div>
                      </div>

                      <div>
                        <div className="text-[9px] text-text-muted font-mono uppercase tracking-wider mb-1">Ads Cost</div>
                        <div className="font-mono font-bold text-danger text-xs truncate">
                          {appCost != null ? `$${appCost.toLocaleString(undefined, {maximumFractionDigits: 0})}` : '—'}
                        </div>
                        {appRoas != null && (
                          <div className="text-[8px] font-mono text-warning mt-0.5">
                            {appRoas.toFixed(1)}x ROAS
                          </div>
                        )}
                      </div>

                      <div>
                        <div className="text-[9px] text-text-muted font-mono uppercase tracking-wider mb-1">Net Profit</div>
                        <div className="font-mono font-bold text-success text-xs truncate">
                          ${(app.profit_30d || 0).toLocaleString(undefined, {maximumFractionDigits: 0})}
                        </div>
                      </div>

                      <div>
                        <div className="text-[9px] text-text-muted font-mono uppercase tracking-wider mb-1.5">Weekly Vol</div>
                        <CustomSparkline data={app.installs_7d} />
                      </div>
                    </div>
                  </div>

                  {/* Card bottom bar: Experiments & worst stage warning */}
                  <div className="flex items-center justify-between mt-2 pt-2 text-[10px]">
                    <div className="flex items-center gap-1.5">
                      <span className="text-text-muted uppercase tracking-wider font-mono text-[9px]">Exps:</span>
                      {app.active_experiments > 0 ? (
                        <div className="flex gap-1">
                          {Array.from({length: app.active_experiments}).map((_, i) => (
                            <span key={i} className="relative flex h-1.5 w-1.5">
                              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-primary opacity-75"></span>
                              <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-accent-primary"></span>
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-text-muted font-mono">—</span>
                      )}
                    </div>

                    {app.worst_stage && app.worst_stage.name !== 'N/A' ? (
                      <div className="bg-danger/5 border border-danger/15 text-danger text-[8px] uppercase tracking-wider px-2 py-0.5 rounded font-mono font-semibold flex items-center gap-1">
                        <TrendingDown className="w-2.5 h-2.5" /> Leak: {app.worst_stage.name} ({(app.worst_stage.value * 100).toFixed(0)}%)
                      </div>
                    ) : (
                      <div className="text-[8px] text-success uppercase tracking-wider px-2 py-0.5 rounded font-mono font-semibold flex items-center gap-1 bg-success/5 border border-success/15">
                        Stable Funnel
                      </div>
                    )}
                  </div>

                  {app.top_opportunity && (
                    <div className="mt-3 pt-3 border-t border-border-subtle/50 flex items-start justify-between gap-3 text-[10px]">
                      <div className="min-w-0">
                        <div className="text-accent-secondary font-mono uppercase tracking-wider mb-0.5">Opportunity</div>
                        <div className="text-text-primary truncate">{app.top_opportunity.title}</div>
                      </div>
                      <div className="font-mono text-success shrink-0">
                        {app.top_opportunity.impact == null ? 'Impact unavailable' : `${app.top_opportunity.impact.toLocaleString()}${app.top_opportunity.impact_unit ? ` ${app.top_opportunity.impact_unit}` : ''}`}
                      </div>
                    </div>
                  )}

                  {/* Slide in Arrow Indicator on Hover */}
                  <div className="absolute right-3 bottom-3 opacity-0 translate-x-2 group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-300 pointer-events-none">
                    <ArrowRight className="w-3.5 h-3.5 text-accent-secondary" />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
