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

const authState = vi.hoisted(() => ({ role: 'USER' as 'ADMIN' | 'USER' }));

vi.mock('../api/client', () => ({
  api: {
    getLlmCatalog: vi.fn(),
    getLlmConfig: vi.fn(),
    getPromptRegistry: vi.fn(),
    saveLlmConfig: vi.fn(),
    testLlmConfig: vi.fn(),
    clearLlmConfig: vi.fn(),
    getAdminLlmCredential: vi.fn(),
    saveAdminLlmCredential: vi.fn(),
    updateAdminLlmCredential: vi.fn(),
    deleteAdminLlmCredential: vi.fn(),
    runEvaluation: vi.fn(),
  },
}));

vi.mock('../state/auth-context', () => ({
  useAuth: () => ({
    user: {
      id: 'admin-or-user-1',
      email: 'owner@example.com',
      role: authState.role,
      emailVerified: true,
      createdAt: '2026-07-20T00:00:00Z',
    },
  }),
}));

const CATALOG: LlmCatalog = {
  defaultProvider: 'zhipu',
  providers: [{
    id: 'zhipu', name: 'Zhipu AI', baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    documentationUrl: 'https://docs.bigmodel.cn/', pricingUrl: 'https://open.bigmodel.cn/pricing',
    region: 'CN', structuredOutputMode: 'json_object', structuredOutputNote: 'JSON object with local validation.',
    integrationValidationStatus: 'REAL_PROJECT_KEY_VERIFIED',
    feedbackIssueUrl: 'https://github.com/Mike-Zhuang/EventShock/issues/new?template=llm-provider-feedback.yml',
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
    integrationValidationStatus: 'CONTRACT_TESTED_COMMUNITY_PREVIEW',
    feedbackIssueUrl: 'https://github.com/Mike-Zhuang/EventShock/issues/new?template=llm-provider-feedback.yml',
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
    integrationValidationStatus: 'CONTRACT_TESTED_COMMUNITY_PREVIEW',
    feedbackIssueUrl: 'https://github.com/Mike-Zhuang/EventShock/issues/new?template=llm-provider-feedback.yml',
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
  pricingSnapshotStatus: 'CURRENT', pricingSnapshotValidUntil: '2026-08-20T00:00:00Z',
  pricingReviewCadenceDays: 31, capabilitySnapshotVersion: 'capabilities-2026-07-20',
  capabilitySnapshotStatus: 'CURRENT', capabilitySnapshotValidUntil: '2026-08-20T23:59:59Z',
  capabilityReviewCadenceDays: 31,
  cnyPerUsdBudgetFloor: 0, costCapSemantics: 'Fail closed.',
  models: [],
};

describe('多供应商 AI 配置', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    });
    authState.role = 'USER';
    window.localStorage.clear();
    window.sessionStorage.clear();
    vi.mocked(api.getLlmCatalog).mockResolvedValue(CATALOG);
    vi.mocked(api.getLlmConfig).mockResolvedValue({ configured: false });
    vi.mocked(api.getPromptRegistry).mockResolvedValue([]);
    vi.mocked(api.getAdminLlmCredential).mockResolvedValue({
      available: true,
      configured: false,
      storageScope: 'ADMIN_SERVER_ENCRYPTED',
    });
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
    expect(screen.getByText('Community preview: not verified with a real project API key')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open a compatibility issue on GitHub' })).toHaveAttribute(
      'href',
      'https://github.com/Mike-Zhuang/EventShock/issues/new?template=llm-provider-feedback.yml',
    );
    expect(screen.getByText(/never paste API keys, tokens, full request headers/i)).toBeInTheDocument();
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
      advancedParameters: {},
    }));
    expect(screen.getByLabelText('OpenAI API Key')).toHaveValue('');
    expect(localStorageWrite.mock.calls.flat().join(' ')).not.toContain(secret);
    expect(sessionStorageWrite.mock.calls.flat().join(' ')).not.toContain(secret);
  });

  it('真实项目 Key 已验证的智谱供应商不显示社区预览警告', async () => {
    render(<I18nProvider><AiConfigurationPage /></I18nProvider>);

    expect(await screen.findByLabelText('Provider')).toHaveValue('zhipu');
    expect(screen.queryByText('Community preview: not verified with a real project API key')).not.toBeInTheDocument();
    expect(screen.getByText('No real-key end-to-end pass is recorded for this exact model'))
      .toBeInTheDocument();
    expect(screen.getByText('Periodic pricing and capability verification')).toBeInTheDocument();
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

  it('中文界面对未实测供应商显示脱敏反馈警告', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem('eventshock-language', 'zh-CN');
    render(<I18nProvider><AiConfigurationPage /></I18nProvider>);

    await user.selectOptions(await screen.findByLabelText('供应商'), 'openai');

    expect(screen.getByText('社区预览：尚未使用真实项目 API Key 验证')).toBeInTheDocument();
    expect(screen.getByText(/请勿粘贴 API Key、令牌、完整请求头、邮箱或其他个人信息/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '在 GitHub 提交兼容性 Issue' })).toBeInTheDocument();
  });

  it('只有供应商、型号、推理设置和输出上限均一致时才视为当前草稿已生效', () => {
    const configuredModel = CATALOG.providers[1].models[1];
    const config = {
      configured: true,
      provider: 'openai' as const,
      model: 'gpt-recommended',
      thinkingEnabled: true,
      maxTokens: 8_192,
      advancedParameters: { temperature: 0.2 },
    };

    expect(configurationMatchesDraft(
      config, 'openai', 'gpt-recommended', configuredModel, true, 8_192,
      { temperature: 0.2 },
    )).toBe(true);
    expect(configurationMatchesDraft(
      config, 'openai', 'gpt-recommended', configuredModel, false, 8_192,
      { temperature: 0.2 },
    )).toBe(false);
    expect(configurationMatchesDraft(
      config, 'openai', 'gpt-recommended', configuredModel, true, 4_096,
      { temperature: 0.2 },
    )).toBe(false);
    expect(configurationMatchesDraft(
      config, 'openai', 'gpt-recommended', configuredModel, true, 8_192,
      { temperature: 0.8 },
    )).toBe(false);
  });

  it('按供应商能力启用白名单高级参数，并把草稿随临时密钥一同提交', async () => {
    const user = userEvent.setup();
    const catalogWithExplicitCapabilities: LlmCatalog = {
      ...CATALOG,
      providers: CATALOG.providers.map((item) => item.id === 'openai'
        ? { ...item, supportedAdvancedParameters: ['temperature', 'timeoutSeconds'] }
        : item),
    };
    vi.mocked(api.getLlmCatalog).mockResolvedValue(catalogWithExplicitCapabilities);
    render(<I18nProvider><AiConfigurationPage /></I18nProvider>);

    await user.selectOptions(await screen.findByLabelText('Provider'), 'openai');
    await user.click(screen.getByText('Advanced request parameters (optional)'));

    expect(screen.getByLabelText('Randomness (temperature)')).toBeEnabled();
    expect(screen.getByLabelText('Per-request timeout (seconds)')).toBeEnabled();
    expect(screen.getByLabelText('Topic repetition penalty (presence penalty)')).toBeDisabled();
    expect(screen.getByLabelText('Provider random seed (seed)')).toBeDisabled();

    await user.clear(screen.getByLabelText('Randomness (temperature)'));
    await user.type(screen.getByLabelText('Randomness (temperature)'), '0.2');
    await user.clear(screen.getByLabelText('Per-request timeout (seconds)'));
    await user.type(screen.getByLabelText('Per-request timeout (seconds)'), '90');
    await user.type(screen.getByLabelText('OpenAI API Key'), 'temporary-advanced-key');
    await user.click(screen.getByRole('button', { name: 'Use for this sign-in' }));

    await waitFor(() => expect(api.saveLlmConfig).toHaveBeenCalledWith(expect.objectContaining({
      advancedParameters: {
        temperature: 0.2,
        timeoutSeconds: 90,
      },
    })));
    expect(screen.getByText('Fixed security boundary')).toBeInTheDocument();
    expect(screen.getByText(/Custom base URLs and headers are not accepted/)).toBeInTheDocument();
  });

  it('恢复供应商默认值会清空所有高级参数', async () => {
    const user = userEvent.setup();
    render(<I18nProvider><AiConfigurationPage /></I18nProvider>);

    await user.click(await screen.findByText('Advanced request parameters (optional)'));
    await user.clear(screen.getByLabelText('Randomness (temperature)'));
    await user.type(screen.getByLabelText('Randomness (temperature)'), '0.7');
    const restoreButton = screen.getByRole('button', { name: 'Restore provider defaults' });
    expect(restoreButton).toBeEnabled();

    await user.click(restoreButton);
    expect(screen.getByLabelText('Randomness (temperature)')).toHaveValue(null);
    expect(restoreButton).toBeDisabled();
  });

  it('普通用户保持临时密钥流程且不会请求管理员服务器凭据', async () => {
    render(<I18nProvider><AiConfigurationPage /></I18nProvider>);

    expect(await screen.findByLabelText('Provider')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Administrator server credential' }))
      .not.toBeInTheDocument();
    expect(api.getAdminLlmCredential).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Use for this sign-in' })).toBeInTheDocument();
  });

  it('页面停留期间也会将已过本地到期时点的临时 Key 标为过期', async () => {
    vi.mocked(api.getLlmConfig).mockResolvedValue({
      configured: true,
      credentialStatus: 'ACTIVE',
      credentialSource: 'SESSION',
      provider: 'zhipu',
      model: 'glm-5.2',
      thinkingEnabled: false,
      maxTokens: 2_048,
      advancedParameters: {},
      expiresAt: '2000-01-01T00:00:00Z',
    });

    render(<I18nProvider><AiConfigurationPage /></I18nProvider>);

    expect(await screen.findByText('Temporary API key expired')).toBeInTheDocument();
    expect(screen.queryByText('Temporary credential expires soon')).not.toBeInTheDocument();
  });

  it('管理员复验密码后把密钥加密保存到服务器且浏览器不持久化明文', async () => {
    authState.role = 'ADMIN';
    const user = userEvent.setup();
    const localStorageWrite = vi.spyOn(window.localStorage, 'setItem');
    const sessionStorageWrite = vi.spyOn(window.sessionStorage, 'setItem');
    const secret = 'administrator-provider-key-for-test';
    vi.mocked(api.saveAdminLlmCredential).mockResolvedValue({
      available: true,
      configured: true,
      storageScope: 'ADMIN_SERVER_ENCRYPTED',
      provider: 'zhipu',
      model: 'glm-5.2',
      thinkingEnabled: false,
      maxTokens: 2_048,
      advancedParameters: {},
      credentialHint: '••••test',
      persistedAt: '2026-08-03T10:00:00Z',
      updatedAt: '2026-08-03T10:00:00Z',
    });
    vi.mocked(api.getLlmConfig)
      .mockResolvedValueOnce({ configured: false })
      .mockResolvedValueOnce({
        configured: true,
        provider: 'zhipu',
        model: 'glm-5.2',
        thinkingEnabled: false,
        maxTokens: 2_048,
        advancedParameters: {},
        credentialHint: '••••test',
        credentialSource: 'ADMIN_SERVER_ENCRYPTED',
      });
    render(<I18nProvider><AiConfigurationPage /></I18nProvider>);

    expect(await screen.findByRole('heading', { name: 'Administrator server credential' }))
      .toBeInTheDocument();
    await user.type(screen.getByLabelText('Zhipu AI API Key'), secret);
    await user.click(screen.getByRole('button', { name: 'Save encrypted on server' }));
    await user.type(screen.getByLabelText('Current administrator password'), 'Admin password 123!');
    await user.click(screen.getByRole('button', { name: 'Save encrypted' }));

    await waitFor(() => expect(api.saveAdminLlmCredential).toHaveBeenCalledWith({
      currentPassword: 'Admin password 123!',
      provider: 'zhipu',
      model: 'glm-5.2',
      apiKey: secret,
      thinkingEnabled: false,
      maxTokens: 2_048,
      advancedParameters: {},
    }));
    expect((await screen.findAllByText(/••••test/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText('ADMIN_SERVER_ENCRYPTED').length).toBeGreaterThan(0);
    expect(screen.getByLabelText('Zhipu AI API Key')).toHaveValue('');
    expect(localStorageWrite.mock.calls.flat().join(' ')).not.toContain(secret);
    expect(sessionStorageWrite.mock.calls.flat().join(' ')).not.toContain(secret);
  });

  it('管理员删除服务器密钥前必须复验密码并看到不可恢复警告', async () => {
    authState.role = 'ADMIN';
    const user = userEvent.setup();
    vi.mocked(api.getAdminLlmCredential).mockResolvedValue({
      available: true,
      configured: true,
      storageScope: 'ADMIN_SERVER_ENCRYPTED',
      provider: 'zhipu',
      model: 'glm-5.2',
      credentialHint: '••••test',
      updatedAt: '2026-08-03T10:00:00Z',
    });
    vi.mocked(api.deleteAdminLlmCredential).mockResolvedValue({
      available: true,
      configured: false,
      storageScope: 'ADMIN_SERVER_ENCRYPTED',
    });
    render(<I18nProvider><AiConfigurationPage /></I18nProvider>);

    await user.click(await screen.findByRole('button', { name: 'Delete server credential' }));
    expect(screen.getByText('The application cannot recover it after deletion')).toBeInTheDocument();
    const confirm = screen.getByRole('button', { name: 'Delete credential' });
    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText('Current administrator password'), 'Admin password 123!');
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    await waitFor(() => expect(api.deleteAdminLlmCredential).toHaveBeenCalledWith({
      currentPassword: 'Admin password 123!',
    }));
    expect(await screen.findByText('No administrator API key is stored on the server.'))
      .toBeInTheDocument();
    expect(screen.queryByText('The application cannot recover it after deletion'))
      .not.toBeInTheDocument();
  });

  it('管理员可以保留现有 Key 并只更新模型设置', async () => {
    authState.role = 'ADMIN';
    const user = userEvent.setup();
    vi.mocked(api.getAdminLlmCredential).mockResolvedValue({
      available: true,
      configured: true,
      storageScope: 'ADMIN_SERVER_ENCRYPTED',
      provider: 'zhipu',
      model: 'glm-5.2',
      thinkingEnabled: false,
      maxTokens: 1_024,
      advancedParameters: {},
      credentialHint: '••••test',
      updatedAt: '2026-08-03T10:00:00Z',
    });
    vi.mocked(api.updateAdminLlmCredential).mockResolvedValue({
      available: true,
      configured: true,
      storageScope: 'ADMIN_SERVER_ENCRYPTED',
      provider: 'zhipu',
      model: 'glm-5.2',
      thinkingEnabled: false,
      maxTokens: 2_048,
      advancedParameters: {},
      credentialHint: '••••test',
      updatedAt: '2026-08-04T10:00:00Z',
    });
    render(<I18nProvider><AiConfigurationPage /></I18nProvider>);

    await user.click(await screen.findByRole('button', {
      name: 'Update model settings (keep key)',
    }));
    expect(screen.getByText('The full key stays in encrypted storage')).toBeInTheDocument();
    await user.type(screen.getByLabelText('Current administrator password'), 'Admin password 123!');
    await user.click(screen.getByRole('button', { name: 'Update settings' }));

    await waitFor(() => expect(api.updateAdminLlmCredential).toHaveBeenCalledWith({
      currentPassword: 'Admin password 123!',
      model: 'glm-5.2',
      thinkingEnabled: false,
      maxTokens: 2_048,
      advancedParameters: {},
    }));
    expect(api.saveAdminLlmCredential).not.toHaveBeenCalled();
  });
});
