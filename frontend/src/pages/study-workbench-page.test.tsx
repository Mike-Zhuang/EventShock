import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import { I18nProvider } from '../i18n';
import { StudyWorkbenchPage } from './study-workbench-page';

vi.mock('../api/client', () => ({
  api: {
    getStudyPresets: vi.fn(),
    getStudyRuns: vi.fn(),
    getStudyRun: vi.fn(),
    previewStudyDesign: vi.fn(),
    runStudy: vi.fn(),
  },
}));

vi.mock('../state/workflow-context', () => ({
  useWorkflow: () => ({
    eventPack: {
      id: 'spacex-nasdaq100-2026-v1',
      status: 'FROZEN',
      name: 'SpaceX research pack',
    },
  }),
}));

const catalog = {
  schemaVersion: '1.0.0',
  historicalValidityEstablished: false as const,
  validityBoundary: 'Templates are model-internal and not executed evidence.',
  requiredNegativeControlCount: 8,
  requiredAblationCount: 10,
  supportedOutcomes: [
    { outcomeId: 'max-spread-bps' as const, unit: 'basis-points' },
    { outcomeId: 'max-drawdown-pct' as const, unit: 'percent' },
    { outcomeId: 'total-volume' as const, unit: 'shares' },
  ],
  supportedFactors: [{
    parameterPath: 'intervention.value' as const,
    unit: 'multiplier',
    minimum: 0.05,
    maximum: 4,
  }],
  items: [{
    presetId: 'spacex-s1-index-demand-liquidity',
    eventPackId: 'spacex-nasdaq100-2026-v1',
    title: 'SpaceX S1 — Index demand and liquidity',
    titleZh: 'SpaceX S1——指数需求与流动性',
    question: 'Under which modeled conditions does passive demand amplify liquidity stress?',
    questionZh: '在什么模型条件下，被动需求会放大流动性压力？',
    recommendedInterventionParameter: 'marketMakerCapacity' as const,
    factorPaths: ['intervention.value' as const],
    primaryOutcomeIds: ['max-spread-bps' as const, 'max-drawdown-pct' as const],
  }],
};

describe('Study Workbench', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    });
    vi.mocked(api.getStudyPresets).mockResolvedValue(catalog);
    vi.mocked(api.getStudyRuns).mockResolvedValue([]);
    vi.mocked(api.previewStudyDesign).mockResolvedValue({
      designKind: 'FULL_FACTORIAL',
      designCellCount: 3,
      requiredNegativeControlCount: 8,
      requiredAblationCount: 10,
      totalExecutionCells: 22,
      matchedSeedCount: 2,
      expectedRunCount: 44,
      estimatedWorkUnits: 18_480,
      maximumRunCount: 96,
      maximumWorkUnits: 150_000,
      withinResourceLimits: true,
      historicalValidityEstablished: false,
      cells: [],
    });
  });

  it('keeps non-validation labeling visible and requires a backend resource preview', async () => {
    const user = userEvent.setup();
    render(
      <I18nProvider>
        <StudyWorkbenchPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    expect(await screen.findByRole('heading', { name: 'Study Workbench' })).toBeInTheDocument();
    expect(screen.getByText('Historical validity is not established')).toBeInTheDocument();
    expect(screen.getByText('MODEL-INTERNAL ONLY')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Preview full design' }));

    await waitFor(() => expect(api.previewStudyDesign).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('44 / 96')).toBeInTheDocument();
    expect(screen.getByText('18,480 / 150,000')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run preregistered study' })).toBeDisabled();
  });
});
