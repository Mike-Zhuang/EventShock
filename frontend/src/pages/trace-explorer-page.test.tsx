import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { I18nProvider } from '../i18n';
import { useWorkflow } from '../state/workflow-context';
import { TraceExplorerPage } from './trace-explorer-page';

vi.mock('../state/workflow-context', () => ({
  useWorkflow: vi.fn(),
}));

describe('TraceExplorerPage 稳定目标', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    vi.mocked(useWorkflow).mockReturnValue({
      activeExperiment: {
        id: 'exp-with-trace',
        eventPackId: 'pack-1',
        status: 'COMPLETED',
        progress: 1,
        logs: [],
        scenario: {
          eventPackId: 'pack-1',
          intervention: {
            parameter: 'marketMakerCapacity',
            baselineValue: 1,
            interventionValue: 0.8,
          },
          seedCount: 10,
          populationSize: 100,
          steps: 100,
          market: {
            instrumentId: 'SYNTH-1',
            benchmarkId: 'SYNTH-BENCH',
            tickSize: 0.01,
            initialPrice: 100,
            feeBps: 1,
            latencyMs: 1,
            openingAuction: true,
            volatilityHalt: true,
            priceCollarBps: 500,
          },
        },
      },
      results: {
        experimentId: 'exp-without-trace',
        metrics: [],
        pairedSeeds: [],
        distribution: [],
        marketPaths: [],
        agentFlows: [],
        agentPnl: [],
        traces: [],
        pairedSeries: {},
        limitations: [],
        limitationsZh: [],
        modelVersions: {},
        dataVersions: {},
      },
    } as unknown as ReturnType<typeof useWorkflow>);
  });

  it('没有链路数据时仍保留可聚焦标题并明确说明空状态', () => {
    render(<I18nProvider><TraceExplorerPage /></I18nProvider>);

    expect(screen.getByRole('heading', { level: 2, name: 'Mechanism timeline' }))
      .toHaveAttribute('id', 'trace-timeline-heading');
    expect(screen.getByText(/no available trace/i)).toBeInTheDocument();
  });

  it('uses bilingual event, agent, scenario, and payload catalogs with friendly fallbacks', async () => {
    vi.mocked(useWorkflow).mockReturnValue({
      activeExperiment: {
        scenario: {
          market: { tickSize: 0.01 },
        },
      },
      results: {
        experimentId: 'exp-with-trace',
        metrics: [],
        pairedSeeds: [],
        distribution: [],
        marketPaths: [],
        agentFlows: [],
        agentPnl: [],
        traces: [
          {
            id: 'trace-trade',
            globalSequence: 42,
            step: 11,
            phase: 'TRADE',
            phaseSequence: 2,
            time: '2026-07-29T20:15:30Z',
            kind: 'TRADE_EXECUTED',
            title: 'TRADE_EXECUTED',
            scenario: 'intervention',
            agentId: 'agent-1',
            sourceLayer: 'DETERMINISTIC_MARKET_MECHANISM',
            isInterventionDifference: true,
            payload: {
              agentType: 'deleveraging',
              side: 'SELL',
              requestedQuantity: 12,
              priceTicks: 9_875,
              customInternal: 'legacy',
            },
          },
          {
            id: 'trace-unknown',
            kind: 'MYSTERY_ENUM',
            title: 'MYSTERY_ENUM',
            scenario: 'baseline',
          },
        ],
        orderExecutionSummary: [{
          orderId: 'order-1',
          orderTraceId: 'trace-trade',
          agentId: 'agent-1',
          side: 'SELL',
          submissionStep: 11,
          submissionSequence: 7,
          requestedQuantity: 12,
          approvedQuantity: 10,
          cumulativeFilledQuantity: 7,
          remainingQuantity: 3,
          vwapPrice: 98.75,
          fillCount: 2,
          tradeIds: ['trade-1', 'trade-2'],
          tradeTraceIds: ['trace-trade-1', 'trace-trade-2'],
          riskDecision: 'MODIFY',
          finalStatus: 'PARTIALLY_FILLED_AT_SIMULATION_END',
          scenario: 'intervention',
          isInterventionDifference: true,
        }],
        pairedSeries: {},
        limitations: [],
        limitationsZh: [],
        modelVersions: {},
        dataVersions: {},
      },
    } as unknown as ReturnType<typeof useWorkflow>);

    render(<I18nProvider><TraceExplorerPage /></I18nProvider>);

    expect(await screen.findAllByText('Trade executed')).not.toHaveLength(0);
    expect(screen.getAllByText('Unknown event (MYSTERY_ENUM)').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Intervention').length).toBeGreaterThan(0);
    const tradeButton = screen.getAllByRole('button').find(
      (button) => button.textContent?.includes('Trade executed'),
    );
    expect(tradeButton).toBeDefined();
    fireEvent.click(tradeButton!);
    expect(screen.getAllByText('Deleveraging trader').length).toBeGreaterThan(0);
    const agentIdentity = screen.getByText('agent-1').closest('.trace-agent-identity');
    expect(agentIdentity).not.toBeNull();
    expect(agentIdentity?.children).toHaveLength(2);
    expect(agentIdentity?.children[0]).toHaveTextContent('agent-1');
    expect(agentIdentity?.children[1]).toHaveTextContent('Deleveraging trader');
    expect(screen.getByText('Order side')).toBeInTheDocument();
    expect(screen.getAllByText('Sell').length).toBeGreaterThan(0);
    expect(screen.getByText('Requested quantity')).toBeInTheDocument();
    expect(screen.getByText('Synthetic trade price')).toBeInTheDocument();
    expect(screen.getByText('98.75 (raw: 9,875 ticks)')).toBeInTheDocument();
    expect(screen.getByText('Other field (customInternal)')).toBeInTheDocument();
    expect(screen.getByText('Global sequence')).toBeInTheDocument();
    expect(screen.getByText('Trade · phase sequence 2')).toBeInTheDocument();
    expect(screen.getAllByText('Deterministic market mechanism').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Intervention difference').length).toBeGreaterThan(0);
    expect(screen.getByRole('heading', { name: 'Representative-path order execution' }))
      .toBeInTheDocument();
    expect(screen.getByText('12 / 10')).toBeInTheDocument();
    expect(screen.getByText('7 / 3')).toBeInTheDocument();
    expect(screen.getByText(/Modified by risk control · Partially filled at simulation end/))
      .toBeInTheDocument();
    expect(screen.getByText('Event time (UTC)')).toBeInTheDocument();
    expect(screen.getByText('2026-07-29T20:15:30.000Z')).toBeInTheDocument();
  });

  it('不会把孤立的 arbitrage 内部枚举泄漏到中英文页面文本', async () => {
    vi.mocked(useWorkflow).mockReturnValue({
      results: {
        experimentId: 'exp-arbitrage-trace',
        metrics: [],
        pairedSeeds: [],
        distribution: [],
        marketPaths: [],
        agentFlows: [],
        agentPnl: [],
        traces: [{
          id: 'trace-arbitrage',
          kind: 'OBSERVATION_CREATED',
          title: 'OBSERVATION_CREATED',
          scenario: 'baseline',
          agentId: 'agent-42',
          payload: { agentType: 'arbitrage' },
        }],
        pairedSeries: {},
        limitations: [],
        limitationsZh: [],
        modelVersions: {},
        dataVersions: {},
      },
    } as unknown as ReturnType<typeof useWorkflow>);

    const english = render(<I18nProvider><TraceExplorerPage /></I18nProvider>);
    expect(await screen.findAllByText('Cross-signal arbitrageur')).not.toHaveLength(0);
    expect(english.container.textContent).not.toMatch(/\barbitrage\b/i);
    english.unmount();

    window.localStorage.setItem('eventshock-language', 'zh-CN');
    const chinese = render(<I18nProvider><TraceExplorerPage /></I18nProvider>);
    expect(await screen.findAllByText('跨信号套利者')).not.toHaveLength(0);
    expect(chinese.container.textContent).not.toMatch(/\barbitrage\b/i);
  });
});
