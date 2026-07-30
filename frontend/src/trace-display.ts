import type { Language } from './i18n';
import { formatPriceTicks } from './utils/format';

export type TraceEventCategory =
  | 'fact'
  | 'observation'
  | 'belief'
  | 'intent'
  | 'risk'
  | 'order'
  | 'fill'
  | 'market'
  | 'metric'
  | 'stop';

interface TraceEventDefinition {
  category: TraceEventCategory;
  en: string;
  zh: string;
}

const TRACE_EVENT_CATALOG: Record<string, TraceEventDefinition> = {
  REGISTERED_INTERVENTION_APPLIED: { category: 'market', en: 'Registered intervention applied', zh: '唯一注册干预已应用' },
  SCENARIO_CONFIGURATION_APPLIED: { category: 'market', en: 'Scenario configuration applied', zh: '情景配置已应用' },
  FACT: { category: 'fact', en: 'Evidence became available', zh: '证据已可用' },
  EXTERNAL_FACT: { category: 'fact', en: 'External evidence became available', zh: '外部证据已可用' },
  FACT_ARRIVED: { category: 'fact', en: 'Evidence arrived', zh: '证据已到达' },
  CLARIFICATION_ARRIVED: { category: 'fact', en: 'Clarification arrived', zh: '澄清信息已到达' },
  OBSERVATION: { category: 'observation', en: 'Agent observation', zh: '智能体观察' },
  OBSERVATION_CREATED: { category: 'observation', en: 'Observation created', zh: '观察已生成' },
  BELIEF: { category: 'belief', en: 'Belief state', zh: '信念状态' },
  BELIEF_UPDATE: { category: 'belief', en: 'Belief updated', zh: '信念已更新' },
  BELIEF_UPDATED: { category: 'belief', en: 'Belief updated', zh: '信念已更新' },
  SOCIAL_PROPAGATION: { category: 'observation', en: 'Social signal propagated', zh: '社交信号已传播' },
  SOCIAL_PROPAGATED: { category: 'observation', en: 'Social signal propagated', zh: '社交信号已传播' },
  INTENT: { category: 'intent', en: 'Action intent', zh: '行动意图' },
  ACTION_PREFERENCE: { category: 'intent', en: 'Action preference', zh: '行动偏好' },
  ACTION_INTENT: { category: 'intent', en: 'Action intent created', zh: '行动意图已生成' },
  ACTION_INTENT_CREATED: { category: 'intent', en: 'Action intent created', zh: '行动意图已生成' },
  RISK: { category: 'risk', en: 'Risk control', zh: '风控检查' },
  RISK_CHECK: { category: 'risk', en: 'Risk check completed', zh: '风控检查已完成' },
  ORDER: { category: 'order', en: 'Order event', zh: '订单事件' },
  ORDER_SUBMITTED: { category: 'order', en: 'Agent order submitted', zh: '智能体订单已提交' },
  SYSTEM_ORDER_SUBMITTED: { category: 'order', en: 'System order submitted', zh: '系统订单已提交' },
  ORDER_ARRIVED: { category: 'order', en: 'Order arrived at the market', zh: '订单已到达市场' },
  AGENT_ORDER_ARRIVED: { category: 'order', en: 'Agent order arrived', zh: '智能体订单已到达' },
  ORDER_EXPIRED_BEFORE_ARRIVAL: { category: 'order', en: 'Order expired before arrival', zh: '订单到达前已过期' },
  ORDER_REJECTED_MARKET_HALTED: { category: 'risk', en: 'Order rejected during market halt', zh: '停牌期间订单被拒绝' },
  FILL: { category: 'fill', en: 'Trade fill', zh: '订单成交' },
  TRADE_EXECUTED: { category: 'fill', en: 'Trade executed', zh: '成交已执行' },
  MARKET: { category: 'market', en: 'Market state changed', zh: '市场状态已变化' },
  MARKET_STATE: { category: 'market', en: 'Market state', zh: '市场状态' },
  OPENING_AUCTION_STARTED: { category: 'market', en: 'Opening auction started', zh: '开盘集合竞价已开始' },
  OPENING_AUCTION_CLEARED: { category: 'market', en: 'Opening auction cleared', zh: '开盘集合竞价已撮合' },
  REOPEN_AUCTION_CLEARED: { category: 'market', en: 'Reopening auction cleared', zh: '复牌集合竞价已撮合' },
  VOLATILITY_HALT_TRIGGERED: { category: 'stop', en: 'Volatility halt triggered', zh: '波动停牌已触发' },
  VOLATILITY_HALT_ENDED: { category: 'stop', en: 'Volatility halt ended', zh: '波动停牌已结束' },
  STOP: { category: 'stop', en: 'Stop condition', zh: '停止条件' },
  STOP_LOSS: { category: 'stop', en: 'Stop-loss triggered', zh: '止损已触发' },
  METRIC: { category: 'metric', en: 'Metric captured', zh: '指标已记录' },
  METRICS_CAPTURED: { category: 'metric', en: 'Metrics captured', zh: '指标已记录' },
};

interface AgentDefinition {
  en: string;
  zh: string;
  descriptionEn: string;
  descriptionZh: string;
}

const AGENT_CATALOG: Record<string, AgentDefinition> = {
  NOISE: { en: 'Noise trader', zh: '噪声交易者', descriptionEn: 'Trades from bounded noise and sentiment signals under standard risk controls.', descriptionZh: '根据受限噪声与情绪信号交易，并受统一风控约束。' },
  VALUE: { en: 'Value trader', zh: '价值型交易者', descriptionEn: 'Responds to the simulated gap from its internal reference value.', descriptionZh: '根据模拟价格与内部参考价值的偏离作出反应。' },
  MOMENTUM: { en: 'Momentum trader', zh: '动量交易者', descriptionEn: 'Responds to short-horizon simulated price momentum.', descriptionZh: '根据短周期模拟价格动量作出反应。' },
  MEAN_REVERSION: { en: 'Mean-reversion trader', zh: '均值回归交易者', descriptionEn: 'Responds when simulated prices move away from a bounded reference.', descriptionZh: '在模拟价格偏离受限参考水平时作出反向反应。' },
  PASSIVE: { en: 'Passive fund', zh: '被动基金', descriptionEn: 'Executes scheduled benchmark-linked flow through the same market controls.', descriptionZh: '通过相同市场约束执行预定的基准关联资金流。' },
  INSTITUTIONAL: { en: 'Institutional execution', zh: '机构执行交易者', descriptionEn: 'Slices scheduled institutional flow across simulation steps.', descriptionZh: '将预定机构资金流拆分到多个仿真步骤执行。' },
  MARKET_MAKER: { en: 'Market maker', zh: '做市商', descriptionEn: 'Quotes both sides subject to inventory, capital, and price controls.', descriptionZh: '在库存、资本与价格约束下提供双边报价。' },
  ARBITRAGE: { en: 'Cross-signal arbitrageur', zh: '跨信号套利者', descriptionEn: 'Responds to bounded discrepancies between simulated signals.', descriptionZh: '根据模拟信号之间的受限差异作出反应。' },
  DELEVERAGING: { en: 'Deleveraging trader', zh: '去杠杆交易者', descriptionEn: 'Reduces exposure under adverse sentiment and margin pressure.', descriptionZh: '在不利情绪与保证金压力下减少风险敞口。' },
  STOP_LOSS: { en: 'Stop-loss trader', zh: '止损交易者', descriptionEn: 'Submits bounded sell pressure after deterministic stop thresholds trigger.', descriptionZh: '在确定性止损阈值触发后提交受限卖出压力。' },
  LIQUIDATION: { en: 'Forced-liquidation trader', zh: '强制平仓交易者', descriptionEn: 'Executes forced exposure reduction under ledger and margin rules.', descriptionZh: '依据账本与保证金规则执行强制减仓。' },
};

const PAYLOAD_FIELD_CATALOG: Record<string, { en: string; zh: string }> = {
  source: { en: 'Signal source', zh: '信号来源' },
  side: { en: 'Order side', zh: '订单方向' },
  requestedQuantity: { en: 'Requested quantity', zh: '请求数量' },
  approvedQuantity: { en: 'Risk-approved quantity', zh: '风控批准数量' },
  proposedQuantity: { en: 'Proposed quantity', zh: '建议数量' },
  quantity: { en: 'Quantity', zh: '数量' },
  cumulativeFilledQuantity: { en: 'Cumulative filled quantity', zh: '累计成交数量' },
  remainingQuantity: { en: 'Remaining quantity', zh: '剩余数量' },
  limitPriceTicks: { en: 'Synthetic limit price', zh: '合成限价' },
  priceTicks: { en: 'Synthetic trade price', zh: '合成成交价' },
  averagePriceTicks: { en: 'Average synthetic price', zh: '合成成交均价' },
  reasonCode: { en: 'Reason', zh: '原因' },
  status: { en: 'Status', zh: '状态' },
  tradeId: { en: 'Trade ID', zh: '成交 ID' },
  orderId: { en: 'Order ID', zh: '订单 ID' },
  aggressiveSide: { en: 'Aggressive side', zh: '主动成交方向' },
  makerAgentId: { en: 'Maker agent ID', zh: '挂单方智能体 ID' },
  takerAgentId: { en: 'Taker agent ID', zh: '吃单方智能体 ID' },
  agentId: { en: 'Agent ID', zh: '智能体 ID' },
  agentType: { en: 'Agent type', zh: '智能体类型' },
  confidence: { en: 'Confidence', zh: '置信度' },
  uncertainty: { en: 'Uncertainty', zh: '不确定性' },
  metricContribution: { en: 'Metric contribution', zh: '指标贡献' },
  parentTraceId: { en: 'Parent trace ID', zh: '父链路 ID' },
};

function normalizeCode(value: string): string {
  return value
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .replace(/[^A-Za-z0-9]+/g, '_')
    .replace(/^_|_$/g, '')
    .toUpperCase();
}

export function traceEventDisplay(
  code: string | undefined,
  language: Language,
): { label: string; category: TraceEventCategory; known: boolean } {
  if (!code) {
    return {
      label: language === 'zh-CN' ? '事件详情' : 'Event details',
      category: 'market',
      known: false,
    };
  }
  const normalized = normalizeCode(code);
  const definition = TRACE_EVENT_CATALOG[normalized];
  if (!definition) {
    return {
      label: language === 'zh-CN' ? `未知事件（${code}）` : `Unknown event (${code})`,
      category: 'market',
      known: false,
    };
  }
  return {
    label: language === 'zh-CN' ? definition.zh : definition.en,
    category: definition.category,
    known: true,
  };
}

export function traceAgentDisplay(
  code: string | undefined,
  language: Language,
): { name: string; description: string; known: boolean } {
  if (!code) {
    return {
      name: language === 'zh-CN' ? '智能体类型未报告' : 'Agent type not reported',
      description: language === 'zh-CN' ? '后端未提供智能体角色代码。' : 'The backend did not provide an agent role code.',
      known: false,
    };
  }
  let normalized = normalizeCode(code)
    .replace(/_(TRADER|AGENT)$/, '')
    .replace(/^FORCED_LIQUIDATION$/, 'LIQUIDATION')
    .replace(/^INSTITUTIONAL_EXECUTION$/, 'INSTITUTIONAL');
  if (normalized === 'FORCEDLIQUIDATION') normalized = 'LIQUIDATION';
  if (normalized === 'INSTITUTIONALEXECUTION') normalized = 'INSTITUTIONAL';
  const definition = AGENT_CATALOG[normalized];
  if (!definition) {
    return {
      name: language === 'zh-CN' ? `其他智能体（${code}）` : `Other agent (${code})`,
      description: language === 'zh-CN' ? '当前目录未收录该角色；原始代码保留用于审计。' : 'This role is not in the current catalog; its code is retained for audit.',
      known: false,
    };
  }
  return {
    name: language === 'zh-CN' ? definition.zh : definition.en,
    description: language === 'zh-CN' ? definition.descriptionZh : definition.descriptionEn,
    known: true,
  };
}

export function tracePayloadFieldDisplay(
  key: string,
  language: Language,
): { label: string; known: boolean } {
  const definition = PAYLOAD_FIELD_CATALOG[key];
  if (definition) {
    return { label: language === 'zh-CN' ? definition.zh : definition.en, known: true };
  }
  return {
    label: language === 'zh-CN' ? `其他字段（${key}）` : `Other field (${key})`,
    known: false,
  };
}

export function traceScenarioLabel(value: string, language: Language): string {
  const normalized = normalizeCode(value);
  if (normalized === 'BASELINE') return language === 'zh-CN' ? '基准组' : 'Baseline';
  if (normalized === 'INTERVENTION') return language === 'zh-CN' ? '干预组' : 'Intervention';
  return language === 'zh-CN' ? `其他场景（${value}）` : `Other scenario (${value})`;
}

export function tracePhaseLabel(value: string | undefined, language: Language): string {
  if (!value) return language === 'zh-CN' ? '阶段未报告' : 'Phase not reported';
  const labels: Record<string, { en: string; zh: string }> = {
    EVIDENCE: { en: 'Evidence', zh: '证据' },
    OBSERVATION: { en: 'Observation', zh: '观察' },
    BELIEF: { en: 'Belief', zh: '信念' },
    INTENT: { en: 'Intent', zh: '意图' },
    RISK: { en: 'Risk control', zh: '风控' },
    ORDER: { en: 'Order', zh: '订单' },
    TRADE: { en: 'Trade', zh: '成交' },
    MECHANISM: { en: 'Market mechanism', zh: '市场机制' },
  };
  const normalized = normalizeCode(value);
  const label = labels[normalized];
  if (label) return language === 'zh-CN' ? label.zh : label.en;
  return language === 'zh-CN' ? `其他阶段（${value}）` : `Other phase (${value})`;
}

export function traceSourceLayerLabel(value: string | undefined, language: Language): string {
  if (!value) return language === 'zh-CN' ? '来源层未报告' : 'Source layer not reported';
  const labels: Record<string, { en: string; zh: string }> = {
    REGISTERED_INTERVENTION: { en: 'Registered intervention', zh: '唯一注册干预' },
    EVENT_PACK_TRIGGER: { en: 'Event Pack trigger', zh: 'Event Pack 触发机制' },
    SCENARIO_MECHANISM: { en: 'Scenario mechanism', zh: '场景固有机制' },
    AGENT_BEHAVIOR: { en: 'Agent behavior', zh: '智能体行为' },
    DETERMINISTIC_MARKET_MECHANISM: {
      en: 'Deterministic market mechanism',
      zh: '确定性市场机制',
    },
  };
  const normalized = normalizeCode(value);
  const label = labels[normalized];
  if (label) return language === 'zh-CN' ? label.zh : label.en;
  return language === 'zh-CN' ? `其他来源层（${value}）` : `Other source layer (${value})`;
}

export function traceRiskDecisionLabel(value: string | undefined, language: Language): string {
  const labels: Record<string, { en: string; zh: string }> = {
    ACCEPT: { en: 'Accepted', zh: '已批准' },
    MODIFY: { en: 'Modified by risk control', zh: '风控调整后批准' },
    REJECT: { en: 'Rejected by risk control', zh: '已被风控拒绝' },
  };
  const normalized = normalizeCode(value ?? '');
  const label = labels[normalized];
  if (label) return language === 'zh-CN' ? label.zh : label.en;
  return value
    ? language === 'zh-CN' ? `其他风控结论（${value}）` : `Other risk decision (${value})`
    : language === 'zh-CN' ? '未报告' : 'Not reported';
}

export function traceOrderStatusLabel(value: string | undefined, language: Language): string {
  if (!value) return language === 'zh-CN' ? '未报告' : 'Not reported';
  const normalized = normalizeCode(value);
  const exactLabels: Record<string, { en: string; zh: string }> = {
    FILLED: { en: 'Fully filled', zh: '全部成交' },
    PARTIALLY_FILLED: { en: 'Partially filled', zh: '部分成交' },
    REJECTED: { en: 'Rejected', zh: '已拒绝' },
    RESTING: { en: 'Resting', zh: '挂单中' },
    RESTING_AT_SIMULATION_END: {
      en: 'Resting at simulation end',
      zh: '仿真结束时仍在挂单',
    },
    PARTIALLY_FILLED_AT_SIMULATION_END: {
      en: 'Partially filled at simulation end',
      zh: '仿真结束时部分成交',
    },
  };
  const exact = exactLabels[normalized];
  if (exact) return language === 'zh-CN' ? exact.zh : exact.en;
  if (normalized.startsWith('PARTIALLY_FILLED_')) {
    return language === 'zh-CN' ? `部分成交（${value}）` : `Partially filled (${value})`;
  }
  if (normalized.startsWith('UNFILLED_')) {
    return language === 'zh-CN' ? `未成交（${value}）` : `Unfilled (${value})`;
  }
  return language === 'zh-CN' ? `其他订单状态（${value}）` : `Other order status (${value})`;
}

export function tracePayloadValueDisplay(
  key: string,
  value: unknown,
  language: Language,
  tickSize?: number,
): string {
  if (key === 'agentType' && typeof value === 'string') {
    return traceAgentDisplay(value, language).name;
  }
  if (['side', 'aggressiveSide'].includes(key) && typeof value === 'string') {
    const normalized = normalizeCode(value);
    if (normalized === 'BUY') return language === 'zh-CN' ? '买入' : 'Buy';
    if (normalized === 'SELL') return language === 'zh-CN' ? '卖出' : 'Sell';
    return language === 'zh-CN' ? `其他方向（${value}）` : `Other side (${value})`;
  }
  if (key === 'source' && typeof value === 'string') {
    const labels: Record<string, { en: string; zh: string }> = {
      LLM_BELIEF_SIGNAL: { en: 'Bounded model belief signal', zh: '受限模型信念信号' },
      RULE_FALLBACK_BELIEF_SIGNAL: { en: 'Deterministic fallback belief signal', zh: '确定性回退信念信号' },
      RULE_AGENT: { en: 'Deterministic rule agent', zh: '确定性规则智能体' },
    };
    const label = labels[normalizeCode(value)];
    if (label) return language === 'zh-CN' ? label.zh : label.en;
    return language === 'zh-CN' ? `其他信号来源（${value}）` : `Other signal source (${value})`;
  }
  if (['limitPriceTicks', 'priceTicks', 'averagePriceTicks'].includes(key) && typeof value === 'number') {
    const price = formatPriceTicks(value, tickSize, language);
    if (tickSize !== undefined && Number.isFinite(tickSize) && tickSize > 0) {
      return language === 'zh-CN'
        ? `${price}（原始：${new Intl.NumberFormat(language).format(value)} tick）`
        : `${price} (raw: ${new Intl.NumberFormat(language).format(value)} ticks)`;
    }
    return language === 'zh-CN'
      ? `价格换算不可用（原始：${new Intl.NumberFormat(language).format(value)} tick）`
      : `Price conversion unavailable (raw: ${new Intl.NumberFormat(language).format(value)} ticks)`;
  }
  if (typeof value === 'boolean') {
    return value ? language === 'zh-CN' ? '是' : 'Yes' : language === 'zh-CN' ? '否' : 'No';
  }
  if (typeof value === 'string' || typeof value === 'number') return String(value);
  return JSON.stringify(value);
}
