import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { api } from '../api';
import JourneyMap from './JourneyMap';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function renderPage() {
  vi.spyOn(api, 'getAppJourneys').mockResolvedValue({
    journeys: {
      '1': {
        title: 'Onboarding',
        sections: [{ section_title: 'Start', rows: [{ Step: '1', 'Screen / State': 'Welcome', Event: 'app_open' }] }],
      },
    },
  });
  vi.spyOn(api, 'getAppEvents').mockResolvedValue({ events: [] });
  return render(
    <MemoryRouter initialEntries={['/app/com.example/journey']}>
      <Routes>
        <Route path="/app/:packageId/journey" element={<JourneyMap />} />
      </Routes>
    </MemoryRouter>,
  );
}

async function openFeedback() {
  fireEvent.click(await screen.findByText('Welcome'));
  fireEvent.click(screen.getByRole('button', { name: 'Feedback' }));
}

describe('JourneyMap review source state', () => {
  it('renders a rejected review request as source unavailable', async () => {
    vi.spyOn(api, 'getAppReviews').mockRejectedValue(new Error('Review provider offline'));
    renderPage();
    await openFeedback();

    expect(await screen.findByText('Review source unavailable')).toBeInTheDocument();
    expect(screen.getByText('Review provider offline')).toBeInTheDocument();
  });

  it('does not treat a legacy empty review array as an observed zero', async () => {
    vi.spyOn(api, 'getAppReviews').mockResolvedValue([]);
    renderPage();
    await openFeedback();

    expect(await screen.findByText('Review source status unavailable')).toBeInTheDocument();
    expect(screen.getByText(/cannot be treated as an observed zero/i)).toBeInTheDocument();
  });

  it('renders an explicitly empty review response as zero lexical matches', async () => {
    vi.spyOn(api, 'getAppReviews').mockResolvedValue({ reviews: [], status: 'empty' });
    renderPage();
    await openFeedback();

    expect(await screen.findByText(/available review source returned zero lexical matches/i)).toBeInTheDocument();
    expect(screen.queryByText('Review source status unavailable')).not.toBeInTheDocument();
  });
});
