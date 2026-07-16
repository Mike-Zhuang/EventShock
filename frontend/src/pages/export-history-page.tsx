import { Button, InlineNotification } from '@carbon/react';
import { DownloadSimple, FileZip, FolderOpen } from '@phosphor-icons/react';
import { useState } from 'react';
import type { ViewId } from '../app';
import { EmptyState, LoadingPanel, PageHeader, StatusBadge } from '../components/common';
import { useI18n } from '../i18n';
import { useWorkflow } from '../state/workflow-context';
import { safeDate } from '../utils/format';

const EXPORT_FILES = [
  'manifest.json',
  'scenario_baseline.json',
  'scenario_intervention.json',
  'event_pack_manifest.json',
  'source_hashes.csv',
  'random_seeds.csv',
  'model_and_prompt_versions.json',
  'cognitive_decisions.json',
  'aggregate_metrics.json',
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

export function ExportHistoryPage({ navigate }: { navigate: (view: ViewId) => void }) {
  const { language, t } = useI18n();
  const {
    experiments,
    experimentsState,
    activeExperiment,
    selectExperiment,
    exportExperiment,
  } = useWorkflow();
  const [exportingId, setExportingId] = useState<string>();
  const [message, setMessage] = useState<{ kind: 'success' | 'error'; text: string }>();

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
    await selectExperiment(experimentId);
    navigate('runs');
  };

  return (
    <div className="page page--export">
      <PageHeader title={t('export.title')} subtitle={t('export.subtitle')} />
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
            <li>{language === 'zh-CN' ? '若 resolvedMode 为 HYBRID_LLM，优先复用 cognitive_decisions.json 中的冻结决策，不重新请求漂移后的供应商模型。' : 'When resolvedMode is HYBRID_LLM, reuse frozen decisions in cognitive_decisions.json instead of calling a potentially drifted provider model.'}</li>
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
        {experimentsState === 'loading' && experiments.length === 0 ? <LoadingPanel /> : null}
        {experimentsState === 'success' && experiments.length === 0 ? (
          <EmptyState title={t('runs.emptyTitle')} body={t('export.noHistory')} icon={<FolderOpen size={28} weight="duotone" />} />
        ) : null}
        {experiments.length > 0 ? (
          <div className="history-table-wrap">
            <table className="history-table">
              <thead>
                <tr>
                  <th scope="col">ID</th>
                  <th scope="col">{t('scenario.eventPack')}</th>
                  <th scope="col">{t('common.details')}</th>
                  <th scope="col">{t('common.updated', { value: '' }).trim()}</th>
                  <th scope="col">{t('export.bundle')}</th>
                </tr>
              </thead>
              <tbody>
                {experiments.map((experiment) => (
                  <tr key={experiment.id} className={activeExperiment?.id === experiment.id ? 'is-selected' : ''}>
                    <td><code>{experiment.id}</code></td>
                    <td><code>{experiment.eventPackId}</code></td>
                    <td><StatusBadge status={experiment.status} /></td>
                    <td>{safeDate(experiment.updatedAt ?? experiment.createdAt, language)}</td>
                    <td>
                      <div className="table-actions">
                        <Button kind="ghost" size="sm" onClick={() => void inspectRun(experiment.id)}>{t('common.open')}</Button>
                        <Button
                          kind="tertiary"
                          size="sm"
                          renderIcon={DownloadSimple}
                          disabled={experiment.status !== 'COMPLETED' || exportingId === experiment.id}
                          title={experiment.status !== 'COMPLETED' ? t('export.notReady') : undefined}
                          onClick={() => void exportRun(experiment.id)}
                        >
                          {exportingId === experiment.id ? t('export.preparing') : t('export.bundle')}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  );
}
