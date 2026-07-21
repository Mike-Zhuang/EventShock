import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from './api/client';
import { App, buildAppHash, parseAppRoute } from './app';

vi.mock('./api/client', () => ({
  api: {
    getHealth: vi.fn(async () => ({ status: 'ok' })),
    getCases: vi.fn(async () => []),
    getExperiments: vi.fn(async () => []),
    getExperiment: vi.fn(),
    getResults: vi.fn(),
  },
}));

describe('移动主导航', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.history.replaceState(null, '', '#/cases');
    document.body.style.overflow = '';
    vi.stubGlobal('scrollTo', vi.fn());
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    });
    vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
      matches: query === '(max-width: 920px)',
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    vi.clearAllMocks();
  });

  it('在结果深链中保留 experimentId，并可解析刷新路由', () => {
    const hash = buildAppHash('results', 'exp-history/with space');

    expect(hash).toBe('#/results?experimentId=exp-history%2Fwith+space');
    expect(parseAppRoute(hash)).toEqual({
      view: 'results',
      experimentId: 'exp-history/with space',
    });
  });

  it('刷新带 experimentId 的结果深链时恢复实验与结果', async () => {
    const experimentId = 'exp-history-restore';
    vi.mocked(api.getExperiment).mockResolvedValue({
      id: experimentId,
      eventPackId: 'pack-history',
      status: 'COMPLETED',
      progress: 100,
      logs: [],
    });
    vi.mocked(api.getResults).mockResolvedValue({
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
    });
    window.history.replaceState(null, '', buildAppHash('results', experimentId));

    render(<App />);

    await waitFor(() => expect(api.getExperiment).toHaveBeenCalledWith(experimentId));
    await waitFor(() => expect(api.getResults).toHaveBeenCalledWith(experimentId));
    expect(window.location.hash).toBe(`#/results?experimentId=${experimentId}`);
  });

  it('从结果页切换历史实验时不会被旧深链重新选回', async () => {
    const user = userEvent.setup();
    const experiments = ['exp-history-a', 'exp-history-b'].map((id) => ({
      id,
      eventPackId: `pack-${id}`,
      status: 'COMPLETED' as const,
      progress: 100,
      logs: [],
      scenario: {
        eventPackId: `pack-${id}`,
        question: `Question ${id}`,
        intervention: {
          parameter: 'marketMakerCapacity' as const,
          baselineValue: 1,
          interventionValue: 0.5,
        },
        seedCount: 10 as const,
        seedRoot: 1,
        populationSize: 20,
        steps: 60,
        primaryOutcome: 'maxSpreadBps' as const,
        secondaryOutcomes: [],
        acknowledgedScenarioNotForecast: true,
        acknowledgedSyntheticAssumptions: true,
      },
    }));
    vi.mocked(api.getExperiments).mockResolvedValue(experiments);
    vi.mocked(api.getExperiment).mockImplementation(async (id) => {
      const experiment = experiments.find((item) => item.id === id);
      if (!experiment) throw new Error('missing experiment');
      return experiment;
    });
    vi.mocked(api.getResults).mockImplementation(async (id) => ({
      experimentId: id,
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
    }));
    window.history.replaceState(null, '', buildAppHash('results', experiments[0].id));
    render(<App />);
    const selector = await screen.findByLabelText('View historical experiment result');

    await user.selectOptions(selector, experiments[1].id);

    await waitFor(() => expect(window.location.hash).toBe(buildAppHash('results', experiments[1].id)));
    expect(api.getResults).toHaveBeenCalledWith(experiments[1].id);
    expect(vi.mocked(api.getExperiment).mock.calls.at(-1)?.[0]).toBe(experiments[1].id);
  });

  it('replaceState 导航离开结果深链后不会被迟到的初始恢复覆盖', async () => {
    const user = userEvent.setup();
    const experimentId = 'exp-delayed-route';
    let resolveExperiment!: (experiment: Awaited<ReturnType<typeof api.getExperiment>>) => void;
    const experimentResponse = new Promise<Awaited<ReturnType<typeof api.getExperiment>>>((resolve) => {
      resolveExperiment = resolve;
    });
    vi.mocked(api.getExperiment).mockReturnValue(experimentResponse);
    window.history.replaceState(null, '', buildAppHash('results', experimentId));
    render(<App />);

    await waitFor(() => expect(api.getExperiment).toHaveBeenCalledWith(experimentId));
    const sidebar = document.querySelector<HTMLElement>('.sidebar');
    if (!sidebar) throw new Error('桌面主导航未渲染。');
    await user.click(within(sidebar).getByRole('button', { name: 'Case Library' }));
    expect(window.location.hash).toBe('#/cases');

    await act(async () => {
      resolveExperiment({
        id: experimentId,
        eventPackId: 'pack-delayed-route',
        status: 'COMPLETED',
        progress: 100,
        logs: [],
      });
      await experimentResponse;
    });
    expect(api.getResults).not.toHaveBeenCalled();

    await user.click(within(sidebar).getByRole('button', { name: 'Results' }));
    expect(await screen.findByText('Select a completed experiment')).toBeInTheDocument();
  });

  it('打开抽屉后聚焦当前页面，并在选择导航项后自动关闭', async () => {
    const user = userEvent.setup();
    render(<App />);

    const menuButton = screen.getByRole('button', { name: 'Open navigation' });
    const drawer = document.getElementById('mobile-primary-navigation');
    expect(drawer).not.toBeNull();
    if (!drawer) throw new Error('移动导航抽屉未渲染。');
    expect(menuButton).toHaveAttribute('aria-controls', drawer.id);
    expect(menuButton).toHaveAttribute('aria-expanded', 'false');
    expect(drawer).not.toBeVisible();

    await user.click(menuButton);

    expect(menuButton).toHaveAttribute('aria-expanded', 'true');
    expect(drawer).toBeVisible();
    await waitFor(() => {
      expect(within(drawer).getByRole('button', { name: 'Case Library' })).toHaveFocus();
    });

    await user.click(within(drawer).getByRole('button', { name: 'Event Pack Review' }));

    expect(drawer).not.toBeVisible();
    expect(menuButton).toHaveAttribute('aria-expanded', 'false');
    expect(window.location.hash).toBe('#/pack');
    expect(document.getElementById('main-content')).toHaveFocus();
  });

  it('支持 Escape 关闭并将焦点返回菜单按钮', async () => {
    const user = userEvent.setup();
    render(<App />);

    const menuButton = screen.getByRole('button', { name: 'Open navigation' });
    const drawer = document.getElementById('mobile-primary-navigation');
    expect(drawer).not.toBeNull();
    if (!drawer) throw new Error('移动导航抽屉未渲染。');
    await user.click(menuButton);
    await waitFor(() => expect(drawer).toBeVisible());

    await user.keyboard('{Escape}');

    expect(drawer).not.toBeVisible();
    expect(menuButton).toHaveFocus();
    expect(document.body.style.overflow).toBe('');
  });

  it('切换为简体中文后同步更新菜单和主导航名称', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('button', { name: '中文' }));

    const menuButton = screen.getByRole('button', { name: '打开导航' });
    await user.click(menuButton);
    const drawer = screen.getByRole('dialog', { name: '主导航' });
    expect(within(drawer).getByRole('button', { name: '案例库' })).toBeInTheDocument();
    expect(menuButton).toHaveAccessibleName('关闭导航');
    expect(menuButton).toHaveAttribute('aria-expanded', 'true');
  });

  it('默认英文首屏明确展示主要目标用户及其工作场景', async () => {
    render(<App />);

    expect(await screen.findByText('Built for')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Market event-risk analysts' })).toBeInTheDocument();
    expect(screen.getByText(/asset managers, banks, and exchanges/i)).toBeInTheDocument();
  });

  it('简体中文首屏明确展示主要目标用户及其工作场景', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('button', { name: '中文' }));

    expect(screen.getByText('主要用户')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '市场事件风险分析人员' })).toBeInTheDocument();
    expect(screen.getByText(/资管机构、银行与交易所/)).toBeInTheDocument();
  });
});
