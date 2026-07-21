import { Button, Tag } from '@carbon/react';
import { ArrowRight, CalendarBlank, Flask, ShieldCheck, UsersThree } from '@phosphor-icons/react';
import { EmptyState, ErrorPanel, LoadingPanel, PageHeader, StatusBadge } from '../components/common';
import { useI18n } from '../i18n';
import { getPageGuide } from '../page-guidance';
import { useWorkflow } from '../state/workflow-context';
import type { ViewId } from '../app';

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

  const openCase = async (caseItem: (typeof cases)[number]) => {
    await selectCase(caseItem);
    navigate('pack');
  };

  const buildFromCase = async (caseItem: (typeof cases)[number]) => {
    await selectCase(caseItem);
    navigate('scenario');
  };

  return (
    <div className="page page--cases">
      <section className="home-intro">
        <div className="home-intro__copy">
          <span className="eyebrow">{t('home.eyebrow')}</span>
          <h1>{t('home.title')}</h1>
          <p>{t('home.subtitle')}</p>
          <section className="home-audience" aria-labelledby="home-audience-title">
            <div className="home-audience__label">
              <UsersThree size={20} weight="duotone" aria-hidden="true" />
              <span>{t('home.audienceLabel')}</span>
            </div>
            <div>
              <h2 id="home-audience-title">{t('home.audienceTitle')}</h2>
              <p>{t('home.audienceBody')}</p>
            </div>
          </section>
        </div>
        <div className="home-intro__guardrails" aria-label={t('common.limitations')}>
          <div><ShieldCheck size={22} weight="duotone" /><span>{t('home.disclaimerForecast')}</span></div>
          <div><ShieldCheck size={22} weight="duotone" /><span>{t('home.disclaimerAdvice')}</span></div>
          <div><Flask size={22} weight="duotone" /><span>{t('home.disclaimerSynthetic')}</span></div>
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
                    {caseItem.caseRole === 'HISTORICAL_VALIDATION_CASE' ? <Tag type="cool-gray" size="sm">{language === 'zh-CN' ? '历史验证候选案例' : 'Historical validation candidate'}</Tag> : null}
                    {caseItem.validationStatus ? <Tag type="warm-gray" size="sm">{caseItem.validationStatus.replaceAll('_', ' ')}</Tag> : null}
                    {caseItem.status ? <StatusBadge status={caseItem.status} /> : null}
                  </div>
                  <h2>{language === 'zh-CN' ? caseItem.nameZh ?? caseItem.name : caseItem.name}</h2>
                  <p>{language === 'zh-CN' ? caseItem.descriptionZh ?? caseItem.description ?? t('common.noData') : caseItem.description ?? t('common.noData')}</p>
                </div>
              </div>
              <div className="case-row__meta">
                {caseItem.updatedAt ? (
                  <span><CalendarBlank size={16} />{new Intl.DateTimeFormat(language, { dateStyle: 'medium' }).format(new Date(caseItem.updatedAt))}</span>
                ) : null}
                <div className="case-row__actions">
                  <Button kind="ghost" size="sm" onClick={() => void openCase(caseItem)}>{t('home.openPack')}</Button>
                  <Button kind="tertiary" size="sm" renderIcon={ArrowRight} onClick={() => void buildFromCase(caseItem)}>{t('home.startScenario')}</Button>
                </div>
              </div>
            </article>
          ))}
        </div>
      ) : null}
    </div>
  );
}
