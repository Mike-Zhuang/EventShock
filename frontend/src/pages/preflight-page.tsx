import { Button, InlineNotification } from '@carbon/react';
import { ArrowLeft, Play, ShieldCheck } from '@phosphor-icons/react';
import { useEffect, useState } from 'react';
import type { ViewId } from '../app';
import { CheckRow, EmptyState, Notice, PageHeader, StatusBadge } from '../components/common';
import { translateParameter, translateValidation, useI18n } from '../i18n';
import { useWorkflow } from '../state/workflow-context';

export function PreflightPage({ navigate }: { navigate: (view: ViewId) => void }) {
  const { language, t } = useI18n();
  const {
    eventPack,
    scenario,
    validation,
    experimentsState,
    experimentsError,
    createAndStartExperiment,
  } = useWorkflow();
  const [confirmations, setConfirmations] = useState([
    Boolean(scenario.acknowledgedScenarioNotForecast),
    false,
    false,
  ]);
  const [startError, setStartError] = useState<string>();
  const allConfirmed = confirmations.every(Boolean);

  useEffect(() => {
    setConfirmations((current) => [Boolean(scenario.acknowledgedScenarioNotForecast), current[1], current[2]]);
  }, [scenario.acknowledgedScenarioNotForecast]);

  const toggleConfirmation = (index: number) => {
    setConfirmations((current) => current.map((value, itemIndex) => itemIndex === index ? !value : value));
  };

  const start = async () => {
    setStartError(undefined);
    try {
      await createAndStartExperiment();
      navigate('runs');
    } catch (error) {
      setStartError(error instanceof Error ? error.message : String(error));
    }
  };

  if (!validation) {
    return (
      <div className="page">
        <PageHeader title={t('preflight.title')} subtitle={t('preflight.subtitle')} />
        <EmptyState
          title={t('preflight.notValidated')}
          body={t('scenario.interventionHelp')}
          icon={<ShieldCheck size={28} weight="duotone" />}
          action={<Button kind="tertiary" onClick={() => navigate('scenario')}>{t('nav.scenario')}</Button>}
        />
      </div>
    );
  }

  return (
    <div className="page page--preflight">
      <PageHeader
        title={t('preflight.title')}
        subtitle={t('preflight.subtitle')}
        actions={(
          <div className="page-header-action-group">
            <StatusBadge status={validation.valid ? 'VALID' : 'INVALID'} />
            <Button kind="ghost" renderIcon={ArrowLeft} onClick={() => navigate('scenario')}>{t('common.back')}</Button>
          </div>
        )}
      />

      {!validation.valid ? (
        <InlineNotification kind="error" lowContrast hideCloseButton title={t('scenario.validationFailed')} subtitle={validation.checks.filter((check) => !check.passed).map((check) => translateValidation(check.id, check.detail, t)).join(' ')} />
      ) : null}
      {startError || experimentsError ? (
        <InlineNotification kind="error" lowContrast hideCloseButton title={t('common.errorTitle')} subtitle={t('common.errorFallback')} />
      ) : null}

      <div className="preflight-grid">
        <section className="preflight-panel">
          <div className="section-heading">
            <h2>{t('preflight.experimentPlan')}</h2>
          </div>
          <dl className="definition-list">
            <div><dt>{t('scenario.eventPack')}</dt><dd>{language === 'zh-CN' ? eventPack?.nameZh ?? eventPack?.name ?? scenario.eventPackId : eventPack?.name ?? scenario.eventPackId}</dd></div>
            <div><dt>{t('scenario.researchQuestion')}</dt><dd>{language === 'zh-CN' ? scenario.questionZh ?? scenario.question : scenario.question}</dd></div>
            <div><dt>{t('pack.pointInTime')}</dt><dd>{eventPack?.pointInTime ? new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(eventPack.pointInTime)) : t('common.unavailable')}</dd></div>
            <div><dt>{t('scenario.interventionLabel')}</dt><dd>{translateParameter(scenario.intervention.parameter, t)}</dd></div>
            <div><dt>{t('common.baseline')}</dt><dd>{scenario.intervention.baselineValue}</dd></div>
            <div><dt>{t('common.intervention')}</dt><dd>{scenario.intervention.interventionValue}</dd></div>
            <div><dt>{t('scenario.seedCount')}</dt><dd>{scenario.seedCount}</dd></div>
            <div><dt>{t('scenario.population')}</dt><dd>{scenario.populationSize}</dd></div>
            <div><dt>{t('scenario.steps')}</dt><dd>{scenario.steps}</dd></div>
            <div><dt>{language === 'zh-CN' ? '主要指标' : 'Primary outcome'}</dt><dd><code>{scenario.primaryOutcome ?? 'maxSpreadBps'}</code></dd></div>
            <div><dt>{language === 'zh-CN' ? '次要指标' : 'Secondary outcomes'}</dt><dd>{scenario.secondaryOutcomes?.join(', ') || t('common.unavailable')}</dd></div>
            <div><dt>{t('preflight.stopRule')}</dt><dd>{language === 'zh-CN' ? `至少 ${scenario.stoppingRule?.minimumPairs ?? scenario.seedCount} 对，最多 ${scenario.stoppingRule?.maximumPairs ?? scenario.seedCount} 对${scenario.stoppingRule?.targetCiHalfWidth ? `，目标区间半宽 ${scenario.stoppingRule.targetCiHalfWidth}` : ''}` : `Minimum ${scenario.stoppingRule?.minimumPairs ?? scenario.seedCount} pairs, maximum ${scenario.stoppingRule?.maximumPairs ?? scenario.seedCount} pairs${scenario.stoppingRule?.targetCiHalfWidth ? `, target interval half-width ${scenario.stoppingRule.targetCiHalfWidth}` : ''}`}</dd></div>
            <div><dt>{language === 'zh-CN' ? '认知模式' : 'Cognition mode'}</dt><dd>{scenario.llmPolicy?.mode ?? 'RULE_ONLY'}</dd></div>
            <div><dt>{language === 'zh-CN' ? 'LLM 路由' : 'LLM route'}</dt><dd>{scenario.llmPolicy?.mode === 'HYBRID_LLM' ? `zhipu / ${scenario.llmPolicy.modelId}` : language === 'zh-CN' ? '不调用外部模型' : 'No external model call'}</dd></div>
            <div><dt>{language === 'zh-CN' ? '预计 LLM 调用' : 'Estimated LLM calls'}</dt><dd>{validation.estimatedLlmCalls ?? 0}</dd></div>
            <div><dt>{language === 'zh-CN' ? '最大费用责任上限（非预计账单）' : 'Maximum cost liability (not forecast spend)'}</dt><dd>${(validation.llmCostCapUsd ?? scenario.llmPolicy?.maxCostUsd ?? 0).toFixed(2)} USD</dd></div>
            <div><dt>{language === 'zh-CN' ? '价格核验状态' : 'Pricing verification'}</dt><dd><code>{validation.llmPricingStatus ?? (scenario.llmPolicy?.mode === 'RULE_ONLY' ? 'NOT_APPLICABLE' : 'UNAVAILABLE')}</code></dd></div>
            {validation.llmMinimumCallReservationUsd !== undefined ? <div><dt>{language === 'zh-CN' ? '单次调用前最坏预留' : 'Worst-case pre-dispatch reservation'}</dt><dd>${validation.llmMinimumCallReservationUsd.toFixed(6)} USD</dd></div> : null}
            <div><dt>{language === 'zh-CN' ? '数据许可边界' : 'Data-license boundary'}</dt><dd>{language === 'zh-CN' ? '导出来源元数据与哈希，不重新分发来源全文；公开再分发仍需人工许可审核。' : 'Export source metadata and hashes, not full source text. Public redistribution still requires human license review.'}</dd></div>
            <div><dt>{language === 'zh-CN' ? '解释上限' : 'Interpretation boundary'}</dt><dd><code>{validation.interpretationBoundary ?? 'MECHANISM_DEMONSTRATION_NOT_FORECAST'}</code></dd></div>
            <div>
              <dt>{t('preflight.cost')}</dt>
              <dd>
                {validation.estimatedRuns !== undefined
                  ? `${validation.estimatedRuns} ${t('preflight.estimatedRuns').toLowerCase()}`
                  : t('preflight.costUnknown')}
              </dd>
            </div>
          </dl>
          {scenario.llmPolicy?.mode === 'HYBRID_LLM' ? <Notice>{language === 'zh-CN' ? '费用闸门在每次请求前按完整上下文、最大输出、一次修复及所有允许的传输重试预留上界；响应后按智谱 usage 中的输入/输出 token 实耗结算。价格未知、预留不足或 usage 缺失都会在继续调用前关闭。该数值不含税费、支付手续费、账户折扣或资源包。' : 'Before every request, the cost gate reserves full context, maximum output, one repair, and every allowed transport retry. After the response, it settles provider-reported input/output tokens. Unknown pricing, insufficient reservation, or missing usage fails closed before another call. Taxes, payment fees, account discounts, and bundles are excluded.'}</Notice> : null}
          <Notice>{t('results.disclaimer')}</Notice>
        </section>

        <section className="preflight-panel">
          <div className="section-heading">
            <h2>{t('preflight.checks')}</h2>
          </div>
          <div className="check-list">
            {validation.checks.map((check) => (
              <CheckRow
                key={check.id}
                passed={check.passed}
                label={translateValidation(check.id, check.label, t)}
                detail={translateValidation(check.id, check.detail, t)}
                severity={check.severity}
              />
            ))}
          </div>
          {validation.checks.length === 0 ? <p className="empty-inline">{t('common.noData')}</p> : null}
        </section>

        <section className="preflight-panel preflight-panel--limitations">
          <div className="section-heading">
            <h2>{t('common.limitations')}</h2>
            <p>{language === 'zh-CN' ? '这些限制在启动决策点展示，并随导出包保存。' : 'These limitations are shown at the launch decision point and retained in the export bundle.'}</p>
          </div>
          <ul>
            {(language === 'zh-CN' ? eventPack?.limitationsZh : eventPack?.limitations)?.map((limitation) => <li key={limitation}>{limitation}</li>)}
            <li>{language === 'zh-CN' ? '所有基准与干预路径均由模型机制生成，不能当作 SpaceX 或任何真实证券的价格预测。' : 'All baseline and intervention paths are generated by model mechanisms and are not price forecasts for SpaceX or any real security.'}</li>
            <li>{language === 'zh-CN' ? '10 对随机种子只适合快速演示；区间宽度和有效样本数必须与结果一起报告。' : 'Ten matched seeds are suitable only for a fast demo. Interval width and valid sample count must accompany every result.'}</li>
          </ul>
        </section>

        <section className="human-gate">
          <div className="section-heading">
            <h2>{t('governance.humanAiMap')}</h2>
            <p>{t('pack.freezeHelp')}</p>
          </div>
          <div className="confirmation-list">
            {[
              t('preflight.confirmScenario'),
              t('preflight.confirmHuman'),
              t('preflight.confirmAdvice'),
            ].map((label, index) => (
              <label key={label} className="confirmation-row">
                <input type="checkbox" checked={confirmations[index]} onChange={() => toggleConfirmation(index)} />
                <span aria-hidden="true" />
                <strong>{label}</strong>
              </label>
            ))}
          </div>
          {!allConfirmed ? <p className="form-message">{t('preflight.confirmAll')}</p> : null}
          <Button
            renderIcon={Play}
            disabled={!validation.valid || !allConfirmed || experimentsState === 'loading'}
            onClick={() => void start()}
          >
            {experimentsState === 'loading' ? t('preflight.starting') : t('preflight.start')}
          </Button>
        </section>
      </div>
    </div>
  );
}
