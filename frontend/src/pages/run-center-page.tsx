import { Button, InlineNotification, ProgressBar } from '@carbon/react';
import { ArrowClockwise, ChartLineUp, Stop, TerminalWindow } from '@phosphor-icons/react';
import { useEffect, useState } from 'react';
import type { CognitionProgress, ExperimentLogEntry } from '../api/types';
import type { Navigate } from '../app';
import { EmptyState, ErrorPanel, ExplainedLabel, LoadingPanel, Notice, PageHeader, StatusBadge } from '../components/common';
import { ExperimentHistoryDisclosure, experimentHistoryLabel } from '../components/experiment-history';
import { TechnicalCodeDisplay, technicalCodeLabel } from '../components/technical-code';
import { translateLogLevel, useI18n } from '../i18n';
import { getPageGuide } from '../page-guidance';
import { getParameterHelp } from '../parameter-help';
import { useWorkflow } from '../state/workflow-context';

const KNOWN_RUNTIME_LOG_CODES = new Set([
  'COGNITION_PREPARATION_STARTED',
  'COGNITION_PREPARATION_COMPLETED',
  'BASELINE_PATH_STARTED',
  'INTERVENTION_PATH_STARTED',
  'MATCHED_PAIR_COMPLETED',
  'RESULT_AGGREGATION_STARTED',
  'EXPERIMENT_COMPLETED',
  'EXPERIMENT_FAILED',
  'EXPERIMENT_CANCELLED',
  'EXPERIMENT_RESUMED_FROM_CHECKPOINT',
]);

export function runtimeLogMessage(entry: ExperimentLogEntry, language: 'en' | 'zh-CN'): string {
  if (!entry.code) return entry.message;
  const isZh = language === 'zh-CN';
  const pairIndex = Number(entry.parameters?.pairIndex);
  const completedPairs = Number(entry.parameters?.completedPairs);
  const labels: Record<string, [string, string]> = {
    COGNITION_PREPARATION_STARTED: ['Preparing deterministic rules or frozen hybrid cognition signals.', '正在准备确定性规则或冻结的混合认知信号。'],
    COGNITION_PREPARATION_COMPLETED: ['Cognition preparation completed.', '认知信号准备已完成。'],
    BASELINE_PATH_STARTED: [`Baseline path started for matched pair ${pairIndex}.`, `第 ${pairIndex} 组配对的基准路径已开始。`],
    INTERVENTION_PATH_STARTED: [`Intervention path started for matched pair ${pairIndex}.`, `第 ${pairIndex} 组配对的干预路径已开始。`],
    MATCHED_PAIR_COMPLETED: [`Matched pair ${pairIndex} completed and checkpointed.`, `第 ${pairIndex} 组配对已完成并写入检查点。`],
    RESULT_AGGREGATION_STARTED: ['Aggregating paired distributions, uncertainty, traces, and diagnostics.', '正在汇总配对分布、不确定性、链路与诊断。'],
    EXPERIMENT_COMPLETED: [`Experiment completed with ${completedPairs} valid matched pairs.`, `实验已完成，共有 ${completedPairs} 组有效配对。`],
    EXPERIMENT_FAILED: ['The experiment stopped after a runtime invariant failed.', '实验因运行时约束检查失败而停止。'],
    EXPERIMENT_CANCELLED: ['The cancellation request was applied.', '取消请求已生效。'],
    EXPERIMENT_RESUMED_FROM_CHECKPOINT: [`Resumed after ${completedPairs} completed matched pairs.`, `已从 ${completedPairs} 组已完成配对后的检查点恢复。`],
  };
  return labels[entry.code]?.[isZh ? 1 : 0]
    ?? (isZh ? '未收录的运行事件' : 'Unknown run event');
}

export function cognitionStatusLabel(progress: CognitionProgress, language: 'en' | 'zh-CN'): string {
  const labels: Record<string, [string, string]> = {
    NOT_APPLICABLE: ['No external model calls are required', '当前模式不需要外部模型调用'],
    INITIALIZING_PILOT: ['Initializing the deterministic pilot', '正在初始化确定性 pilot'],
    PILOT_READY: ['Pilot ready; model calls are next', 'Pilot 已就绪，即将调用模型'],
    MODEL_CALL_IN_PROGRESS: ['Waiting for the current model response', '正在等待当前模型响应'],
    MODEL_REQUESTING: ['Sending the current model request', '正在发送当前模型请求'],
    MODEL_STREAM_RECEIVING: ['Receiving the model response stream', '正在接收模型响应流'],
    MODEL_VALIDATING: ['Validating the structured model response', '正在校验结构化模型响应'],
    MODEL_REPAIRING: ['Repairing an invalid structured response', '正在修复无效结构化响应'],
    MODEL_CALL_COMPLETED: ['Model response validated', '模型响应已验证'],
    MODEL_CALL_FAILED: ['The current model call failed safely', '当前模型调用已安全失败'],
    CIRCUIT_BREAKER_OPEN: ['Repeated-failure circuit breaker opened', '重复失败断路器已打开'],
    RULE_CONTINUATION_REQUESTED: ['Stopping future model calls', '正在停止后续模型调用'],
    FAILED_CLOSED: ['Cognition preparation failed closed', '认知准备已安全关闭'],
    COMPLETED_WITH_RULE_CONTINUATION: ['Continued with deterministic rules', '已改用确定性规则继续'],
    COMPLETED: ['Cognition preparation completed', '认知准备已完成'],
  };
  return labels[progress.status ?? '']?.[language === 'zh-CN' ? 1 : 0]
    ?? progress.status
    ?? (language === 'zh-CN' ? '正在准备' : 'Preparing');
}

export function RunCenterPage({ navigate }: { navigate: Navigate }) {
  const { language, t } = useI18n();
  const explained = (key: string, label: string, fallback?: string) => (
    <ExplainedLabel label={label} explanation={getParameterHelp(key, language) ?? fallback ?? label} />
  );
  const {
    experiments,
    experimentsState,
    experimentsError,
    activeExperiment,
    refreshExperiments,
    selectExperiment,
    cancelActiveExperiment,
    continueActiveCognitionWithRules,
    loadResults,
    resultsError,
  } = useWorkflow();
  const [actionError, setActionError] = useState<string>();
  const [playbackPaused, setPlaybackPaused] = useState(false);
  const [playbackRate, setPlaybackRate] = useState<1 | 2 | 4>(1);
  const [visibleLogCount, setVisibleLogCount] = useState(0);
  const liveState = activeExperiment?.liveState;
  const cognitionProgress = liveState?.cognitionProgress;
  const activeSnapshot = liveState?.phase === 'INTERVENTION'
    ? liveState.intervention
    : liveState?.baseline ?? liveState?.intervention;
  const formatValue = (value: number | undefined, maximumFractionDigits = 2) => value === undefined
    ? t('common.unavailable')
    : new Intl.NumberFormat(language, { maximumFractionDigits }).format(value);

  useEffect(() => {
    setVisibleLogCount(activeExperiment?.logs.length ?? 0);
    setPlaybackPaused(false);
  }, [activeExperiment?.id]);

  useEffect(() => {
    if (playbackPaused || !activeExperiment || visibleLogCount >= activeExperiment.logs.length) return;
    const timer = window.setTimeout(() => {
      setVisibleLogCount((current) => Math.min(activeExperiment.logs.length, current + playbackRate));
    }, 600);
    return () => window.clearTimeout(timer);
  }, [activeExperiment, playbackPaused, playbackRate, visibleLogCount]);

  const select = async (experimentId: string) => {
    setActionError(undefined);
    try {
      await selectExperiment(experimentId);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    }
  };

  const cancel = async () => {
    setActionError(undefined);
    try {
      await cancelActiveExperiment();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    }
  };

  const continueWithRules = async () => {
    const confirmed = window.confirm(language === 'zh-CN'
      ? '当前正在执行的模型请求可能仍会完成并计费。确认后，系统会保留已经校验的冻结认知决策，停止后续模型调用，并使用确定性规则完成剩余流程。是否继续？'
      : 'The model request already in flight may still complete and be billed. The system will preserve validated frozen cognition, stop future model calls, and finish the remaining workflow with deterministic rules. Continue?');
    if (!confirmed) return;
    setActionError(undefined);
    try {
      await continueActiveCognitionWithRules();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    }
  };

  const openResults = async () => {
    if (!activeExperiment) return;
    setActionError(undefined);
    try {
      const nextResults = await loadResults(activeExperiment.id);
      if (!nextResults) return;
      navigate('results', { experimentId: activeExperiment.id });
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <div className="page page--runs">
      <PageHeader
        title={t('runs.title')}
        subtitle={t('runs.subtitle')}
        guide={getPageGuide('runs', language)}
        actions={(
          <Button kind="ghost" renderIcon={ArrowClockwise} onClick={() => void refreshExperiments()}>
            {t('runs.refresh')}
          </Button>
        )}
      />
      <ExperimentHistoryDisclosure />

      {actionError || experimentsError || resultsError ? (
        <InlineNotification kind="error" lowContrast hideCloseButton title={t('common.errorTitle')} subtitle={t('common.errorFallback')} />
      ) : null}

      {experimentsState === 'loading' && experiments.length === 0 ? <LoadingPanel /> : null}
      {experimentsState === 'error' && experiments.length === 0 ? <ErrorPanel detail={experimentsError} onRetry={() => void refreshExperiments()} /> : null}
      {experimentsState === 'success' && experiments.length === 0 ? (
        <EmptyState
          title={t('runs.emptyTitle')}
          body={t('runs.emptyBody')}
          action={<Button kind="tertiary" onClick={() => navigate('scenario')}>{t('nav.scenario')}</Button>}
        />
      ) : null}

      {experiments.length > 0 ? (
        <div className="run-layout">
          <section className="run-list" aria-label={t('export.history')}>
            {experiments.map((experiment) => (
              <button
                key={experiment.id}
                type="button"
                className={`run-row ${activeExperiment?.id === experiment.id ? 'run-row--selected' : ''}`}
                onClick={() => void select(experiment.id)}
              >
                <div>
                  <span>
                    <code>{experiment.id}</code><br />
                    <small>{experimentHistoryLabel(experiment, language, false, false)}</small>
                  </span>
                  <StatusBadge status={experiment.status} />
                </div>
                <span>{experiment.createdAt ? new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(experiment.createdAt)) : t('common.unavailable')}</span>
                <strong>{Math.round(experiment.progress)}%</strong>
              </button>
            ))}
          </section>

          {activeExperiment ? (
            <section className="run-detail">
              <div className="run-detail__header">
                <div>
                  <span>{t('runs.progress')}</span>
                  <h2><code>{activeExperiment.id}</code></h2>
                </div>
                <StatusBadge status={activeExperiment.status} />
              </div>

              <ProgressBar
                label={t('runs.progress')}
                helperText={activeExperiment.message}
                value={activeExperiment.progress}
                max={100}
                status={['FAILED', 'FAILED_FINAL', 'FAILED_RETRYABLE', 'INVALIDATED'].includes(activeExperiment.status) ? 'error' : activeExperiment.status === 'COMPLETED' ? 'finished' : 'active'}
              />

              <div className="run-stats">
                <div><span>{explained('matchedSeeds', t('runs.validSeeds'))}</span><strong>{activeExperiment.validSeeds ?? 0} / {activeExperiment.totalSeeds ?? t('common.unavailable')}</strong></div>
                <div>
                  <span>{explained(
                    'rootSeed',
                    activeExperiment.currentSeed !== undefined
                      ? t('runs.currentSeed')
                      : language === 'zh-CN' ? '最后完成种子' : 'Last completed seed',
                    language === 'zh-CN'
                      ? '运行中显示当前配对随机种子；完成后保留最后一组已完成种子。'
                      : 'Shows the current matched seed while running and retains the last completed seed afterward.',
                  )}</span>
                  <strong>{activeExperiment.currentSeed ?? activeExperiment.lastCompletedSeed ?? t('common.unavailable')}</strong>
                </div>
                <div><span>{explained('populationSize', t('scenario.population'))}</span><strong>{activeExperiment.scenario?.populationSize ?? t('common.unavailable')}</strong></div>
              </div>

              {cognitionProgress ? (
                <section className="cognition-runtime-progress" aria-live="polite" aria-labelledby="cognition-runtime-heading">
                  <div>
                    <h3 id="cognition-runtime-heading">{language === 'zh-CN' ? '认知准备进度' : 'Cognition preparation'}</h3>
                    <p>{cognitionStatusLabel(cognitionProgress, language)}</p>
                  </div>
                  <ProgressBar
                    label={language === 'zh-CN' ? '已验证模型调用' : 'Validated model calls'}
                    helperText={cognitionProgress.failureCode
                      ? technicalCodeLabel(cognitionProgress.failureCode, language)
                      : undefined}
                    value={cognitionProgress.completedCalls ?? 0}
                    max={Math.max(cognitionProgress.plannedCalls ?? 0, 1)}
                    status={cognitionProgress.status === 'COMPLETED' ? 'finished' : cognitionProgress.status === 'FAILED_CLOSED' ? 'error' : 'active'}
                  />
                  {cognitionProgress.failureCode ? (
                    <TechnicalCodeDisplay codes={[cognitionProgress.failureCode]} language={language} />
                  ) : null}
                  <dl>
                    <div><dt>{language === 'zh-CN' ? '计划调用' : 'Planned'}</dt><dd>{cognitionProgress.plannedCalls ?? 0}</dd></div>
                    <div><dt>{language === 'zh-CN' ? '已尝试' : 'Attempted'}</dt><dd>{cognitionProgress.attemptedCalls ?? 0}</dd></div>
                    <div><dt>{language === 'zh-CN' ? '已验证' : 'Validated'}</dt><dd>{cognitionProgress.completedCalls ?? 0}</dd></div>
                    <div><dt>{language === 'zh-CN' ? '规则回退' : 'Rule fallbacks'}</dt><dd>{cognitionProgress.fallbackCount ?? 0}</dd></div>
                    <div><dt>Tokens</dt><dd>{cognitionProgress.totalTokens ?? 0}</dd></div>
                    <div>
                      <dt>{language === 'zh-CN' ? '当前费用上界' : 'Current cost upper bound'}</dt>
                      <dd>{new Intl.NumberFormat(language, {
                        style: 'currency',
                        currency: 'USD',
                        minimumFractionDigits: 4,
                        maximumFractionDigits: 6,
                      }).format(cognitionProgress.currentCostUsd ?? 0)}</dd>
                    </div>
                    <div>
                      <dt>{language === 'zh-CN' ? '结构化成功率' : 'Structured success rate'}</dt>
                      <dd>{new Intl.NumberFormat(language, {
                        style: 'percent',
                        maximumFractionDigits: 1,
                      }).format(cognitionProgress.structuredSuccessRate ?? 0)}
                        {' / '}
                        {new Intl.NumberFormat(language, {
                          style: 'percent',
                          maximumFractionDigits: 0,
                        }).format(cognitionProgress.structuredSuccessThreshold ?? 0.95)}
                      </dd>
                    </div>
                    <div>
                      <dt>{language === 'zh-CN' ? '流片段' : 'Stream chunks'}</dt>
                      <dd>{cognitionProgress.streamChunkCount ?? 0}</dd>
                    </div>
                    <div>
                      <dt>{language === 'zh-CN' ? '修复阶段' : 'Repair stage'}</dt>
                      <dd>{cognitionProgress.repairAttempted
                        ? language === 'zh-CN' ? '已进入修复' : 'Repair attempted'
                        : language === 'zh-CN' ? '未进入修复' : 'Not entered'}</dd>
                    </div>
                  </dl>
                  {Object.keys(cognitionProgress.failureCategoryCounts ?? {}).length > 0 ? (
                    <details>
                      <summary>{language === 'zh-CN' ? '失败分类汇总' : 'Failure category summary'}</summary>
                      <ul>
                        {Object.entries(cognitionProgress.failureCategoryCounts ?? {}).map(
                          ([category, count]) => (
                            <li key={category}>
                              <TechnicalCodeDisplay codes={[category]} language={language} />
                              <span>{language === 'zh-CN' ? '次数' : 'Count'}: {count}</span>
                            </li>
                          ),
                        )}
                      </ul>
                    </details>
                  ) : null}
                  {cognitionProgress.userRequestedRuleContinuation
                    || activeExperiment.cognitionFallbackRequested ? (
                      <InlineNotification
                        kind="warning"
                        lowContrast
                        hideCloseButton
                        title={language === 'zh-CN'
                          ? '已请求停止后续模型调用'
                          : 'Future model calls will stop'}
                        subtitle={language === 'zh-CN'
                          ? '当前在途请求可能仍会完成并计费；已校验的冻结决策会保留，剩余认知由确定性规则完成。'
                          : 'The in-flight request may still complete and be billed. Validated frozen decisions are preserved; deterministic rules complete the remainder.'}
                      />
                    ) : liveState?.phase === 'COGNITION'
                      && activeExperiment.scenario?.llmPolicy?.mode === 'HYBRID_LLM'
                      && activeExperiment.scenario?.llmPolicy?.fallbackToRules ? (
                        <Button
                          kind="tertiary"
                          size="sm"
                          onClick={() => void continueWithRules()}
                        >
                          {language === 'zh-CN'
                            ? '停止后续 LLM 调用并按规则完成'
                            : 'Stop future LLM calls and finish with rules'}
                        </Button>
                      ) : null}
                  {liveState?.phase === 'COGNITION'
                    && activeExperiment.scenario?.llmPolicy?.mode === 'HYBRID_LLM'
                    && !activeExperiment.scenario?.llmPolicy?.fallbackToRules
                    && ['FAILED_CLOSED', 'FAILED'].includes(cognitionProgress.status ?? '') ? (
                      <InlineNotification
                        kind="error"
                        lowContrast
                        hideCloseButton
                        title={language === 'zh-CN'
                          ? '严格 LLM 模式已停止认知准备'
                          : 'Strict LLM cognition stopped'}
                        subtitle={language === 'zh-CN'
                          ? '无效模型结果没有进入实验，也不会自动改用规则。请取消本实验并在检查配置后新建实验；若确实接受规则回退，请在启动前明确开启弹性混合模式。'
                          : 'Invalid model output was not accepted and rules were not substituted. Cancel this experiment and create a new run after reviewing the configuration; enable elastic hybrid mode before launch only if rule fallback is acceptable.'}
                      />
                    ) : null}
                </section>
              ) : null}

              <Notice><strong>{t('runs.singlePath')}.</strong> {t('runs.singlePathHelp')}</Notice>
              {activeExperiment.status === 'INVALIDATED' ? (
                <InlineNotification
                  kind="error"
                  lowContrast
                  hideCloseButton
                  title={language === 'zh-CN' ? '实验结果已作废，禁止研究使用与导出' : 'Experiment result invalidated; research use and export are blocked'}
                  subtitle={`${activeExperiment.invalidationReasonCode ?? 'OTHER'} — ${activeExperiment.invalidationReason ?? t('common.unavailable')}`}
                />
              ) : null}
              {liveState?.resumedFromCheckpoint ? (
                <InlineNotification
                  kind="info"
                  lowContrast
                  hideCloseButton
                  title={language === 'zh-CN' ? '已从断点恢复' : 'Resumed from checkpoint'}
                  subtitle={language === 'zh-CN'
                    ? `已复用 ${liveState.checkpointPairs ?? 0} 组完整 matched pairs 和冻结认知信号。`
                    : `${liveState.checkpointPairs ?? 0} completed matched pairs and frozen cognition signals were reused.`}
                />
              ) : null}

              <section className="live-monitor-controls" aria-labelledby="live-playback-heading">
                <div>
                  <h3 id="live-playback-heading">{language === 'zh-CN' ? '前端事件播放' : 'Frontend event playback'}</h3>
                  <p>{language === 'zh-CN' ? '暂停只冻结日志播放，不会暂停或修改后端实验。' : 'Pause freezes log playback only. It never pauses or changes the backend experiment.'}</p>
                </div>
                <div className="segmented-control" role="group" aria-label={language === 'zh-CN' ? '播放控制' : 'Playback controls'}>
                  <button type="button" className={playbackPaused ? 'is-active' : ''} onClick={() => setPlaybackPaused((current) => !current)}>{playbackPaused ? language === 'zh-CN' ? '继续' : 'Resume' : language === 'zh-CN' ? '暂停' : 'Pause'}</button>
                  {([1, 2, 4] as const).map((rate) => <button type="button" key={rate} className={playbackRate === rate ? 'is-active' : ''} onClick={() => setPlaybackRate(rate)}>{rate}x</button>)}
                  <button type="button" onClick={() => setVisibleLogCount(activeExperiment.logs.length)}>{language === 'zh-CN' ? '跳到最新' : 'Jump to latest'}</button>
                </div>
              </section>

              <div className="live-market-status">
                <div>
                  <span>{explained('runPhase', language === 'zh-CN' ? '运行阶段' : 'Run phase', language === 'zh-CN' ? '当前后端计算阶段，例如认知信号生成、基准路径、干预路径或聚合。' : 'Current backend phase, such as cognition generation, baseline, intervention, or aggregation.')}</span>
                  <strong>{liveState?.phase ?? (language === 'zh-CN' ? '等待首个检查点' : 'Waiting for first checkpoint')}</strong>
                </div>
                <div>
                  <span>{language === 'zh-CN' ? '当前价格' : 'Current price'}</span>
                  <strong>{formatValue(activeSnapshot?.price, 4)}</strong>
                </div>
                <div>
                  <span>{explained('maxSpreadBps', language === 'zh-CN' ? '价差 / 深度' : 'Spread / depth', language === 'zh-CN' ? '价差以基点表示买卖报价距离；深度表示当前订单簿可成交数量。' : 'Spread is the bid–ask distance in basis points; depth is currently available order-book quantity.')}</span>
                  <strong>{activeSnapshot
                    ? `${formatValue(activeSnapshot.spreadBps)} bps / ${formatValue(activeSnapshot.depth, 0)}`
                    : t('common.unavailable')}</strong>
                </div>
                <div>
                  <span>{language === 'zh-CN' ? '市场状态 / 成交量' : 'Market state / volume'}</span>
                  <strong>{activeSnapshot
                    ? `${activeSnapshot.marketState ?? t('common.unavailable')} / ${formatValue(activeSnapshot.volume, 0)}`
                    : t('common.unavailable')}</strong>
                </div>
              </div>

              {liveState?.baseline || liveState?.intervention ? (
                <div className="live-scenario-comparison" aria-label={language === 'zh-CN' ? '实时场景对比' : 'Live scenario comparison'}>
                  {([
                    ['baseline', liveState.baseline],
                    ['intervention', liveState.intervention],
                  ] as const).map(([scenarioName, snapshot]) => (
                    <article key={scenarioName}>
                      <span>{scenarioName === 'baseline'
                        ? language === 'zh-CN' ? '基准' : 'Baseline'
                        : language === 'zh-CN' ? '干预' : 'Intervention'}</span>
                      {snapshot ? (
                        <dl>
                          <div><dt>{language === 'zh-CN' ? '步数' : 'Step'}</dt><dd>{snapshot.completedSteps} / {snapshot.totalSteps}</dd></div>
                          <div><dt>{language === 'zh-CN' ? '价格' : 'Price'}</dt><dd>{formatValue(snapshot.price, 4)}</dd></div>
                          <div><dt>{language === 'zh-CN' ? '情绪' : 'Sentiment'}</dt><dd>{formatValue(snapshot.sentiment, 4)}</dd></div>
                          <div><dt>{language === 'zh-CN' ? '停牌次数' : 'Halts'}</dt><dd>{formatValue(snapshot.haltCount, 0)}</dd></div>
                        </dl>
                      ) : <p>{language === 'zh-CN' ? '等待该路径开始运行。' : 'Waiting for this path to start.'}</p>}
                    </article>
                  ))}
                </div>
              ) : null}

              <div className="run-log">
                <div className="section-heading section-heading--inline">
                  <h2><TerminalWindow size={20} />{t('runs.logs')}</h2>
                </div>
                {activeExperiment.logs.length === 0 ? <p className="empty-inline">{t('runs.noLogs')}</p> : (
                  <ol>
                    {activeExperiment.logs.slice(0, visibleLogCount).map((entry, index) => (
                      <li key={`${entry.timestamp}-${index}`}>
                        <time>{entry.timestamp ? new Intl.DateTimeFormat(language, { timeStyle: 'medium' }).format(new Date(entry.timestamp)) : ''}</time>
                        <span className={`log-level log-level--${entry.level.toLowerCase()}`}>{translateLogLevel(entry.level, t)}</span>
                        <p>{runtimeLogMessage(entry, language)}</p>
                        {entry.seed !== undefined ? <code>{t('chart.seed')} {entry.seed}</code> : null}
                        {entry.code ? (
                          <details>
                            <summary>{language === 'zh-CN' ? '技术详情' : 'Technical details'}</summary>
                            <dl>
                              <div><dt>code</dt><dd><code>{entry.code}</code></dd></div>
                              {!KNOWN_RUNTIME_LOG_CODES.has(entry.code) ? (
                                <div><dt>message</dt><dd>{entry.message}</dd></div>
                              ) : null}
                              {entry.parameters ? (
                                <div>
                                  <dt>parameters</dt>
                                  <dd><code>{JSON.stringify(entry.parameters)}</code></dd>
                                </div>
                              ) : null}
                            </dl>
                          </details>
                        ) : null}
                      </li>
                    ))}
                  </ol>
                )}
              </div>

              <div className="run-detail__actions">
                {['QUEUED', 'RUNNING', 'AGGREGATING'].includes(activeExperiment.status) ? (
                  <Button kind="danger--tertiary" renderIcon={Stop} onClick={() => void cancel()}>{t('runs.cancel')}</Button>
                ) : null}
                {activeExperiment.status === 'COMPLETED' ? (
                  <Button renderIcon={ChartLineUp} onClick={() => void openResults()}>{t('runs.openResults')}</Button>
                ) : null}
              </div>
            </section>
          ) : (
            <EmptyState title={t('common.select')} body={t('results.selectBody')} />
          )}
        </div>
      ) : null}
    </div>
  );
}
