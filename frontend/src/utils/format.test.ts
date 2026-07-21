import { describe, expect, it } from 'vitest';
import { formatInterval, formatMetricValue } from './format';

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
});
