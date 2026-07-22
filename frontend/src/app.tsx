import { Button, IconButton, InlineNotification, Theme } from '@carbon/react';
import {
  Archive,
  Books,
  ChartLineUp,
  CheckSquare,
  ClipboardText,
  Cpu,
  FloppyDiskBack,
  Flask,
  List,
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
import { ApiConnectionBanner, LoadingPanel, ServiceStatus } from './components/common';
import { I18nProvider, useI18n } from './i18n';
import { AuthenticationPage } from './pages/authentication-page';
import { CaseLibraryPage } from './pages/case-library-page';
import { AuthProvider, useAuth } from './state/auth-context';
import { useWorkflow, WorkflowProvider } from './state/workflow-context';

const EventPackPage = lazy(async () => ({ default: (await import('./pages/event-pack-page')).EventPackPage }));
const AiConfigurationPage = lazy(async () => ({ default: (await import('./pages/ai-configuration-page')).AiConfigurationPage }));
const ExportHistoryPage = lazy(async () => ({ default: (await import('./pages/export-history-page')).ExportHistoryPage }));
const GovernancePage = lazy(async () => ({ default: (await import('./pages/governance-page')).GovernancePage }));
const PreflightPage = lazy(async () => ({ default: (await import('./pages/preflight-page')).PreflightPage }));
const ResultsPage = lazy(async () => ({ default: (await import('./pages/results-page')).ResultsPage }));
const RunCenterPage = lazy(async () => ({ default: (await import('./pages/run-center-page')).RunCenterPage }));
const ScenarioBuilderPage = lazy(async () => ({ default: (await import('./pages/scenario-builder-page')).ScenarioBuilderPage }));
const StudyWorkbenchPage = lazy(async () => ({ default: (await import('./pages/study-workbench-page')).StudyWorkbenchPage }));
const TraceExplorerPage = lazy(async () => ({ default: (await import('./pages/trace-explorer-page')).TraceExplorerPage }));
const AdminPage = lazy(async () => ({ default: (await import('./pages/admin-page')).AdminPage }));

export type ViewId = 'cases' | 'pack' | 'ai' | 'scenario' | 'preflight' | 'runs' | 'results' | 'study' | 'trace' | 'governance' | 'export' | 'admin';
export type Navigate = (view: ViewId, experimentId?: string) => void;

const VIEW_IDS: ViewId[] = ['cases', 'pack', 'ai', 'scenario', 'preflight', 'runs', 'results', 'study', 'trace', 'governance', 'export', 'admin'];
const MOBILE_NAVIGATION_ID = 'mobile-primary-navigation';

interface NavigationItem {
  id: ViewId;
  label: string;
  icon: ComponentType<{ size?: number; weight?: 'regular' | 'fill' }>;
}

export function parseAppRoute(hash: string): { view: ViewId; experimentId?: string } {
  const [rawView, rawQuery = ''] = hash.replace(/^#\/?/, '').split('?', 2);
  const view = VIEW_IDS.includes(rawView as ViewId) ? rawView as ViewId : 'cases';
  const experimentId = new URLSearchParams(rawQuery).get('experimentId') || undefined;
  return { view, experimentId };
}

export function buildAppHash(view: ViewId, experimentId?: string): string {
  if (view !== 'results' || !experimentId) return `#/${view}`;
  return `#/${view}?${new URLSearchParams({ experimentId }).toString()}`;
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
  const { user, logout } = useAuth();
  const { cancelPendingExperimentRequests, loadResults, selectExperiment } = useWorkflow();
  const loadResultsRef = useRef(loadResults);
  const routeGenerationRef = useRef(0);
  const [view, setView] = useState<ViewId>(() => parseAppRoute(window.location.hash).view);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [logoutBusy, setLogoutBusy] = useState(false);
  const [logoutError, setLogoutError] = useState(false);
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
      if (!cancelled) setView(route.view);
      if (route.view !== 'results' || !route.experimentId) return;
      try {
        const experiment = await selectExperiment(route.experimentId);
        if (
          experiment
          && !cancelled
          && currentGeneration === routeGenerationRef.current
          && experiment.status === 'COMPLETED'
        ) {
          await loadResultsRef.current(experiment.id);
        }
      } catch {
        // 工作流上下文已经记录可展示的错误；路由仍保留，便于刷新或审计链接。
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

  const navigate: Navigate = (nextView, experimentId) => {
    routeGenerationRef.current += 1;
    cancelPendingExperimentRequests();
    setView(nextView);
    setMobileNavOpen(false);
    window.history.replaceState(null, '', buildAppHash(nextView, experimentId));
    document.getElementById('main-content')?.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: 'auto' });
  };

  useEffect(() => {
    if (view === 'admin' && user?.role !== 'ADMIN') navigate('cases');
  }, [user?.role, view]);

  const navigation = useMemo<NavigationSection[]>(() => {
    const sections: NavigationSection[] = [
      {
        label: t('nav.groupCore'),
        items: [
          { id: 'cases', label: t('nav.cases'), icon: Books },
          { id: 'pack', label: t('nav.pack'), icon: ClipboardText },
          { id: 'scenario', label: t('nav.scenario'), icon: SlidersHorizontal },
          { id: 'preflight', label: t('nav.preflight'), icon: CheckSquare },
          { id: 'runs', label: t('nav.runs'), icon: PlayCircle },
          { id: 'results', label: t('nav.results'), icon: ChartLineUp },
        ],
      },
      {
        label: t('nav.groupOptional'),
        items: [
          { id: 'ai', label: t('nav.ai'), icon: Cpu },
          { id: 'study', label: t('nav.study'), icon: Flask },
          { id: 'trace', label: t('nav.trace'), icon: TreeStructure },
          { id: 'governance', label: t('nav.governance'), icon: ShieldCheck },
          { id: 'export', label: t('nav.export'), icon: Archive },
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
    cases: <CaseLibraryPage navigate={navigate} />,
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
    admin: <AdminPage />,
  };

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
          <footer className="sidebar__footer">
            <p>{t('footer.disclaimer')}</p>
          </footer>
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
          <footer className="sidebar__footer">
            <p>{t('footer.disclaimer')}</p>
          </footer>
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
          <ApiConnectionBanner />
          <Suspense fallback={<LoadingPanel />}>
            {pages[view]}
          </Suspense>
          <footer className="product-footer">
            <p>{t('footer.copyright')}</p>
            <p>
              {t('footer.license')}{' '}
              <a href="https://github.com/Mike-Zhuang/EventShock" target="_blank" rel="noreferrer">
                {t('footer.github')}
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
  const { state } = useAuth();
  const [isDark, setIsDark] = useState(() => window.localStorage.getItem('eventshock-theme') === 'dark');

  useEffect(() => {
    window.localStorage.setItem('eventshock-theme', isDark ? 'dark' : 'light');
    document.documentElement.dataset.theme = isDark ? 'dark' : 'light';
  }, [isDark]);

  if (state === 'authenticated') {
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
