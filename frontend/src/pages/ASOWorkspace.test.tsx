import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';

import { api, type AppRulebook, type Keyword, type StoreListing } from '../api';
import ASOWorkspace from './ASOWorkspace';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(next => { resolve = next; });
  return { promise, resolve };
}

function RouteHarness() {
  const navigate = useNavigate();
  return <>
    <button onClick={() => navigate('/app/b/aso')}>Switch app</button>
    <ASOWorkspace />
  </>;
}

const rulebook = (packageName: string): AppRulebook => ({
  package_name: packageName,
  allowed_autonomy_modes: ['recommend_only', 'manual'],
  target_keywords: [],
  constraints: {},
});

describe('ASOWorkspace package isolation', () => {
  it('ignores a stale app response after the route switches packages', async () => {
    const aRulebook = deferred<AppRulebook>();
    const aListing = deferred<StoreListing>();
    const aKeywords = deferred<Keyword[]>();
    vi.spyOn(api, 'getAppRulebook').mockImplementation(packageName => packageName === 'a' ? aRulebook.promise : Promise.resolve(rulebook('b')));
    vi.spyOn(api, 'getAppListing').mockImplementation(packageName => packageName === 'a'
      ? aListing.promise
      : Promise.resolve({ title: 'Current B Title', short_description: 'B short', full_description: 'B full' }));
    vi.spyOn(api, 'getAppKeywords').mockImplementation(packageName => packageName === 'a' ? aKeywords.promise : Promise.resolve([]));
    const createProposal = vi.spyOn(api, 'createStoreConversionProposal');

    render(
      <MemoryRouter initialEntries={['/app/a/aso']}>
        <Routes>
          <Route path="/app/:packageId/aso" element={<RouteHarness />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(api.getAppRulebook).toHaveBeenCalledWith('a', expect.any(AbortSignal)));
    fireEvent.click(screen.getByRole('button', { name: 'Switch app' }));
    expect(screen.queryByText('Current B Title')).not.toBeInTheDocument();

    expect(await screen.findByText('Current B Title')).toBeInTheDocument();
    await act(async () => {
      aRulebook.resolve(rulebook('a'));
      aListing.resolve({ title: 'Stale A Title', short_description: 'A short', full_description: 'A full' });
      aKeywords.resolve([]);
      await Promise.resolve();
    });

    expect(screen.queryByText('Stale A Title')).not.toBeInTheDocument();
    expect(screen.getByText('Current B Title')).toBeInTheDocument();
    expect(createProposal).not.toHaveBeenCalled();
  });
});
