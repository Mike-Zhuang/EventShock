import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Navigate } from '../app';
import { normalizeResults } from '../api/normalize';
import { I18nProvider } from '../i18n';
import { useWorkflow } from '../state/workflow-context';
import { ResultsPage } from './results-page';

vi.mock('../components/result-interpretation-assistant', () => ({
  ResultInterpretationAssistant: ({
    onCreateExperimentDraft,
  }: {
    onCreateExperimentDraft?: (suggestion: string) => void;
  }) => (
    <section aria-label="Result interpretation assistant">
      {onCreateExperimentDraft ? (
        <button
          type="button"
          onClick={() => onCreateExperimentDraft('What changes with 50 matched seeds?')}
        >
          Mock create experiment draft
        </button>
      ) : null}
    </section>
  ),
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
  strongestMetricIds: ['maxSpreadBps'],
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

function workflowValue(results = RESULTS): ReturnType<typeof useWorkflow> {
  return {
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
    results,
    resultsState: 'success',
    resultsError: undefined,
    loadResults: vi.fn(),
    selectExperiment: vi.fn(),
    setScenario: vi.fn(),
    createAndStartExperiment: vi.fn(),
    invalidateActiveExperiment: vi.fn(),
  } as unknown as ReturnType<typeof useWorkflow>;
}

describe('ResultsPage 结果证据导航', () => {
  const navigate = vi.fn<Navigate>();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    });
    vi.mocked(useWorkflow).mockReturnValue(workflowValue());
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
    expect(screen.getByRole('heading', { name: 'Strongest supported findings' }))
      .toBeInTheDocument();
    expect(screen.getAllByText('Median paired difference').length).toBeGreaterThan(0);
    expect(screen.getByText('View full seeds for short labels')).toBeInTheDocument();
    expect(screen.getByText('Seed 1')).toBeInTheDocument();
    expect(
      screen.getAllByText('Reached the fixed matched-pair count').length,
    ).toBeGreaterThan(0);
  });

  it('describes simultaneous stopping without claiming sample savings and exposes full-seed copy', async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    vi.mocked(useWorkflow).mockReturnValue(workflowValue({
      ...RESULTS,
      stoppingRule: {
        mode: 'TARGET_CI_HALF_WIDTH',
        triggered: true,
        reason: 'MAXIMUM_PAIRS_REACHED',
        primaryReason: 'MAXIMUM_PAIRS_REACHED',
        reasons: ['MAXIMUM_PAIRS_REACHED', 'TARGET_CI_HALF_WIDTH_REACHED'],
        primaryOutcome: 'maxSpreadBps',
        completedPairs: 10,
        minimumPairs: 10,
        maximumPairs: 10,
        conditionEvaluations: [
          {
            code: 'MINIMUM_PAIRS_REACHED',
            evaluationOrder: 1,
            satisfied: true,
            firstSatisfiedAtPair: 10,
          },
          {
            code: 'MAXIMUM_PAIRS_REACHED',
            evaluationOrder: 2,
            satisfied: true,
            firstSatisfiedAtPair: 10,
          },
          {
            code: 'TARGET_CI_HALF_WIDTH_REACHED',
            evaluationOrder: 3,
            satisfied: true,
            firstSatisfiedAtPair: 10,
          },
        ],
      },
      narrativeReport: {
        schemaVersion: 'deterministic_report_v1.0.0',
        headline: 'Scenario summary',
        summary: 'Bounded summary.',
        interpretationBoundary: 'Synthetic scenario only.',
        generatedBy: 'DETERMINISTIC_TEMPLATE',
      },
    }));

    render(<I18nProvider><ResultsPage navigate={navigate} /></I18nProvider>);

    expect(screen.getAllByText(
      'Completed the preset 10 pairs; the target interval condition was met at the same time',
    ).length).toBeGreaterThan(0);
    expect(screen.queryByText(/saved samples|stopped early/i)).not.toBeInTheDocument();
    expect(screen.getAllByText('Deterministic result summary').length).toBeGreaterThan(0);
    const manifest = screen.getByRole('heading', { name: 'Versions and provenance' })
      .closest('section');
    if (!manifest) throw new Error('版本与来源区域未渲染。');
    expect(within(manifest).getByText('DETERMINISTIC_TEMPLATE')).toBeInTheDocument();
    expect(within(manifest).getByText('deterministic_report_v1.0.0')).toBeInTheDocument();

    await user.click(screen.getByRole('button', {
      name: 'Copy the full value for Seed 1',
    }));
    expect(writeText).toHaveBeenCalledWith('101');
  });

  it('limits first-screen metric cards and expands the remaining metrics on demand', async () => {
    const user = userEvent.setup();
    const extraMetrics = Array.from({ length: 7 }, (_, index) => ({
      id: `extraMetric${index + 1}`,
      label: `EXTRA_METRIC_${index + 1}`,
      unit: 'count' as const,
      baseline: index,
      intervention: index + 1,
      delta: 1,
      ciLow: -1,
      ciHigh: 2,
      n: 10,
    }));
    vi.mocked(useWorkflow).mockReturnValue(workflowValue({
      ...RESULTS,
      metrics: [...RESULTS.metrics, ...extraMetrics],
    }));

    render(<I18nProvider><ResultsPage navigate={navigate} /></I18nProvider>);

    const metricsHeading = screen.getByRole('heading', { name: 'Primary metrics' });
    const metricsSection = metricsHeading.closest('section');
    if (!metricsSection) throw new Error('指标区域未渲染。');
    expect(within(metricsSection).getAllByRole('article')).toHaveLength(6);

    await user.click(screen.getByRole('button', { name: 'Show 2 more metrics' }));
    expect(within(metricsSection).getAllByRole('article')).toHaveLength(8);
  });

  it('uses backend strongest order and filters cognition, microstructure, and risk groups', async () => {
    const user = userEvent.setup();
    const groupedMetrics = [
      {
        ...RESULTS.metrics[0],
        id: 'maxSpreadBps',
        label: 'MAX_SPREAD_BPS',
      },
      {
        ...RESULTS.metrics[0],
        id: 'minDepth',
        label: 'MIN_DEPTH',
        delta: -15,
      },
      {
        ...RESULTS.metrics[0],
        id: 'cognitionRiskBlockedCount',
        label: 'COGNITION_RISK_BLOCKED_COUNT',
        delta: 1,
        ciLow: -1,
        ciHigh: 2,
      },
      {
        ...RESULTS.metrics[0],
        id: 'cognitionOrderEffectRate',
        label: 'COGNITION_ORDER_EFFECT_RATE',
        delta: 0.2,
        ciLow: 0,
        ciHigh: 0,
      },
      {
        ...RESULTS.metrics[0],
        id: 'maxDrawdownPct',
        label: 'MAX_DRAWDOWN_PCT',
        delta: 0.4,
        ciLow: -0.5,
        ciHigh: 1,
      },
    ];
    vi.mocked(useWorkflow).mockReturnValue(workflowValue({
      ...RESULTS,
      metrics: groupedMetrics,
      strongestMetricIds: ['minDepth', 'maxSpreadBps'],
    }));

    render(<I18nProvider><ResultsPage navigate={navigate} /></I18nProvider>);

    const strongestHeading = screen.getByRole('heading', { name: 'Strongest supported findings' });
    const strongestSection = strongestHeading.closest('section');
    if (!strongestSection) throw new Error('最强结果区域未渲染。');
    const strongestItems = within(strongestSection).getAllByRole('listitem');
    expect(strongestItems[0]).toHaveTextContent('Minimum market depth');
    expect(strongestItems[1]).toHaveTextContent('Peak spread');
    expect(strongestSection).toHaveTextContent('The frontend does not rescore it');
    const readingGuideHeading = screen.getByRole('heading', { name: 'Before reading the numbers' });
    expect(
      strongestHeading.compareDocumentPosition(readingGuideHeading)
      & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    const filter = screen.getByLabelText('Filter metrics');
    const metricsSection = screen.getByRole('heading', { name: 'Primary metrics' }).closest('section');
    if (!metricsSection) throw new Error('指标区域未渲染。');

    await user.selectOptions(filter, 'primary');
    expect(within(metricsSection).getAllByRole('article')).toHaveLength(1);
    expect(metricsSection).toHaveTextContent('Peak spread');

    await user.selectOptions(filter, 'supported');
    expect(within(metricsSection).getAllByRole('article')).toHaveLength(2);
    expect(metricsSection).toHaveTextContent('Peak spread');
    expect(metricsSection).toHaveTextContent('Minimum market depth');

    await user.selectOptions(filter, 'cognition');
    expect(within(metricsSection).getAllByRole('article')).toHaveLength(2);
    expect(metricsSection).toHaveTextContent('Cognition actions blocked by risk');
    expect(metricsSection).toHaveTextContent('Cognition order-effect rate');

    await user.selectOptions(filter, 'microstructure');
    expect(within(metricsSection).getAllByRole('article')).toHaveLength(2);
    expect(metricsSection).toHaveTextContent('Peak spread');
    expect(metricsSection).toHaveTextContent('Minimum market depth');

    await user.selectOptions(filter, 'risk');
    expect(within(metricsSection).getAllByRole('article')).toHaveLength(1);
    expect(metricsSection).toHaveTextContent('Maximum drawdown');
  });

  it('creates a not-run prefilled scenario draft without starting an experiment', async () => {
    const user = userEvent.setup();
    const workflow = workflowValue();
    vi.mocked(useWorkflow).mockReturnValue(workflow);

    render(<I18nProvider><ResultsPage navigate={navigate} /></I18nProvider>);
    await user.click(screen.getByRole('button', { name: 'Mock create experiment draft' }));

    expect(workflow.setScenario).toHaveBeenCalledWith(expect.objectContaining({
      seedCount: 50,
      question: 'Follow-up experiment draft (not run): What changes with 50 matched seeds?',
      acknowledgedScenarioNotForecast: false,
      acknowledgedSyntheticAssumptions: false,
    }));
    expect(navigate).toHaveBeenCalledWith('scenario');
    expect(workflow.createAndStartExperiment).not.toHaveBeenCalled();
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
