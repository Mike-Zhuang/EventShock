import { Select, SelectItem, Tag } from '@carbon/react';
import {
  ArrowRight,
  Brain,
  CheckCircle,
  FileText,
  FlowArrow,
  ShoppingCart,
  Warning,
} from '@phosphor-icons/react';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import type { TraceNode } from '../api/types';
import { EmptyState, Notice, PageHeader } from '../components/common';
import { useI18n } from '../i18n';
import { getPageGuide } from '../page-guidance';
import { useWorkflow } from '../state/workflow-context';
import {
  traceAgentDisplay,
  traceEventDisplay,
  traceOrderStatusLabel,
  tracePayloadFieldDisplay,
  tracePayloadValueDisplay,
  tracePhaseLabel,
  traceRiskDecisionLabel,
  traceScenarioLabel,
  traceSourceLayerLabel,
} from '../trace-display';
import { formatMetricValue, isoUtcDate, safeDate } from '../utils/format';

function traceIcon(kind: string | undefined): ReactNode {
  switch (traceEventDisplay(kind, 'en').category) {
    case 'fact':
      return <FileText size={20} />;
    case 'belief':
      return <Brain size={20} />;
    case 'order':
    case 'fill':
      return <ShoppingCart size={20} />;
    case 'risk':
      return <CheckCircle size={20} />;
    case 'stop':
      return <Warning size={20} />;
    default:
      return <FlowArrow size={20} />;
  }
}

export function TraceExplorerPage() {
  const { language, t } = useI18n();
  const { activeExperiment, results } = useWorkflow();
  const [selectedNode, setSelectedNode] = useState<TraceNode>();
  const [scenarioFilter, setScenarioFilter] = useState('all');
  const [kindFilter, setKindFilter] = useState('all');

  const scenarios = useMemo(() => [...new Set((results?.traces ?? []).map((node) => node.scenario).filter((item): item is string => Boolean(item)))], [results?.traces]);
  const kinds = useMemo(() => [...new Set((results?.traces ?? []).map((node) => node.kind).filter((item): item is string => Boolean(item)))].sort(), [results?.traces]);
  const filteredTraces = useMemo(() => (results?.traces ?? []).filter((node) => (
    (scenarioFilter === 'all' || node.scenario === scenarioFilter)
    && (kindFilter === 'all' || node.kind === kindFilter)
  )).sort((left, right) => {
    const scenarioOrder = (scenario: string | undefined) => (
      scenario?.toLowerCase() === 'baseline' ? 0
        : scenario?.toLowerCase() === 'intervention' ? 1 : 2
    );
    return scenarioOrder(left.scenario) - scenarioOrder(right.scenario)
      || (left.globalSequence ?? Number.MAX_SAFE_INTEGER)
        - (right.globalSequence ?? Number.MAX_SAFE_INTEGER)
      || (left.step ?? Number.MAX_SAFE_INTEGER) - (right.step ?? Number.MAX_SAFE_INTEGER)
      || (left.phaseSequence ?? Number.MAX_SAFE_INTEGER)
        - (right.phaseSequence ?? Number.MAX_SAFE_INTEGER)
      || left.id.localeCompare(right.id);
  }), [kindFilter, results?.traces, scenarioFilter]);
  const orderSummaries = results?.orderExecutionSummary ?? [];
  const tickSize = activeExperiment?.scenario?.market?.tickSize;

  useEffect(() => {
    setSelectedNode(filteredTraces[0]);
  }, [filteredTraces]);

  useEffect(() => {
    setScenarioFilter('all');
    setKindFilter('all');
  }, [results?.experimentId]);

  return (
    <div className="page page--trace">
      <PageHeader title={t('trace.title')} subtitle={t('trace.subtitle')} guide={getPageGuide('trace', language)} />
      {!results || results.traces.length === 0 ? (
        <section className="trace-timeline" aria-labelledby="trace-timeline-heading">
          <div className="section-heading">
            <h2 id="trace-timeline-heading">{t('trace.timeline')}</h2>
            <p>{language === 'zh-CN'
              ? '当前实验没有可用链路；目标仍保留，便于深链明确说明空状态。'
              : 'This experiment has no available trace. The stable target remains so deep links can explain the empty state.'}</p>
          </div>
          <EmptyState title={t('trace.selectTitle')} body={t('trace.selectBody')} icon={<FlowArrow size={28} weight="duotone" />} />
        </section>
      ) : (
        <div className="trace-layout">
          <section className="trace-timeline" aria-labelledby="trace-timeline-heading">
            <div className="section-heading"><h2 id="trace-timeline-heading">{t('trace.timeline')}</h2><p>{language === 'zh-CN' ? '按场景和事件类型筛选，不改变原始追踪。' : 'Filter by scenario and event kind without changing the underlying trace.'}</p></div>
            <div className="trace-filters">
              <Select id="trace-scenario-filter" labelText={language === 'zh-CN' ? '场景' : 'Scenario'} value={scenarioFilter} onChange={(event) => setScenarioFilter(event.target.value)}>
                <SelectItem value="all" text={language === 'zh-CN' ? '全部场景' : 'All scenarios'} />
                {scenarios.map((scenario) => <SelectItem key={scenario} value={scenario} text={traceScenarioLabel(scenario, language)} />)}
              </Select>
              <Select id="trace-kind-filter" labelText={language === 'zh-CN' ? '事件类型' : 'Event kind'} value={kindFilter} onChange={(event) => setKindFilter(event.target.value)}>
                <SelectItem value="all" text={language === 'zh-CN' ? '全部类型' : 'All kinds'} />
                {kinds.map((kind) => <SelectItem key={kind} value={kind} text={traceEventDisplay(kind, language).label} />)}
              </Select>
            </div>
            <ol>
              {filteredTraces.map((node, index) => (
                <li key={node.id}>
                  <button
                    type="button"
                    className={[
                      selectedNode?.id === node.id ? 'is-active' : '',
                      node.isInterventionDifference ? 'is-intervention-difference' : '',
                    ].filter(Boolean).join(' ')}
                    onClick={() => setSelectedNode(node)}
                    aria-current={selectedNode?.id === node.id ? 'step' : undefined}
                  >
                    <span className="trace-node__icon" aria-hidden="true">{traceIcon(node.kind)}</span>
                    <span className="trace-node__body">
                      <small>
                        {node.globalSequence !== undefined ? `#${node.globalSequence} · ` : ''}
                        {node.time ? safeDate(node.time, language) : node.step !== undefined ? `${t('chart.step')} ${node.step}` : `${index + 1}`}
                        {node.phase ? ` · ${tracePhaseLabel(node.phase, language)} ${node.phaseSequence ?? ''}` : ''}
                      </small>
                      <strong>{traceEventDisplay(node.kind, language).label}</strong>
                      {node.sourceLayer ? (
                        <small>
                          {traceSourceLayerLabel(node.sourceLayer, language)}
                          {node.isInterventionDifference
                            ? language === 'zh-CN' ? ' · 与基准不同' : ' · differs from baseline'
                            : ''}
                        </small>
                      ) : null}
                      <span>{language === 'zh-CN' ? node.summaryZh ?? node.summary ?? t('common.noData') : node.summary ?? t('common.noData')}</span>
                    </span>
                    <ArrowRight size={17} aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ol>
          </section>

          <section className="trace-detail" aria-live="polite">
            {selectedNode ? (
              <>
                <div className="trace-detail__heading">
                  <Tag type="blue" size="sm">{traceEventDisplay(selectedNode.kind, language).label}</Tag>
                  {selectedNode.sourceLayer ? (
                    <Tag type="gray" size="sm">{traceSourceLayerLabel(selectedNode.sourceLayer, language)}</Tag>
                  ) : null}
                  {selectedNode.isInterventionDifference ? (
                    <Tag type="warm-gray" size="sm">
                      {language === 'zh-CN' ? '干预变化' : 'Intervention difference'}
                    </Tag>
                  ) : null}
                  <h2>{traceEventDisplay(selectedNode.kind, language).label}</h2>
                  {selectedNode.summary ? <p>{language === 'zh-CN' ? selectedNode.summaryZh ?? selectedNode.summary : selectedNode.summary}</p> : null}
                </div>
                <dl className="definition-list">
                  {selectedNode.globalSequence !== undefined ? <div><dt>{language === 'zh-CN' ? '全局序号' : 'Global sequence'}</dt><dd>{selectedNode.globalSequence}</dd></div> : null}
                  {selectedNode.step !== undefined ? <div><dt>{t('chart.step')}</dt><dd>{selectedNode.step}</dd></div> : null}
                  {selectedNode.phase ? <div><dt>{language === 'zh-CN' ? '步骤内阶段' : 'Within-step phase'}</dt><dd>{tracePhaseLabel(selectedNode.phase, language)}{selectedNode.phaseSequence !== undefined ? ` · ${language === 'zh-CN' ? '阶段序号' : 'phase sequence'} ${selectedNode.phaseSequence}` : ''}</dd></div> : null}
                  {selectedNode.time ? <div><dt>{t('pack.pointInTime')}</dt><dd>{safeDate(selectedNode.time, language)}</dd></div> : null}
                  {selectedNode.scenario ? <div><dt>{language === 'zh-CN' ? '场景' : 'Scenario'}</dt><dd>{traceScenarioLabel(selectedNode.scenario, language)}</dd></div> : null}
                  {selectedNode.seed !== undefined ? <div><dt>{t('chart.seed')}</dt><dd>{selectedNode.seed}</dd></div> : null}
                  {selectedNode.parentId ? <div><dt>{language === 'zh-CN' ? '父节点' : 'Parent node'}</dt><dd><code>{selectedNode.parentId}</code></dd></div> : null}
                  {selectedNode.sourceId ? <div><dt>{t('common.sourceId')}</dt><dd><code>{selectedNode.sourceId}</code></dd></div> : null}
                  {selectedNode.agentId ? (
                    <div>
                      <dt>{t('common.agentId')}</dt>
                      <dd>
                        <code>{selectedNode.agentId}</code>
                        {typeof selectedNode.payload?.agentType === 'string' ? (
                          <span title={traceAgentDisplay(selectedNode.payload.agentType, language).description}>
                            {traceAgentDisplay(selectedNode.payload.agentType, language).name}
                          </span>
                        ) : null}
                      </dd>
                    </div>
                  ) : null}
                  {selectedNode.orderId ? <div><dt>{t('common.orderId')}</dt><dd><code>{selectedNode.orderId}</code></dd></div> : null}
                  {selectedNode.metricContribution !== undefined ? (
                    <div><dt>{t('trace.metricContribution')}</dt><dd>{formatMetricValue(selectedNode.metricContribution, undefined, language)}</dd></div>
                  ) : null}
                  {selectedNode.methodNote ? <div><dt>{t('common.method')}</dt><dd>{selectedNode.methodNote}</dd></div> : null}
                </dl>
                {selectedNode.time
                  || (selectedNode.payload && Object.keys(selectedNode.payload).length > 0) ? (
                  <details className="trace-payload">
                    <summary>{language === 'zh-CN' ? '技术详情' : 'Technical details'}</summary>
                    <dl className="definition-list definition-list--compact">
                      {selectedNode.time ? (
                        <div>
                          <dt>{language === 'zh-CN' ? '事件时间（UTC）' : 'Event time (UTC)'}</dt>
                          <dd><code>{isoUtcDate(selectedNode.time, language)}</code></dd>
                        </div>
                      ) : null}
                      {Object.entries(selectedNode.payload ?? {}).map(([key, value]) => {
                        const field = tracePayloadFieldDisplay(key, language);
                        return (
                          <div key={key}>
                            <dt title={field.known ? undefined : key}>{field.label}</dt>
                            <dd>
                              <code>{tracePayloadValueDisplay(key, value, language, tickSize)}</code>
                            </dd>
                          </div>
                        );
                      })}
                    </dl>
                  </details>
                ) : null}
                <Notice>{t('trace.methodWarning')}</Notice>
              </>
            ) : null}
          </section>
        </div>
      )}
      {orderSummaries.length > 0 ? (
        <section className="trace-order-summary" aria-labelledby="trace-order-summary-heading">
          <div className="section-heading">
            <h2 id="trace-order-summary-heading">
              {language === 'zh-CN' ? '代表路径订单执行汇总' : 'Representative-path order execution'}
            </h2>
            <p>
              {language === 'zh-CN'
                ? '同一订单聚合显示请求量、风控批准量、累计成交、剩余数量、成交均价与最终状态。'
                : 'Each order combines requested, approved, filled, remaining, VWAP, and final-status evidence.'}
            </p>
          </div>
          <div className="result-table-wrap">
            <table className="result-table">
              <thead>
                <tr>
                  <th>{language === 'zh-CN' ? '顺序 / 场景' : 'Sequence / scenario'}</th>
                  <th>{language === 'zh-CN' ? '订单' : 'Order'}</th>
                  <th>{language === 'zh-CN' ? '方向' : 'Side'}</th>
                  <th>{language === 'zh-CN' ? '请求 / 批准' : 'Requested / approved'}</th>
                  <th>{language === 'zh-CN' ? '累计成交 / 剩余' : 'Filled / remaining'}</th>
                  <th>{language === 'zh-CN' ? '均价 / 笔数' : 'VWAP / fills'}</th>
                  <th>{language === 'zh-CN' ? '风控 / 最终状态' : 'Risk / final status'}</th>
                </tr>
              </thead>
              <tbody>
                {orderSummaries.map((order) => (
                  <tr
                    key={`${order.scenario ?? 'unknown'}-${order.orderId}`}
                    className={order.isInterventionDifference ? 'is-intervention-difference' : undefined}
                  >
                    <td>
                      #{order.submissionSequence ?? '—'} · {order.scenario
                        ? traceScenarioLabel(order.scenario, language)
                        : t('common.unavailable')}
                      {order.isInterventionDifference
                        ? language === 'zh-CN' ? ' · 干预变化' : ' · intervention difference'
                        : ''}
                    </td>
                    <td><code>{order.orderId}</code></td>
                    <td>{tracePayloadValueDisplay('side', order.side, language)}</td>
                    <td>{order.requestedQuantity ?? '—'} / {order.approvedQuantity ?? '—'}</td>
                    <td>{order.cumulativeFilledQuantity ?? '—'} / {order.remainingQuantity ?? '—'}</td>
                    <td>
                      {order.vwapPrice !== undefined
                        ? new Intl.NumberFormat(language, { maximumFractionDigits: 4 }).format(order.vwapPrice)
                        : '—'} / {order.fillCount ?? 0}
                    </td>
                    <td>
                      {traceRiskDecisionLabel(order.riskDecision, language)}
                      {' · '}
                      {traceOrderStatusLabel(order.finalStatus, language)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}
