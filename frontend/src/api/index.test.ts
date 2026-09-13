import { afterEach, describe, expect, it, vi } from 'vitest';

import { api, type StoreConversionProposalInput } from './index';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('createStoreConversionProposal', () => {
  it('uses the encoded app route and sends only the proposal contract', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ experiment: { id: 'exp-1' } }),
    });
    vi.stubGlobal('fetch', fetchMock);
    const proposal: StoreConversionProposalInput = {
      language: 'en-US',
      country: 'us',
      execution_mode: 'manual',
      proposed_listing: {
        title: 'New title',
        short_description: 'New short description',
        full_description: 'New full description',
      },
    };

    await api.createStoreConversionProposal('com.example/app beta', proposal);

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/apps/com.example%2Fapp%20beta/store-conversion/proposals',
      {
        headers: { 'Content-Type': 'application/json' },
        method: 'POST',
        body: JSON.stringify(proposal),
      },
    );
  });
});

describe('API routing and semantic actions', () => {
  it('defaults requests to the same-origin /api path', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ status: 'ok' }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await api.getSystemStatus();

    expect(fetchMock).toHaveBeenCalledWith('/api/system/status', {
      headers: { 'Content-Type': 'application/json' },
    });
  });

  it('returns the semantic-action envelope and sends only a reason when attribution is required', async () => {
    const actionResponse = {
      experiment: { id: 'exp-1', status: 'approved', app_package: 'com.example' },
      message: 'Experiment approved',
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(actionResponse),
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.runExperimentAction('exp-1', 'approve', { reason: 'reviewed' })).resolves.toEqual(actionResponse);
    await api.runExperimentAction('exp-1', 'execute');

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/experiments/exp-1/approve', {
      headers: { 'Content-Type': 'application/json' },
      method: 'POST',
      body: JSON.stringify({ reason: 'reviewed' }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/experiments/exp-1/execute', {
      headers: { 'Content-Type': 'application/json' },
      method: 'POST',
    });
  });

  it('returns the evaluate action envelope with its experiment and evaluation', async () => {
    const evaluation = { verdict: 'winner', confidence: 0.98, treatment_rate: 0.26 };
    const actionResponse = {
      experiment: { id: 'exp-1', status: 'evaluated', app_package: 'com.example' },
      evaluation,
      message: 'Experiment evaluated',
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(actionResponse),
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.runExperimentAction('exp-1', 'evaluate')).resolves.toEqual(actionResponse);
    expect(fetchMock).toHaveBeenCalledWith('/api/experiments/exp-1/evaluate', {
      headers: { 'Content-Type': 'application/json' },
      method: 'POST',
    });
  });

  it('requests experiment designs from the encoded app MCP recommendation route', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ recommendations: [] }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await api.recommendExperimentDesigns('com.example/app', {
      focus: 'monetization',
      max_results: 4,
      refresh_live: false,
    });

    expect(fetchMock).toHaveBeenCalledWith('/api/apps/com.example%2Fapp/experiment-recommendations', {
      headers: { 'Content-Type': 'application/json' },
      method: 'POST',
      body: JSON.stringify({ focus: 'monetization', max_results: 4, refresh_live: false }),
    });
  });
});
