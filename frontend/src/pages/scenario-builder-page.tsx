import {
  Accordion,
  AccordionItem,
  Button,
  InlineNotification,
  NumberInput,
  Select,
  SelectItem,
  TextInput,
  Toggle,
} from '@carbon/react';
import {
  ArrowsLeftRight,
  ArrowRight,
  CheckCircle,
  Copy,
  FloppyDisk,
  LockKey,
  SlidersHorizontal,
  Trash,
} from '@phosphor-icons/react';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { ViewId } from '../app';
import type {
  InterventionParameter,
  LlmCatalog,
  LlmModelDescriptor,
  LlmProviderId,
  SavedScenario,
  ScenarioDiffResult,
  ScenarioDraft,
} from '../api/types';
import { api } from '../api/client';
import { EmptyState, ExplainedLabel, Notice, PageHeader, ParameterHelp, StatusBadge } from '../components/common';
import {
  clearScenarioGuidedHandoff,
  readScenarioGuidedHandoff,
} from '../guided-handoff';
import { translateValidation, useI18n } from '../i18n';
import { getPageGuide } from '../page-guidance';
import { getParameterHelp } from '../parameter-help';
import { useWorkflow } from '../state/workflow-context';

interface InterventionOption {
  parameter: InterventionParameter;
  labelKey: 'scenario.option.capacity' | 'scenario.option.social' | 'scenario.option.stopLoss' | 'scenario.option.clarification' | 'scenario.option.depth' | 'scenario.option.passiveFlow' | 'scenario.option.latency';
  helpKey: 'scenario.option.capacityHelp' | 'scenario.option.socialHelp' | 'scenario.option.stopLossHelp' | 'scenario.option.clarificationHelp' | 'scenario.option.depthHelp' | 'scenario.option.passiveFlowHelp' | 'scenario.option.latencyHelp';
  baselineValue: number;
  interventionValue: number;
  min: number;
  max: number;
  step: number;
  unit: string;
}

const OPTIONS: InterventionOption[] = [
  {
    parameter: 'marketMakerCapacity',
    labelKey: 'scenario.option.capacity',
    helpKey: 'scenario.option.capacityHelp',
    baselineValue: 1,
    interventionValue: 0.45,
    min: 0.1,
    max: 3,
    step: 0.05,
    unit: '×',
  },
  {
    parameter: 'socialAmplification',
    labelKey: 'scenario.option.social',
    helpKey: 'scenario.option.socialHelp',
    baselineValue: 1,
    interventionValue: 1.6,
    min: 0.1,
    max: 3,
    step: 0.05,
    unit: '×',
  },
  {
    parameter: 'stopLossSensitivity',
    labelKey: 'scenario.option.stopLoss',
    helpKey: 'scenario.option.stopLossHelp',
    baselineValue: 1,
    interventionValue: 1.5,
    min: 0.1,
    max: 3,
    step: 0.05,
    unit: '×',
  },
  {
    parameter: 'clarificationDelay',
    labelKey: 'scenario.option.clarification',
    helpKey: 'scenario.option.clarificationHelp',
    baselineValue: 1,
    interventionValue: 2,
    min: 0.1,
    max: 4,
    step: 0.05,
    unit: '×',
  },
  {
    parameter: 'liquidityDepthMultiplier',
    labelKey: 'scenario.option.depth',
    helpKey: 'scenario.option.depthHelp',
    baselineValue: 1,
    interventionValue: 0.65,
    min: 0.1,
    max: 3,
    step: 0.05,
    unit: '×',
  },
  {
    parameter: 'passiveFlowMultiplier',
    labelKey: 'scenario.option.passiveFlow',
    helpKey: 'scenario.option.passiveFlowHelp',
    baselineValue: 1,
    interventionValue: 1.5,
    min: 0.1,
    max: 3,
    step: 0.05,
    unit: '×',
  },
  {
    parameter: 'informationLatency',
    labelKey: 'scenario.option.latency',
    helpKey: 'scenario.option.latencyHelp',
    baselineValue: 1,
    interventionValue: 2,
    min: 0.1,
    max: 4,
    step: 0.05,
    unit: '×',
  },
];

const OUTCOME_OPTIONS = [
  { id: 'maxSpreadBps', key: 'metric.peakSpread' as const },
  { id: 'maxDrawdownPct', key: 'metric.maxDrawdown' as const },
  { id: 'realizedVolatilityPct', key: 'metric.realizedVolatility' as const },
  { id: 'minDepth', key: 'metric.minDepth' as const },
  { id: 'recoverySteps', key: 'metric.recoveryTime' as const },
  { id: 'totalVolume', key: 'metric.totalVolume' as const },
  { id: 'orderImbalance', key: 'metric.orderImbalance' as const },
  { id: 'cascadeScore', key: 'metric.cascadeScore' as const },
];

function numericInputValue(value: string | number): number | undefined {
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export type LlmModelAvailability = 'READY' | 'PRICE_UNVERIFIED' | 'OUTPUT_LIMIT_UNVERIFIED' | 'MISSING';

export function getLlmModelAvailability(model: LlmModelDescriptor | undefined): LlmModelAvailability {
  if (!model) return 'MISSING';
  if (model.pricingStatus !== 'VERIFIED_UPPER_BOUND') return 'PRICE_UNVERIFIED';
  if ((model.officialMaxOutputTokens ?? model.maxOutputTokens) === undefined) {
    return 'OUTPUT_LIMIT_UNVERIFIED';
  }
  return 'READY';
}

export function SecondaryOutcomeOption({
  id,
  label,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <label className="native-check-row">
      <input type="checkbox" value={id} checked={checked} onChange={onChange} />
      <strong className="native-check-row__label">{label}</strong>
    </label>
  );
}

export class GuidedScenarioReplacementError extends Error {}

export async function linkSavedScenarioToGuidedWorkflow(
  workflowId: string,
  savedScenario: SavedScenario,
): Promise<void> {
  if (!savedScenario.frozen || !savedScenario.contentHash) {
    throw new GuidedScenarioReplacementError(
      'Only a successfully frozen scenario can be linked to guided workflow.',
    );
  }
  const currentWorkflow = await api.getGuidedWorkflow(workflowId);
  const linkedScenarioId = currentWorkflow.draft.scenarioId;
  if (linkedScenarioId !== savedScenario.id) {
    await api.linkGuidedWorkflowArtifacts(currentWorkflow.id, {
      expectedVersion: currentWorkflow.version,
      scenarioId: savedScenario.id,
    });
  }
}

export function ScenarioBuilderPage({ navigate }: { navigate: (view: ViewId) => void }) {
  const { language, t } = useI18n();
  const {
    eventPack,
    scenario,
    setScenario,
    validateScenario,
    validation,
    validationState,
    validationError,
  } = useWorkflow();
  const isZh = language === 'zh-CN';
  const explained = (key: string, label: string) => (
    <ExplainedLabel label={label} explanation={getParameterHelp(key, language) ?? label} />
  );
  const parameterHelp = (key: string, label: string) => (
    <ParameterHelp label={label} explanation={getParameterHelp(key, language) ?? label} />
  );
  const [modelCatalog, setModelCatalog] = useState<LlmCatalog>();
  const [savedScenarios, setSavedScenarios] = useState<SavedScenario[]>([]);
  const [savedScenariosLoading, setSavedScenariosLoading] = useState(true);
  const [selectedScenarioId, setSelectedScenarioId] = useState('');
  const [scenarioName, setScenarioName] = useState('');
  const [scenarioAction, setScenarioAction] = useState<'create' | 'update' | 'clone' | 'freeze' | 'delete' | 'diff'>();
  const [scenarioManagementError, setScenarioManagementError] = useState<string>();
  const [savedScenarioDiff, setSavedScenarioDiff] = useState<ScenarioDiffResult>();
  const [guidedHandoff] = useState(readScenarioGuidedHandoff);
  const [guidedLinkComplete, setGuidedLinkComplete] = useState(false);
  const guidedHandoffApplied = useRef(false);
  const isFrozen = eventPack?.status.toUpperCase() === 'FROZEN' || Boolean(eventPack?.frozenAt);
  const selectedOption = OPTIONS.find((option) => option.parameter === scenario.intervention.parameter) ?? OPTIONS[0];
  const market: NonNullable<ScenarioDraft['market']> = scenario.market ?? {
    instrumentId: 'SPCX', benchmarkId: 'NDX_SYNTHETIC', tickSize: 0.01,
    initialPrice: 135, feeBps: 0.3, latencyMs: 25, openingAuction: true,
    volatilityHalt: true, priceCollarBps: 180,
  };
  const population: NonNullable<ScenarioDraft['population']> = scenario.population ?? {
    profileId: 'mixed-event-risk-v1', representativeLlmAgents: 8,
    institutionalShare: 0.2, leverageEnabled: true, shortSellingEnabled: true,
  };
  const network: NonNullable<ScenarioDraft['network']> = scenario.network ?? {
    topology: 'WATTS_STROGATZ', averageDegree: 6, rewiringProbability: 0.12,
    echoChamberStrength: 0.35, correctionReach: 0.7,
  };
  const llmPolicy: NonNullable<ScenarioDraft['llmPolicy']> = scenario.llmPolicy ?? {
    mode: 'RULE_ONLY', provider: 'zhipu', modelId: 'glm-5.2', representativeAgentCount: 8,
    decisionIntervalSteps: 12, callBudget: 24, maxCostUsd: 10, fallbackToRules: true,
  };
  const representativeLlmAgentCount = Math.min(
    population.representativeLlmAgents,
    llmPolicy.representativeAgentCount,
  );
  const selectedLlmProvider = modelCatalog?.providers.find((item) => item.id === llmPolicy.provider);
  const selectedLlmModel = selectedLlmProvider?.models.find((item) => item.id === llmPolicy.modelId);
  const selectedLlmModelAvailability = getLlmModelAvailability(selectedLlmModel);
  const selectedSavedScenario = savedScenarios.find((item) => item.id === selectedScenarioId);

  const refreshSavedScenarios = async () => {
    setSavedScenariosLoading(true);
    try {
      setSavedScenarios(await api.getScenarios());
    } catch (error) {
      setScenarioManagementError(error instanceof Error ? error.message : String(error));
    } finally {
      setSavedScenariosLoading(false);
    }
  };

  useEffect(() => {
    void api.getLlmCatalog().then(setModelCatalog).catch(() => setModelCatalog(undefined));
    void refreshSavedScenarios();
  }, []);

  useEffect(() => {
    if (!scenarioName && eventPack) {
      setScenarioName(`${eventPack.name} - ${scenario.intervention.parameter}`.slice(0, 150));
    }
  }, [eventPack?.id]);

  useEffect(() => {
    if (
      guidedHandoffApplied.current
      || !guidedHandoff
      || eventPack?.id !== guidedHandoff.eventPackId
    ) return;
    // 交接只负责预填可编辑草稿；不会替用户保存、冻结或通过运行前检查。
    guidedHandoffApplied.current = true;
    setScenario({
      ...scenario,
      eventPackId: guidedHandoff.eventPackId,
      question: guidedHandoff.eventMetadata.researchQuestion,
      intervention: {
        parameter: guidedHandoff.intervention.parameter,
        baselineValue: guidedHandoff.intervention.baselineValue,
        interventionValue: guidedHandoff.intervention.interventionValue,
      },
    });
    setScenarioName(
      `${guidedHandoff.eventMetadata.title} - ${guidedHandoff.intervention.parameter}`.slice(0, 150),
    );
  }, [eventPack?.id, guidedHandoff, scenario, setScenario]);

  const scenarioIsWithinBounds = useMemo(() => (
    scenario.intervention.baselineValue >= selectedOption.min
    && scenario.intervention.baselineValue <= selectedOption.max
    && scenario.intervention.interventionValue >= selectedOption.min
    && scenario.intervention.interventionValue <= selectedOption.max
    && scenario.intervention.baselineValue !== scenario.intervention.interventionValue
    && scenario.populationSize >= 14
    && scenario.populationSize <= 250
    && scenario.steps >= 30
    && scenario.steps <= 300
    && (scenario.seedRoot ?? 2_026_070_700) >= 1
    && (scenario.seedRoot ?? 2_026_070_700) <= 2_147_483_000
    && (scenario.stoppingRule?.minimumPairs ?? scenario.seedCount) >= 5
    && (scenario.stoppingRule?.minimumPairs ?? scenario.seedCount) <= scenario.seedCount
    && network.averageDegree < scenario.populationSize
    && (llmPolicy.mode === 'RULE_ONLY' || (
      llmPolicy.representativeAgentCount > 0
      && llmPolicy.representativeAgentCount <= scenario.populationSize
      && llmPolicy.callBudget >= llmPolicy.representativeAgentCount
    ))
  ), [llmPolicy, network.averageDegree, scenario, selectedOption]);

  const update = (partial: Partial<ScenarioDraft>) => setScenario({ ...scenario, ...partial });
  const updateIntervention = (partial: Partial<ScenarioDraft['intervention']>) => {
    setScenario({ ...scenario, intervention: { ...scenario.intervention, ...partial } });
  };
  const updateMarket = (partial: Partial<NonNullable<ScenarioDraft['market']>>) => {
    setScenario({ ...scenario, market: { ...market, ...partial } });
  };
  const updatePopulation = (partial: Partial<NonNullable<ScenarioDraft['population']>>) => {
    setScenario({ ...scenario, population: { ...population, ...partial } });
  };
  const updateNetwork = (partial: Partial<NonNullable<ScenarioDraft['network']>>) => {
    setScenario({ ...scenario, network: { ...network, ...partial } });
  };
  const updateLlmPolicy = (partial: Partial<NonNullable<ScenarioDraft['llmPolicy']>>) => {
    setScenario({ ...scenario, llmPolicy: { ...llmPolicy, ...partial } });
  };
  const toggleSecondaryOutcome = (outcomeId: string) => {
    const current = scenario.secondaryOutcomes ?? [];
    const next = current.includes(outcomeId)
      ? current.filter((item) => item !== outcomeId)
      : [...current, outcomeId];
    update({ secondaryOutcomes: next });
  };

  const selectIntervention = (option: InterventionOption) => {
    setScenario({
      ...scenario,
      intervention: {
        parameter: option.parameter,
        baselineValue: option.baselineValue,
        interventionValue: option.interventionValue,
      },
    });
  };

  const validate = async () => {
    const result = await validateScenario();
    if (result.valid) navigate('preflight');
  };

  const runScenarioAction = async (
    action: NonNullable<typeof scenarioAction>,
    operation: () => Promise<SavedScenario | void | ScenarioDiffResult>,
  ) => {
    setScenarioAction(action);
    setScenarioManagementError(undefined);
    try {
      const result = await operation();
      if (action === 'diff') {
        setSavedScenarioDiff(result as ScenarioDiffResult);
        return;
      }
      if (result) {
        const saved = result as SavedScenario;
        setSelectedScenarioId(saved.id);
        setScenarioName(saved.name);
        setScenario(saved.config);
        if (
          guidedHandoff
          && action === 'freeze'
          && saved.frozen
          && Boolean(saved.contentHash)
          && saved.config.eventPackId === guidedHandoff.eventPackId
        ) {
          try {
            await linkSavedScenarioToGuidedWorkflow(guidedHandoff.workflowId, saved);
            setGuidedLinkComplete(true);
            clearScenarioGuidedHandoff();
          } catch (linkError) {
            const linkDetail = isZh && linkError instanceof GuidedScenarioReplacementError
              ? '只有已成功冻结且带有内容哈希的情景才能关联回引导。'
              : linkError instanceof Error ? linkError.message : String(linkError);
            setScenarioManagementError(isZh
              ? `情景已保存，但未能关联回引导：${linkDetail}`
              : `The scenario was saved, but could not be linked back to guidance: ${linkDetail}`);
          }
        }
      } else {
        setSelectedScenarioId('');
        setSavedScenarioDiff(undefined);
      }
      await refreshSavedScenarios();
    } catch (error) {
      setScenarioManagementError(error instanceof Error ? error.message : String(error));
    } finally {
      setScenarioAction(undefined);
    }
  };

  const selectSavedScenario = (scenarioId: string) => {
    setSelectedScenarioId(scenarioId);
    setSavedScenarioDiff(undefined);
    const saved = savedScenarios.find((item) => item.id === scenarioId);
    if (!saved) return;
    setScenarioName(saved.name);
    setScenario(saved.config);
  };

  if (!eventPack) {
    return (
      <div className="page">
        <PageHeader title={t('scenario.title')} subtitle={t('scenario.subtitle')} />
        <EmptyState
          title={t('pack.selectTitle')}
          body={t('pack.selectBody')}
          action={<Button kind="tertiary" onClick={() => navigate('cases')}>{t('nav.cases')}</Button>}
          icon={<SlidersHorizontal size={28} weight="duotone" />}
        />
      </div>
    );
  }

  return (
    <div className="page page--scenario">
      <PageHeader title={t('scenario.title')} subtitle={t('scenario.subtitle')} guide={getPageGuide('scenario', language)} />
      {guidedHandoff && eventPack.id === guidedHandoff.eventPackId ? (
        <div className="inline-action-notice">
          <InlineNotification
            kind={guidedLinkComplete ? 'success' : 'info'}
            lowContrast
            hideCloseButton
            title={guidedLinkComplete
              ? isZh ? '真实情景已关联回 AI 引导' : 'Real scenario linked back to AI guidance'
              : isZh ? '已载入 AI 引导中的可编辑草稿' : 'Editable guided draft loaded'}
            subtitle={guidedLinkComplete
              ? isZh
                ? '你仍需在对应阶段核对冻结状态与运行前检查，关联本身不会推进工作流。'
                : 'You still need to review freeze status and preflight in the corresponding stage; linking does not advance the workflow.'
              : isZh
                ? '研究问题和单一干预已预填。请逐字段检查、按需编辑，再亲自保存和冻结；页面不会自动提交。'
                : 'The research question and one intervention are prefilled. Review and edit every field, then explicitly save and freeze it; this page never auto-submits.'}
          />
          <Button kind="ghost" size="sm" onClick={() => navigate('guided')}>
            {isZh ? '返回 AI 引导' : 'Return to AI guidance'}
          </Button>
        </div>
      ) : null}
      {!isFrozen ? (
        <div className="inline-action-notice">
          <InlineNotification
            kind="warning"
            lowContrast
            hideCloseButton
            title={t('scenario.needsPack')}
            subtitle={t('pack.freezeHelp')}
          />
          <Button kind="ghost" size="sm" onClick={() => navigate('pack')}>{t('nav.pack')}</Button>
        </div>
      ) : null}
      {validationState === 'error' || (validation && !validation.valid) ? (
        <InlineNotification
          kind="error"
          lowContrast
          hideCloseButton
          title={t('scenario.validationFailed')}
          subtitle={validation?.checks.filter((check) => !check.passed).map((check) => translateValidation(check.id, check.detail, t)).join(' ') || t('common.errorFallback')}
        />
      ) : null}
      {scenarioManagementError ? (
        <InlineNotification
          kind="error"
          lowContrast
          hideCloseButton
          title={isZh ? '场景库操作失败' : 'Scenario-library operation failed'}
          subtitle={scenarioManagementError}
        />
      ) : null}

      <section className="scenario-library" aria-labelledby="scenario-library-heading">
        <div className="section-heading">
          <h2 id="scenario-library-heading">{isZh ? '会话场景库' : 'Session scenario library'}</h2>
          <p>{isZh ? '保存、复用、克隆并冻结完整实验配置。冻结后不可覆盖或删除。' : 'Save, reuse, clone, and freeze complete experiment configurations. Frozen records cannot be overwritten or deleted.'}</p>
        </div>
        <div className="scenario-library__fields">
          <Select
            id="saved-scenario"
            labelText={isZh ? '已保存场景' : 'Saved scenario'}
            value={selectedScenarioId}
            disabled={savedScenariosLoading || scenarioAction !== undefined}
            onChange={(event) => selectSavedScenario(event.target.value)}
          >
            <SelectItem value="" text={savedScenariosLoading ? isZh ? '加载中' : 'Loading' : isZh ? '当前未保存草稿' : 'Current unsaved draft'} />
            {savedScenarios.map((saved) => (
              <SelectItem key={saved.id} value={saved.id} text={`${saved.name}${saved.frozen ? isZh ? '（已冻结）' : ' (Frozen)' : ''}`} />
            ))}
          </Select>
          <TextInput
            id="scenario-name"
            labelText={isZh ? '场景名称' : 'Scenario name'}
            value={scenarioName}
            maxLength={150}
            disabled={scenarioAction !== undefined}
            onChange={(event) => setScenarioName(event.target.value)}
          />
        </div>
        <div className="scenario-library__actions">
          <Button size="sm" renderIcon={FloppyDisk} disabled={!scenarioName.trim() || scenarioAction !== undefined} onClick={() => void runScenarioAction('create', () => api.createScenario(scenarioName.trim(), scenario))}>{isZh ? '另存为新场景' : 'Save as new'}</Button>
          <Button size="sm" kind="tertiary" renderIcon={FloppyDisk} disabled={!selectedSavedScenario || selectedSavedScenario.frozen || !scenarioName.trim() || scenarioAction !== undefined} onClick={() => selectedSavedScenario && void runScenarioAction('update', () => api.updateScenario(selectedSavedScenario.id, scenarioName.trim(), scenario))}>{isZh ? '更新当前场景' : 'Update selected'}</Button>
          <Button size="sm" kind="ghost" renderIcon={Copy} disabled={!selectedSavedScenario || scenarioAction !== undefined} onClick={() => selectedSavedScenario && void runScenarioAction('clone', () => api.cloneScenario(selectedSavedScenario.id))}>{isZh ? '克隆' : 'Clone'}</Button>
          <Button size="sm" kind="ghost" renderIcon={ArrowsLeftRight} disabled={!selectedSavedScenario || scenarioAction !== undefined} onClick={() => selectedSavedScenario && void runScenarioAction('diff', () => api.diffScenarios(selectedSavedScenario.config, scenario))}>{isZh ? '与当前草稿比较' : 'Compare with draft'}</Button>
          <Button size="sm" kind="ghost" renderIcon={LockKey} disabled={!selectedSavedScenario || selectedSavedScenario.frozen || scenarioAction !== undefined} onClick={() => selectedSavedScenario && void runScenarioAction('freeze', () => api.freezeScenario(selectedSavedScenario.id))}>{isZh ? '冻结' : 'Freeze'}</Button>
          <Button size="sm" kind="danger--ghost" renderIcon={Trash} disabled={!selectedSavedScenario || selectedSavedScenario.frozen || scenarioAction !== undefined} onClick={() => {
            if (!selectedSavedScenario) return;
            const confirmed = window.confirm(isZh ? `删除场景“${selectedSavedScenario.name}”？该操作不能撤销。` : `Delete scenario "${selectedSavedScenario.name}"? This cannot be undone.`);
            if (confirmed) void runScenarioAction('delete', () => api.deleteScenario(selectedSavedScenario.id));
          }}>{isZh ? '删除' : 'Delete'}</Button>
        </div>
        {selectedSavedScenario ? (
          <dl className="scenario-library__metadata">
            <div><dt>{isZh ? '状态' : 'Status'}</dt><dd><StatusBadge status={selectedSavedScenario.frozen ? 'FROZEN' : 'DRAFT'} /></dd></div>
            <div><dt>{isZh ? '内容哈希' : 'Content hash'}</dt><dd><code title={selectedSavedScenario.contentHash}>{selectedSavedScenario.contentHash.slice(0, 20)}</code></dd></div>
            <div><dt>{isZh ? '更新时间' : 'Updated'}</dt><dd>{selectedSavedScenario.updatedAt ? new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(selectedSavedScenario.updatedAt)) : t('common.unavailable')}</dd></div>
          </dl>
        ) : null}
        {savedScenarioDiff ? (
          <div className="scenario-library__diff" role="status">
            <strong>{isZh ? `${savedScenarioDiff.changeCount} 个字段发生变化` : `${savedScenarioDiff.changeCount} changed fields`}</strong>
            <StatusBadge status={savedScenarioDiff.singleInterventionCompliant ? 'VALID' : 'REVIEW'} />
            {savedScenarioDiff.changes.length > 0 ? (
              <ul>{savedScenarioDiff.changes.map((change) => <li key={change.path}><code>{change.path}</code><span>{String(change.baseline ?? 'null')} → {String(change.intervention ?? 'null')}</span></li>)}</ul>
            ) : <p>{isZh ? '已保存场景与当前草稿完全一致。' : 'The saved scenario and current draft are identical.'}</p>}
          </div>
        ) : null}
      </section>

      <nav className="scenario-step-navigation" aria-label={isZh ? '场景配置步骤' : 'Scenario configuration steps'}>
        {[
          ['event', isZh ? '事件' : 'Event'],
          ['facts', isZh ? '事实' : 'Facts'],
          ['market', isZh ? '市场' : 'Market'],
          ['population', isZh ? '人口' : 'Population'],
          ['network', isZh ? '网络' : 'Network'],
          ['intervention', isZh ? '干预' : 'Intervention'],
          ['review', isZh ? '复核' : 'Review'],
        ].map(([id, label], index) => (
          <a key={id} href={`#scenario-step-${id}`}>
            <span>{index + 1}</span>
            {label}
          </a>
        ))}
      </nav>

      <div className="scenario-layout">
        <div className="scenario-form">
          <section id="scenario-step-event" className="form-section scenario-step-section">
            <div className="form-section__heading">
              <span className="step-kicker">01</span>
              <h2>{isZh ? '事件与研究问题' : 'Event and research question'}</h2>
              <p>{isZh ? '实验只能读取冻结 Event Pack 中、在 asOf 时点已经可见的事实。' : 'The experiment can read only frozen Event Pack facts that were visible at the asOf cutoff.'}</p>
            </div>
            <dl className="definition-list definition-list--compact">
              <div><dt>{t('scenario.eventPack')}</dt><dd>{isZh ? eventPack.nameZh ?? eventPack.name : eventPack.name} <StatusBadge status={eventPack.status} /></dd></div>
              <div><dt>{explained('asOf', isZh ? '截止时间 (asOf)' : 'Cutoff (asOf)')}</dt><dd>{eventPack.pointInTime ? new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(eventPack.pointInTime)) : t('common.unavailable')}</dd></div>
              <div><dt>{explained('instrument', isZh ? '目标证券' : 'Target instrument')}</dt><dd>{eventPack.instrument ?? market.instrumentId}</dd></div>
            </dl>
            <div className="stacked-fields">
              <TextInput
                id="scenario-question"
                labelText={isZh ? '英文研究问题' : 'English research question'}
                value={scenario.question ?? t('scenario.questionValue', { parameter: t(selectedOption.labelKey).toLowerCase() })}
                maxLength={500}
                onChange={(event) => update({ question: event.target.value })}
              />
              <TextInput
                id="scenario-question-zh"
                labelText={isZh ? '中文研究问题（可选）' : 'Chinese research question (optional)'}
                value={scenario.questionZh ?? ''}
                maxLength={500}
                onChange={(event) => update({ questionZh: event.target.value })}
              />
            </div>
          </section>

          <section id="scenario-step-facts" className="form-section scenario-step-section">
            <div className="form-section__heading">
              <span className="step-kicker">02</span>
              <h2>{isZh ? '冻结事实与来源边界' : 'Frozen facts and source boundary'}</h2>
              <p>{isZh ? '只有人工批准或修改后冻结的主张能够进入智能体观察。拒绝项保留在审计记录中，但不会进入仿真。' : 'Only human-approved or edited claims that were frozen can enter agent observations. Rejected items remain auditable but do not enter simulation.'}</p>
            </div>
            <div className="fact-review-summary">
              <div><span>{t('common.sources')}</span><strong>{eventPack.sources.length}</strong></div>
              <div><span>{isZh ? '批准或编辑' : 'Approved or edited'}</span><strong>{eventPack.claims.filter((claim) => ['HUMAN_APPROVED', 'EDITED', 'FROZEN'].includes(claim.status)).length}</strong></div>
              <div><span>{isZh ? '拒绝' : 'Rejected'}</span><strong>{eventPack.claims.filter((claim) => claim.status === 'REJECTED').length}</strong></div>
              <div><span>{isZh ? '待审核' : 'Pending review'}</span><strong>{eventPack.claims.filter((claim) => claim.status === 'AI_PROPOSED').length}</strong></div>
            </div>
            <div className="frozen-claim-list">
              {eventPack.claims.filter((claim) => claim.status !== 'REJECTED').map((claim) => (
                <article key={claim.id}>
                  <StatusBadge status={claim.status} />
                  <p>{isZh ? claim.textZh ?? claim.text : claim.text}</p>
                  <small>{(claim.sourceIds?.length ? claim.sourceIds : claim.sourceId ? [claim.sourceId] : []).join(', ') || t('common.unavailable')}</small>
                </article>
              ))}
            </div>
            <Button kind="ghost" size="sm" onClick={() => navigate('pack')}>{isZh ? '返回 Event Pack 审核' : 'Return to Event Pack review'}</Button>
          </section>

          <section id="scenario-step-market" className="form-section scenario-step-section">
            <div className="form-section__heading">
              <span className="step-kicker">03</span>
              <h2>{isZh ? '市场与交易制度' : 'Market and trading rules'}</h2>
              <p>{isZh ? '价格只由确定性撮合引擎形成；下列配置在配对场景之间保持不变。' : 'Only the deterministic matching engine forms prices. These settings remain fixed across paired scenarios.'}</p>
            </div>
            <div className="number-grid">
              <TextInput id="market-instrument" labelText={isZh ? '证券代码' : 'Instrument'} decorator={parameterHelp('instrument', isZh ? '证券代码' : 'Instrument')} value={market.instrumentId} onChange={(event) => updateMarket({ instrumentId: event.target.value.toUpperCase() })} />
              <TextInput id="market-benchmark" labelText={isZh ? '基准' : 'Benchmark'} decorator={parameterHelp('benchmark', isZh ? '基准' : 'Benchmark')} value={market.benchmarkId} onChange={(event) => updateMarket({ benchmarkId: event.target.value.toUpperCase() })} />
              <NumberInput id="market-initial-price" label={isZh ? '初始价格' : 'Initial price'} decorator={parameterHelp('initialPrice', isZh ? '初始价格' : 'Initial price')} min={1} max={1_000_000} value={market.initialPrice} onChange={(_event, state) => { const value = numericInputValue(state.value); if (value !== undefined) updateMarket({ initialPrice: value }); }} />
              <NumberInput id="market-tick-size" label={isZh ? '最小价格变动' : 'Tick size'} decorator={parameterHelp('tickSize', isZh ? '最小价格变动' : 'Tick size')} min={0.0001} max={10} step={0.01} value={market.tickSize} onChange={(_event, state) => { const value = numericInputValue(state.value); if (value !== undefined) updateMarket({ tickSize: value }); }} />
              <NumberInput id="market-fee-bps" label={isZh ? '费用（bps）' : 'Fee (bps)'} decorator={parameterHelp('feeBps', isZh ? '费用（bps）' : 'Fee (bps)')} min={0} max={100} step={0.1} value={market.feeBps} onChange={(_event, state) => { const value = numericInputValue(state.value); if (value !== undefined) updateMarket({ feeBps: value }); }} />
              <NumberInput id="market-latency-ms" label={isZh ? '基础延迟（ms）' : 'Base latency (ms)'} decorator={parameterHelp('latencyMs', isZh ? '基础延迟（ms）' : 'Base latency (ms)')} min={0} max={60_000} value={market.latencyMs} onChange={(_event, state) => { const value = numericInputValue(state.value); if (value !== undefined) updateMarket({ latencyMs: Math.round(value) }); }} />
              <NumberInput id="market-price-collar" label={isZh ? '价格保护带（bps）' : 'Price collar (bps)'} decorator={parameterHelp('priceCollarBps', isZh ? '价格保护带（bps）' : 'Price collar (bps)')} min={10} max={10_000} value={market.priceCollarBps} onChange={(_event, state) => { const value = numericInputValue(state.value); if (value !== undefined) updateMarket({ priceCollarBps: Math.round(value) }); }} />
            </div>
            <div className="toggle-grid">
              <div className="toggle-with-help">
                {explained('openingAuction', isZh ? '开盘集合竞价' : 'Opening auction')}
                <Toggle id="market-opening-auction" aria-label={isZh ? '开盘集合竞价' : 'Opening auction'} labelA={isZh ? '关闭' : 'Off'} labelB={isZh ? '开启' : 'On'} toggled={market.openingAuction} onToggle={(value) => updateMarket({ openingAuction: value })} />
              </div>
              <div className="toggle-with-help">
                {explained('volatilityHalt', isZh ? '波动停牌' : 'Volatility halt')}
                <Toggle id="market-volatility-halt" aria-label={isZh ? '波动停牌' : 'Volatility halt'} labelA={isZh ? '关闭' : 'Off'} labelB={isZh ? '开启' : 'On'} toggled={market.volatilityHalt} onToggle={(value) => updateMarket({ volatilityHalt: value })} />
              </div>
            </div>
          </section>

          <section id="scenario-step-population" className="form-section scenario-step-section">
            <div className="form-section__heading">
              <span className="step-kicker">04</span>
              <h2>{isZh ? '智能体人口与资产负债约束' : 'Agent population and balance-sheet constraints'}</h2>
              <p>{isZh ? '规则智能体覆盖价值、动量、均值回归、做市、被动执行、止损、机构执行、去杠杆与强平。' : 'Rule agents cover value, momentum, mean reversion, market making, passive execution, stop loss, institutional execution, deleveraging, and liquidation.'}</p>
            </div>
            <div className="number-grid">
              <NumberInput id="population-size" label={t('scenario.population')} decorator={parameterHelp('populationSize', t('scenario.population'))} helperText="14 - 250" value={scenario.populationSize} min={14} max={250} step={1} invalid={scenario.populationSize < 14 || scenario.populationSize > 250} invalidText={t('scenario.invalidRange')} onChange={(_event, state) => { const value = numericInputValue(state.value); if (value !== undefined) update({ populationSize: Math.round(value) }); }} />
              <TextInput id="population-profile" labelText={isZh ? '人口配置版本' : 'Population profile'} decorator={parameterHelp('populationProfile', isZh ? '人口配置版本' : 'Population profile')} value={population.profileId} onChange={(event) => updatePopulation({ profileId: event.target.value })} />
              <NumberInput id="institutional-share" label={isZh ? '机构占比' : 'Institutional share'} decorator={parameterHelp('institutionalShare', isZh ? '机构占比' : 'Institutional share')} helperText="0 - 1" value={population.institutionalShare} min={0} max={1} step={0.05} onChange={(_event, state) => { const value = numericInputValue(state.value); if (value !== undefined) updatePopulation({ institutionalShare: value }); }} />
            </div>
            <div className="toggle-grid">
              <div className="toggle-with-help">
                {explained('leverage', isZh ? '杠杆与保证金' : 'Leverage and margin')}
                <Toggle id="population-leverage" aria-label={isZh ? '杠杆与保证金' : 'Leverage and margin'} labelA={isZh ? '关闭' : 'Off'} labelB={isZh ? '开启' : 'On'} toggled={population.leverageEnabled} onToggle={(value) => updatePopulation({ leverageEnabled: value })} />
              </div>
              <div className="toggle-with-help">
                {explained('shortSelling', isZh ? '借券卖空' : 'Borrowed short selling')}
                <Toggle id="population-short-selling" aria-label={isZh ? '借券卖空' : 'Borrowed short selling'} labelA={isZh ? '关闭' : 'Off'} labelB={isZh ? '开启' : 'On'} toggled={population.shortSellingEnabled} onToggle={(value) => updatePopulation({ shortSellingEnabled: value })} />
              </div>
            </div>
            <div className="subsection-heading">
              <h3>{explained('cognitionMode', isZh ? '认知模式与代表性 LLM 节点' : 'Cognition mode and representative LLM nodes')}</h3>
              <p>{isZh ? 'LLM 只能更新证据约束的信念与动作偏好。确定性策略、风控和撮合负责订单与价格。' : 'The LLM can update evidence-bound beliefs and action preferences only. Deterministic policy, risk controls, and matching own orders and prices.'}</p>
            </div>
            <div className="segmented-control" role="radiogroup" aria-label={isZh ? '智能体模式' : 'Agent mode'}>
              {(['RULE_ONLY', 'HYBRID_LLM'] as const).map((mode) => (
                <button type="button" role="radio" aria-checked={llmPolicy.mode === mode} className={llmPolicy.mode === mode ? 'is-active' : ''} key={mode} onClick={() => updateLlmPolicy({ mode })}>
                  {mode === 'RULE_ONLY' ? isZh ? '仅规则' : 'Rule only' : isZh ? '混合 LLM' : 'Hybrid LLM'}
                </button>
              ))}
            </div>
            <div className="number-grid agent-config-grid">
              <Select
                id="scenario-provider"
                labelText={isZh ? '模型供应商' : 'Model provider'}
                decorator={parameterHelp('provider', isZh ? '模型供应商' : 'Model provider')}
                value={llmPolicy.provider}
                disabled={llmPolicy.mode === 'RULE_ONLY'}
                onChange={(event) => {
                  const providerId = event.target.value as LlmProviderId;
                  const provider = modelCatalog?.providers.find((item) => item.id === providerId);
                  const nextModel = provider?.models.find((item) => item.recommended && getLlmModelAvailability(item) === 'READY')
                    ?? provider?.models.find((item) => getLlmModelAvailability(item) === 'READY')
                    ?? provider?.models[0];
                  updateLlmPolicy({ provider: providerId, modelId: nextModel?.id ?? llmPolicy.modelId });
                }}
              >
                {(modelCatalog?.providers ?? []).map((item) => <SelectItem key={item.id} value={item.id} text={`${item.name}${item.id === modelCatalog?.defaultProvider ? isZh ? '（默认）' : ' (default)' : ''}`} />)}
                {!modelCatalog ? <SelectItem value="zhipu" text="Zhipu AI" /> : null}
              </Select>
              <Select id="scenario-model" labelText={isZh ? '模型' : 'Model'} decorator={parameterHelp('model', isZh ? '模型' : 'Model')} value={llmPolicy.modelId} disabled={llmPolicy.mode === 'RULE_ONLY'} onChange={(event) => updateLlmPolicy({ modelId: event.target.value })}>
                {(selectedLlmProvider?.models ?? []).map((item) => {
                  const availability = getLlmModelAvailability(item);
                  const unavailableSuffix = availability === 'PRICE_UNVERIFIED'
                    ? isZh ? '（价格未核验，禁止调用）' : ' (price unverified — blocked)'
                    : availability === 'OUTPUT_LIMIT_UNVERIFIED'
                      ? isZh ? '（输出上限未核验，禁止调用）' : ' (output cap unverified — blocked)'
                      : '';
                  return <SelectItem key={item.id} value={item.id} disabled={availability !== 'READY'} text={`${item.id}${unavailableSuffix}`} />;
                })}
                {!modelCatalog ? <SelectItem value="glm-5.2" text="glm-5.2" /> : null}
              </Select>
              <NumberInput id="scenario-llm-count" label={isZh ? '代表性节点数' : 'Representative node count'} decorator={parameterHelp('representativeLlmAgents', isZh ? '代表性节点数' : 'Representative node count')} min={0} max={100} value={representativeLlmAgentCount} disabled={llmPolicy.mode === 'RULE_ONLY'} onChange={(_event, state) => { const value = numericInputValue(state.value); if (value !== undefined) { const count = Math.round(value); setScenario({ ...scenario, llmPolicy: { ...llmPolicy, representativeAgentCount: count }, population: { ...population, representativeLlmAgents: count } }); } }} />
              <NumberInput id="scenario-llm-interval" label={isZh ? '决策间隔（步）' : 'Decision interval (steps)'} decorator={parameterHelp('decisionInterval', isZh ? '决策间隔（步）' : 'Decision interval (steps)')} min={1} max={100} value={llmPolicy.decisionIntervalSteps} disabled={llmPolicy.mode === 'RULE_ONLY'} onChange={(_event, state) => { const value = numericInputValue(state.value); if (value !== undefined) updateLlmPolicy({ decisionIntervalSteps: Math.round(value) }); }} />
              <NumberInput id="scenario-llm-budget" label={isZh ? '调用预算' : 'Call budget'} decorator={parameterHelp('callBudget', isZh ? '调用预算' : 'Call budget')} min={0} max={500} value={llmPolicy.callBudget} disabled={llmPolicy.mode === 'RULE_ONLY'} onChange={(_event, state) => { const value = numericInputValue(state.value); if (value !== undefined) updateLlmPolicy({ callBudget: Math.round(value) }); }} />
              <NumberInput id="scenario-cost-budget" label={isZh ? '模型费用硬上限（USD）' : 'Model-cost hard cap (USD)'} decorator={parameterHelp('costCap', isZh ? '模型费用硬上限（USD）' : 'Model-cost hard cap (USD)')} helperText={isZh ? '最大责任上限，不是预计账单；调用后按实耗 token 结算' : 'Maximum liability, not an expected bill; actual tokens settle after'} min={0} max={100} step={0.1} value={llmPolicy.maxCostUsd} disabled={llmPolicy.mode === 'RULE_ONLY'} onChange={(_event, state) => { const value = numericInputValue(state.value); if (value !== undefined) updateLlmPolicy({ maxCostUsd: value }); }} />
            </div>
            {llmPolicy.mode === 'HYBRID_LLM' ? (
              <InlineNotification
                kind={selectedLlmModelAvailability === 'READY' ? 'info' : 'error'}
                lowContrast
                hideCloseButton
                title={selectedLlmModelAvailability === 'READY'
                  ? isZh ? '费用硬闸门已启用' : 'Hard cost gate enabled'
                  : selectedLlmModelAvailability === 'OUTPUT_LIMIT_UNVERIFIED'
                    ? isZh ? '该型号输出上限未核验' : 'This model has no verified output cap'
                    : selectedLlmModelAvailability === 'PRICE_UNVERIFIED'
                      ? isZh ? '该型号价格未核验' : 'This model has no verified price'
                      : isZh ? '目录中找不到所选型号' : 'The selected model is missing from the catalog'}
                subtitle={selectedLlmModelAvailability === 'READY'
                  ? isZh
                    ? `费用闸门使用目录中按 ${selectedLlmModel?.billingCurrency ?? '原币种'} 记录的保守输入/输出预留上界，而不是用缓存优惠放宽预算；免费额度、折扣和资源包同样不会放宽上限。价格快照：${modelCatalog?.pricingSnapshotVersion ?? '—'}。`
                    : `The cost gate uses the catalog's conservative input/output reservation bounds in ${selectedLlmModel?.billingCurrency ?? 'the original currency'}; cache discounts, free credits, discounts, and bundles never relax the cap. Pricing snapshot: ${modelCatalog?.pricingSnapshotVersion ?? '—'}.`
                  : selectedLlmModelAvailability === 'OUTPUT_LIMIT_UNVERIFIED'
                    ? isZh
                      ? '系统不会猜测最大输出 token；启用回退时改用规则智能体，否则预检失败，且请求不会发送给供应商。'
                      : 'The system will not guess a maximum output token count. It falls back to rules when allowed; otherwise preflight fails and no provider request is sent.'
                    : isZh
                      ? '系统不会猜测价格或目录记录；启用回退时改用规则智能体，否则预检失败，且请求不会发送给供应商。'
                      : 'The system will not guess a price or catalog entry. It falls back to rules when allowed; otherwise preflight fails and no provider request is sent.'}
              />
            ) : null}
            <div className="toggle-grid">
              <div className="toggle-with-help">
                {explained('ruleFallback', isZh ? '失败时降级为规则智能体' : 'Fall back to rules on failure')}
                <Toggle id="scenario-rule-fallback" aria-label={isZh ? '失败时降级为规则智能体' : 'Fall back to rules on failure'} labelA={isZh ? '禁止' : 'Disabled'} labelB={isZh ? '允许' : 'Enabled'} toggled={llmPolicy.fallbackToRules} onToggle={(value) => updateLlmPolicy({ fallbackToRules: value })} />
              </div>
            </div>
            <Button kind="ghost" size="sm" onClick={() => navigate('ai')}>{isZh ? '配置 API Key 与测试 JSON 输出' : 'Configure API key and test JSON output'}</Button>
          </section>

          <section id="scenario-step-network" className="form-section scenario-step-section">
            <div className="form-section__heading">
              <span className="step-kicker">05</span>
              <h2>{isZh ? '信息传播网络' : 'Information diffusion network'}</h2>
              <p>{isZh ? '网络控制事实、传闻与更正到达各节点的顺序，不得绕过 knownAt。' : 'The network controls the order in which facts, rumors, and corrections reach nodes without bypassing knownAt.'}</p>
            </div>
            <div className="number-grid">
              <Select id="network-topology" labelText={isZh ? '拓扑' : 'Topology'} decorator={parameterHelp('topology', isZh ? '拓扑' : 'Topology')} value={network.topology} onChange={(event) => updateNetwork({ topology: event.target.value as typeof network.topology })}>
                <SelectItem value="ERDOS_RENYI" text="Erdos-Renyi" />
                <SelectItem value="WATTS_STROGATZ" text="Watts-Strogatz" />
                <SelectItem value="BARABASI_ALBERT" text="Barabasi-Albert" />
                <SelectItem value="STOCHASTIC_BLOCK" text={isZh ? '随机区块模型' : 'Stochastic block model'} />
                <SelectItem value="ECHO_CHAMBER" text={isZh ? '回音室' : 'Echo chamber'} />
                <SelectItem value="CORE_PERIPHERY" text={isZh ? '核心-边缘' : 'Core-periphery'} />
              </Select>
              <NumberInput id="network-degree" label={isZh ? '平均度' : 'Average degree'} decorator={parameterHelp('averageDegree', isZh ? '平均度' : 'Average degree')} value={network.averageDegree} min={2} max={50} onChange={(_event, state) => { const value = numericInputValue(state.value); if (value !== undefined) updateNetwork({ averageDegree: Math.round(value) }); }} />
              <NumberInput id="network-rewiring" label={isZh ? '重连概率' : 'Rewiring probability'} decorator={parameterHelp('rewiringProbability', isZh ? '重连概率' : 'Rewiring probability')} value={network.rewiringProbability} min={0} max={1} step={0.01} onChange={(_event, state) => { const value = numericInputValue(state.value); if (value !== undefined) updateNetwork({ rewiringProbability: value }); }} />
              <NumberInput id="network-echo" label={isZh ? '回音室强度' : 'Echo chamber strength'} decorator={parameterHelp('echoChamberStrength', isZh ? '回音室强度' : 'Echo chamber strength')} value={network.echoChamberStrength} min={0} max={1} step={0.05} onChange={(_event, state) => { const value = numericInputValue(state.value); if (value !== undefined) updateNetwork({ echoChamberStrength: value }); }} />
              <NumberInput id="network-correction" label={isZh ? '更正触达率' : 'Correction reach'} decorator={parameterHelp('correctionReach', isZh ? '更正触达率' : 'Correction reach')} value={network.correctionReach} min={0} max={1} step={0.05} onChange={(_event, state) => { const value = numericInputValue(state.value); if (value !== undefined) updateNetwork({ correctionReach: value }); }} />
            </div>
          </section>

          <section id="scenario-step-intervention" className="form-section scenario-step-section">
            <div className="form-section__heading">
              <span className="step-kicker">06</span>
              <h2>{t('scenario.interventionLabel')}</h2>
              <p>{t('scenario.interventionHelp')}</p>
            </div>
            <div className="intervention-options" role="radiogroup" aria-label={t('scenario.interventionLabel')}>
              {OPTIONS.map((option) => {
                const selected = scenario.intervention.parameter === option.parameter;
                return (
                  <label key={option.parameter} className={`intervention-option ${selected ? 'intervention-option--selected' : ''}`}>
                    <input type="radio" name="intervention" value={option.parameter} checked={selected} onChange={() => selectIntervention(option)} />
                    <span className="intervention-option__indicator" aria-hidden="true">{selected ? <CheckCircle size={20} weight="fill" /> : null}</span>
                    <span><strong>{t(option.labelKey)}</strong><small>{t(option.helpKey)}</small></span>
                  </label>
                );
              })}
            </div>
            <div className="number-grid intervention-values">
              <NumberInput id="baseline-value" label={t('scenario.baselineValue')} decorator={parameterHelp('baselineValue', t('scenario.baselineValue'))} helperText={`${selectedOption.min} - ${selectedOption.max} ${selectedOption.unit}`} value={scenario.intervention.baselineValue} min={selectedOption.min} max={selectedOption.max} step={selectedOption.step} invalid={scenario.intervention.baselineValue < selectedOption.min || scenario.intervention.baselineValue > selectedOption.max} invalidText={t('scenario.invalidRange')} onChange={(_event, state) => { const value = numericInputValue(state.value); if (value !== undefined) updateIntervention({ baselineValue: value }); }} />
              <NumberInput id="intervention-value" label={t('scenario.interventionValue')} decorator={parameterHelp('interventionValue', t('scenario.interventionValue'))} helperText={`${selectedOption.min} - ${selectedOption.max} ${selectedOption.unit}`} value={scenario.intervention.interventionValue} min={selectedOption.min} max={selectedOption.max} step={selectedOption.step} invalid={scenario.intervention.interventionValue < selectedOption.min || scenario.intervention.interventionValue > selectedOption.max || scenario.intervention.interventionValue === scenario.intervention.baselineValue} invalidText={t('scenario.invalidRange')} onChange={(_event, state) => { const value = numericInputValue(state.value); if (value !== undefined) updateIntervention({ interventionValue: value }); }} />
            </div>
          </section>

          <section id="scenario-step-review" className="form-section scenario-step-section">
            <div className="form-section__heading">
              <span className="step-kicker">07</span>
              <h2>{isZh ? '实验设计与复核' : 'Experiment design and review'}</h2>
              <p>{t('scenario.seedHelp')}</p>
            </div>
            <div className="field-heading-with-help">
              {explained('matchedSeeds', t('scenario.seedCount'))}
            </div>
            <div className="segmented-control" role="radiogroup" aria-label={t('scenario.seedCount')}>
              {([10, 25, 50] as const).map((count) => (
                <button type="button" role="radio" aria-checked={scenario.seedCount === count} className={scenario.seedCount === count ? 'is-active' : ''} key={count} onClick={() => update({ seedCount: count, stoppingRule: { minimumPairs: Math.min(scenario.stoppingRule?.minimumPairs ?? 10, count), maximumPairs: count, targetCiHalfWidth: scenario.stoppingRule?.targetCiHalfWidth } })}>{count}</button>
              ))}
            </div>
            <div className="number-grid review-config-grid">
              <NumberInput id="simulation-steps" label={t('scenario.steps')} decorator={parameterHelp('simulationSteps', t('scenario.steps'))} helperText="30 - 300" value={scenario.steps} min={30} max={300} step={1} invalid={scenario.steps < 30 || scenario.steps > 300} invalidText={t('scenario.invalidRange')} onChange={(_event, state) => { const value = numericInputValue(state.value); if (value !== undefined) update({ steps: Math.round(value) }); }} />
              <NumberInput id="seed-root" label={isZh ? '根随机种子' : 'Root random seed'} decorator={parameterHelp('rootSeed', isZh ? '根随机种子' : 'Root random seed')} helperText="1 - 2147483000" value={scenario.seedRoot ?? 2_026_070_700} min={1} max={2_147_483_000} step={1} onChange={(_event, state) => { const value = numericInputValue(state.value); if (value !== undefined) update({ seedRoot: Math.round(value) }); }} />
              <Select id="primary-outcome" labelText={isZh ? '主要结果指标' : 'Primary outcome'} decorator={parameterHelp('primaryOutcome', isZh ? '主要结果指标' : 'Primary outcome')} value={scenario.primaryOutcome ?? 'maxSpreadBps'} onChange={(event) => update({ primaryOutcome: event.target.value, secondaryOutcomes: (scenario.secondaryOutcomes ?? []).filter((item) => item !== event.target.value) })}>
                {OUTCOME_OPTIONS.map((outcome) => <SelectItem key={outcome.id} value={outcome.id} text={t(outcome.key)} />)}
              </Select>
              <NumberInput id="minimum-pairs" label={isZh ? '最少有效配对' : 'Minimum valid pairs'} decorator={parameterHelp('minimumPairs', isZh ? '最少有效配对' : 'Minimum valid pairs')} min={5} max={scenario.seedCount} step={1} value={scenario.stoppingRule?.minimumPairs ?? Math.min(10, scenario.seedCount)} onChange={(_event, state) => { const value = numericInputValue(state.value); if (value !== undefined) update({ stoppingRule: { minimumPairs: Math.round(value), maximumPairs: scenario.seedCount, targetCiHalfWidth: scenario.stoppingRule?.targetCiHalfWidth } }); }} />
              <NumberInput id="target-ci-half-width" label={isZh ? '目标 95% 区间半宽（可选）' : 'Target 95% interval half-width (optional)'} decorator={parameterHelp('targetCiHalfWidth', isZh ? '目标 95% 区间半宽（可选）' : 'Target 95% interval half-width (optional)')} min={0.0001} max={100} step={0.01} value={scenario.stoppingRule?.targetCiHalfWidth ?? ''} onChange={(_event, state) => { const rawValue = String(state.value).trim(); const value = numericInputValue(state.value); update({ stoppingRule: { minimumPairs: scenario.stoppingRule?.minimumPairs ?? Math.min(10, scenario.seedCount), maximumPairs: scenario.seedCount, targetCiHalfWidth: rawValue === '' ? undefined : value } }); }} />
            </div>
            <fieldset className="secondary-outcomes">
              <legend>{isZh ? '次要与探索性指标' : 'Secondary and exploratory outcomes'}</legend>
              <p>{isZh ? '主要指标预先登记后保持唯一，次要指标用于解释，不替代主要结论。' : 'The preregistered primary metric remains unique. Secondary metrics support interpretation and do not replace it.'}</p>
              <div>
                {OUTCOME_OPTIONS.filter((outcome) => outcome.id !== scenario.primaryOutcome).map((outcome) => (
                  <SecondaryOutcomeOption
                    key={outcome.id}
                    id={outcome.id}
                    label={t(outcome.key)}
                    checked={(scenario.secondaryOutcomes ?? []).includes(outcome.id)}
                    onChange={() => toggleSecondaryOutcome(outcome.id)}
                  />
                ))}
              </div>
            </fieldset>
            <div className="toggle-grid acknowledgement-grid">
              <Toggle id="ack-scenario" labelText={isZh ? '我理解这是场景分析，不是价格预测' : 'I understand this is scenario analysis, not a price forecast'} labelA={isZh ? '未确认' : 'Not confirmed'} labelB={isZh ? '已确认' : 'Confirmed'} toggled={scenario.acknowledgedScenarioNotForecast ?? false} onToggle={(value) => update({ acknowledgedScenarioNotForecast: value })} />
              <Toggle id="ack-synthetic" labelText={isZh ? '我理解市场路径与机制参数包含合成假设' : 'I understand market paths and mechanism parameters include synthetic assumptions'} labelA={isZh ? '未确认' : 'Not confirmed'} labelB={isZh ? '已确认' : 'Confirmed'} toggled={scenario.acknowledgedSyntheticAssumptions ?? false} onToggle={(value) => update({ acknowledgedSyntheticAssumptions: value })} />
            </div>
          </section>

          <Accordion className="advanced-settings" align="start">
            <AccordionItem title={t('scenario.advanced')}>
              <p>{t('scenario.advancedHelp')}</p>
              <dl className="definition-list">
                <div><dt>{t('scenario.engine')}</dt><dd>{t('scenario.engineValue')}</dd></div>
                <div><dt>{t('scenario.priceAuthority')}</dt><dd>{t('scenario.priceAuthorityValue')}</dd></div>
                <div><dt>{isZh ? '配对设计' : 'Paired design'}</dt><dd>{isZh ? '基准组与干预组共享 seed 与命名随机子流' : 'Baseline and intervention share seeds and named random substreams'}</dd></div>
                <div><dt>{isZh ? '失败策略' : 'Failure policy'}</dt><dd>{isZh ? '无效运行排除并报告；LLM 失败显式记录回退' : 'Invalid runs are excluded and reported; LLM fallbacks are explicit'}</dd></div>
              </dl>
            </AccordionItem>
          </Accordion>
        </div>

        <aside className="scenario-diff" aria-labelledby="scenario-diff-heading">
          <div className="scenario-diff__heading">
            <h2 id="scenario-diff-heading">{t('scenario.diffTitle')}</h2>
            <p>{t('scenario.diffHelp')}</p>
          </div>
          <div className="diff-field">
            <span className="diff-field__name">{t(selectedOption.labelKey)}</span>
            <div className="diff-field__values">
              <div><small>{t('common.baseline')}</small><strong>{scenario.intervention.baselineValue} {selectedOption.unit}</strong></div>
              <ArrowRight size={20} aria-hidden="true" />
              <div><small>{t('common.intervention')}</small><strong>{scenario.intervention.interventionValue} {selectedOption.unit}</strong></div>
            </div>
          </div>
          <dl className="definition-list definition-list--compact">
            <div><dt>{t('scenario.seedCount')}</dt><dd>{scenario.seedCount}</dd></div>
            <div><dt>{t('scenario.population')}</dt><dd>{scenario.populationSize}</dd></div>
            <div><dt>{t('scenario.steps')}</dt><dd>{scenario.steps}</dd></div>
            <div><dt>{isZh ? '网络' : 'Network'}</dt><dd>{network.topology}</dd></div>
            <div><dt>{isZh ? '智能体模式' : 'Agent mode'}</dt><dd>{llmPolicy.mode}</dd></div>
            <div><dt>{isZh ? '预计 LLM 调用上限' : 'Estimated LLM call cap'}</dt><dd>{llmPolicy.mode === 'HYBRID_LLM' ? Math.min(llmPolicy.callBudget, llmPolicy.representativeAgentCount * Math.ceil(scenario.steps / llmPolicy.decisionIntervalSteps)) : 0}</dd></div>
          </dl>
          <Notice>{t('results.disclaimer')}</Notice>
          <Button
            className="scenario-diff__submit"
            renderIcon={ArrowRight}
            disabled={!isFrozen || !scenarioIsWithinBounds || validationState === 'loading'}
            onClick={() => void validate()}
          >
            {validationState === 'loading' ? t('common.loading') : t('scenario.validate')}
          </Button>
        </aside>
      </div>
    </div>
  );
}
