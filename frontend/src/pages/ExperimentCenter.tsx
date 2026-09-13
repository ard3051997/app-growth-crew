import { useEffect, useId, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowRight,
  ArrowUpRight,
  Check,
  Clock,
  Database,
  FlaskConical,
  Plus,
  RefreshCw,
  RotateCcw,
  Shield,
  Sparkles,
  TrendingUp,
  X,
  XCircle,
} from 'lucide-react';

import {
  api,
  type Experiment,
  type ExperimentDesignRecommendation,
  type ExperimentRecommendationFocus,
  type ExperimentRecommendationResponse,
  type ExperimentSemanticAction,
  type ExperimentTypeDefinition,
  type FieldChange,
  type PortfolioApp,
} from '../api';
import { LifecycleProgress } from '../components/LifecycleProgress';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { useAccessibleDialog } from '../components/useAccessibleDialog';
import { getErrorMessage } from '../utils';

const actionLabels: Record<ExperimentSemanticAction, string> = {
  approve: 'Approve proposal',
  reject: 'Reject proposal',
  execute: 'Execute approved change',
  evaluate: 'Evaluate evidence',
  retain: 'Retain winning change',
  rollback: 'Rollback live change',
};

function formatValue(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? 'Unavailable' : value.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function proposalChanges(experiment: Experiment): FieldChange[] {
  if (experiment.proposal?.changes) return experiment.proposal.changes;
  const current = experiment.proposal?.current;
  const proposed = experiment.proposal?.proposed;
  if (!current || !proposed) return [];
  return (['title', 'short_description', 'full_description'] as const)
    .filter(field => current[field] !== proposed[field])
    .map(field => ({ field, before: current[field] || null, after: proposed[field] || null }));
}

export default function ExperimentCenter() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [apps, setApps] = useState<PortfolioApp[]>([]);
  const [experimentTypes, setExperimentTypes] = useState<ExperimentTypeDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const selectedId = searchParams.get('experiment');
  const [selected, setSelected] = useState<Experiment | null>(null);
  const [detailLoading, setDetailLoading] = useState(Boolean(searchParams.get('experiment')));
  const [pendingAction, setPendingAction] = useState<ExperimentSemanticAction | null>(null);
  const [confirmingAction, setConfirmingAction] = useState<ExperimentSemanticAction | null>(null);
  const [reason, setReason] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const [newExperimentOpen, setNewExperimentOpen] = useState(false);
  const [newExperimentApp, setNewExperimentApp] = useState('');
  const [newExperimentType, setNewExperimentType] = useState('aso_metadata');
  const [newExperimentHypothesis, setNewExperimentHypothesis] = useState('');
  const [newExperimentMetric, setNewExperimentMetric] = useState('store_view_to_install_rate');
  const [newExperimentMinDays, setNewExperimentMinDays] = useState(7);
  const [newExperimentMaxDays, setNewExperimentMaxDays] = useState(28);
  const [newExperimentNotes, setNewExperimentNotes] = useState('');
  const [newExperimentSubmitting, setNewExperimentSubmitting] = useState(false);
  const [recommendationOpen, setRecommendationOpen] = useState(false);
  const [recommendationApp, setRecommendationApp] = useState('');
  const [recommendationFocus, setRecommendationFocus] = useState<ExperimentRecommendationFocus>('auto');
  const [recommendationRefreshLive, setRecommendationRefreshLive] = useState(false);
  const [recommendationResult, setRecommendationResult] = useState<ExperimentRecommendationResponse | null>(null);
  const [recommendationLoading, setRecommendationLoading] = useState(false);
  const [recommendationCreatingId, setRecommendationCreatingId] = useState<string | null>(null);
  const activeRef = useRef(true);
  const detailGeneration = useRef(0);
  const detailRequest = useRef<AbortController | null>(null);
  const selectExperiment = (id: string | null) => {
    ++detailGeneration.current;
    detailRequest.current?.abort();
    setSelected(null);
    setDetailLoading(Boolean(id));
    setConfirmingAction(null);
    setNotice(null);
    const next = new URLSearchParams(searchParams);
    if (id) next.set('experiment', id);
    else next.delete('experiment');
    setSearchParams(next, { replace: true });
  };
  const closeDetail = () => selectExperiment(null);
  const detailDialogRef = useAccessibleDialog(Boolean(selectedId), closeDetail);
  const detailTitleId = useId();
  const detailDescriptionId = useId();
  const closeNewExperiment = () => setNewExperimentOpen(false);
  const newExperimentDialogRef = useAccessibleDialog(newExperimentOpen, closeNewExperiment);
  const newExperimentTitleId = useId();
  const newExperimentDescriptionId = useId();
  const closeRecommendation = () => setRecommendationOpen(false);
  const recommendationDialogRef = useAccessibleDialog(recommendationOpen, closeRecommendation);
  const recommendationTitleId = useId();
  const recommendationDescriptionId = useId();
  const selectedExperimentType = experimentTypes.find(type => type.id === newExperimentType) || null;

  const openNewExperiment = () => {
    const initialType = experimentTypes.find(type => type.id === 'aso_metadata') || experimentTypes[0];
    if (initialType) {
      setNewExperimentType(initialType.id);
      setNewExperimentMetric(initialType.default_metric);
    }
    setNewExperimentHypothesis('');
    setNewExperimentMinDays(7);
    setNewExperimentMaxDays(28);
    setNewExperimentNotes('');
    setNewExperimentOpen(true);
  };

  const continueNewExperiment = () => {
    if (!selectedExperimentType || !newExperimentApp || newExperimentSubmitting) return;
    if (selectedExperimentType.capability === 'executable' && selectedExperimentType.builder === 'aso') {
      closeNewExperiment();
      navigate(`/app/${encodeURIComponent(newExperimentApp)}/aso`);
      return;
    }
    if (!newExperimentHypothesis.trim() || !newExperimentMetric.trim()) return;
    setNewExperimentSubmitting(true);
    setError(null);
    api.createPlannedExperiment({
      app_package: newExperimentApp,
      experiment_type: selectedExperimentType.id,
      hypothesis: newExperimentHypothesis.trim(),
      success_metric: newExperimentMetric.trim(),
      min_observation_days: newExperimentMinDays,
      max_observation_days: newExperimentMaxDays,
      notes: newExperimentNotes.trim() || undefined,
    })
      .then(response => {
        setExperiments(current => [response.experiment, ...current.filter(item => item.id !== response.experiment.id)]);
        closeNewExperiment();
        selectExperiment(response.experiment.id);
      })
      .catch(err => setError(getErrorMessage(err, 'Failed to create planning experiment')))
      .finally(() => setNewExperimentSubmitting(false));
  };

  const openRecommendations = () => {
    setRecommendationApp(current => current || apps[0]?.package_name || '');
    setRecommendationFocus('auto');
    setRecommendationRefreshLive(false);
    setRecommendationResult(null);
    setRecommendationOpen(true);
  };

  const generateRecommendations = () => {
    if (!recommendationApp || recommendationLoading) return;
    setRecommendationLoading(true);
    setError(null);
    api.recommendExperimentDesigns(recommendationApp, {
      focus: recommendationFocus,
      max_results: 5,
      refresh_live: recommendationRefreshLive,
    })
      .then(setRecommendationResult)
      .catch(err => setError(getErrorMessage(err, 'Failed to recommend experiments from MCP data')))
      .finally(() => setRecommendationLoading(false));
  };

  const createRecommendedExperiment = (recommendation: ExperimentDesignRecommendation) => {
    if (recommendation.conflicts_with_active_experiment || recommendationCreatingId) return;
    if (recommendation.capability === 'executable' && recommendation.experiment_type === 'aso_metadata') {
      closeRecommendation();
      navigate(`/app/${encodeURIComponent(recommendation.app_package)}/aso`);
      return;
    }
    setRecommendationCreatingId(recommendation.id);
    setError(null);
    api.createPlannedExperiment({
      app_package: recommendation.app_package,
      experiment_type: recommendation.experiment_type,
      hypothesis: recommendation.hypothesis,
      success_metric: recommendation.success_metric,
      min_observation_days: recommendation.suggested_min_observation_days,
      max_observation_days: recommendation.suggested_max_observation_days,
      notes: recommendation.rationale,
      recommendation,
    })
      .then(response => {
        setExperiments(current => [response.experiment, ...current.filter(item => item.id !== response.experiment.id)]);
        closeRecommendation();
        selectExperiment(response.experiment.id);
      })
      .catch(err => setError(getErrorMessage(err, 'Failed to create the recommended experiment')))
      .finally(() => setRecommendationCreatingId(null));
  };

  const loadExperiments = (showLoading = false) => {
    if (showLoading) setLoading(true);
    api.getExperiments()
      .then(result => {
        if (!activeRef.current) return;
        setExperiments(result.experiments || []);
        setError(null);
      })
      .catch(err => {
        if (activeRef.current) setError(getErrorMessage(err, 'Failed to load experiments'));
      })
      .finally(() => {
        if (activeRef.current) setLoading(false);
      });
  };

  useEffect(() => {
    activeRef.current = true;
    api.getPortfolio()
      .then(result => {
        if (!activeRef.current) return;
        const availableApps = result.apps || [];
        setApps(availableApps);
        setNewExperimentApp(current => current || availableApps[0]?.package_name || '');
        setRecommendationApp(current => current || availableApps[0]?.package_name || '');
      })
      .catch(() => {
        if (activeRef.current) setApps([]);
      });
    api.getExperimentTypes()
      .then(result => {
        if (!activeRef.current) return;
        const types = result.experiment_types || [];
        setExperimentTypes(types);
        const initialType = types.find(type => type.id === 'aso_metadata') || types[0];
        if (initialType) {
          setNewExperimentType(initialType.id);
          setNewExperimentMetric(initialType.default_metric);
        }
      })
      .catch(() => {
        if (activeRef.current) setExperimentTypes([]);
      });
    api.getExperiments()
      .then(result => {
        if (!activeRef.current) return;
        setExperiments(result.experiments || []);
        setError(null);
      })
      .catch(err => {
        if (activeRef.current) setError(getErrorMessage(err, 'Failed to load experiments'));
      })
      .finally(() => {
        if (activeRef.current) setLoading(false);
      });
    const poll = () => {
      if (document.visibilityState === 'visible') loadExperiments();
    };
    const interval = window.setInterval(poll, 60_000);
    document.addEventListener('visibilitychange', poll);
    return () => {
      activeRef.current = false;
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', poll);
    };
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    ++detailGeneration.current;
    const refreshDetail = () => {
      const requestGeneration = ++detailGeneration.current;
      detailRequest.current?.abort();
      const controller = new AbortController();
      detailRequest.current = controller;
      api.getExperiment(selectedId, controller.signal)
        .then(result => {
          if (!controller.signal.aborted && detailGeneration.current === requestGeneration) {
            setSelected(result);
            setError(null);
          }
        })
        .catch(err => {
          if (!controller.signal.aborted && detailGeneration.current === requestGeneration) setError(getErrorMessage(err, 'Failed to load experiment detail'));
        })
        .finally(() => {
          if (!controller.signal.aborted && detailGeneration.current === requestGeneration) setDetailLoading(false);
        });
    };
    const poll = () => {
      if (document.visibilityState === 'visible') refreshDetail();
    };
    refreshDetail();
    const interval = window.setInterval(poll, 20_000);
    document.addEventListener('visibilitychange', poll);
    return () => {
      detailRequest.current?.abort();
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', poll);
    };
  }, [selectedId]);

  const runAction = () => {
    const action = confirmingAction;
    if (!selected || pendingAction) return;
    if (!action) return;
    const attributed = ['approve', 'reject', 'retain', 'rollback'].includes(action);
    if (attributed && !reason.trim()) return;
    setPendingAction(action);
    setError(null);
    setNotice(null);
    const experimentId = selected.id;
    ++detailGeneration.current;
    detailRequest.current?.abort();
    api.runExperimentAction(
      experimentId,
      action,
      attributed ? { reason: reason.trim() } : undefined,
    )
      .then(async response => {
        const experiment = response.evaluation
          ? { ...response.experiment, evaluation: response.evaluation }
          : response.experiment;
        setSelected(experiment);
        setExperiments(current => current.map(item => item.id === experiment.id ? experiment : item));
        setConfirmingAction(null);
        setReason('');
        const requestGeneration = ++detailGeneration.current;
        const controller = new AbortController();
        detailRequest.current = controller;
        const [listResult, detailResult] = await Promise.allSettled([
          api.getExperiments(),
          api.getExperiment(experimentId, controller.signal),
        ]);
        if (listResult.status === 'fulfilled') setExperiments(listResult.value.experiments || []);
        if (detailResult.status === 'fulfilled' && !controller.signal.aborted && detailGeneration.current === requestGeneration) {
          setSelected(detailResult.value);
        }
        if (listResult.status === 'rejected' || detailResult.status === 'rejected') {
          setNotice(`${response.message}. A follow-up refresh was unavailable; the action response is shown.`);
        }
      })
      .catch(err => setError(getErrorMessage(err, `Failed to ${action} experiment`)))
      .finally(() => setPendingAction(null));
  };

  const consequences: Record<ExperimentSemanticAction, string> = {
    approve: 'The server attributes approval to the authenticated actor. Manual mode still requires a separate execute command.',
    reject: 'Rejection is terminal for this proposal and remains in the audit history.',
    execute: 'This writes the approved listing after recapturing rollback state and revalidating policy.',
    evaluate: 'This evaluates only recorded source-backed observations; it does not collect browser-supplied data.',
    retain: 'This concludes the experiment and keeps the treatment listing live.',
    rollback: 'This restores the persisted pre-execution listing and verifies the restored fields.',
  };

  if (loading && experiments.length === 0) {
    return <div className="p-8 flex justify-center items-center h-full"><div className="animate-spin w-8 h-8 border-2 border-accent-primary border-t-transparent rounded-full" /></div>;
  }

  const terminal = experiments.filter(experiment => ['retained', 'concluded', 'rolled_back', 'rejected', 'failed'].includes(experiment.status));
  const decided = terminal.filter(experiment => experiment.result_verdict);
  const winners = decided.filter(experiment => ['winner', 'win', 'retained'].includes(experiment.result_verdict?.toLowerCase() || ''));
  const winRate = decided.length > 0 ? Math.round((winners.length / decided.length) * 100) : null;
  const lifts = terminal.flatMap(experiment => {
    if (experiment.baseline_value == null || experiment.result_value == null || experiment.baseline_value === 0) return [];
    return [((experiment.result_value - experiment.baseline_value) / experiment.baseline_value) * 100];
  });
  const averageLift = lifts.length > 0 ? lifts.reduce((sum, value) => sum + value, 0) / lifts.length : null;

  const columns = [
    { id: 'proposed', title: 'Proposed', records: experiments.filter(experiment => experiment.status === 'proposed') },
    { id: 'approved', title: 'Approved', records: experiments.filter(experiment => experiment.status === 'approved') },
    { id: 'in_flight', title: 'In flight', records: experiments.filter(experiment => ['active', 'executing', 'observing', 'measuring'].includes(experiment.status)) },
    { id: 'evaluated', title: 'Evaluated', records: experiments.filter(experiment => ['evaluated', 'concluded', 'retained'].includes(experiment.status)) },
    { id: 'exceptions', title: 'Rejected / failed', records: experiments.filter(experiment => ['rejected', 'failed', 'rolled_back'].includes(experiment.status)) },
  ];

  return (
    <div className="p-5 md:p-8 max-w-[1700px] mx-auto min-h-screen relative overflow-hidden">
      <div className="absolute top-[-10%] right-[-10%] w-[35%] h-[35%] bg-accent-primary/5 rounded-full blur-[100px] pointer-events-none" />
      <header className="mb-6 flex flex-col md:flex-row md:items-end justify-between gap-4 relative z-10">
        <div>
          <div className="text-[10px] font-mono text-accent-secondary uppercase tracking-[0.2em] mb-2">Proposal to retained outcome</div>
          <h1 className="text-3xl font-heading font-bold mb-2">Experiment Center</h1>
          <p className="text-text-secondary text-sm">Evidence, validation, decisions, and reversible execution in one audit surface.</p>
        </div>
        <div className="flex items-center gap-2 self-start md:self-auto">
          <button
            onClick={openRecommendations}
            className="flex items-center gap-2 rounded-lg border border-accent-secondary/30 bg-accent-secondary/10 px-4 py-2.5 text-xs font-semibold text-accent-secondary transition-colors hover:bg-accent-secondary/15"
          >
            <Sparkles className="w-4 h-4" /> Recommend from data
          </button>
          <button
            onClick={openNewExperiment}
            className="flex items-center gap-2 rounded-lg bg-accent-primary px-4 py-2.5 text-xs font-semibold text-white shadow-[0_0_18px_rgba(139,92,246,0.22)] transition-colors hover:bg-accent-primary/90"
          >
            <Plus className="w-4 h-4" /> New experiment
          </button>
          <button onClick={() => loadExperiments(true)} className="p-2.5 bg-surface hover:bg-white/5 border border-border-subtle rounded-lg" title="Refresh experiments"><RefreshCw className="w-4 h-4" /></button>
        </div>
      </header>

      {error && <div className="relative z-10 mb-5 bg-danger/10 border border-danger/20 text-danger text-sm p-4 rounded-xl flex gap-3"><AlertTriangle className="w-5 h-5 shrink-0" />{error}</div>}
      {notice && <div className="relative z-10 mb-5 bg-warning/10 border border-warning/20 text-warning text-sm p-4 rounded-xl">{notice}</div>}

      <section className="relative z-10 grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        <div className="glass-card p-4"><div className="text-[10px] text-text-muted uppercase font-mono">Total proposals</div><div className="text-2xl font-mono font-bold mt-1">{experiments.length}</div></div>
        <div className="glass-card p-4"><div className="text-[10px] text-text-muted uppercase font-mono">In flight</div><div className="text-2xl font-mono font-bold mt-1 text-info">{columns[2].records.length}</div></div>
        <div className="glass-card p-4"><div className="text-[10px] text-text-muted uppercase font-mono">Decided win rate</div><div className="text-2xl font-mono font-bold mt-1">{winRate == null ? 'Unavailable' : `${winRate}%`}</div></div>
        <div className="glass-card p-4"><div className="text-[10px] text-text-muted uppercase font-mono">Measured avg lift</div><div className="text-2xl font-mono font-bold mt-1">{averageLift == null ? 'Unavailable' : `${averageLift >= 0 ? '+' : ''}${averageLift.toFixed(1)}%`}</div></div>
      </section>

      <section className="relative z-10 flex gap-4 overflow-x-auto pb-6">
        {columns.map(column => (
          <div key={column.id} className="flex-none w-[310px] bg-black/15 border border-border-subtle rounded-xl p-3 min-h-[480px]">
            <div className="flex items-center justify-between px-2 py-1 mb-3">
              <h2 className="text-xs uppercase tracking-wider font-heading font-bold text-text-secondary">{column.title}</h2>
              <span className="text-[10px] font-mono bg-surface rounded-full px-2 py-0.5">{column.records.length}</span>
            </div>
            <div className="space-y-3">
              {column.records.map(experiment => {
                const actual = experiment.result_value ?? experiment.current_value;
                const change = actual != null && experiment.baseline_value != null && experiment.baseline_value !== 0
                  ? ((actual - experiment.baseline_value) / experiment.baseline_value) * 100
                  : null;
                const failed = ['failed', 'rejected', 'rolled_back'].includes(experiment.status);
                return (
                  <button key={experiment.id} onClick={() => selectExperiment(experiment.id)} className={`w-full text-left glass-card p-4 border transition-all hover:border-accent-primary/50 ${selectedId === experiment.id ? 'border-accent-primary bg-accent-primary/5' : 'border-border-subtle'} ${failed ? 'border-danger/20' : ''}`}>
                    <div className="flex items-start justify-between gap-2 mb-3">
                      <span className="text-[9px] font-mono uppercase tracking-wider bg-white/5 border border-border-subtle rounded px-2 py-0.5">{experiment.experiment_type.replaceAll('_', ' ')}</span>
                      <span className={`text-[9px] font-mono uppercase ${failed ? 'text-danger' : 'text-accent-secondary'}`}>{experiment.status.replaceAll('_', ' ')}</span>
                    </div>
                    <div className="text-[10px] font-mono text-text-muted truncate mb-1">{experiment.app_package}</div>
                    <div className="text-xs leading-relaxed text-text-primary line-clamp-3">{experiment.hypothesis}</div>
                    <div className="mt-4 pt-3 border-t border-border-subtle flex items-center justify-between text-[10px] font-mono">
                      <span className="text-text-muted">{experiment.autonomy_mode || 'Mode unavailable'}</span>
                      {change == null ? <span className="text-text-muted">Lift unavailable</span> : <span className={change >= 0 ? 'text-success' : 'text-danger'}>{change >= 0 ? '+' : ''}{change.toFixed(1)}%</span>}
                    </div>
                    {experiment.failure_reason && <div className="mt-2 text-[10px] text-danger line-clamp-2">{experiment.failure_reason}</div>}
                  </button>
                );
              })}
              {column.records.length === 0 && <div className="border border-dashed border-border-subtle rounded-xl p-8 text-center text-xs text-text-muted">No records</div>}
            </div>
          </div>
        ))}
      </section>

      {selectedId && (selected || detailLoading) && (
        <div className="fixed inset-0 z-[90] bg-black/45 backdrop-blur-sm" onMouseDown={event => { if (event.currentTarget === event.target) selectExperiment(null); }}>
          <aside ref={detailDialogRef} role="dialog" aria-modal="true" aria-labelledby={detailTitleId} aria-describedby={detailDescriptionId} tabIndex={-1} className="absolute inset-y-0 right-0 flex w-full max-w-[720px] flex-col border-l border-border-subtle bg-background-base shadow-2xl outline-none">
            {(detailLoading || selected?.id !== selectedId) ? <div className="flex h-full items-center justify-center"><div className="animate-spin w-8 h-8 border-2 border-accent-primary border-t-transparent rounded-full" /></div> : selected && <>
            <header className="p-5 border-b border-border-subtle flex items-start gap-4">
              <div className="p-2.5 bg-accent-primary/10 text-accent-primary rounded-xl"><FlaskConical className="w-5 h-5" /></div>
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2 mb-1"><span className="text-[10px] font-mono uppercase text-accent-secondary">{selected.status}</span><span className="text-[10px] font-mono text-text-muted">{selected.id}</span></div>
                 <h2 id={detailTitleId} className="font-heading font-bold text-lg leading-snug">{selected.hypothesis}</h2>
                 <div id={detailDescriptionId} className="text-xs text-text-secondary mt-1">{selected.app_package} - {selected.experiment_type.replaceAll('_', ' ')}</div>
               </div>
                <button data-dialog-initial-focus onClick={closeDetail} className="p-1.5 text-text-muted hover:text-white" aria-label="Close experiment detail"><X className="w-5 h-5" /></button>
            </header>

            <div className="flex-1 overflow-y-auto p-5 space-y-6 pb-28">
              <LifecycleProgress status={selected.status} />

              <section className="grid grid-cols-2 md:grid-cols-4 gap-2">
                <div className="bg-surface border border-border-subtle rounded-lg p-3"><div className="text-[9px] uppercase font-mono text-text-muted">Metric</div><div className="text-xs mt-1 truncate" title={selected.success_metric}>{selected.success_metric}</div></div>
                <div className="bg-surface border border-border-subtle rounded-lg p-3"><div className="text-[9px] uppercase font-mono text-text-muted">Baseline</div><div className="text-xs font-mono mt-1">{formatValue(selected.baseline_value)}</div></div>
                <div className="bg-surface border border-border-subtle rounded-lg p-3"><div className="text-[9px] uppercase font-mono text-text-muted">Current</div><div className="text-xs font-mono mt-1">{formatValue(selected.current_value ?? selected.result_value)}</div></div>
                <div className="bg-surface border border-border-subtle rounded-lg p-3"><div className="text-[9px] uppercase font-mono text-text-muted">Confidence</div><div className="text-xs font-mono mt-1">{selected.confidence == null ? 'Unavailable' : `${(selected.confidence * 100).toFixed(1)}%`}</div></div>
              </section>

              <section>
                <div className="flex items-center justify-between mb-3"><h3 className="text-xs uppercase tracking-wider font-bold flex items-center gap-2"><ArrowRight className="w-4 h-4 text-accent-primary" /> Before / after diff</h3><span className="text-[10px] font-mono text-text-muted">Listing {selected.proposal?.listing_version || 'version unavailable'}</span></div>
                {proposalChanges(selected).length > 0 ? (
                  <div className="space-y-3">
                    {proposalChanges(selected).map(change => (
                        <div key={change.field} className="overflow-hidden rounded-xl border border-border-subtle bg-black/20">
                          <div className="flex items-center justify-between border-b border-border-subtle bg-white/3 px-3 py-2 font-mono text-[10px]"><span className="text-text-secondary">{change.field.replaceAll('_', ' ')}</span><span className="text-text-muted">modified</span></div>
                          <div className="grid grid-cols-1 text-xs md:grid-cols-2 md:divide-x md:divide-border-subtle">
                            <div className="border-b border-border-subtle bg-danger/5 md:border-b-0"><div className="border-b border-danger/10 px-3 py-1.5 text-[9px] uppercase text-danger font-mono">Before</div><div className="grid grid-cols-[28px_1fr] font-mono"><span className="select-none border-r border-danger/10 bg-danger/8 px-2 py-3 text-danger">-</span><div className="whitespace-pre-wrap break-words p-3 text-text-secondary">{change.before || 'Empty'}</div></div></div>
                            <div className="bg-success/5"><div className="border-b border-success/10 px-3 py-1.5 text-[9px] uppercase text-success font-mono">After</div><div className="grid grid-cols-[28px_1fr] font-mono"><span className="select-none border-r border-success/10 bg-success/8 px-2 py-3 text-success">+</span><div className="whitespace-pre-wrap break-words p-3 text-text-primary">{change.after || 'Empty'}</div></div></div>
                          </div>
                        </div>
                    ))}
                  </div>
                ) : <div className="border border-dashed border-border-subtle rounded-xl p-5 text-xs text-text-muted">No structured proposal diff was supplied.</div>}
              </section>

              <section>
                <h3 className="text-xs uppercase tracking-wider font-bold flex items-center gap-2 mb-3"><Shield className="w-4 h-4 text-warning" /> Validation</h3>
                {selected.validation ? (
                  <div className={`rounded-xl border p-4 ${selected.validation.valid ? 'border-success/20 bg-success/5' : 'border-danger/20 bg-danger/5'}`}>
                    <div className={`text-xs font-bold flex items-center gap-2 ${selected.validation.valid ? 'text-success' : 'text-danger'}`}>{selected.validation.valid ? <Check className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}{selected.validation.valid ? 'Server validation passed' : 'Server validation failed'}</div>
                    {selected.validation.issues.length > 0 && <div className="mt-3 space-y-2">{selected.validation.issues.map(issue => <div key={`${issue.code}-${issue.message}`} className="text-[10px] font-mono"><span className={issue.severity === 'error' ? 'text-danger' : 'text-warning'}>{issue.severity.toUpperCase()}</span> - {issue.field ? `${issue.field}: ` : ''}{issue.message}</div>)}</div>}
                  </div>
                ) : <div className="border border-dashed border-border-subtle rounded-xl p-5 text-xs text-warning">No server validation record is attached.</div>}
              </section>

              <section>
                <div className="flex flex-col items-start justify-between gap-2 mb-3 sm:flex-row sm:items-center"><h3 className="text-xs uppercase tracking-wider font-bold flex items-center gap-2"><Database className="w-4 h-4 text-info" /> Evidence</h3><ProvenanceBadge provenance={selected.provenance} /></div>
                {(selected.evidence || []).length > 0 ? <div className="grid grid-cols-1 md:grid-cols-2 gap-2">{(selected.evidence || []).map((item, index) => <div key={item.id || `${item.label}-${index}`} className="bg-info/5 border border-info/15 rounded-lg p-3"><div className="flex justify-between gap-3 text-xs"><span className="text-info">{item.label}</span><span className="font-mono">{item.value ?? 'Unavailable'}</span></div><div className="mt-2"><ProvenanceBadge source={item.source} observedAt={item.observed_at} /></div>{item.detail && <div className="text-[10px] text-text-secondary mt-1">{item.detail}</div>}</div>)}</div> : <div className="border border-dashed border-border-subtle rounded-xl p-5 text-xs text-text-muted">No evidence payload is attached.</div>}
              </section>

              {selected.recommendation && <section>
                <h3 className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-wider"><Sparkles className="h-4 w-4 text-accent-secondary" /> Recommended design</h3>
                <div className="space-y-3 rounded-xl border border-accent-secondary/15 bg-accent-secondary/5 p-4">
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <div><div className="text-[9px] font-mono uppercase text-text-muted">Control</div><div className="mt-1 text-xs leading-relaxed">{selected.recommendation.design.control}</div></div>
                    <div><div className="text-[9px] font-mono uppercase text-accent-secondary">Treatment</div><div className="mt-1 text-xs leading-relaxed">{selected.recommendation.design.treatment}</div></div>
                  </div>
                  <div><div className="text-[9px] font-mono uppercase text-text-muted">Analysis plan</div><div className="mt-1 text-xs leading-relaxed text-text-secondary">{selected.recommendation.design.analysis_plan}</div></div>
                  <div className="flex flex-wrap gap-2">{selected.recommendation.design.guardrail_metrics.map(metric => <span key={metric} className="rounded border border-border-subtle bg-black/20 px-2 py-1 text-[9px] font-mono">{metric}</span>)}</div>
                </div>
              </section>}

              <section>
                <div className="flex items-center justify-between mb-3"><h3 className="text-xs uppercase tracking-wider font-bold flex items-center gap-2"><Clock className="w-4 h-4 text-accent-secondary" /> Source-backed observations</h3></div>
                {(selected.observations || []).length > 0 ? <div className="space-y-2">{(selected.observations || []).map((observation, index) => <div key={observation.id || `${observation.observed_at}-${index}`} className="flex items-center gap-3 bg-black/20 border border-border-subtle rounded-lg p-3"><div className="w-2 h-2 rounded-full bg-accent-secondary" /><div className="flex-1"><div className="text-xs font-mono">{formatValue(observation.metric_value)}</div><div className="text-[10px] text-text-muted">{observation.source || 'Source unavailable'} - {observation.observed_at ? new Date(observation.observed_at).toLocaleString() : 'Time unavailable'}</div></div><div className="text-[10px] text-text-muted font-mono">n={observation.visitors ?? observation.sample_size ?? 'unavailable'}</div></div>)}</div> : <div className="border border-dashed border-border-subtle rounded-xl p-5 text-xs text-text-muted">No automatic source-backed observations have been recorded. Browser-entered observations are not supported.</div>}
              </section>

              {selected.failure_reason && <section className="bg-danger/10 border border-danger/20 rounded-xl p-4"><h3 className="text-xs font-bold text-danger mb-2">Failure reason</h3><p className="text-xs text-text-secondary">{selected.failure_reason}</p></section>}
            </div>

            <footer className="absolute bottom-0 inset-x-0 bg-background-base/95 backdrop-blur-xl border-t border-border-subtle p-4">
              {confirmingAction ? <div>
                <div className="mb-3 text-xs text-text-secondary"><span className="font-semibold text-text-primary">{actionLabels[confirmingAction]}:</span> {consequences[confirmingAction]}</div>
                {['approve', 'reject', 'retain', 'rollback'].includes(confirmingAction) && <div className="mb-3 space-y-2"><div className="text-[10px] font-mono text-text-muted">Actor is derived by the server from the authenticated request.</div><input value={reason} onChange={event => setReason(event.target.value)} placeholder="Reason required" className="w-full rounded-lg border border-border-subtle bg-surface px-3 py-2 text-xs outline-none focus:border-accent-primary" /></div>}
                <div className="flex gap-2"><button onClick={() => { setConfirmingAction(null); setReason(''); }} className="flex-1 rounded-lg border border-border-subtle bg-surface py-2.5 text-xs font-semibold">Cancel</button><button onClick={runAction} disabled={pendingAction != null || (['approve', 'reject', 'retain', 'rollback'].includes(confirmingAction) && !reason.trim())} className={`flex-1 rounded-lg py-2.5 text-xs font-semibold disabled:opacity-40 ${confirmingAction === 'reject' || confirmingAction === 'rollback' ? 'bg-danger/15 text-danger border border-danger/20' : 'bg-accent-primary text-white'}`}>{pendingAction ? 'Working...' : `Confirm ${confirmingAction}`}</button></div>
              </div> : <div className="flex flex-wrap gap-2">
                {(selected.available_actions || []).map(action => {
                  const destructive = action === 'reject' || action === 'rollback';
                  const Icon = action === 'rollback' ? RotateCcw : action === 'retain' ? TrendingUp : action === 'evaluate' ? ArrowUpRight : action === 'reject' ? XCircle : action === 'execute' ? ArrowRight : Check;
                  return <button key={action} onClick={() => setConfirmingAction(action)} disabled={pendingAction != null} className={`flex-1 min-w-[150px] rounded-lg py-2.5 px-3 text-xs font-semibold flex items-center justify-center gap-2 disabled:opacity-40 ${destructive ? 'bg-danger/15 text-danger border border-danger/20' : 'bg-accent-primary text-white'}`}><Icon className="w-4 h-4" />{actionLabels[action]}</button>;
                })}
                {(selected.available_actions || []).length === 0 && <div className="w-full text-center text-xs text-text-muted py-2">No server-authorized actions are currently available for this state.</div>}
              </div>}
            </footer>
            </>}
          </aside>
        </div>
      )}

      {recommendationOpen && (
        <div
          className="fixed inset-0 z-[105] flex items-center justify-center bg-black/65 p-4 backdrop-blur-sm"
          onMouseDown={event => { if (event.currentTarget === event.target) closeRecommendation(); }}
        >
          <section
            ref={recommendationDialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={recommendationTitleId}
            aria-describedby={recommendationDescriptionId}
            tabIndex={-1}
            className="glass-card max-h-[92vh] w-full max-w-[960px] overflow-y-auto border border-accent-secondary/20 bg-background-base/95 p-6 shadow-2xl outline-none"
          >
            <header className="flex items-start gap-4">
              <div className="rounded-xl bg-accent-secondary/10 p-3 text-accent-secondary"><Sparkles className="h-5 w-5" /></div>
              <div className="flex-1">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 id={recommendationTitleId} className="font-heading text-xl font-bold">Recommend experiment designs</h2>
                    <p id={recommendationDescriptionId} className="mt-1 max-w-2xl text-xs leading-relaxed text-text-secondary">
                      Analyze observed MCP funnel leaks and category benchmarks. Every recommendation includes its source evidence, treatment design, primary metric, guardrails, duration, and current execution capability.
                    </p>
                  </div>
                  <button data-dialog-initial-focus onClick={closeRecommendation} className="p-1.5 text-text-muted hover:text-white" aria-label="Close recommendations"><X className="h-5 w-5" /></button>
                </div>

                <div className="mt-6 grid grid-cols-1 gap-3 md:grid-cols-[1fr_220px_auto] md:items-end">
                  <div>
                    <label htmlFor="recommendation-app" className="block text-[10px] font-mono uppercase tracking-wider text-text-muted">App</label>
                    <select id="recommendation-app" value={recommendationApp} onChange={event => { setRecommendationApp(event.target.value); setRecommendationResult(null); }} disabled={apps.length === 0} className="mt-2 w-full rounded-lg border border-border-subtle bg-surface px-3 py-2.5 text-xs outline-none focus:border-accent-secondary disabled:opacity-50">
                      {apps.length === 0 && <option value="">No configured apps available</option>}
                      {apps.map(app => <option key={app.package_name} value={app.package_name}>{app.display_name} ({app.package_name})</option>)}
                    </select>
                  </div>
                  <div>
                    <label htmlFor="recommendation-focus" className="block text-[10px] font-mono uppercase tracking-wider text-text-muted">Focus</label>
                    <select id="recommendation-focus" value={recommendationFocus} onChange={event => { setRecommendationFocus(event.target.value as ExperimentRecommendationFocus); setRecommendationResult(null); }} className="mt-2 w-full rounded-lg border border-border-subtle bg-surface px-3 py-2.5 text-xs outline-none focus:border-accent-secondary">
                      <option value="auto">Highest impact</option>
                      <option value="acquisition">Acquisition</option>
                      <option value="activation">Activation</option>
                      <option value="monetization">Monetization</option>
                      <option value="retention">Retention</option>
                    </select>
                  </div>
                  <button onClick={generateRecommendations} disabled={!recommendationApp || recommendationLoading} className="flex items-center justify-center gap-2 rounded-lg bg-accent-secondary px-4 py-2.5 text-xs font-semibold text-background-base disabled:opacity-40">
                    {recommendationLoading ? <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" /> : <Sparkles className="h-4 w-4" />}
                    {recommendationLoading ? 'Analyzing...' : 'Analyze MCP data'}
                  </button>
                </div>
                <label className="mt-3 flex items-center gap-2 text-[10px] text-text-muted">
                  <input type="checkbox" checked={recommendationRefreshLive} onChange={event => setRecommendationRefreshLive(event.target.checked)} className="accent-cyan-500" />
                  Refresh connected MCP sources instead of using the latest persisted MCP snapshot
                </label>
              </div>
            </header>

            {recommendationResult && (
              <div className="mt-6 border-t border-border-subtle pt-5">
                <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <div className="text-xs font-semibold">{recommendationResult.recommendations.length} design recommendation(s)</div>
                    <div className="mt-1 text-[10px] font-mono text-text-muted">{recommendationResult.snapshot_source.replaceAll('_', ' ')} · {recommendationResult.data_sources.join(', ') || 'No sources reported'} · {new Date(recommendationResult.generated_at).toLocaleString()}</div>
                  </div>
                  <span className={`rounded border px-2 py-1 text-[9px] font-mono uppercase ${recommendationResult.source_status === 'fresh' ? 'border-success/20 bg-success/10 text-success' : 'border-warning/20 bg-warning/10 text-warning'}`}>{recommendationResult.source_status} evidence</span>
                </div>

                {recommendationResult.recommendations.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-border-subtle p-8 text-center text-xs text-text-muted">{recommendationResult.message || 'No observed below-benchmark leak matched this focus.'}</div>
                ) : (
                  <div className="space-y-4">
                    {recommendationResult.recommendations.map(recommendation => (
                      <article key={recommendation.id} className="rounded-xl border border-border-subtle bg-black/20 p-5">
                        <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent-secondary/15 text-[10px] font-mono text-accent-secondary">{recommendation.rank}</span>
                              <span className="text-sm font-semibold">{recommendation.label}</span>
                              <span className="rounded bg-white/5 px-2 py-0.5 text-[9px] font-mono uppercase text-text-secondary">{recommendation.focus}</span>
                              <span className={`rounded px-2 py-0.5 text-[9px] font-mono uppercase ${recommendation.capability === 'executable' ? 'bg-success/10 text-success' : 'bg-warning/10 text-warning'}`}>{recommendation.capability === 'executable' ? 'Validated builder' : 'Planning only'}</span>
                              {recommendation.conflicts_with_active_experiment && <span className="rounded bg-danger/10 px-2 py-0.5 text-[9px] font-mono uppercase text-danger">Active conflict</span>}
                            </div>
                            <h3 className="mt-3 text-sm leading-relaxed text-text-primary">{recommendation.hypothesis}</h3>
                            <p className="mt-2 text-[11px] leading-relaxed text-text-secondary">{recommendation.rationale}</p>
                          </div>
                          <div className="grid min-w-[230px] grid-cols-2 gap-2 text-center font-mono text-[10px]">
                            <div className="rounded-lg border border-border-subtle bg-surface p-2"><div className="text-text-muted">Actual</div><div className="mt-1 text-sm">{(recommendation.evidence.actual_rate * 100).toFixed(1)}%</div></div>
                            <div className="rounded-lg border border-border-subtle bg-surface p-2"><div className="text-text-muted">Benchmark</div><div className="mt-1 text-sm">{(recommendation.evidence.benchmark_rate * 100).toFixed(1)}%</div></div>
                            <div className="col-span-2 rounded-lg border border-accent-primary/15 bg-accent-primary/5 p-2"><div className="text-text-muted">Estimated monthly impact</div><div className="mt-1 text-sm text-accent-primary">${recommendation.estimated_monthly_impact.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div></div>
                          </div>
                        </div>

                        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
                          <div className="rounded-lg border border-border-subtle bg-surface/60 p-3"><div className="text-[9px] font-mono uppercase text-text-muted">Control</div><div className="mt-1 text-[11px] leading-relaxed">{recommendation.design.control}</div></div>
                          <div className="rounded-lg border border-success/15 bg-success/5 p-3"><div className="text-[9px] font-mono uppercase text-success">Treatment</div><div className="mt-1 text-[11px] leading-relaxed">{recommendation.design.treatment}</div></div>
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2">
                          <span className="rounded border border-info/15 bg-info/5 px-2 py-1 text-[9px] font-mono text-info">Primary: {recommendation.success_metric}</span>
                          {recommendation.design.guardrail_metrics.map(metric => <span key={metric} className="rounded border border-border-subtle bg-white/3 px-2 py-1 text-[9px] font-mono text-text-secondary">Guardrail: {metric}</span>)}
                        </div>
                        <div className="mt-4 flex flex-col items-start justify-between gap-3 border-t border-border-subtle pt-4 sm:flex-row sm:items-center">
                          <div className="text-[10px] text-text-muted"><span className="font-mono">{recommendation.suggested_min_observation_days}-{recommendation.suggested_max_observation_days} days</span> · {recommendation.design.method.replaceAll('_', ' ')} · {recommendation.evidence.freshness} MCP evidence</div>
                          <button onClick={() => createRecommendedExperiment(recommendation)} disabled={recommendation.conflicts_with_active_experiment || recommendationCreatingId != null} className="flex items-center gap-2 rounded-lg bg-accent-primary px-4 py-2 text-xs font-semibold text-white disabled:opacity-40">
                            {recommendationCreatingId === recommendation.id ? 'Creating...' : recommendation.capability === 'executable' ? 'Open validated builder' : 'Create this experiment'} <ArrowRight className="h-4 w-4" />
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      )}

      {newExperimentOpen && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
          onMouseDown={event => { if (event.currentTarget === event.target) closeNewExperiment(); }}
        >
          <section
            ref={newExperimentDialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={newExperimentTitleId}
            aria-describedby={newExperimentDescriptionId}
            tabIndex={-1}
            className="glass-card max-h-[90vh] w-full max-w-[820px] overflow-y-auto border border-border-subtle bg-background-base/95 p-6 shadow-2xl outline-none"
          >
            <div className="flex items-start gap-4">
              <div className="rounded-xl bg-accent-primary/10 p-3 text-accent-primary"><FlaskConical className="h-5 w-5" /></div>
              <div className="flex-1">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 id={newExperimentTitleId} className="font-heading text-xl font-bold">Create an experiment</h2>
                    <p id={newExperimentDescriptionId} className="mt-1 text-xs leading-relaxed text-text-secondary">
                      Choose any experiment type to maintain its hypothesis and measurement plan. Types without a validated executor are created in recommendation-only mode and cannot mutate production.
                    </p>
                  </div>
                  <button data-dialog-initial-focus onClick={closeNewExperiment} className="p-1.5 text-text-muted hover:text-white" aria-label="Close new experiment dialog"><X className="h-5 w-5" /></button>
                </div>

                <div className="mt-6">
                  <div className="mb-2 text-[10px] font-mono uppercase tracking-wider text-text-muted">Experiment type</div>
                  {experimentTypes.length > 0 ? (
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      {experimentTypes.map(type => (
                        <button
                          key={type.id}
                          onClick={() => {
                            setNewExperimentType(type.id);
                            setNewExperimentMetric(type.default_metric);
                          }}
                          className={`rounded-xl border p-3 text-left transition-colors ${newExperimentType === type.id ? 'border-accent-primary bg-accent-primary/10' : 'border-border-subtle bg-black/20 hover:bg-white/5'}`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-xs font-semibold">{type.label}</span>
                            <span className={`rounded px-1.5 py-0.5 text-[8px] font-mono uppercase ${type.capability === 'executable' ? 'bg-success/10 text-success' : 'bg-warning/10 text-warning'}`}>
                              {type.capability === 'executable' ? 'Executable' : 'Planning only'}
                            </span>
                          </div>
                          <div className="mt-1 text-[10px] leading-relaxed text-text-secondary">{type.description}</div>
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div className="rounded-xl border border-dashed border-border-subtle p-4 text-xs text-warning">Experiment catalog is unavailable.</div>
                  )}
                </div>

                <label htmlFor="new-experiment-app" className="mt-5 block text-[10px] font-mono uppercase tracking-wider text-text-muted">App</label>
                <select
                  id="new-experiment-app"
                  value={newExperimentApp}
                  onChange={event => setNewExperimentApp(event.target.value)}
                  disabled={apps.length === 0}
                  className="mt-2 w-full rounded-lg border border-border-subtle bg-surface px-3 py-2.5 text-xs text-text-primary outline-none focus:border-accent-primary disabled:opacity-50"
                >
                  {apps.length === 0 && <option value="">No configured apps available</option>}
                  {apps.map(app => <option key={app.package_name} value={app.package_name}>{app.display_name} ({app.package_name})</option>)}
                </select>

                {selectedExperimentType?.capability === 'planning_only' && (
                  <div className="mt-5 space-y-4 rounded-xl border border-warning/20 bg-warning/5 p-4">
                    <div className="flex items-start gap-2 text-[11px] text-warning">
                      <Shield className="mt-0.5 h-4 w-4 shrink-0" />
                      This type can be planned and reviewed, but execution stays disabled until its provider validation and rollback adapter are implemented.
                    </div>
                    <div>
                      <label htmlFor="new-experiment-hypothesis" className="block text-[10px] font-mono uppercase tracking-wider text-text-muted">Hypothesis</label>
                      <textarea
                        id="new-experiment-hypothesis"
                        rows={3}
                        value={newExperimentHypothesis}
                        onChange={event => setNewExperimentHypothesis(event.target.value)}
                        placeholder="Describe the expected behavior and why it should improve the metric."
                        className="mt-2 w-full rounded-lg border border-border-subtle bg-surface p-3 text-xs outline-none focus:border-accent-primary"
                      />
                    </div>
                    <div>
                      <label htmlFor="new-experiment-metric" className="block text-[10px] font-mono uppercase tracking-wider text-text-muted">Success metric</label>
                      <input
                        id="new-experiment-metric"
                        value={newExperimentMetric}
                        onChange={event => setNewExperimentMetric(event.target.value)}
                        className="mt-2 w-full rounded-lg border border-border-subtle bg-surface px-3 py-2.5 text-xs font-mono outline-none focus:border-accent-primary"
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label htmlFor="new-experiment-min-days" className="block text-[10px] font-mono uppercase tracking-wider text-text-muted">Minimum days</label>
                        <input id="new-experiment-min-days" type="number" min={1} max={90} value={newExperimentMinDays} onChange={event => setNewExperimentMinDays(Number(event.target.value))} className="mt-2 w-full rounded-lg border border-border-subtle bg-surface px-3 py-2.5 text-xs font-mono outline-none focus:border-accent-primary" />
                      </div>
                      <div>
                        <label htmlFor="new-experiment-max-days" className="block text-[10px] font-mono uppercase tracking-wider text-text-muted">Maximum days</label>
                        <input id="new-experiment-max-days" type="number" min={newExperimentMinDays} max={180} value={newExperimentMaxDays} onChange={event => setNewExperimentMaxDays(Number(event.target.value))} className="mt-2 w-full rounded-lg border border-border-subtle bg-surface px-3 py-2.5 text-xs font-mono outline-none focus:border-accent-primary" />
                      </div>
                    </div>
                    <div>
                      <label htmlFor="new-experiment-notes" className="block text-[10px] font-mono uppercase tracking-wider text-text-muted">Notes</label>
                      <textarea id="new-experiment-notes" rows={2} value={newExperimentNotes} onChange={event => setNewExperimentNotes(event.target.value)} placeholder="Dependencies, owner, implementation link, or rollout notes." className="mt-2 w-full rounded-lg border border-border-subtle bg-surface p-3 text-xs outline-none focus:border-accent-primary" />
                    </div>
                  </div>
                )}

                <div className="mt-6 flex gap-3">
                  <button onClick={closeNewExperiment} className="flex-1 rounded-lg border border-border-subtle bg-surface py-2.5 text-xs font-semibold">Cancel</button>
                  {apps.length === 0 ? (
                    <button onClick={() => navigate('/settings')} className="flex-1 rounded-lg bg-accent-primary py-2.5 text-xs font-semibold text-white">Configure an app</button>
                  ) : (
                    <button
                      onClick={continueNewExperiment}
                      disabled={
                        !newExperimentApp
                        || !selectedExperimentType
                        || newExperimentSubmitting
                        || (selectedExperimentType.capability === 'planning_only' && (!newExperimentHypothesis.trim() || !newExperimentMetric.trim() || newExperimentMaxDays < newExperimentMinDays))
                      }
                      className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-accent-primary py-2.5 text-xs font-semibold text-white disabled:opacity-40"
                    >
                      {newExperimentSubmitting
                        ? 'Creating...'
                        : selectedExperimentType?.capability === 'executable'
                          ? <>Open proposal builder <ArrowRight className="h-4 w-4" /></>
                          : <>Create planning experiment <Plus className="h-4 w-4" /></>}
                    </button>
                  )}
                </div>
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
