import { Database } from 'lucide-react';

import type { Provenance } from '../api';
import { cn } from '../utils';

interface ProvenanceBadgeProps {
  provenance?: Provenance | null;
  source?: string | null;
  observedAt?: string | null;
  className?: string;
}

export function ProvenanceBadge({ provenance, source, observedAt, className }: ProvenanceBadgeProps) {
  const resolvedSource = provenance?.source || source || 'Provenance unavailable';
  const capturedAt = provenance?.captured_at || provenance?.retrieved_at || observedAt;
  const capturedDate = capturedAt ? new Date(capturedAt) : null;
  const capturedLabel = capturedDate && Number.isFinite(capturedDate.valueOf())
    ? capturedDate.toLocaleString()
    : null;
  const live = provenance?.is_live ?? provenance?.live;

  return (
    <span
      className={cn('inline-flex max-w-full items-center gap-1.5 rounded-md border border-info/20 bg-info/8 px-2 py-1 text-[9px] font-mono text-info', className)}
      title={capturedLabel ? `${resolvedSource} / ${capturedLabel}` : resolvedSource}
    >
      <Database className="h-3 w-3 shrink-0" />
      <span className="truncate">{resolvedSource}</span>
      {live != null && (
        <span className={cn('shrink-0 border-l pl-1.5 uppercase tracking-wider', live ? 'border-success/20 text-success' : 'border-border-subtle text-text-muted')}>
          {live ? 'Live' : 'Snapshot'}
        </span>
      )}
      {capturedLabel && <span className="hidden shrink-0 border-l border-border-subtle pl-1.5 text-text-muted sm:inline">{capturedLabel}</span>}
    </span>
  );
}
