import {
  Button,
  InlineNotification,
  Select,
  SelectItem,
  Tag,
  TextArea,
  TextInput,
} from '@carbon/react';
import {
  ArrowClockwise,
  ChartLineUp,
  Flask,
  Play,
  ShieldWarning,
} from '@phosphor-icons/react';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { getPageGuide } from '../page-guidance';
import type {
  StudyDesignInput,
  StudyDesignKind,
  StudyDesignPreview,
  StudyEvidenceBasis,
  StudyExpectedDirection,
  StudyFactorPath,
  StudyOutcomeId,
  StudyPreset,
  StudyPresetCatalog,
  StudyRunInput,
  StudyRunRecord,
} from '../api/types';
import type { ViewId } from '../app';
import { EmptyState, ErrorPanel, LoadingPanel, Notice, PageHeader } from '../components/common';
import { useI18n } from '../i18n';
import { useWorkflow } from '../state/workflow-context';

interface FactorDraft {
  baseline: number;
  lower: number;
  upper: number;
  evidenceBasis: StudyEvidenceBasis;
  sourceReference: string;
}

const OUTCOME_LABELS: Record<StudyOutcomeId, { en: string; zh: string }> = {
  'max-drawdown-pct': { en: 'Maximum drawdown', zh: '最大回撤' },
  'realized-volatility-pct': { en: 'Realized volatility', zh: '已实现波动率' },
  'max-spread-bps': { en: 'Maximum spread', zh: '最大价差' },
  'min-depth': { en: 'Minimum depth', zh: '最低深度' },
  'recovery-steps': { en: 'Recovery steps', zh: '恢复步数' },
  'total-volume': { en: 'Total volume', zh: '总成交量' },
  'order-imbalance': { en: 'Order imbalance', zh: '订单不平衡' },
  'cascade-score': { en: 'Cascade score', zh: '级联得分' },
  'network-reach-rate': { en: 'Network reach rate', zh: '网络触达率' },
  'information-delay-steps': { en: 'Information delay', zh: '信息延迟' },
  'liquidity-stress-index': { en: 'Liquidity stress index', zh: '流动性压力指数' },
  'tail-loss-probability': { en: 'Tail-loss probability', zh: '尾部损失概率' },
  'abnormal-return-pct': { en: 'Abnormal return', zh: '异常收益' },
};

const FACTOR_LABELS: Record<StudyFactorPath, { en: string; zh: string }> = {
  'intervention.value': { en: 'Intervention value', zh: '干预变量值' },
  'market.fee_bps': { en: 'Market fee', zh: '市场费率' },
  'market.latency_ms': { en: 'Market latency', zh: '市场延迟' },
  'market.price_collar_bps': { en: 'Price collar', zh: '价格笼子' },
  'network.correction_reach': { en: 'Correction reach', zh: '纠正触达率' },
  'network.echo_chamber_strength': { en: 'Echo-chamber strength', zh: '回音室强度' },
  'network.rewiring_probability': { en: 'Rewiring probability', zh: '网络重连概率' },
  'population.institutional_share': { en: 'Institutional share', zh: '机构占比' },
};

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function slug(value: string): string {
  return value
    .toLowerCase()
    .replaceAll(/[^a-z0-9.-]+/g, '-')
    .replaceAll(/^-+|-+$/g, '')
    .slice(0, 64) || 'eventshock-study';
}

function defaultFactorDraft(path: StudyFactorPath, catalog: StudyPresetCatalog): FactorDraft {
  const descriptor = catalog.supportedFactors.find((item) => item.parameterPath === path);
  const minimum = descriptor?.minimum ?? 0;
  const maximum = descriptor?.maximum ?? 1;
  const defaults: Partial<Record<StudyFactorPath, [number, number, number]>> = {
    'intervention.value': [0.5, 1, 1.5],
    'market.fee_bps': [0.1, 0.3, 1],
    'market.latency_ms': [5, 25, 100],
    'market.price_collar_bps': [100, 180, 300],
    'network.correction_reach': [0.2, 0.5, 0.8],
    'network.echo_chamber_strength': [0.2, 0.5, 0.8],
    'network.rewiring_probability': [0.05, 0.2, 0.5],
    'population.institutional_share': [0.1, 0.35, 0.7],
  };
  const [lowerValue, baselineValue, upperValue] = defaults[path] ?? [minimum, (minimum + maximum) / 2, maximum];
  return {
    lower: Math.max(minimum, Math.min(maximum, lowerValue)),
    baseline: Math.max(minimum, Math.min(maximum, baselineValue)),
    upper: Math.max(minimum, Math.min(maximum, upperValue)),
    evidenceBasis: 'ASSUMPTION',
    sourceReference: '',
  };
}

function NumericField({
  id,
  label,
  value,
  minimum,
  maximum,
  step = 'any',
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  minimum: number;
  maximum: number;
  step?: number | 'any';
  onChange: (value: number) => void;
}) {
  return (
    <label className="study-field" htmlFor={id}>
      <span>{label}</span>
      <input
        id={id}
        type="number"
        min={minimum}
        max={maximum}
        step={step}
        value={value}
        onChange={(event) => {
          const nextValue = Number(event.target.value);
          if (Number.isFinite(nextValue)) onChange(nextValue);
        }}
      />
    </label>
  );
}

function ResultWorkbench({ run }: { run: StudyRunRecord }) {
  const { language } = useI18n();
  const isZh = language === 'zh-CN';
  const document = run.result;
  const core = document?.result;
  if (!document || !core) return null;
  const designAnalyses = core.cellOutcomeAnalyses.filter((item) => item.cellId.startsWith('design.'));
  const ablations = core.cells.filter((item) => item.role === 'ABLATION');
  const passedNullControls = core.negativeControls
    .filter((item) => item.expectation === 'NULL_EFFECT')
    .filter((item) => item.outcomeResults.length > 0 && item.outcomeResults.every((outcome) => outcome.result.passed))
    .length;
  const nullControlCount = core.negativeControls.filter((item) => item.expectation === 'NULL_EFFECT').length;
  const format = (value: number, maximumFractionDigits = 4) => new Intl.NumberFormat(language, {
    maximumFractionDigits,
  }).format(value);

  return (
    <section className="study-results" aria-labelledby="study-results-heading">
      <div className="section-heading">
        <span className="eyebrow">{run.studyId}</span>
        <h2 id="study-results-heading">{isZh ? '已执行研究结果' : 'Executed study results'}</h2>
        <p>{document.validityBoundary}</p>
      </div>

      <div className="study-kpis study-kpis--result">
        <div><span>{isZh ? '完成运行' : 'Completed runs'}</span><strong>{core.audit.completedRunCount} / {core.audit.expectedRunCount}</strong></div>
        <div><span>{isZh ? '共同随机种子' : 'Common seeds'}</span><strong>{core.audit.commonRandomSeedScheduleVerified ? 'VERIFIED' : 'FAILED'}</strong></div>
        <div><span>{isZh ? '通过的零效应对照' : 'Null controls passed'}</span><strong>{passedNullControls} / {nullControlCount}</strong></div>
        <div><span>{isZh ? '历史有效性' : 'Historical validity'}</span><strong className="study-negative">NOT ESTABLISHED</strong></div>
      </div>

      <InlineNotification
        kind="warning"
        lowContrast
        hideCloseButton
        title={isZh ? '不能作为历史验证或预测' : 'Not historical validation or a forecast'}
        subtitle={isZh
          ? '所有统计量均为确定性模型内部比较。冻结认知带和代理消融只验证可审计的模型机制边界。'
          : 'Every statistic is a deterministic model-internal comparison. The frozen cognitive tape and proxy ablations test only auditable model-mechanism boundaries.'}
      />

      <div className="study-result-grid">
        <section className="study-panel study-panel--wide">
          <div className="section-heading">
            <h3>{isZh ? '预注册设计单元效应' : 'Preregistered design-cell effects'}</h3>
            <p>{isZh ? '精确 sign test、配对 bootstrap 区间与效应量；先读区间，再读 p 值。' : 'Exact sign tests, paired bootstrap intervals, and effect sizes. Read intervals before p-values.'}</p>
          </div>
          <div className="study-table-wrap">
            <table className="study-table">
              <thead><tr><th>{isZh ? '单元 / 指标' : 'Cell / outcome'}</th><th>{isZh ? '平均差' : 'Mean Δ'}</th><th>95% bootstrap</th><th>p (sign)</th><th>{isZh ? '方向一致率' : 'Sign consistency'}</th></tr></thead>
              <tbody>
                {designAnalyses.map((item) => (
                  <tr key={item.hypothesisId}>
                    <td><strong>{item.cellId}</strong><small>{OUTCOME_LABELS[item.outcomeId][isZh ? 'zh' : 'en']}</small></td>
                    <td>{format(item.analysis.meanDifference)}</td>
                    <td>[{format(item.analysis.bootstrap95.lower)}, {format(item.analysis.bootstrap95.upper)}]</td>
                    <td>{format(item.exactSignPValue, 6)}</td>
                    <td>{format(item.analysis.signConsistency * 100, 1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="study-panel">
          <div className="section-heading">
            <h3>{isZh ? '负对照' : 'Negative controls'}</h3>
            <p>{isZh ? '机制诊断不要求零差异，也不构成现实因果证据。' : 'Mechanism diagnostics need not be null and do not establish real-world causality.'}</p>
          </div>
          <div className="study-control-list">
            {core.negativeControls.map((control) => {
              const passed = control.expectation === 'NULL_EFFECT'
                ? control.outcomeResults.length > 0 && control.outcomeResults.every((item) => item.result.passed)
                : undefined;
              return (
                <details key={control.controlId}>
                  <summary><span><strong>{control.kind.replaceAll('_', ' ')}</strong><small>{control.expectation}</small></span><Tag type={passed === undefined ? 'blue' : passed ? 'green' : 'red'} size="sm">{passed === undefined ? 'DIAGNOSTIC' : passed ? 'PASS' : 'FAIL'}</Tag></summary>
                  <p>{control.interpretationBoundary}</p>
                  {control.outcomeResults.map((item) => <p key={item.outcomeId}><code>{item.outcomeId}</code>: {item.result.reason}</p>)}
                </details>
              );
            })}
          </div>
        </section>

        <section className="study-panel">
          <div className="section-heading">
            <h3>{isZh ? 'Holm 多重比较' : 'Holm multiple comparisons'}</h3>
            <p>{isZh ? '按预注册 family 控制错误率。' : 'Family-wise correction follows the preregistration.'}</p>
          </div>
          <div className="study-control-list">
            {core.holmFamilies.map((family) => (
              <details key={family.familyId}>
                <summary><strong>{family.familyId}</strong><Tag size="sm" type="gray">α {family.alpha}</Tag></summary>
                <div className="study-mini-table">
                  {family.results.map((item) => (
                    <div key={item.hypothesisId}><code>{item.hypothesisId}</code><span>p<sub>adj</sub> {format(item.adjustedPValue, 6)} · {item.rejected ? 'REJECT' : 'RETAIN'}</span></div>
                  ))}
                </div>
              </details>
            ))}
          </div>
        </section>

        <section className="study-panel study-panel--wide">
          <div className="section-heading">
            <h3>{isZh ? '局部敏感性筛查' : 'Local sensitivity screening'}</h3>
            <p>{isZh ? '归一化 Spearman² 是筛查代理，不是 Sobol 分解或现实因果份额。' : 'Normalized Spearman² is a screening proxy, not a Sobol decomposition or real-world causal share.'}</p>
          </div>
          <div className="study-sensitivity-grid">
            {core.sensitivity.map((outcome) => (
              <article key={outcome.outcomeId}>
                <span>{OUTCOME_LABELS[outcome.outcomeId][isZh ? 'zh' : 'en']}</span>
                <strong>{outcome.dominantParameter ?? (isZh ? '无稳定排序信号' : 'No stable rank signal')}</strong>
                <small>{outcome.interpretation.replaceAll('_', ' ')}</small>
                <p>{outcome.warning}</p>
                {outcome.indices.map((item) => <div key={item.parameter}><code>{item.parameter}</code><span>{format(item.varianceImportanceProxy * 100, 1)}%</span></div>)}
              </article>
            ))}
          </div>
        </section>

        <section className="study-panel study-panel--wide">
          <div className="section-heading">
            <h3>{isZh ? '消融与执行边界' : 'Ablations and execution boundaries'}</h3>
            <p>{isZh ? '十个消融臂均执行；当前内核未暴露直接开关的部分使用明确标注的最近可执行代理。' : 'All ten ablation arms execute. Where the kernel lacks a literal switch, it uses the explicitly labeled nearest executable proxy.'}</p>
          </div>
          <div className="study-ablation-grid">
            {ablations.map((cell) => <div key={cell.cellId}><strong>{cell.sourceKind.replaceAll('_', ' ')}</strong><code>{cell.cellId}</code></div>)}
          </div>
          <div className="study-semantics">
            {document.executionProtocol.mechanismSemantics.map((item) => (
              <article key={item.kind}><Tag type={item.status.includes('PROXY') ? 'purple' : 'blue'} size="sm">{item.status}</Tag><strong>{item.kind}</strong><p>{item.boundary}</p></article>
            ))}
          </div>
        </section>
      </div>

      <dl className="study-integrity">
        <div><dt>{isZh ? '预注册哈希' : 'Preregistration hash'}</dt><dd><code>{run.specHash}</code></dd></div>
        <div><dt>{isZh ? '存储结果哈希' : 'Stored result hash'}</dt><dd><code>{run.resultHash}</code></dd></div>
        <div><dt>{isZh ? '核心结果哈希' : 'Core result hash'}</dt><dd><code>{core.audit.resultHash}</code></dd></div>
        <div><dt>{isZh ? '认知协议' : 'Cognition protocol'}</dt><dd><code>{document.executionProtocol.cognitionMode}</code></dd></div>
      </dl>
    </section>
  );
}

export function StudyWorkbenchPage({ navigate }: { navigate: (view: ViewId) => void }) {
  const { language } = useI18n();
  const isZh = language === 'zh-CN';
  const { eventPack } = useWorkflow();
  const [catalog, setCatalog] = useState<StudyPresetCatalog>();
  const [runs, setRuns] = useState<StudyRunRecord[]>([]);
  const [selectedRun, setSelectedRun] = useState<StudyRunRecord>();
  const [selectedPresetId, setSelectedPresetId] = useState('');
  const [studyId, setStudyId] = useState('eventshock-study-v1');
  const [question, setQuestion] = useState('');
  const [primaryOutcomes, setPrimaryOutcomes] = useState<StudyOutcomeId[]>([]);
  const [secondaryOutcomes, setSecondaryOutcomes] = useState<StudyOutcomeId[]>([]);
  const [directions, setDirections] = useState<Partial<Record<StudyOutcomeId, StudyExpectedDirection>>>({});
  const [tolerances, setTolerances] = useState<Partial<Record<StudyOutcomeId, number>>>({});
  const [selectedFactors, setSelectedFactors] = useState<StudyFactorPath[]>([]);
  const [factorDrafts, setFactorDrafts] = useState<Partial<Record<StudyFactorPath, FactorDraft>>>({});
  const [designKind, setDesignKind] = useState<StudyDesignKind>('FULL_FACTORIAL');
  const [sampleCount, setSampleCount] = useState(6);
  const [matchedSeedCount, setMatchedSeedCount] = useState(2);
  const [populationSize, setPopulationSize] = useState(14);
  const [steps, setSteps] = useState(30);
  const [seedRoot, setSeedRoot] = useState(2_026_070_700);
  const [frozenCognitiveRepresentativeCount, setFrozenCognitiveRepresentativeCount] = useState(2);
  const [exclusionRule, setExclusionRule] = useState('Exclude only explicit simulator invariant failures.');
  const [knownLimitation, setKnownLimitation] = useState('This is a model-internal mechanism study, not a forecast or causal proof.');
  const [supportCriterion, setSupportCriterion] = useState('Matched effects follow the preregistered direction.');
  const [contradictionCriterion, setContradictionCriterion] = useState('Matched effects follow the opposite direction.');
  const [inconclusiveCriterion, setInconclusiveCriterion] = useState('Intervals remain wide or a negative control fails.');
  const [preview, setPreview] = useState<StudyDesignPreview>();
  const [previewKey, setPreviewKey] = useState('');
  const [acknowledgeModelBoundary, setAcknowledgeModelBoundary] = useState(false);
  const [acknowledgeProxyAblations, setAcknowledgeProxyAblations] = useState(false);
  const [acknowledgeResourceBudget, setAcknowledgeResourceBudget] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<'preview' | 'run' | 'history'>();
  const [error, setError] = useState<string>();

  const selectedPreset = catalog?.items.find((item) => item.presetId === selectedPresetId);
  const activePackReady = Boolean(
    eventPack
    && selectedPreset
    && eventPack.id === selectedPreset.eventPackId
    && eventPack.status === 'FROZEN',
  );

  const applyPreset = (preset: StudyPreset, nextCatalog: StudyPresetCatalog) => {
    setSelectedPresetId(preset.presetId);
    setStudyId(slug(`${preset.presetId}-study-v1`));
    setQuestion(isZh ? preset.questionZh : preset.question);
    const nextPrimary = preset.primaryOutcomeIds.slice(0, 4);
    const nextSecondary = nextCatalog.supportedOutcomes
      .map((item) => item.outcomeId)
      .filter((item) => !nextPrimary.includes(item))
      .slice(0, 2);
    setPrimaryOutcomes(nextPrimary);
    setSecondaryOutcomes(nextSecondary);
    setDirections(Object.fromEntries(nextPrimary.map((item) => [item, 'TWO_SIDED'])));
    setTolerances(Object.fromEntries(nextPrimary.map((item) => [item, 0.01])));
    const nextFactors = preset.factorPaths.slice(0, 1);
    setSelectedFactors(nextFactors);
    setFactorDrafts(Object.fromEntries(preset.factorPaths.map((path) => [path, defaultFactorDraft(path, nextCatalog)])));
    setPreview(undefined);
    setPreviewKey('');
    setAcknowledgeResourceBudget(false);
  };

  const load = async () => {
    setLoading(true);
    setError(undefined);
    try {
      const [nextCatalog, nextRuns] = await Promise.all([api.getStudyPresets(), api.getStudyRuns()]);
      setCatalog(nextCatalog);
      setRuns(nextRuns);
      const matchingPreset = nextCatalog.items.find((item) => item.eventPackId === eventPack?.id);
      const initialPreset = matchingPreset ?? nextCatalog.items[0];
      if (initialPreset) applyPreset(initialPreset, nextCatalog);
      if (nextRuns[0]) {
        const detail = await api.getStudyRun(nextRuns[0].runId);
        setSelectedRun(detail);
      }
    } catch (loadError) {
      setError(messageOf(loadError));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const design = useMemo<StudyDesignInput | undefined>(() => {
    if (!catalog || selectedFactors.length === 0) return undefined;
    const factors = selectedFactors.flatMap((path) => {
      const draft = factorDrafts[path];
      if (!draft) return [];
      const base = {
        parameterPath: path,
        baselineValue: draft.baseline,
        rationale: `Preregister a bounded model-internal range for ${path}.`,
        evidenceBasis: draft.evidenceBasis,
        ...(draft.evidenceBasis === 'EVIDENCE_BOUND' ? { sourceReference: draft.sourceReference } : {}),
      };
      return [designKind === 'FULL_FACTORIAL'
        ? { ...base, levels: [draft.lower, draft.baseline, draft.upper] }
        : { ...base, lower: draft.lower, upper: draft.upper }];
    });
    return {
      kind: designKind,
      factors,
      ...(designKind === 'LATIN_HYPERCUBE' ? { sampleCount } : {}),
      designSeed: 719,
    };
  }, [catalog, designKind, factorDrafts, sampleCount, selectedFactors]);

  const previewInput = useMemo(() => design ? {
    design,
    matchedSeedCount,
    populationSize,
    steps,
  } : undefined, [design, matchedSeedCount, populationSize, steps]);
  const currentPreviewKey = previewInput ? JSON.stringify(previewInput) : '';

  const updateFactor = (path: StudyFactorPath, changes: Partial<FactorDraft>) => {
    setFactorDrafts((current) => ({
      ...current,
      [path]: { ...current[path]!, ...changes },
    }));
  };

  const togglePrimary = (outcomeId: StudyOutcomeId) => {
    setPrimaryOutcomes((current) => {
      if (current.includes(outcomeId)) return current.length > 2 ? current.filter((item) => item !== outcomeId) : current;
      return current.length < 4 ? [...current, outcomeId] : current;
    });
    setSecondaryOutcomes((current) => current.filter((item) => item !== outcomeId));
    setDirections((current) => ({ ...current, [outcomeId]: current[outcomeId] ?? 'TWO_SIDED' }));
    setTolerances((current) => ({ ...current, [outcomeId]: current[outcomeId] ?? 0.01 }));
  };

  const toggleSecondary = (outcomeId: StudyOutcomeId) => {
    if (primaryOutcomes.includes(outcomeId)) return;
    setSecondaryOutcomes((current) => current.includes(outcomeId)
      ? current.length > 1 ? current.filter((item) => item !== outcomeId) : current
      : current.length < 8 ? [...current, outcomeId] : current);
  };

  const toggleFactor = (path: StudyFactorPath) => {
    setSelectedFactors((current) => current.includes(path)
      ? current.length > 1 ? current.filter((item) => item !== path) : current
      : current.length < 2 ? [...current, path] : current);
  };

  const requestPreview = async () => {
    if (!previewInput) return;
    setBusy('preview');
    setError(undefined);
    try {
      const result = await api.previewStudyDesign(previewInput);
      setPreview(result);
      setPreviewKey(currentPreviewKey);
      setAcknowledgeResourceBudget(false);
    } catch (previewError) {
      setPreview(undefined);
      setPreviewKey('');
      setError(messageOf(previewError));
    } finally {
      setBusy(undefined);
    }
  };

  const runStudy = async () => {
    if (!design || !selectedPreset) return;
    const input: StudyRunInput = {
      eventPackId: selectedPreset.eventPackId,
      preregistration: {
        studyId,
        question,
        claimLevel: 'MODEL_INTERNAL_SENSITIVITY',
        primaryOutcomes: primaryOutcomes.map((outcomeId) => ({
          outcomeId,
          familyId: 'primary-model-internal',
          expectedDirection: directions[outcomeId] ?? 'TWO_SIDED',
          rationale: `Preregister ${outcomeId} before observing any study result.`,
          minimumEffectOfInterest: tolerances[outcomeId] ?? 0,
        })),
        secondaryOutcomes: secondaryOutcomes.map((outcomeId) => ({
          outcomeId,
          familyId: 'secondary-exploratory',
          expectedDirection: 'TWO_SIDED',
          rationale: `Treat ${outcomeId} as a secondary exploratory outcome.`,
        })),
        exclusionRules: [exclusionRule],
        supportCriterion,
        contradictionCriterion,
        inconclusiveCriterion,
        knownLimitations: [knownLimitation],
      },
      design,
      execution: {
        interventionParameter: selectedPreset.recommendedInterventionParameter,
        baselineInterventionValue: factorDrafts['intervention.value']?.baseline ?? 1,
        matchedSeedCount,
        seedRoot,
        populationSize,
        steps,
        frozenCognitiveRepresentativeCount,
      },
      nullToleranceByOutcome: Object.fromEntries(primaryOutcomes.map((outcomeId) => [outcomeId, tolerances[outcomeId] ?? 0.01])),
      alpha: 0.05,
      bootstrapResamples: 100,
      analysisSeed: 719,
      acknowledgedModelInternalOnly: true,
      acknowledgedProxyAblations: true,
    };
    setBusy('run');
    setError(undefined);
    try {
      const result = await api.runStudy(input);
      setSelectedRun(result);
      setRuns((current) => [result, ...current.filter((item) => item.runId !== result.runId)]);
    } catch (runError) {
      setError(messageOf(runError));
    } finally {
      setBusy(undefined);
    }
  };

  const openRun = async (runId: string) => {
    setBusy('history');
    setError(undefined);
    try {
      setSelectedRun(await api.getStudyRun(runId));
    } catch (historyError) {
      setError(messageOf(historyError));
    } finally {
      setBusy(undefined);
    }
  };

  if (loading) {
    return <div className="page"><PageHeader title={isZh ? '研究工作台' : 'Study Workbench'} subtitle={isZh ? '正在加载预注册模板与执行历史。' : 'Loading preregistration templates and execution history.'} /><LoadingPanel /></div>;
  }
  if (!catalog) {
    return <div className="page"><PageHeader title={isZh ? '研究工作台' : 'Study Workbench'} subtitle={isZh ? '无法加载研究 API。' : 'The Study API could not be loaded.'} /><ErrorPanel detail={error} onRetry={() => void load()} /></div>;
  }

  const previewIsCurrent = Boolean(preview && previewKey === currentPreviewKey);
  const formValid = studyId.length >= 1
    && question.length >= 12
    && primaryOutcomes.length >= 2
    && primaryOutcomes.length <= 4
    && secondaryOutcomes.length >= 1
    && selectedFactors.length >= 1
    && selectedFactors.every((path) => {
      const draft = factorDrafts[path];
      return draft && draft.lower < draft.baseline && draft.baseline < draft.upper
        && (draft.evidenceBasis !== 'EVIDENCE_BOUND' || draft.sourceReference.length > 0);
    });
  const canRun = formValid && activePackReady && previewIsCurrent && preview?.withinResourceLimits
    && acknowledgeModelBoundary && acknowledgeProxyAblations && acknowledgeResourceBudget && busy === undefined;

  return (
    <div className="page page--study">
      <PageHeader
        title={isZh ? '研究工作台' : 'Study Workbench'}
        subtitle={isZh
          ? '把模型内部机制问题预注册为有界设计，执行共同随机种子、完整负对照、消融、Holm 校正和敏感性筛查。'
          : 'Preregister a model-mechanism question as a bounded design, then execute common seeds, the full control and ablation suite, Holm correction, and sensitivity screening.'}
        guide={getPageGuide('study', language)}
        actions={<Tag type="purple" size="md">MODEL-INTERNAL ONLY</Tag>}
      />

      {error ? <InlineNotification kind="error" lowContrast hideCloseButton title={isZh ? '研究操作失败' : 'Study operation failed'} subtitle={error} /> : null}
      <InlineNotification
        kind="warning"
        lowContrast
        hideCloseButton
        title={isZh ? '历史有效性尚未建立' : 'Historical validity is not established'}
        subtitle={isZh
          ? '预设不是已执行证据；运行结果也只描述冻结 Event Pack 和当前确定性内核中的模型内部差异。'
          : 'A preset is not executed evidence. A completed run still describes only model-internal differences under the frozen Event Pack and current deterministic kernel.'}
      />

      <div className="study-kpis">
        <div><span>{isZh ? '活动 Event Pack' : 'Active Event Pack'}</span><strong>{eventPack?.id ?? 'NONE'}</strong></div>
        <div><span>{isZh ? '冻结状态' : 'Freeze status'}</span><strong className={activePackReady ? '' : 'study-negative'}>{activePackReady ? 'READY' : 'NOT READY'}</strong></div>
        <div><span>{isZh ? '必做负对照' : 'Required controls'}</span><strong>{catalog.requiredNegativeControlCount}</strong></div>
        <div><span>{isZh ? '必做消融' : 'Required ablations'}</span><strong>{catalog.requiredAblationCount}</strong></div>
      </div>

      <section className="study-panel study-preset-panel">
        <div className="section-heading">
          <span className="eyebrow">01 / PROTOCOL</span>
          <h2>{isZh ? '选择预设与冻结证据' : 'Choose a preset and frozen evidence'}</h2>
          <p>{catalog.validityBoundary}</p>
        </div>
        <Select id="study-preset" labelText={isZh ? '研究预设' : 'Study preset'} value={selectedPresetId} onChange={(event) => {
          const preset = catalog.items.find((item) => item.presetId === event.target.value);
          if (preset) applyPreset(preset, catalog);
        }}>
          {catalog.items.map((preset) => <SelectItem key={preset.presetId} value={preset.presetId} text={isZh ? preset.titleZh : preset.title} />)}
        </Select>
        {selectedPreset ? (
          <div className="study-preset-summary">
            <div><span>Event Pack</span><strong>{selectedPreset.eventPackId}</strong></div>
            <div><span>{isZh ? '推荐干预' : 'Recommended intervention'}</span><strong>{selectedPreset.recommendedInterventionParameter}</strong></div>
            <div><span>{isZh ? '活动证据状态' : 'Active evidence state'}</span><strong>{eventPack?.id === selectedPreset.eventPackId ? eventPack.status : 'NOT SELECTED'}</strong></div>
          </div>
        ) : null}
        {!activePackReady ? (
          <div className="study-inline-action">
            <ShieldWarning size={22} />
            <p>{isZh ? '先从案例库选择此预设对应的案例，逐条审核主张并冻结 Event Pack。' : 'Select this preset’s case in the Case Library, review every claim, and freeze its Event Pack first.'}</p>
            <Button kind="tertiary" size="sm" onClick={() => navigate(eventPack?.id === selectedPreset?.eventPackId ? 'pack' : 'cases')}>{isZh ? '打开审核流程' : 'Open review flow'}</Button>
          </div>
        ) : null}
      </section>

      <div className="study-authoring-grid">
        <section className="study-panel">
          <div className="section-heading">
            <span className="eyebrow">02 / PREREGISTRATION</span>
            <h2>{isZh ? '冻结问题与结果指标' : 'Freeze the question and outcomes'}</h2>
            <p>{isZh ? '正式运行前选择 2–4 个主要指标和至少 1 个次要指标。' : 'Choose 2–4 primary outcomes and at least one secondary outcome before execution.'}</p>
          </div>
          <div className="study-form-stack">
            <TextInput id="study-id" labelText={isZh ? '研究 ID' : 'Study ID'} value={studyId} onChange={(event) => setStudyId(slug(event.target.value))} />
            <TextArea id="study-question" labelText={isZh ? '研究问题' : 'Research question'} value={question} maxCount={1_000} enableCounter onChange={(event) => setQuestion(event.target.value)} />
          </div>
          <fieldset className="study-outcome-picker">
            <legend>{isZh ? `主要指标（${primaryOutcomes.length}/4）` : `Primary outcomes (${primaryOutcomes.length}/4)`}</legend>
            {catalog.supportedOutcomes.map((outcome) => (
              <label key={outcome.outcomeId} className="study-checkbox-card">
                <input type="checkbox" checked={primaryOutcomes.includes(outcome.outcomeId)} onChange={() => togglePrimary(outcome.outcomeId)} />
                <span><strong>{OUTCOME_LABELS[outcome.outcomeId][isZh ? 'zh' : 'en']}</strong><small>{outcome.outcomeId} · {outcome.unit}</small></span>
              </label>
            ))}
          </fieldset>
          <div className="study-primary-config">
            {primaryOutcomes.map((outcomeId) => (
              <div key={outcomeId}>
                <strong>{OUTCOME_LABELS[outcomeId][isZh ? 'zh' : 'en']}</strong>
                <Select id={`direction-${outcomeId}`} labelText={isZh ? '预期方向' : 'Expected direction'} value={directions[outcomeId] ?? 'TWO_SIDED'} onChange={(event) => setDirections((current) => ({ ...current, [outcomeId]: event.target.value as StudyExpectedDirection }))}>
                  <SelectItem value="INCREASE" text={isZh ? '增加' : 'Increase'} />
                  <SelectItem value="DECREASE" text={isZh ? '减少' : 'Decrease'} />
                  <SelectItem value="TWO_SIDED" text={isZh ? '双侧' : 'Two-sided'} />
                </Select>
                <NumericField id={`tolerance-${outcomeId}`} label={isZh ? '零效应容忍度' : 'Null tolerance'} value={tolerances[outcomeId] ?? 0.01} minimum={0} maximum={1_000_000} onChange={(value) => setTolerances((current) => ({ ...current, [outcomeId]: value }))} />
              </div>
            ))}
          </div>
          <fieldset className="study-outcome-picker study-outcome-picker--secondary">
            <legend>{isZh ? `次要指标（${secondaryOutcomes.length}/8）` : `Secondary outcomes (${secondaryOutcomes.length}/8)`}</legend>
            {catalog.supportedOutcomes.filter((outcome) => !primaryOutcomes.includes(outcome.outcomeId)).map((outcome) => (
              <label key={outcome.outcomeId} className="study-checkbox-card">
                <input type="checkbox" checked={secondaryOutcomes.includes(outcome.outcomeId)} onChange={() => toggleSecondary(outcome.outcomeId)} />
                <span><strong>{OUTCOME_LABELS[outcome.outcomeId][isZh ? 'zh' : 'en']}</strong><small>{outcome.outcomeId}</small></span>
              </label>
            ))}
          </fieldset>
          <details className="study-prereg-details">
            <summary>{isZh ? '编辑判定规则与已知限制' : 'Edit decision rules and known limitations'}</summary>
            <TextArea id="study-support" labelText={isZh ? '支持标准' : 'Support criterion'} value={supportCriterion} onChange={(event) => setSupportCriterion(event.target.value)} />
            <TextArea id="study-contradiction" labelText={isZh ? '矛盾标准' : 'Contradiction criterion'} value={contradictionCriterion} onChange={(event) => setContradictionCriterion(event.target.value)} />
            <TextArea id="study-inconclusive" labelText={isZh ? '不确定标准' : 'Inconclusive criterion'} value={inconclusiveCriterion} onChange={(event) => setInconclusiveCriterion(event.target.value)} />
            <TextArea id="study-exclusion" labelText={isZh ? '排除规则' : 'Exclusion rule'} value={exclusionRule} onChange={(event) => setExclusionRule(event.target.value)} />
            <TextArea id="study-limitation" labelText={isZh ? '已知限制' : 'Known limitation'} value={knownLimitation} onChange={(event) => setKnownLimitation(event.target.value)} />
          </details>
        </section>

        <section className="study-panel">
          <div className="section-heading">
            <span className="eyebrow">03 / DESIGN</span>
            <h2>{isZh ? '设置设计因素' : 'Set the design factors'}</h2>
            <p>{isZh ? '当前演示实例最多选择两个因素，以保留完整负对照和消融的资源空间。' : 'This bounded demo selects at most two factors so the complete control and ablation suite remains inside the resource envelope.'}</p>
          </div>
          <Select id="study-design-kind" labelText={isZh ? '设计类型' : 'Design kind'} value={designKind} onChange={(event) => setDesignKind(event.target.value as StudyDesignKind)}>
            <SelectItem value="FULL_FACTORIAL" text={isZh ? '全因子（每因素三水平）' : 'Full factorial (three levels per factor)'} />
            <SelectItem value="LATIN_HYPERCUBE" text={isZh ? '拉丁超立方' : 'Latin hypercube'} />
          </Select>
          <div className="study-factor-toggle">
            {selectedPreset?.factorPaths.map((path) => (
              <label key={path}>
                <input type="checkbox" checked={selectedFactors.includes(path)} onChange={() => toggleFactor(path)} />
                <span>{FACTOR_LABELS[path][isZh ? 'zh' : 'en']}<small>{path}</small></span>
              </label>
            ))}
          </div>
          <div className="study-factor-list">
            {selectedFactors.map((path) => {
              const draft = factorDrafts[path]!;
              const descriptor = catalog.supportedFactors.find((item) => item.parameterPath === path)!;
              return (
                <article key={path}>
                  <div><strong>{FACTOR_LABELS[path][isZh ? 'zh' : 'en']}</strong><code>{descriptor.unit} · [{descriptor.minimum}, {descriptor.maximum}]</code></div>
                  <div className="study-number-grid">
                    <NumericField id={`${path}-lower`} label={isZh ? '下界' : 'Lower'} value={draft.lower} minimum={descriptor.minimum} maximum={descriptor.maximum} step={path === 'market.latency_ms' ? 1 : 'any'} onChange={(value) => updateFactor(path, { lower: value })} />
                    <NumericField id={`${path}-baseline`} label={isZh ? '基准' : 'Baseline'} value={draft.baseline} minimum={descriptor.minimum} maximum={descriptor.maximum} step={path === 'market.latency_ms' ? 1 : 'any'} onChange={(value) => updateFactor(path, { baseline: value })} />
                    <NumericField id={`${path}-upper`} label={isZh ? '上界' : 'Upper'} value={draft.upper} minimum={descriptor.minimum} maximum={descriptor.maximum} step={path === 'market.latency_ms' ? 1 : 'any'} onChange={(value) => updateFactor(path, { upper: value })} />
                  </div>
                  <Select id={`${path}-evidence`} labelText={isZh ? '参数依据' : 'Evidence basis'} value={draft.evidenceBasis} onChange={(event) => updateFactor(path, { evidenceBasis: event.target.value as StudyEvidenceBasis })}>
                    <SelectItem value="ASSUMPTION" text={isZh ? '假设' : 'Assumption'} />
                    <SelectItem value="EVIDENCE_BOUND" text={isZh ? '证据约束' : 'Evidence-bound'} />
                    <SelectItem value="SYNTHETIC" text={isZh ? '合成设定' : 'Synthetic'} />
                  </Select>
                  {draft.evidenceBasis === 'EVIDENCE_BOUND' ? <TextInput id={`${path}-source`} labelText={isZh ? '来源引用' : 'Source reference'} value={draft.sourceReference} onChange={(event) => updateFactor(path, { sourceReference: event.target.value })} /> : null}
                </article>
              );
            })}
          </div>
          {designKind === 'LATIN_HYPERCUBE' ? <NumericField id="study-sample-count" label={isZh ? '设计样本数' : 'Design sample count'} value={sampleCount} minimum={3} maximum={16} step={1} onChange={(value) => setSampleCount(Math.round(value))} /> : null}
        </section>
      </div>

      <section className="study-panel study-execution-panel">
        <div className="section-heading">
          <span className="eyebrow">04 / RESOURCE GATE</span>
          <h2>{isZh ? '预览资源并确认边界' : 'Preview resources and confirm boundaries'}</h2>
          <p>{isZh ? '运行会同步执行所有设计单元、8 个负对照和 10 个消融；更改配置后必须重新预览。' : 'Execution synchronously runs every design cell, 8 controls, and 10 ablations. Any configuration change requires a new preview.'}</p>
        </div>
        <div className="study-execution-config">
          <NumericField id="study-seeds" label={isZh ? '共同随机种子数' : 'Matched seeds'} value={matchedSeedCount} minimum={2} maximum={4} step={1} onChange={(value) => setMatchedSeedCount(Math.round(value))} />
          <NumericField id="study-population" label={isZh ? 'Agent 数量' : 'Population'} value={populationSize} minimum={14} maximum={28} step={1} onChange={(value) => setPopulationSize(Math.round(value))} />
          <NumericField id="study-steps" label={isZh ? '仿真步数' : 'Simulation steps'} value={steps} minimum={30} maximum={60} step={1} onChange={(value) => setSteps(Math.round(value))} />
          <NumericField id="study-seed-root" label={isZh ? '随机种子根' : 'Seed root'} value={seedRoot} minimum={1} maximum={2_147_483_000} step={1} onChange={(value) => setSeedRoot(Math.round(value))} />
          <NumericField id="study-cognitive-agents" label={isZh ? '冻结认知代表数' : 'Frozen cognitive representatives'} value={frozenCognitiveRepresentativeCount} minimum={0} maximum={4} step={1} onChange={(value) => setFrozenCognitiveRepresentativeCount(Math.round(value))} />
        </div>
        <Button kind="tertiary" renderIcon={ChartLineUp} disabled={!formValid || busy !== undefined} onClick={() => void requestPreview()}>{busy === 'preview' ? isZh ? '正在计算' : 'Calculating' : isZh ? '预览完整设计' : 'Preview full design'}</Button>
        {preview && previewIsCurrent ? (
          <div className="study-budget">
            <div><span>{isZh ? '设计单元' : 'Design cells'}</span><strong>{preview.designCellCount}</strong></div>
            <div><span>{isZh ? '总执行单元' : 'Execution cells'}</span><strong>{preview.totalExecutionCells}</strong></div>
            <div><span>{isZh ? '总运行数' : 'Total runs'}</span><strong>{preview.expectedRunCount} / {preview.maximumRunCount}</strong></div>
            <div><span>{isZh ? '工作单元' : 'Work units'}</span><strong>{preview.estimatedWorkUnits.toLocaleString(language)} / {preview.maximumWorkUnits.toLocaleString(language)}</strong></div>
          </div>
        ) : preview ? <Notice>{isZh ? '配置已改变；运行前请重新预览。' : 'The configuration changed. Preview it again before running.'}</Notice> : null}
        <div className="study-confirmations">
          <label><input type="checkbox" checked={acknowledgeModelBoundary} onChange={(event) => setAcknowledgeModelBoundary(event.target.checked)} /><span>{isZh ? '我理解这是模型内部敏感性研究，不是历史验证、现实因果证明或预测。' : 'I understand this is a model-internal sensitivity study, not historical validation, real-world causal proof, or a forecast.'}</span></label>
          <label><input type="checkbox" checked={acknowledgeProxyAblations} onChange={(event) => setAcknowledgeProxyAblations(event.target.checked)} /><span>{isZh ? '我理解冻结认知带不会调用实时 LLM，部分消融是有界的最近可执行代理。' : 'I understand the frozen cognitive tape makes no live LLM call and some ablations are bounded nearest-executable proxies.'}</span></label>
          <label><input type="checkbox" checked={acknowledgeResourceBudget} disabled={!previewIsCurrent} onChange={(event) => setAcknowledgeResourceBudget(event.target.checked)} /><span>{isZh ? '我确认上方完整运行数和资源预算。' : 'I confirm the complete run count and resource budget shown above.'}</span></label>
        </div>
        <Button renderIcon={Play} disabled={!canRun} onClick={() => void runStudy()}>{busy === 'run' ? isZh ? '正在执行完整研究' : 'Executing full study' : isZh ? '运行预注册研究' : 'Run preregistered study'}</Button>
      </section>

      <section className="study-panel study-history-panel">
        <div className="section-heading section-heading--with-control">
          <div><span className="eyebrow">05 / IMMUTABLE HISTORY</span><h2>{isZh ? '研究历史' : 'Study history'}</h2><p>{isZh ? '每次完成的预注册和结果都以哈希保存，不能原地修改。' : 'Each completed preregistration and result is hash-pinned and cannot be edited in place.'}</p></div>
          <Button kind="ghost" size="sm" renderIcon={ArrowClockwise} disabled={busy !== undefined} onClick={() => void load()}>{isZh ? '刷新' : 'Refresh'}</Button>
        </div>
        {runs.length === 0 ? <EmptyState icon={<Flask size={28} />} title={isZh ? '还没有研究运行' : 'No Study runs yet'} body={isZh ? '完成资源预览与三项确认后运行第一个预注册研究。' : 'Preview resources and complete all three confirmations to run the first preregistered study.'} /> : (
          <div className="study-history-list">
            {runs.map((run) => (
              <button key={run.runId} type="button" className={selectedRun?.runId === run.runId ? 'is-active' : ''} onClick={() => void openRun(run.runId)}>
                <span><strong>{run.studyId}</strong><small>{run.runId}</small></span>
                <span><time>{run.createdAt ? new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(run.createdAt)) : ''}</time><Tag size="sm" type="green">COMPLETED</Tag></span>
              </button>
            ))}
          </div>
        )}
      </section>

      {busy === 'history' ? <LoadingPanel /> : selectedRun ? <ResultWorkbench run={selectedRun} /> : null}
    </div>
  );
}
