export type LifecycleStageState = 'complete' | 'current' | 'upcoming' | 'blocked';

export interface LifecycleStage {
  id: 'proposed' | 'approved' | 'active' | 'measuring' | 'concluded';
  label: string;
  state: LifecycleStageState;
}

const stages: Array<Pick<LifecycleStage, 'id' | 'label'>> = [
  { id: 'proposed', label: 'Proposed' },
  { id: 'approved', label: 'Approved' },
  { id: 'active', label: 'Live' },
  { id: 'measuring', label: 'Measuring' },
  { id: 'concluded', label: 'Concluded' },
];

const currentStageByStatus: Record<string, number> = {
  proposed: 0,
  approved: 1,
  executing: 2,
  active: 2,
  observing: 3,
  measuring: 3,
  evaluated: 4,
  retained: 4,
  concluded: 4,
};

const blockedStageByStatus: Record<string, number> = {
  rejected: 1,
  failed: 2,
  rolled_back: 4,
};

export function getLifecycleStages(status: string): LifecycleStage[] {
  const normalized = status.toLowerCase();
  const blockedIndex = blockedStageByStatus[normalized];
  const currentIndex = currentStageByStatus[normalized] ?? 0;

  return stages.map((stage, index) => ({
    ...stage,
    state: blockedIndex != null
      ? index < blockedIndex
        ? 'complete'
        : index === blockedIndex
          ? 'blocked'
          : 'upcoming'
      : index < currentIndex
        ? 'complete'
        : index === currentIndex
          ? 'current'
          : 'upcoming',
  }));
}
