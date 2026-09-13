import { cleanup, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { api, type FunnelResponse, type ReviewsAnalysis } from '../api';
import FunnelDiagnostics from './FunnelDiagnostics';

vi.mock('recharts', async importOriginal => {
  const actual = await importOriginal<typeof import('recharts')>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  };
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const funnel: FunnelResponse = {
  all_steps: [{
    name: 'Onboarding',
    conversion_rate: 0.5,
    benchmark_rate: 0.6,
    users_entered: 100,
    users_completed: 50,
  }],
  funnel_health_score: 50,
  total_monthly_revenue_impact: null,
  ranked_leaks: [],
};

const emptyAnalysis: ReviewsAnalysis = {
  average_rating: 0,
  total_reviews: 0,
  sentiment: { positive: 0, neutral: 0, negative: 0 },
  keywords: [],
  stage_correlation: {
    onboarding: { count: 0, rating: 0, reviews: [] },
  },
};

function renderPage() {
  vi.spyOn(api, 'getAppFunnel').mockResolvedValue(funnel);
  vi.spyOn(api, 'getAppDiagnostic').mockResolvedValue({ diagnostic: '' });
  vi.spyOn(api, 'getExperiments').mockResolvedValue({ experiments: [] });
  return render(
    <MemoryRouter initialEntries={['/app/com.example/funnel']}>
      <Routes>
        <Route path="/app/:packageId/funnel" element={<FunnelDiagnostics />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('FunnelDiagnostics review source state', () => {
  it('renders review-source failure without failing the funnel request', async () => {
    vi.spyOn(api, 'getAppReviewsAnalysis').mockRejectedValue(new Error('Play reviews offline'));
    renderPage();

    expect(await screen.findByText('Overall Score')).toBeInTheDocument();
    expect(screen.getAllByText('Review source unavailable').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Play reviews offline').length).toBeGreaterThan(0);
  });

  it('does not present an unprovenanced zero response as measured', async () => {
    vi.spyOn(api, 'getAppReviewsAnalysis').mockResolvedValue(emptyAnalysis);
    renderPage();

    expect(await screen.findByText('Review source status unavailable')).toBeInTheDocument();
    expect(screen.getByText(/zero is not presented as an observed measurement/i)).toBeInTheDocument();
    expect(screen.queryByText('Observed review sample: 0')).not.toBeInTheDocument();
  });

  it('renders an explicit empty source as an observed zero', async () => {
    vi.spyOn(api, 'getAppReviewsAnalysis').mockResolvedValue({ ...emptyAnalysis, status: 'empty' });
    renderPage();

    expect(await screen.findByText('Observed review sample: 0')).toBeInTheDocument();
    expect(screen.getAllByText(/source explicitly reported an empty sample/i).length).toBeGreaterThan(0);
  });
});
