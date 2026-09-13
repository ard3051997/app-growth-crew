import { useEffect, useId, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowRight,
  Check,
  Database,
  FileText,
  RefreshCw,
  Search,
  Shield,
  TrendingUp,
  X,
} from 'lucide-react';

import {
  api,
  type AppRulebook,
  type AutonomyMode,
  type Keyword,
  type ListingField,
  type ListingSnapshot,
  type StoreListing,
  type ValidationIssue,
} from '../api';
import { getErrorMessage } from '../utils';
import { useAccessibleDialog } from '../components/useAccessibleDialog';

const fields: Array<{ key: ListingField; label: string; rows?: number }> = [
  { key: 'title', label: 'App title' },
  { key: 'short_description', label: 'Short description' },
  { key: 'full_description', label: 'Full description', rows: 8 },
];

const modeCopy: Record<AutonomyMode, { label: string; detail: string }> = {
  recommend_only: {
    label: 'Recommend only',
    detail: 'Create an evidence-backed proposal. Execution is disabled.',
  },
  manual: {
    label: 'Manual approval',
    detail: 'Require an operator approval before any storefront mutation.',
  },
  auto_low_risk: {
    label: 'Auto low-risk',
    detail: 'Permit execution only if the server rulebook classifies the change as low risk.',
  },
};

function provenanceLabel(listing: StoreListing | null) {
  if (!listing) return 'Unavailable';
  const source = listing.provenance?.source || 'Source unavailable';
  const captured = listing.provenance?.captured_at || listing.provenance?.retrieved_at || listing.fetched_at;
  return captured ? `${source} - ${new Date(captured).toLocaleString()}` : source;
}

export default function ASOWorkspace() {
  const { packageId } = useParams<{ packageId: string }>() as { packageId: string };
  const navigate = useNavigate();
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [listing, setListing] = useState<StoreListing | null>(null);
  const [rulebook, setRulebook] = useState<AppRulebook | null>(null);
  const [proposed, setProposed] = useState<ListingSnapshot>({ title: '', short_description: '', full_description: '' });
  const [mode, setMode] = useState<AutonomyMode>('recommend_only');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showConfirmation, setShowConfirmation] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [loadedPackage, setLoadedPackage] = useState<string | null>(null);
  const [errorPackage, setErrorPackage] = useState<string | null>(null);
  const requestGeneration = useRef(0);
  const loadRequest = useRef<AbortController | null>(null);
  const submitRequest = useRef<AbortController | null>(null);
  const closeConfirmation = () => setShowConfirmation(false);
  const confirmationDialogRef = useAccessibleDialog(showConfirmation, closeConfirmation);
  const confirmationTitleId = useId();
  const confirmationDescriptionId = useId();

  const loadData = (targetPackage = packageId) => {
    const generation = ++requestGeneration.current;
    loadRequest.current?.abort();
    submitRequest.current?.abort();
    const controller = new AbortController();
    loadRequest.current = controller;
    setLoading(true);
    setError(null);
    setErrorPackage(null);
    setLoadedPackage(null);
    setKeywords([]);
    setListing(null);
    setRulebook(null);
    setProposed({ title: '', short_description: '', full_description: '' });
    setMode('recommend_only');
    setSubmitting(false);
    setShowConfirmation(false);
    setConfirmed(false);
    Promise.all([
      api.getAppRulebook(targetPackage, controller.signal),
      api.getAppListing(targetPackage, 'en-US', controller.signal),
      api.getAppKeywords(targetPackage, controller.signal),
    ])
      .then(([rulebookResponse, currentListing, rankingResponse]) => {
        if (controller.signal.aborted || requestGeneration.current !== generation || targetPackage !== packageId) return;
        const nextRulebook = rulebookResponse;
        const tracked = new Set(nextRulebook.target_keywords || []);
        setRulebook(nextRulebook);
        setListing(currentListing);
        setKeywords((rankingResponse || []).filter(keyword => tracked.has(keyword.keyword)));
        setProposed({
          title: currentListing.title || '',
          short_description: currentListing.short_description || '',
          full_description: currentListing.full_description || '',
        });
        const allowed = nextRulebook.allowed_autonomy_modes;
        setMode(allowed?.includes('recommend_only') ? 'recommend_only' : allowed?.[0] || 'recommend_only');
        setLoadedPackage(targetPackage);
      })
      .catch(err => {
        if (controller.signal.aborted || requestGeneration.current !== generation || targetPackage !== packageId) return;
        setError(getErrorMessage(err, 'Failed to load the rulebook and current listing provenance'));
        setErrorPackage(targetPackage);
      })
      .finally(() => {
        if (!controller.signal.aborted && requestGeneration.current === generation && targetPackage === packageId) setLoading(false);
      });
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- route changes must immediately invalidate package-bound state
    loadData(packageId);
    return () => {
      loadRequest.current?.abort();
      submitRequest.current?.abort();
    };
    // loadData intentionally starts a fresh generation for this route package.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [packageId]);

  const packageMatches = loadedPackage === packageId;
  const activeRulebook = packageMatches ? rulebook : null;
  const activeListing = packageMatches ? listing : null;
  const current: ListingSnapshot = {
    title: activeListing?.title || '',
    short_description: activeListing?.short_description || '',
    full_description: activeListing?.full_description || '',
  };
  const changedFields = fields.filter(field => current[field.key] !== proposed[field.key]);
  const validationIssues: ValidationIssue[] = [];

  fields.forEach(field => {
    const value = proposed[field.key];
    const constraint = activeRulebook?.constraints?.[field.key];
    if (constraint?.required && !value.trim()) {
      validationIssues.push({ field: field.key, code: 'required', message: `${field.label} is required by the rulebook.`, severity: 'error' });
    }
    if (constraint?.max_length != null && value.length > constraint.max_length) {
      validationIssues.push({ field: field.key, code: 'max_length', message: `${value.length - constraint.max_length} characters over the rulebook limit.`, severity: 'error' });
    }
    if (constraint?.min_length != null && value.length < constraint.min_length) {
      validationIssues.push({ field: field.key, code: 'min_length', message: `${constraint.min_length - value.length} characters below the rulebook minimum.`, severity: 'error' });
    }
    (constraint?.required_terms || []).forEach(term => {
      if (!value.toLowerCase().includes(term.toLowerCase())) {
        validationIssues.push({ field: field.key, code: 'required_term', message: `Missing required term "${term}".`, severity: 'error' });
      }
    });
    (constraint?.prohibited_terms || []).forEach(term => {
      if (value.toLowerCase().includes(term.toLowerCase())) {
        validationIssues.push({ field: field.key, code: 'prohibited_term', message: `Contains prohibited term "${term}".`, severity: 'error' });
      }
    });
  });

  (activeRulebook?.forbidden_terms || []).forEach(term => {
    fields.forEach(field => {
      if (proposed[field.key].toLowerCase().includes(term.toLowerCase())) {
        validationIssues.push({ field: field.key, code: 'forbidden_term', message: `Contains forbidden term "${term}".`, severity: 'error' });
      }
    });
  });

  const hasValidationErrors = validationIssues.some(issue => issue.severity === 'error');
  const allowedModes = activeRulebook?.allowed_autonomy_modes || (['recommend_only'] as AutonomyMode[]);

  const submitProposal = () => {
    const submissionPackage = packageId;
    const generation = requestGeneration.current;
    if (!packageMatches || loadedPackage !== submissionPackage || !activeRulebook || !activeListing || !confirmed || hasValidationErrors || changedFields.length === 0 || !allowedModes.includes(mode)) return;
    submitRequest.current?.abort();
    const controller = new AbortController();
    submitRequest.current = controller;
    setSubmitting(true);
    setError(null);
    setErrorPackage(null);
    api.createStoreConversionProposal(submissionPackage, {
      language: 'en-US',
      country: 'us',
      proposed_listing: proposed,
      execution_mode: mode,
    }, controller.signal)
      .then(response => {
        if (controller.signal.aborted || requestGeneration.current !== generation || packageId !== submissionPackage || loadedPackage !== submissionPackage) return;
        navigate(`/experiments?experiment=${encodeURIComponent(response.experiment.id)}`);
      })
      .catch(err => {
        if (controller.signal.aborted || requestGeneration.current !== generation || packageId !== submissionPackage) return;
        setError(getErrorMessage(err, 'The server could not create this store-conversion proposal'));
        setErrorPackage(submissionPackage);
      })
      .finally(() => {
        if (!controller.signal.aborted && requestGeneration.current === generation && packageId === submissionPackage) setSubmitting(false);
      });
  };

  if (loading || (!packageMatches && errorPackage !== packageId)) {
    return <div className="p-8 flex justify-center items-center h-full"><div className="animate-spin w-8 h-8 border-2 border-accent-primary border-t-transparent rounded-full" /></div>;
  }

  return (
    <div className="p-5 md:p-8 max-w-[1500px] mx-auto min-h-screen relative">
      <div className="absolute top-[-10%] right-[-10%] w-[35%] h-[35%] bg-accent-primary/5 rounded-full blur-[100px] pointer-events-none" />

      <header className="mb-7 flex flex-col md:flex-row md:items-end justify-between gap-4 relative z-10">
        <div>
          <div className="text-[10px] font-mono text-accent-secondary uppercase tracking-[0.2em] mb-2">Store conversion proposal</div>
          <h1 className="text-3xl font-heading font-bold mb-2">ASO Workspace</h1>
          <p className="text-text-secondary text-sm">Compare live metadata with a proposed variant under the app rulebook.</p>
        </div>
         <button onClick={() => loadData(packageId)} className="self-start md:self-auto p-2.5 bg-surface hover:bg-white/5 border border-border-subtle rounded-lg" title="Reload listing and rulebook">
          <RefreshCw className="w-4 h-4" />
        </button>
      </header>

      {error && errorPackage === packageId && <div className="relative z-10 mb-5 bg-danger/10 border border-danger/20 text-danger text-sm p-4 rounded-xl flex gap-3"><AlertTriangle className="w-5 h-5 shrink-0" />{error}</div>}

      <section className="relative z-10 grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        <div className="glass-card p-4">
          <div className="text-[10px] text-text-muted uppercase font-mono mb-2">Current listing provenance</div>
          <div className="text-xs text-text-primary flex items-start gap-2"><Database className="w-4 h-4 text-info shrink-0" />{provenanceLabel(activeListing)}</div>
          <div className="text-[10px] text-text-muted font-mono mt-2">Version: {activeListing?.version || 'Unavailable'}</div>
        </div>
        <div className="glass-card p-4">
          <div className="text-[10px] text-text-muted uppercase font-mono mb-2">Rulebook authority</div>
          <div className="text-xs text-text-primary flex items-start gap-2"><Shield className="w-4 h-4 text-accent-primary shrink-0" />{activeRulebook?.provenance?.source || 'Source unavailable'}</div>
          <div className="text-[10px] text-text-muted font-mono mt-2">Version: {activeRulebook?.version || 'Unavailable'}</div>
        </div>
        <div className="glass-card p-4">
          <div className="text-[10px] text-text-muted uppercase font-mono mb-2">Diff status</div>
          <div className="text-xl font-mono font-bold">{changedFields.length} <span className="text-xs text-text-secondary font-normal">fields changed</span></div>
          <div className={`text-[10px] mt-2 font-mono ${hasValidationErrors ? 'text-danger' : 'text-success'}`}>{hasValidationErrors ? `${validationIssues.length} rulebook issue(s)` : 'Local rulebook checks pass'}</div>
        </div>
      </section>

      <div className="relative z-10 grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_340px] gap-6 items-start">
        <section className="glass-card overflow-hidden">
          <div className="px-5 py-4 border-b border-border-subtle flex items-center justify-between">
            <div>
              <h2 className="font-heading font-bold flex items-center gap-2"><FileText className="w-5 h-5 text-accent-primary" /> Field-level before / after</h2>
              <p className="text-xs text-text-secondary mt-1">Edits remain proposals until the server-owned lifecycle permits execution.</p>
            </div>
          </div>
          <div className="divide-y divide-border-subtle">
            {fields.map(field => {
              const constraint = activeRulebook?.constraints?.[field.key];
              const issues = validationIssues.filter(issue => issue.field === field.key);
              const changed = current[field.key] !== proposed[field.key];
              return (
                <div key={field.key} className="p-5">
                  <div className="flex items-center justify-between gap-3 mb-3">
                    <div className="text-xs font-mono uppercase tracking-wider text-text-secondary">{field.label}</div>
                    <div className="flex gap-2 text-[10px] font-mono">
                      {changed && <span className="bg-accent-primary/10 text-accent-primary border border-accent-primary/20 rounded px-2 py-0.5">Changed</span>}
                      <span className={constraint?.max_length != null && proposed[field.key].length > constraint.max_length ? 'text-danger' : 'text-text-muted'}>
                        {proposed[field.key].length}{constraint?.max_length != null ? ` / ${constraint.max_length}` : ' - limit unavailable'}
                      </span>
                    </div>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <div className="text-[9px] text-text-muted uppercase font-mono mb-1.5">Current - read only</div>
                      <div className="min-h-10 bg-black/20 border border-border-subtle rounded-lg p-3 text-xs text-text-secondary whitespace-pre-wrap break-words">{current[field.key] || 'No value supplied'}</div>
                    </div>
                    <div>
                      <div className="text-[9px] text-accent-secondary uppercase font-mono mb-1.5">Proposed</div>
                      {field.rows ? (
                        <textarea rows={field.rows} value={proposed[field.key]} onChange={event => setProposed(value => ({ ...value, [field.key]: event.target.value }))} className="w-full bg-surface border border-border-subtle rounded-lg p-3 text-xs outline-none focus:border-accent-primary leading-relaxed" />
                      ) : (
                        <input value={proposed[field.key]} onChange={event => setProposed(value => ({ ...value, [field.key]: event.target.value }))} className="w-full bg-surface border border-border-subtle rounded-lg p-3 text-xs outline-none focus:border-accent-primary" />
                      )}
                    </div>
                  </div>
                  <div className="mt-2 min-h-4">
                    {issues.map(issue => <div key={`${issue.code}-${issue.message}`} className="text-[10px] text-danger font-mono flex gap-1.5"><AlertTriangle className="w-3 h-3 shrink-0" />{issue.message}</div>)}
                    {issues.length === 0 && constraint && <div className="text-[10px] text-success font-mono flex gap-1.5"><Check className="w-3 h-3" />Rulebook constraint passes</div>}
                    {!constraint && <div className="text-[10px] text-warning font-mono">No field constraint supplied; server validation still required.</div>}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <aside className="space-y-5 xl:sticky xl:top-5">
          <section className="glass-card p-5">
            <h2 className="font-heading font-bold flex items-center gap-2 mb-4"><Search className="w-4 h-4 text-accent-secondary" /> Rulebook keywords</h2>
            {(activeRulebook?.target_keywords || []).length > 0 ? (
              <div className="space-y-2">
                {(activeRulebook?.target_keywords || []).map(keyword => {
                  const ranking = keywords.find(item => item.keyword === keyword);
                  return <div key={keyword} className="flex items-center justify-between bg-black/20 border border-border-subtle rounded-lg px-3 py-2 text-xs"><span>{keyword}</span><span className="font-mono text-text-muted">{ranking?.found ? `#${ranking.rank}` : ranking ? 'Not ranked' : 'Evidence unavailable'}</span></div>;
                })}
              </div>
            ) : <div className="text-xs text-text-muted border border-dashed border-border-subtle rounded-lg p-4">No target keywords are defined in the rulebook.</div>}
          </section>

          <section className="glass-card p-5">
            <h2 className="font-heading font-bold mb-4">Proposal policy</h2>
            <label className="block text-[10px] text-text-muted uppercase font-mono mb-1.5">Operating mode</label>
            <div className="space-y-2 mb-4">
              {allowedModes.map(candidate => (
                <button key={candidate} onClick={() => setMode(candidate)} className={`w-full text-left rounded-lg border p-3 transition-colors ${mode === candidate ? 'border-accent-primary bg-accent-primary/10' : 'border-border-subtle bg-black/20 hover:bg-white/5'}`}>
                  <div className="text-xs font-semibold">{modeCopy[candidate].label}</div>
                  <div className="text-[10px] text-text-secondary mt-1 leading-relaxed">{modeCopy[candidate].detail}</div>
                </button>
              ))}
            </div>
            <div className="rounded-lg border border-border-subtle bg-black/20 p-3 text-[10px] leading-relaxed text-text-secondary">
              The backend derives the hypothesis, measured baseline, success metric, target tool, and package from server-owned evidence. The browser submits only the proposed copy and policy controls.
            </div>
          </section>

          <button
            onClick={() => { setConfirmed(false); setShowConfirmation(true); }}
            disabled={!packageMatches || !activeRulebook || !activeListing || changedFields.length === 0 || hasValidationErrors || !allowedModes.includes(mode)}
            className="w-full bg-gradient-to-r from-accent-primary to-accent-secondary disabled:opacity-35 disabled:cursor-not-allowed text-white py-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 shadow-[0_0_20px_rgba(139,92,246,0.2)]"
          >
            Review safety & create proposal <ArrowRight className="w-4 h-4" />
          </button>
        </aside>
      </div>

      {showConfirmation && (
        <div className="fixed inset-0 z-[100] bg-background-base/75 backdrop-blur-md flex items-center justify-center p-4">
          <section ref={confirmationDialogRef} role="dialog" aria-modal="true" aria-labelledby={confirmationTitleId} aria-describedby={confirmationDescriptionId} tabIndex={-1} className="glass-card bg-background-base/95 w-full max-w-xl p-6 shadow-2xl outline-none">
            <button onClick={closeConfirmation} aria-label="Close proposal confirmation" className="float-right p-1 text-text-muted hover:text-white"><X className="w-5 h-5" /></button>
            <div className="w-10 h-10 rounded-xl bg-warning/10 text-warning flex items-center justify-center mb-4"><Shield className="w-5 h-5" /></div>
            <h2 id={confirmationTitleId} className="text-xl font-heading font-bold">Confirm proposal boundary</h2>
            <p id={confirmationDescriptionId} className="text-xs text-text-secondary mt-2 leading-relaxed">
              This creates a server-owned store-conversion proposal in <span className="text-white font-mono">{mode}</span> mode.{' '}
              {mode === 'auto_low_risk'
                ? 'If deterministic validation preserves auto-low-risk authority, the server may approve and write this listing immediately. Any policy downgrade stops before the write and returns the proposal for review.'
                : mode === 'manual'
                  ? 'No storefront write occurs until an attributed approval and a separate explicit execute command.'
                  : 'The proposal is persisted for review, but approval and execution remain disabled.'}
            </p>
            <div className="my-5 bg-black/20 border border-border-subtle rounded-xl p-4 text-xs space-y-2">
              <div className="flex justify-between"><span className="text-text-muted">Changed fields</span><span>{changedFields.map(field => field.label).join(', ')}</span></div>
              <div className="flex justify-between"><span className="text-text-muted">Listing version</span><span className="font-mono">{activeListing?.version || 'Unavailable'}</span></div>
              <div className="flex justify-between"><span className="text-text-muted">Rulebook version</span><span className="font-mono">{activeRulebook?.version || 'Unavailable'}</span></div>
            </div>
            <label className="flex items-start gap-3 text-xs text-text-secondary cursor-pointer">
              <input data-dialog-initial-focus type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} className="mt-0.5 accent-purple-500" />
              I reviewed the before/after diff and understand that execution authority is determined by the selected mode and server rulebook.
            </label>
            <div className="flex gap-3 mt-6">
              <button onClick={closeConfirmation} className="flex-1 border border-border-subtle bg-surface rounded-lg py-2.5 text-xs font-semibold">Cancel</button>
              <button onClick={submitProposal} disabled={!confirmed || submitting || !packageMatches || loadedPackage !== packageId} className="flex-1 bg-accent-primary disabled:opacity-40 rounded-lg py-2.5 text-xs font-semibold flex items-center justify-center gap-2">
                {submitting ? <div className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full" /> : <><TrendingUp className="w-4 h-4" /> Create proposal</>}
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
