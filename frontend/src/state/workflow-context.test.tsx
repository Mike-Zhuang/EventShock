import { act, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type { Experiment, ExperimentResults } from '../api/types';
import { useWorkflow, WorkflowProvider } from './workflow-context';

vi.mock('../api/client', () => ({
  api: {
    getHealth: vi.fn(async () => ({ status: 'ok' })),
    getCases: vi.fn(async () => []),
    getExperiments: vi.fn(async () => []),
    getExperiment: vi.fn(),
    getResults: vi.fn(),
    createExperiment: vi.fn(),
    startExperiment: vi.fn(),
    streamExperiment: vi.fn(async () => undefined),
  },
}));

function emptyResults(experimentId: string): ExperimentResults {
  return {
    experimentId,
    metrics: [],
    pairedSeeds: [],
    distribution: [],
    marketPaths: [],
    agentFlows: [],
    agentPnl: [],
    traces: [],
    limitations: [],
    limitationsZh: [],
    modelVersions: {},
    dataVersions: {},
    pairedSeries: {},
  };
}

function completedExperiment(id: string): Experiment {
  return {
    id,
    eventPackId: `pack-${id}`,
    status: 'COMPLETED',
    progress: 100,
    logs: [],
  };
}

describe('工作流实验与结果归属', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('启动新实验后清除旧结果，并忽略旧实验迟到的结果响应', async () => {
    let workflow!: ReturnType<typeof useWorkflow>;
    let resolveOldResults!: (results: ExperimentResults) => void;
    const oldResults = new Promise<ExperimentResults>((resolve) => {
      resolveOldResults = resolve;
    });
    vi.mocked(api.getExperiment).mockResolvedValue({
      id: 'exp-old',
      eventPackId: 'pack-old',
      status: 'COMPLETED',
      progress: 100,
      logs: [],
    });
    vi.mocked(api.getResults).mockReturnValue(oldResults);
    vi.mocked(api.createExperiment).mockResolvedValue({
      id: 'exp-new',
      eventPackId: 'pack-new',
      status: 'READY',
      progress: 0,
      logs: [],
    });
    vi.mocked(api.startExperiment).mockResolvedValue({
      id: 'exp-new',
      eventPackId: 'pack-new',
      status: 'QUEUED',
      progress: 0,
      logs: [],
    });

    function Harness() {
      workflow = useWorkflow();
      return (
        <output data-testid="workflow-state">
          {workflow.activeExperiment?.id ?? 'none'}|{workflow.results?.experimentId ?? 'none'}
        </output>
      );
    }

    render(<WorkflowProvider><Harness /></WorkflowProvider>);
    await waitFor(() => expect(api.getExperiments).toHaveBeenCalled());
    await act(async () => {
      await workflow.selectExperiment('exp-old');
    });

    let oldRequest!: Promise<ExperimentResults | undefined>;
    act(() => {
      oldRequest = workflow.loadResults('exp-old');
    });
    await act(async () => {
      await workflow.createAndStartExperiment();
    });
    expect(screen.getByTestId('workflow-state')).toHaveTextContent('exp-new|none');

    resolveOldResults(emptyResults('exp-old'));
    await act(async () => {
      await oldRequest;
    });
    expect(screen.getByTestId('workflow-state')).toHaveTextContent('exp-new|none');
  });

  it('并发选择实验时只提交最后一次选择，并拒绝为非活动实验加载结果', async () => {
    let workflow!: ReturnType<typeof useWorkflow>;
    let resolveFirst!: (experiment: Experiment) => void;
    let resolveSecond!: (experiment: Experiment) => void;
    const firstResponse = new Promise<Experiment>((resolve) => {
      resolveFirst = resolve;
    });
    const secondResponse = new Promise<Experiment>((resolve) => {
      resolveSecond = resolve;
    });
    vi.mocked(api.getExperiment).mockImplementation((experimentId) => {
      if (experimentId === 'exp-first') return firstResponse;
      if (experimentId === 'exp-second') return secondResponse;
      throw new Error(`Unexpected experiment: ${experimentId}`);
    });

    function Harness() {
      workflow = useWorkflow();
      return (
        <output data-testid="workflow-state">
          {workflow.activeExperiment?.id ?? 'none'}|{workflow.results?.experimentId ?? 'none'}
        </output>
      );
    }

    render(<WorkflowProvider><Harness /></WorkflowProvider>);
    await waitFor(() => expect(api.getExperiments).toHaveBeenCalled());

    let firstRequest!: Promise<Experiment | undefined>;
    let secondRequest!: Promise<Experiment | undefined>;
    act(() => {
      firstRequest = workflow.selectExperiment('exp-first');
      secondRequest = workflow.selectExperiment('exp-second');
    });

    let secondResult: Experiment | undefined;
    await act(async () => {
      resolveSecond(completedExperiment('exp-second'));
      secondResult = await secondRequest;
    });
    expect(secondResult?.id).toBe('exp-second');
    expect(screen.getByTestId('workflow-state')).toHaveTextContent('exp-second|none');

    let firstResult: Experiment | undefined;
    await act(async () => {
      resolveFirst(completedExperiment('exp-first'));
      firstResult = await firstRequest;
    });
    expect(firstResult).toBeUndefined();
    expect(screen.getByTestId('workflow-state')).toHaveTextContent('exp-second|none');

    let staleResults: ExperimentResults | undefined;
    await act(async () => {
      staleResults = await workflow.loadResults('exp-first');
    });
    expect(staleResults).toBeUndefined();
    expect(api.getResults).not.toHaveBeenCalled();
  });

  it('过期的实验选择失败时不抛出错误，也不覆盖当前选择', async () => {
    let workflow!: ReturnType<typeof useWorkflow>;
    let rejectFirst!: (reason: Error) => void;
    const firstResponse = new Promise<Experiment>((_resolve, reject) => {
      rejectFirst = reject;
    });
    vi.mocked(api.getExperiment)
      .mockReturnValueOnce(firstResponse)
      .mockResolvedValueOnce(completedExperiment('exp-current'));

    function Harness() {
      workflow = useWorkflow();
      return (
        <output data-testid="workflow-state">
          {workflow.activeExperiment?.id ?? 'none'}|{workflow.experimentsError ?? 'no-error'}
        </output>
      );
    }

    render(<WorkflowProvider><Harness /></WorkflowProvider>);
    await waitFor(() => expect(api.getExperiments).toHaveBeenCalled());

    let staleRequest!: Promise<Experiment | undefined>;
    await act(async () => {
      staleRequest = workflow.selectExperiment('exp-stale');
      await workflow.selectExperiment('exp-current');
    });
    await act(async () => {
      rejectFirst(new Error('stale request failed'));
      await expect(staleRequest).resolves.toBeUndefined();
    });

    expect(screen.getByTestId('workflow-state')).toHaveTextContent('exp-current|no-error');
  });
});
