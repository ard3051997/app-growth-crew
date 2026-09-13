import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { SafetyStatusPanel } from './SafetyStatusPanel';

afterEach(cleanup);

describe('SafetyStatusPanel', () => {
  it('renders explicit unavailable values instead of inventing safe telemetry', () => {
    render(<SafetyStatusPanel safety={{}} />);

    expect(screen.getAllByText('Unavailable')).toHaveLength(4);
    expect(screen.getAllByText(/threshold unavailable/i)).toHaveLength(2);
    expect(screen.getByText('Provenance unavailable')).toBeInTheDocument();
  });

  it.each([
    ['Triggered', 'text-danger', 'border-t-danger'],
    ['Armed', 'text-success', 'border-t-success'],
    ['Unknown', 'text-warning', 'border-t-warning'],
  ])('maps %s to the expected safety tone', (status, textClass, borderClass) => {
    const view = render(<SafetyStatusPanel safety={{ emergency_brake: status }} />);

    expect(view.getByText(status)).toHaveClass(textClass);
    expect(view.getByRole('region', { name: 'Safety monitor' })).toHaveClass(borderClass);
    view.unmount();
  });
});
