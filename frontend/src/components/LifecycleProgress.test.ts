import { describe, expect, it } from 'vitest';

import { getLifecycleStages } from '../utils/experimentLifecycle';

describe('getLifecycleStages', () => {
  it('marks earlier stages complete and the active stage as current', () => {
    expect(getLifecycleStages('measuring').map(stage => stage.state)).toEqual([
      'complete',
      'complete',
      'complete',
      'current',
      'upcoming',
    ]);
  });

  it('makes terminal exception states visibly blocked', () => {
    expect(getLifecycleStages('rejected').map(stage => stage.state)).toEqual([
      'complete',
      'blocked',
      'upcoming',
      'upcoming',
      'upcoming',
    ]);
    expect(getLifecycleStages('rolled_back').at(-1)?.state).toBe('blocked');
  });
});
