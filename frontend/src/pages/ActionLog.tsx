import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ShieldAlert, Wrench, FlaskConical, Bell, ChevronDown, RefreshCw } from 'lucide-react';
import { api, type ActionEntry, type Experiment, type PortfolioApp, type SafetyStatus } from '../api';
import { SafetyStatusPanel } from '../components/SafetyStatusPanel';
import { getErrorMessage } from '../utils';

type ActionRow = ActionEntry & { expanded: boolean };

export default function ActionLog() {
  const [safety, setSafety] = useState<SafetyStatus | null>(null);
  const [actions, setActions] = useState<ActionRow[]>([]);
  const [apps, setApps] = useState<PortfolioApp[]>([]);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [appFilter, setAppFilter] = useState<string>('');
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [experimentFilter, setExperimentFilter] = useState<string>('');
  const navigate = useNavigate();

  const loadData = () => {
    setLoading(true);
    setError(null);
    Promise.all([
      api.getSystemSafety(),
      api.getActions(appFilter || undefined, typeFilter || undefined, 50, experimentFilter || undefined)
    ])
      .then(([safetyData, actionsData]) => {
        setSafety(safetyData);
        // Add expanded key to action rows
        const rows = (actionsData.actions || []).map((action) => ({ ...action, expanded: false }));
        setActions(rows);
        setLoading(false);
      })
      .catch(err => {
        console.error(err);
        setError(getErrorMessage(err, 'Failed to load action logs'));
        setLoading(false);
      });
  };

  useEffect(() => {
    let active = true;
    const refresh = () => {
      Promise.all([api.getSystemSafety(), api.getActions(appFilter || undefined, typeFilter || undefined, 50, experimentFilter || undefined)])
        .then(([safetyData, actionsData]) => {
          if (!active) return;
          setSafety(safetyData);
          setActions((actionsData.actions || []).map(action => ({ ...action, expanded: false })));
          setError(null);
          setLoading(false);
        })
        .catch(err => {
          if (!active) return;
          setError(getErrorMessage(err, 'Failed to load action logs'));
          setLoading(false);
        });
    };
    refresh();
    const poll = () => {
      if (document.visibilityState === 'visible') refresh();
    };
    const interval = window.setInterval(poll, 30_000);
    document.addEventListener('visibilitychange', poll);
    return () => {
      active = false;
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', poll);
    };
  }, [appFilter, typeFilter, experimentFilter]);

  useEffect(() => {
    Promise.all([api.getPortfolio(), api.getExperiments()])
      .then(([portfolio, experimentResponse]) => {
        setApps(portfolio.apps || []);
        setExperiments(experimentResponse.experiments || []);
      })
      .catch(() => {
        setApps([]);
        setExperiments([]);
      });
  }, []);

  const toggleExpand = (id: string | number) => {
    setActions(prev => prev.map(act => act.id === id ? { ...act, expanded: !act.expanded } : act));
  };

  if (loading && actions.length === 0) {
    return (
      <div className="p-8 flex justify-center items-center h-full">
        <div className="animate-spin w-8 h-8 border-2 border-accent-primary border-t-transparent rounded-full" />
      </div>
    );
  }

  // Format time relative or iso
  const formatTime = (timeStr: string) => {
    if (!timeStr) return '';
    try {
      const d = new Date(timeStr);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' ' + d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    } catch {
      return timeStr;
    }
  };

  return (
    <div className="p-8 max-w-[1200px] mx-auto h-screen flex flex-col relative overflow-hidden">
      {/* Glow ambient */}
      <div className="absolute top-[-10%] right-[-10%] w-[35%] h-[35%] bg-accent-primary/5 rounded-full blur-[100px] pointer-events-none" />

      <header className="mb-6 flex justify-between items-end z-10">
        <div>
          <h1 className="text-3xl font-heading font-bold mb-2">Action Log & Safety Monitor</h1>
          <p className="text-text-secondary">Audit trail of all autonomous actions and system health.</p>
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
          <ShieldAlert className="w-5 h-5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Safety Monitor */}
      {safety && <SafetyStatusPanel safety={safety} />}

      {/* Action Log */}
      <div className="flex-1 bg-surface border border-border-subtle rounded-xl overflow-hidden flex flex-col z-10">
        <div className="px-6 py-4 border-b border-border-subtle bg-black/20 flex items-center justify-between">
          <h2 className="font-heading font-bold text-sm uppercase tracking-wider">Event Stream</h2>
          <div className="flex flex-wrap justify-end gap-2">
            <select
              value={appFilter}
              onChange={(e) => setAppFilter(e.target.value)}
              className="text-xs bg-surface border border-border-subtle rounded px-2 py-1 text-text-secondary outline-none focus:border-accent-primary"
            >
              <option value="">All Apps</option>
              {apps.map(app => <option key={app.package_name} value={app.package_name}>{app.display_name}</option>)}
            </select>
            <select
              value={experimentFilter}
              onChange={(e) => setExperimentFilter(e.target.value)}
              className="max-w-[210px] text-xs bg-surface border border-border-subtle rounded px-2 py-1 text-text-secondary outline-none focus:border-accent-primary"
            >
              <option value="">All experiments</option>
              {experiments.map(experiment => <option key={experiment.id} value={experiment.id}>{experiment.id.slice(0, 8)} - {experiment.app_package}</option>)}
            </select>
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="text-xs bg-surface border border-border-subtle rounded px-2 py-1 text-text-secondary outline-none focus:border-accent-primary"
            >
              <option value="">All Types</option>
              <option value="mcp_tool_call">Tool Calls</option>
              <option value="experiment_start">Experiment Starts</option>
              <option value="rollback">Rollbacks</option>
              <option value="safety_trigger">Safety Triggers</option>
            </select>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-2">
          {actions.map((act) => {
            const isTool = act.action_type === 'mcp_tool_call';
            const isExp = act.experiment_id != null || act.action_type.startsWith('experiment_');
            const isSafety = act.action_type === 'safety_trigger';
            const isRollback = act.action_type === 'rollback';

            const Icon = isTool ? Wrench : isExp ? FlaskConical : isSafety ? ShieldAlert : Bell;

            let resultColor = 'bg-white/5 text-text-muted';
            if (act.result?.toLowerCase() === 'success' || act.result?.toLowerCase() === 'succeeded') {
              resultColor = 'bg-success/20 text-success';
            }
            if (act.result?.toLowerCase() === 'failed' || act.result?.toLowerCase() === 'error') {
              resultColor = 'bg-danger/20 text-danger';
            } else if (act.result?.toLowerCase() === 'blocked_by_policy') {
              resultColor = 'bg-warning/20 text-warning';
            }

            const formattedArgs = typeof act.arguments === 'string'
              ? act.arguments
              : JSON.stringify(act.arguments, null, 2);

            return (
              <div key={act.id} className="mb-2 glass-card overflow-hidden border border-border-subtle">
                <div
                  className="px-4 py-3 flex items-center gap-4 cursor-pointer hover:bg-white/5 transition-colors"
                  onClick={() => toggleExpand(act.id)}
                >
                  <div className="w-32 text-xs font-mono text-text-muted shrink-0">
                    {formatTime(act.timestamp)}
                  </div>

                  <div className={`p-1.5 rounded-md shrink-0 bg-surface border border-border-subtle`}>
                    <Icon className="w-4 h-4 text-text-secondary" />
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-xs font-mono text-text-muted truncate max-w-[200px]">
                        {act.app_package || 'system'}
                      </span>
                      <span className={`text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded-sm font-bold font-mono ${resultColor}`}>
                        {act.result ?? 'result unavailable'}
                      </span>
                    </div>
                    <div className="text-sm truncate font-medium text-text-primary">
                      {isTool ? `Invoked ${act.tool_name}` :
                       isRollback ? 'Triggered rollback' :
                       isSafety ? 'Safety threshold alert' : act.action_type}
                    </div>
                  </div>

                  <ChevronDown className={`w-4 h-4 text-text-muted transition-transform ${act.expanded ? 'rotate-180' : ''}`} />
                </div>

                {act.expanded && (
                  <div className="px-4 py-4 bg-black/40 border-t border-border-subtle font-mono text-xs text-text-secondary space-y-3">
                    {act.reasoning && (
                      <div>
                        <div className="text-[10px] text-text-muted uppercase tracking-wider font-bold mb-1">Reasoning</div>
                        <div className="bg-surface/30 p-2.5 rounded border border-border-subtle text-text-primary leading-relaxed">
                          {act.reasoning}
                        </div>
                      </div>
                    )}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <div className="text-[10px] text-text-muted uppercase tracking-wider font-bold mb-1">Experiment correlation</div>
                        {act.experiment_id ? (
                          <button onClick={() => navigate(`/experiments?experiment=${encodeURIComponent(act.experiment_id || '')}`)} className="text-accent-primary hover:text-accent-secondary font-mono text-xs text-left">
                            {act.experiment_id}
                          </button>
                        ) : <div className="text-warning">Not supplied</div>}
                      </div>
                      <div>
                        <div className="text-[10px] text-text-muted uppercase tracking-wider font-bold mb-1">Safety decision</div>
                        <div className={act.safety_decision == null ? 'text-warning' : 'text-text-primary'}>{act.safety_decision ?? 'Not supplied'}</div>
                        {act.policy_name && <div className="text-[10px] text-text-muted mt-1">Policy: {act.policy_name}</div>}
                      </div>
                    </div>
                    {act.tool_name && (
                      <div>
                        <div className="text-[10px] text-text-muted uppercase tracking-wider font-bold mb-1">Tool Name</div>
                        <div className="text-accent-secondary font-bold font-mono text-sm">{act.tool_name}</div>
                      </div>
                    )}
                    {formattedArgs && formattedArgs !== '{}' && formattedArgs !== 'null' && (
                      <div>
                        <div className="text-[10px] text-text-muted uppercase tracking-wider font-bold mb-1">Arguments</div>
                        <pre className="bg-surface/50 p-2.5 rounded border border-border-subtle overflow-x-auto text-[10px] text-info">
                          {formattedArgs}
                        </pre>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}

          {actions.length === 0 && (
            <div className="text-text-muted text-sm italic text-center p-8 bg-surface/30 rounded-lg py-12">
              No logged actions matching the filter.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
