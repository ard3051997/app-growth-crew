import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { api, type Experiment } from '../api';
import ExperimentCenter from './ExperimentCenter';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const proposed: Experiment = {
  id: 'exp-1',
  app_package: 'com.example',
  experiment_type: 'store_conversion',
  hypothesis: 'A clearer title improves conversion',
  status: 'proposed',
  success_metric: 'store_view_to_install_rate',
  available_actions: ['approve'],
  observations: [],
  evidence: [],
};

describe('ExperimentCenter semantic actions', () => {
  it('keeps a successful action result when follow-up refreshes fail', async () => {
    const approved: Experiment = { ...proposed, status: 'approved', available_actions: ['execute'] };
    vi.spyOn(api, 'getExperiments')
      .mockResolvedValueOnce({ experiments: [proposed] })
      .mockRejectedValueOnce(new Error('list refresh unavailable'));
    vi.spyOn(api, 'getExperiment')
      .mockResolvedValueOnce(proposed)
      .mockRejectedValueOnce(new Error('detail refresh unavailable'));
    vi.spyOn(api, 'getPortfolio').mockResolvedValue({ apps: [] });
    vi.spyOn(api, 'getExperimentTypes').mockResolvedValue({ experiment_types: [] });
    const runAction = vi.spyOn(api, 'runExperimentAction').mockResolvedValue({
      experiment: approved,
      message: 'Experiment approved',
    });

    render(
      <MemoryRouter initialEntries={['/experiments?experiment=exp-1']}>
        <Routes>
          <Route path="/experiments" element={<ExperimentCenter />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: 'Approve proposal' }));
    fireEvent.change(screen.getByPlaceholderText('Reason required'), { target: { value: 'Reviewed evidence' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm approve' }));

    expect(await screen.findByText(/Experiment approved.*follow-up refresh was unavailable/i)).toBeInTheDocument();
    expect(screen.getAllByText('approved').length).toBeGreaterThan(0);
    expect(screen.queryByText(/Failed to approve experiment/i)).not.toBeInTheDocument();
    await waitFor(() => expect(runAction).toHaveBeenCalledWith('exp-1', 'approve', {
      reason: 'Reviewed evidence',
    }));
    expect(screen.queryByPlaceholderText('Actor')).not.toBeInTheDocument();
  });

  it('opens the supported proposal builder from the new experiment entry point', async () => {
    vi.spyOn(api, 'getExperiments').mockResolvedValue({ experiments: [] });
    vi.spyOn(api, 'getPortfolio').mockResolvedValue({
      apps: [{
        package_name: 'com.example.app',
        display_name: 'Example App',
        funnel_health_score: 80,
        revenue_30d: 0,
        revenue_change_pct: 0,
        profit_30d: 0,
        installs_7d: [],
        active_experiments: 0,
      }],
    });
    vi.spyOn(api, 'getExperimentTypes').mockResolvedValue({
      experiment_types: [{
        id: 'aso_metadata',
        label: 'Play Store metadata',
        description: 'Test listing metadata.',
        default_metric: 'store_view_to_install_rate',
        capability: 'executable',
        builder: 'aso',
      }],
    });

    render(
      <MemoryRouter initialEntries={['/experiments']}>
        <Routes>
          <Route path="/experiments" element={<ExperimentCenter />} />
          <Route path="/app/:packageId/aso" element={<div>ASO proposal builder</div>} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: 'New experiment' }));
    expect(screen.getByRole('dialog', { name: 'Create an experiment' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'App' })).toHaveValue('com.example.app');
    fireEvent.click(screen.getByRole('button', { name: /Open proposal builder/i }));
    expect(await screen.findByText('ASO proposal builder')).toBeInTheDocument();
  });

  it('creates unsupported types as recommendation-only planning experiments', async () => {
    const planned: Experiment = {
      ...proposed,
      id: 'exp-paywall',
      experiment_type: 'paywall_variant',
      hypothesis: 'A shorter paywall will improve trial conversion',
      success_metric: 'trial_to_paid_conversion_rate',
      autonomy_mode: 'recommend_only',
      available_actions: ['reject'],
    };
    vi.spyOn(api, 'getExperiments').mockResolvedValue({ experiments: [] });
    vi.spyOn(api, 'getExperiment').mockResolvedValue(planned);
    vi.spyOn(api, 'getPortfolio').mockResolvedValue({
      apps: [{
        package_name: 'com.example.app',
        display_name: 'Example App',
        funnel_health_score: 80,
        revenue_30d: 0,
        revenue_change_pct: 0,
        profit_30d: 0,
        installs_7d: [],
        active_experiments: 0,
      }],
    });
    vi.spyOn(api, 'getExperimentTypes').mockResolvedValue({
      experiment_types: [
        {
          id: 'aso_metadata',
          label: 'Play Store metadata',
          description: 'Test listing metadata.',
          default_metric: 'store_view_to_install_rate',
          capability: 'executable',
          builder: 'aso',
        },
        {
          id: 'paywall_variant',
          label: 'Paywall variant',
          description: 'Track a paywall hypothesis.',
          default_metric: 'trial_to_paid_conversion_rate',
          capability: 'planning_only',
        },
      ],
    });
    const createPlanned = vi.spyOn(api, 'createPlannedExperiment').mockResolvedValue({
      experiment: planned,
      message: 'Planning experiment created.',
    });

    render(
      <MemoryRouter initialEntries={['/experiments']}>
        <Routes><Route path="/experiments" element={<ExperimentCenter />} /></Routes>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: 'New experiment' }));
    fireEvent.click(screen.getByRole('button', { name: /Paywall variant/i }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Hypothesis' }), {
      target: { value: planned.hypothesis },
    });
    fireEvent.click(screen.getByRole('button', { name: /Create planning experiment/i }));

    await waitFor(() => expect(createPlanned).toHaveBeenCalledWith(expect.objectContaining({
      app_package: 'com.example.app',
      experiment_type: 'paywall_variant',
      hypothesis: planned.hypothesis,
      success_metric: 'trial_to_paid_conversion_rate',
    })));
    expect(await screen.findByText(planned.hypothesis)).toBeInTheDocument();
  });

  it('recommends and creates an experiment design from MCP evidence', async () => {
    const recommendation = {
      id: 'com.example.app:Paywall View → Trial Start:paywall_variant',
      rank: 1,
      app_package: 'com.example.app',
      experiment_type: 'paywall_variant',
      label: 'Paywall variant',
      focus: 'monetization' as const,
      hypothesis: 'A clearer paywall will improve trial conversion toward benchmark.',
      rationale: 'Paywall conversion is below benchmark.',
      success_metric: 'paywall_to_trial_start_rate',
      suggested_min_observation_days: 7,
      suggested_max_observation_days: 28,
      target_improvement_pct: 0.1,
      estimated_monthly_impact: 2500,
      conflicts_with_active_experiment: false,
      capability: 'planning_only' as const,
      design: {
        method: 'before_after',
        control: 'Current paywall.',
        treatment: 'Benefit-led paywall.',
        primary_metric: 'paywall_to_trial_start_rate',
        guardrail_metrics: ['refund_rate'],
        analysis_plan: 'Compare source-backed periods.',
        sample_guidance: 'Wait for minimum samples.',
      },
      evidence: {
        stage: 'Paywall View → Trial Start',
        actual_rate: 0.08,
        benchmark_rate: 0.15,
        gap: -0.07,
        estimated_monthly_impact: 2500,
        sources: ['analytics_mcp', 'revenuecat_mcp'],
        captured_at: '2026-07-22T00:00:00Z',
        freshness: 'fresh' as const,
      },
    };
    const planned: Experiment = {
      ...proposed,
      id: 'recommended-exp',
      experiment_type: recommendation.experiment_type,
      hypothesis: recommendation.hypothesis,
      success_metric: recommendation.success_metric,
      autonomy_mode: 'recommend_only',
      recommendation,
      available_actions: ['reject'],
    };
    vi.spyOn(api, 'getExperiments').mockResolvedValue({ experiments: [] });
    vi.spyOn(api, 'getExperiment').mockResolvedValue(planned);
    vi.spyOn(api, 'getExperimentTypes').mockResolvedValue({ experiment_types: [] });
    vi.spyOn(api, 'getPortfolio').mockResolvedValue({
      apps: [{
        package_name: 'com.example.app',
        display_name: 'Example App',
        funnel_health_score: 65,
        revenue_30d: 0,
        revenue_change_pct: 0,
        profit_30d: 0,
        installs_7d: [],
        active_experiments: 0,
      }],
    });
    vi.spyOn(api, 'recommendExperimentDesigns').mockResolvedValue({
      app_package: 'com.example.app',
      generated_at: '2026-07-22T00:00:00Z',
      source_status: 'fresh',
      snapshot_source: 'cached_mcp_snapshot',
      data_sources: ['analytics_mcp', 'revenuecat_mcp'],
      recommendations: [recommendation],
    });
    const createPlanned = vi.spyOn(api, 'createPlannedExperiment').mockResolvedValue({
      experiment: planned,
      message: 'Planning experiment created.',
    });

    render(
      <MemoryRouter initialEntries={['/experiments']}>
        <Routes><Route path="/experiments" element={<ExperimentCenter />} /></Routes>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: 'Recommend from data' }));
    fireEvent.click(screen.getByRole('button', { name: /Analyze MCP data/i }));
    expect(await screen.findByText(recommendation.hypothesis)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Create this experiment/i }));

    await waitFor(() => expect(createPlanned).toHaveBeenCalledWith(expect.objectContaining({
      experiment_type: 'paywall_variant',
      recommendation,
    })));
    expect(await screen.findByText('Recommended design')).toBeInTheDocument();
  });
});
