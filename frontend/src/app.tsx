import { Button, IconButton, InlineNotification, Theme } from '@carbon/react';
import {
  Archive,
  Books,
  ChartLineUp,
  CheckSquare,
  ClipboardText,
  Cpu,
  Factory,
  FloppyDiskBack,
  Flask,
  GithubLogo,
  List,
  Path,
  Moon,
  PlayCircle,
  ShieldCheck,
  SlidersHorizontal,
  Sun,
  TreeStructure,
  SignOut,
  UserCircle,
  UsersThree,
  X,
} from '@phosphor-icons/react';
import {
  lazy,
  Suspense,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
} from 'react';
import {
  ApiConnectionBanner,
  ErrorPanel,
  LoadingPanel,
  ServiceStatus,
} from './components/common';
import {
  GITHUB_ISSUE_CHOOSER_URL,
  GITHUB_REPOSITORY_URL,
} from './external-links';
import { I18nProvider, useI18n } from './i18n';
import { AuthenticationPage } from './pages/authentication-page';
import { CaseLibraryPage } from './pages/case-library-page';
import { LegalAcceptancePage } from './pages/legal-acceptance-page';
import { OnboardingPage } from './pages/onboarding-page';
import { AuthProvider, useAuth } from './state/auth-context';
import { useWorkflow, WorkflowProvider } from './state/workflow-context';

const EventPackPage = lazy(async () => ({ default: (await import('./pages/event-pack-page')).EventPackPage }));
const EventPackFactoryPage = lazy(async () => ({ default: (await import('./pages/event-pack-factory-page')).EventPackFactoryPage }));
const GuidedWorkflowPage = lazy(async () => ({ default: (await import('./pages/guided-workflow-page')).GuidedWorkflowPage }));
const AiConfigurationPage = lazy(async () => ({ default: (await import('./pages/ai-configuration-page')).AiConfigurationPage }));
const ExportHistoryPage = lazy(async () => ({ default: (await import('./pages/export-history-page')).ExportHistoryPage }));
const GovernancePage = lazy(async () => ({ default: (await import('./pages/governance-page')).GovernancePage }));
const PreflightPage = lazy(async () => ({ default: (await import('./pages/preflight-page')).PreflightPage }));
const ResultsPage = lazy(async () => ({ default: (await import('./pages/results-page')).ResultsPage }));
const RunCenterPage = lazy(async () => ({ default: (await import('./pages/run-center-page')).RunCenterPage }));
const ScenarioBuilderPage = lazy(async () => ({ default: (await import('./pages/scenario-builder-page')).ScenarioBuilderPage }));
const StudyWorkbenchPage = lazy(async () => ({ default: (await import('./pages/study-workbench-page')).StudyWorkbenchPage }));
const TraceExplorerPage = lazy(async () => ({ default: (await import('./pages/trace-explorer-page')).TraceExplorerPage }));
const AccountPrivacyPage = lazy(async () => ({ default: (await import('./pages/account-privacy-page')).AccountPrivacyPage }));
const AdminPage = lazy(async () => ({ default: (await import('./pages/admin-page')).AdminPage }));

export type ViewId = 'guided' | 'cases' | 'factory' | 'pack' | 'ai' | 'scenario' | 'preflight' | 'runs' | 'results' | 'study' | 'trace' | 'governance' | 'export' | 'account' | 'admin';
export const ROUTE_TARGET_IDS = [
  'result-overview-heading',
  'metrics-heading',
  'paired-heading',
  'paths-heading',
  'trace-timeline-heading',
  'agent-flow-heading',
  'cognition-heading',
  'cognition-decisions-heading',
  'analysis-diagnostics-heading',
  'result-limitations-heading',
  'result-manifest-heading',
] as const;
export type RouteTargetId = (typeof ROUTE_TARGET_IDS)[number];

export interface NavigateOptions {
  experimentId?: string;
  target?: RouteTargetId;
}

export type Navigate = (view: ViewId, options?: NavigateOptions) => void;

type RouteRestoreState = 'idle' | 'loading' | 'error';

const VIEW_IDS: ViewId[] = ['guided', 'cases', 'factory', 'pack', 'ai', 'scenario', 'preflight', 'runs', 'results', 'study', 'trace', 'governance', 'export', 'account', 'admin'];
const MOBILE_NAVIGATION_ID = 'mobile-primary-navigation';
const ROUTE_TARGET_VIEWS: Record<RouteTargetId, Extract<ViewId, 'results' | 'trace'>> = {
  'result-overview-heading': 'results',
  'metrics-heading': 'results',
  'paired-heading': 'results',
  'paths-heading': 'results',
  'trace-timeline-heading': 'trace',
  'agent-flow-heading': 'results',
  'cognition-heading': 'results',
  'cognition-decisions-heading': 'results',
  'analysis-diagnostics-heading': 'results',
  'result-limitations-heading': 'results',
  'result-manifest-heading': 'results',
};

interface NavigationItem {
  id: ViewId;
  label: string;
  icon: ComponentType<{ size?: number; weight?: 'regular' | 'fill' }>;
}

function SidebarFooter({
  disclaimer,
  issueLabel,
}: {
  disclaimer: string;
  issueLabel: string;
}) {
  return (
    <footer className="sidebar__footer">
      <p>{disclaimer}</p>
      <a
        className="sidebar__issue-link"
        href={GITHUB_ISSUE_CHOOSER_URL}
        target="_blank"
        rel="noopener noreferrer"
      >
        <GithubLogo size={16} weight="duotone" aria-hidden="true" />
        <span>{issueLabel}</span>
      </a>
    </footer>
  );
}

export function parseAppRoute(hash: string): { view: ViewId; experimentId?: string; target?: RouteTargetId } {
  const [rawView, rawQuery = ''] = hash.replace(/^#\/?/, '').split('?', 2);
  const view = VIEW_IDS.includes(rawView as ViewId) ? rawView as ViewId : 'cases';
  const parameters = new URLSearchParams(rawQuery);
  const experimentId = view === 'results' || view === 'trace'
    ? parameters.get('experimentId') || undefined
    : undefined;
  const rawTarget = parameters.get('target');
  const target = rawTarget && ROUTE_TARGET_IDS.includes(rawTarget as RouteTargetId)
    && ROUTE_TARGET_VIEWS[rawTarget as RouteTargetId] === view
    ? rawTarget as RouteTargetId
    : undefined;
  return { view, experimentId, target };
}

export function buildAppHash(view: ViewId, options: NavigateOptions = {}): string {
  const parameters = new URLSearchParams();
  if ((view === 'results' || view === 'trace') && options.experimentId) {
    parameters.set('experimentId', options.experimentId);
  }
  if (options.target && ROUTE_TARGET_VIEWS[options.target] === view) {
    parameters.set('target', options.target);
  }
  const query = parameters.toString();
  return query ? `#/${view}?${query}` : `#/${view}`;
}

interface NavigationSection {
  label: string;
  items: NavigationItem[];
}

function NavigationItems({
  sections,
  view,
  onNavigate,
}: {
  sections: NavigationSection[];
  view: ViewId;
  onNavigate: (view: ViewId) => void;
}) {
  return (
    <>
      {sections.map((section) => (
        <section className="navigation-section" key={section.label} aria-label={section.label}>
          <span className="navigation-section__label">{section.label}</span>
          {section.items.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                type="button"
                className={`navigation-item${view === item.id ? ' is-active' : ''}`}
                aria-current={view === item.id ? 'page' : undefined}
                onClick={() => onNavigate(item.id)}
              >
                <Icon size={19} weight={view === item.id ? 'fill' : 'regular'} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </section>
      ))}
    </>
  );
}

function AppShell({ isDark, onToggleTheme }: { isDark: boolean; onToggleTheme: () => void }) {
  const { language, setLanguage, t } = useI18n();
  const { user, preferences, completeOnboarding, logout } = useAuth();
  const { cancelPendingExperimentRequests, loadResults, selectExperiment } = useWorkflow();
  const loadResultsRef = useRef(loadResults);
  const routeGenerationRef = useRef(0);
  const initialRoute = useMemo(() => parseAppRoute(window.location.hash), []);
  const [view, setView] = useState<ViewId>(initialRoute.view);
  // 带 experimentId 的刷新必须先恢复对应结果，避免先聚焦仍在页面上的上一实验同名标题。
  const [routeTarget, setRouteTarget] = useState<RouteTargetId | undefined>(
    initialRoute.experimentId ? undefined : initialRoute.target,
  );
  const [routeTargetRequest, setRouteTargetRequest] = useState(0);
  const [routeRestoreState, setRouteRestoreState] = useState<RouteRestoreState>(
    initialRoute.experimentId ? 'loading' : 'idle',
  );
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [logoutBusy, setLogoutBusy] = useState(false);
  const [logoutError, setLogoutError] = useState(false);
  const [workspaceModeBusy, setWorkspaceModeBusy] = useState(false);
  const [workspaceModeError, setWorkspaceModeError] = useState(false);
  const mobileMenuButtonRef = useRef<HTMLButtonElement>(null);
  const mobileNavigationRef = useRef<HTMLElement>(null);

  useEffect(() => {
    loadResultsRef.current = loadResults;
  }, [loadResults]);

  useEffect(() => {
    let cancelled = false;
    const restoreRoute = async () => {
      const currentGeneration = ++routeGenerationRef.current;
      cancelPendingExperimentRequests();
      const route = parseAppRoute(window.location.hash);
      const requiresResultRestore = Boolean(
        (route.view === 'results' || route.view === 'trace') && route.experimentId,
      );
      if (!cancelled) {
        setView(route.view);
        setRouteTarget(requiresResultRestore ? undefined : route.target);
        setRouteTargetRequest((current) => current + 1);
        setRouteRestoreState(requiresResultRestore ? 'loading' : 'idle');
      }
      if ((route.view !== 'results' && route.view !== 'trace') || !route.experimentId) return;
      try {
        const experiment = await selectExperiment(route.experimentId);
        if (
          experiment
          && !cancelled
          && currentGeneration === routeGenerationRef.current
          && experiment.status === 'COMPLETED'
        ) {
          const restoredResults = await loadResultsRef.current(experiment.id);
          if (
            restoredResults
            && !cancelled
            && currentGeneration === routeGenerationRef.current
          ) {
            setRouteTarget(route.target);
            setRouteTargetRequest((current) => current + 1);
            setRouteRestoreState('idle');
          } else if (!cancelled && currentGeneration === routeGenerationRef.current) {
            setRouteRestoreState('error');
          }
        } else if (
          experiment
          && !cancelled
          && currentGeneration === routeGenerationRef.current
        ) {
          setRouteRestoreState('error');
        }
      } catch {
        // 深链恢复失败时必须遮蔽旧实验，避免新 URL 与旧结果产生错误归属。
        if (!cancelled && currentGeneration === routeGenerationRef.current) {
          setRouteRestoreState('error');
        }
      }
    };
    const handleHashChange = () => void restoreRoute();
    void restoreRoute();
    window.addEventListener('hashchange', handleHashChange);
    return () => {
      cancelled = true;
      window.removeEventListener('hashchange', handleHashChange);
    };
  }, [cancelPendingExperimentRequests, selectExperiment]);

  useEffect(() => {
    if (!routeTarget) return;
    let cancelled = false;
    let observer: MutationObserver | undefined;
    let timeoutId: number | undefined;

    const focusTarget = () => {
      if (cancelled) return false;
      const target = document.getElementById(routeTarget);
      if (!target) return false;
      const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      target.setAttribute('tabindex', '-1');
      target.scrollIntoView({ block: 'start', behavior: reducedMotion ? 'auto' : 'smooth' });
      target.focus({ preventScroll: true });
      observer?.disconnect();
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
      return true;
    };

    if (focusTarget()) return;
    observer = new MutationObserver(() => {
      focusTarget();
    });
    observer.observe(document.getElementById('main-content') ?? document.body, {
      childList: true,
      subtree: true,
    });
    timeoutId = window.setTimeout(() => observer?.disconnect(), 15_000);
    return () => {
      cancelled = true;
      observer?.disconnect();
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
    };
  }, [routeTarget, routeTargetRequest, view]);

  useEffect(() => {
    const mobileQuery = window.matchMedia('(max-width: 920px)');
    const closeAboveMobile = (event: MediaQueryListEvent) => {
      if (!event.matches) setMobileNavOpen(false);
    };
    mobileQuery.addEventListener('change', closeAboveMobile);
    return () => mobileQuery.removeEventListener('change', closeAboveMobile);
  }, []);

  useEffect(() => {
    if (!mobileNavOpen) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const focusTimer = window.setTimeout(() => {
      const activeItem = mobileNavigationRef.current?.querySelector<HTMLElement>('[aria-current="page"]');
      const firstItem = mobileNavigationRef.current?.querySelector<HTMLElement>('button');
      (activeItem ?? firstItem)?.focus();
    }, 0);

    const handleNavigationKeys = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setMobileNavOpen(false);
        mobileMenuButtonRef.current?.focus();
        return;
      }
      if (event.key !== 'Tab' || !mobileNavigationRef.current) return;

      const focusableItems = Array.from(
        mobileNavigationRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), a[href]'),
      );
      const firstItem = focusableItems[0];
      const lastItem = focusableItems.at(-1);
      if (!firstItem || !lastItem) return;

      if (event.shiftKey && document.activeElement === firstItem) {
        event.preventDefault();
        lastItem.focus();
      } else if (!event.shiftKey && document.activeElement === lastItem) {
        event.preventDefault();
        firstItem.focus();
      }
    };

    document.addEventListener('keydown', handleNavigationKeys);
    return () => {
      window.clearTimeout(focusTimer);
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', handleNavigationKeys);
    };
  }, [mobileNavOpen]);

  const closeMobileNavigation = (restoreFocus = true) => {
    setMobileNavOpen(false);
    if (restoreFocus) mobileMenuButtonRef.current?.focus();
  };

  const navigate: Navigate = (nextView, options = {}) => {
    routeGenerationRef.current += 1;
    cancelPendingExperimentRequests();
    setView(nextView);
    const nextHash = buildAppHash(nextView, options);
    const nextRoute = parseAppRoute(nextHash);
    setRouteTarget(nextRoute.target);
    setRouteTargetRequest((current) => current + 1);
    setRouteRestoreState('idle');
    setMobileNavOpen(false);
    window.history.replaceState(null, '', nextHash);
    if (!nextRoute.target) {
      document.getElementById('main-content')?.focus({ preventScroll: true });
      window.scrollTo({ top: 0, behavior: 'auto' });
    }
  };

  useEffect(() => {
    if (view === 'admin' && user?.role !== 'ADMIN') navigate('cases');
  }, [user?.role, view]);

  const navigation = useMemo<NavigationSection[]>(() => {
    const sections: NavigationSection[] = [
      {
        label: t('nav.groupCore'),
        items: [
          { id: 'guided', label: t('nav.guided'), icon: Path },
          { id: 'cases', label: t('nav.cases'), icon: Books },
          { id: 'factory', label: t('nav.factory'), icon: Factory },
          { id: 'pack', label: t('nav.pack'), icon: ClipboardText },
          { id: 'scenario', label: t('nav.scenario'), icon: SlidersHorizontal },
          { id: 'preflight', label: t('nav.preflight'), icon: CheckSquare },
          { id: 'runs', label: t('nav.runs'), icon: PlayCircle },
          { id: 'results', label: t('nav.results'), icon: ChartLineUp },
        ],
      },
      {
        label: t('nav.groupResearch'),
        items: [
          { id: 'study', label: t('nav.study'), icon: Flask },
          { id: 'trace', label: t('nav.trace'), icon: TreeStructure },
          { id: 'governance', label: t('nav.governance'), icon: ShieldCheck },
          { id: 'export', label: t('nav.export'), icon: Archive },
        ],
      },
      {
        label: t('nav.groupOptional'),
        items: [
          { id: 'ai', label: t('nav.ai'), icon: Cpu },
        ],
      },
      {
        label: t('nav.groupAccount'),
        items: [
          { id: 'account', label: t('nav.account'), icon: UserCircle },
        ],
      },
    ];
    if (user?.role === 'ADMIN') {
      sections.push({
        label: t('nav.groupAdmin'),
        items: [{ id: 'admin', label: t('nav.admin'), icon: UsersThree }],
      });
    }
    return sections;
  }, [t, user?.role]);

  const pages: Record<ViewId, React.ReactNode> = {
    guided: <GuidedWorkflowPage navigate={navigate} />,
    cases: <CaseLibraryPage navigate={navigate} />,
    factory: <EventPackFactoryPage navigate={navigate} />,
    pack: <EventPackPage navigate={navigate} />,
    ai: <AiConfigurationPage />,
    scenario: <ScenarioBuilderPage navigate={navigate} />,
    preflight: <PreflightPage navigate={navigate} />,
    runs: <RunCenterPage navigate={navigate} />,
    results: <ResultsPage navigate={navigate} />,
    study: <StudyWorkbenchPage navigate={navigate} />,
    trace: <TraceExplorerPage />,
    governance: <GovernancePage />,
    export: <ExportHistoryPage navigate={navigate} />,
    account: <AccountPrivacyPage />,
    admin: <AdminPage />,
  };

  const pageRequiresRouteRestore = (view === 'results' || view === 'trace')
    && routeRestoreState !== 'idle';
  const currentPage = pageRequiresRouteRestore
    ? routeRestoreState === 'loading'
      ? (
        <div className="page">
          <LoadingPanel label={language === 'zh-CN' ? '正在恢复实验结果' : 'Restoring experiment results'} />
        </div>
      )
      : (
        <div className="page">
          <ErrorPanel
            title={language === 'zh-CN' ? '无法恢复实验' : 'Experiment could not be restored'}
            body={language === 'zh-CN'
              ? '请求的实验或结果不可用。旧实验已被隐藏，请核对链接后重试。'
              : 'The requested experiment or result is unavailable. The previous experiment has been hidden; verify the link and retry.'}
            onRetry={() => window.dispatchEvent(new HashChangeEvent('hashchange'))}
          />
        </div>
      )
    : pages[view];

  const signOut = async () => {
    setLogoutBusy(true);
    setLogoutError(false);
    try {
      await logout();
    } catch {
      // 后端未确认注销时保留当前界面与 Cookie 状态，避免共享设备产生“假退出”。
      setLogoutError(true);
    } finally {
      setLogoutBusy(false);
    }
  };

  const switchWorkspaceMode = async () => {
    if (
      !preferences?.experienceLevel
      || !preferences.assistancePreference
      || !preferences.firstGoal
      || !preferences.workspaceMode
    ) {
      setWorkspaceModeError(true);
      return;
    }
    const nextMode = preferences.workspaceMode === 'GUIDED' ? 'EXPERT' : 'GUIDED';
    setWorkspaceModeBusy(true);
    setWorkspaceModeError(false);
    try {
      await completeOnboarding({
        experienceLevel: preferences.experienceLevel,
        assistancePreference: preferences.assistancePreference,
        firstGoal: preferences.firstGoal,
        workspaceMode: nextMode,
      });
      navigate(nextMode === 'GUIDED' ? 'guided' : 'study');
    } catch {
      setWorkspaceModeError(true);
    } finally {
      setWorkspaceModeBusy(false);
    }
  };

  return (
    <Theme theme={isDark ? 'g100' : 'g10'} className="app-theme">
      <a className="skip-link" href="#main-content">{t('app.skip')}</a>
      <div className="app-shell">
        <header className="topbar">
          <div className="topbar__brand">
            <button
              ref={mobileMenuButtonRef}
              type="button"
              className="mobile-menu-button"
              aria-label={mobileNavOpen ? t('app.menuClose') : t('app.menuOpen')}
              aria-expanded={mobileNavOpen}
              aria-controls={MOBILE_NAVIGATION_ID}
              onClick={() => mobileNavOpen ? closeMobileNavigation() : setMobileNavOpen(true)}
            >
              {mobileNavOpen ? <X size={21} /> : <List size={21} />}
              <span className="sr-only">{mobileNavOpen ? t('app.menuClose') : t('app.menuOpen')}</span>
            </button>
            <div className="brand-mark" aria-hidden="true"><FloppyDiskBack size={22} weight="duotone" /></div>
            <div>
              <strong>{t('app.name')}</strong>
              <span>{t('app.workspace')}</span>
            </div>
          </div>
          <div className="topbar__controls">
            <ServiceStatus />
            <div className="account-summary" title={user?.email}>
              <UserCircle size={19} weight="duotone" aria-hidden="true" />
              <span>{user?.email}</span>
              {user?.role === 'ADMIN' ? <small>{t('app.adminRole')}</small> : null}
            </div>
            <Button
              className="workspace-mode-button"
              kind="ghost"
              size="sm"
              renderIcon={preferences?.workspaceMode === 'GUIDED' ? Books : Path}
              disabled={workspaceModeBusy}
              onClick={() => void switchWorkspaceMode()}
            >
              {preferences?.workspaceMode === 'GUIDED'
                ? t('app.switchToExpert')
                : t('app.switchToGuided')}
            </Button>
            <div className="language-toggle" role="group" aria-label={t('app.language')}>
              <button type="button" className={language === 'en' ? 'is-active' : ''} onClick={() => setLanguage('en')}>EN</button>
              <button type="button" className={language === 'zh-CN' ? 'is-active' : ''} onClick={() => setLanguage('zh-CN')}>中文</button>
            </div>
            <IconButton
              kind="ghost"
              size="sm"
              label={isDark ? t('app.themeLight') : t('app.themeDark')}
              onClick={onToggleTheme}
            >
              {isDark ? <Sun size={19} /> : <Moon size={19} />}
            </IconButton>
            <Button
              className="logout-button"
              kind="ghost"
              size="sm"
              renderIcon={SignOut}
              aria-label={logoutBusy ? t('app.signingOut') : t('app.signOut')}
              disabled={logoutBusy}
              onClick={() => void signOut()}
            >
              <span className="logout-button__label">
                {logoutBusy ? t('app.signingOut') : t('app.signOut')}
              </span>
            </Button>
          </div>
        </header>

        <aside className="sidebar" aria-label={t('app.primaryNavigation')}>
          <nav>
            <NavigationItems sections={navigation} view={view} onNavigate={navigate} />
          </nav>
          <SidebarFooter disclaimer={t('footer.disclaimer')} issueLabel={t('footer.issue')} />
        </aside>

        {mobileNavOpen ? (
          <button
            className="mobile-nav-backdrop"
            type="button"
            aria-label={t('app.menuClose')}
            onClick={() => closeMobileNavigation()}
          />
        ) : null}

        <aside
          ref={mobileNavigationRef}
          id={MOBILE_NAVIGATION_ID}
          className="mobile-navigation"
          role="dialog"
          aria-modal="true"
          aria-label={t('app.primaryNavigation')}
          hidden={!mobileNavOpen}
        >
          <nav aria-label={t('app.primaryNavigation')}>
            <NavigationItems sections={navigation} view={view} onNavigate={navigate} />
          </nav>
          <SidebarFooter disclaimer={t('footer.disclaimer')} issueLabel={t('footer.issue')} />
        </aside>

        <main id="main-content" className="main-content" tabIndex={-1}>
          {logoutError ? (
            <InlineNotification
              kind="error"
              lowContrast
              hideCloseButton
              title={t('app.signOutFailed')}
              subtitle={t('app.signOutFailedBody')}
            />
          ) : null}
          {workspaceModeError ? (
            <InlineNotification
              kind="error"
              lowContrast
              hideCloseButton
              title={t('app.workspaceModeFailed')}
              subtitle={t('app.workspaceModeFailedBody')}
            />
          ) : null}
          <ApiConnectionBanner />
          <Suspense fallback={<LoadingPanel />}>
            {currentPage}
          </Suspense>
          <footer className="product-footer">
            <p>{t('footer.copyright')}</p>
            <p>
              {t('footer.license')}{' '}
              <a href={GITHUB_REPOSITORY_URL} target="_blank" rel="noopener noreferrer">
                {t('footer.github')}
              </a>{' · '}
              <a href={GITHUB_ISSUE_CHOOSER_URL} target="_blank" rel="noopener noreferrer">
                {t('footer.issue')}
              </a>
            </p>
            <p>{t('footer.disclaimer')}</p>
          </footer>
        </main>
      </div>
    </Theme>
  );
}

function AuthenticationBoundary() {
  const { state, legalAcceptance, preferences } = useAuth();
  const [isDark, setIsDark] = useState(() => window.localStorage.getItem('eventshock-theme') === 'dark');

  useEffect(() => {
    window.localStorage.setItem('eventshock-theme', isDark ? 'dark' : 'light');
    document.documentElement.dataset.theme = isDark ? 'dark' : 'light';
  }, [isDark]);

  if (state === 'authenticated') {
    if (legalAcceptance?.required) {
      return (
        <Theme theme={isDark ? 'g100' : 'g10'} className="app-theme">
          <LegalAcceptancePage
            isDark={isDark}
            onToggleTheme={() => setIsDark((current) => !current)}
          />
        </Theme>
      );
    }
    if (preferences?.onboardingRequired) {
      return (
        <Theme theme={isDark ? 'g100' : 'g10'} className="app-theme">
          <OnboardingPage
            isDark={isDark}
            onToggleTheme={() => setIsDark((current) => !current)}
          />
        </Theme>
      );
    }
    return (
      <WorkflowProvider>
        <AppShell isDark={isDark} onToggleTheme={() => setIsDark((current) => !current)} />
      </WorkflowProvider>
    );
  }

  return (
    <Theme theme={isDark ? 'g100' : 'g10'} className="app-theme">
      {state === 'checking' ? (
        <div className="auth-loading"><LoadingPanel /></div>
      ) : (
        <AuthenticationPage isDark={isDark} onToggleTheme={() => setIsDark((current) => !current)} />
      )}
    </Theme>
  );
}

export function App() {
  return (
    <I18nProvider>
      <AuthProvider>
        <AuthenticationBoundary />
      </AuthProvider>
    </I18nProvider>
  );
}
