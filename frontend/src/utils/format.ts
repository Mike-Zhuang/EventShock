import type { MetricDisplayUnit } from '../api/types';
import type { Language } from '../i18n';

export function formatNumber(value: number | undefined, language: Language, maximumFractionDigits = 3): string {
  if (value === undefined || !Number.isFinite(value)) return language === 'zh-CN' ? '暂无数据' : 'Not available';
  return new Intl.NumberFormat(language, { maximumFractionDigits }).format(value);
}

const COUNT_UNIT_LABELS: Readonly<Record<string, { en: string; zh: string }>> = {
  forcedLiquidations: { en: 'liquidations', zh: '次平仓' },
  haltCount: { en: 'halts', zh: '次停牌' },
  ledgerRejectedOrders: { en: 'orders', zh: '笔订单' },
  cognitiveOrderCount: { en: 'orders', zh: '笔订单' },
  cognitionInfluencedOrderCount: { en: 'orders', zh: '笔订单' },
  validCognitionDecisionCount: { en: 'decisions', zh: '次决策' },
  cognitionSignalConsumedCount: { en: 'signals', zh: '个信号' },
  validCognitionSignalConsumedCount: { en: 'signals', zh: '个信号' },
  cognitionChangedIntentCount: { en: 'intents', zh: '个意图' },
  cognitionRiskBlockedCount: { en: 'actions', zh: '个行动' },
  cognitionNoActionCount: { en: 'decisions', zh: '次决策' },
};

export function formatMetricValue(
  value: number | undefined,
  unit: MetricDisplayUnit | undefined,
  language: Language,
  metricId?: string,
): string {
  if (value === undefined || !Number.isFinite(value)) return language === 'zh-CN' ? '暂无数据' : 'Not available';
  // `ratio` 是 0–1 比例；`%`/`percent` 是后端已经换算好的百分点，不能根据数值大小猜测单位。
  if (unit === 'ratio') return `${formatNumber(value * 100, language, 2)}%`;
  if (unit === '%' || unit === 'percent') return `${formatNumber(value, language, 2)}%`;
  if (unit === 'bps') return `${formatNumber(value, language, 2)} bps`;
  if (unit === 'steps') return `${formatNumber(value, language, 0)} ${language === 'zh-CN' ? '步' : 'steps'}`;
  if (unit === 'seconds' || unit === 's') return `${formatNumber(value, language, 1)}s`;
  if (unit === 'shares') return `${formatNumber(value, language, 0)} ${language === 'zh-CN' ? '股' : 'shares'}`;
  if (unit === 'cents') {
    return new Intl.NumberFormat(language, {
      style: 'currency',
      currency: 'USD',
      maximumFractionDigits: 2,
    }).format(value / 100);
  }
  if (unit === 'count') {
    const label = metricId ? COUNT_UNIT_LABELS[metricId] : undefined;
    return `${formatNumber(value, language, 0)} ${
      label
        ? language === 'zh-CN' ? label.zh : label.en
        : language === 'zh-CN' ? '次' : 'events'
    }`;
  }
  if (unit === 'events/s') return `${formatNumber(value, language, 2)} ${language === 'zh-CN' ? '事件/秒' : 'events/s'}`;
  if (unit === 'ms') return `${formatNumber(value, language, 1)} ms`;
  if (unit === 'score') return formatNumber(value, language);
  return `${formatNumber(value, language)}${unit ? ` ${unit}` : ''}`;
}

export function formatInterval(
  low: number | undefined,
  high: number | undefined,
  unit: MetricDisplayUnit | undefined,
  language: Language,
  metricId?: string,
): string {
  if (low === undefined || high === undefined) return language === 'zh-CN' ? '暂无数据' : 'Not available';
  return `[${formatMetricValue(low, unit, language, metricId)}, ${formatMetricValue(high, unit, language, metricId)}]`;
}

export function safeDate(value: string | undefined, language: Language, withTime = true): string {
  if (!value) return language === 'zh-CN' ? '暂无数据' : 'Not available';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const formatted = new Intl.DateTimeFormat(language, withTime
    ? { dateStyle: 'medium', timeStyle: 'short' }
    : { dateStyle: 'medium' }).format(parsed);
  return withTime ? `${formatted} (${userTimeZone()})` : formatted;
}

export function isoUtcDate(value: string | undefined, language: Language): string {
  if (!value) return language === 'zh-CN' ? '暂无数据' : 'Not available';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toISOString();
}

export function userTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
}

export function formatPriceTicks(
  value: number | undefined,
  tickSize: number | undefined,
  language: Language,
): string {
  if (
    value === undefined
    || !Number.isFinite(value)
    || tickSize === undefined
    || !Number.isFinite(tickSize)
    || tickSize <= 0
  ) {
    return language === 'zh-CN' ? '暂无数据' : 'Not available';
  }
  const tickDecimals = Math.min(
    8,
    Math.max(0, (String(tickSize).split('.')[1] ?? '').length),
  );
  return formatNumber(value * tickSize, language, tickDecimals);
}

export function downloadFilename(experimentId: string): string {
  const safeId = experimentId.replaceAll(/[^a-zA-Z0-9_-]/g, '-').slice(0, 80);
  return `eventshock-reproducibility-${safeId || 'experiment'}.zip`;
}
