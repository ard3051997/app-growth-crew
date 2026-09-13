import { Check, Circle, X } from 'lucide-react';

import { getLifecycleStages } from '../utils/experimentLifecycle';

export function LifecycleProgress({ status }: { status: string }) {
  const lifecycle = getLifecycleStages(status);
  const blocked = lifecycle.some(stage => stage.state === 'blocked');

  return (
    <section aria-label="Experiment lifecycle" className="rounded-xl border border-border-subtle bg-black/25 p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="text-[9px] font-mono uppercase tracking-[0.18em] text-text-muted">Lifecycle</div>
        <div className={`rounded-md border px-2.5 py-1 text-[10px] font-mono font-bold uppercase tracking-wider ${blocked ? 'border-danger/25 bg-danger/10 text-danger' : 'border-accent-primary/30 bg-accent-primary/15 text-accent-primary'}`}>
          {status.replaceAll('_', ' ')}
        </div>
      </div>
      <ol className="grid grid-cols-5 gap-1" aria-label={`Current state: ${status.replaceAll('_', ' ')}`}>
        {lifecycle.map(stage => {
          const Icon = stage.state === 'complete' ? Check : stage.state === 'blocked' ? X : Circle;
          return (
            <li
              key={stage.id}
              data-state={stage.state}
              className={`relative min-w-0 rounded-lg border px-1.5 py-2 text-center ${
                stage.state === 'current'
                  ? 'border-accent-primary/50 bg-accent-primary/15 text-white shadow-[0_0_18px_rgba(139,92,246,0.12)]'
                  : stage.state === 'complete'
                    ? 'border-success/20 bg-success/5 text-success'
                    : stage.state === 'blocked'
                      ? 'border-danger/30 bg-danger/10 text-danger'
                      : 'border-transparent text-text-muted'
              }`}
            >
              <Icon className={`mx-auto mb-1 h-3 w-3 ${stage.state === 'upcoming' ? 'opacity-40' : ''}`} fill={stage.state === 'current' ? 'currentColor' : 'none'} />
              <span className="block truncate text-[8px] font-mono uppercase sm:text-[9px]">{stage.label}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
