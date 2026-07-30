import type { Language } from './i18n';

interface ImpactChannelDefinition {
  id: string;
  name: { en: string; 'zh-CN': string };
  description: { en: string; 'zh-CN': string };
  example: { en: string; 'zh-CN': string };
  evidenceType: { en: string; 'zh-CN': string };
  simulatorParameter: string;
  unselectedMeaning: { en: string; 'zh-CN': string };
}

export const IMPACT_CHANNEL_DEFINITIONS = [
  {
    id: 'belief',
    name: { en: 'Belief update', 'zh-CN': '信念更新' },
    description: {
      en: 'How the claim may change simulated agents’ assessed direction or confidence.',
      'zh-CN': '该主张可能如何改变模拟智能体对方向或置信度的判断。',
    },
    example: {
      en: 'Example: an official safety notice changes agents’ assessment of event severity.',
      'zh-CN': '示例：官方安全公告改变智能体对事件严重程度的判断。',
    },
    evidenceType: { en: 'Mechanism hypothesis', 'zh-CN': '机制假设' },
    simulatorParameter: 'beliefShock',
    unselectedMeaning: {
      en: 'Not selected means this claim is not used to directly update simulated beliefs.',
      'zh-CN': '未选择表示该主张不会直接驱动仿真中的信念更新。',
    },
  },
  {
    id: 'socialAmplification',
    name: { en: 'Social amplification', 'zh-CN': '社交传播放大' },
    description: {
      en: 'How repetition and network propagation may amplify the simulated signal.',
      'zh-CN': '重复传播与网络扩散可能如何放大模拟信号。',
    },
    example: {
      en: 'Example: repeated posts propagate the same claim through the agent network.',
      'zh-CN': '示例：重复帖子在智能体网络中传播同一主张。',
    },
    evidenceType: { en: 'Mechanism hypothesis', 'zh-CN': '机制假设' },
    simulatorParameter: 'socialAmplification',
    unselectedMeaning: {
      en: 'Not selected means no direct social-propagation multiplier is assigned to this claim.',
      'zh-CN': '未选择表示该主张不直接获得社交传播倍数。',
    },
  },
  {
    id: 'liquidity',
    name: { en: 'Market liquidity', 'zh-CN': '市场流动性' },
    description: {
      en: 'Possible pressure on simulated spread, depth, queueing, or execution.',
      'zh-CN': '对模拟价差、深度、排队或成交状况的潜在压力。',
    },
    example: {
      en: 'Example: an operational halt may reduce market-making capacity.',
      'zh-CN': '示例：运营暂停可能降低做市能力。',
    },
    evidenceType: { en: 'Mechanism hypothesis', 'zh-CN': '机制假设' },
    simulatorParameter: 'marketMakerCapacity',
    unselectedMeaning: {
      en: 'Not selected means this claim does not directly alter simulated depth or capacity.',
      'zh-CN': '未选择表示该主张不会直接改变仿真深度或做市能力。',
    },
  },
  {
    id: 'passiveFlow',
    name: { en: 'Passive investment flow', 'zh-CN': '被动资金流' },
    description: {
      en: 'Possible scheduled index, fund, or benchmark-linked simulated flow.',
      'zh-CN': '可能触发的指数、基金或基准关联模拟计划资金流。',
    },
    example: {
      en: 'Example: a documented index rebalance creates scheduled benchmark-linked flow.',
      'zh-CN': '示例：有记录的指数再平衡产生按计划执行的基准关联资金流。',
    },
    evidenceType: { en: 'Mechanism hypothesis', 'zh-CN': '机制假设' },
    simulatorParameter: 'passiveFlowMultiplier',
    unselectedMeaning: {
      en: 'Not selected means no rule-based portfolio flow is attributed to this claim.',
      'zh-CN': '未选择表示不会把规则化组合资金流归因给该主张。',
    },
  },
  {
    id: 'stopLoss',
    name: { en: 'Stop-loss pressure', 'zh-CN': '止损压力' },
    description: {
      en: 'Possible activation of deterministic stop-loss behavior in the simulation.',
      'zh-CN': '可能触发仿真中的确定性止损行为。',
    },
    example: {
      en: 'Example: a documented threshold may activate deterministic liquidation rules.',
      'zh-CN': '示例：有记录的阈值可能触发确定性平仓规则。',
    },
    evidenceType: { en: 'Mechanism hypothesis', 'zh-CN': '机制假设' },
    simulatorParameter: 'stopLossSensitivity',
    unselectedMeaning: {
      en: 'Not selected means this claim does not directly activate stop-loss behavior.',
      'zh-CN': '未选择表示该主张不会直接触发止损行为。',
    },
  },
  {
    id: 'informationLatency',
    name: { en: 'Information latency', 'zh-CN': '信息延迟' },
    description: {
      en: 'How delayed availability may change when simulated agents can react.',
      'zh-CN': '信息延迟可见可能如何改变模拟智能体的反应时点。',
    },
    example: {
      en: 'Example: a delayed filing becomes visible to agents several steps later.',
      'zh-CN': '示例：延迟披露的文件在若干步之后才对智能体可见。',
    },
    evidenceType: { en: 'Mechanism hypothesis', 'zh-CN': '机制假设' },
    simulatorParameter: 'informationLatency',
    unselectedMeaning: {
      en: 'Not selected means this claim adds no direct information-delay mechanism.',
      'zh-CN': '未选择表示该主张不会增加直接的信息延迟机制。',
    },
  },
] as const satisfies readonly ImpactChannelDefinition[];

const IMPACT_CHANNEL_BY_ID = new Map<string, ImpactChannelDefinition>(
  IMPACT_CHANNEL_DEFINITIONS.map((definition) => [definition.id, definition]),
);

export function impactChannelDisplay(
  id: string,
  language: Language,
): {
  name: string;
  description: string;
  example: string;
  evidenceType: string;
  simulatorParameter: string;
  unselectedMeaning: string;
  known: boolean;
} {
  const definition = IMPACT_CHANNEL_BY_ID.get(id);
  if (!definition) {
    return {
      name: language === 'zh-CN' ? `其他影响通道（${id}）` : `Other impact channel (${id})`,
      description: language === 'zh-CN'
        ? '当前界面尚未收录该后端通道；原始代码已保留用于审计。'
        : 'This backend channel is not yet in the display catalog; its code is retained for audit.',
      example: language === 'zh-CN' ? '暂无已审核示例。' : 'No reviewed example is available.',
      evidenceType: language === 'zh-CN' ? '机制假设' : 'Mechanism hypothesis',
      simulatorParameter: id,
      unselectedMeaning: language === 'zh-CN'
        ? '未选择表示该通道不会由此主张直接驱动。'
        : 'Not selected means this claim does not directly drive the channel.',
      known: false,
    };
  }
  return {
    name: definition.name[language],
    description: definition.description[language],
    example: definition.example[language],
    evidenceType: definition.evidenceType[language],
    simulatorParameter: definition.simulatorParameter,
    unselectedMeaning: definition.unselectedMeaning[language],
    known: true,
  };
}
