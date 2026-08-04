import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import {
  humanizeTechnicalText,
  TechnicalCodeDisplay,
  technicalCodeLabel,
} from './technical-code';

describe('技术状态的人类可读展示', () => {
  it('默认只显示解释，展开技术详情后才显示原始代码', async () => {
    const user = userEvent.setup();
    render(
      <TechnicalCodeDisplay
        codes={['SCHEMA_INVALID', 'MODEL_RESPONSE_INVALID', 'SCHEMA_INVALID']}
        language="zh-CN"
      />,
    );

    expect(screen.getByText(/结构化回复不符合规定格式/)).toBeInTheDocument();
    expect(screen.getByText(/模型回复未通过校验/)).toBeInTheDocument();
    const rawCodes = screen.getByText('SCHEMA_INVALID, MODEL_RESPONSE_INVALID');
    expect(rawCodes).not.toBeVisible();

    await user.click(screen.getByText('技术详情'));
    expect(rawCodes).toBeVisible();
  });

  it('转换自由文本中的已知枚举，并为异常类名提供稳定说明', () => {
    expect(humanizeTechnicalText(
      'The run stopped after MODEL_TIMEOUT and SCHEMA_INVALID.',
      'en',
    )).toBe(
      'The run stopped after The model did not respond before the timeout and The structured response did not match the required format.',
    );
    expect(technicalCodeLabel('ModelGatewayError', 'en'))
      .toBe('The model service could not complete the request');
    expect(technicalCodeLabel('NEW_PROVIDER_STATE', 'zh-CN'))
      .toBe('未收录的技术状态：new provider state');
  });
});
