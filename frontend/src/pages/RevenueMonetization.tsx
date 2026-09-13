import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { DollarSign, TrendingUp, CreditCard, PlaySquare, MapPin, Globe, Compass, RefreshCw, AlertTriangle } from 'lucide-react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { api, type RevenueResponse, type StorefrontRow } from '../api';
import { getErrorMessage } from '../utils';

export default function RevenueMonetization() {
  const { packageId } = useParams<{ packageId: string }>() as { packageId: string };
  const navigate = useNavigate();
  const [revenueData, setRevenueData] = useState<RevenueResponse | null>(null);
  const [storefrontData, setStorefrontData] = useState<{ country?: StorefrontRow[]; traffic_source?: StorefrontRow[] } | null>(null);
  const [adsData, setAdsData] = useState<{ google_ads?: { cost_usd?: number } | null } | null>(null);
  const [timelineData, setTimelineData] = useState<{ daily?: Array<{ date: string; revenue: number }> } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = () => {
    setLoading(true);
    setError(null);
    // Core data — if this fails, show error state
    Promise.all([
      api.getAppRevenue(packageId, '30d'),
      api.getAppStorefront(packageId, '30d'),
      api.getAppAds(packageId, '30d'),
    ])
      .then(([rev, store, ads]) => {
        setRevenueData(rev);
        setStorefrontData(store);
        setAdsData(ads);
        setLoading(false);
      })
      .catch(err => {
        console.error(err);
        setError(getErrorMessage(err, 'Failed to load revenue and storefront data'));
        setLoading(false);
      });
    // Timeline is optional — failure doesn't block the page, falls back to synthetic
    api.getAppAdmobTimeline(packageId, 30)
      .then(timeline => setTimelineData(timeline))
      .catch(() => setTimelineData(null));
  };

  useEffect(() => {
    let active = true;
    Promise.all([
      api.getAppRevenue(packageId, '30d'),
      api.getAppStorefront(packageId, '30d'),
      api.getAppAds(packageId, '30d'),
    ]).then(([rev, store, ads]) => {
      if (!active) return;
      setRevenueData(rev);
      setStorefrontData(store);
      setAdsData(ads);
      setLoading(false);
    }).catch(err => {
      if (!active) return;
      setError(getErrorMessage(err, 'Failed to load revenue and storefront data'));
      setLoading(false);
    });
    api.getAppAdmobTimeline(packageId, 30)
      .then(timeline => { if (active) setTimelineData(timeline); })
      .catch(() => { if (active) setTimelineData(null); });
    return () => { active = false; };
  }, [packageId]);

  if (loading) {
    return (
      <div className="p-8 flex justify-center items-center h-full">
        <div className="animate-spin w-8 h-8 border-2 border-accent-primary border-t-transparent rounded-full" />
      </div>
    );
  }

  // Parse Metrics
  const admob = revenueData?.admob || {};
  const rc = revenueData?.revenuecat || null;
  const gcsIap = revenueData?.gcs_iap || null;
  const ascIap = revenueData?.app_store || null;
  const googleAds = adsData?.google_ads || null;

  // IAP/subscription revenue: use first available source
  const iapRevenue: number = rc?.revenue ?? gcsIap?.iap_revenue_30d ?? ascIap?.iap_revenue_30d ?? 0;
  const iapSource: string | null = rc ? 'RevenueCat' : gcsIap ? 'Play Console' : ascIap ? 'App Store Connect' : null;
  const mrr: number = rc?.mrr ?? 0;
  const adRevenue: number = admob.ad_revenue_30d || 0;
  const totalRevenue: number = iapRevenue + adRevenue;

  const adsCost: number | null = googleAds?.cost_usd ?? null;
  const adsRoas: number | null = adsCost != null && adsCost > 0 && totalRevenue > 0
    ? totalRevenue / adsCost
    : null;

  // The timeline endpoint currently provides AdMob daily values only.
  const realDaily: {date: string; revenue: number}[] = timelineData?.daily || [];
  const chartData = realDaily.slice(-30).map(d => ({
        date: d.date.slice(5).replace('-', '/'),
        admob: Math.round(d.revenue * 100) / 100,
        iap: 0,
        subs: 0,
      }));

  // Extract storefront lists
  const countryList = storefrontData?.country || [];
  const trafficList = storefrontData?.traffic_source || [];

  return (
    <div className="p-8 max-w-[1400px] mx-auto min-h-screen relative overflow-hidden">
      {/* Background glow */}
      <div className="absolute top-[-10%] left-[-10%] w-[35%] h-[35%] bg-accent-secondary/5 rounded-full blur-[100px] pointer-events-none" />

      <header className="mb-8 flex justify-between items-end z-10">
        <div>
          <h1 className="text-3xl font-heading font-bold mb-2">Revenue & Monetization</h1>
          <p className="text-text-secondary">Combined view of AdMob, IAP, and Subscriptions.</p>
        </div>
        <button
          onClick={loadData}
          className="p-2 bg-surface hover:bg-white/5 border border-border-subtle text-text-primary rounded-lg text-sm transition-all"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </header>

      {error && (
        <div className="bg-danger/10 border border-danger/20 text-danger text-sm p-4 rounded-lg flex items-center gap-3 mb-6">
          <AlertTriangle className="w-5 h-5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-5 gap-6 mb-8 z-10">
        <div className="glass-card p-5 border-l-4 border-l-success">
          <div className="flex items-center gap-2 text-text-muted mb-2 text-xs uppercase tracking-wider">
            <DollarSign className="w-4 h-4 text-success" /> Total Revenue (30d)
          </div>
          <div className="text-3xl font-mono font-bold">${totalRevenue.toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0})}</div>
          <div className="text-success text-xs flex items-center gap-1 mt-2 font-mono">
             <TrendingUp className="w-3 h-3" /> AdMob + subscription/IAP
          </div>
        </div>
        <div className="glass-card p-5">
          <div className="flex items-center gap-2 text-text-muted mb-2 text-xs uppercase tracking-wider">
            <PlaySquare className="w-4 h-4 text-accent-primary" /> AdMob Revenue
          </div>
          <div className="text-3xl font-mono font-bold">${adRevenue.toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0})}</div>
          <div className="text-text-secondary text-xs mt-2 font-mono">
            {totalRevenue > 0 ? Math.round((adRevenue / totalRevenue) * 100) : 0}% of total
          </div>
        </div>
        <div className="glass-card p-5">
          <div className="flex items-center gap-2 text-text-muted mb-2 text-xs uppercase tracking-wider">
            <CreditCard className="w-4 h-4 text-info" /> IAP / Subs Payout (30d)
          </div>
          <div className="text-3xl font-mono font-bold">${iapRevenue.toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0})}</div>
          <div className="text-text-secondary text-xs mt-2 font-mono">
            {iapSource ? `via ${iapSource}` : 'No source'} · {totalRevenue > 0 ? Math.round((iapRevenue / totalRevenue) * 100) : 0}% of total
          </div>
        </div>
        <div className="glass-card p-5">
          <div className="flex items-center gap-2 text-text-muted mb-2 text-xs uppercase tracking-wider">
            <CreditCard className="w-4 h-4 text-warning" /> Subscription MRR
          </div>
          <div className="text-3xl font-mono font-bold">${mrr.toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0})}</div>
          <div className="text-text-secondary text-xs mt-2 font-mono">
            Active: {rc?.active_subscriptions ?? '—'} subs
          </div>
        </div>
        <div className="glass-card p-5 border-l-4 border-l-danger">
          <div className="flex items-center gap-2 text-text-muted mb-2 text-xs uppercase tracking-wider">
            <TrendingUp className="w-4 h-4 text-danger" /> Ads Spend (30d)
          </div>
          {adsCost != null ? (
            <>
              <div className="text-3xl font-mono font-bold text-danger">
                ${adsCost.toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0})}
              </div>
              <div className="text-xs mt-2 font-mono text-accent-primary font-bold">
                {adsRoas != null ? `ROAS ${adsRoas.toFixed(2)}x` : adsCost === 0 ? 'No active campaigns' : '—'}
              </div>
            </>
          ) : (
            <>
              <div className="text-3xl font-mono font-bold text-text-muted">—</div>
              <div className="text-text-muted text-xs mt-2 font-mono">No Google Ads config</div>
            </>
          )}
        </div>
      </div>

      {/* Main Chart */}
      <div className="glass-card p-6 h-[400px] mb-8 z-10">
        <h2 className="text-lg font-heading font-bold mb-6">AdMob Revenue (Daily, up to 30 Days)</h2>
        {chartData.length > 0 ? <ResponsiveContainer width="100%" height="85%">
          <AreaChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="colorAdmob" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="var(--accent-primary)" stopOpacity={0.3}/>
                <stop offset="95%" stopColor="var(--accent-primary)" stopOpacity={0}/>
              </linearGradient>
              <linearGradient id="colorIap" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="var(--info)" stopOpacity={0.3}/>
                <stop offset="95%" stopColor="var(--info)" stopOpacity={0}/>
              </linearGradient>
              <linearGradient id="colorSubs" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="var(--warning)" stopOpacity={0.3}/>
                <stop offset="95%" stopColor="var(--warning)" stopOpacity={0}/>
              </linearGradient>
            </defs>
            <XAxis dataKey="date" stroke="var(--border)" tick={{ fill: 'var(--text-muted)' }} />
            <YAxis stroke="var(--border)" tick={{ fill: 'var(--text-muted)' }} />
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
            <Tooltip contentStyle={{ backgroundColor: 'var(--background-base)', borderColor: 'var(--border)' }} />
            <Area type="monotone" dataKey="admob" stackId="1" stroke="var(--accent-primary)" fill="url(#colorAdmob)" />
            <Area type="monotone" dataKey="iap" stackId="1" stroke="var(--info)" fill="url(#colorIap)" />
            <Area type="monotone" dataKey="subs" stackId="1" stroke="var(--warning)" fill="url(#colorSubs)" />
          </AreaChart>
        </ResponsiveContainer> : (
          <div className="h-[85%] flex items-center justify-center text-xs text-text-muted font-mono border border-dashed border-border-subtle rounded-xl">
             Daily AdMob timeline unavailable. Summary totals remain available from the returned revenue sources.
          </div>
        )}
      </div>

      {/* Storefront Performance Split Tables */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8 z-10">

        {/* Country Conversions */}
        <div className="glass-card p-6">
          <h2 className="text-lg font-heading font-bold mb-4 flex items-center gap-2">
            <Globe className="w-5 h-5 text-accent-secondary" /> Country Conversions
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-mono">
              <thead>
                <tr className="border-b border-border-subtle text-text-muted">
                  <th className="pb-3 uppercase">Country</th>
                  <th className="pb-3 uppercase">Visitors</th>
                  <th className="pb-3 uppercase">Installs</th>
                  <th className="pb-3 uppercase">CVR</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle/30">
                {countryList.slice(0, 5).map((c, i: number) => (
                  <tr key={i} className="hover:bg-white/2 transition-colors">
                    <td className="py-3 font-medium font-sans text-text-primary flex items-center gap-2">
                      <MapPin className="w-3.5 h-3.5 text-accent-secondary" /> {c.country}
                    </td>
                    <td className="py-3 text-text-secondary">{(c.visitors || 0).toLocaleString()}</td>
                    <td className="py-3 text-text-secondary">{(c.installs || 0).toLocaleString()}</td>
                    <td className="py-3 font-bold text-text-primary">{(c.conversion_rate * 100).toFixed(1)}%</td>
                  </tr>
                ))}
                {countryList.length === 0 && (
                  <tr>
                    <td colSpan={4} className="py-4 text-center text-text-muted italic">
                      No country stats in storefront database.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Traffic Sources */}
        <div className="glass-card p-6">
          <h2 className="text-lg font-heading font-bold mb-4 flex items-center gap-2">
            <Compass className="w-5 h-5 text-accent-primary" /> Acquisition Channels
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-mono">
              <thead>
                <tr className="border-b border-border-subtle text-text-muted">
                  <th className="pb-3 uppercase">Channel</th>
                  <th className="pb-3 uppercase">Visitors</th>
                  <th className="pb-3 uppercase">Installs</th>
                  <th className="pb-3 uppercase">CVR</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle/30">
                {trafficList.slice(0, 5).map((t, i: number) => (
                  <tr key={i} className="hover:bg-white/2 transition-colors">
                    <td className="py-3 font-medium font-sans text-text-primary truncate max-w-[150px]">{t.traffic_source}</td>
                    <td className="py-3 text-text-secondary">{(t.visitors || 0).toLocaleString()}</td>
                    <td className="py-3 text-text-secondary">{(t.installs || 0).toLocaleString()}</td>
                    <td className="py-3 font-bold text-text-primary">{(t.conversion_rate * 100).toFixed(1)}%</td>
                  </tr>
                ))}
                {trafficList.length === 0 && (
                  <tr>
                    <td colSpan={4} className="py-4 text-center text-text-muted italic">
                      No acquisition channel stats in storefront database.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

      </div>

      <div className="glass-card p-6 mt-8 z-10 bg-background-base/60 border border-border-subtle">
        <h2 className="text-lg font-heading font-bold mb-3 flex items-center gap-2 border-b border-border-subtle pb-3">
          <DollarSign className="w-5 h-5 text-accent-primary" /> Monetization Experiment Recommendation
        </h2>
        <p className="text-xs text-text-secondary leading-relaxed max-w-3xl">
          Revenue and storefront evidence can inform a paywall hypothesis, but this client does not create executable RevenueCat payloads. Paywall mutations remain unavailable until the server owns validator, approval, snapshot, and rollback contracts for offering changes.
        </p>
        <button onClick={() => navigate(`/app/${encodeURIComponent(packageId)}/aso`)} className="mt-5 bg-surface border border-border-subtle hover:border-accent-primary/50 text-text-primary py-2.5 px-5 rounded-lg text-xs font-semibold">
          Open server-validated ASO proposal workspace
        </button>
      </div>

    </div>
  );
}
