import { describe, expect, it } from 'vitest';
import { getPageGuide } from './page-guidance';

describe('研究工作区页面引导', () => {
  it('将研究、链路与治理列为正式研究工具，并保留 AI 为可选能力', () => {
    expect(getPageGuide('study', 'en').optional).toBe(false);
    expect(getPageGuide('trace', 'en').optional).toBe(false);
    expect(getPageGuide('governance', 'en').optional).toBe(false);
    expect(getPageGuide('ai', 'en').optional).toBe(true);
  });
});
