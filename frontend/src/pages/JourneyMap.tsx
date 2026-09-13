import { useState, useEffect, useId, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  AlertTriangle,
  Code,
  Database,
  Star,
  Sparkles,
  Activity,
  X,
  Clipboard,
  Check,
  Compass,
  Terminal,
  HelpCircle
} from 'lucide-react';
import { api, type JourneyDefinition, type JourneyRow, type Provenance, type Review } from '../api';
import { getErrorMessage } from '../utils';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { useAccessibleDialog } from '../components/useAccessibleDialog';

type OverlayPeriod = '7d' | '30d' | '90d';

const eventCache = new Map<string, { counts: Record<string, number>; users: Record<string, number>; fetchedAt: number }>();

export default function JourneyMap() {
  const { packageId } = useParams<{ packageId: string }>() as { packageId: string };
  const navigate = useNavigate();
  const [journeysData, setJourneysData] = useState<Record<string, JourneyDefinition> | null>(null);
  const [journeysPackage, setJourneysPackage] = useState<string | null>(null);
  const [selectedJourneyId, setSelectedJourneyId] = useState<string>('1');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Live Data Overlay — on by default so event counts show immediately
  const [liveOverlay, setLiveOverlay] = useState(true);
  const [eventCounts, setEventCounts] = useState<Record<string, number>>({});
  const [eventUsers, setEventUsers] = useState<Record<string, number>>({});
  const [overlayLoading, setOverlayLoading] = useState(true);
  const [overlayError, setOverlayError] = useState<string | null>(null);
  const [overlayPeriod, setOverlayPeriod] = useState<OverlayPeriod>('30d');
  const [overlayFetchedAt, setOverlayFetchedAt] = useState<number | null>(null);
  const journeyGeneration = useRef(0);
  const telemetryGeneration = useRef(0);
  const journeyRequest = useRef<AbortController | null>(null);
  const telemetryRequest = useRef<AbortController | null>(null);

  // Selected Stage for Side Panel Drawer
  const [selectedStage, setSelectedStage] = useState<JourneyRow | null>(null);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [reviewsLoading, setReviewsLoading] = useState(false);
  const [reviewsError, setReviewsError] = useState<string | null>(null);
  const [reviewsStatus, setReviewsStatus] = useState<string | null>(null);
  const [reviewsProvenance, setReviewsProvenance] = useState<Provenance | null>(null);
  const reviewRequest = useRef(0);
  const reviewController = useRef<AbortController | null>(null);
  const [activeTab, setActiveTab] = useState<'analytics' | 'feedback' | 'dev'>('analytics');

  // Copy to Clipboard indicator
  const [copied, setCopied] = useState(false);

  const closeStage = () => {
    ++reviewRequest.current;
    reviewController.current?.abort();
    setSelectedStage(null);
    setReviews([]);
    setReviewsLoading(false);
    setReviewsError(null);
    setReviewsStatus(null);
    setReviewsProvenance(null);
  };
  const stageDialogRef = useAccessibleDialog(Boolean(selectedStage), closeStage);
  const stageTitleId = useId();
  const stageDescriptionId = useId();

  useEffect(() => {
    const generation = ++journeyGeneration.current;
    journeyRequest.current?.abort();
    telemetryRequest.current?.abort();
    reviewController.current?.abort();
    ++reviewRequest.current;
    const controller = new AbortController();
    journeyRequest.current = controller;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- route changes must immediately invalidate package-bound state
    setJourneysData(null);
    setJourneysPackage(null);
    setSelectedJourneyId('1');
    setSelectedStage(null);
    setReviews([]);
    setReviewsLoading(false);
    setReviewsError(null);
    setReviewsStatus(null);
    setReviewsProvenance(null);
    setEventCounts({});
    setEventUsers({});
    setOverlayFetchedAt(null);
    setOverlayError(null);
    setOverlayLoading(liveOverlay);
    setError(null);
    setLoading(true);
    api.getAppJourneys(packageId, controller.signal)
      .then(res => {
        if (controller.signal.aborted || journeyGeneration.current !== generation) return;
        setJourneysData(res.journeys || {});
        setJourneysPackage(packageId);
        const keys = Object.keys(res.journeys || {});
        if (keys.length > 0) {
          setSelectedJourneyId(keys[0]);
        }
        setLoading(false);
      })
      .catch(err => {
        if (controller.signal.aborted || journeyGeneration.current !== generation) return;
        setError(getErrorMessage(err, 'Failed to load journey map data'));
        setJourneysPackage(packageId);
        setLoading(false);
      });
    return () => {
      controller.abort();
    };
    // The route package owns all state reset above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [packageId]);

  // Load and cache GA4 event counts only while the live overlay is enabled.
  useEffect(() => {
    const generation = ++telemetryGeneration.current;
    telemetryRequest.current?.abort();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- period/package changes must clear the previous telemetry snapshot
    setEventCounts({});
    setEventUsers({});
    setOverlayFetchedAt(null);
    setOverlayError(null);
    if (!liveOverlay) {
      setOverlayLoading(false);
      return;
    }
    setOverlayLoading(true);
    const cacheKey = `${packageId}:${overlayPeriod}`;
    const cached = eventCache.get(cacheKey);
    if (cached && Date.now() - cached.fetchedAt < 15 * 60 * 1000) {
      Promise.resolve().then(() => {
        if (telemetryGeneration.current !== generation) return;
        setEventCounts(cached.counts);
        setEventUsers(cached.users);
        setOverlayFetchedAt(cached.fetchedAt);
        setOverlayLoading(false);
      });
      return;
    }
    const controller = new AbortController();
    telemetryRequest.current = controller;
    api.getAppEvents(packageId, overlayPeriod, controller.signal)
      .then(res => {
        if (controller.signal.aborted || telemetryGeneration.current !== generation) return;
        const counts: Record<string, number> = {};
        const users: Record<string, number> = {};
        if (res?.events) {
          res.events.forEach((e) => {
            if (e.event_name) {
              counts[e.event_name] = e.event_count || 0;
              users[e.event_name] = e.total_users || 0;
            }
          });
        } else if (res?.rows) {
          res.rows.forEach((row) => {
            const name = row.dimensionValues?.[0]?.value || row.name;
            const value = parseInt(String(row.metricValues?.[0]?.value || row.value || '0'), 10);
            if (name && Number.isFinite(value)) counts[name] = value;
          });
        }
        setEventCounts(counts);
        setEventUsers(users);
        const fetchedAt = Date.now();
        eventCache.set(cacheKey, { counts, users, fetchedAt });
        setOverlayFetchedAt(fetchedAt);
        setOverlayError(null);
        setOverlayLoading(false);
      })
      .catch(err => {
        if (controller.signal.aborted || telemetryGeneration.current !== generation) return;
        setOverlayError(getErrorMessage(err, 'Telemetry snapshot unavailable'));
        setOverlayLoading(false);
      });
    return () => controller.abort();
  }, [liveOverlay, overlayPeriod, packageId]);

  const openStage = (row: JourneyRow) => {
    const requestId = ++reviewRequest.current;
    reviewController.current?.abort();
    const controller = new AbortController();
    reviewController.current = controller;
    setSelectedStage(row);
    setActiveTab('analytics');
    setReviews([]);
    setReviewsLoading(true);
    setReviewsError(null);
    setReviewsStatus(null);
    setReviewsProvenance(null);
    let stageCategory = 'onboarding';
    if (selectedJourneyId === '2') stageCategory = 'paywall';
    else if (selectedJourneyId === '3') stageCategory = 'dashboard';
    else if (parseInt(selectedJourneyId, 10) >= 4) stageCategory = 'core_calculator';
    api.getAppReviews(packageId, stageCategory, controller.signal)
      .then(result => {
        if (controller.signal.aborted || reviewRequest.current !== requestId) return;
        if (Array.isArray(result)) {
          setReviews(result);
        } else {
          setReviews(result.reviews || []);
          setReviewsStatus(result.status || null);
          setReviewsProvenance(result.provenance || null);
        }
      })
      .catch(err => {
        if (controller.signal.aborted || reviewRequest.current !== requestId) return;
        setReviews([]);
        setReviewsError(getErrorMessage(err, 'Review source unavailable'));
      })
      .finally(() => {
        if (reviewRequest.current === requestId) setReviewsLoading(false);
      });
  };

  if (loading || journeysPackage !== packageId) {
    return (
      <div className="p-8 flex items-center justify-center h-[80vh] flex-col gap-4">
        <div className="w-10 h-10 border-4 border-accent-primary border-t-transparent rounded-full animate-spin" />
        <p className="text-text-secondary font-mono text-sm">Compiling user paths & code mapping...</p>
      </div>
    );
  }

  if (error || !journeysData) {
    return (
      <div className="p-8 text-center text-danger h-[80vh] flex flex-col justify-center items-center">
        <AlertTriangle className="w-16 h-16 mx-auto mb-4 animate-bounce" />
        <p className="font-heading font-bold text-xl">{error || 'No journey map loaded'}</p>
      </div>
    );
  }

  const selectedJourney = journeysData[selectedJourneyId];
  const sections = selectedJourney?.sections || [];
  const normalizedReviewsStatus = reviewsStatus?.toLowerCase() || null;
  const reviewsStatusUnavailable = Boolean(normalizedReviewsStatus && ['unavailable', 'error', 'failed', 'failure'].includes(normalizedReviewsStatus));
  const reviewsSourceExplicit = Boolean(reviewsProvenance)
    || Boolean(normalizedReviewsStatus && ['available', 'success', 'ok', 'empty', 'observed'].includes(normalizedReviewsStatus));

  const cleanEventName = (rawEvent: string) => {
    if (!rawEvent) return '';
    const clean = rawEvent.replace(/[`*_]/g, '').trim();
    if (clean.includes('none') || clean.includes('—') || clean.includes('*')) {
      return '';
    }
    return clean;
  };

  const getCodePath = (rawFile: string) => rawFile.startsWith('/') ? `file://${rawFile}` : null;

  const copyText = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="p-6 max-w-[1600px] mx-auto min-h-screen flex flex-col relative overflow-hidden space-y-6 pb-12">
      {/* Background glow */}
      <div className="absolute top-[-10%] left-[-15%] w-[45%] h-[45%] bg-accent-primary/5 rounded-full blur-[140px] pointer-events-none" />
      <div className="absolute bottom-[-10%] right-[-15%] w-[45%] h-[45%] bg-accent-secondary/5 rounded-full blur-[140px] pointer-events-none" />

      {/* Header */}
      <header className="flex justify-between items-start z-10 border-b border-border-subtle pb-4">
        <div>
          <div className="flex items-center gap-2 mb-1.5">
            <span className="bg-accent-secondary/20 text-accent-secondary text-[10px] px-2.5 py-0.5 rounded font-mono font-bold uppercase">Flow Diagnostics</span>
          </div>
          <h1 className="text-3xl font-heading font-bold mb-1.5 flex items-center gap-3">
            <Compass className="w-8 h-8 text-accent-secondary" /> User Journey Maps
          </h1>
          <p className="text-text-secondary font-mono text-xs">{packageId}</p>
        </div>

        <div className="flex flex-wrap justify-end items-center gap-3">
          <div className="flex bg-surface border border-border-subtle rounded-lg p-1">
            {(['7d', '30d', '90d'] as const).map(period => (
              <button
                key={period}
                onClick={() => {
                  if (period === overlayPeriod) return;
                  setOverlayPeriod(period);
                  if (liveOverlay) {
                    setOverlayLoading(true);
                    setOverlayError(null);
                  }
                }}
                className={`px-2.5 py-1 rounded text-[10px] font-mono font-bold transition-colors ${overlayPeriod === period ? 'bg-accent-secondary text-background-base' : 'text-text-muted hover:text-text-primary'}`}
              >
                {period}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-3 bg-surface border border-border-subtle rounded-xl px-4 py-2">
            <span className="text-xs font-mono font-bold text-text-primary flex items-center gap-2">
              <Activity className={`w-4 h-4 ${liveOverlay ? 'text-accent-secondary animate-pulse' : 'text-text-muted'}`} />
              Cached Telemetry Snapshot
            </span>
            <button
              onClick={() => {
                if (!liveOverlay) {
                  setOverlayLoading(true);
                  setOverlayError(null);
                }
                setLiveOverlay(!liveOverlay);
              }}
              className={`w-9 h-5 rounded-full p-0.5 transition-colors outline-none ${liveOverlay ? 'bg-accent-secondary' : 'bg-white/10'}`}
            >
              <div className={`w-4 h-4 rounded-full bg-white transition-transform ${liveOverlay ? 'translate-x-4' : 'translate-x-0'}`} />
            </button>
          </div>
          {liveOverlay && (overlayLoading || overlayError) && (
            <span className={`text-[10px] font-mono ${overlayError ? 'text-danger' : 'text-text-muted animate-pulse'}`}>
              {overlayError || 'Fetching GA4 telemetry snapshot...'}
            </span>
          )}
          {liveOverlay && !overlayLoading && !overlayError && overlayFetchedAt && (
            <span className="text-[10px] font-mono text-text-muted">Cached snapshot fetched {new Date(overlayFetchedAt).toLocaleString()}</span>
          )}
        </div>
      </header>

      {/* Main Content Layout */}
      <div className="flex flex-col lg:flex-row gap-6 z-10 flex-1 items-start">

        {/* Navigation Sidebar */}
        <aside className="w-full lg:w-72 shrink-0 flex flex-col bg-surface border border-border-subtle rounded-xl p-4 space-y-3">
          <div className="text-[10px] font-mono font-bold text-text-muted uppercase tracking-wider px-2">Flow Navigator</div>
          <div className="space-y-1.5">
            {Object.keys(journeysData).map((id) => {
              const j = journeysData[id];
              const flowStages = j.sections?.reduce((total, section) => total + (section.rows?.length || 0), 0) || 0;
              const isSelected = selectedJourneyId === id;
              return (
                <button
                  key={id}
                  onClick={() => {
                    setSelectedJourneyId(id);
                    closeStage();
                  }}
                  className={`w-full text-left px-3.5 py-3 rounded-lg text-sm transition-all font-mono flex items-center justify-between border ${
                    isSelected
                      ? 'bg-accent-primary/10 text-text-primary border-accent-primary'
                      : 'text-text-secondary hover:text-text-primary hover:bg-white/5 border-transparent'
                  }`}
                >
                  <div className="flex items-center gap-2.5 truncate">
                    <span className={`w-2 h-2 rounded-full ${isSelected ? 'bg-accent-primary animate-pulse' : 'bg-text-muted'}`} />
                    <span className="truncate">{j.title}</span>
                  </div>
                  <span className="text-[9px] bg-white/5 border border-border-subtle text-text-muted px-2 py-0.5 rounded font-bold shrink-0 ml-2">
                    {flowStages} Steps
                  </span>
                </button>
              );
            })}
          </div>
        </aside>

        {/* Stages Board & Flow Timeline */}
        <section className="flex-1 flex flex-col min-w-0 w-full space-y-6">
          {/* Active Flow Info Header */}
          <div className="glass-card p-5 border-l-4 border-l-accent-secondary">
            <span className="text-[10px] font-mono text-text-muted uppercase tracking-wider block mb-1">Active User Path</span>
            <h2 className="text-xl font-heading font-bold text-text-primary mb-2">
              JOURNEY {selectedJourneyId}: {selectedJourney?.title}
            </h2>
            {selectedJourney?.description && (
              <p className="text-text-secondary text-xs whitespace-pre-line leading-relaxed font-mono mt-2 bg-black/10 p-3.5 rounded-lg border border-white/5">
                {selectedJourney.description}
              </p>
            )}
          </div>

          <div className="space-y-8">
            {sections.map((section, sectionIndex) => {
              const rows = section.rows || [];
              return (
                <div key={`${section.section_title || 'section'}-${sectionIndex}`} className="space-y-4 relative pl-8 py-2">
                  <div className="absolute top-10 bottom-0 left-[31px] w-[2px] bg-white/5 border-l border-dashed border-border-subtle" />
                  <div className="flex items-center gap-3 -ml-8">
                    <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-accent-secondary">
                      {section.section_title || `Section ${sectionIndex + 1}`}
                    </span>
                    <div className="h-px flex-1 bg-border-subtle" />
                  </div>

                  {rows.map((row, index) => {
                    const stepName = row.Step || `${index + 1}`;
                    const stateName = row['Screen / State'] || row.State || 'State';
                    const eventName = cleanEventName(row.Event || '');
                    const nextStep = row.Next || '—';
                    const nextEventName = cleanEventName(nextStep);
                    const hasEvent = eventName !== '';
                    const currentUserTotal = eventUsers[eventName];
                    const nextUserTotal = eventUsers[nextEventName];
                    const currentEventTotal = eventCounts[eventName];
                    const nextEventTotal = eventCounts[nextEventName];
                    const ratioBasis = currentUserTotal !== undefined && nextUserTotal !== undefined
                      ? 'user'
                      : currentEventTotal !== undefined && nextEventTotal !== undefined ? 'event' : null;
                    const ratioCurrent = ratioBasis === 'user' ? currentUserTotal : currentEventTotal;
                    const ratioNext = ratioBasis === 'user' ? nextUserTotal : nextEventTotal;
                    const rawRatio = ratioCurrent !== undefined && ratioNext !== undefined && ratioCurrent > 0
                      ? (ratioNext / ratioCurrent) * 100
                      : null;
                    const aggregateRatio = rawRatio !== null && Number.isFinite(rawRatio) && rawRatio >= 0 && rawRatio <= 100 ? rawRatio : null;
                    const aggregateDecrease = aggregateRatio === null ? null : 100 - aggregateRatio;
                    const displayTotal = currentUserTotal ?? currentEventTotal;
                    const displayLabel = currentUserTotal !== undefined ? 'Aggregate users' : 'Event volume';
                    const isPaywall = ['paywall', 'purchase', 'subscription', 'premium'].some(term => eventName.includes(term));
                    const isCrash = ['crash', 'error', 'exception', 'failed', 'fail'].some(term => eventName.includes(term));
                    const isEngagement = ['engagement', 'session', 'open', 'load'].some(term => eventName.includes(term));
                    const isSelected = selectedStage === row;

                    return (
                      <div key={`${sectionIndex}-${stepName}-${index}`} className="relative space-y-4">
                        <div className="flex items-start gap-4">
                          <div className={`w-8 h-8 rounded-full shrink-0 flex items-center justify-center font-mono text-xs z-10 border transition-all ${
                            isCrash ? 'bg-danger/20 text-danger border-danger/40' :
                            isPaywall ? 'bg-warning/20 text-warning border-warning/40' :
                            isSelected ? 'bg-accent-primary text-white border-accent-primary shadow-[0_0_12px_rgba(139,92,246,0.5)]' :
                            'bg-surface text-text-secondary border-border-subtle'
                          }`}>
                            {stepName}
                          </div>

                          <div
                            onClick={() => openStage(row)}
                            className={`flex-1 glass-card p-4 cursor-pointer hover:border-accent-secondary/50 border transition-all relative flex flex-col md:flex-row md:items-center justify-between gap-4 ${isSelected ? 'bg-accent-secondary/5 border-accent-secondary shadow-md' : ''}`}
                          >
                            <div className="space-y-1">
                              <div className="flex flex-wrap items-center gap-2">
                                <span className={`text-[9px] px-2 py-0.5 rounded font-mono font-bold uppercase border ${
                                  isPaywall ? 'bg-warning/10 text-warning border-warning/20' :
                                  isCrash ? 'bg-danger/10 text-danger border-danger/20' :
                                  isEngagement ? 'bg-info/10 text-info border-info/20' :
                                  'bg-accent-secondary/10 text-accent-secondary border-accent-secondary/20'
                                }`}>
                                  {hasEvent ? eventName : 'no_event'}
                                </span>
                                <span className="text-[10px] text-text-muted font-mono">→ {nextStep}</span>
                              </div>
                              <h3 className="text-sm font-semibold font-heading text-text-primary">{stateName.replace('GA4 Event: ', '')}</h3>
                            </div>

                            {liveOverlay && !overlayLoading && hasEvent && displayTotal !== undefined ? (
                              <div className="flex gap-4 shrink-0 font-mono text-xs">
                                <div className="text-right">
                                  <span className="text-text-muted text-[10px] block">{displayLabel}</span>
                                  <span className="text-text-primary font-bold">{displayTotal.toLocaleString()}</span>
                                </div>
                                {aggregateRatio !== null && (
                                  <div className="text-right border-l border-white/5 pl-4">
                                    <span className="text-text-muted text-[10px] block">Next aggregate {ratioBasis} ratio</span>
                                    <span className={`font-bold ${aggregateRatio >= 70 ? 'text-success' : aggregateRatio >= 45 ? 'text-warning' : 'text-danger'}`}>{aggregateRatio.toFixed(1)}%</span>
                                  </div>
                                )}
                                {rawRatio !== null && aggregateRatio === null && (
                                  <div className="text-right border-l border-white/5 pl-4 text-warning text-[10px] max-w-32">Non-cohort totals cannot form a conversion rate</div>
                                )}
                              </div>
                            ) : (
                              <div className="text-text-muted text-[10px] italic font-mono shrink-0">
                                {hasEvent ? (overlayLoading ? 'Loading telemetry...' : overlayError ? 'Telemetry unavailable' : 'Metrics unavailable') : 'No telemetry mapped'}
                              </div>
                            )}
                          </div>
                        </div>

                        {index < rows.length - 1 && aggregateDecrease !== null && aggregateDecrease > 10 && (
                          <div className="pl-14 py-1 flex items-center gap-2">
                            <div className="h-0.5 w-4 bg-warning/20" />
                            <span className="text-[9px] font-mono font-bold bg-warning/10 text-warning border border-warning/20 px-2 py-0.5 rounded-full flex items-center gap-1">
                              <AlertTriangle className="w-3 h-3" />
                              Aggregate {ratioBasis} total is {aggregateDecrease.toFixed(0)}% lower for the mapped next event; this is not cohort conversion.
                            </span>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}

            {sections.every(section => (section.rows?.length || 0) === 0) && (
              <div className="w-full flex items-center justify-center text-text-muted border border-dashed border-border-subtle rounded-xl p-12 font-mono text-xs">
                <HelpCircle className="w-6 h-6 mr-2 opacity-50" /> No stages configured for this journey map.
              </div>
            )}
          </div>
        </section>
      </div>

      {/* Side detail Panel Drawer Overlay */}
      {selectedStage && (
        <aside ref={stageDialogRef} role="dialog" aria-modal="true" aria-labelledby={stageTitleId} aria-describedby={stageDescriptionId} tabIndex={-1} className="fixed top-0 right-0 h-screen w-full sm:w-[460px] bg-background-base/95 border-l border-border-subtle shadow-[0_0_60px_rgba(0,0,0,0.6)] z-50 flex flex-col backdrop-blur-md transition-all duration-300 outline-none">

          {/* Drawer Header */}
          <div className="p-6 border-b border-border-subtle flex justify-between items-center bg-black/30">
            <div>
              <span className="bg-accent-secondary/20 text-accent-secondary text-[9px] px-2 py-0.5 rounded font-mono font-bold uppercase">Stage Diagnostics</span>
              <h3 id={stageTitleId} className="font-heading font-bold text-lg text-text-primary mt-1 truncate max-w-[280px]">
                {selectedStage["Screen / State"] || selectedStage["State"] || "Stage Detail"}
              </h3>
              <p id={stageDescriptionId} className="text-[10px] text-text-muted font-mono mt-0.5">Journey {selectedJourneyId} - Step {selectedStage["Step"]}</p>
            </div>
            <button
              data-dialog-initial-focus
              onClick={closeStage}
              aria-label="Close stage diagnostics"
              className="p-1.5 rounded-full hover:bg-white/5 border border-border-subtle text-text-muted hover:text-text-primary transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Tabs Navigation */}
          <div className="flex border-b border-border-subtle font-mono text-xs bg-black/10">
            <button
              onClick={() => setActiveTab('analytics')}
              className={`flex-1 py-3 text-center font-bold border-b-2 transition-all ${
                activeTab === 'analytics' ? 'border-accent-secondary text-accent-secondary' : 'border-transparent text-text-muted hover:text-text-primary'
              }`}
            >
              Telemetry
            </button>
            <button
              onClick={() => setActiveTab('feedback')}
              className={`flex-1 py-3 text-center font-bold border-b-2 transition-all ${
                activeTab === 'feedback' ? 'border-accent-secondary text-accent-secondary' : 'border-transparent text-text-muted hover:text-text-primary'
              }`}
            >
              Feedback
            </button>
            <button
              onClick={() => setActiveTab('dev')}
              className={`flex-1 py-3 text-center font-bold border-b-2 transition-all ${
                activeTab === 'dev' ? 'border-accent-secondary text-accent-secondary' : 'border-transparent text-text-muted hover:text-text-primary'
              }`}
            >
              Source Code
            </button>
          </div>

          {/* Drawer Scrollable Content */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6">

            {/* TAB 1: Analytics / Telemetry */}
            {activeTab === 'analytics' && (
              <div className="space-y-6">
                {/* Mini Metric Grid */}
                <div className="grid grid-cols-2 gap-4">
                  <div className="bg-white/5 border border-border-subtle p-3 rounded-xl font-mono">
                    <span className="text-text-muted text-[10px] block">Aggregate users ({overlayPeriod})</span>
                    <span className="text-lg font-bold text-text-primary">
                      {(() => {
                        const name = cleanEventName(selectedStage.Event);
                        return liveOverlay && !overlayLoading ? (eventUsers[name] ?? eventCounts[name] ?? '—') : '—';
                      })()}
                    </span>
                  </div>
                  <div className="bg-white/5 border border-border-subtle p-3 rounded-xl font-mono">
                    <span className="text-text-muted text-[10px] block">Event Volume</span>
                    <span className="text-lg font-bold text-text-primary">
                      {liveOverlay && !overlayLoading ? (eventCounts[cleanEventName(selectedStage.Event)] ?? '—') : '—'}
                    </span>
                  </div>
                </div>

                {/* BigQuery SQL Template */}
                {cleanEventName(selectedStage?.Event) && (
                  <div className="space-y-3">
                    <div className="flex justify-between items-center text-xs font-mono">
                      <span className="text-text-muted uppercase tracking-wider flex items-center gap-1.5">
                        <Database className="w-4 h-4 text-accent-secondary" /> BigQuery Path SQL
                      </span>
                      <button
                        onClick={() => {
                          const name = cleanEventName(selectedStage.Event);
                          const query = `SELECT
  event_date,
  count(distinct user_pseudo_id) as unique_users,
  count(1) as event_count
FROM \`YOUR_GCP_PROJECT.analytics_PROPERTY_ID.events_*\`
WHERE event_name = '${name}'
  AND _TABLE_SUFFIX BETWEEN FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL ${parseInt(overlayPeriod, 10)} DAY))
                        AND FORMAT_DATE('%Y%m%d', CURRENT_DATE())
GROUP BY 1
ORDER BY 1 ASC;`;
                          copyText(query);
                        }}
                        className="text-accent-secondary hover:underline flex items-center gap-1"
                      >
                        {copied ? <Check className="w-3.5 h-3.5" /> : <Clipboard className="w-3.5 h-3.5" />}
                        {copied ? 'Copied' : 'Copy'}
                      </button>
                    </div>
                    <div className="bg-black/50 border border-border-subtle p-4 rounded-xl overflow-x-auto relative">
                      <pre className="text-[10px] text-accent-secondary font-mono leading-relaxed">
{`SELECT
  event_date,
  count(distinct user_pseudo_id) as unique_users,
  count(1) as event_count
FROM \`YOUR_GCP_PROJECT.analytics_PROPERTY_ID.events_*\`
WHERE event_name = '${cleanEventName(selectedStage.Event)}'
  AND _TABLE_SUFFIX BETWEEN FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL ${parseInt(overlayPeriod, 10)} DAY))
                        AND FORMAT_DATE('%Y%m%d', CURRENT_DATE())
GROUP BY 1
ORDER BY 1 ASC;`}
                      </pre>
                    </div>
                  </div>
                )}

                {/* Action Card */}
                <div className="bg-gradient-to-r from-accent-primary/10 to-transparent border border-accent-primary/20 p-5 rounded-xl space-y-3">
                  <div className="flex items-center gap-2 text-text-primary font-bold text-sm font-heading">
                    <Sparkles className="w-5 h-5 text-accent-primary" /> Sprint Opportunity
                  </div>
                  <p className="text-xs text-text-secondary leading-relaxed font-mono">
                    Treat this stage as a recommendation signal. Executable journey experiments are disabled until the server owns their validation and rollback contracts.
                  </p>
                  <button
                    onClick={() => navigate(`/app/${encodeURIComponent(packageId)}/aso`)}
                    className="w-full bg-accent-primary hover:bg-accent-primary/80 text-white py-2.5 rounded-lg text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors"
                  >
                    <Sparkles className="w-4 h-4" /> Open validated ASO proposal path
                  </button>
                </div>
              </div>
            )}

            {/* TAB 2: Qualitative Feedback (Play Reviews) */}
            {activeTab === 'feedback' && (
              <div className="space-y-4">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[10px] font-mono text-text-muted uppercase tracking-wider">Lexical stage matches from recent reviews</div>
                  {reviewsProvenance && <ProvenanceBadge provenance={reviewsProvenance} />}
                </div>
                <div className="space-y-3">
                  {reviewsLoading ? (
                    <div className="space-y-2">
                      <div className="h-20 w-full bg-white/5 animate-pulse rounded-xl" />
                      <div className="h-20 w-full bg-white/5 animate-pulse rounded-xl" />
                    </div>
                  ) : reviewsError || reviewsStatusUnavailable ? (
                    <div className="text-danger text-xs p-5 bg-danger/5 border border-danger/20 rounded-xl font-mono">
                      <div className="font-semibold">Review source unavailable</div>
                      <div className="mt-1 text-text-secondary">{reviewsError || `The server reported review status “${reviewsStatus}”.`}</div>
                    </div>
                  ) : reviews.length > 0 ? (
                    reviews.map((r, i) => (
                      <div key={i} className="bg-white/5 border border-border-subtle p-4 rounded-xl space-y-2 text-xs">
                        <div className="flex justify-between items-center">
                          <span className="font-semibold text-text-primary font-mono">{r.author_name || 'Anonymous User'}</span>
                          <div className="flex text-warning">
                            {Array.from({ length: r.star_rating ?? r.rating ?? 0 }).map((_, idx) => (
                              <Star key={idx} className="w-3.5 h-3.5 fill-current" />
                            ))}
                          </div>
                        </div>
                        <p className="text-text-secondary leading-relaxed font-mono italic">"{r.comment}"</p>
                        {r.developer_reply && (
                          <div className="mt-2.5 pl-3 border-l-2 border-accent-secondary text-[11px] text-accent-secondary/80 font-mono">
                            Developer Reply: "{r.developer_reply}"
                          </div>
                        )}
                      </div>
                    ))
                  ) : reviewsSourceExplicit ? (
                    <div className="text-text-muted text-xs italic p-6 bg-white/5 rounded-xl text-center border border-dashed border-border-subtle font-mono">
                      The available review source returned zero lexical matches for this stage. This does not indicate that negative feedback is absent.
                    </div>
                  ) : (
                    <div className="text-warning text-xs p-5 bg-warning/5 border border-warning/20 rounded-xl font-mono">
                      <div className="font-semibold">Review source status unavailable</div>
                      <div className="mt-1 text-text-secondary">The API returned an empty list without status or provenance, so it cannot be treated as an observed zero.</div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* TAB 3: Developer Resources / Source Code */}
            {activeTab === 'dev' && (
              <div className="space-y-4">
                <div className="text-[10px] font-mono text-text-muted uppercase tracking-wider">Associated Native Activities</div>

                {selectedJourney?.description?.includes('File:') ? (
                  <div className="bg-white/5 border border-border-subtle p-4 rounded-xl space-y-3">
                    <div className="text-xs font-mono flex items-center gap-1.5 text-text-primary">
                      <Code className="w-4 h-4 text-accent-primary" /> Code Binding
                    </div>
                    {(() => {
                       const fileMatch = selectedJourney.description?.match(/File:\s*\[?([^\]\n]+)\]?/);
                      const filename = fileMatch ? fileMatch[1].trim() : 'Source File';
                      return (
                        <div className="flex flex-col gap-2">
                          <span className="font-mono text-xs text-accent-primary bg-black/20 p-2 rounded truncate border border-white/5">
                            {filename}
                          </span>
                           {getCodePath(filename) && (
                             <a
                               href={getCodePath(filename) || undefined}
                               className="text-xs text-white bg-accent-primary hover:bg-accent-primary/80 py-2 rounded-lg font-mono text-center font-bold transition-all mt-1"
                               target="_blank"
                               rel="noopener noreferrer"
                             >
                               Open Native File
                             </a>
                           )}
                        </div>
                      );
                    })()}
                  </div>
                ) : (
                  <div className="bg-white/5 border border-border-subtle p-4 rounded-xl space-y-3 text-xs font-mono">
                    <div className="text-text-muted flex items-center gap-1.5">
                      <Terminal className="w-4 h-4" /> Layout Configuration
                    </div>
                    <p className="text-text-secondary leading-relaxed">
                      No direct class binding detected in this flow catalog. Check android manifest XML to locate the launch target path.
                    </p>
                  </div>
                )}
              </div>
            )}

          </div>
        </aside>
      )}

    </div>
  );
}
