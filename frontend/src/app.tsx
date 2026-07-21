import { IconButton, Theme } from '@carbon/react';
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
import { CaseLibraryPage } from './pages/case-library-page';
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

export type ViewId = 'cases' | 'pack' | 'ai' | 'scenario' | 'preflight' | 'runs' | 'results' | 'study' | 'trace' | 'governance' | 'export';
export type Navigate = (view: ViewId, experimentId?: string) => void;

const VIEW_IDS: ViewId[] = ['cases', 'pack', 'ai', 'scenario', 'preflight', 'runs', 'results', 'study', 'trace', 'governance', 'export'];
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

function NavigationItems({
  items,
  view,
  onNavigate,
}: {
  items: NavigationItem[];
  view: ViewId;
  onNavigate: (view: ViewId) => void;
}) {
  return (
    <>
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <button
            key={item.id}
            type="button"
            className={view === item.id ? 'is-active' : ''}
            aria-current={view === item.id ? 'page' : undefined}
            onClick={() => onNavigate(item.id)}
          >
            <Icon size={19} weight={view === item.id ? 'fill' : 'regular'} />
            <span>{item.label}</span>
          </button>
        );
      })}
    </>
  );
}

function AppShell() {
  const { language, setLanguage, t } = useI18n();
  const { cancelPendingExperimentRequests, loadResults, selectExperiment } = useWorkflow();
  const loadResultsRef = useRef(loadResults);
  const routeGenerationRef = useRef(0);
  const [view, setView] = useState<ViewId>(() => parseAppRoute(window.location.hash).view);
  const [isDark, setIsDark] = useState(() => window.localStorage.getItem('eventshock-theme') === 'dark');
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const mobileMenuButtonRef = useRef<HTMLButtonElement>(null);
  const mobileNavigationRef = useRef<HTMLElement>(null);

  useEffect(() => {
    loadResultsRef.current = loadResults;
  }, [loadResults]);

  useEffect(() => {
    window.localStorage.setItem('eventshock-theme', isDark ? 'dark' : 'light');
    document.documentElement.dataset.theme = isDark ? 'dark' : 'light';
  }, [isDark]);

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

  const navigation = useMemo<NavigationItem[]>(() => [
    { id: 'cases', label: t('nav.cases'), icon: Books },
    { id: 'pack', label: t('nav.pack'), icon: ClipboardText },
    { id: 'ai', label: t('nav.ai'), icon: Cpu },
    { id: 'scenario', label: t('nav.scenario'), icon: SlidersHorizontal },
    { id: 'preflight', label: t('nav.preflight'), icon: CheckSquare },
    { id: 'runs', label: t('nav.runs'), icon: PlayCircle },
    { id: 'results', label: t('nav.results'), icon: ChartLineUp },
    { id: 'study', label: t('nav.study'), icon: Flask },
    { id: 'trace', label: t('nav.trace'), icon: TreeStructure },
    { id: 'governance', label: t('nav.governance'), icon: ShieldCheck },
    { id: 'export', label: t('nav.export'), icon: Archive },
  ], [t]);

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
            <div className="language-toggle" role="group" aria-label={t('app.language')}>
              <button type="button" className={language === 'en' ? 'is-active' : ''} onClick={() => setLanguage('en')}>EN</button>
              <button type="button" className={language === 'zh-CN' ? 'is-active' : ''} onClick={() => setLanguage('zh-CN')}>中文</button>
            </div>
            <IconButton
              kind="ghost"
              size="sm"
              label={isDark ? t('app.themeLight') : t('app.themeDark')}
              onClick={() => setIsDark((current) => !current)}
            >
              {isDark ? <Sun size={19} /> : <Moon size={19} />}
            </IconButton>
          </div>
        </header>

        <aside className="sidebar" aria-label={t('app.primaryNavigation')}>
          <nav>
            <NavigationItems items={navigation} view={view} onNavigate={navigate} />
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
            <NavigationItems items={navigation} view={view} onNavigate={navigate} />
          </nav>
          <footer className="sidebar__footer">
            <p>{t('footer.disclaimer')}</p>
          </footer>
        </aside>

        <main id="main-content" className="main-content" tabIndex={-1}>
          <ApiConnectionBanner />
          <Suspense fallback={<LoadingPanel />}>
            {pages[view]}
          </Suspense>
          <footer className="product-footer">
            <p>{t('footer.copyright')}</p>
            <p>{t('footer.license')}</p>
            <p>{t('footer.disclaimer')}</p>
          </footer>
        </main>
      </div>
    </Theme>
  );
}

export function App() {
  return (
    <I18nProvider>
      <WorkflowProvider>
        <AppShell />
      </WorkflowProvider>
    </I18nProvider>
  );
}
