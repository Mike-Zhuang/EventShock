import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from './api/client';
import { App, buildAppHash, parseAppRoute } from './app';

vi.mock('./api/client', () => ({
  AUTH_SESSION_EXPIRED_EVENT: 'eventshock:auth-session-expired',
  setCsrfToken: vi.fn(),
  ApiError: class extends Error {
    status = 500;
  },
  api: {
    getAuthSession: vi.fn(async () => ({
      authenticationRequired: true,
      authenticated: true,
      csrfToken: 'test-csrf',
      user: {
        id: 'user-test',
        email: 'analyst@example.com',
        role: 'USER',
        emailVerified: true,
        createdAt: '2026-07-20T00:00:00Z',
      },
    })),
    login: vi.fn(),
    register: vi.fn(),
    requestVerificationCode: vi.fn(),
    resetPassword: vi.fn(async () => undefined),
    logout: vi.fn(async () => undefined),
    getAdminUsers: vi.fn(async () => ({
      items: [],
      total: 0,
      summary: { totalUsers: 0, verifiedUsers: 0, activeUsersLastSevenDays: 0, totalActivities: 0 },
    })),
    getAdminActivity: vi.fn(async () => ({ items: [], total: 0 })),
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

    const menuButton = await screen.findByRole('button', { name: 'Open navigation' });
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

    const menuButton = await screen.findByRole('button', { name: 'Open navigation' });
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

    await user.click(await screen.findByRole('button', { name: '中文' }));

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

    await user.click(await screen.findByRole('button', { name: '中文' }));

    expect(screen.getByText('主要用户')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '市场事件风险分析人员' })).toBeInTheDocument();
    expect(screen.getByText(/资管机构、银行与交易所/)).toBeInTheDocument();
  });

  it('未登录时只渲染认证页面，不加载任何用户工作流数据', async () => {
    vi.mocked(api.getAuthSession).mockResolvedValueOnce({
      authenticationRequired: true,
      authenticated: false,
    });

    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.getByText('Market event-risk analysts')).toBeInTheDocument();
    expect(api.getCases).not.toHaveBeenCalled();
    expect(api.getExperiments).not.toHaveBeenCalled();
  });

  it('完成英文注册验证码流程后才挂载持久工作区', async () => {
    const user = userEvent.setup();
    const authenticatedSession = {
      authenticationRequired: true,
      authenticated: true,
      csrfToken: 'registered-csrf',
      user: {
        id: 'user-new',
        email: 'new.analyst@example.com',
        role: 'USER' as const,
        emailVerified: true,
        createdAt: '2026-07-20T01:00:00Z',
      },
    };
    vi.mocked(api.getAuthSession).mockResolvedValueOnce({ authenticationRequired: true, authenticated: false });
    vi.mocked(api.requestVerificationCode).mockResolvedValueOnce({ accepted: true, retryAfterSeconds: 60, expiresInSeconds: 600 });
    vi.mocked(api.register).mockResolvedValueOnce(authenticatedSession);
    render(<App />);

    await user.click(await screen.findByRole('button', { name: 'Create account' }));
    await user.type(screen.getByLabelText('Email address'), 'new.analyst@example.com');
    await user.type(screen.getByLabelText('New password'), 'ResearchPass42');
    await user.type(screen.getByLabelText('Confirm password'), 'ResearchPass42');
    await user.click(screen.getByRole('button', { name: 'Send verification code' }));

    await waitFor(() => expect(api.requestVerificationCode).toHaveBeenCalledWith({
      email: 'new.analyst@example.com',
      purpose: 'REGISTER',
      language: 'en',
    }));
    await user.type(await screen.findByLabelText('Six-digit verification code'), '123456');
    await user.click(screen.getByRole('button', { name: 'Create account' }));

    await waitFor(() => expect(api.register).toHaveBeenCalledWith({
      email: 'new.analyst@example.com',
      password: 'ResearchPass42',
      verificationCode: '123456',
      language: 'en',
    }));
    await waitFor(() => expect(api.getCases).toHaveBeenCalled());
  });

  it('收到全局 401 会话失效事件后卸载工作流并返回登录页', async () => {
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Case Library' })).toBeInTheDocument();

    act(() => window.dispatchEvent(new Event('eventshock:auth-session-expired')));

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('服务器未确认退出时保留工作区并显示共享设备安全提示', async () => {
    const user = userEvent.setup();
    vi.mocked(api.logout).mockRejectedValueOnce(new Error('network unavailable'));
    render(<App />);

    await user.click(await screen.findByRole('button', { name: 'Sign out' }));

    expect(await screen.findByText('Sign-out was not confirmed')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Case Library' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Sign in' })).not.toBeInTheDocument();
  });

  it('只有管理员账户会显示用户管理入口并加载最小化活动数据', async () => {
    const user = userEvent.setup();
    vi.mocked(api.getAuthSession).mockResolvedValueOnce({
      authenticationRequired: true,
      authenticated: true,
      csrfToken: 'admin-csrf',
      user: {
        id: 'admin-user',
        email: 'admin@example.com',
        role: 'ADMIN',
        emailVerified: true,
        createdAt: '2026-07-20T00:00:00Z',
      },
    });
    render(<App />);

    const sidebar = await waitFor(() => {
      const element = document.querySelector<HTMLElement>('.sidebar');
      if (!element) throw new Error('桌面主导航未渲染。');
      return element;
    });
    await user.click(within(sidebar).getByRole('button', { name: 'User Administration' }));

    expect(await screen.findByRole('heading', { name: 'User Administration' })).toBeInTheDocument();
    await waitFor(() => expect(api.getAdminUsers).toHaveBeenCalledWith(25, 0));
    await waitFor(() => expect(api.getAdminActivity).toHaveBeenCalledWith(50, 0, undefined));
  });
});
