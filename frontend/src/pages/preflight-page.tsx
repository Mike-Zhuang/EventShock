import { Button, InlineNotification, Tag } from '@carbon/react';
import { ArrowLeft, Play, ShieldCheck } from '@phosphor-icons/react';
import { useEffect, useState } from 'react';
import type { ViewId } from '../app';
import { CheckRow, EmptyState, ExplainedLabel, Notice, PageHeader } from '../components/common';
import { readGuidedReturnContext } from '../guided-handoff';
import { translateParameter, translateValidation, useI18n } from '../i18n';
import { getPageGuide } from '../page-guidance';
import { getParameterHelp } from '../parameter-help';
import {
  scenarioContentDigest,
  useWorkflow,
} from '../state/workflow-context';
import { safeDate } from '../utils/format';

function cognitionModeLabel(mode: string | undefined, isZh: boolean): string {
  if (!mode || mode === 'RULE_ONLY') {
    return isZh ? '仅确定性规则（不调用外部模型）' : 'Deterministic rules only (no external model call)';
  }
  if (mode === 'HYBRID_LLM') {
    return isZh ? '受限结构化模型辅助' : 'Bounded structured-model assistance';
  }
  return isZh ? `其他认知模式（${mode}）` : `Other cognition mode (${mode})`;
}

function pricingStatusLabel(status: string | undefined, isZh: boolean): string {
  const labels: Record<string, { en: string; zh: string }> = {
    VERIFIED_UPPER_BOUND: {
      en: 'Verified public-price upper bound',
      zh: '已核验公开价格上界',
    },
    NOT_APPLICABLE: {
      en: 'Not applicable — no external model call',
      zh: '不适用——不调用外部模型',
    },
    UNAVAILABLE_FAIL_CLOSED: {
      en: 'Price unavailable — model calls fail closed',
      zh: '价格不可用——模型调用将关闭',
    },
    UNAVAILABLE: {
      en: 'Pricing status unavailable',
      zh: '价格核验状态不可用',
    },
  };
  const normalized = status ?? 'UNAVAILABLE';
  const label = labels[normalized];
  return label ? isZh ? label.zh : label.en : isZh
    ? `其他价格状态（${normalized}）`
    : `Other pricing status (${normalized})`;
}

function interpretationBoundaryLabel(boundary: string | undefined, isZh: boolean): string {
  if (!boundary || boundary === 'MECHANISM_DEMONSTRATION_NOT_FORECAST') {
    return isZh
      ? '机制演示与情景比较，不是现实预测'
      : 'Mechanism demonstration and scenario comparison, not a real-world forecast';
  }
  return isZh ? `其他解释边界（${boundary}）` : `Other interpretation boundary (${boundary})`;
}

function degradationReasonLabel(code: string, isZh: boolean): string {
  const labels: Record<string, { en: string; zh: string }> = {
    LLM_CREDENTIAL_NOT_CONFIGURED: {
      en: 'No session API key is configured.',
      zh: '当前会话尚未配置 API Key。',
    },
    LLM_PROVIDER_MODEL_CONFIG_MISMATCH: {
      en: 'The scenario route differs from the configured provider and model.',
      zh: '场景中的供应商/模型与当前会话配置不一致。',
    },
    LLM_CALL_BUDGET_TOO_SMALL: {
      en: 'The model-call budget cannot cover the representative agents.',
      zh: '模型调用预算不足以覆盖代表性智能体。',
    },
    LLM_PRICE_UNAVAILABLE: {
      en: 'A verified price is unavailable, so paid calls fail closed.',
      zh: '当前没有可核验价格，因此付费调用失败关闭。',
    },
    LLM_OUTPUT_LIMIT_UNAVAILABLE: {
      en: 'The official output limit cannot be verified.',
      zh: '无法核验官方输出上限。',
    },
    LLM_COST_CAP_INSUFFICIENT: {
      en: 'The cost cap cannot reserve one safe structured call.',
      zh: '费用上限不足以预留一次安全的结构化调用。',
    },
  };
  const label = labels[code];
  if (label) return isZh ? label.zh : label.en;
  return isZh ? `模型降级原因：${code}` : `Model degradation reason: ${code}`;
}

function preflightCheckLabel(code: string, fallback: string, isZh: boolean): string {
  const labels: Record<string, { en: string; zh: string }> = {
    EVENT_PACK_EXISTS: { en: 'Event Pack exists', zh: '事件包存在' },
    EVENT_PACK_FROZEN: { en: 'Event Pack is frozen', zh: '事件包已冻结' },
    POINT_IN_TIME_BOUNDARY: { en: 'Point-in-time boundary', zh: '时点边界' },
    CLAIM_REVIEW_COMPLETE: { en: 'Claim review complete', zh: '主张审核完整' },
    SOURCE_CONTENT_HASHES: { en: 'Source content hashes', zh: '来源内容哈希' },
    SOURCE_REDISTRIBUTION_BOUNDARY: {
      en: 'Source redistribution boundary',
      zh: '来源再分发边界',
    },
    SINGLE_REGISTERED_INTERVENTION: {
      en: 'Single registered intervention',
      zh: '单一注册干预',
    },
    OUTCOMES_REGISTERED: { en: 'Outcome metrics registered', zh: '结果指标已注册' },
    STOPPING_RULE: { en: 'Stopping rule', zh: '停止规则' },
    NETWORK_FEASIBLE: { en: 'Network configuration feasible', zh: '网络配置可执行' },
    BORROW_AND_MARGIN_CONTROLS: {
      en: 'Borrow and margin controls',
      zh: '借券与保证金控制',
    },
    LLM_RUNTIME_CONFIG: { en: 'Model runtime configuration', zh: '模型运行配置' },
    LLM_CALL_BUDGET: { en: 'Model-call budget', zh: '模型调用预算' },
    LLM_COST_CONTROL: { en: 'Model cost control', zh: '模型费用控制' },
    LLM_TOOL_AUTHORITY: { en: 'Model tool authority', zh: '模型工具权限' },
    REPRODUCIBILITY_METADATA: {
      en: 'Reproducibility metadata',
      zh: '可复现元数据',
    },
  };
  const label = labels[code];
  if (label) return isZh ? label.zh : label.en;
  return isZh ? `其他检查（${code}）` : fallback || `Other check (${code})`;
}

function stoppingRuleDescription(
  minimumPairs: number,
  maximumPairs: number,
  targetCiHalfWidth: number | undefined,
  isZh: boolean,
): string {
  if (minimumPairs === maximumPairs) {
    return isZh
      ? `固定运行 ${maximumPairs} 对匹配种子；不会因区间提前停止${targetCiHalfWidth !== undefined ? `，目标区间半宽 ${targetCiHalfWidth} 仅用于结果对照` : ''}`
      : `Fixed at ${maximumPairs} matched pairs; the interval cannot stop the run early${targetCiHalfWidth !== undefined ? `, and target half-width ${targetCiHalfWidth} is reported for comparison only` : ''}`;
  }
  return isZh
    ? `至少 ${minimumPairs} 对，最多 ${maximumPairs} 对${targetCiHalfWidth !== undefined ? `；达到目标区间半宽 ${targetCiHalfWidth} 后可提前停止` : ''}`
    : `Minimum ${minimumPairs} pairs, maximum ${maximumPairs} pairs${targetCiHalfWidth !== undefined ? `; may stop early after reaching target interval half-width ${targetCiHalfWidth}` : ''}`;
}

export function PreflightPage({ navigate }: { navigate: (view: ViewId) => void }) {
  const { language, t } = useI18n();
  const isZh = language === 'zh-CN';
  const guidedReturnContext = readGuidedReturnContext();
  const explained = (key: string, label: string) => (
    <ExplainedLabel label={label} explanation={getParameterHelp(key, language) ?? label} />
  );
  const outcomeLabel = (outcomeId: string): string => {
    const labels: Record<string, string> = {
      maxSpreadBps: t('metric.peakSpread'),
      maxDrawdownPct: t('metric.maxDrawdown'),
      realizedVolatilityPct: t('metric.realizedVolatility'),
      minDepth: t('metric.minDepth'),
      recoverySteps: t('metric.recoveryTime'),
      totalVolume: t('metric.totalVolume'),
      orderImbalance: t('metric.orderImbalance'),
      cascadeScore: t('metric.cascadeScore'),
    };
    return labels[outcomeId] ?? outcomeId;
  };
  const {
    eventPack,
    scenario,
    validation,
    validationBinding,
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
  const [ruleFallbackConfirmed, setRuleFallbackConfirmed] = useState(false);
  const allConfirmed = confirmations.every(Boolean);
  const minimumPairs = scenario.stoppingRule?.minimumPairs ?? scenario.seedCount;
  const maximumPairs = scenario.stoppingRule?.maximumPairs ?? scenario.seedCount;

  useEffect(() => {
    setConfirmations((current) => [Boolean(scenario.acknowledgedScenarioNotForecast), current[1], current[2]]);
  }, [scenario.acknowledgedScenarioNotForecast]);

  useEffect(() => {
    setRuleFallbackConfirmed(false);
  }, [scenario, validation]);

  const toggleConfirmation = (index: number) => {
    setConfirmations((current) => current.map((value, itemIndex) => itemIndex === index ? !value : value));
  };

  const start = async () => {
    setStartError(undefined);
    try {
      const ruleOnlyScenario = validation?.requiresExplicitRuleFallbackConfirmation
        && ruleFallbackConfirmed
        && scenario.llmPolicy
        ? {
            ...scenario,
            llmPolicy: {
              ...scenario.llmPolicy,
              mode: 'RULE_ONLY' as const,
            },
          }
        : undefined;
      await createAndStartExperiment(ruleOnlyScenario);
      navigate('runs');
    } catch (error) {
      setStartError(error instanceof Error ? error.message : String(error));
    }
  };

  if (
    !validation
    || !validationBinding
    || validationBinding.draftDigest !== scenarioContentDigest(scenario)
  ) {
    return (
      <div className="page">
        <PageHeader title={t('preflight.title')} subtitle={t('preflight.subtitle')} />
        <EmptyState
          title={validation ? t('preflight.validationStaleTitle') : t('preflight.notValidated')}
          body={validation ? t('preflight.validationStale') : t('scenario.interventionHelp')}
          icon={<ShieldCheck size={28} weight="duotone" />}
          action={<Button kind="tertiary" onClick={() => navigate('scenario')}>{t('nav.scenario')}</Button>}
        />
      </div>
    );
  }

  const simulationRunnable = validation.simulationRunnable;
  const requestedCognitionRunnable = validation.requestedCognitionRunnable;
  const requiresRuleFallback = validation.requiresExplicitRuleFallbackConfirmation;
  const canStart = simulationRunnable
    && allConfirmed
    && (!requiresRuleFallback || ruleFallbackConfirmed);
  const validationStateLabel = !simulationRunnable
    ? isZh ? '完全不可运行' : 'Not runnable'
    : requiresRuleFallback
      ? isZh ? '仅可显式改为规则模式' : 'Explicit rule-only switch required'
      : requestedCognitionRunnable
        ? isZh ? '可按请求配置运行' : 'Requested configuration runnable'
        : isZh ? '认知配置不可运行' : 'Cognition configuration unavailable';

  return (
    <div className="page page--preflight">
      <PageHeader
        title={t('preflight.title')}
        subtitle={t('preflight.subtitle')}
        guide={getPageGuide('preflight', language)}
        actions={(
          <div className="page-header-action-group">
            <Tag
              type={!simulationRunnable ? 'red' : requiresRuleFallback ? 'warm-gray' : 'green'}
              size="sm"
            >
              {validationStateLabel}
            </Tag>
            <Button kind="ghost" renderIcon={ArrowLeft} onClick={() => navigate('scenario')}>{t('common.back')}</Button>
            {guidedReturnContext ? (
              <Button kind="ghost" renderIcon={ArrowLeft} onClick={() => navigate('guided')}>
                {isZh ? '返回 AI 引导' : 'Return to AI guidance'}
              </Button>
            ) : null}
          </div>
        )}
      />

      <InlineNotification
        kind="info"
        lowContrast
        hideCloseButton
        title={t('scenario.validationBinding')}
        subtitle={validationBinding.kind === 'saved'
          ? t('preflight.validationSaved', {
              name: validationBinding.scenarioName,
              id: validationBinding.scenarioId,
              hash: validationBinding.contentHash.slice(0, 20),
            })
          : t('preflight.validationUnsaved', {
              digest: validationBinding.draftDigest,
            })}
      />
      {!simulationRunnable ? (
        <InlineNotification kind="error" lowContrast hideCloseButton title={t('scenario.validationFailed')} subtitle={validation.checks.filter((check) => !check.passed).map((check) => translateValidation(check.id, check.detail, t)).join(' ')} />
      ) : null}
      {requiresRuleFallback ? (
        <InlineNotification
          kind="warning"
          lowContrast
          hideCloseButton
          title={isZh ? '混合 LLM 无法按当前配置运行' : 'Hybrid LLM cannot run as configured'}
          subtitle={isZh
            ? `仿真结构仍可运行，但不会静默降级。请在启动区明确确认将本次场景改为 RULE_ONLY。${validation.degradationReasons.map((code) => ` ${degradationReasonLabel(code, true)}`).join('')}`
            : `The simulation itself remains runnable, but it will not degrade silently. Explicitly confirm that this run changes the scenario to RULE_ONLY.${validation.degradationReasons.map((code) => ` ${degradationReasonLabel(code, false)}`).join('')}`}
        />
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
            <div><dt>{t('pack.pointInTime')}</dt><dd>{eventPack?.pointInTime ? safeDate(eventPack.pointInTime, language) : t('common.unavailable')}</dd></div>
            <div><dt>{t('scenario.interventionLabel')}</dt><dd>{translateParameter(scenario.intervention.parameter, t)}</dd></div>
            <div><dt>{t('common.baseline')}</dt><dd>{scenario.intervention.baselineValue}</dd></div>
            <div><dt>{t('common.intervention')}</dt><dd>{scenario.intervention.interventionValue}</dd></div>
            <div><dt>{t('scenario.seedCount')}</dt><dd>{scenario.seedCount}</dd></div>
            <div><dt>{t('scenario.population')}</dt><dd>{scenario.populationSize}</dd></div>
            <div><dt>{t('scenario.steps')}</dt><dd>{scenario.steps}</dd></div>
            <div><dt>{explained('primaryOutcome', language === 'zh-CN' ? '主要指标' : 'Primary outcome')}</dt><dd>{outcomeLabel(scenario.primaryOutcome ?? 'maxSpreadBps')} <code>{scenario.primaryOutcome ?? 'maxSpreadBps'}</code></dd></div>
            <div><dt>{language === 'zh-CN' ? '次要指标' : 'Secondary outcomes'}</dt><dd>{scenario.secondaryOutcomes?.map(outcomeLabel).join(', ') || t('common.unavailable')}</dd></div>
            <div><dt>{explained('minimumPairs', t('preflight.stopRule'))}</dt><dd>{stoppingRuleDescription(minimumPairs, maximumPairs, scenario.stoppingRule?.targetCiHalfWidth, isZh)}</dd></div>
            <div><dt>{language === 'zh-CN' ? '认知模式' : 'Cognition mode'}</dt><dd>{cognitionModeLabel(scenario.llmPolicy?.mode, isZh)}</dd></div>
            <div>
              <dt>{language === 'zh-CN' ? '运行时有效认知模式' : 'Effective runtime cognition'}</dt>
              <dd>{cognitionModeLabel(validation.effectiveCognitionMode, isZh)}</dd>
            </div>
            <div><dt>{language === 'zh-CN' ? 'LLM 路由' : 'LLM route'}</dt><dd>{scenario.llmPolicy?.mode === 'HYBRID_LLM' ? `${scenario.llmPolicy.provider} / ${scenario.llmPolicy.modelId}` : language === 'zh-CN' ? '不调用外部模型' : 'No external model call'}</dd></div>
            <div><dt>{explained('callBudget', language === 'zh-CN' ? '预计 LLM 调用' : 'Estimated LLM calls')}</dt><dd>{validation.estimatedLlmCalls ?? 0}</dd></div>
            <div><dt>{explained('costCap', language === 'zh-CN' ? '最大费用责任上限（非预计账单）' : 'Maximum cost liability (not forecast spend)')}</dt><dd>${(validation.llmCostCapUsd ?? scenario.llmPolicy?.maxCostUsd ?? 0).toFixed(2)} USD</dd></div>
            <div><dt>{language === 'zh-CN' ? '价格核验状态' : 'Pricing verification'}</dt><dd>{pricingStatusLabel(validation.llmPricingStatus ?? (scenario.llmPolicy?.mode === 'RULE_ONLY' ? 'NOT_APPLICABLE' : 'UNAVAILABLE'), isZh)}</dd></div>
            {validation.llmMinimumCallReservationUsd !== undefined ? <div><dt>{language === 'zh-CN' ? '单次调用前最坏预留' : 'Worst-case pre-dispatch reservation'}</dt><dd>${validation.llmMinimumCallReservationUsd.toFixed(6)} USD</dd></div> : null}
            <div><dt>{language === 'zh-CN' ? '数据许可边界' : 'Data-license boundary'}</dt><dd>{language === 'zh-CN' ? '导出来源元数据与哈希，不重新分发来源全文；公开再分发仍需人工许可审核。' : 'Export source metadata and hashes, not full source text. Public redistribution still requires human license review.'}</dd></div>
            <div><dt>{language === 'zh-CN' ? '解释上限' : 'Interpretation boundary'}</dt><dd>{interpretationBoundaryLabel(validation.interpretationBoundary, isZh)}</dd></div>
            <div>
              <dt>{t('preflight.cost')}</dt>
              <dd>
                {validation.estimatedRuns !== undefined
                  ? `${validation.estimatedRuns} ${t('preflight.estimatedRuns').toLowerCase()}`
                  : t('preflight.costUnknown')}
              </dd>
            </div>
          </dl>
          {scenario.llmPolicy?.mode === 'HYBRID_LLM' ? <Notice>{language === 'zh-CN' ? '费用闸门在每次请求前按完整上下文、最大输出、一次修复及所有允许的传输重试预留上界；响应后按供应商 usage 中的输入/输出 token 实耗结算。价格未知、预留不足或 usage 缺失都会在继续调用前关闭。该数值不含税费、支付手续费、账户折扣或资源包。' : 'Before every request, the cost gate reserves full context, maximum output, one repair, and every allowed transport retry. After the response, it settles provider-reported input/output tokens. Unknown pricing, insufficient reservation, or missing usage fails closed before another call. Taxes, payment fees, account discounts, and bundles are excluded.'}</Notice> : null}
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
                label={preflightCheckLabel(
                  check.id,
                  translateValidation(check.id, check.label, t),
                  isZh,
                )}
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
            <li>{language === 'zh-CN' ? '所有基准与干预路径均由模型机制生成，不能当作任何真实证券、资产或研究对象的价格预测。' : 'All baseline and intervention paths are generated by model mechanisms and are not price forecasts for any real security, asset, or research subject.'}</li>
            <li>{language === 'zh-CN' ? `${scenario.seedCount} 对匹配随机种子的区间宽度和有效样本数必须与结果一起报告；小样本仅适合快速演示。` : `Interval width and valid sample count must accompany results from ${scenario.seedCount} matched seeds; small samples are suitable only for a fast demo.`}</li>
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
            {requiresRuleFallback ? (
              <label className="confirmation-row">
                <input
                  type="checkbox"
                  checked={ruleFallbackConfirmed}
                  onChange={(event) => setRuleFallbackConfirmed(event.target.checked)}
                />
                <span aria-hidden="true" />
                <strong>
                  {isZh
                    ? '我确认本次实验将把认知模式明确改为 RULE_ONLY，并且不会调用外部模型。'
                    : 'I confirm that this experiment will explicitly change cognition to RULE_ONLY and will not call an external model.'}
                </strong>
              </label>
            ) : null}
          </div>
          {!allConfirmed || (requiresRuleFallback && !ruleFallbackConfirmed) ? (
            <p className="form-message">
              {requiresRuleFallback && !ruleFallbackConfirmed
                ? isZh ? '还需确认规则模式降级后才能启动。' : 'Confirm the rule-only switch before starting.'
                : t('preflight.confirmAll')}
            </p>
          ) : null}
          <Button
            renderIcon={Play}
            disabled={!canStart || experimentsState === 'loading'}
            onClick={() => void start()}
          >
            {experimentsState === 'loading'
              ? t('preflight.starting')
              : requiresRuleFallback
                ? isZh ? '确认改为规则模式并启动' : 'Switch to rule-only and start'
                : t('preflight.start')}
          </Button>
        </section>
      </div>
    </div>
  );
}
