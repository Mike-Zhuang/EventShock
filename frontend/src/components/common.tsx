import {
  Button,
  InlineNotification,
  Popover,
  PopoverContent,
  SkeletonText,
  Tag,
} from '@carbon/react';
import {
  ArrowClockwise,
  CheckCircle,
  CloudSlash,
  Compass,
  Database,
  Info,
  WarningCircle,
} from '@phosphor-icons/react';
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { GITHUB_ISSUE_CHOOSER_URL } from '../external-links';
import { translateStatus, useI18n } from '../i18n';
import type { PageGuideContent } from '../page-guidance';
import { useWorkflow, type RequestState } from '../state/workflow-context';

export function PageHeader({
  title,
  subtitle,
  actions,
  guide,
  headingId,
}: {
  title: string;
  subtitle: string;
  actions?: ReactNode;
  guide?: PageGuideContent;
  headingId?: string;
}) {
  return (
    <>
      <header className="page-header">
        <div>
          <h1 id={headingId}>{title}</h1>
          <p>{subtitle}</p>
        </div>
        {actions ? <div className="page-header__actions">{actions}</div> : null}
      </header>
      {guide ? <PageGuide guide={guide} /> : null}
    </>
  );
}

export function PageGuide({ guide }: { guide: PageGuideContent }) {
  return (
    <aside className="page-guide" aria-label={guide.label}>
      <div className="page-guide__label">
        <Compass size={19} weight="duotone" aria-hidden="true" />
        <strong>{guide.label}</strong>
        {guide.optional ? <span>{guide.label === '本页怎么做' ? '高级可选' : 'Advanced · optional'}</span> : null}
      </div>
      <ol>
        {guide.steps.map((step) => <li key={step}>{step}</li>)}
      </ol>
    </aside>
  );
}

export function ExplainedLabel({
  label,
  explanation,
}: {
  label: ReactNode;
  explanation: string;
}) {
  return (
    <span className="explained-label">
      <span>{label}</span>
      <ParameterHelp
        label={typeof label === 'string' ? label : undefined}
        explanation={explanation}
      />
    </span>
  );
}

type ParameterHelpOpenMode = 'hover' | 'focus' | 'click';

let closeActiveParameterHelp: (() => void) | undefined;

export function ParameterHelp({
  label,
  explanation,
}: {
  label?: string;
  explanation: string;
}) {
  const { language } = useI18n();
  const [openMode, setOpenMode] = useState<ParameterHelpOpenMode>();
  const popoverRef = useRef<HTMLSpanElement>(null);
  const pointerFocusRef = useRef(false);
  const tooltipId = useId();
  const open = openMode !== undefined;
  const genericLabel = language === 'zh-CN' ? '查看参数说明' : 'View parameter help';
  const accessibilityLabel = label
    ? language === 'zh-CN' ? `查看“${label}”的参数说明` : `View parameter help for ${label}`
    : genericLabel;

  const close = useCallback(() => {
    setOpenMode(undefined);
    if (closeActiveParameterHelp === close) closeActiveParameterHelp = undefined;
  }, []);

  const openWithMode = useCallback((mode: ParameterHelpOpenMode) => {
    if (closeActiveParameterHelp && closeActiveParameterHelp !== close) {
      closeActiveParameterHelp();
    }
    closeActiveParameterHelp = close;
    setOpenMode(mode);
  }, [close]);

  useEffect(() => () => {
    if (closeActiveParameterHelp === close) closeActiveParameterHelp = undefined;
  }, [close]);

  useEffect(() => {
    close();
  }, [close, explanation, label]);

  useEffect(() => {
    if (!open) return undefined;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close();
    };
    const closeOnOutsidePointerDown = (event: PointerEvent) => {
      if (
        event.target instanceof Node
        && !popoverRef.current?.contains(event.target)
      ) {
        close();
      }
    };
    window.addEventListener('keydown', closeOnEscape);
    window.addEventListener('scroll', close, true);
    window.addEventListener('hashchange', close);
    window.addEventListener('popstate', close);
    document.addEventListener('pointerdown', closeOnOutsidePointerDown, true);
    return () => {
      window.removeEventListener('keydown', closeOnEscape);
      window.removeEventListener('scroll', close, true);
      window.removeEventListener('hashchange', close);
      window.removeEventListener('popstate', close);
      document.removeEventListener('pointerdown', closeOnOutsidePointerDown, true);
    };
  }, [close, open]);

  return (
    <Popover
      ref={popoverRef}
      align="top"
      autoAlign
      caret
      dropShadow
      open={open}
      onRequestClose={close}
    >
      <button
        type="button"
        className="explained-label__trigger"
        aria-label={accessibilityLabel}
        aria-describedby={tooltipId}
        aria-expanded={open}
        onBlur={() => {
          pointerFocusRef.current = false;
          close();
        }}
        onClick={() => {
          if (openMode === 'click') close();
          else openWithMode('click');
        }}
        onFocus={() => {
          if (!pointerFocusRef.current && openMode !== 'click') openWithMode('focus');
        }}
        onMouseEnter={() => {
          if (openMode === undefined) openWithMode('hover');
        }}
        onMouseLeave={() => {
          if (openMode === 'hover') close();
        }}
        onPointerCancel={() => {
          pointerFocusRef.current = false;
        }}
        onPointerDown={() => {
          pointerFocusRef.current = true;
        }}
        onPointerUp={() => {
          pointerFocusRef.current = false;
        }}
      >
        <Info size={15} weight="fill" aria-hidden="true" />
      </button>
      <PopoverContent id={tooltipId} role="tooltip" className="parameter-help-content">
        {explanation}
      </PopoverContent>
    </Popover>
  );
}

export function LoadingPanel({ label }: { label?: string }) {
  const { t } = useI18n();
  return (
    <div className="state-panel state-panel--loading" role="status" aria-live="polite">
      <div className="state-panel__skeleton" aria-hidden="true">
        <SkeletonText heading width="36%" />
        <SkeletonText paragraph lineCount={3} width="76%" />
      </div>
      <span className="sr-only">{label ?? t('common.loading')}</span>
    </div>
  );
}

export function EmptyState({
  title,
  body,
  action,
  icon = <Database size={28} weight="duotone" />,
}: {
  title: string;
  body: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <section className="state-panel state-panel--empty">
      <div className="state-panel__icon" aria-hidden="true">{icon}</div>
      <h2>{title}</h2>
      <p>{body}</p>
      {action ? <div className="state-panel__action">{action}</div> : null}
    </section>
  );
}

export function ErrorPanel({
  title,
  body,
  detail,
  onRetry,
  savedState,
  costState,
  dataSafety,
  nextStep,
  traceId,
}: {
  title?: string;
  body?: string;
  detail?: string;
  onRetry?: () => void;
  savedState?: string;
  costState?: string;
  dataSafety?: string;
  nextStep?: string;
  traceId?: string;
}) {
  const { language, t } = useI18n();
  const isZh = language === 'zh-CN';
  const inferredTraceId = traceId
    ?? detail?.match(/(?:trace(?:\s*id)?|追踪(?:号| ID)?)[:：]\s*([A-Za-z0-9_-]+)/i)?.[1];
  return (
    <section className="state-panel state-panel--error" role="alert">
      <div className="state-panel__icon" aria-hidden="true"><WarningCircle size={28} weight="duotone" /></div>
      <h2>{title ?? t('common.errorTitle')}</h2>
      <p>{body ?? t('common.errorFallback')}</p>
      <dl className="state-panel__impact">
        <div>
          <dt>{isZh ? '保存状态' : 'Save status'}</dt>
          <dd>{savedState ?? (isZh ? '未确认成功；请以重新加载后的服务器状态为准。' : 'Not confirmed; rely on the server state after reloading.')}</dd>
        </div>
        <div>
          <dt>{isZh ? '费用状态' : 'Cost status'}</dt>
          <dd>{costState ?? (isZh ? '当前错误没有提供费用结论；付费请求请先查历史再重试。' : 'This error provides no cost conclusion; check history before retrying a paid request.')}</dd>
        </div>
        <div>
          <dt>{isZh ? '数据安全' : 'Data safety'}</dt>
          <dd>{dataSafety ?? (isZh ? '此处不显示敏感请求内容；不要把 Key、Cookie 或完整请求头提交到 Issue。' : 'Sensitive request content is not shown here; never put keys, cookies, or full headers in an issue.')}</dd>
        </div>
        <div>
          <dt>{isZh ? '下一步' : 'Next step'}</dt>
          <dd>{nextStep ?? (onRetry
            ? isZh ? '确认配置和网络后重试一次；仍失败时携带脱敏追踪号提交 Issue。' : 'Verify configuration and network, retry once, then file an issue with a redacted trace ID.'
            : isZh ? '重新加载当前页面核对状态；仍失败时携带脱敏追踪号提交 Issue。' : 'Reload this page to verify state, then file an issue with a redacted trace ID.')}</dd>
        </div>
      </dl>
      {detail ? <details><summary>{t('common.details')}</summary><code>{detail}</code></details> : null}
      <div className="state-panel__actions">
        {onRetry ? (
          <Button kind="tertiary" size="sm" renderIcon={ArrowClockwise} onClick={onRetry}>
            {t('common.retry')}
          </Button>
        ) : null}
        <a href={GITHUB_ISSUE_CHOOSER_URL} target="_blank" rel="noopener noreferrer">
          {isZh ? '提交脱敏 Issue' : 'File a redacted issue'}
        </a>
      </div>
      {inferredTraceId ? <p className="state-panel__trace">{isZh ? '追踪号' : 'Trace ID'}: <code>{inferredTraceId}</code></p> : null}
    </section>
  );
}

export function RequestBoundary({
  state,
  error,
  children,
  empty,
  isEmpty = false,
}: {
  state: RequestState;
  error?: string;
  children: ReactNode;
  empty?: ReactNode;
  isEmpty?: boolean;
}) {
  if (state === 'loading' || state === 'idle') return <LoadingPanel />;
  if (state === 'error') return <ErrorPanel detail={error} />;
  if (isEmpty && empty) return <>{empty}</>;
  return <>{children}</>;
}

export function StatusBadge({ status, type }: { status: string; type?: 'gray' | 'blue' | 'green' | 'red' | 'warm-gray' }) {
  const { t } = useI18n();
  const upper = status.toUpperCase();
  const tagType = type ?? (
    ['COMPLETED', 'FROZEN', 'HUMAN_APPROVED', 'VALID'].includes(upper) ? 'green'
      : upper.startsWith('FAILED') || ['REJECTED', 'INVALID', 'INVALIDATED'].includes(upper) ? 'red'
        : ['RUNNING', 'QUEUED', 'AGGREGATING', 'CANCEL_REQUESTED', 'AI_PROPOSED'].includes(upper) ? 'blue'
          : 'gray'
  );
  const label = translateStatus(status, t);
  return <Tag type={tagType} size="sm" title={label} aria-label={label}>{label}</Tag>;
}

export function ApiConnectionBanner() {
  const { t } = useI18n();
  const { apiConnection, refreshAll } = useWorkflow();
  if (apiConnection !== 'offline') return null;
  return (
    <div className="connection-banner">
      <InlineNotification
        kind="error"
        lowContrast
        hideCloseButton
        title={t('error.offlineTitle')}
        subtitle={t('error.offlineBody')}
      />
      <Button kind="ghost" size="sm" renderIcon={ArrowClockwise} onClick={() => void refreshAll()}>
        {t('common.retry')}
      </Button>
    </div>
  );
}

export function CheckRow({
  passed,
  label,
  detail,
  severity,
}: {
  passed: boolean;
  label: string;
  detail?: string;
  severity?: 'info' | 'warning' | 'error';
}) {
  const isWarning = passed && severity === 'warning';
  return (
    <div className={`check-row ${isWarning ? 'check-row--warning' : passed ? 'check-row--passed' : 'check-row--failed'}`}>
      <div aria-hidden="true">
        {passed && !isWarning ? <CheckCircle size={20} weight="fill" /> : <WarningCircle size={20} weight="fill" />}
      </div>
      <div>
        <strong>{label}</strong>
        {detail ? <p>{detail}</p> : null}
      </div>
    </div>
  );
}

export function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="research-notice">
      <Info size={20} weight="fill" aria-hidden="true" />
      <p>{children}</p>
    </div>
  );
}

export function ServiceStatus() {
  const { t } = useI18n();
  const { apiConnection } = useWorkflow();
  const label = apiConnection === 'online'
    ? t('status.online')
    : apiConnection === 'offline'
      ? t('status.offline')
      : t('status.checking');
  return (
    <span className={`service-status service-status--${apiConnection}`}>
      {apiConnection === 'offline' ? <CloudSlash size={16} /> : null}
      <span>{label}</span>
    </span>
  );
}
