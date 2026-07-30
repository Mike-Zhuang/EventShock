import { describe, expect, it } from 'vitest';
import {
  traceAgentDisplay,
  traceEventDisplay,
  tracePayloadFieldDisplay,
  tracePayloadValueDisplay,
  traceScenarioLabel,
} from './trace-display';

describe('trace display catalogs', () => {
  it('localizes the previously exposed event and agent enums', () => {
    expect(traceEventDisplay('SCENARIO_CONFIGURATION_APPLIED', 'zh-CN').label)
      .toBe('情景配置已应用');
    expect(traceEventDisplay('OPENING_AUCTION_CLEARED', 'zh-CN').label)
      .toBe('开盘集合竞价已撮合');
    expect(traceAgentDisplay('institutionalexecution', 'zh-CN').name)
      .toBe('机构执行交易者');
    expect(traceAgentDisplay('forcedliquidation', 'zh-CN').name)
      .toBe('强制平仓交易者');
    expect(traceAgentDisplay('arbitrage', 'zh-CN').name)
      .toBe('跨信号套利者');
  });

  it('uses readable payload values and explicit unknown fallbacks', () => {
    expect(tracePayloadFieldDisplay('limitPriceTicks', 'zh-CN').label)
      .toBe('合成限价');
    expect(tracePayloadValueDisplay('side', 'SELL', 'zh-CN')).toBe('卖出');
    expect(tracePayloadValueDisplay('priceTicks', 1234, 'en', 0.01))
      .toBe('12.34 (raw: 1,234 ticks)');
    expect(tracePayloadValueDisplay('priceTicks', 1234, 'zh-CN'))
      .toBe('价格换算不可用（原始：1,234 tick）');
    expect(traceScenarioLabel('baseline', 'zh-CN')).toBe('基准组');
    expect(traceEventDisplay('NEW_BACKEND_EVENT', 'zh-CN').label)
      .toBe('未知事件（NEW_BACKEND_EVENT）');
    expect(tracePayloadFieldDisplay('futureField', 'en').label)
      .toBe('Other field (futureField)');
  });
});
