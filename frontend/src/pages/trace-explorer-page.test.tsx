import { render, screen } from '@testing-library/react';
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
    vi.mocked(useWorkflow).mockReturnValue({
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
});
