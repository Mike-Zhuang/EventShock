import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from './api/client';
import type { UserPreferencesInput } from './api/types';
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
    getLegalDocument: vi.fn(async (language: 'en' | 'zh-CN') => ({
      schemaVersion: '1.0.0',
      version: '2026-07-22-v1',
      effectiveDate: '2026-07-22',
      locale: language,
      title: language === 'zh-CN'
        ? 'EventShock Lab 使用条款与隐私告知'
        : 'EventShock Lab Terms of Use and Privacy Notice',
      summary: language === 'zh-CN' ? '继续前请完整阅读。' : 'Read this document before continuing.',
      operatorLabel: 'EventShock Lab project operators',
      minimumAge: 18,
      sections: [
        {
          id: 'scope',
          title: language === 'zh-CN' ? '1. 范围与接受' : '1. Scope and acceptance',
          body: [language === 'zh-CN' ? '这些条款适用于本服务。' : 'These terms govern the Service.'],
        },
      ],
      acceptanceStatements: [
        language === 'zh-CN'
          ? '我已阅读并同意本版本《使用条款与隐私告知》。'
          : 'I have read and agree to this version of the Terms of Use and Privacy Notice.',
        'I confirm that I am at least 18 years old.',
        'I understand the AI boundary.',
      ],
      legalReviewNotice: 'Qualified counsel should review this document.',
      documentHash: 'a'.repeat(64),
    })),
    acceptLegalDocuments: vi.fn(async () => ({
      required: false,
      version: '2026-07-22-v1',
      acceptedAt: '2026-07-22T12:00:00Z',
    })),
    getUserPreferences: vi.fn(async () => ({ onboardingRequired: true })),
    saveUserPreferences: vi.fn(async (input: UserPreferencesInput) => ({
      ...input,
      onboardingRequired: false,
      onboardingVersion: '2026-07-22-v1',
      onboardingCompletedAt: '2026-07-22T12:01:00Z',
    })),
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
    getGuidedWorkflows: vi.fn(async () => []),
    createGuidedWorkflow: vi.fn(),
    getGuidedWorkflow: vi.fn(),
    sendGuidedTurn: vi.fn(),
    applyGuidedProposal: vi.fn(),
    advanceGuidedWorkflow: vi.fn(),
    linkGuidedWorkflowArtifacts: vi.fn(),
    getExperiments: vi.fn(async () => []),
    getExperiment: vi.fn(),
    getResults: vi.fn(),
    getLlmConfig: vi.fn(async () => ({ configured: false })),
  },
}));

describe('移动主导航', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.history.replaceState(null, '', '#/cases');
    document.body.style.overflow = '';
    vi.stubGlobal('scrollTo', vi.fn());
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    });
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
    const hash = buildAppHash('results', {
      experimentId: 'exp-history/with space',
      target: 'metrics-heading',
    });

    expect(hash).toBe('#/results?experimentId=exp-history%2Fwith+space&target=metrics-heading');
    expect(parseAppRoute(hash)).toEqual({
      view: 'results',
      experimentId: 'exp-history/with space',
      target: 'metrics-heading',
    });
  });

  it('丢弃未知 target 以及不属于当前页面的白名单 target', () => {
    expect(parseAppRoute('#/guided')).toEqual({
      view: 'guided',
      experimentId: undefined,
      target: undefined,
    });
    expect(parseAppRoute('#/factory')).toEqual({
      view: 'factory',
      experimentId: undefined,
      target: undefined,
    });
    expect(parseAppRoute('#/results?target=not-a-target')).toEqual({
      view: 'results',
      experimentId: undefined,
      target: undefined,
    });
    expect(parseAppRoute('#/trace?target=metrics-heading')).toEqual({
      view: 'trace',
      experimentId: undefined,
      target: undefined,
    });
    expect(buildAppHash('cases', {
      experimentId: 'ignored',
      target: 'metrics-heading',
    })).toBe('#/cases');
  });

  it('恢复登录会话时只在空路由进入用户保存的默认工作区', async () => {
    vi.mocked(api.getAuthSession).mockResolvedValueOnce({
      authenticationRequired: true,
      authenticated: true,
      csrfToken: 'guided-csrf',
      user: {
        id: 'user-guided-home',
        email: 'guided@example.com',
        role: 'USER',
        emailVerified: true,
        createdAt: '2026-07-22T00:00:00Z',
      },
      legalAcceptance: { required: false, version: '2026-07-22-v1' },
      preferences: {
        onboardingRequired: false,
        experienceLevel: 'NEW',
        assistancePreference: 'STEP_BY_STEP',
        firstGoal: 'RESEARCH_NEW_EVENT',
        workspaceMode: 'GUIDED',
      },
    });
    window.history.replaceState(null, '', window.location.pathname);

    render(<App />);

    expect(await screen.findByRole('heading', { name: 'AI-guided workflow' }))
      .toBeInTheDocument();
    expect(window.location.hash).toBe('#/guided');
  });

  it('允许用户保存工作区模式并立即切换入口', async () => {
    const user = userEvent.setup();
    vi.mocked(api.getAuthSession).mockResolvedValueOnce({
      authenticationRequired: true,
      authenticated: true,
      csrfToken: 'guided-switch-csrf',
      user: {
        id: 'user-guided-switch',
        email: 'guided-switch@example.com',
        role: 'USER',
        emailVerified: true,
        createdAt: '2026-07-22T00:00:00Z',
      },
      legalAcceptance: { required: false, version: '2026-07-22-v1' },
      preferences: {
        onboardingRequired: false,
        experienceLevel: 'NEW',
        assistancePreference: 'STEP_BY_STEP',
        firstGoal: 'RESEARCH_NEW_EVENT',
        workspaceMode: 'GUIDED',
      },
    });
    window.history.replaceState(null, '', '#/guided');

    render(<App />);
    await user.click(await screen.findByRole('button', { name: 'Research workspace' }));

    await waitFor(() => expect(api.saveUserPreferences).toHaveBeenCalledWith({
      experienceLevel: 'NEW',
      assistancePreference: 'STEP_BY_STEP',
      firstGoal: 'RESEARCH_NEW_EVENT',
      workspaceMode: 'EXPERT',
    }));
    await waitFor(() => expect(window.location.hash).toBe('#/study'));
  });

  it('用户要求减少动态效果时以无动画方式定位目标', async () => {
    vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
      matches: query === '(prefers-reduced-motion: reduce)',
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    const target = document.createElement('h2');
    target.id = 'metrics-heading';
    target.textContent = 'External test target';
    document.body.append(target);
    window.history.replaceState(null, '', buildAppHash('results', { target: 'metrics-heading' }));

    render(<App />);

    await waitFor(() => expect(target).toHaveFocus());
    expect(target.scrollIntoView).toHaveBeenCalledWith({ block: 'start', behavior: 'auto' });
    target.remove();
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
    window.history.replaceState(null, '', buildAppHash('results', { experimentId }));

    render(<App />);

    await waitFor(() => expect(api.getExperiment).toHaveBeenCalledWith(experimentId));
    await waitFor(() => expect(api.getResults).toHaveBeenCalledWith(experimentId));
    expect(window.location.hash).toBe(`#/results?experimentId=${experimentId}`);
  });

  it('刷新追踪深链时恢复同一实验结果，并聚焦追踪区段', async () => {
    const experimentId = 'exp-trace-restore';
    vi.mocked(api.getExperiment).mockResolvedValue({
      id: experimentId,
      eventPackId: 'pack-trace',
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
      traces: [{ id: 'trace-one', title: 'Fact', kind: 'FACT' }],
      limitations: [],
      limitationsZh: [],
      modelVersions: {},
      dataVersions: {},
      pairedSeries: {},
    });
    window.history.replaceState(null, '', buildAppHash('trace', {
      experimentId,
      target: 'trace-timeline-heading',
    }));

    render(<App />);

    await waitFor(() => expect(api.getResults).toHaveBeenCalledWith(experimentId));
    const target = await screen.findByRole('heading', { name: 'Mechanism timeline' });
    await waitFor(() => expect(target).toHaveFocus());
    expect(target).toHaveAttribute('tabindex', '-1');
    expect(target.scrollIntoView).toHaveBeenCalledWith({
      block: 'start',
      behavior: 'smooth',
    });
  });

  it('跨实验 hash 跳转会等待新结果恢复后再聚焦同名目标', async () => {
    const firstExperimentId = 'exp-focus-first';
    const secondExperimentId = 'exp-focus-second';
    const experiment = (id: string) => ({
      id,
      eventPackId: `pack-${id}`,
      status: 'COMPLETED' as const,
      progress: 100,
      logs: [],
    });
    const results = (id: string) => ({
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
    });
    let resolveSecondResults!: (value: ReturnType<typeof results>) => void;
    const secondResults = new Promise<ReturnType<typeof results>>((resolve) => {
      resolveSecondResults = resolve;
    });
    vi.mocked(api.getExperiment).mockImplementation(async (id) => experiment(id));
    vi.mocked(api.getResults).mockImplementation((id) => (
      id === firstExperimentId ? Promise.resolve(results(id)) : secondResults
    ));
    window.history.replaceState(null, '', buildAppHash('results', {
      experimentId: firstExperimentId,
      target: 'metrics-heading',
    }));
    render(<App />);

    const firstTarget = await screen.findByRole('heading', { name: 'Primary metrics' });
    await waitFor(() => expect(firstTarget).toHaveFocus());
    document.getElementById('main-content')?.focus();

    window.history.replaceState(null, '', buildAppHash('results', {
      experimentId: secondExperimentId,
      target: 'metrics-heading',
    }));
    window.dispatchEvent(new HashChangeEvent('hashchange'));
    await waitFor(() => expect(api.getResults).toHaveBeenCalledWith(secondExperimentId));
    expect(firstTarget).not.toHaveFocus();
    expect(screen.queryByRole('heading', { name: 'Primary metrics' })).not.toBeInTheDocument();

    await act(async () => {
      resolveSecondResults(results(secondExperimentId));
      await secondResults;
    });
    await waitFor(() => expect(document.getElementById('metrics-heading')).toHaveFocus());
  }, 20_000);

  it('跨实验深链恢复失败时隐藏旧结果并显示可重试错误', async () => {
    const firstExperimentId = 'exp-restore-visible-first';
    const missingExperimentId = 'exp-restore-missing-second';
    const firstExperiment = {
      id: firstExperimentId,
      eventPackId: 'pack-restore-first',
      status: 'COMPLETED' as const,
      progress: 100,
      logs: [],
    };
    const firstResults = {
      experimentId: firstExperimentId,
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
    vi.mocked(api.getExperiment).mockImplementation(async (id) => {
      if (id === missingExperimentId) throw new Error('not found');
      return firstExperiment;
    });
    vi.mocked(api.getResults).mockResolvedValue(firstResults);
    window.history.replaceState(null, '', buildAppHash('results', {
      experimentId: firstExperimentId,
      target: 'metrics-heading',
    }));
    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Primary metrics' })).toBeInTheDocument();
    window.history.replaceState(null, '', buildAppHash('results', {
      experimentId: missingExperimentId,
      target: 'metrics-heading',
    }));
    window.dispatchEvent(new HashChangeEvent('hashchange'));

    expect(await screen.findByRole('heading', {
      name: 'Experiment could not be restored',
    })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Primary metrics' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(window.location.hash).toContain(`experimentId=${missingExperimentId}`);
  }, 20_000);

  // 该集成用例会懒加载完整 Results 页；GitHub 共享 runner 上首次模块转换可超过 Vitest 默认 5 秒。
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
    window.history.replaceState(null, '', buildAppHash('results', { experimentId: experiments[0].id }));
    render(<App />);
    const selector = await screen.findByLabelText(
      'View historical experiment result',
      {},
      { timeout: 10_000 },
    );

    await user.selectOptions(selector, experiments[1].id);

    await waitFor(() => expect(window.location.hash).toBe(buildAppHash('results', { experimentId: experiments[1].id })));
    expect(api.getResults).toHaveBeenCalledWith(experiments[1].id);
    expect(vi.mocked(api.getExperiment).mock.calls.at(-1)?.[0]).toBe(experiments[1].id);
  }, 15_000);

  it('replaceState 导航离开结果深链后不会被迟到的初始恢复覆盖', async () => {
    const user = userEvent.setup();
    const experimentId = 'exp-delayed-route';
    let resolveExperiment!: (experiment: Awaited<ReturnType<typeof api.getExperiment>>) => void;
    const experimentResponse = new Promise<Awaited<ReturnType<typeof api.getExperiment>>>((resolve) => {
      resolveExperiment = resolve;
    });
    vi.mocked(api.getExperiment).mockReturnValue(experimentResponse);
    window.history.replaceState(null, '', buildAppHash('results', { experimentId }));
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
    expect(within(drawer).getByRole('link', { name: 'Report an issue' })).toHaveAttribute(
      'href',
      'https://github.com/Mike-Zhuang/EventShock/issues/new/choose',
    );

    await user.click(within(drawer).getByRole('button', { name: 'Review Evidence' }));

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

  it('桌面与移动导航项共享占满分组宽度的结构契约', async () => {
    render(<App />);

    await screen.findByRole('heading', { name: 'Case Library' });
    const navigationContainers = [
      document.querySelector<HTMLElement>('.sidebar nav'),
      document.querySelector<HTMLElement>('.mobile-navigation nav'),
    ];

    navigationContainers.forEach((navigation) => {
      expect(navigation).not.toBeNull();
      if (!navigation) return;
      const items = Array.from(navigation.querySelectorAll<HTMLButtonElement>('button.navigation-item'));
      expect(items.length).toBeGreaterThan(0);
      items.forEach((item) => {
        expect(item).toHaveClass('navigation-item');
        expect(item.parentElement).toHaveClass('navigation-section');
      });
    });

    const researchSections = Array.from(document.querySelectorAll<HTMLElement>('.navigation-section'))
      .filter((section) => section.getAttribute('aria-label') === 'Research tools');
    expect(researchSections).toHaveLength(2);
    researchSections.forEach((section) => {
      expect(within(section).getByRole('button', { name: 'Study Workbench', hidden: true })).toBeInTheDocument();
      expect(within(section).getByRole('button', { name: 'Mechanism Trace', hidden: true })).toBeInTheDocument();
      expect(within(section).getByRole('button', { name: 'Validation & Governance', hidden: true })).toBeInTheDocument();
      expect(within(section).queryByRole('button', { name: 'AI Configuration', hidden: true })).not.toBeInTheDocument();
    });
  });

  it('默认英文首屏明确展示主要目标用户及其工作场景', async () => {
    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Change one condition. See whether the same shock gets worse.' })).toBeInTheDocument();
    expect(await screen.findByText('Built for')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Market event-risk analysts' })).toBeInTheDocument();
    expect(screen.getByText(/asset managers, banks, exchanges/i)).toBeInTheDocument();
    expect(screen.getByText('Not for')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Personal investment decisions' })).toBeInTheDocument();
    expect(screen.getByText('whether to buy or sell')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'GitHub repository' })).toHaveAttribute(
      'href',
      'https://github.com/Mike-Zhuang/EventShock',
    );
    screen.getAllByRole('link', { name: 'Report an issue' }).forEach((link) => {
      expect(link).toHaveAttribute(
        'href',
        'https://github.com/Mike-Zhuang/EventShock/issues/new/choose',
      );
      expect(link).toHaveAttribute('target', '_blank');
      expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
    });
  });

  it('简体中文首屏明确展示主要目标用户及其工作场景', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('button', { name: '中文' }));

    expect(screen.getByRole('heading', { name: '改一个条件，看同一场冲击会不会更糟。' })).toBeInTheDocument();
    expect(screen.getByText('主要用户')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '市场事件风险分析人员' })).toBeInTheDocument();
    expect(screen.getByText(/资管机构、银行、交易所/)).toBeInTheDocument();
    expect(screen.getByText('不服务于')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '个人投资决策' })).toBeInTheDocument();
    expect(screen.getByText('应该买入还是卖出')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: '提交问题反馈' }).length).toBeGreaterThan(0);
  });

  it('未登录时只渲染认证页面，不加载任何用户工作流数据', async () => {
    vi.mocked(api.getAuthSession).mockResolvedValueOnce({
      authenticationRequired: true,
      authenticated: false,
    });

    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.getByText('Market event-risk analysts')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'GitHub repository' })).toHaveAttribute(
      'href',
      'https://github.com/Mike-Zhuang/EventShock',
    );
    expect(screen.getByRole('link', { name: 'Report an issue' })).toHaveAttribute(
      'href',
      'https://github.com/Mike-Zhuang/EventShock/issues/new/choose',
    );
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
    const registrationChecks = await screen.findAllByRole('checkbox');
    expect(registrationChecks).toHaveLength(3);
    for (const checkbox of registrationChecks) await user.click(checkbox);
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
      version: '2026-07-22-v1',
      documentHash: 'a'.repeat(64),
      acceptedTerms: true,
      acknowledgedPrivacy: true,
      confirmedMinimumAge: true,
      acknowledgedAiBoundary: true,
    }));
    await waitFor(() => expect(api.getCases).toHaveBeenCalled());
  });

  it('现有用户必须先接受当前条款，且门禁期间不挂载研究工作流', async () => {
    const user = userEvent.setup();
    vi.mocked(api.getAuthSession).mockResolvedValueOnce({
      authenticationRequired: true,
      authenticated: true,
      csrfToken: 'legal-gate-csrf',
      user: {
        id: 'user-existing',
        email: 'existing@example.com',
        role: 'USER',
        emailVerified: true,
        createdAt: '2026-07-01T00:00:00Z',
      },
      legalAcceptance: { required: true, version: '2026-07-22-v1' },
      preferences: { onboardingRequired: true },
    });

    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Review the terms before entering your workspace.' })).toBeInTheDocument();
    expect(api.getCases).not.toHaveBeenCalled();
    expect(await screen.findByRole('button', { name: 'Accept and continue' })).toBeDisabled();

    for (const checkbox of screen.getAllByRole('checkbox')) await user.click(checkbox);
    await user.click(screen.getByRole('button', { name: 'Accept and continue' }));

    await waitFor(() => expect(api.acceptLegalDocuments).toHaveBeenCalledWith({
      language: 'en',
      version: '2026-07-22-v1',
      documentHash: 'a'.repeat(64),
      acceptedTerms: true,
      acknowledgedPrivacy: true,
      confirmedMinimumAge: true,
      acknowledgedAiBoundary: true,
    }));
    expect(await screen.findByRole('heading', { name: 'Choose how EventShock should guide you.' })).toBeInTheDocument();
    expect(api.getCases).not.toHaveBeenCalled();
  });

  it('onboarding 要求三项自我描述和明确模式选择，保存后才加载工作区', async () => {
    const user = userEvent.setup();
    vi.mocked(api.getAuthSession).mockResolvedValueOnce({
      authenticationRequired: true,
      authenticated: true,
      csrfToken: 'onboarding-csrf',
      user: {
        id: 'user-onboarding',
        email: 'new@example.com',
        role: 'USER',
        emailVerified: true,
        createdAt: '2026-07-22T00:00:00Z',
      },
      legalAcceptance: {
        required: false,
        version: '2026-07-22-v1',
        acceptedAt: '2026-07-22T00:00:00Z',
      },
      preferences: { onboardingRequired: true },
    });

    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Choose how EventShock should guide you.' })).toBeInTheDocument();
    expect(api.getCases).not.toHaveBeenCalled();
    const continueButton = screen.getByRole('button', { name: 'Save and open workspace' });
    expect(continueButton).toBeDisabled();

    await user.click(screen.getByRole('radio', { name: /New to this workflow/ }));
    await user.click(screen.getByRole('radio', { name: /Guide me step by step/ }));
    await user.click(screen.getByRole('radio', { name: /Research a new event/ }));
    expect(screen.getByText('Recommended starting mode')).toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: /Guided workspace/ }));
    await user.click(continueButton);

    await waitFor(() => expect(api.saveUserPreferences).toHaveBeenCalledWith({
      experienceLevel: 'NEW',
      workspaceMode: 'GUIDED',
      assistancePreference: 'STEP_BY_STEP',
      firstGoal: 'RESEARCH_NEW_EVENT',
    }));
    await waitFor(() => expect(window.location.hash).toBe('#/guided'));
    await waitFor(() => expect(api.getCases).toHaveBeenCalled());
  });

  it('onboarding 选择研究工作区后以研究工作台作为默认首页', async () => {
    const user = userEvent.setup();
    vi.mocked(api.getAuthSession).mockResolvedValueOnce({
      authenticationRequired: true,
      authenticated: true,
      csrfToken: 'expert-onboarding-csrf',
      user: {
        id: 'user-expert-onboarding',
        email: 'expert@example.com',
        role: 'USER',
        emailVerified: true,
        createdAt: '2026-07-22T00:00:00Z',
      },
      legalAcceptance: {
        required: false,
        version: '2026-07-22-v1',
        acceptedAt: '2026-07-22T00:00:00Z',
      },
      preferences: { onboardingRequired: true },
    });

    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Choose how EventShock should guide you.' })).toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: /Experienced researcher/ }));
    await user.click(screen.getByRole('radio', { name: /Give me direct control/ }));
    await user.click(screen.getByRole('radio', { name: /Design a complete experiment/ }));
    await user.click(screen.getByRole('radio', { name: /Research workspace/ }));
    await user.click(screen.getByRole('button', { name: 'Save and open workspace' }));

    await waitFor(() => expect(api.saveUserPreferences).toHaveBeenCalledWith({
      experienceLevel: 'ADVANCED',
      workspaceMode: 'EXPERT',
      assistancePreference: 'DIRECT_CONTROL',
      firstGoal: 'DESIGN_FULL_EXPERIMENT',
    }));
    await waitFor(() => expect(window.location.hash).toBe('#/study'));
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
