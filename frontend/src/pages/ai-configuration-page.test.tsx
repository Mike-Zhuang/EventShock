import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type { LlmCatalog } from '../api/types';
import { I18nProvider } from '../i18n';
import {
  AiConfigurationPage,
  configurationMatchesDraft,
} from './ai-configuration-page';

vi.mock('../api/client', () => ({
  api: {
    getLlmCatalog: vi.fn(),
    getLlmConfig: vi.fn(),
    getPromptRegistry: vi.fn(),
    saveLlmConfig: vi.fn(),
    testLlmConfig: vi.fn(),
    clearLlmConfig: vi.fn(),
    runEvaluation: vi.fn(),
  },
}));

const CATALOG: LlmCatalog = {
  defaultProvider: 'zhipu',
  providers: [{
    id: 'zhipu', name: 'Zhipu AI', baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    documentationUrl: 'https://docs.bigmodel.cn/', pricingUrl: 'https://open.bigmodel.cn/pricing',
    region: 'CN', structuredOutputMode: 'json_object', structuredOutputNote: 'JSON object with local validation.',
    models: [{
      provider: 'zhipu', id: 'glm-5.2', name: 'GLM-5.2', contextTokens: 200_000,
      maxOutputTokens: 131_072, officialMaxOutputTokens: 131_072,
      applicationMaxOutputTokens: 32_768,
      supportsThinking: true, supportsFunctionCalling: true,
      recommended: true, qualityTier: 'PREMIUM', freeTier: false, legacy: false,
      pricingStatus: 'VERIFIED_UPPER_BOUND', billingCurrency: 'CNY',
      inputRateUpperPerMillion: 4, outputRateUpperPerMillion: 16,
      budgetInputRateUpperPerMillion: 8, budgetOutputRateUpperPerMillion: 20,
      pricingVerifiedAt: '2026-07-20',
    }],
  }, {
    id: 'openai', name: 'OpenAI', baseUrl: 'https://api.openai.com/v1',
    documentationUrl: 'https://platform.openai.com/docs', pricingUrl: 'https://openai.com/api/pricing/',
    region: 'US', structuredOutputMode: 'json_schema', structuredOutputNote: 'Strict JSON Schema when supported.',
    models: [{
      provider: 'openai', id: 'gpt-economy', name: 'GPT Economy', contextTokens: 128_000,
      maxOutputTokens: 16_384, applicationMaxOutputTokens: 16_384,
      supportsThinking: false, supportsFunctionCalling: true,
      recommended: false, qualityTier: 'ECONOMY', freeTier: false, legacy: false,
      pricingStatus: 'VERIFIED_UPPER_BOUND', billingCurrency: 'USD',
      inputRateUpperPerMillion: 0.2, outputRateUpperPerMillion: 0.8,
      pricingVerifiedAt: '2026-07-20',
    }, {
      provider: 'openai', id: 'gpt-recommended', name: 'GPT Recommended', contextTokens: 400_000,
      maxOutputTokens: 128_000, officialMaxOutputTokens: 128_000,
      applicationMaxOutputTokens: 32_768,
      supportsThinking: true, supportsFunctionCalling: true,
      recommended: true, qualityTier: 'PREMIUM', freeTier: false, legacy: false,
      pricingStatus: 'VERIFIED_UPPER_BOUND', billingCurrency: 'USD',
      inputRateUpperPerMillion: 1.75, cachedInputRatePerMillion: 0.175,
      outputRateUpperPerMillion: 14, pricingVerifiedAt: '2026-07-20',
    }],
  }, {
    id: 'moonshot', name: 'Moonshot AI / Kimi', baseUrl: 'https://api.moonshot.cn/v1/chat/completions',
    documentationUrl: 'https://platform.kimi.com/docs/models', pricingUrl: 'https://platform.kimi.com/docs/pricing/chat-k3',
    region: 'CN', structuredOutputMode: 'json_schema', structuredOutputNote: 'Native JSON Schema with local validation.',
    models: [{
      provider: 'moonshot', id: 'kimi-k2.6', name: 'Kimi K2.6', contextTokens: 262_144,
      supportsThinking: true, supportsFunctionCalling: true, recommended: false,
      qualityTier: 'BALANCED', freeTier: false, legacy: false,
      pricingStatus: 'VERIFIED_UPPER_BOUND', billingCurrency: 'CNY',
      inputRateUpperPerMillion: 6.5, outputRateUpperPerMillion: 27,
      capabilityNote: 'Official output cap is not independently verifiable.',
    }, {
      provider: 'moonshot', id: 'kimi-k3', name: 'Kimi K3', contextTokens: 1_048_576,
      maxOutputTokens: 1_048_576, supportsThinking: true, supportsFunctionCalling: true,
      applicationMaxOutputTokens: 32_768, thinkingAlwaysOn: true,
      recommended: true, qualityTier: 'PREMIUM', freeTier: false, legacy: false,
      pricingStatus: 'VERIFIED_UPPER_BOUND', billingCurrency: 'CNY',
      inputRateUpperPerMillion: 20, outputRateUpperPerMillion: 100,
    }],
  }],
  provider: 'zhipu', providerName: 'Zhipu AI', baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
  documentationUrl: 'https://docs.bigmodel.cn/', pricingUrl: 'https://open.bigmodel.cn/pricing',
  pricingSnapshotVersion: '2026-07-20', fxSourceUrl: '', officialFxSnapshotCnyPerUsd: 0,
  cnyPerUsdBudgetFloor: 0, costCapSemantics: 'Fail closed.',
  models: [],
};

describe('多供应商 AI 配置', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    window.sessionStorage.clear();
    vi.mocked(api.getLlmCatalog).mockResolvedValue(CATALOG);
    vi.mocked(api.getLlmConfig).mockResolvedValue({ configured: false });
    vi.mocked(api.getPromptRegistry).mockResolvedValue([]);
    vi.mocked(api.saveLlmConfig).mockResolvedValue({
      configured: true,
      provider: 'openai',
      model: 'gpt-recommended',
      thinkingEnabled: false,
      maxTokens: 2_048,
      credentialHint: '…test',
    });
  });

  it('切换供应商后选择已定价推荐模型，且 API Key 不进入浏览器存储', async () => {
    const user = userEvent.setup();
    const localStorageWrite = vi.spyOn(window.localStorage, 'setItem');
    const sessionStorageWrite = vi.spyOn(window.sessionStorage, 'setItem');
    render(<I18nProvider><AiConfigurationPage /></I18nProvider>);

    const providerSelect = await screen.findByLabelText('Provider');
    expect(providerSelect).toHaveValue('zhipu');
    await user.selectOptions(providerSelect, 'openai');

    expect(screen.getByLabelText('Model')).toHaveValue('gpt-recommended');
    expect(screen.getByLabelText('OpenAI API Key')).toBeInTheDocument();
    expect(screen.getByText('Native JSON Schema + local validation')).toBeInTheDocument();
    expect(screen.getByLabelText('Maximum output tokens')).toHaveAttribute('max', '32768');

    const secret = 'temporary-provider-key-for-test';
    await user.type(screen.getByLabelText('OpenAI API Key'), secret);
    await user.click(screen.getByRole('button', { name: 'Use for this sign-in' }));

    await waitFor(() => expect(api.saveLlmConfig).toHaveBeenCalledWith({
      provider: 'openai',
      model: 'gpt-recommended',
      apiKey: secret,
      thinkingEnabled: false,
      maxTokens: 2_048,
    }));
    expect(screen.getByLabelText('OpenAI API Key')).toHaveValue('');
    expect(localStorageWrite.mock.calls.flat().join(' ')).not.toContain(secret);
    expect(sessionStorageWrite.mock.calls.flat().join(' ')).not.toContain(secret);
  });

  it('保留但禁用缺少官方输出上限的模型，并解释关闭原因', async () => {
    const user = userEvent.setup();
    render(<I18nProvider><AiConfigurationPage /></I18nProvider>);

    await user.selectOptions(await screen.findByLabelText('Provider'), 'moonshot');
    expect(screen.getByLabelText('Model')).toHaveValue('kimi-k3');

    const blockedOption = screen.getByRole('option', {
      name: 'Kimi K2.6 (Output cap unverified — blocked)',
    });
    expect(blockedOption).toBeDisabled();
  });

  it('Kimi K3 显示为供应商固定推理且提交时不会伪装为关闭', async () => {
    const user = userEvent.setup();
    render(<I18nProvider><AiConfigurationPage /></I18nProvider>);

    await user.selectOptions(await screen.findByLabelText('Provider'), 'moonshot');
    const thinkingToggle = screen.getByRole('switch', { name: 'Thinking mode' });
    expect(thinkingToggle).toBeChecked();
    expect(thinkingToggle).toBeDisabled();
    expect(screen.getAllByText('Always on').length).toBeGreaterThan(0);

    const secret = 'temporary-kimi-key-for-test';
    await user.type(screen.getByLabelText('Moonshot AI / Kimi API Key'), secret);
    await user.click(screen.getByRole('button', { name: 'Use for this sign-in' }));

    await waitFor(() => expect(api.saveLlmConfig).toHaveBeenCalledWith(expect.objectContaining({
      provider: 'moonshot',
      model: 'kimi-k3',
      thinkingEnabled: true,
    })));
  });

  it('中文界面把区域、能力档和结构化输出语义本地化', async () => {
    window.localStorage.setItem('eventshock-language', 'zh-CN');
    render(<I18nProvider><AiConfigurationPage /></I18nProvider>);

    expect(await screen.findByText('中国大陆')).toBeInTheDocument();
    expect(screen.getByText('高能力型')).toBeInTheDocument();
    expect(screen.getByText('JSON 对象 + 本地 Schema 校验')).toBeInTheDocument();
    expect(screen.getByText('费用闸门输入上界')).toBeInTheDocument();
    expect(screen.queryByText('JSON object with local validation.')).not.toBeInTheDocument();
  });

  it('只有供应商、型号、推理设置和输出上限均一致时才视为当前草稿已生效', () => {
    const configuredModel = CATALOG.providers[1].models[1];
    const config = {
      configured: true,
      provider: 'openai' as const,
      model: 'gpt-recommended',
      thinkingEnabled: true,
      maxTokens: 8_192,
    };

    expect(configurationMatchesDraft(
      config, 'openai', 'gpt-recommended', configuredModel, true, 8_192,
    )).toBe(true);
    expect(configurationMatchesDraft(
      config, 'openai', 'gpt-recommended', configuredModel, false, 8_192,
    )).toBe(false);
    expect(configurationMatchesDraft(
      config, 'openai', 'gpt-recommended', configuredModel, true, 4_096,
    )).toBe(false);
  });
});
