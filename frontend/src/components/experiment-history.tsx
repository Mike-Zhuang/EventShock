import { InlineNotification } from '@carbon/react';
import type { Experiment } from '../api/types';
import { useI18n } from '../i18n';

export const EXPERIMENT_HISTORY_RETENTION_DAYS = 90;
export const MAX_EXPERIMENTS_PER_ANONYMOUS_SESSION = 30;
export const MAX_STORED_EXPERIMENTS_SITE_WIDE = 500;

function localizedQuestion(experiment: Experiment, language: 'en' | 'zh-CN'): string {
  const scenario = experiment.scenario;
  if (language === 'zh-CN') {
    return scenario?.questionZh || scenario?.question || experiment.eventPackId;
  }
  return scenario?.question || scenario?.questionZh || experiment.eventPackId;
}

export function experimentHistoryLabel(
  experiment: Experiment,
  language: 'en' | 'zh-CN',
  includeId = true,
  includeQuestion = true,
): string {
  const intervention = experiment.intervention ?? experiment.scenario?.intervention;
  const mode = experiment.scenario?.llmPolicy?.mode ?? 'RULE_ONLY';
  const modelId = experiment.scenario?.llmPolicy?.modelId;
  const modelRoute = mode === 'HYBRID_LLM' && modelId ? `${mode} / ${modelId}` : mode;
  const seedCount = experiment.scenario?.seedCount ?? experiment.totalSeeds;
  const comparison = intervention
    ? `${intervention.parameter}: ${intervention.baselineValue} → ${intervention.interventionValue}`
    : language === 'zh-CN' ? '干预信息不可用' : 'Intervention unavailable';
  const seeds = seedCount === undefined
    ? language === 'zh-CN' ? '种子数不可用' : 'Seeds unavailable'
    : language === 'zh-CN' ? `${seedCount} 个种子` : `${seedCount} seeds`;
  const subject = includeQuestion
    ? localizedQuestion(experiment, language)
    : experiment.eventPackId;
  const identity = `${subject} · ${comparison} · ${modelRoute} · ${seeds}`;
  return includeId ? `${identity} · ${experiment.id}` : identity;
}

export function ExperimentHistoryDisclosure() {
  const { language } = useI18n();
  return (
    <InlineNotification
      kind="info"
      lowContrast
      hideCloseButton
      className="history-retention-notice"
      title={language === 'zh-CN' ? '匿名会话历史与留存' : 'Anonymous-session history and retention'}
      subtitle={language === 'zh-CN'
        ? `这里只显示当前匿名浏览器会话的实验。终态实验最多保留 ${EXPERIMENT_HISTORY_RETENTION_DAYS} 天；每个会话最多 ${MAX_EXPERIMENTS_PER_ANONYMOUS_SESSION} 条，全站最多 ${MAX_STORED_EXPERIMENTS_SITE_WIDE} 条并滚动淘汰。需要长期保存时请及时导出。`
        : `Only experiments from this anonymous browser session are shown. Terminal experiments are retained for up to ${EXPERIMENT_HISTORY_RETENTION_DAYS} days; each session keeps at most ${MAX_EXPERIMENTS_PER_ANONYMOUS_SESSION} records and the site keeps at most ${MAX_STORED_EXPERIMENTS_SITE_WIDE} with rolling eviction. Export promptly for long-term retention.`}
    />
  );
}
