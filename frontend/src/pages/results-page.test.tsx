import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Navigate } from '../app';
import { normalizeResults } from '../api/normalize';
import { I18nProvider } from '../i18n';
import { useWorkflow } from '../state/workflow-context';
import { ResultsPage } from './results-page';

vi.mock('../components/result-interpretation-assistant', () => ({
  ResultInterpretationAssistant: () => <section aria-label="Result interpretation assistant" />,
}));

vi.mock('../state/workflow-context', () => ({
  useWorkflow: vi.fn(),
}));

const RESULTS = normalizeResults({
  experimentId: 'exp-overview',
  question: 'How does reduced market-making capacity change simulated liquidity?',
  questionZh: '做市能力下降如何改变模拟流动性？',
  scenarioDiff: {
    parameter: 'marketMakerCapacity',
    baselineValue: 1,
    interventionValue: 0.45,
  },
  primaryOutcome: 'maxSpreadBps',
  pairedRuns: [
    { seed: 101, baseline: { maxSpreadBps: 10 }, intervention: { maxSpreadBps: 16 }, delta: { maxSpreadBps: 6 } },
    { seed: 102, baseline: { maxSpreadBps: 12 }, intervention: { maxSpreadBps: 19 }, delta: { maxSpreadBps: 7 } },
  ],
  metricSummaries: {
    maxSpreadBps: {
      baseline: { median: 11, interval95: { lower: 10, upper: 12 } },
      intervention: { median: 17.5, interval95: { lower: 16, upper: 19 } },
      delta: {
        median: 6.5,
        interval95: { lower: 6, upper: 7 },
        validN: 2,
      },
    },
  },
  medianPaths: {
    step: [0, 1],
    baseline: { price: [100, 99], spreadBps: [10, 11], depth: [300, 285] },
    intervention: { price: [100, 97], spreadBps: [11, 18], depth: [285, 220] },
  },
  agentFlows: {
    MARKET_MAKER: {
      baseline: { netVolume: 4 },
      intervention: { netVolume: -8 },
    },
  },
  stoppingRule: {
    mode: 'FIXED_PAIR_COUNT',
    reason: 'FIXED_PAIR_COUNT_REACHED',
    completedPairs: 10,
  },
  cognition: {
    requestedMode: 'RULE_ONLY',
    resolvedMode: 'RULE_ONLY',
    decisions: [],
  },
  limitations: [{ text: 'Synthetic scenario analysis only.', textZh: '仅用于合成情景分析。' }],
  manifest: {
    generatedAt: '2026-07-22T18:00:00Z',
    validPairedSeeds: 10,
    engineVersion: 'eventshock-simulation-0.2.0',
    schemaVersion: '2.0.0',
  },
  eventPackManifest: {
    id: 'pack-spacex',
    title: 'SpaceX event pack',
    titleZh: 'SpaceX 事件包',
    sources: [{ sourceId: 'source-one' }, { sourceId: 'source-two' }],
    claims: [{ claimId: 'claim-one' }],
  },
});

describe('ResultsPage 结果证据导航', () => {
  const navigate = vi.fn<Navigate>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    });
    vi.mocked(useWorkflow).mockReturnValue({
      activeExperiment: {
        id: 'exp-overview',
        eventPackId: 'pack-spacex',
        status: 'COMPLETED',
        progress: 100,
        logs: [],
        scenario: {
          eventPackId: 'pack-spacex',
          question: 'How does reduced market-making capacity change simulated liquidity?',
          intervention: {
            parameter: 'marketMakerCapacity',
            baselineValue: 1,
            interventionValue: 0.45,
          },
          seedCount: 10,
          populationSize: 56,
          steps: 120,
          primaryOutcome: 'maxSpreadBps',
          secondaryOutcomes: [],
          acknowledgedScenarioNotForecast: true,
          acknowledgedSyntheticAssumptions: true,
        },
      },
      experiments: [],
      results: RESULTS,
      resultsState: 'success',
      resultsError: undefined,
      loadResults: vi.fn(),
      selectExperiment: vi.fn(),
      invalidateActiveExperiment: vi.fn(),
    } as unknown as ReturnType<typeof useWorkflow>);
  });

  it('没有叙事报告时仍显示稳定概览、认知决策与版本来源锚点', () => {
    render(<I18nProvider><ResultsPage navigate={navigate} /></I18nProvider>);

    expect(screen.getByRole('heading', { name: 'Before reading the numbers' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'What these results are' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'What these results are not' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'What you can do with them' })).toBeInTheDocument();
    expect(screen.getByText('what a person should buy, sell, hold, or short')).toBeInTheDocument();
    expect(screen.getByText('a real target price, return, or loss limit')).toBeInTheDocument();
    expect(screen.getAllByTestId('simulated-chart')).toHaveLength(4);
    expect(screen.getByRole('img', { name: /SIMULATED DATA: Paired seed differences/ })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /SIMULATED DATA: Median market paths/ })).toBeInTheDocument();

    const overview = screen.getByRole('heading', { level: 2, name: 'Experiment overview' });
    expect(overview).toHaveAttribute('id', 'result-overview-heading');
    expect(screen.getByText('How does reduced market-making capacity change simulated liquidity?')).toBeInTheDocument();
    expect(screen.getByText('Market maker inventory capacity: 1 → 0.45')).toBeInTheDocument();

    expect(screen.getByRole('heading', { name: 'Representative cognition decisions' }))
      .toHaveAttribute('id', 'cognition-decisions-heading');

    const manifestHeading = screen.getByRole('heading', { level: 2, name: 'Versions and provenance' });
    expect(manifestHeading).toHaveAttribute('id', 'result-manifest-heading');
    const manifest = manifestHeading.closest('section');
    if (!manifest) throw new Error('版本与来源区域未渲染。');
    expect(within(manifest).getByText('pack-spacex')).toBeInTheDocument();
    expect(within(manifest).getByText('SpaceX event pack')).toBeInTheDocument();
    expect(within(manifest).getByText('eventshock-simulation-0.2.0')).toBeInTheDocument();
    expect(within(manifest).getByText('2 sources / 1 claims')).toBeInTheDocument();
  });

  it('从结果页打开机制链路时携带实验和目标锚点', async () => {
    const user = userEvent.setup();
    render(<I18nProvider><ResultsPage navigate={navigate} /></I18nProvider>);

    await user.click(screen.getByRole('button', { name: 'Mechanism Trace' }));

    expect(navigate).toHaveBeenCalledWith('trace', {
      experimentId: 'exp-overview',
      target: 'trace-timeline-heading',
    });
  }, 20_000);
});
