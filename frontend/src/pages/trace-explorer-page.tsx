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
import { useWorkflow } from '../state/workflow-context';
import { formatMetricValue, safeDate } from '../utils/format';

function traceKindLabel(kind: string | undefined, t: ReturnType<typeof useI18n>['t']): string {
  if (!kind) return t('common.details');
  const keys = {
    FACT: 'trace.kind.fact',
    EXTERNAL_FACT: 'trace.kind.fact',
    FACT_ARRIVED: 'trace.kind.fact',
    CLARIFICATION_ARRIVED: 'trace.kind.fact',
    OBSERVATION: 'trace.kind.observation',
    OBSERVATION_CREATED: 'trace.kind.observation',
    BELIEF: 'trace.kind.belief',
    BELIEF_UPDATE: 'trace.kind.belief',
    BELIEF_UPDATED: 'trace.kind.belief',
    SOCIAL: 'trace.kind.social',
    SOCIAL_PROPAGATION: 'trace.kind.social',
    SOCIAL_PROPAGATED: 'trace.kind.social',
    INTENT: 'trace.kind.intent',
    ACTION_PREFERENCE: 'trace.kind.intent',
    ACTION_INTENT: 'trace.kind.intent',
    RISK: 'trace.kind.risk',
    RISK_CHECK: 'trace.kind.risk',
    ORDER: 'trace.kind.order',
    ORDER_SUBMITTED: 'trace.kind.order',
    SYSTEM_ORDER_SUBMITTED: 'trace.kind.order',
    FILL: 'trace.kind.fill',
    TRADE_EXECUTED: 'trace.kind.fill',
    MARKET: 'trace.kind.market',
    MARKET_STATE: 'trace.kind.market',
    STOP: 'trace.kind.stop',
    STOP_LOSS: 'trace.kind.stop',
    METRIC: 'trace.kind.metric',
  } as const;
  const key = keys[kind.toUpperCase() as keyof typeof keys];
  return key ? t(key) : kind.replaceAll('_', ' ').toLowerCase();
}

function traceIcon(kind: string | undefined): ReactNode {
  switch (kind?.toUpperCase()) {
    case 'FACT':
    case 'EXTERNAL_FACT':
      return <FileText size={20} />;
    case 'BELIEF':
    case 'BELIEF_UPDATE':
    case 'BELIEF_UPDATED':
      return <Brain size={20} />;
    case 'ORDER':
    case 'ORDER_SUBMITTED':
    case 'FILL':
    case 'TRADE_EXECUTED':
      return <ShoppingCart size={20} />;
    case 'RISK':
    case 'RISK_CHECK':
      return <CheckCircle size={20} />;
    case 'STOP':
    case 'STOP_LOSS':
      return <Warning size={20} />;
    default:
      return <FlowArrow size={20} />;
  }
}

function tracePayloadValue(
  key: string,
  value: unknown,
  language: 'en' | 'zh-CN',
): string {
  if (key === 'source' && typeof value === 'string') {
    const labels: Record<string, { en: string; zh: string }> = {
      LLM_BELIEF_SIGNAL: { en: 'LLM belief signal', zh: 'LLM 信念信号' },
      RULE_FALLBACK_BELIEF_SIGNAL: {
        en: 'Deterministic rule-fallback belief signal',
        zh: '确定性规则回退信念信号',
      },
      RULE_AGENT: { en: 'Deterministic rule agent', zh: '确定性规则智能体' },
    };
    const label = labels[value];
    if (label) return language === 'zh-CN' ? label.zh : label.en;
  }
  if (typeof value === 'boolean') {
    return value
      ? language === 'zh-CN' ? '是' : 'Yes'
      : language === 'zh-CN' ? '否' : 'No';
  }
  return typeof value === 'string' ? value : JSON.stringify(value);
}

export function TraceExplorerPage() {
  const { language, t } = useI18n();
  const { results } = useWorkflow();
  const [selectedNode, setSelectedNode] = useState<TraceNode>();
  const [scenarioFilter, setScenarioFilter] = useState('all');
  const [kindFilter, setKindFilter] = useState('all');

  const scenarios = useMemo(() => [...new Set((results?.traces ?? []).map((node) => node.scenario).filter((item): item is string => Boolean(item)))], [results?.traces]);
  const kinds = useMemo(() => [...new Set((results?.traces ?? []).map((node) => node.kind).filter((item): item is string => Boolean(item)))].sort(), [results?.traces]);
  const filteredTraces = useMemo(() => (results?.traces ?? []).filter((node) => (
    (scenarioFilter === 'all' || node.scenario === scenarioFilter)
    && (kindFilter === 'all' || node.kind === kindFilter)
  )), [kindFilter, results?.traces, scenarioFilter]);

  useEffect(() => {
    setSelectedNode(filteredTraces[0]);
  }, [filteredTraces]);

  useEffect(() => {
    setScenarioFilter('all');
    setKindFilter('all');
  }, [results?.experimentId]);

  return (
    <div className="page page--trace">
      <PageHeader title={t('trace.title')} subtitle={t('trace.subtitle')} />
      {!results || results.traces.length === 0 ? (
        <EmptyState title={t('trace.selectTitle')} body={t('trace.selectBody')} icon={<FlowArrow size={28} weight="duotone" />} />
      ) : (
        <div className="trace-layout">
          <section className="trace-timeline" aria-labelledby="trace-timeline-heading">
            <div className="section-heading"><h2 id="trace-timeline-heading">{t('trace.timeline')}</h2><p>{language === 'zh-CN' ? '按场景和事件类型筛选，不改变原始追踪。' : 'Filter by scenario and event kind without changing the underlying trace.'}</p></div>
            <div className="trace-filters">
              <Select id="trace-scenario-filter" labelText={language === 'zh-CN' ? '场景' : 'Scenario'} value={scenarioFilter} onChange={(event) => setScenarioFilter(event.target.value)}>
                <SelectItem value="all" text={language === 'zh-CN' ? '全部场景' : 'All scenarios'} />
                {scenarios.map((scenario) => <SelectItem key={scenario} value={scenario} text={scenario} />)}
              </Select>
              <Select id="trace-kind-filter" labelText={language === 'zh-CN' ? '事件类型' : 'Event kind'} value={kindFilter} onChange={(event) => setKindFilter(event.target.value)}>
                <SelectItem value="all" text={language === 'zh-CN' ? '全部类型' : 'All kinds'} />
                {kinds.map((kind) => <SelectItem key={kind} value={kind} text={traceKindLabel(kind, t)} />)}
              </Select>
            </div>
            <ol>
              {filteredTraces.map((node, index) => (
                <li key={node.id}>
                  <button
                    type="button"
                    className={selectedNode?.id === node.id ? 'is-active' : ''}
                    onClick={() => setSelectedNode(node)}
                    aria-current={selectedNode?.id === node.id ? 'step' : undefined}
                  >
                    <span className="trace-node__icon" aria-hidden="true">{traceIcon(node.kind)}</span>
                    <span className="trace-node__body">
                      <small>{node.time ? safeDate(node.time, language) : node.step !== undefined ? `${t('chart.step')} ${node.step}` : `${index + 1}`}</small>
                      <strong>{traceKindLabel(node.kind, t)}</strong>
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
                  <Tag type="blue" size="sm">{traceKindLabel(selectedNode.kind, t)}</Tag>
                  <h2>{traceKindLabel(selectedNode.kind, t)}</h2>
                  {selectedNode.summary ? <p>{language === 'zh-CN' ? selectedNode.summaryZh ?? selectedNode.summary : selectedNode.summary}</p> : null}
                </div>
                <dl className="definition-list">
                  {selectedNode.time ? <div><dt>{t('pack.pointInTime')}</dt><dd>{safeDate(selectedNode.time, language)}</dd></div> : null}
                  {selectedNode.scenario ? <div><dt>{language === 'zh-CN' ? '场景' : 'Scenario'}</dt><dd>{selectedNode.scenario}</dd></div> : null}
                  {selectedNode.seed !== undefined ? <div><dt>{t('chart.seed')}</dt><dd>{selectedNode.seed}</dd></div> : null}
                  {selectedNode.parentId ? <div><dt>{language === 'zh-CN' ? '父节点' : 'Parent node'}</dt><dd><code>{selectedNode.parentId}</code></dd></div> : null}
                  {selectedNode.sourceId ? <div><dt>{t('common.sourceId')}</dt><dd><code>{selectedNode.sourceId}</code></dd></div> : null}
                  {selectedNode.agentId ? <div><dt>{t('common.agentId')}</dt><dd><code>{selectedNode.agentId}</code></dd></div> : null}
                  {selectedNode.orderId ? <div><dt>{t('common.orderId')}</dt><dd><code>{selectedNode.orderId}</code></dd></div> : null}
                  {selectedNode.metricContribution !== undefined ? (
                    <div><dt>{t('trace.metricContribution')}</dt><dd>{formatMetricValue(selectedNode.metricContribution, undefined, language)}</dd></div>
                  ) : null}
                  {selectedNode.methodNote ? <div><dt>{t('common.method')}</dt><dd>{selectedNode.methodNote}</dd></div> : null}
                </dl>
                {selectedNode.payload && Object.keys(selectedNode.payload).length > 0 ? (
                  <details className="trace-payload">
                    <summary>{language === 'zh-CN' ? '查看经过清理的事件负载' : 'Inspect sanitized event payload'}</summary>
                    <dl className="definition-list definition-list--compact">
                      {Object.entries(selectedNode.payload).map(([key, value]) => (
                        <div key={key}><dt>{key}</dt><dd><code>{tracePayloadValue(key, value, language)}</code></dd></div>
                      ))}
                    </dl>
                  </details>
                ) : null}
                <Notice>{t('trace.methodWarning')}</Notice>
              </>
            ) : null}
          </section>
        </div>
      )}
    </div>
  );
}
