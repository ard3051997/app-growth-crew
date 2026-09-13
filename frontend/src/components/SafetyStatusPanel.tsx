import { ShieldAlert } from 'lucide-react';

import type { SafetyStatus } from '../api';
import { ProvenanceBadge } from './ProvenanceBadge';

function formatTime(time: string) {
  const date = new Date(time);
  return Number.isFinite(date.valueOf())
    ? `${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} ${date.toLocaleDateString([], { month: 'short', day: 'numeric' })}`
    : time;
}

export function SafetyStatusPanel({ safety }: { safety: SafetyStatus }) {
  const brakeState = safety.emergency_brake?.toLowerCase();
  const brakeTone = brakeState === 'triggered'
    ? { border: 'border-t-danger', text: 'text-danger' }
    : brakeState === 'armed'
      ? { border: 'border-t-success', text: 'text-success' }
      : { border: 'border-t-warning', text: 'text-warning' };
  return (
    <section className={`glass-card p-6 mb-8 border-t-4 ${brakeTone.border} flex flex-col md:flex-row justify-between md:items-center gap-5 z-10`} aria-label="Safety monitor">
      <div className="flex flex-wrap gap-8">
        <div>
          <div className="text-xs text-text-muted uppercase tracking-wider mb-1">Emergency Brake</div>
          <div className={`font-mono font-bold flex items-center gap-2 ${brakeTone.text}`}>
            <ShieldAlert className="w-4 h-4" /> {safety.emergency_brake ?? 'Unavailable'}
          </div>
        </div>
        <div>
          <div className="text-xs text-text-muted uppercase tracking-wider mb-1">Max Crash Rate</div>
          <div className="font-mono font-bold text-text-primary">
            <span className={safety.crash_rate == null ? 'text-warning' : 'text-success'}>{safety.crash_rate == null ? 'Unavailable' : `${safety.crash_rate.toFixed(2)}%`}</span> / {safety.crash_threshold == null ? 'threshold unavailable' : `${safety.crash_threshold.toFixed(2)}%`}
          </div>
        </div>
        <div>
          <div className="text-xs text-text-muted uppercase tracking-wider mb-1">Max ANR Rate</div>
          <div className="font-mono font-bold text-text-primary">
            <span className="text-warning">{safety.anr_rate == null ? 'Unavailable' : `${safety.anr_rate.toFixed(2)}%`}</span> / {safety.anr_threshold == null ? 'threshold unavailable' : `${safety.anr_threshold.toFixed(2)}%`}
          </div>
        </div>
      </div>
      <div className="md:text-right">
        <div className="text-xs text-text-muted uppercase tracking-wider mb-1">Last Scan</div>
        <div className="font-mono text-sm mb-2">{safety.last_scan ? formatTime(safety.last_scan) : 'Unavailable'}</div>
        <ProvenanceBadge provenance={safety.provenance} />
      </div>
    </section>
  );
}
