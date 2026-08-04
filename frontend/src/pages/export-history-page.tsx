import {
  Button,
  InlineNotification,
  Select,
  SelectItem,
  TextInput,
} from '@carbon/react';
import { DownloadSimple, FileZip, FolderOpen } from '@phosphor-icons/react';
import { useMemo, useState } from 'react';
import type { CaseSummary, Experiment } from '../api/types';
import type { Navigate } from '../app';
import { EmptyState, LoadingPanel, PageHeader, StatusBadge } from '../components/common';
import { ExperimentHistoryDisclosure, experimentHistoryLabel } from '../components/experiment-history';
import { SyntheticInstrumentLabel } from '../components/synthetic-instrument-label';
import { useI18n } from '../i18n';
import { getPageGuide } from '../page-guidance';
import { useWorkflow } from '../state/workflow-context';
import { downloadFilename, safeDate } from '../utils/format';

const EXPORT_FILES = [
  'manifest.json',
  'scenario_baseline.json',
  'scenario_intervention.json',
  'event_pack_manifest.json',
  'source_hashes.csv',
  'random_seeds.csv',
  'model_and_prompt_versions.json',
  'cognitive_decisions.json',
  'cognition_closed_loop_pilot.json',
  'aggregate_metrics.json',
  'analysis_diagnostics.json',
  'order_execution_summary.json',
  'run_level_metrics.csv',
  'selected_traces.jsonl',
  'validation_report.md',
  'limitations.md',
  'README_REPRODUCE.md',
];

const PARQUET_FILES = [
  'parquet/run_level_metrics.parquet',
  'parquet/market_snapshots.parquet',
  'parquet/trace_index.parquet',
  'parquet/orders.parquet',
  'parquet/trades.parquet',
  'parquet/agent_decisions.parquet',
  'parquet/schema_manifest.json',
];

function historyStatusLabel(status: string, isZh: boolean): string {
  const labels: Record<string, { en: string; zh: string }> = {
    DRAFT: { en: 'Draft', zh: '草稿' },
    READY: { en: 'Ready', zh: '就绪' },
    QUEUED: { en: 'Queued', zh: '排队中' },
    RUNNING: { en: 'Running', zh: '运行中' },
    AGGREGATING: { en: 'Aggregating', zh: '汇总中' },
    CANCEL_REQUESTED: { en: 'Cancellation requested', zh: '正在取消' },
    COMPLETED: { en: 'Completed', zh: '已完成' },
    FAILED: { en: 'Failed', zh: '失败' },
    FAILED_RETRYABLE: { en: 'Failed, retryable', zh: '失败，可重试' },
    FAILED_FINAL: { en: 'Failed, final', zh: '最终失败' },
    CANCELLED: { en: 'Cancelled', zh: '已取消' },
    INVALIDATED: { en: 'Invalidated', zh: '已作废' },
  };
  const label = labels[status];
  return label ? isZh ? label.zh : label.en : isZh
    ? `其他状态（${status}）`
    : `Other status (${status})`;
}

function caseForExperiment(
  experiment: Experiment,
  casesByEventPackId: ReadonlyMap<string, CaseSummary>,
): CaseSummary | undefined {
  return casesByEventPackId.get(experiment.eventPackId);
}

function localizedEventTitle(
  experiment: Experiment,
  casesByEventPackId: ReadonlyMap<string, CaseSummary>,
  language: 'en' | 'zh-CN',
): string {
  const caseItem = caseForExperiment(experiment, casesByEventPackId);
  if (language === 'zh-CN') {
    return caseItem?.nameZh || caseItem?.name || experiment.eventPackId;
  }
  return caseItem?.name || caseItem?.nameZh || experiment.eventPackId;
}

function localizedResearchQuestion(
  experiment: Experiment,
  language: 'en' | 'zh-CN',
): string {
  if (language === 'zh-CN') {
    return experiment.scenario?.questionZh
      || experiment.scenario?.question
      || '研究问题不可用';
  }
  return experiment.scenario?.question
    || experiment.scenario?.questionZh
    || 'Research question unavailable';
}

function modelFilterKey(experiment: Experiment): string {
  const policy = experiment.scenario?.llmPolicy;
  if (!policy || policy.mode === 'RULE_ONLY') return 'RULE_ONLY';
  return [
    policy.mode,
    policy.provider || 'PROVIDER_UNAVAILABLE',
    policy.modelId || 'MODEL_UNAVAILABLE',
  ].join('::');
}

function modelFilterLabel(experiment: Experiment, isZh: boolean): string {
  const policy = experiment.scenario?.llmPolicy;
  if (!policy || policy.mode === 'RULE_ONLY') {
    return isZh ? '仅确定性规则（未请求外部模型）' : 'Deterministic rules only (no external model requested)';
  }
  const route = [policy.provider, policy.modelId].filter(Boolean).join(' / ');
  return route || (isZh ? '混合 LLM（模型不可用）' : 'Hybrid LLM (model unavailable)');
}

function interventionParameter(experiment: Experiment): string {
  return experiment.intervention?.parameter
    ?? experiment.scenario?.intervention.parameter
    ?? 'UNAVAILABLE';
}

function matchesUpdatedDateRange(
  experiment: Experiment,
  fromDate: string,
  throughDate: string,
): boolean {
  if (!fromDate && !throughDate) return true;
  const updatedAt = experiment.updatedAt ?? experiment.createdAt;
  if (!updatedAt) return false;
  const updatedTimestamp = new Date(updatedAt).getTime();
  if (!Number.isFinite(updatedTimestamp)) return false;
  const fromTimestamp = fromDate
    ? new Date(`${fromDate}T00:00:00`).getTime()
    : Number.NEGATIVE_INFINITY;
  const throughTimestamp = throughDate
    ? new Date(`${throughDate}T23:59:59.999`).getTime()
    : Number.POSITIVE_INFINITY;
  return updatedTimestamp >= fromTimestamp && updatedTimestamp <= throughTimestamp;
}

interface ExperimentExportAction {
  label: string;
  available: boolean;
  reason?: string;
  filename?: string;
}

function experimentExportAction(
  experiment: Experiment,
  isZh: boolean,
): ExperimentExportAction {
  if (experiment.status === 'COMPLETED') {
    return {
      label: isZh ? '导出完整可复现包' : 'Export full reproducibility bundle',
      available: true,
      filename: downloadFilename(experiment.id),
    };
  }
  if (['FAILED', 'FAILED_RETRYABLE', 'FAILED_FINAL'].includes(experiment.status)) {
    return {
      label: isZh ? '诊断包' : 'Diagnostic bundle',
      available: false,
      reason: isZh
        ? '当前后端没有失败实验诊断包接口；为避免把不完整数据伪装成合法 ZIP，下载保持禁用。请打开实验查看错误和运行日志。'
        : 'The current backend has no failed-run diagnostic bundle endpoint. Download stays disabled so incomplete data is not presented as a valid ZIP; open the experiment to review its error and run logs.',
    };
  }
  if (experiment.status === 'INVALIDATED') {
    return {
      label: isZh ? '可复现包不可用' : 'Reproducibility bundle unavailable',
      available: false,
      reason: isZh
        ? '该实验已作废，后端禁止把保留结果导出为有效研究证据。'
        : 'This experiment was invalidated, so the backend blocks exporting its preserved result as valid research evidence.',
    };
  }
  return {
    label: isZh ? '可复现包尚不可用' : 'Reproducibility bundle not ready',
    available: false,
    reason: isZh
      ? '完整可复现包仅在实验成功完成并持久化结果后可用。'
      : 'A full reproducibility bundle is available only after the experiment completes and its results are persisted.',
  };
}

export function ExportHistoryPage({ navigate }: { navigate: Navigate }) {
  const { language, t } = useI18n();
  const {
    cases,
    experiments,
    experimentsState,
    activeExperiment,
    selectExperiment,
    loadResults,
    exportExperiment,
  } = useWorkflow();
  const [exportingId, setExportingId] = useState<string>();
  const [message, setMessage] = useState<{ kind: 'success' | 'error'; text: string }>();
  const [historySearch, setHistorySearch] = useState('');
  const [historyStatus, setHistoryStatus] = useState('all');
  const [historyFromDate, setHistoryFromDate] = useState('');
  const [historyThroughDate, setHistoryThroughDate] = useState('');
  const [historyModel, setHistoryModel] = useState('all');
  const [historyIntervention, setHistoryIntervention] = useState('all');
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  const isZh = language === 'zh-CN';
  const casesByEventPackId = useMemo(
    () => new Map(cases.flatMap((caseItem) => (
      caseItem.eventPackId ? [[caseItem.eventPackId, caseItem] as const] : []
    ))),
    [cases],
  );
  const filteredExperiments = useMemo(() => {
    const query = historySearch.trim().toLocaleLowerCase(language);
    return experiments.filter((experiment) => {
      const caseItem = caseForExperiment(experiment, casesByEventPackId);
      const searchIndex = [
        caseItem?.name,
        caseItem?.nameZh,
        experiment.scenario?.question,
        experiment.scenario?.questionZh,
        experimentHistoryLabel(experiment, 'en'),
        experimentHistoryLabel(experiment, 'zh-CN'),
        experiment.id,
        experiment.eventPackId,
        modelFilterLabel(experiment, false),
        modelFilterLabel(experiment, true),
        interventionParameter(experiment),
      ].filter(Boolean).join(' ').toLocaleLowerCase(language);
      return (
        (historyStatus === 'all' || experiment.status === historyStatus)
        && (historyModel === 'all' || modelFilterKey(experiment) === historyModel)
        && (
          historyIntervention === 'all'
          || interventionParameter(experiment) === historyIntervention
        )
        && matchesUpdatedDateRange(experiment, historyFromDate, historyThroughDate)
        && (!query || searchIndex.includes(query))
      );
    });
  }, [
    casesByEventPackId,
    experiments,
    historyFromDate,
    historyIntervention,
    historyModel,
    historySearch,
    historyStatus,
    historyThroughDate,
    language,
  ]);
  const historyStatuses = useMemo(
    () => [...new Set(experiments.map((experiment) => experiment.status))].sort(),
    [experiments],
  );
  const historyModels = useMemo(
    () => [...new Map(experiments.map((experiment) => [
      modelFilterKey(experiment),
      modelFilterLabel(experiment, isZh),
    ])).entries()].sort((left, right) => left[1].localeCompare(right[1], language)),
    [experiments, isZh, language],
  );
  const historyInterventions = useMemo(
    () => [...new Set(experiments.map(interventionParameter))]
      .filter((parameter) => parameter !== 'UNAVAILABLE')
      .sort((left, right) => left.localeCompare(right, language)),
    [experiments, language],
  );
  const hasFailedExperiments = experiments.some((experiment) => (
    ['FAILED', 'FAILED_RETRYABLE', 'FAILED_FINAL'].includes(experiment.status)
  ));
  const hasActiveFilters = Boolean(
    historySearch
    || historyStatus !== 'all'
    || historyFromDate
    || historyThroughDate
    || historyModel !== 'all'
    || historyIntervention !== 'all',
  );

  const clearHistoryFilters = () => {
    setHistorySearch('');
    setHistoryStatus('all');
    setHistoryFromDate('');
    setHistoryThroughDate('');
    setHistoryModel('all');
    setHistoryIntervention('all');
  };

  const exportRun = async (experimentId: string) => {
    setExportingId(experimentId);
    setMessage(undefined);
    try {
      await exportExperiment(experimentId);
      setMessage({ kind: 'success', text: t('export.success') });
    } catch (error) {
      setMessage({ kind: 'error', text: t('error.export') });
    } finally {
      setExportingId(undefined);
    }
  };

  const inspectRun = async (experimentId: string) => {
    setMessage(undefined);
    try {
      const experiment = await selectExperiment(experimentId);
      if (!experiment) return;
      if (experiment.status === 'COMPLETED') {
        const nextResults = await loadResults(experiment.id);
        if (!nextResults) return;
        navigate('results', { experimentId: experiment.id });
        return;
      }
      navigate('runs');
    } catch {
      setMessage({ kind: 'error', text: t('common.errorFallback') });
    }
  };

  return (
    <div className="page page--export">
      <PageHeader title={t('export.title')} subtitle={t('export.subtitle')} guide={getPageGuide('export', language)} />
      {message ? (
        <InlineNotification kind={message.kind} lowContrast hideCloseButton title={message.kind === 'success' ? t('export.success') : t('common.errorTitle')} subtitle={message.text} />
      ) : null}

      <section className="export-manifest">
        <FileZip size={28} weight="duotone" aria-hidden="true" />
        <div>
          <h2>{t('export.manifest')}</h2>
          <p>{t('export.manifestValue')}</p>
        </div>
      </section>

      <div className="export-contract-grid">
        <section className="export-contract-panel" aria-labelledby="export-file-list-heading">
          <div className="section-heading"><h2 id="export-file-list-heading">{language === 'zh-CN' ? '固定导出契约' : 'Fixed export contract'}</h2><p>{language === 'zh-CN' ? 'ZIP 中的每个文件都来自已完成实验，不包含 API key 或来源全文。' : 'Every file in the ZIP comes from a completed experiment. API keys and full source documents are excluded.'}</p></div>
          <div className="export-file-columns">
            <ul>{EXPORT_FILES.map((file) => <li key={file}><code>{file}</code></li>)}</ul>
            <ul>{PARQUET_FILES.map((file) => <li key={file}><code>{file}</code></li>)}</ul>
          </div>
        </section>
        <section className="export-contract-panel" aria-labelledby="reproduce-heading">
          <div className="section-heading"><h2 id="reproduce-heading">{language === 'zh-CN' ? '重放要求' : 'Replay requirements'}</h2></div>
          <ol>
            <li>{language === 'zh-CN' ? '核对 manifest 中的 Event Pack、场景、种子、引擎、模型和提示词哈希。' : 'Verify Event Pack, scenario, seed, engine, model, and prompt hashes in the manifest.'}</li>
            <li>{language === 'zh-CN' ? '使用 CPython 3.12.13 和 manifest 指定的引擎版本。' : 'Use CPython 3.12.13 and the engine version declared in the manifest.'}</li>
            <li>{language === 'zh-CN' ? '若 resolvedMode 以 HYBRID_LLM 开头，优先复用 cognitive_decisions.json 中的冻结决策，不重新请求漂移后的供应商模型。' : 'When resolvedMode starts with HYBRID_LLM, reuse frozen decisions in cognitive_decisions.json instead of calling a potentially drifted provider model.'}</li>
            <li>{language === 'zh-CN' ? '按 README_REPRODUCE.md 验证配对种子和结果哈希。' : 'Follow README_REPRODUCE.md to verify matched seeds and result hashes.'}</li>
          </ol>
          <InlineNotification
            kind="info"
            lowContrast
            hideCloseButton
            title={language === 'zh-CN' ? '许可与隐私边界' : 'License and privacy boundary'}
            subtitle={language === 'zh-CN' ? '来源链接、元数据、内容哈希和短候选 claim 可进入导出；完整上传文档与 API key 不进入导出。公开再分发仍需人工许可审核。' : 'Source links, metadata, content hashes, and short candidate claims may be exported. Full uploaded documents and API keys are excluded. Public redistribution still requires human license review.'}
          />
        </section>
      </div>

      <section className="history-section" aria-labelledby="history-heading">
        <div className="section-heading"><h2 id="history-heading">{t('export.history')}</h2></div>
        <ExperimentHistoryDisclosure />
        {hasFailedExperiments ? (
          <InlineNotification
            kind="warning"
            lowContrast
            hideCloseButton
            className="history-export-boundary"
            title={isZh ? '失败实验只应生成诊断包' : 'Failed experiments require a diagnostic bundle'}
            subtitle={isZh
              ? '现有后端导出接口只接受已完成实验，并生成完整可复现包；它尚未提供合法的失败诊断 ZIP。失败行会明确标为“诊断包”并禁用下载，不会调用完成实验的导出接口。'
              : 'The existing backend export endpoint accepts only completed experiments and creates a full reproducibility bundle; it does not yet provide a valid failed-run diagnostic ZIP. Failed rows are labeled “Diagnostic bundle” and stay disabled without calling the completed-run export endpoint.'}
          />
        ) : null}
        {experiments.length > 0 ? (
          <div className="history-filters" role="search" aria-label={language === 'zh-CN' ? '筛选实验历史' : 'Filter experiment history'}>
            <TextInput
              id="history-search"
              labelText={language === 'zh-CN' ? '搜索事件、研究问题、干预或实验 ID' : 'Search event, question, intervention, or experiment ID'}
              value={historySearch}
              onChange={(event) => setHistorySearch(event.target.value)}
            />
            <Select
              id="history-status"
              labelText={language === 'zh-CN' ? '实验状态' : 'Experiment status'}
              value={historyStatus}
              onChange={(event) => setHistoryStatus(event.target.value)}
            >
              <SelectItem value="all" text={language === 'zh-CN' ? '全部状态' : 'All statuses'} />
              {historyStatuses.map((status) => (
                <SelectItem
                  key={status}
                  value={status}
                  text={historyStatusLabel(status, language === 'zh-CN')}
                />
              ))}
            </Select>
            <Select
              id="history-model"
              labelText={isZh ? '请求的模型' : 'Requested model'}
              value={historyModel}
              onChange={(event) => setHistoryModel(event.target.value)}
            >
              <SelectItem value="all" text={isZh ? '全部模型' : 'All models'} />
              {historyModels.map(([model, label]) => (
                <SelectItem key={model} value={model} text={label} />
              ))}
            </Select>
            <Select
              id="history-intervention"
              labelText={isZh ? '干预参数' : 'Intervention parameter'}
              value={historyIntervention}
              onChange={(event) => setHistoryIntervention(event.target.value)}
            >
              <SelectItem value="all" text={isZh ? '全部干预' : 'All interventions'} />
              {historyInterventions.map((parameter) => (
                <SelectItem key={parameter} value={parameter} text={parameter} />
              ))}
            </Select>
            <TextInput
              id="history-from-date"
              type="date"
              labelText={isZh ? '更新日期起' : 'Updated from'}
              value={historyFromDate}
              onChange={(event) => setHistoryFromDate(event.target.value)}
            />
            <TextInput
              id="history-through-date"
              type="date"
              labelText={isZh ? '更新日期止（含当天）' : 'Updated through (inclusive)'}
              value={historyThroughDate}
              onChange={(event) => setHistoryThroughDate(event.target.value)}
            />
            <Button
              kind="ghost"
              size="sm"
              disabled={!hasActiveFilters}
              onClick={clearHistoryFilters}
            >
              {isZh ? '清除筛选' : 'Clear filters'}
            </Button>
          </div>
        ) : null}
        {experimentsState === 'loading' && experiments.length === 0 ? <LoadingPanel /> : null}
        {experimentsState === 'success' && experiments.length === 0 ? (
          <EmptyState title={t('runs.emptyTitle')} body={t('export.noHistory')} icon={<FolderOpen size={28} weight="duotone" />} />
        ) : null}
        {experiments.length > 0 && filteredExperiments.length === 0 ? (
          <EmptyState
            title={language === 'zh-CN' ? '没有匹配的实验' : 'No matching experiments'}
            body={language === 'zh-CN'
              ? '请调整搜索词、状态、日期、请求模型或干预参数筛选。'
              : 'Adjust the search, status, date, requested-model, or intervention filter.'}
            icon={<FolderOpen size={28} weight="duotone" />}
          />
        ) : null}
        {filteredExperiments.length > 0 ? (
          <div className="history-table-wrap">
            <table className="history-table">
              <thead>
                <tr>
                  <th scope="col">{isZh ? '事件与研究问题' : 'Event and research question'}</th>
                  <th scope="col">{isZh ? '状态与实验设计' : 'Status and design'}</th>
                  <th scope="col">{t('common.updated', { value: '' }).trim()} ({timeZone})</th>
                  <th scope="col">{isZh ? '导出工件' : 'Export artifact'}</th>
                </tr>
              </thead>
              <tbody>
                {filteredExperiments.map((experiment) => {
                  const exportAction = experimentExportAction(experiment, isZh);
                  const intervention = experiment.intervention ?? experiment.scenario?.intervention;
                  return (
                    <tr key={experiment.id} className={activeExperiment?.id === experiment.id ? 'is-selected' : ''}>
                      <td className="history-table__subject">
                        <strong>
                          {localizedEventTitle(experiment, casesByEventPackId, language)}
                        </strong>
                        <span>{localizedResearchQuestion(experiment, language)}</span>
                        <SyntheticInstrumentLabel
                          instrument={experiment.scenario?.market?.instrumentId}
                          compact
                        />
                        <small>
                          <code>{experiment.id}</code>
                          {' · '}
                          <code>{experiment.eventPackId}</code>
                        </small>
                      </td>
                      <td className="history-table__design">
                        <StatusBadge status={experiment.status} />
                        <span>
                          {intervention
                            ? `${intervention.parameter}: ${intervention.baselineValue} → ${intervention.interventionValue}`
                            : isZh ? '干预信息不可用' : 'Intervention unavailable'}
                        </span>
                        <small>{modelFilterLabel(experiment, isZh)}</small>
                      </td>
                      <td>{safeDate(experiment.updatedAt ?? experiment.createdAt, language)}</td>
                      <td className="history-table__export">
                        <div className="table-actions">
                          <Button kind="ghost" size="sm" onClick={() => void inspectRun(experiment.id)}>{t('common.open')}</Button>
                          <Button
                            kind="tertiary"
                            size="sm"
                            renderIcon={DownloadSimple}
                            disabled={!exportAction.available || exportingId === experiment.id}
                            title={exportAction.reason}
                            onClick={() => void exportRun(experiment.id)}
                          >
                            {exportingId === experiment.id
                              ? t('export.preparing')
                              : exportAction.label}
                          </Button>
                        </div>
                        {exportAction.reason ? (
                          <small>{exportAction.reason}</small>
                        ) : (
                          <small>
                            {isZh ? '文件名' : 'Filename'}: <code>{exportAction.filename}</code>
                          </small>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  );
}
