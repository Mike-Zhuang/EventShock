import type { MetricDisplayUnit } from '../api/types';
import type { Language } from '../i18n';

export function formatNumber(value: number | undefined, language: Language, maximumFractionDigits = 3): string {
  if (value === undefined || !Number.isFinite(value)) return language === 'zh-CN' ? '暂无数据' : 'Not available';
  return new Intl.NumberFormat(language, { maximumFractionDigits }).format(value);
}

export function formatMetricValue(value: number | undefined, unit: MetricDisplayUnit | undefined, language: Language): string {
  if (value === undefined || !Number.isFinite(value)) return language === 'zh-CN' ? '暂无数据' : 'Not available';
  // `ratio` 是 0–1 比例；`%`/`percent` 是后端已经换算好的百分点，不能根据数值大小猜测单位。
  if (unit === 'ratio') return `${formatNumber(value * 100, language, 2)}%`;
  if (unit === '%' || unit === 'percent') return `${formatNumber(value, language, 2)}%`;
  if (unit === 'bps') return `${formatNumber(value, language, 2)} bps`;
  if (unit === 'steps') return `${formatNumber(value, language, 0)} ${language === 'zh-CN' ? '步' : 'steps'}`;
  if (unit === 'seconds' || unit === 's') return `${formatNumber(value, language, 1)}s`;
  if (unit === 'shares') return `${formatNumber(value, language, 0)} ${language === 'zh-CN' ? '单位' : 'units'}`;
  if (unit === 'score') return formatNumber(value, language);
  return `${formatNumber(value, language)}${unit ? ` ${unit}` : ''}`;
}

export function formatInterval(low: number | undefined, high: number | undefined, unit: MetricDisplayUnit | undefined, language: Language): string {
  if (low === undefined || high === undefined) return language === 'zh-CN' ? '暂无数据' : 'Not available';
  return `[${formatMetricValue(low, unit, language)}, ${formatMetricValue(high, unit, language)}]`;
}

export function safeDate(value: string | undefined, language: Language, withTime = true): string {
  if (!value) return language === 'zh-CN' ? '暂无数据' : 'Not available';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(language, withTime
    ? { dateStyle: 'medium', timeStyle: 'short' }
    : { dateStyle: 'medium' }).format(parsed);
}

export function downloadFilename(experimentId: string): string {
  const safeId = experimentId.replaceAll(/[^a-zA-Z0-9_-]/g, '-').slice(0, 80);
  return `eventshock-${safeId || 'experiment'}.zip`;
}
