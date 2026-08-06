import { useState } from 'react';
import { Button, Tag } from '@carbon/react';
import { ArrowRight, CalendarBlank, Flask, ShieldCheck, UsersThree, WarningCircle } from '@phosphor-icons/react';
import type { ViewId } from '../app';
import type { CaseSummary } from '../api/types';
import { EmptyState, ErrorPanel, LoadingPanel, PageHeader, StatusBadge } from '../components/common';
import { SyntheticInstrumentLabel } from '../components/synthetic-instrument-label';
import { useI18n } from '../i18n';
import { getPageGuide } from '../page-guidance';
import { useWorkflow } from '../state/workflow-context';

export function CaseDescription({
  text,
  instrument,
  isZh,
}: {
  text: string;
  instrument?: string;
  isZh: boolean;
}) {
  if (!instrument) return <>{text}</>;
  const escapedInstrument = instrument.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const parts = text.split(new RegExp(`(\\b${escapedInstrument}\\b)`, 'gi'));
  return (
    <>
      {parts.map((part, index) => part.toUpperCase() === instrument.toUpperCase()
        ? (
          <span className="case-description__instrument" key={`${part}-${index}`}>
            <code>{part}</code>
            <small>{isZh ? '合成市场代理' : 'synthetic market proxy'}</small>
          </span>
        )
        : part)}
    </>
  );
}

export function casePrimaryActionLabel(caseItem: CaseSummary, isZh: boolean): string {
  if (caseItem.eventPackReviewState === 'FROZEN' || caseItem.status?.toUpperCase() === 'FROZEN') {
    return isZh ? '构建情景' : 'Build scenario';
  }
  if (caseItem.eventPackReviewState === 'IN_PROGRESS') {
    return isZh ? '继续审核证据' : 'Continue evidence review';
  }
  return isZh ? '先审核证据' : 'Review evidence first';
}

export function CaseLibraryPage({ navigate }: { navigate: (view: ViewId) => void }) {
  const { language, t } = useI18n();
  const {
    cases,
    casesState,
    casesError,
    selectedCase,
    refreshCases,
    selectCase,
  } = useWorkflow();
  const [busyCaseId, setBusyCaseId] = useState<string>();

  const openCase = async (caseItem: (typeof cases)[number]) => {
    setBusyCaseId(caseItem.id);
    try {
      await selectCase(caseItem);
      navigate('pack');
    } catch {
      // 工作流上下文已保存可见错误；加载失败时留在案例库，不进入无效页面。
    } finally {
      setBusyCaseId(undefined);
    }
  };

  const buildFromCase = async (caseItem: (typeof cases)[number]) => {
    setBusyCaseId(caseItem.id);
    try {
      const nextPack = await selectCase(caseItem);
      const isFrozen = nextPack.status.toUpperCase() === 'FROZEN' || Boolean(nextPack.frozenAt);
      navigate(isFrozen ? 'scenario' : 'pack');
    } catch {
      // 工作流上下文已保存可见错误；不得在 Event Pack 未加载时继续导航。
    } finally {
      setBusyCaseId(undefined);
    }
  };

  const validationStatusLabel = (status: string) => {
    if (status === 'L5_CASE_AVAILABLE') return t('home.validationRunnableOnly');
    if (status === 'PENDING_HUMAN_STUDY') return t('home.validationPendingStudy');
    if (status === 'NOT_HISTORICALLY_CALIBRATED') return t('home.validationNotCalibrated');
    return t('home.validationReviewRequired');
  };

  const validationStatusLabels = (
    status: NonNullable<(typeof cases)[number]['validationStatus']>,
  ) => [...new Set([
    status.level,
    status.empiricalCalibration,
  ].filter((value): value is string => Boolean(value)).map(validationStatusLabel))];

  return (
    <div className="page page--cases">
      <section className="home-intro">
        <div className="home-intro__copy">
          <span className="eyebrow">{t('home.eyebrow')}</span>
          <h1>{t('home.title')}</h1>
          <p>{t('home.subtitle')}</p>
          <p className="home-intro__explainer">{t('home.plainExplainer')}</p>
          <Button
            className="home-intro__cta"
            kind="tertiary"
            renderIcon={ArrowRight}
            onClick={() => navigate('factory')}
          >
            {t('home.addCase')}
          </Button>
        </div>
        <div className="home-boundary" aria-label={t('common.limitations')}>
          <section className="home-boundary__panel" aria-labelledby="home-audience-title">
            <div className="home-boundary__label">
              <UsersThree size={20} weight="duotone" aria-hidden="true" />
              <span>{t('home.audienceLabel')}</span>
            </div>
            <h2 id="home-audience-title">{t('home.audienceTitle')}</h2>
            <p>{t('home.audienceBody')}</p>
            <div className="home-boundary__guardrail">
              <ShieldCheck size={18} weight="duotone" aria-hidden="true" />
              <span>{t('home.disclaimerSynthetic')}</span>
            </div>
            <div className="home-boundary__guardrail">
              <ShieldCheck size={18} weight="duotone" aria-hidden="true" />
              <span>{t('home.resilience')}</span>
            </div>
          </section>
          <section className="home-boundary__panel home-boundary__panel--excluded" aria-labelledby="home-not-audience-title">
            <div className="home-boundary__label">
              <WarningCircle size={20} weight="duotone" aria-hidden="true" />
              <span>{t('home.notAudienceLabel')}</span>
            </div>
            <h2 id="home-not-audience-title">{t('home.notAudienceTitle')}</h2>
            <p>{t('home.notAudienceBody')}</p>
            <h3>{t('home.notProvidedTitle')}</h3>
            <ul>
              <li>{t('home.notProvidedDirection')}</li>
              <li>{t('home.notProvidedTiming')}</li>
              <li>{t('home.notProvidedTarget')}</li>
              <li>{t('home.notProvidedReality')}</li>
            </ul>
          </section>
        </div>
      </section>

      <PageHeader title={t('home.caseHeading')} subtitle={t('home.caseBody')} guide={getPageGuide('cases', language)} />

      {casesState === 'loading' || casesState === 'idle' ? <LoadingPanel /> : null}
      {casesState === 'error' ? <ErrorPanel detail={casesError} onRetry={() => void refreshCases()} /> : null}
      {casesState === 'success' && cases.length === 0 ? (
        <EmptyState title={t('home.emptyTitle')} body={t('home.emptyBody')} />
      ) : null}

      {casesState === 'success' && cases.length > 0 ? (
        <div className="case-list">
          {cases.map((caseItem) => (
            <article key={caseItem.id} className={`case-row ${selectedCase?.id === caseItem.id ? 'case-row--selected' : ''}`}>
              <div className="case-row__identity">
                <div className="case-row__icon" aria-hidden="true"><Flask size={24} weight="duotone" /></div>
                <div>
                  <div className="case-row__tags">
                    {caseItem.isSynthetic ? <Tag type="warm-gray" size="sm">{language === 'zh-CN' ? caseItem.syntheticLabelZh ?? t('status.synthetic') : caseItem.syntheticLabel ?? t('status.synthetic')}</Tag> : null}
                    {caseItem.featured ? <Tag type="blue" size="sm">{language === 'zh-CN' ? '旗舰样本外演示' : 'Flagship out-of-sample demo'}</Tag> : null}
                    {caseItem.caseRole === 'HISTORICAL_VALIDATION_CASE' ? <Tag type="cool-gray" size="sm">{t('home.historicalComparison')}</Tag> : null}
                    {caseItem.validationStatus
                      ? validationStatusLabels(caseItem.validationStatus).map((label) => (
                        <Tag key={label} type="warm-gray" size="sm">{label}</Tag>
                      ))
                      : null}
                    {caseItem.status ? <StatusBadge status={caseItem.status} /> : null}
                  </div>
                  <h2>{language === 'zh-CN' ? caseItem.nameZh ?? caseItem.name : caseItem.name}</h2>
                  <p>
                    <CaseDescription
                      text={language === 'zh-CN' ? caseItem.descriptionZh ?? caseItem.description ?? t('common.noData') : caseItem.description ?? t('common.noData')}
                      instrument={caseItem.instrument}
                      isZh={language === 'zh-CN'}
                    />
                  </p>
                  {caseItem.instrument ? <SyntheticInstrumentLabel instrument={caseItem.instrument} compact /> : null}
                </div>
              </div>
              <div className="case-row__meta">
                {caseItem.updatedAt ? (
                  <span><CalendarBlank size={16} />{new Intl.DateTimeFormat(language, { dateStyle: 'medium' }).format(new Date(caseItem.updatedAt))}</span>
                ) : null}
                <div className="case-row__actions">
                  <Button kind="ghost" size="sm" disabled={busyCaseId === caseItem.id} onClick={() => void openCase(caseItem)}>{t('home.openPack')}</Button>
                  <Button kind="tertiary" size="sm" renderIcon={ArrowRight} disabled={busyCaseId === caseItem.id} onClick={() => void buildFromCase(caseItem)}>
                    {busyCaseId === caseItem.id ? t('common.loading') : casePrimaryActionLabel(caseItem, language === 'zh-CN')}
                  </Button>
                </div>
              </div>
            </article>
          ))}
        </div>
      ) : null}
    </div>
  );
}
