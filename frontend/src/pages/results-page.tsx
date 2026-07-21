import { Button, InlineNotification, Modal, Select, SelectItem, Tag, TextArea } from '@carbon/react';
import { ArrowRight, Brain, ChartLineUp, Trash, Warning } from '@phosphor-icons/react';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { Navigate } from '../app';
import type { InvalidationReasonCode, MetricResult } from '../api/types';
import { buildHistogram } from '../api/normalize';
import { EmptyState, LoadingPanel, Notice, PageHeader, StatusBadge } from '../components/common';
import { ExperimentHistoryDisclosure, experimentHistoryLabel } from '../components/experiment-history';
import { translateAgentType, translateParameter, translateStatus, useI18n } from '../i18n';
import { useWorkflow } from '../state/workflow-context';
import { formatInterval, formatMetricValue } from '../utils/format';

const METRIC_CATALOG = [
  { id: 'maxDrawdownPct', labelKey: 'metric.maxDrawdown' as const },
  { id: 'realizedVolatilityPct', labelKey: 'metric.realizedVolatility' as const },
  { id: 'maxSpreadBps', labelKey: 'metric.peakSpread' as const },
  { id: 'minDepth', labelKey: 'metric.minDepth' as const },
  { id: 'recoverySteps', labelKey: 'metric.recoveryTime' as const },
  { id: 'totalVolume', labelKey: 'metric.totalVolume' as const },
  { id: 'orderImbalance', labelKey: 'metric.orderImbalance' as const },
  { id: 'cascadeScore', labelKey: 'metric.cascadeScore' as const },
];

const EXTENDED_METRIC_LABELS: Record<string, { en: string; zh: string }> = {
  returnQuantile05Pct: { en: '5% return quantile', zh: '收益率 5% 分位数' },
  returnQuantile01Pct: { en: '1% return quantile', zh: '收益率 1% 分位数' },
  expectedShortfallPct: { en: 'Expected shortfall', zh: '期望损失' },
  drawdownDurationSteps: { en: 'Drawdown duration', zh: '回撤持续时间' },
  relativeSpreadBps: { en: 'Relative spread', zh: '相对价差' },
  effectiveSpreadBps: { en: 'Effective spread', zh: '有效价差' },
  depth10Bps: { en: 'Depth within 10 bps', zh: '正负 10 bps 深度' },
  depth25Bps: { en: 'Depth within 25 bps', zh: '正负 25 bps 深度' },
  amihudIlliquidity: { en: 'Amihud illiquidity proxy', zh: 'Amihud 非流动性代理' },
  kyleImpactProxy: { en: 'Kyle-style impact proxy', zh: 'Kyle 风格冲击代理' },
  orderToTradeRatio: { en: 'Order-to-trade ratio', zh: '订单成交比' },
  cancellationRate: { en: 'Cancellation rate', zh: '撤单率' },
  fillRate: { en: 'Fill rate', zh: '成交率' },
  rejectionRate: { en: 'Rejection rate', zh: '拒单率' },
  marketOrderShare: { en: 'Market-order share', zh: '市价单占比' },
  averageQueueTime: { en: 'Average queue time', zh: '平均排队时间' },
  herdingRate: { en: 'Directional herding', zh: '方向羊群率' },
  beliefDispersion: { en: 'Belief dispersion', zh: '信念离散度' },
  forcedLiquidations: { en: 'Forced liquidations', zh: '强制平仓数量' },
  systemEventsPerSecond: { en: 'Simulation throughput', zh: '仿真吞吐量' },
  networkReachRate: { en: 'Information-network reach', zh: '信息网络触达率' },
  informationDelaySteps: { en: 'Information delay', zh: '信息延迟' },
  liquidityStressIndex: { en: 'Liquidity stress index', zh: '流动性压力指数' },
  tailLossProbability: { en: 'Tail-loss probability', zh: '尾部损失概率' },
  agentPnlDispersionCents: { en: 'Agent P&L dispersion', zh: '智能体损益离散度' },
  systemEquityChangeCents: { en: 'System equity change', zh: '系统权益变化' },
  forcedLiquidationVolume: { en: 'Forced-liquidation volume', zh: '强制平仓量' },
  ledgerRejectedOrders: { en: 'Ledger-rejected orders', zh: '账本拒绝订单数' },
  cognitiveOrderCount: { en: 'Cognition-influenced orders', zh: '认知信号影响订单数' },
  benchmarkReturnPct: { en: 'Benchmark return', zh: '基准收益率' },
  abnormalReturnPct: { en: 'Abnormal return', zh: '异常收益率' },
  haltCount: { en: 'Trading halts', zh: '停牌次数' },
  haltedSteps: { en: 'Halted steps', zh: '停牌步数' },
  totalFeesPaidCents: { en: 'Total fees paid', zh: '总支付费用' },
};

function formatCents(value: number | undefined, language: 'en' | 'zh-CN'): string {
  if (value === undefined || !Number.isFinite(value)) return language === 'zh-CN' ? '暂无数据' : 'Not available';
  return new Intl.NumberFormat(language, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(value / 100);
}

function resultMetricLabel(metric: MetricResult, language: 'en' | 'zh-CN', t: ReturnType<typeof useI18n>['t']): string {
  const canonical = METRIC_CATALOG.find((item) => item.id === metric.id);
  if (canonical) return t(canonical.labelKey);
  const extended = EXTENDED_METRIC_LABELS[metric.id];
  if (extended) return language === 'zh-CN' ? extended.zh : extended.en;
  return metric.label.replaceAll('_', ' ');
}

function metricRows(metrics: MetricResult[]): Array<MetricResult & { labelKey?: (typeof METRIC_CATALOG)[number]['labelKey'] }> {
  const byId = new Map(metrics.map((metric) => [metric.id, metric]));
  const canonicalRows = METRIC_CATALOG.map((definition) => ({
    id: definition.id,
    label: byId.get(definition.id)?.label ?? definition.id,
    labelKey: definition.labelKey,
    ...byId.get(definition.id),
  }));
  const extraRows = metrics
    .filter((metric) => !METRIC_CATALOG.some((definition) => definition.id === metric.id))
    .map((metric) => ({ ...metric }));
  return [...canonicalRows, ...extraRows];
}

function ChartEmpty() {
  const { t } = useI18n();
  return <div className="chart-empty"><ChartLineUp size={28} weight="duotone" /><p>{t('results.noChart')}</p></div>;
}

export function ResultsPage({ navigate }: { navigate: Navigate }) {
  const { language, t } = useI18n();
  const {
    activeExperiment,
    experiments,
    results,
    resultsState,
    resultsError,
    loadResults,
    selectExperiment,
    invalidateActiveExperiment,
  } = useWorkflow();
  const [pathMetric, setPathMetric] = useState<'price' | 'spread' | 'depth'>('price');
  const [analysisMetricId, setAnalysisMetricId] = useState('maxSpreadBps');
  const [invalidationOpen, setInvalidationOpen] = useState(false);
  const [invalidationReasonCode, setInvalidationReasonCode] = useState<InvalidationReasonCode>('OTHER');
  const [invalidationReason, setInvalidationReason] = useState('');
  const [invalidationError, setInvalidationError] = useState<string>();
  const [invalidationBusy, setInvalidationBusy] = useState(false);
  const [historyError, setHistoryError] = useState<string>();
  const historyRequestGeneration = useRef(0);
  const metrics = useMemo(() => metricRows(results?.metrics ?? []), [results?.metrics]);
  const primaryMetricId = results?.stoppingRule?.primaryOutcome
    ?? results?.analysisDiagnostics?.preregisteredPrimaryOutcome
    ?? results?.primaryMetricId;
  const primaryMetricUnit = results?.metrics.find((metric) => metric.id === primaryMetricId)?.unit;

  const openHistoricalExperiment = async (experimentId: string) => {
    const requestGeneration = ++historyRequestGeneration.current;
    setHistoryError(undefined);
    try {
      const experiment = await selectExperiment(experimentId);
      if (!experiment || requestGeneration !== historyRequestGeneration.current) return;
      if (experiment.status === 'COMPLETED') {
        const nextResults = await loadResults(experiment.id);
        if (nextResults && requestGeneration === historyRequestGeneration.current) {
          navigate('results', experiment.id);
        }
        return;
      }
      if (experiment.status === 'INVALIDATED') {
        navigate('results', experiment.id);
        return;
      }
      navigate('runs');
    } catch (error) {
      if (requestGeneration === historyRequestGeneration.current) {
        setHistoryError(error instanceof Error ? error.message : String(error));
      }
    }
  };
  const historySelector = experiments.length > 0 ? (
    <section className="history-selector" aria-label={language === 'zh-CN' ? '切换历史实验' : 'Switch historical experiment'}>
      <Select
        id="results-history-experiment"
        labelText={language === 'zh-CN' ? '查看历史实验结果' : 'View historical experiment result'}
        value={activeExperiment?.id ?? ''}
        onChange={(event) => void openHistoricalExperiment(event.target.value)}
      >
        <SelectItem value="" text={language === 'zh-CN' ? '请选择实验' : 'Select an experiment'} disabled />
        {experiments.map((experiment) => (
          <SelectItem
            key={experiment.id}
            value={experiment.id}
            text={experimentHistoryLabel(experiment, language)}
          />
        ))}
      </Select>
      {historyError ? (
        <InlineNotification kind="error" lowContrast hideCloseButton title={t('common.errorTitle')} subtitle={historyError} />
      ) : null}
      <ExperimentHistoryDisclosure />
    </section>
  ) : null;

  useEffect(() => {
    const preferred = activeExperiment?.scenario?.primaryOutcome ?? results?.primaryMetricId;
    if (preferred && results?.pairedSeries[preferred]) setAnalysisMetricId(preferred);
  }, [activeExperiment?.scenario?.primaryOutcome, results?.experimentId, results?.primaryMetricId]);

  if (!activeExperiment) {
    return (
      <div className="page">
        <PageHeader title={t('results.title')} subtitle={t('results.subtitle')} />
        {historySelector}
        <EmptyState
          title={t('results.selectTitle')}
          body={t('results.selectBody')}
          action={<Button kind="tertiary" onClick={() => navigate('runs')}>{t('nav.runs')}</Button>}
        />
      </div>
    );
  }

  if (activeExperiment.status === 'INVALIDATED') {
    return (
      <div className="page">
        <PageHeader title={t('results.title')} subtitle={t('results.subtitle')} actions={<StatusBadge status={activeExperiment.status} />} />
        {historySelector}
        <InlineNotification
          kind="error"
          lowContrast
          hideCloseButton
          title={language === 'zh-CN' ? '此实验结果已经作废' : 'This experiment result is invalidated'}
          subtitle={`${activeExperiment.invalidationReasonCode ?? 'OTHER'} — ${activeExperiment.invalidationReason ?? (language === 'zh-CN' ? '结果已保留供审计，但不能读取、导出或用于研究。' : 'The result is retained for audit but cannot be read, exported, or used for research.')}`}
        />
        <EmptyState
          title={language === 'zh-CN' ? '研究工件不可用' : 'Research artifact unavailable'}
          body={language === 'zh-CN' ? '返回运行中心查看作废时间和原因。' : 'Return to Run Center to inspect the invalidation time and reason.'}
          action={<Button kind="tertiary" onClick={() => navigate('runs')}>{t('nav.runs')}</Button>}
        />
      </div>
    );
  }

  if (resultsState === 'loading') return <div className="page"><PageHeader title={t('results.title')} subtitle={t('results.subtitle')} />{historySelector}<LoadingPanel /></div>;

  if (!results) {
    return (
      <div className="page">
        <PageHeader title={t('results.title')} subtitle={t('results.subtitle')} />
        {historySelector}
        {resultsError ? <InlineNotification kind="error" lowContrast hideCloseButton title={t('common.errorTitle')} subtitle={t('common.errorFallback')} /> : null}
        <EmptyState
          title={t('results.pendingTitle')}
          body={t('results.pendingBody')}
          action={activeExperiment.status === 'COMPLETED' ? (
            <Button onClick={() => void loadResults()}>{t('results.load')}</Button>
          ) : (
            <Button kind="tertiary" onClick={() => navigate('runs')}>{t('nav.runs')}</Button>
          )}
        />
      </div>
    );
  }

  const pathFields = {
    price: { baseline: 'baselinePrice', intervention: 'interventionPrice', label: t('results.price') },
    spread: { baseline: 'baselineSpread', intervention: 'interventionSpread', label: t('results.spread') },
    depth: { baseline: 'baselineDepth', intervention: 'interventionDepth', label: t('results.depth') },
  } as const;
  const selectedFields = pathFields[pathMetric];
  const pairedSeries = results.pairedSeries[analysisMetricId] ?? [];
  const selectedMetric = results.metrics.find((metric) => metric.id === analysisMetricId);
  const distribution = buildHistogram(pairedSeries);
  const robustness = results.robustness ?? (results.analysisDiagnostics ? {
    sensitivityStatus: results.analysisDiagnostics.localSensitivity.status,
    ablationStatus: 'NOT_EVALUATED',
    negativeControlStatus: results.analysisDiagnostics.negativeControl.passed === true
      ? 'PASS'
      : results.analysisDiagnostics.negativeControl.passed === false
        ? 'FAIL'
        : results.analysisDiagnostics.negativeControl.status,
    knockoutStatus: results.analysisDiagnostics.parameterRestorationKnockout.mechanismSupported === true
      ? 'PASS'
      : results.analysisDiagnostics.parameterRestorationKnockout.mechanismSupported === false
        ? 'FAIL'
        : results.analysisDiagnostics.parameterRestorationKnockout.status,
    notes: [results.analysisDiagnostics.interpretationBoundary.replaceAll('_', ' ')],
  } : {
    sensitivityStatus: 'NOT_EVALUATED',
    ablationStatus: 'NOT_EVALUATED',
    negativeControlStatus: 'NOT_EVALUATED',
    knockoutStatus: 'NOT_EVALUATED',
    notes: [],
  });

  const invalidate = async () => {
    setInvalidationError(undefined);
    setInvalidationBusy(true);
    try {
      await invalidateActiveExperiment(invalidationReasonCode, invalidationReason.trim());
      setInvalidationOpen(false);
      navigate('runs');
    } catch (error) {
      setInvalidationError(error instanceof Error ? error.message : String(error));
    } finally {
      setInvalidationBusy(false);
    }
  };

  return (
    <div className="page page--results">
      <PageHeader
        title={t('results.title')}
        subtitle={t('results.subtitle')}
        actions={(
          <div className="page-header-action-group">
            <StatusBadge status={activeExperiment.status} />
            {activeExperiment.status === 'COMPLETED' ? (
              <Button kind="danger--tertiary" renderIcon={Trash} onClick={() => setInvalidationOpen(true)}>
                {language === 'zh-CN' ? '作废结果' : 'Invalidate result'}
              </Button>
            ) : null}
          </div>
        )}
      />
      {historySelector}
      <Notice>{t('results.disclaimer')}</Notice>
      <Modal
        open={invalidationOpen}
        danger
        modalHeading={language === 'zh-CN' ? '作废实验结果' : 'Invalidate experiment result'}
        modalLabel={activeExperiment.id}
        primaryButtonText={language === 'zh-CN' ? '确认作废' : 'Invalidate'}
        secondaryButtonText={t('common.cancel')}
        primaryButtonDisabled={invalidationBusy || invalidationReason.trim().length < 8}
        onRequestClose={() => setInvalidationOpen(false)}
        onRequestSubmit={() => void invalidate()}
      >
        <p className="modal-help">{language === 'zh-CN'
          ? '作废会保留结果和审计哈希，但立即禁止结果读取与导出，并标记为不可用于研究。该操作不能在界面中撤销。'
          : 'Invalidation preserves the result and audit hash, but immediately blocks result access and export and marks the artifact as unusable for research. This cannot be reversed in the interface.'}</p>
        <Select
          id="invalidation-reason-code"
          labelText={language === 'zh-CN' ? '原因分类' : 'Reason category'}
          value={invalidationReasonCode}
          onChange={(event) => setInvalidationReasonCode(event.target.value as InvalidationReasonCode)}
        >
          <SelectItem value="DATA_ISSUE" text={language === 'zh-CN' ? '数据问题' : 'Data issue'} />
          <SelectItem value="MODEL_ISSUE" text={language === 'zh-CN' ? '模型问题' : 'Model issue'} />
          <SelectItem value="METRIC_ISSUE" text={language === 'zh-CN' ? '指标问题' : 'Metric issue'} />
          <SelectItem value="SECURITY_INCIDENT" text={language === 'zh-CN' ? '安全事件' : 'Security incident'} />
          <SelectItem value="OTHER" text={language === 'zh-CN' ? '其他' : 'Other'} />
        </Select>
        <TextArea
          id="invalidation-reason"
          labelText={language === 'zh-CN' ? '具体原因（至少 8 个字符）' : 'Specific reason (at least 8 characters)'}
          value={invalidationReason}
          rows={4}
          onChange={(event) => setInvalidationReason(event.target.value)}
        />
        {invalidationError ? (
          <InlineNotification kind="error" lowContrast hideCloseButton title={t('common.errorTitle')} subtitle={invalidationError} />
        ) : null}
      </Modal>

      {results.narrativeReport ? (
        <section className="result-narrative" aria-labelledby="result-narrative-heading">
          <div>
            <Tag type="cool-gray" size="sm">{results.narrativeReport.generatedBy.replaceAll('_', ' ')}</Tag>
            <h2 id="result-narrative-heading">{language === 'zh-CN' ? results.narrativeReport.headlineZh ?? results.narrativeReport.headline : results.narrativeReport.headline}</h2>
            <p>{language === 'zh-CN' ? results.narrativeReport.summaryZh ?? results.narrativeReport.summary : results.narrativeReport.summary}</p>
          </div>
          <aside>
            <strong>{language === 'zh-CN' ? '解释边界' : 'Interpretation boundary'}</strong>
            <p>{language === 'zh-CN' ? results.narrativeReport.interpretationBoundaryZh ?? results.narrativeReport.interpretationBoundary : results.narrativeReport.interpretationBoundary}</p>
            <code>{results.narrativeReport.schemaVersion}</code>
          </aside>
        </section>
      ) : null}

      <section className="result-section" aria-labelledby="metrics-heading">
        <div className="section-heading">
          <h2 id="metrics-heading">{t('results.metrics')}</h2>
          <p>{t('results.metricsHelp')}</p>
        </div>
        <div className="metric-grid">
          {metrics.map((metric) => (
            <article key={metric.id} className="metric-cell">
              <div className="metric-cell__heading">
                <h3>{resultMetricLabel(metric, language, t)}</h3>
                {metric.stable !== undefined ? <StatusBadge status={metric.stable ? 'VALID' : 'INVALID'} /> : null}
              </div>
              <div className="metric-cell__values">
                <div><span>{t('common.baseline')}</span><strong>{formatMetricValue(metric.baseline, metric.unit, language)}</strong></div>
                <div><span>{t('common.intervention')}</span><strong>{formatMetricValue(metric.intervention, metric.unit, language)}</strong></div>
                <div className="metric-cell__delta"><span>{t('common.delta')}</span><strong>{formatMetricValue(metric.delta, metric.unit, language)}</strong></div>
              </div>
              <footer>
                <span>{t('common.interval')} {formatInterval(metric.ciLow, metric.ciHigh, metric.unit, language)}</span>
                <span>{t('common.sampleSize')} {metric.n ?? t('common.unavailable')}</span>
                {metric.directionConsistencyRate !== undefined ? <span>{t('results.consistency')} {formatMetricValue(metric.directionConsistencyRate, 'ratio', language)}</span> : null}
                <span>{language === 'zh-CN' ? '排除运行' : 'Excluded runs'} {metric.excludedRuns ?? 0}</span>
              </footer>
              {(metric.bootstrapCiLow !== undefined || metric.cohensDz !== undefined || metric.positiveTailProbability !== undefined) ? (
                <details className="metric-diagnostics">
                  <summary>{language === 'zh-CN' ? '配对统计诊断' : 'Paired statistical diagnostics'}</summary>
                  <dl>
                    <div><dt>{language === 'zh-CN' ? 'Bootstrap 95% 区间' : 'Bootstrap 95% interval'}</dt><dd>{formatInterval(metric.bootstrapCiLow, metric.bootstrapCiHigh, metric.unit, language)}</dd></div>
                    <div><dt>{language === 'zh-CN' ? '区间包含零' : 'Interval contains zero'}</dt><dd>{metric.bootstrapContainsZero === undefined ? t('common.unavailable') : metric.bootstrapContainsZero ? language === 'zh-CN' ? '是' : 'Yes' : language === 'zh-CN' ? '否' : 'No'}</dd></div>
                    <div><dt>Cohen's dz</dt><dd>{formatMetricValue(metric.cohensDz, undefined, language)}</dd></div>
                    <div><dt>{language === 'zh-CN' ? '配对秩二列相关' : 'Matched rank-biserial'}</dt><dd>{formatMetricValue(metric.matchedRankBiserial, undefined, language)}</dd></div>
                    <div><dt>{language === 'zh-CN' ? '符号一致率' : 'Sign consistency'}</dt><dd>{formatMetricValue(metric.signConsistency, 'ratio', language)}</dd></div>
                    <div><dt>P(Δ &gt; 0)</dt><dd>{formatMetricValue(metric.positiveTailProbability, 'ratio', language)}</dd></div>
                    <div><dt>P(Δ &lt; 0)</dt><dd>{formatMetricValue(metric.negativeTailProbability, 'ratio', language)}</dd></div>
                  </dl>
                </details>
              ) : null}
              {metric.sensitivityFlag ? <Tag type={metric.sensitivityFlag === 'STABLE' ? 'green' : 'warm-gray'} size="sm">{metric.sensitivityFlag.replaceAll('_', ' ')}</Tag> : null}
              {metric.interpretation || metric.interpretationZh ? <p className="metric-cell__interpretation">{language === 'zh-CN' ? metric.interpretationZh ?? metric.interpretation : metric.interpretation}</p> : null}
              {metric.limitation || metric.limitationZh ? <p className="metric-cell__limitation">{language === 'zh-CN' ? metric.limitationZh ?? metric.limitation : metric.limitation}</p> : null}
            </article>
          ))}
        </div>
      </section>

      <div className="chart-grid">
        <section className="chart-panel" aria-labelledby="paired-heading">
          <div className="section-heading section-heading--with-control">
            <div>
              <h2 id="paired-heading">{t('results.paired')}</h2>
              <p>{t('results.pairedHelp')}</p>
            </div>
            <Select
              id="paired-metric-selector"
              hideLabel
              labelText={language === 'zh-CN' ? '选择配对指标' : 'Select paired metric'}
              value={analysisMetricId}
              onChange={(event) => setAnalysisMetricId(event.target.value)}
            >
              {results.metrics.filter((metric) => results.pairedSeries[metric.id]).map((metric) => (
                <SelectItem key={metric.id} value={metric.id} text={resultMetricLabel(metric, language, t)} />
              ))}
            </Select>
          </div>
          {pairedSeries.length === 0 ? <ChartEmpty /> : (
            <div className="chart-canvas" role="img" aria-label={`${t('results.paired')}: ${selectedMetric ? resultMetricLabel(selectedMetric, language, t) : analysisMetricId}`}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={pairedSeries} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                  <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                  <XAxis dataKey="seed" name={t('chart.seed')} tick={{ fill: 'var(--text-secondary)', fontSize: 12 }} />
                  <YAxis tick={{ fill: 'var(--text-secondary)', fontSize: 12 }} width={52} />
                  <Tooltip contentStyle={{ background: 'var(--surface-raised)', borderColor: 'var(--border-strong)', color: 'var(--text-primary)' }} />
                  <Legend />
                  <Line type="monotone" dataKey="baseline" name={t('chart.baseline')} stroke="var(--chart-baseline)" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
                  <Line type="monotone" dataKey="intervention" name={t('chart.intervention')} stroke="var(--accent)" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>

        <section className="chart-panel" aria-labelledby="distribution-heading">
          <div className="section-heading"><h2 id="distribution-heading">{t('results.distribution')}</h2><p>{selectedMetric ? resultMetricLabel(selectedMetric, language, t) : analysisMetricId}</p></div>
          {distribution.length === 0 ? <ChartEmpty /> : (
            <div className="chart-canvas" role="img" aria-label={t('results.distribution')}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={distribution} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                  <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                  <XAxis dataKey="bin" tick={{ fill: 'var(--text-secondary)', fontSize: 12 }} />
                  <YAxis tick={{ fill: 'var(--text-secondary)', fontSize: 12 }} width={52} />
                  <Tooltip contentStyle={{ background: 'var(--surface-raised)', borderColor: 'var(--border-strong)', color: 'var(--text-primary)' }} />
                  <Legend />
                  <Bar dataKey="baseline" name={t('chart.baseline')} fill="var(--chart-baseline)" radius={[2, 2, 0, 0]} isAnimationActive={false} />
                  <Bar dataKey="intervention" name={t('chart.intervention')} fill="var(--accent)" radius={[2, 2, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>
      </div>

      <section className="result-section path-section" aria-labelledby="paths-heading">
        <div className="section-heading section-heading--with-control">
          <h2 id="paths-heading">{t('results.paths')}</h2>
          <div className="segmented-control" role="tablist" aria-label={t('results.paths')}>
            {(['price', 'spread', 'depth'] as const).map((metric) => (
              <button
                key={metric}
                type="button"
                role="tab"
                aria-selected={pathMetric === metric}
                className={pathMetric === metric ? 'is-active' : ''}
                onClick={() => setPathMetric(metric)}
              >
                {t(`results.${metric}` as 'results.price' | 'results.spread' | 'results.depth')}
              </button>
            ))}
          </div>
        </div>
        {results.marketPaths.length === 0 ? <ChartEmpty /> : (
          <div className="chart-canvas chart-canvas--wide" role="img" aria-label={`${t('results.paths')}: ${selectedFields.label}`}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={results.marketPaths} margin={{ top: 8, right: 20, left: 0, bottom: 8 }}>
                <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                <XAxis dataKey="step" name={t('chart.step')} tick={{ fill: 'var(--text-secondary)', fontSize: 12 }} />
                <YAxis tick={{ fill: 'var(--text-secondary)', fontSize: 12 }} width={62} />
                <Tooltip contentStyle={{ background: 'var(--surface-raised)', borderColor: 'var(--border-strong)', color: 'var(--text-primary)' }} />
                <Legend />
                <Line type="monotone" dataKey={selectedFields.baseline} name={`${t('chart.baseline')} ${selectedFields.label}`} stroke="var(--chart-baseline)" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line type="monotone" dataKey={selectedFields.intervention} name={`${t('chart.intervention')} ${selectedFields.label}`} stroke="var(--accent)" strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>

      <div className="chart-grid chart-grid--bottom">
        <section className="chart-panel" aria-labelledby="agent-flow-heading">
          <div className="section-heading"><h2 id="agent-flow-heading">{t('results.agentFlow')}</h2></div>
          {results.agentFlows.length === 0 ? <ChartEmpty /> : (
            <div className="chart-canvas" role="img" aria-label={t('results.agentFlow')}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={results.agentFlows} layout="vertical" margin={{ top: 8, right: 16, left: 18, bottom: 8 }}>
                  <CartesianGrid stroke="var(--chart-grid)" horizontal={false} />
                  <XAxis type="number" tick={{ fill: 'var(--text-secondary)', fontSize: 12 }} />
                  <YAxis type="category" dataKey="agentType" tickFormatter={(value: string) => translateAgentType(value, t)} tick={{ fill: 'var(--text-secondary)', fontSize: 12 }} width={110} />
                  <Tooltip contentStyle={{ background: 'var(--surface-raised)', borderColor: 'var(--border-strong)', color: 'var(--text-primary)' }} />
                  <ReferenceLine x={0} stroke="var(--border-strong)" />
                  <Bar dataKey="delta" name={t('chart.delta')} fill="var(--accent)" radius={[0, 2, 2, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>

        <section className="scenario-result-diff" aria-labelledby="result-diff-heading">
          <div className="section-heading"><h2 id="result-diff-heading">{t('results.scenarioDiff')}</h2></div>
          <dl className="definition-list">
            <div><dt>{t('scenario.eventPack')}</dt><dd><code>{activeExperiment.eventPackId}</code></dd></div>
            <div><dt>{t('scenario.interventionLabel')}</dt><dd>{activeExperiment.intervention?.parameter || results.scenarioDiff?.parameter ? translateParameter(activeExperiment.intervention?.parameter ?? results.scenarioDiff?.parameter ?? '', t) : t('common.unavailable')}</dd></div>
            <div><dt>{t('common.baseline')}</dt><dd>{activeExperiment.intervention?.baselineValue ?? results.scenarioDiff?.baselineValue ?? t('common.unavailable')}</dd></div>
            <div><dt>{t('common.intervention')}</dt><dd>{activeExperiment.intervention?.interventionValue ?? results.scenarioDiff?.interventionValue ?? t('common.unavailable')}</dd></div>
            <div><dt>{t('runs.validSeeds')}</dt><dd>{results.validSeedCount ?? t('common.unavailable')}</dd></div>
            <div><dt>{language === 'zh-CN' ? '停止模式' : 'Stopping mode'}</dt><dd>{results.stoppingRule?.mode?.replaceAll('_', ' ') ?? t('common.unavailable')}</dd></div>
            <div><dt>{language === 'zh-CN' ? '停止原因' : 'Stopping reason'}</dt><dd>{results.stoppingRule?.reason.replaceAll('_', ' ') ?? t('common.unavailable')}</dd></div>
            <div><dt>{language === 'zh-CN' ? '完成配对' : 'Completed pairs'}</dt><dd>{results.stoppingRule?.completedPairs ?? results.validSeedCount ?? t('common.unavailable')}</dd></div>
            <div><dt>{language === 'zh-CN' ? '观察区间半宽' : 'Observed interval half-width'}</dt><dd>{formatMetricValue(results.stoppingRule?.observedCiHalfWidth, primaryMetricUnit, language)}</dd></div>
            <div><dt>{language === 'zh-CN' ? '目标区间半宽' : 'Target interval half-width'}</dt><dd>{formatMetricValue(results.stoppingRule?.targetCiHalfWidth, primaryMetricUnit, language)}</dd></div>
          </dl>
          <Button kind="tertiary" renderIcon={ArrowRight} onClick={() => navigate('trace')}>{t('nav.trace')}</Button>
        </section>
      </div>

      <section className="result-section agent-pnl-section" aria-labelledby="agent-pnl-heading">
        <div className="section-heading">
          <h2 id="agent-pnl-heading">{language === 'zh-CN' ? '按智能体类型汇总的组合损益' : 'Portfolio P&L by agent type'}</h2>
          <p>{language === 'zh-CN' ? '每一行先在单次运行内按类型汇总，再跨 matched seeds 取中位数；智能体不是独立样本。' : 'Each row aggregates within a run before taking the median across matched seeds. Agents are not treated as independent samples.'}</p>
        </div>
        {results.agentPnl.length > 0 ? (
          <div className="result-table-wrap">
            <table className="result-table">
              <thead><tr><th>{language === 'zh-CN' ? '智能体类型' : 'Agent type'}</th><th>{t('common.baseline')}</th><th>{t('common.intervention')}</th><th>{t('common.delta')}</th><th>{language === 'zh-CN' ? '有效配对' : 'Valid pairs'}</th><th>{language === 'zh-CN' ? '方向一致率' : 'Direction consistency'}</th></tr></thead>
              <tbody>{results.agentPnl.map((row) => <tr key={row.agentType}><td>{translateAgentType(row.agentType, t)}</td><td>{formatCents(row.baselineEquityChangeCents, language)}</td><td>{formatCents(row.interventionEquityChangeCents, language)}</td><td>{formatCents(row.deltaEquityChangeCents, language)}</td><td>{row.validN ?? t('common.unavailable')}</td><td>{formatMetricValue(row.directionConsistencyRate, 'ratio', language)}</td></tr>)}</tbody>
            </table>
          </div>
        ) : <p className="empty-inline">{language === 'zh-CN' ? '本次结果没有按类型汇总的账本损益。' : 'This result does not contain ledger P&L aggregated by agent type.'}</p>}
      </section>

      <div className="result-evidence-grid">
        <section className="result-section cognition-summary" aria-labelledby="cognition-heading">
          <div className="section-heading">
            <h2 id="cognition-heading"><Brain size={21} weight="duotone" />{language === 'zh-CN' ? '认知层运行证据' : 'Cognition-layer run evidence'}</h2>
            <p>{language === 'zh-CN' ? 'LLM 输出是信念与行动偏好，不是订单、价格或投资建议。' : 'LLM output is a belief and action preference, not an order, price, or investment recommendation.'}</p>
          </div>
          {results.cognition ? (
            <>
              <dl className="definition-list definition-list--compact">
                <div><dt>{language === 'zh-CN' ? '请求模式' : 'Requested mode'}</dt><dd>{translateStatus(results.cognition.requestedMode, t)}</dd></div>
                <div><dt>{language === 'zh-CN' ? '实际模式' : 'Resolved mode'}</dt><dd><StatusBadge status={results.cognition.resolvedMode} /></dd></div>
                <div><dt>{language === 'zh-CN' ? '供应商与模型' : 'Provider and model'}</dt><dd>{results.cognition.provider && results.cognition.resolvedModel ? `${results.cognition.provider} / ${results.cognition.resolvedModel}` : language === 'zh-CN' ? '未调用外部模型' : 'No external model used'}</dd></div>
                <div><dt>{language === 'zh-CN' ? '模型调用' : 'Model calls'}</dt><dd>{results.cognition.calls}</dd></div>
                <div><dt>{language === 'zh-CN' ? '计划 / 尝试调用' : 'Planned / attempted calls'}</dt><dd>{results.cognition.plannedCalls} / {results.cognition.attemptedCalls}</dd></div>
                <div><dt>{language === 'zh-CN' ? 'Token 总数' : 'Total tokens'}</dt><dd>{results.cognition.totalTokens.toLocaleString(language)}</dd></div>
                <div><dt>{language === 'zh-CN' ? '输入 / 输出 token' : 'Input / output tokens'}</dt><dd>{results.cognition.promptTokens.toLocaleString(language)} / {results.cognition.completionTokens.toLocaleString(language)}</dd></div>
                <div><dt>{language === 'zh-CN' ? '缓存输入 token' : 'Cached input tokens'}</dt><dd>{results.cognition.cachedTokens.toLocaleString(language)}</dd></div>
                {results.cognition.costBudget ? <div><dt>{language === 'zh-CN' ? '费用上界 / 硬上限' : 'Cost upper bound / hard cap'}</dt><dd>${results.cognition.costBudget.chargedUsdUpperBound.toFixed(6)} / ${results.cognition.costBudget.capUsd.toFixed(2)} USD</dd></div> : null}
                {results.cognition.costBudget ? <div><dt>{language === 'zh-CN' ? '剩余硬预算' : 'Remaining hard budget'}</dt><dd>${results.cognition.costBudget.remainingUsd.toFixed(6)} USD</dd></div> : null}
                {results.cognition.costBudget ? <div><dt>{language === 'zh-CN' ? '已结算 / 已阻止调用' : 'Settled / blocked calls'}</dt><dd>{results.cognition.costBudget.settledCalls} / {results.cognition.costBudget.blockedCalls}</dd></div> : null}
                <div><dt>{language === 'zh-CN' ? '回退次数' : 'Fallback count'}</dt><dd>{results.cognition.fallbackCount}</dd></div>
                <div><dt>{language === 'zh-CN' ? '决策调度' : 'Decision schedule'}</dt><dd>{results.cognition.decisionScheduleMode?.replaceAll('_', ' ') ?? t('common.unavailable')}</dd></div>
                <div><dt>{language === 'zh-CN' ? '提示词版本' : 'Prompt version'}</dt><dd><code>{results.cognition.promptVersion ?? t('common.unavailable')}</code></dd></div>
                <div><dt>{language === 'zh-CN' ? '输出契约' : 'Output contract'}</dt><dd><code>{results.cognition.promptSchemaVersion ?? t('common.unavailable')}</code></dd></div>
              </dl>
              {results.cognition.failureCode || results.cognition.fallbackCount > 0 ? (
                <InlineNotification
                  kind="warning"
                  lowContrast
                  hideCloseButton
                  title={results.cognition.resolvedMode === 'HYBRID_LLM_PARTIAL_RULE_FALLBACK'
                    ? language === 'zh-CN' ? '混合模式包含部分规则回退' : 'Hybrid mode includes partial rule fallback'
                    : language === 'zh-CN' ? '混合模式已显式降级' : 'Hybrid mode used an explicit fallback'}
                  subtitle={results.cognition.fallbackReasons.length > 0
                    ? results.cognition.fallbackReasons.join(', ')
                    : results.cognition.failureCode ?? (language === 'zh-CN' ? '未返回具体原因' : 'No specific reason returned')}
                />
              ) : null}
              {results.cognition.costBudget ? (
                <InlineNotification
                  kind={results.cognition.costBudget.unknownUsageCalls > 0 ? 'warning' : 'info'}
                  lowContrast
                  hideCloseButton
                  title={language === 'zh-CN' ? '可审计费用边界' : 'Auditable cost boundary'}
                  subtitle={`${results.cognition.costBudget.semantics} Snapshot: ${results.cognition.costBudget.pricingSnapshotVersion}; ¥${results.cognition.costBudget.cnyPerUsdBudgetFloor.toFixed(2)}/$.`}
                />
              ) : null}
              {results.cognition.decisions.length > 0 ? (
                <div className="cognition-decision-list">
                  {results.cognition.decisions.map((decision, index) => (
                    <details key={decision.requestId ?? `${decision.agentId ?? 'agent'}-${index}`}>
                      <summary>
                        <span><strong>{decision.role ?? decision.agentId ?? `${language === 'zh-CN' ? '代表节点' : 'Representative node'} ${index + 1}`}</strong><small>{decision.direction ?? 'NEUTRAL'} / {decision.actionPreference ?? 'ABSTAIN'}</small></span>
                        <Tag type={decision.fallbackUsed ? 'warm-gray' : 'blue'} size="sm">{decision.fallbackUsed ? language === 'zh-CN' ? '规则回退' : 'Rule fallback' : language === 'zh-CN' ? '结构化决策' : 'Structured decision'}</Tag>
                      </summary>
                      <p>{decision.decisionSummary ?? (language === 'zh-CN' ? '后端未返回可展示的决策摘要。' : 'No reviewable decision summary was returned.')}</p>
                      <dl className="definition-list definition-list--compact">
                        <div><dt>{language === 'zh-CN' ? '置信度' : 'Confidence'}</dt><dd>{formatMetricValue(decision.confidence, 'ratio', language)}</dd></div>
                        <div><dt>{language === 'zh-CN' ? '不确定性' : 'Uncertainty'}</dt><dd>{formatMetricValue(decision.uncertainty, 'ratio', language)}</dd></div>
                        <div><dt>{language === 'zh-CN' ? '证据 ID' : 'Evidence IDs'}</dt><dd>{decision.evidenceIds.length > 0 ? decision.evidenceIds.join(', ') : t('common.unavailable')}</dd></div>
                        <div><dt>{language === 'zh-CN' ? '代表节点 / 轮次' : 'Representative / round'}</dt><dd>{decision.representativeIndex ?? t('common.unavailable')} / {decision.decisionRound ?? t('common.unavailable')}</dd></div>
                        <div><dt>{language === 'zh-CN' ? '观察时间' : 'Observation time'}</dt><dd>{decision.observationAt ? new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'medium' }).format(new Date(decision.observationAt)) : t('common.unavailable')}</dd></div>
                        <div><dt>{language === 'zh-CN' ? '生效步 / 间隔' : 'Active step / interval'}</dt><dd>{decision.activeFromStep ?? t('common.unavailable')} / {decision.decisionIntervalSteps ?? t('common.unavailable')}</dd></div>
                        <div><dt>{language === 'zh-CN' ? '证据 / 社交 / 记忆条数' : 'Evidence / social / memory counts'}</dt><dd>{decision.evidenceCount ?? 0} / {decision.socialPostCount ?? 0} / {decision.memoryCount ?? 0}</dd></div>
                        <div><dt>{language === 'zh-CN' ? '修复 / 规则回退' : 'Repair / rule fallback'}</dt><dd>{decision.repairUsed ? language === 'zh-CN' ? '是' : 'Yes' : language === 'zh-CN' ? '否' : 'No'} / {decision.fallbackUsed ? language === 'zh-CN' ? '是' : 'Yes' : language === 'zh-CN' ? '否' : 'No'}</dd></div>
                        <div><dt>{language === 'zh-CN' ? '失败原因' : 'Failure reason'}</dt><dd>{decision.failureReason ?? t('common.unavailable')}</dd></div>
                        <div><dt>{language === 'zh-CN' ? '失败代码' : 'Failure codes'}</dt><dd>{decision.failureCodes.length > 0 ? decision.failureCodes.join(', ') : t('common.unavailable')}</dd></div>
                        <div><dt>{language === 'zh-CN' ? '传输尝试次数' : 'Transport attempts'}</dt><dd>{decision.transportAttempts ?? t('common.unavailable')}</dd></div>
                        <div><dt>{language === 'zh-CN' ? '输入 / 输出 token' : 'Input / output tokens'}</dt><dd>{(decision.promptTokens ?? 0).toLocaleString(language)} / {(decision.completionTokens ?? 0).toLocaleString(language)}</dd></div>
                        <div><dt>{language === 'zh-CN' ? '本次费用上界' : 'Call cost upper bound'}</dt><dd>${(decision.costUpperBoundUsd ?? 0).toFixed(6)} USD</dd></div>
                      </dl>
                    </details>
                  ))}
                </div>
              ) : (
                <Notice>{language === 'zh-CN' ? '本次运行没有外部 LLM 决策记录；规则智能体仍由确定性政策执行。' : 'This run has no external LLM decision records. Rule agents still execute through deterministic policy.'}</Notice>
              )}
            </>
          ) : <p className="empty-inline">{language === 'zh-CN' ? '旧结果未包含认知层清单。不能据此声称调用过 LLM。' : 'This older result has no cognition manifest. It cannot be presented as an LLM-backed run.'}</p>}
        </section>

        <section className="result-section robustness-summary" aria-labelledby="robustness-heading">
          <div className="section-heading">
            <h2 id="robustness-heading">{language === 'zh-CN' ? '敏感性、消融与负对照' : 'Sensitivity, ablation, and negative controls'}</h2>
            <p>{language === 'zh-CN' ? '代码存在不等于研究已执行。这里只显示后端随本次结果返回的证据状态。' : 'Available code does not mean a study was executed. This panel reports only run-linked evidence returned by the backend.'}</p>
          </div>
          <div className="robustness-list">
            {[
              [language === 'zh-CN' ? '参数敏感性' : 'Parameter sensitivity', robustness.sensitivityStatus],
              [language === 'zh-CN' ? '规则与 LLM 消融' : 'Rule and LLM ablation', robustness.ablationStatus],
              [language === 'zh-CN' ? '负对照与安慰剂' : 'Negative control and placebo', robustness.negativeControlStatus],
              [language === 'zh-CN' ? '机制 knockout' : 'Mechanism knockout', robustness.knockoutStatus],
            ].map(([label, status]) => (
              <div key={label}><strong>{label}</strong><Tag type={status === 'PASS' || status === 'PASSED' ? 'green' : 'warm-gray'} size="sm">{translateStatus(status, t)}</Tag></div>
            ))}
          </div>
          {results.robustness || results.analysisDiagnostics ? (
            robustness.notes.length > 0 ? <ul>{robustness.notes.map((note) => <li key={note}>{note}</li>)}</ul> : null
          ) : (
            <InlineNotification
              kind="warning"
              lowContrast
              hideCloseButton
              title={language === 'zh-CN' ? '本次结果未附稳健性研究' : 'No robustness study is attached to this result'}
              subtitle={language === 'zh-CN' ? '这些项目保持 NOT EVALUATED，不能据此宣称结果稳健。' : 'These items remain NOT EVALUATED and cannot support a robustness claim.'}
            />
          )}
        </section>
      </div>

      {results.analysisDiagnostics ? (
        <section className="result-section analysis-diagnostics" aria-labelledby="analysis-diagnostics-heading">
          <div className="section-heading">
            <h2 id="analysis-diagnostics-heading">{language === 'zh-CN' ? '预注册分析诊断' : 'Preregistered analysis diagnostics'}</h2>
            <p>{language === 'zh-CN' ? `主要指标：${results.analysisDiagnostics.preregisteredPrimaryOutcome}。结果族：${results.analysisDiagnostics.outcomeFamily.join(', ') || '暂无数据'}。` : `Primary outcome: ${results.analysisDiagnostics.preregisteredPrimaryOutcome}. Outcome family: ${results.analysisDiagnostics.outcomeFamily.join(', ') || 'not available'}.`}</p>
          </div>
          <Notice>{results.analysisDiagnostics.interpretationBoundary.replaceAll('_', ' ')}</Notice>
          <div className="analysis-control-grid">
            <article>
              <div><h3>{language === 'zh-CN' ? '负对照' : 'Negative control'}</h3><StatusBadge status={results.analysisDiagnostics.negativeControl.status} /></div>
              <dl className="definition-list definition-list--compact">
                <div><dt>{language === 'zh-CN' ? '对照类型' : 'Control type'}</dt><dd>{results.analysisDiagnostics.negativeControl.controlType?.replaceAll('_', ' ') ?? t('common.unavailable')}</dd></div>
                <div><dt>{language === 'zh-CN' ? '容差' : 'Tolerance'}</dt><dd>{formatMetricValue(results.analysisDiagnostics.negativeControl.tolerance, primaryMetricUnit, language)}</dd></div>
                <div><dt>{language === 'zh-CN' ? '通过' : 'Passed'}</dt><dd>{results.analysisDiagnostics.negativeControl.passed === undefined ? t('common.unavailable') : results.analysisDiagnostics.negativeControl.passed ? language === 'zh-CN' ? '是' : 'Yes' : language === 'zh-CN' ? '否' : 'No'}</dd></div>
              </dl>
              <p>{results.analysisDiagnostics.negativeControl.reason ?? results.analysisDiagnostics.negativeControl.interpretation}</p>
            </article>
            <article>
              <div><h3>{language === 'zh-CN' ? '参数恢复 knockout' : 'Parameter-restoration knockout'}</h3><StatusBadge status={results.analysisDiagnostics.parameterRestorationKnockout.status} /></div>
              <dl className="definition-list definition-list--compact">
                <div><dt>{language === 'zh-CN' ? '完整效应' : 'Full effect'}</dt><dd>{formatMetricValue(results.analysisDiagnostics.parameterRestorationKnockout.fullEffect, primaryMetricUnit, language)}</dd></div>
                <div><dt>{language === 'zh-CN' ? '恢复后效应' : 'Restored effect'}</dt><dd>{formatMetricValue(results.analysisDiagnostics.parameterRestorationKnockout.knockoutEffect, primaryMetricUnit, language)}</dd></div>
                <div><dt>{language === 'zh-CN' ? '衰减比例' : 'Attenuation'}</dt><dd>{formatMetricValue(results.analysisDiagnostics.parameterRestorationKnockout.attenuationFraction, 'ratio', language)}</dd></div>
                <div><dt>{language === 'zh-CN' ? '内部机制支持' : 'Internal mechanism supported'}</dt><dd>{results.analysisDiagnostics.parameterRestorationKnockout.mechanismSupported === undefined ? t('common.unavailable') : results.analysisDiagnostics.parameterRestorationKnockout.mechanismSupported ? language === 'zh-CN' ? '是' : 'Yes' : language === 'zh-CN' ? '否' : 'No'}</dd></div>
              </dl>
              <p>{results.analysisDiagnostics.parameterRestorationKnockout.interpretation}</p>
            </article>
            <article>
              <div><h3>{language === 'zh-CN' ? '局部敏感性' : 'Local sensitivity'}</h3><StatusBadge status={results.analysisDiagnostics.localSensitivity.status} /></div>
              <p>{results.analysisDiagnostics.localSensitivity.design?.replaceAll('_', ' ')}</p>
              {results.analysisDiagnostics.localSensitivity.indices.map((item) => <dl key={item.parameter} className="definition-list definition-list--compact"><div><dt>{item.parameter}</dt><dd>ρ {formatMetricValue(item.spearmanCorrelation, undefined, language)} / {language === 'zh-CN' ? '重要性' : 'importance'} {formatMetricValue(item.varianceImportanceProxy, 'ratio', language)} / n={item.sampleSize ?? t('common.unavailable')}</dd></div></dl>)}
            </article>
          </div>
          <div className="section-heading analysis-comparison-heading"><h3>{language === 'zh-CN' ? 'Holm 校正的精确双侧符号检验' : 'Holm-adjusted exact two-sided sign tests'}</h3><p>{results.analysisDiagnostics.multipleComparison.method.replaceAll('_', ' ')} / α={results.analysisDiagnostics.multipleComparison.alpha ?? t('common.unavailable')}</p></div>
          <div className="result-table-wrap">
            <table className="result-table">
              <thead><tr><th>{language === 'zh-CN' ? '结果指标' : 'Outcome'}</th><th>{language === 'zh-CN' ? '原始 p' : 'Raw p'}</th><th>{language === 'zh-CN' ? '校正 p' : 'Adjusted p'}</th><th>{language === 'zh-CN' ? '阈值' : 'Threshold'}</th><th>{language === 'zh-CN' ? '拒绝零假设' : 'Reject null'}</th></tr></thead>
              <tbody>{results.analysisDiagnostics.multipleComparison.items.map((item) => <tr key={item.hypothesisId}><td>{item.hypothesisId}</td><td>{formatMetricValue(item.rawPValue, undefined, language)}</td><td>{formatMetricValue(item.adjustedPValue, undefined, language)}</td><td>{formatMetricValue(item.alphaThreshold, undefined, language)}</td><td><StatusBadge status={item.rejected ? 'REJECTED' : 'NOT REJECTED'} /></td></tr>)}</tbody>
            </table>
          </div>
        </section>
      ) : null}

      <section className="result-section run-limitations" aria-labelledby="result-limitations-heading">
        <div className="section-heading"><h2 id="result-limitations-heading">{t('common.limitations')}</h2></div>
        <div className="limitation-list">
          {(language === 'zh-CN' ? results.limitationsZh : results.limitations).map((limitation) => (
            <div key={limitation}><Warning size={20} weight="fill" aria-hidden="true" /><p>{limitation}</p></div>
          ))}
        </div>
      </section>
    </div>
  );
}
