import { Button, DefinitionTooltip, InlineNotification, SkeletonText, Tag } from '@carbon/react';
import {
  ArrowClockwise,
  CheckCircle,
  CloudSlash,
  Compass,
  Database,
  Info,
  WarningCircle,
} from '@phosphor-icons/react';
import type { ReactNode } from 'react';
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

export function ParameterHelp({
  label,
  explanation,
}: {
  label?: string;
  explanation: string;
}) {
  const { language } = useI18n();
  const genericLabel = language === 'zh-CN' ? '查看参数说明' : 'View parameter help';
  const accessibilityLabel = label
    ? language === 'zh-CN' ? `查看“${label}”的参数说明` : `View parameter help for ${label}`
    : genericLabel;

  return (
    <DefinitionTooltip
      definition={explanation}
      align="top"
      autoAlign
      openOnHover
      aria-label={accessibilityLabel}
      triggerClassName="explained-label__trigger"
    >
      <Info size={15} weight="fill" aria-hidden="true" />
    </DefinitionTooltip>
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
}: {
  title?: string;
  body?: string;
  detail?: string;
  onRetry?: () => void;
}) {
  const { t } = useI18n();
  return (
    <section className="state-panel state-panel--error" role="alert">
      <div className="state-panel__icon" aria-hidden="true"><WarningCircle size={28} weight="duotone" /></div>
      <h2>{title ?? t('common.errorTitle')}</h2>
      <p>{body ?? t('common.errorFallback')}</p>
      {detail ? <details><summary>{t('common.details')}</summary><code>{detail}</code></details> : null}
      {onRetry ? (
        <Button kind="tertiary" size="sm" renderIcon={ArrowClockwise} onClick={onRetry}>
          {t('common.retry')}
        </Button>
      ) : null}
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
  return <Tag type={tagType} size="sm">{translateStatus(status, t)}</Tag>;
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
