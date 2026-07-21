import { Button, InlineNotification, Tag } from '@carbon/react';
import {
  Brain,
  CheckCircle,
  Code,
  FileLock,
  Gauge,
  ShieldCheck,
  UserCheck,
  Warning,
} from '@phosphor-icons/react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type {
  CognitionEvalSummary,
  GovernanceInventory,
  RedTeamRegistry,
  ReleaseGateView,
  SystemMetrics,
  ValidationLadderView,
} from '../api/types';
import { EmptyState, LoadingPanel, Notice, PageHeader, StatusBadge } from '../components/common';
import { useI18n } from '../i18n';
import { getPageGuide } from '../page-guidance';
import { useWorkflow } from '../state/workflow-context';
import { formatMetricValue, safeDate } from '../utils/format';

interface GovernanceData {
  inventory: GovernanceInventory;
  redTeam: RedTeamRegistry;
  releaseGate: ReleaseGateView;
  ladder: ValidationLadderView;
  evalSummary: CognitionEvalSummary;
  systemMetrics: SystemMetrics;
}

const LADDER_TITLES_ZH: Record<string, string> = {
  L0: '代码与账本不变量',
  L1: '市场微观结构模块',
  L2: '规则智能体总体行为',
  L3: 'LLM 认知与工具行为',
  L4: '市场统计与典型事实',
  L5: '历史事件响应',
  L6: '反事实稳健性',
  L7: '用户理解与可用性',
  L8: '运行、成本、安全与治理',
};

const STATUS_ZH: Record<string, string> = {
  PASS: '通过',
  FAIL: '失败',
  BLOCKED: '阻止发布',
  NOT_RUN: '尚未执行',
  NOT_EVALUATED: '尚未评估',
  NOT_COMPLETED: '尚未完成',
  PENDING_HUMAN_EVIDENCE: '等待人工证据',
  AUTOMATED_EVIDENCE_AVAILABLE: '已有自动化证据',
  IMPLEMENTED_AWAITING_EMPIRICAL_STUDY: '已实现，等待实证研究',
  IMPLEMENTED_AWAITING_LIVE_MODEL_REVIEW: '已实现，等待真实模型审核',
  IMPLEMENTED_AWAITING_CALIBRATION_EVIDENCE: '已实现，等待校准证据',
  IMPLEMENTED_AWAITING_STUDY_EXECUTION: '已实现，等待执行研究',
  APPROVED_FOR_DEMO: '批准用于演示',
  APPROVED_WITH_LIMITATIONS: '附带限制批准',
  NOT_APPROVED: '未批准',
  CODE_VERIFIED: '代码验证',
  TEST_VERIFIED: '测试验证',
  DOCUMENTED_ONLY: '仅有文档',
  READY_FOR_CONTROLLED_DEMO: '可用于受控演示',
};

function statusLabel(status: string, isZh: boolean): string {
  return isZh ? STATUS_ZH[status] ?? status.replaceAll('_', ' ') : status.replaceAll('_', ' ');
}

function statusTagType(status: string): 'green' | 'red' | 'blue' | 'warm-gray' | 'purple' {
  if (['PASS', 'APPROVED_FOR_DEMO', 'AUTOMATED_EVIDENCE_AVAILABLE'].includes(status)) return 'green';
  if (['FAIL', 'BLOCKED', 'NOT_APPROVED'].includes(status)) return 'red';
  if (status.includes('PENDING') || status.includes('AWAITING') || status === 'NOT_RUN') return 'warm-gray';
  if (status.includes('VERIFIED')) return 'blue';
  return 'purple';
}

function rate(value: number, language: string): string {
  return new Intl.NumberFormat(language, { style: 'percent', maximumFractionDigits: 1 }).format(value);
}

export function GovernancePage() {
  const { language, t } = useI18n();
  const { results } = useWorkflow();
  const isZh = language === 'zh-CN';
  const limitations = isZh ? results?.limitationsZh : results?.limitations;
  const [data, setData] = useState<GovernanceData>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();

  const load = useCallback(async () => {
    setLoading(true);
    setError(undefined);
    try {
      const [inventory, redTeam, releaseGate, ladder, evalSummary, systemMetrics] = await Promise.all([
        api.getGovernanceInventory(),
        api.getRedTeamRegistry(),
        api.getReleaseGate(),
        api.getValidationLadder(),
        api.getEvalSummary(),
        api.getSystemMetrics(),
      ]);
      setData({ inventory, redTeam, releaseGate, ladder, evalSummary, systemMetrics });
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : String(loadError));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const componentCounts = useMemo(() => {
    const items = data?.inventory.items ?? [];
    return {
      total: items.length,
      external: items.filter((item) => item.external).length,
      pending: items.filter((item) => item.approvalStatus.includes('PENDING')).length,
      critical: items.filter((item) => item.materiality === 'CRITICAL').length,
    };
  }, [data?.inventory.items]);

  const decisionRows = [
    { icon: Brain, label: t('governance.extract'), value: t('governance.extractValue') },
    { icon: Brain, label: t('governance.beliefs'), value: t('governance.beliefsValue') },
    { icon: Code, label: t('governance.orders'), value: t('governance.ordersValue') },
    { icon: UserCheck, label: t('governance.interpret'), value: t('governance.interpretValue') },
  ];
  const riskRows = [
    t('governance.riskForecast'),
    t('governance.riskLeakage'),
    t('governance.riskAuthority'),
    t('governance.riskCherryPick'),
  ];

  return (
    <div className="page page--governance">
      <PageHeader
        title={t('governance.title')}
        subtitle={t('governance.subtitle')}
        guide={getPageGuide('governance', language)}
        actions={<Button kind="ghost" onClick={() => void load()}>{isZh ? '刷新治理证据' : 'Refresh evidence'}</Button>}
      />

      {loading ? <LoadingPanel /> : null}
      {error ? (
        <InlineNotification
          kind="error"
          lowContrast
          hideCloseButton
          title={isZh ? '无法加载治理证据' : 'Governance evidence could not be loaded'}
          subtitle={error}
        />
      ) : null}

      {data ? (
        <>
          <section className={`release-gate-banner ${data.releaseGate.canRelease ? 'is-ready' : 'is-blocked'}`}>
            <ShieldCheck size={34} weight="duotone" aria-hidden="true" />
            <div>
              <span>{isZh ? 'P0 发布门禁' : 'P0 release gate'}</span>
              <h2>{statusLabel(data.releaseGate.decision, isZh)}</h2>
              <p>{isZh
                ? '当前状态不会阻止教学演示，但禁止把系统表述为已获得外部验证或已达到生产就绪。'
                : data.releaseGate.interpretationBoundary}</p>
            </div>
            <dl>
              <div><dt>{isZh ? '阻断项' : 'Blockers'}</dt><dd>{data.releaseGate.blockerGateIds.length}</dd></div>
              <div><dt>{isZh ? '人工证据' : 'Human evidence'}</dt><dd>{data.releaseGate.humanEvidenceComplete ? isZh ? '完整' : 'Complete' : isZh ? '待完成' : 'Pending'}</dd></div>
              <div><dt>{isZh ? '评估时间' : 'Evaluated'}</dt><dd>{safeDate(data.releaseGate.evaluatedAt, language)}</dd></div>
            </dl>
          </section>

          <section className="governance-panel governance-panel--operations" aria-labelledby="operations-heading">
            <div className="section-heading section-heading--with-control">
              <div>
                <h2 id="operations-heading">{isZh ? '有界运行指标' : 'Bounded runtime metrics'}</h2>
                <p>{isZh ? '只显示当前单进程实例的聚合观测；不记录路径、正文、会话标识或凭据。' : 'Aggregates cover only this single-process instance. Paths, bodies, session identifiers, and credentials are not recorded.'}</p>
              </div>
              <Tag type={data.systemMetrics.storage.database === 'ok' ? 'green' : 'red'}>{isZh ? '数据库' : 'Database'}: {data.systemMetrics.storage.database}</Tag>
            </div>
            <div className="governance-stat-grid">
              <div><span>{isZh ? '实例运行时间' : 'Instance uptime'}</span><strong>{formatMetricValue(data.systemMetrics.runtime.uptimeSeconds, 'seconds', language)}</strong></div>
              <div><span>{isZh ? '请求总数' : 'Requests'}</span><strong>{data.systemMetrics.runtime.requestCount.toLocaleString(language)}</strong></div>
              <div><span>{isZh ? 'P50 延迟' : 'P50 latency'}</span><strong>{formatMetricValue(data.systemMetrics.runtime.latencyMs.p50, 'ms', language)}</strong></div>
              <div><span>{isZh ? 'P95 延迟' : 'P95 latency'}</span><strong>{formatMetricValue(data.systemMetrics.runtime.latencyMs.p95, 'ms', language)}</strong></div>
              <div><span>{isZh ? '服务端错误率' : 'Server-error rate'}</span><strong>{rate(data.systemMetrics.runtime.serverErrorRate, language)}</strong></div>
              <div><span>{isZh ? '运行中或排队' : 'Active or queued'}</span><strong>{data.systemMetrics.experiments.activeOrQueued} / {data.systemMetrics.experiments.maximumActiveOrQueued}</strong></div>
              <div><span>{isZh ? '保留实验数' : 'Retained experiments'}</span><strong>{data.systemMetrics.storage.retainedExperiments} / {data.systemMetrics.storage.maximumRetainedExperiments}</strong></div>
              <div><span>{isZh ? 'LLM 调用' : 'LLM calls'}</span><strong>{data.systemMetrics.cognition.calls.toLocaleString(language)}</strong></div>
            </div>
            <InlineNotification
              kind="info"
              lowContrast
              hideCloseButton
              title={isZh ? 'SLO 仅是目标，不是生产证据' : 'SLOs are targets, not production evidence'}
              subtitle={isZh
                ? `可用性目标 ${rate(data.systemMetrics.sloTargets.availability, language)}；API P95 目标 ${formatMetricValue(data.systemMetrics.sloTargets.apiP95Milliseconds, 'ms', language)}。状态：${data.systemMetrics.sloTargets.status.replaceAll('_', ' ')}。`
                : `Availability target ${rate(data.systemMetrics.sloTargets.availability, language)}; API P95 target ${formatMetricValue(data.systemMetrics.sloTargets.apiP95Milliseconds, 'ms', language)}. Status: ${data.systemMetrics.sloTargets.status.replaceAll('_', ' ')}.`}
            />
          </section>

          <section className="governance-panel governance-panel--ladder" aria-labelledby="validation-ladder-heading">
            <div className="section-heading section-heading--with-control">
              <div>
                <h2 id="validation-ladder-heading">{isZh ? 'L0 至 L8 验证阶梯' : 'L0 to L8 validation ladder'}</h2>
                <p>{isZh ? '只有下层证据通过后，才允许提升解释层级。' : 'Higher interpretation claims require the lower evidence levels to pass first.'}</p>
              </div>
              <Tag type="purple">{isZh ? '最高允许主张：机制演示' : 'Highest claim: mechanism demonstration'}</Tag>
            </div>
            <ol className="validation-ladder">
              {data.ladder.levels.map((level) => (
                <li key={level.level}>
                  <span className="validation-ladder__level">{level.level}</span>
                  <div>
                    <div className="validation-ladder__title">
                      <h3>{isZh ? LADDER_TITLES_ZH[level.level] ?? level.title : level.title}</h3>
                      <Tag type={statusTagType(level.status)} size="sm">{statusLabel(level.status, isZh)}</Tag>
                    </div>
                    <p>{level.boundary}</p>
                  </div>
                </li>
              ))}
            </ol>
          </section>

          <div className="governance-grid governance-grid--evidence">
            <section className="governance-panel" aria-labelledby="eval-heading">
              <div className="section-heading">
                <h2 id="eval-heading">{isZh ? 'LLM 评估与运行遥测' : 'LLM evaluation and runtime telemetry'}</h2>
                <p>{isZh ? '代码 grader 不能替代真实模型和人工语义审核。' : 'Code graders do not replace live-model and human semantic review.'}</p>
              </div>
              <div className="governance-stat-grid">
                <div><span>{isZh ? '已评估用例' : 'Evaluated cases'}</span><strong>{data.evalSummary.evaluatedCases}</strong></div>
                <div><span>{isZh ? '通过率' : 'Pass rate'}</span><strong>{data.evalSummary.evaluatedCases > 0 ? rate(data.evalSummary.passRate, language) : isZh ? '待评估' : 'Pending'}</strong></div>
                <div><span>{isZh ? '模型调用' : 'Model calls'}</span><strong>{data.evalSummary.telemetry.calls}</strong></div>
                <div><span>{isZh ? '总 token' : 'Total tokens'}</span><strong>{data.evalSummary.telemetry.totalTokens.toLocaleString(language)}</strong></div>
                <div><span>{isZh ? '平均延迟' : 'Average latency'}</span><strong>{formatMetricValue(data.evalSummary.telemetry.averageLatencyMs, 'ms', language)}</strong></div>
                <div><span>{isZh ? '回退率' : 'Fallback rate'}</span><strong>{rate(data.evalSummary.telemetry.fallbackRate, language)}</strong></div>
                <div><span>{isZh ? '无效输出率' : 'Invalid output rate'}</span><strong>{rate(data.evalSummary.telemetry.invalidOutputRate, language)}</strong></div>
                <div><span>{isZh ? '缓存命中率' : 'Cache hit rate'}</span><strong>{rate(data.evalSummary.telemetry.cacheHitRate, language)}</strong></div>
              </div>
              {data.evalSummary.evaluatedCases === 0 ? (
                <InlineNotification
                  kind="warning"
                  lowContrast
                  hideCloseButton
                  title={isZh ? '等待真实评估证据' : 'Live evaluation evidence is pending'}
                  subtitle={isZh ? '仓库没有声称尚未执行的模型质量、双语行为或人工 grader 研究已经完成。' : 'The repository does not claim that unexecuted model-quality, bilingual-behavior, or human-grader studies are complete.'}
                />
              ) : null}
            </section>

            <section className="governance-panel" aria-labelledby="red-team-heading">
              <div className="section-heading">
                <h2 id="red-team-heading">{isZh ? '红队测试注册表' : 'Red-team test registry'}</h2>
                <p>{isZh ? '用例定义不是已执行证据。' : 'A test definition is not execution evidence.'}</p>
              </div>
              <div className="red-team-summary">
                <div><strong>{data.redTeam.definitions.length}</strong><span>{isZh ? '已定义攻击' : 'defined attacks'}</span></div>
                <div><strong>{data.redTeam.results.filter((item) => item.status === 'PASS').length}</strong><span>{isZh ? '有证据通过' : 'evidence-backed passes'}</span></div>
                <div><strong>{data.redTeam.results.filter((item) => item.status === 'NOT_RUN').length}</strong><span>{isZh ? '尚未执行' : 'not run'}</span></div>
              </div>
              <div className="governance-table-wrap">
                <table className="governance-table">
                  <thead><tr><th>{isZh ? '类别' : 'Category'}</th><th>{isZh ? '严重度' : 'Severity'}</th><th>{isZh ? '状态' : 'Status'}</th></tr></thead>
                  <tbody>
                    {data.redTeam.definitions.map((definition) => {
                      const result = data.redTeam.results.find((item) => item.caseId === definition.caseId);
                      const status = result?.status ?? 'NOT_RUN';
                      return (
                        <tr key={definition.caseId}>
                          <td><strong>{definition.category.replaceAll('_', ' ')}</strong><small>{definition.caseId}</small></td>
                          <td>{definition.severity}</td>
                          <td><Tag type={statusTagType(status)} size="sm">{statusLabel(status, isZh)}</Tag></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <Notice>{isZh
                ? '所有红队结果当前都保持 NOT_RUN，直到附加可核验执行证据。'
                : data.redTeam.notice}</Notice>
            </section>
          </div>

          <section className="governance-panel governance-panel--inventory" aria-labelledby="inventory-heading">
            <div className="section-heading section-heading--with-control">
              <div>
                <h2 id="inventory-heading">{isZh ? '模型与关键组件清单' : 'Model and critical-component inventory'}</h2>
                <p>{isZh ? '清单覆盖规则、订单、撮合、账本、网络、提示词、供应商模型、指标和密钥控制。' : 'The inventory covers rules, orders, matching, ledger, network, prompts, provider models, metrics, and secret controls.'}</p>
              </div>
              <code title={data.inventory.inventoryHash}>{data.inventory.inventoryHash.slice(0, 16)}</code>
            </div>
            <div className="governance-stat-grid governance-stat-grid--compact">
              <div><span>{isZh ? '总组件' : 'Components'}</span><strong>{componentCounts.total}</strong></div>
              <div><span>{isZh ? '关键组件' : 'Critical'}</span><strong>{componentCounts.critical}</strong></div>
              <div><span>{isZh ? '外部依赖' : 'External'}</span><strong>{componentCounts.external}</strong></div>
              <div><span>{isZh ? '等待人工证据' : 'Pending human evidence'}</span><strong>{componentCounts.pending}</strong></div>
            </div>
            <div className="component-inventory-grid">
              {data.inventory.items.map((component) => (
                <details key={component.componentId}>
                  <summary>
                    <span><strong>{component.name}</strong><small>{component.componentId}</small></span>
                    <Tag type={statusTagType(component.approvalStatus)} size="sm">{statusLabel(component.approvalStatus, isZh)}</Tag>
                  </summary>
                  <dl className="definition-list definition-list--compact">
                    <div><dt>{isZh ? '类型' : 'Kind'}</dt><dd>{component.kind}</dd></div>
                    <div><dt>{isZh ? '重要性' : 'Materiality'}</dt><dd>{component.materiality}</dd></div>
                    <div><dt>{isZh ? '版本' : 'Version'}</dt><dd><code>{component.version}</code></dd></div>
                    <div><dt>{isZh ? '负责人' : 'Owner'}</dt><dd>{component.owner}</dd></div>
                    <div><dt>{isZh ? '验证状态' : 'Validation'}</dt><dd>{component.validationStatuses.map((status) => statusLabel(status, isZh)).join(', ')}</dd></div>
                  </dl>
                  <p>{component.purpose}</p>
                  <ul>{component.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
                </details>
              ))}
            </div>
          </section>

          <section className="governance-panel governance-panel--release-details" aria-labelledby="release-blockers-heading">
            <div className="section-heading"><h2 id="release-blockers-heading">{isZh ? '发布证据门禁详情' : 'Release evidence gate details'}</h2></div>
            <div className="gate-result-list">
              {data.releaseGate.gateResults.map((gate) => {
                const definition = data.releaseGate.definitions.find((item) => item.gateId === gate.gateId);
                return (
                  <article key={gate.gateId}>
                    <Tag type={statusTagType(gate.status)} size="sm">{statusLabel(gate.status, isZh)}</Tag>
                    <div><h3>{definition?.title ?? gate.gateId}</h3><p>{gate.detail}</p><small>{definition?.owner}</small></div>
                  </article>
                );
              })}
            </div>
          </section>
        </>
      ) : null}

      <div className="governance-grid">
        <section className="governance-panel governance-panel--status">
          <div className="section-heading"><h2>{t('governance.validationStatus')}</h2></div>
          {results?.validationStatus ? (
            <div className="validation-status">
              <Gauge size={38} weight="duotone" aria-hidden="true" />
              <div><StatusBadge status={results.validationStatus} /><p>{t('results.disclaimer')}</p></div>
            </div>
          ) : (
            <EmptyState title={t('common.unavailable')} body={t('governance.backendUnavailable')} icon={<ShieldCheck size={28} weight="duotone" />} />
          )}
        </section>

        <section className="governance-panel governance-panel--map">
          <div className="section-heading"><h2>{t('governance.humanAiMap')}</h2></div>
          <div className="decision-map">
            {decisionRows.map((row) => {
              const Icon = row.icon;
              return <div key={row.label}><Icon size={22} weight="duotone" aria-hidden="true" /><div><strong>{row.label}</strong><p>{row.value}</p></div></div>;
            })}
          </div>
        </section>
      </div>

      <div className="governance-grid governance-grid--second">
        <section className="governance-panel">
          <div className="section-heading"><h2>{t('governance.riskTitle')}</h2></div>
          <div className="risk-control-list">
            {riskRows.map((risk) => <div key={risk}><CheckCircle size={20} weight="fill" aria-hidden="true" /><p>{risk}</p></div>)}
          </div>
        </section>

        <section className="governance-panel">
          <div className="section-heading"><h2>{t('governance.versions')}</h2></div>
          {results && (Object.keys(results.modelVersions).length > 0 || Object.keys(results.dataVersions).length > 0) ? (
            <div className="version-groups">
              <div><h3>{t('governance.modelVersions')}</h3><dl className="definition-list definition-list--compact">{Object.entries(results.modelVersions).map(([key, value]) => <div key={key}><dt>{key}</dt><dd><code>{value}</code></dd></div>)}</dl></div>
              <div><h3>{t('governance.dataVersions')}</h3><dl className="definition-list definition-list--compact">{Object.entries(results.dataVersions).map(([key, value]) => <div key={key}><dt>{key}</dt><dd><code title={value}>{value.length > 24 ? value.slice(0, 24) : value}</code></dd></div>)}</dl></div>
            </div>
          ) : <p className="empty-inline">{t('governance.noVersions')}</p>}
        </section>
      </div>

      {results?.analysisDiagnostics ? (
        <section className="governance-panel governance-panel--run-diagnostics" aria-labelledby="run-diagnostics-heading">
          <div className="section-heading">
            <h2 id="run-diagnostics-heading">{isZh ? '本次实验的分析治理摘要' : 'Run-linked analysis governance'}</h2>
            <p>{isZh
              ? `预注册主要指标：${results.analysisDiagnostics.preregisteredPrimaryOutcome || '暂无数据'}。此处只汇总当前结果包返回的诊断状态。`
              : `Preregistered primary outcome: ${results.analysisDiagnostics.preregisteredPrimaryOutcome || 'not available'}. This summary reports only diagnostics attached to the current result bundle.`}</p>
          </div>
          <div className="governance-stat-grid governance-stat-grid--compact">
            <div><span>{isZh ? '负对照' : 'Negative control'}</span><strong>{statusLabel(results.analysisDiagnostics.negativeControl.status, isZh)}</strong></div>
            <div><span>{isZh ? '参数恢复检验' : 'Parameter restoration'}</span><strong>{statusLabel(results.analysisDiagnostics.parameterRestorationKnockout.status, isZh)}</strong></div>
            <div><span>{isZh ? '局部敏感性' : 'Local sensitivity'}</span><strong>{statusLabel(results.analysisDiagnostics.localSensitivity.status, isZh)}</strong></div>
            <div><span>{isZh ? 'Holm 拒绝数' : 'Holm rejections'}</span><strong>{results.analysisDiagnostics.multipleComparison.items.filter((item) => item.rejected).length} / {results.analysisDiagnostics.multipleComparison.items.length}</strong></div>
          </div>
          <Notice>{results.analysisDiagnostics.interpretationBoundary.replaceAll('_', ' ')}</Notice>
        </section>
      ) : null}

      <section className="governance-panel governance-panel--limitations">
        <div className="section-heading"><h2>{t('common.limitations')}</h2></div>
        {limitations && limitations.length > 0 ? (
          <div className="limitation-list">{limitations.map((limitation) => <div key={limitation}><Warning size={20} weight="fill" aria-hidden="true" /><p>{limitation}</p></div>)}</div>
        ) : <p className="empty-inline">{isZh ? '尚未加载某次实验的限制。全局验证和发布门禁仍按上方证据显示。' : 'No run-specific limitations are loaded. Global validation and release gates remain visible above.'}</p>}
      </section>

      <section className="license-panel">
        <FileLock size={24} weight="duotone" aria-hidden="true" />
        <div><strong>PolyForm Strict License 1.0.0</strong><p>{t('footer.license')}</p><p>{t('footer.copyright')}</p></div>
      </section>

      <Notice>{t('footer.disclaimer')}</Notice>
    </div>
  );
}
