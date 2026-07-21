import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { LlmModelDescriptor } from '../api/types';
import { getLlmModelAvailability, SecondaryOutcomeOption } from './scenario-builder-page';

describe('次要结果指标布局', () => {
  it('复选框与完整文本保持为两列中的两个直接子元素', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { container } = render(
      <SecondaryOutcomeOption
        id="maxDrawdownPct"
        label="最大回撤"
        checked={false}
        onChange={onChange}
      />,
    );

    const row = container.querySelector<HTMLLabelElement>('.native-check-row');
    expect(row).not.toBeNull();
    expect(row?.children).toHaveLength(2);
    expect(row?.querySelector('.native-check-row__label')).toHaveTextContent('最大回撤');
    expect(row?.querySelector('[aria-hidden="true"]')).not.toBeInTheDocument();

    await user.click(screen.getByRole('checkbox', { name: '最大回撤' }));
    expect(onChange).toHaveBeenCalledOnce();
  });

  it('分别识别价格未核验与输出上限未核验，避免把 K2.6 错报为费用闸门可用', () => {
    const readyModel: LlmModelDescriptor = {
      provider: 'zhipu', id: 'ready', name: 'Ready', contextTokens: 128_000,
      maxOutputTokens: 32_768, supportsThinking: true, supportsFunctionCalling: true,
      recommended: true, qualityTier: 'BALANCED', freeTier: false, legacy: false,
      pricingStatus: 'VERIFIED_UPPER_BOUND', billingCurrency: 'CNY',
    };
    const missingOutputLimit = { ...readyModel, id: 'kimi-k2.6', maxOutputTokens: undefined };
    const missingPrice = { ...readyModel, id: 'unpriced', pricingStatus: 'UNAVAILABLE_FAIL_CLOSED' as const };

    expect(getLlmModelAvailability(readyModel)).toBe('READY');
    expect(getLlmModelAvailability(missingOutputLimit)).toBe('OUTPUT_LIMIT_UNVERIFIED');
    expect(getLlmModelAvailability(missingPrice)).toBe('PRICE_UNVERIFIED');
    expect(getLlmModelAvailability(undefined)).toBe('MISSING');
  });
});
