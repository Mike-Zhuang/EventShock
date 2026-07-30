import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { I18nProvider } from '../i18n';
import { useWorkflow } from '../state/workflow-context';
import { ExportHistoryPage } from './export-history-page';

vi.mock('../state/workflow-context', () => ({
  useWorkflow: vi.fn(),
}));

describe('ExportHistoryPage 账号历史筛选', () => {
  const exportExperiment = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    vi.mocked(useWorkflow).mockReturnValue({
      cases: [
        {
          id: 'case-liquidity',
          eventPackId: 'pack-liquidity',
          name: 'Liquidity withdrawal event',
          nameZh: '流动性撤出事件',
        },
        {
          id: 'case-latency',
          eventPackId: 'pack-latency',
          name: 'Information latency event',
          nameZh: '信息延迟事件',
        },
      ],
      experiments: [
        {
          id: 'experiment-liquidity',
          eventPackId: 'pack-liquidity',
          status: 'COMPLETED',
          progress: 100,
          logs: [],
          createdAt: '2026-07-20T10:00:00Z',
          updatedAt: '2026-07-20T11:00:00Z',
          scenario: {
            eventPackId: 'pack-liquidity',
            question: 'How does liquidity change?',
            questionZh: '流动性变化会如何影响结果？',
            intervention: {
              parameter: 'marketMakerCapacity',
              baselineValue: 1,
              interventionValue: 0.5,
            },
            seedCount: 10,
            populationSize: 56,
            steps: 120,
            llmPolicy: {
              mode: 'RULE_ONLY',
            },
            acknowledgedScenarioNotForecast: true,
            acknowledgedSyntheticAssumptions: true,
          },
        },
        {
          id: 'experiment-latency',
          eventPackId: 'pack-latency',
          status: 'FAILED_FINAL',
          progress: 20,
          logs: [],
          createdAt: '2026-07-21T10:00:00Z',
          updatedAt: '2026-07-21T10:05:00Z',
          scenario: {
            eventPackId: 'pack-latency',
            question: 'How does information latency change?',
            questionZh: '信息延迟变化会如何影响结果？',
            intervention: {
              parameter: 'informationLatency',
              baselineValue: 0,
              interventionValue: 5,
            },
            seedCount: 10,
            populationSize: 56,
            steps: 120,
            llmPolicy: {
              mode: 'HYBRID_LLM',
              provider: 'zhipu',
              modelId: 'glm-5.2',
              representativeAgentCount: 8,
              decisionIntervalSteps: 12,
              callBudget: 24,
              maxCostUsd: 3,
              fallbackToRules: true,
            },
            acknowledgedScenarioNotForecast: true,
            acknowledgedSyntheticAssumptions: true,
          },
        },
      ],
      experimentsState: 'success',
      activeExperiment: undefined,
      selectExperiment: vi.fn(),
      loadResults: vi.fn(),
      exportExperiment,
    } as unknown as ReturnType<typeof useWorkflow>);
  });

  it('prioritizes event titles and research questions, then filters by friendly search and status', async () => {
    const user = userEvent.setup();
    render(<I18nProvider><ExportHistoryPage navigate={vi.fn()} /></I18nProvider>);

    expect(screen.getByText('Current-account experiment history and retention'))
      .toBeInTheDocument();
    expect(screen.queryByText(/anonymous browser session/i)).not.toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /Updated \(.+\)/ })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Event and research question' }))
      .toBeInTheDocument();
    expect(screen.getByText('Liquidity withdrawal event')).toBeInTheDocument();
    expect(screen.getByText('How does liquidity change?')).toBeInTheDocument();

    const search = screen.getByLabelText(
      'Search event, question, intervention, or experiment ID',
    );
    await user.type(search, 'Liquidity withdrawal event');
    const table = screen.getByRole('table');
    expect(within(table).getByText('experiment-liquidity')).toBeInTheDocument();
    expect(within(table).queryByText('experiment-latency')).not.toBeInTheDocument();

    await user.clear(search);
    await user.selectOptions(screen.getByLabelText('Experiment status'), 'FAILED_FINAL');
    expect(within(table).getByText('experiment-latency')).toBeInTheDocument();
    expect(within(table).queryByText('experiment-liquidity')).not.toBeInTheDocument();
  });

  it('combines updated-date, requested-model, and intervention filters without leaving account scope', async () => {
    const user = userEvent.setup();
    render(<I18nProvider><ExportHistoryPage navigate={vi.fn()} /></I18nProvider>);
    const table = screen.getByRole('table');

    await user.selectOptions(
      screen.getByLabelText('Requested model'),
      'HYBRID_LLM::zhipu::glm-5.2',
    );
    expect(within(table).getByText('experiment-latency')).toBeInTheDocument();
    expect(within(table).queryByText('experiment-liquidity')).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Requested model'), 'all');
    await user.selectOptions(
      screen.getByLabelText('Intervention parameter'),
      'marketMakerCapacity',
    );
    expect(within(table).getByText('experiment-liquidity')).toBeInTheDocument();
    expect(within(table).queryByText('experiment-latency')).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Intervention parameter'), 'all');
    fireEvent.change(screen.getByLabelText('Updated from'), {
      target: { value: '2026-07-21' },
    });
    expect(within(table).getByText('experiment-latency')).toBeInTheDocument();
    expect(within(table).queryByText('experiment-liquidity')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(within(table).getByText('experiment-liquidity')).toBeInTheDocument();
    expect(within(table).getByText('experiment-latency')).toBeInTheDocument();
  });

  it('exports completed runs as reproducibility bundles and fails closed for diagnostics', async () => {
    const user = userEvent.setup();
    exportExperiment.mockResolvedValue(undefined);
    render(<I18nProvider><ExportHistoryPage navigate={vi.fn()} /></I18nProvider>);

    expect(screen.getByText('Failed experiments require a diagnostic bundle'))
      .toBeInTheDocument();
    expect(screen.getByText(/does not yet provide a valid failed-run diagnostic ZIP/))
      .toBeInTheDocument();

    const completedRow = screen.getByText('experiment-liquidity').closest('tr');
    const failedRow = screen.getByText('experiment-latency').closest('tr');
    expect(completedRow).not.toBeNull();
    expect(failedRow).not.toBeNull();

    const completedExport = within(completedRow as HTMLTableRowElement).getByRole(
      'button',
      { name: 'Export full reproducibility bundle' },
    );
    expect(completedExport).toBeEnabled();
    expect(within(completedRow as HTMLTableRowElement).getByText(
      'eventshock-reproducibility-experiment-liquidity.zip',
    )).toBeInTheDocument();

    const diagnosticExport = within(failedRow as HTMLTableRowElement).getByRole(
      'button',
      { name: 'Diagnostic bundle' },
    );
    expect(diagnosticExport).toBeDisabled();
    expect(within(failedRow as HTMLTableRowElement).getByText(
      /current backend has no failed-run diagnostic bundle endpoint/i,
    )).toBeInTheDocument();

    await user.click(completedExport);
    expect(exportExperiment).toHaveBeenCalledOnce();
    expect(exportExperiment).toHaveBeenCalledWith('experiment-liquidity');
  });

  it('provides equivalent Simplified Chinese history and diagnostic-package boundaries', () => {
    window.localStorage.setItem('eventshock-language', 'zh-CN');
    render(<I18nProvider><ExportHistoryPage navigate={vi.fn()} /></I18nProvider>);

    expect(screen.getByRole('columnheader', { name: '事件与研究问题' }))
      .toBeInTheDocument();
    expect(screen.getByText('流动性撤出事件')).toBeInTheDocument();
    expect(screen.getByText('流动性变化会如何影响结果？')).toBeInTheDocument();
    expect(screen.getByText('失败实验只应生成诊断包')).toBeInTheDocument();
    expect(screen.getByLabelText('请求的模型')).toBeInTheDocument();
    expect(screen.getByLabelText('干预参数')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '诊断包' })).toBeDisabled();
    expect(screen.getByText(/当前后端没有失败实验诊断包接口/)).toBeInTheDocument();
  });
});
