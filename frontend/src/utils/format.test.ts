import { describe, expect, it } from 'vitest';
import {
  downloadFilename,
  formatInterval,
  formatMetricValue,
  formatPriceTicks,
  isoUtcDate,
  safeDate,
} from './format';

describe('metric formatting', () => {
  it('formats backend percentage-point values without scaling them again', () => {
    expect(formatMetricValue(-0.0296, '%', 'en')).toBe('-0.03%');
    expect(formatMetricValue(0.5, 'percent', 'en')).toBe('0.5%');
    expect(formatInterval(-0.938657, 1.405134, '%', 'en')).toBe('[-0.94%, 1.41%]');
  });

  it('converts zero-to-one ratios into percentages', () => {
    expect(formatMetricValue(0.5, 'ratio', 'en')).toBe('50%');
    expect(formatMetricValue(-0.00938657, 'ratio', 'en')).toBe('-0.94%');
  });

  it('does not change the unit interpretation at the value boundary', () => {
    expect(formatMetricValue(1, '%', 'en')).toBe('1%');
    expect(formatMetricValue(1.01, '%', 'en')).toBe('1.01%');
    expect(formatMetricValue(1, 'ratio', 'en')).toBe('100%');
  });

  it('keeps unavailable values unavailable', () => {
    expect(formatMetricValue(undefined, '%', 'en')).toBe('Not available');
    expect(formatMetricValue(Number.NaN, 'ratio', 'zh-CN')).toBe('暂无数据');
  });

  it('formats money, counts, throughput, and latency without leaking raw unit enums', () => {
    expect(formatMetricValue(12_345, 'cents', 'en')).toBe('$123.45');
    expect(formatMetricValue(3, 'count', 'en')).toBe('3 events');
    expect(formatMetricValue(3, 'count', 'zh-CN')).toBe('3 次');
    expect(formatMetricValue(3, 'count', 'zh-CN', 'ledgerRejectedOrders')).toBe('3 笔订单');
    expect(formatMetricValue(3, 'count', 'en', 'haltCount')).toBe('3 halts');
    expect(formatMetricValue(120, 'shares', 'zh-CN')).toBe('120 股');
    expect(formatMetricValue(15.25, 'events/s', 'zh-CN')).toBe('15.25 事件/秒');
    expect(formatMetricValue(12.5, 'ms', 'en')).toBe('12.5 ms');
  });

  it('converts price ticks with the declared tick size', () => {
    expect(formatPriceTicks(1_234, 0.01, 'en')).toBe('12.34');
    expect(formatPriceTicks(1_234, undefined, 'zh-CN')).toBe('暂无数据');
  });

  it('keeps the nearby timestamp in the user timezone and technical time in UTC', () => {
    expect(safeDate('2026-07-15T00:00:00Z', 'en')).toContain('(');
    expect(isoUtcDate('2026-07-15T00:00:00Z', 'en')).toBe('2026-07-15T00:00:00.000Z');
  });

  it('names completed-run exports as reproducibility bundles and sanitizes the identifier', () => {
    expect(downloadFilename('exp-123')).toBe('eventshock-reproducibility-exp-123.zip');
    expect(downloadFilename('../private report')).toBe(
      'eventshock-reproducibility----private-report.zip',
    );
  });
});
