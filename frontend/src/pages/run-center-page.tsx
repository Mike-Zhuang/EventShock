import { Button, InlineNotification, ProgressBar } from '@carbon/react';
import { ArrowClockwise, ChartLineUp, Stop, TerminalWindow } from '@phosphor-icons/react';
import { useEffect, useState } from 'react';
import type { Navigate } from '../app';
import { EmptyState, ErrorPanel, LoadingPanel, Notice, PageHeader, StatusBadge } from '../components/common';
import { ExperimentHistoryDisclosure, experimentHistoryLabel } from '../components/experiment-history';
import { translateLogLevel, useI18n } from '../i18n';
import { useWorkflow } from '../state/workflow-context';

export function RunCenterPage({ navigate }: { navigate: Navigate }) {
  const { language, t } = useI18n();
  const {
    experiments,
    experimentsState,
    experimentsError,
    activeExperiment,
    refreshExperiments,
    selectExperiment,
    cancelActiveExperiment,
    loadResults,
    resultsError,
  } = useWorkflow();
  const [actionError, setActionError] = useState<string>();
  const [playbackPaused, setPlaybackPaused] = useState(false);
  const [playbackRate, setPlaybackRate] = useState<1 | 2 | 4>(1);
  const [visibleLogCount, setVisibleLogCount] = useState(0);
  const liveState = activeExperiment?.liveState;
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

  const openResults = async () => {
    if (!activeExperiment) return;
    setActionError(undefined);
    try {
      const nextResults = await loadResults(activeExperiment.id);
      if (!nextResults) return;
      navigate('results', activeExperiment.id);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <div className="page page--runs">
      <PageHeader
        title={t('runs.title')}
        subtitle={t('runs.subtitle')}
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
                <div><span>{t('runs.validSeeds')}</span><strong>{activeExperiment.validSeeds ?? 0} / {activeExperiment.totalSeeds ?? t('common.unavailable')}</strong></div>
                <div><span>{t('runs.currentSeed')}</span><strong>{activeExperiment.currentSeed ?? t('common.unavailable')}</strong></div>
                <div><span>{t('scenario.population')}</span><strong>{activeExperiment.scenario?.populationSize ?? t('common.unavailable')}</strong></div>
              </div>

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
                  <span>{language === 'zh-CN' ? '运行阶段' : 'Run phase'}</span>
                  <strong>{liveState?.phase ?? (language === 'zh-CN' ? '等待首个检查点' : 'Waiting for first checkpoint')}</strong>
                </div>
                <div>
                  <span>{language === 'zh-CN' ? '当前价格' : 'Current price'}</span>
                  <strong>{formatValue(activeSnapshot?.price, 4)}</strong>
                </div>
                <div>
                  <span>{language === 'zh-CN' ? '价差 / 深度' : 'Spread / depth'}</span>
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
                        <p>{entry.message}</p>
                        {entry.seed !== undefined ? <code>{t('chart.seed')} {entry.seed}</code> : null}
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
