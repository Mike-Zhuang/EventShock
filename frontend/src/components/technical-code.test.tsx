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
      .toBe('系统正在处理此步骤');
    expect(technicalCodeLabel('NEW_PROVIDER_STATE', 'en'))
      .toBe('The system is processing this step');
  });

  it('区分供应商连接失败、格式失败和证据审核阻塞原因', () => {
    expect(technicalCodeLabel('MODEL_TRANSPORT_ERROR', 'zh-CN'))
      .toBe('模型供应商连接暂时失败');
    expect(technicalCodeLabel('PROVIDER_RESPONSE_FAILED', 'en'))
      .toBe('No usable provider response was received');
    expect(technicalCodeLabel('EXTRACTION_NOT_ELIGIBLE', 'zh-CN'))
      .toBe('该来源暂不符合证据抽取条件');
    expect(technicalCodeLabel('PREPARED_PROPOSAL_READY', 'zh-CN'))
      .toBe('引导候选已通过校验，正在准备人工审核');
    expect(technicalCodeLabel('PREPARED_PROPOSAL_READY', 'en'))
      .toBe('The guided candidate is ready for human review');
  });
});
