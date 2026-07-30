import { InlineNotification } from '@carbon/react';
import type { Experiment } from '../api/types';
import { useI18n } from '../i18n';

export const EXPERIMENT_HISTORY_RETENTION_DAYS = 90;
export const MAX_EXPERIMENTS_PER_ACCOUNT = 30;
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
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  return (
    <InlineNotification
      kind="info"
      lowContrast
      hideCloseButton
      className="history-retention-notice"
      title={language === 'zh-CN' ? '当前账号的实验历史与留存' : 'Current-account experiment history and retention'}
      subtitle={language === 'zh-CN'
        ? `这里只显示当前已登录账号拥有的实验。终态实验最多保留 ${EXPERIMENT_HISTORY_RETENTION_DAYS} 天；每个账号最多 ${MAX_EXPERIMENTS_PER_ACCOUNT} 条，全站最多 ${MAX_STORED_EXPERIMENTS_SITE_WIDE} 条并按状态和时间滚动淘汰。页面时间使用 ${timeZone}，导出时间始终使用 UTC。需要长期保存时请及时导出。`
        : `Only experiments owned by the current signed-in account are shown. Terminal experiments are retained for up to ${EXPERIMENT_HISTORY_RETENTION_DAYS} days; each account keeps at most ${MAX_EXPERIMENTS_PER_ACCOUNT} records and the site keeps at most ${MAX_STORED_EXPERIMENTS_SITE_WIDE} with status-aware rolling eviction. Page times use ${timeZone}; exports always use UTC. Export promptly for long-term retention.`}
    />
  );
}
