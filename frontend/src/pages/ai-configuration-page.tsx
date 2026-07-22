import {
  Button,
  InlineNotification,
  NumberInput,
  Select,
  SelectItem,
  Tag,
  TextInput,
  Toggle,
} from '@carbon/react';
import { CheckCircle, FloppyDisk, Key, Plug, Trash } from '@phosphor-icons/react';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type {
  CognitionEvaluationRun,
  LlmCatalog,
  LlmConfigView,
  LlmConnectionTest,
  LlmModelDescriptor,
  LlmProviderDescriptor,
  LlmProviderId,
  PromptRegistryItem,
} from '../api/types';
import { ErrorPanel, ExplainedLabel, LoadingPanel, Notice, PageHeader, ParameterHelp, StatusBadge } from '../components/common';
import { useI18n } from '../i18n';
import { getPageGuide } from '../page-guidance';
import { getParameterHelp } from '../parameter-help';

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function selectRecommendedPricedModel(
  provider: LlmProviderDescriptor,
): LlmModelDescriptor | undefined {
  return provider.models.find((item) => item.recommended && isModelCallable(item))
    ?? provider.models.find(isModelCallable)
    ?? provider.models[0];
}

export function officialOutputLimit(model: LlmModelDescriptor | undefined): number | undefined {
  return model?.officialMaxOutputTokens ?? model?.maxOutputTokens;
}

export function applicationOutputLimit(model: LlmModelDescriptor | undefined): number | undefined {
  const officialLimit = officialOutputLimit(model);
  const applicationLimit = model?.applicationMaxOutputTokens ?? officialLimit;
  if (applicationLimit === undefined) return undefined;
  return officialLimit === undefined ? applicationLimit : Math.min(applicationLimit, officialLimit);
}

export function isModelCallable(model: LlmModelDescriptor | undefined): boolean {
  return Boolean(
    model
    && model.pricingStatus === 'VERIFIED_UPPER_BOUND'
    && officialOutputLimit(model) !== undefined
    && applicationOutputLimit(model) !== undefined,
  );
}

export function effectiveThinkingSetting(
  model: LlmModelDescriptor | undefined,
  requested: boolean | undefined,
): boolean {
  if (model?.thinkingAlwaysOn) return true;
  return Boolean(model?.supportsThinking && requested);
}

export function configurationMatchesDraft(
  config: LlmConfigView | undefined,
  provider: LlmProviderId,
  modelId: string,
  model: LlmModelDescriptor | undefined,
  thinkingEnabled: boolean,
  maxTokens: number,
): boolean {
  return Boolean(
    config?.configured
    && config.provider === provider
    && config.model === modelId
    && effectiveThinkingSetting(model, config.thinkingEnabled) === effectiveThinkingSetting(model, thinkingEnabled)
    && config.maxTokens === maxTokens,
  );
}

function formatRate(
  value: number | undefined,
  currency: string | undefined,
  language: string,
): string {
  if (value === undefined || !currency) return '—';
  try {
    const formatted = new Intl.NumberFormat(language, {
      style: 'currency',
      currency,
      maximumFractionDigits: 6,
    }).format(value);
    return `${formatted} / ${language === 'zh-CN' ? '每百万 token' : '1M tokens'}`;
  } catch {
    return `${value} ${currency} / ${language === 'zh-CN' ? '每百万 token' : '1M tokens'}`;
  }
}

function localizeRegion(region: string | undefined, isZh: boolean): string {
  const normalized = region?.trim().toUpperCase();
  const regions: Record<string, [string, string]> = {
    CN: ['中国大陆', 'Mainland China'],
    US: ['美国', 'United States'],
    GLOBAL: ['全球', 'Global'],
    CN_BEIJING_GLOBAL: ['中国（北京端点，全球服务）', 'China (Beijing endpoint, global service)'],
  };
  const label = normalized ? regions[normalized] : undefined;
  return label ? label[isZh ? 0 : 1] : region || '—';
}

function localizeQualityTier(tier: LlmModelDescriptor['qualityTier'], isZh: boolean): string {
  const labels = {
    ECONOMY: ['经济型', 'Economy'],
    BALANCED: ['均衡型', 'Balanced'],
    PREMIUM: ['高能力型', 'Premium'],
  } as const;
  return labels[tier][isZh ? 0 : 1];
}

function localizeStructuredOutput(mode: string | undefined, isZh: boolean): string {
  const normalized = mode?.trim().toUpperCase();
  if (normalized?.includes('JSON_SCHEMA')) {
    return isZh ? '原生 JSON Schema + 本地校验' : 'Native JSON Schema + local validation';
  }
  if (normalized?.includes('JSON_OBJECT')) {
    return isZh ? 'JSON 对象 + 本地 Schema 校验' : 'JSON object + local schema validation';
  }
  return isZh ? '结构化 JSON + 本地校验' : 'Structured JSON + local validation';
}

export function AiConfigurationPage() {
  const { language, t } = useI18n();
  const isZh = language === 'zh-CN';
  const explained = (key: string, label: string) => (
    <ExplainedLabel label={label} explanation={getParameterHelp(key, language) ?? label} />
  );
  const parameterHelp = (key: string, label: string) => (
    <ParameterHelp label={label} explanation={getParameterHelp(key, language) ?? label} />
  );
  const [catalog, setCatalog] = useState<LlmCatalog>();
  const [config, setConfig] = useState<LlmConfigView>();
  const [prompts, setPrompts] = useState<PromptRegistryItem[]>([]);
  const [provider, setProvider] = useState<LlmProviderId>('zhipu');
  const [model, setModel] = useState('glm-5.2');
  const [apiKey, setApiKey] = useState('');
  const [thinkingEnabled, setThinkingEnabled] = useState(false);
  const [maxTokens, setMaxTokens] = useState(2_048);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<'save' | 'test' | 'clear'>();
  const [error, setError] = useState<string>();
  const [testResult, setTestResult] = useState<LlmConnectionTest>();
  const [evaluationRun, setEvaluationRun] = useState<CognitionEvaluationRun>();
  const [evaluationBusy, setEvaluationBusy] = useState<CognitionEvaluationRun['mode']>();
  const [evaluationMaximumCases, setEvaluationMaximumCases] = useState(3);

  const load = async () => {
    setLoading(true);
    setError(undefined);
    try {
      const [nextCatalog, nextConfig, nextPrompts] = await Promise.all([
        api.getLlmCatalog(),
        api.getLlmConfig(),
        api.getPromptRegistry(),
      ]);
      setCatalog(nextCatalog);
      setConfig(nextConfig);
      setPrompts(nextPrompts);
      const nextProvider = nextCatalog.providers.find((item) => item.id === nextConfig.provider)
        ?? nextCatalog.providers.find((item) => item.id === nextCatalog.defaultProvider)
        ?? nextCatalog.providers[0];
      if (nextProvider) {
        setProvider(nextProvider.id);
        const configuredModel = nextProvider.models.find((item) => item.id === nextConfig.model);
        const nextModel = configuredModel ?? selectRecommendedPricedModel(nextProvider);
        if (nextModel) {
          setModel(nextModel.id);
          setThinkingEnabled(effectiveThinkingSetting(nextModel, nextConfig.thinkingEnabled));
          const outputLimit = applicationOutputLimit(nextModel);
          const requestedMaxTokens = configuredModel ? nextConfig.maxTokens ?? 2_048 : 2_048;
          setMaxTokens(outputLimit === undefined
            ? requestedMaxTokens
            : Math.min(requestedMaxTokens, outputLimit));
        }
      }
    } catch (loadError) {
      setError(messageOf(loadError));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const selectedProvider = useMemo(
    () => catalog?.providers.find((item) => item.id === provider),
    [catalog, provider],
  );
  const selectedModel = useMemo(
    () => selectedProvider?.models.find((item) => item.id === model),
    [selectedProvider, model],
  );
  const selectedApplicationOutputLimit = applicationOutputLimit(selectedModel);
  const selectedOfficialOutputLimit = officialOutputLimit(selectedModel);
  const hasActiveConfig = Boolean(config?.configured);
  const hasMatchingConfig = configurationMatchesDraft(
    config,
    provider,
    model,
    selectedModel,
    thinkingEnabled,
    maxTokens,
  );
  const hasUnsavedDraft = hasActiveConfig && !hasMatchingConfig;

  const changeProvider = (nextProviderId: LlmProviderId) => {
    const nextProvider = catalog?.providers.find((item) => item.id === nextProviderId);
    if (!nextProvider) return;
    const nextModel = selectRecommendedPricedModel(nextProvider);
    setProvider(nextProvider.id);
    if (nextModel) {
      setModel(nextModel.id);
      setThinkingEnabled(effectiveThinkingSetting(nextModel, false));
      const outputLimit = applicationOutputLimit(nextModel);
      setMaxTokens(outputLimit === undefined ? 2_048 : Math.min(2_048, outputLimit));
    }
    setApiKey('');
    setTestResult(undefined);
  };

  const save = async () => {
    setBusyAction('save');
    setError(undefined);
    setTestResult(undefined);
    try {
      const nextConfig = await api.saveLlmConfig({
        provider,
        model,
        apiKey,
        thinkingEnabled: effectiveThinkingSetting(selectedModel, thinkingEnabled),
        maxTokens,
      });
      setConfig(nextConfig);
      setApiKey('');
    } catch (saveError) {
      setError(messageOf(saveError));
    } finally {
      setBusyAction(undefined);
    }
  };

  const test = async () => {
    setBusyAction('test');
    setError(undefined);
    setTestResult(undefined);
    try {
      setTestResult(await api.testLlmConfig());
    } catch (testError) {
      setError(messageOf(testError));
    } finally {
      setBusyAction(undefined);
    }
  };

  const clear = async () => {
    setBusyAction('clear');
    setError(undefined);
    setTestResult(undefined);
    try {
      setConfig(await api.clearLlmConfig());
      setApiKey('');
    } catch (clearError) {
      setError(messageOf(clearError));
    } finally {
      setBusyAction(undefined);
    }
  };

  const runEvaluation = async (mode: CognitionEvaluationRun['mode']) => {
    setEvaluationBusy(mode);
    setEvaluationRun(undefined);
    setError(undefined);
    try {
      setEvaluationRun(await api.runEvaluation(mode, evaluationMaximumCases));
    } catch (evaluationError) {
      setError(messageOf(evaluationError));
    } finally {
      setEvaluationBusy(undefined);
    }
  };

  if (loading) {
    return (
      <div className="page">
        <PageHeader
          title={isZh ? 'AI 模型配置' : 'AI Model Configuration'}
          subtitle={isZh ? '正在加载多供应商模型目录。' : 'Loading the multi-provider model catalog.'}
        />
        <LoadingPanel />
      </div>
    );
  }

  if (!catalog && error) {
    return (
      <div className="page">
        <PageHeader
          title={isZh ? 'AI 模型配置' : 'AI Model Configuration'}
          subtitle={isZh ? '无法加载模型目录。' : 'The model catalog could not be loaded.'}
        />
        <ErrorPanel detail={error} onRetry={() => void load()} />
      </div>
    );
  }

  return (
    <div className="page page--ai-configuration">
      <PageHeader
        title={isZh ? 'AI 模型配置' : 'AI Model Configuration'}
        subtitle={isZh
          ? '选择用于证据抽取与代表性认知智能体的模型供应商。智谱仍是默认选项；密钥仅绑定当前登录会话并短时驻留服务器内存，不写入账户、数据库或浏览器存储。'
          : 'Choose a model provider for evidence extraction and representative cognitive agents. Zhipu remains the default; the key is bound only to this sign-in session, kept briefly in server memory, and never written to the account, database, or browser storage.'}
        guide={getPageGuide('ai', language)}
        actions={<StatusBadge status={hasActiveConfig ? 'CONFIGURED' : 'RULE ONLY'} />}
      />

      {error ? (
        <InlineNotification
          kind="error"
          lowContrast
          hideCloseButton
          title={isZh ? '配置操作失败' : 'Configuration action failed'}
          subtitle={error}
        />
      ) : null}
      {testResult ? (
        <InlineNotification
          kind={testResult.ok ? 'success' : 'error'}
          lowContrast
          hideCloseButton
          title={testResult.ok
            ? isZh ? '结构化输出验证成功' : 'Structured output validated'
            : isZh ? '连接测试失败' : 'Connection test failed'}
          subtitle={`${isZh
            ? testResult.ok
              ? `已验证 ${testResult.provider} / ${testResult.model} 的结构化响应。`
              : `已生效配置未通过连接或结构化输出校验${testResult.failureCode ? `（${testResult.failureCode}）` : ''}。`
            : testResult.message}${testResult.latencyMs ? ` (${Math.round(testResult.latencyMs)} ms)` : ''}`}
        />
      ) : null}
      {hasUnsavedDraft ? (
        <InlineNotification
          kind="info"
          lowContrast
          hideCloseButton
          title={isZh ? '当前表单是尚未生效的草稿' : 'The current form is an unapplied draft'}
          subtitle={isZh
            ? `服务器仍使用 ${config?.provider ?? '—'} / ${config?.model ?? '—'}、最大输出 ${config?.maxTokens ?? '—'} token 的临时凭据。重新提交 API Key 前，连接测试和真实模型评估仍针对这套已生效配置。`
            : `The server still uses the temporary credential for ${config?.provider ?? '—'} / ${config?.model ?? '—'} with a ${config?.maxTokens ?? '—'}-token output limit. Until you submit an API key again, connection tests and live evaluations continue to use that active configuration.`}
        />
      ) : null}

      <div className="ai-config-layout">
        <section className="ai-config-panel" aria-labelledby="provider-settings-heading">
          <div className="section-heading">
            <h2 id="provider-settings-heading">{isZh ? '供应商与凭据' : 'Provider and credential'}</h2>
            <p>{isZh ? '浏览器只把密钥发送到同源后端，不直接请求供应商；退出、过期、切换供应商或服务重启后需要重新填写。' : 'The browser sends the key only to the same-origin backend and never calls the provider directly. Re-enter it after sign-out, expiry, provider changes, or a service restart.'}</p>
          </div>
          <div className="config-form-grid">
            <Select
              id="llm-provider"
              labelText={isZh ? '供应商' : 'Provider'}
              decorator={parameterHelp('provider', isZh ? '供应商' : 'Provider')}
              value={provider}
              onChange={(event) => changeProvider(event.target.value as LlmProviderId)}
            >
              {catalog?.providers.map((item) => (
                <SelectItem
                  key={item.id}
                  value={item.id}
                  text={`${item.name}${item.id === catalog.defaultProvider ? isZh ? '（默认）' : ' (Default)' : ''}`}
                />
              ))}
            </Select>
            <Select
              id="llm-model"
              labelText={isZh ? '模型' : 'Model'}
              decorator={parameterHelp('model', isZh ? '模型' : 'Model')}
              value={model}
              onChange={(event) => {
                setModel(event.target.value);
                const descriptor = selectedProvider?.models.find((item) => item.id === event.target.value);
                if (descriptor) {
                  setThinkingEnabled((current) => effectiveThinkingSetting(descriptor, current));
                  const outputLimit = applicationOutputLimit(descriptor);
                  if (outputLimit !== undefined) {
                    setMaxTokens((current) => Math.min(current, outputLimit));
                  }
                }
              }}
            >
              {selectedProvider?.models.map((item) => (
                <SelectItem
                  key={item.id}
                  value={item.id}
                  disabled={!isModelCallable(item)}
                  text={`${item.name}${item.recommended ? isZh ? '（推荐）' : ' (Recommended)' : ''}${item.freeTier ? isZh ? '（免费层）' : ' (Free tier)' : ''}${item.pricingStatus !== 'VERIFIED_UPPER_BOUND' ? isZh ? '（价格未知，禁止调用）' : ' (Unpriced — blocked)' : officialOutputLimit(item) === undefined ? isZh ? '（输出上限未核验，禁止调用）' : ' (Output cap unverified — blocked)' : ''}`}
                />
              ))}
            </Select>
            <TextInput
              id="llm-api-key"
              type="password"
              labelText={`${selectedProvider?.name ?? provider} API Key`}
              helperText={hasMatchingConfig
                ? `${isZh ? '当前配置' : 'Current credential'}: ${config?.credentialHint ?? 'hidden'}`
                : hasActiveConfig
                  ? isZh ? '当前表单与已生效配置不同；重新提交密钥后才会切换。' : 'This draft differs from the active configuration; submit a key to switch.'
                  : isZh ? '仅为当前登录会话临时启用；保存后输入框立即清空。' : 'Used temporarily for this sign-in session only; the field clears immediately after saving.'}
              value={apiKey}
              autoComplete="off"
              onChange={(event) => setApiKey(event.target.value)}
            />
            <NumberInput
              id="llm-max-tokens"
              label={isZh ? '最大输出 token' : 'Maximum output tokens'}
              decorator={parameterHelp('maxOutputTokens', isZh ? '最大输出 token' : 'Maximum output tokens')}
              min={256}
              max={selectedApplicationOutputLimit ?? 1_048_576}
              step={256}
              value={maxTokens}
              onChange={(_event, state) => {
                const value = Number(state.value);
                if (Number.isFinite(value)) setMaxTokens(Math.round(value));
              }}
            />
          </div>
          {selectedProvider?.integrationValidationStatus === 'CONTRACT_TESTED_COMMUNITY_PREVIEW' ? (
            <div className="provider-preview-warning">
              <InlineNotification
                kind="warning"
                lowContrast
                hideCloseButton
                title={isZh
                  ? '社区预览：尚未使用真实项目 API Key 验证'
                  : 'Community preview: not verified with a real project API key'}
                subtitle={isZh
                  ? '该供应商接入已通过自动化契约测试，但尚未使用真实项目 Key 和账户完成端到端验证；账户区域、模型权限或响应格式仍可能存在差异。欢迎提交脱敏反馈，且请勿粘贴 API Key、令牌、完整请求头、邮箱或其他个人信息。'
                  : 'This provider integration has passed automated contract tests, but has not completed end-to-end verification with a real project key and account. Account region, model access, or response-shape differences may remain. Please share only redacted feedback—never paste API keys, tokens, full request headers, email addresses, or other personal information.'}
              />
              <a
                className="provider-preview-warning__link"
                href={selectedProvider.feedbackIssueUrl}
                target="_blank"
                rel="noreferrer"
              >
                {isZh ? '在 GitHub 提交兼容性 Issue' : 'Open a compatibility issue on GitHub'}
              </a>
            </div>
          ) : null}
          <div className="toggle-with-help">
            {explained('thinkingMode', isZh ? '思考模式' : 'Thinking mode')}
            <Toggle
              id="llm-thinking"
              aria-label={isZh ? '思考模式' : 'Thinking mode'}
              labelA={isZh ? '关闭' : 'Off'}
              labelB={selectedModel?.thinkingAlwaysOn ? isZh ? '始终开启' : 'Always on' : isZh ? '开启' : 'On'}
              toggled={effectiveThinkingSetting(selectedModel, thinkingEnabled)}
              disabled={!selectedModel?.supportsThinking || selectedModel.thinkingAlwaysOn}
              onToggle={(value) => setThinkingEnabled(effectiveThinkingSetting(selectedModel, value))}
            />
          </div>
          <div className="ai-config-actions">
            <Button
              renderIcon={FloppyDisk}
              disabled={!apiKey.trim() || busyAction !== undefined || !isModelCallable(selectedModel)}
              onClick={() => void save()}
            >
              {busyAction === 'save' ? isZh ? '保存中' : 'Saving' : isZh ? '临时用于本次登录' : 'Use for this sign-in'}
            </Button>
            <Button
              kind="tertiary"
              renderIcon={Plug}
              disabled={!hasActiveConfig || busyAction !== undefined}
              onClick={() => void test()}
            >
              {busyAction === 'test'
                ? isZh ? '测试中' : 'Testing'
                : hasUnsavedDraft
                  ? isZh ? '测试已生效配置' : 'Test active configuration'
                  : isZh ? '测试 JSON 输出' : 'Test JSON output'}
            </Button>
            <Button
              kind="danger--tertiary"
              renderIcon={Trash}
              disabled={!config?.configured || busyAction !== undefined}
              onClick={() => void clear()}
            >
              {isZh ? '清除密钥' : 'Clear key'}
            </Button>
          </div>
        </section>

        <aside className="ai-model-panel" aria-labelledby="selected-model-heading">
          <div className="section-heading">
            <h2 id="selected-model-heading">{selectedModel?.name ?? model}</h2>
            <p>{isZh ? '模型能力与价格来自后端固定的官方资料快照；不同供应商的原币种价格不会被混写。' : 'Capabilities and prices come from the backend’s fixed official-source snapshot; each provider keeps its original billing currency.'}</p>
          </div>
          {selectedModel ? (
            <dl className="definition-list">
              <div><dt>{isZh ? '供应商' : 'Provider'}</dt><dd>{selectedProvider?.name ?? selectedModel.provider}</dd></div>
              <div><dt>{isZh ? '服务区域' : 'Service region'}</dt><dd>{localizeRegion(selectedProvider?.region, isZh)}</dd></div>
              <div><dt>{isZh ? '模型 ID' : 'Model ID'}</dt><dd><code>{selectedModel.id}</code></dd></div>
              <div><dt>{isZh ? '上下文' : 'Context'}</dt><dd>{selectedModel.contextTokens.toLocaleString(language)} {isZh ? '个 token' : 'tokens'}</dd></div>
              <div><dt>{isZh ? '本次配置输出上限' : 'Configured output limit'}</dt><dd>{maxTokens.toLocaleString(language)} {isZh ? '个 token' : 'tokens'}</dd></div>
              <div><dt>{isZh ? '应用允许上限' : 'Application limit'}</dt><dd>{selectedApplicationOutputLimit !== undefined ? `${selectedApplicationOutputLimit.toLocaleString(language)} ${isZh ? '个 token' : 'tokens'}` : isZh ? '未核验，禁止调用' : 'Unverified; calls blocked'}</dd></div>
              <div><dt>{isZh ? '官方模型上限' : 'Official model limit'}</dt><dd>{selectedOfficialOutputLimit !== undefined ? `${selectedOfficialOutputLimit.toLocaleString(language)} ${isZh ? '个 token' : 'tokens'}` : isZh ? '未核验' : 'Unverified'}</dd></div>
              <div><dt>{isZh ? '结构化输出' : 'Structured output'}</dt><dd><CheckCircle size={17} weight="fill" /> {localizeStructuredOutput(selectedProvider?.structuredOutputMode, isZh)}</dd></div>
              <div><dt>{isZh ? '函数调用' : 'Function calling'}</dt><dd>{selectedModel.supportsFunctionCalling ? isZh ? '支持' : 'Supported' : isZh ? '不支持' : 'Not supported'}</dd></div>
              <div><dt>{isZh ? '思考模式' : 'Thinking mode'}</dt><dd>{selectedModel.thinkingAlwaysOn ? isZh ? '始终开启' : 'Always on' : selectedModel.supportsThinking ? isZh ? '可选' : 'Optional' : isZh ? '不支持' : 'Not supported'}</dd></div>
              <div><dt>{isZh ? '质量档' : 'Quality tier'}</dt><dd>{localizeQualityTier(selectedModel.qualityTier, isZh)}</dd></div>
              <div><dt>{isZh ? '价格状态' : 'Pricing status'}</dt><dd>{selectedModel.pricingStatus === 'VERIFIED_UPPER_BOUND' ? isZh ? '已核验上界' : 'Verified upper bound' : isZh ? '不可用；调用前关闭' : 'Unavailable; fail-closed'}</dd></div>
              <div><dt>{isZh ? '输入刊例上界' : 'Input list-rate ceiling'}</dt><dd>{formatRate(selectedModel.inputRateUpperPerMillion, selectedModel.billingCurrency, language)}</dd></div>
              <div><dt>{isZh ? '缓存输入价' : 'Cached-input rate'}</dt><dd>{formatRate(selectedModel.cachedInputRatePerMillion, selectedModel.billingCurrency, language)}</dd></div>
              <div><dt>{isZh ? '输出刊例上界' : 'Output list-rate ceiling'}</dt><dd>{formatRate(selectedModel.outputRateUpperPerMillion, selectedModel.billingCurrency, language)}</dd></div>
              <div><dt>{isZh ? '费用闸门输入上界' : 'Cost-gate input reserve'}</dt><dd>{formatRate(selectedModel.budgetInputRateUpperPerMillion, selectedModel.billingCurrency, language)}</dd></div>
              <div><dt>{isZh ? '费用闸门输出上界' : 'Cost-gate output reserve'}</dt><dd>{formatRate(selectedModel.budgetOutputRateUpperPerMillion, selectedModel.billingCurrency, language)}</dd></div>
              <div><dt>{isZh ? '价格核验日期' : 'Pricing verified'}</dt><dd>{selectedModel.pricingVerifiedAt ?? '—'}</dd></div>
            </dl>
          ) : null}
          {selectedProvider ? <Notice>{isZh
            ? '供应商返回的结构化内容仍会经过本地 Schema、证据引用和时间边界校验；供应商原生模式不会绕过这些约束。'
            : 'Provider-structured content still passes local schema, evidence-reference, and time-boundary checks; native provider modes never bypass these constraints.'}</Notice> : null}
          {selectedModel?.thinkingAlwaysOn ? <Notice>{isZh
            ? '该模型由供应商固定启用推理，应用不会把它显示或提交为“关闭”。'
            : 'The provider keeps reasoning enabled for this model; the application never displays or submits it as off.'}</Notice> : null}
          {selectedModel?.legacy ? (
            <InlineNotification
              kind="warning"
              lowContrast
              hideCloseButton
              title={isZh ? '旧模型' : 'Legacy model'}
              subtitle={isZh ? '仅为兼容已有实验保留，不建议用于新实验。' : 'Retained only for compatibility with existing experiments; not recommended for new work.'}
            />
          ) : null}
          {!isModelCallable(selectedModel) ? (
            <InlineNotification
              kind="error"
              lowContrast
              hideCloseButton
              title={selectedModel?.pricingStatus !== 'VERIFIED_UPPER_BOUND'
                ? isZh ? '价格未知，拒绝模型调用' : 'Unpriced model calls are blocked'
                : isZh ? '输出上限未核验，拒绝模型调用' : 'Calls blocked: output cap unverified'}
              subtitle={selectedModel?.pricingStatus !== 'VERIFIED_UPPER_BOUND'
                ? isZh ? '官方公开资料未提供可稳定核验的精确价格；系统不会猜测价格或发送请求。' : 'Official public material does not provide a stable exact price, so the system neither guesses nor dispatches a request.'
                : isZh ? '官方公开资料未给出可独立核验的最大输出上限，因此系统在发送请求前失败关闭。' : 'Official public material does not publish an independently verifiable maximum output limit, so the system fails closed before dispatch.'}
            />
          ) : null}
          {hasActiveConfig ? (
            <div className="credential-state">
              <Key size={20} />
              <div>
                <strong>{isZh ? '当前登录已有临时凭据' : 'Temporary credential active for this sign-in'}</strong>
                <span>{config?.provider ?? '—'} / {config?.model ?? '—'} · {config?.maxTokens ?? '—'} tokens</span>
                <span>{config?.expiresAt ? new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(config.expiresAt)) : ''}</span>
              </div>
            </div>
          ) : (
            <Notice>{isZh ? '未配置密钥时，系统保持可运行并明确降级为规则智能体。' : 'Without a key, the system remains usable and explicitly falls back to rule agents.'}</Notice>
          )}
          <a className="official-doc-link" href={selectedProvider?.documentationUrl} target="_blank" rel="noreferrer">
            {isZh ? `打开 ${selectedProvider?.name ?? '供应商'} 官方文档` : `Open ${selectedProvider?.name ?? 'provider'} official documentation`}
          </a>
          <a className="official-doc-link" href={selectedProvider?.pricingUrl} target="_blank" rel="noreferrer">
            {isZh ? `打开 ${selectedProvider?.name ?? '供应商'} 官方价格页` : `Open ${selectedProvider?.name ?? 'provider'} official pricing`}
          </a>
          <Notice>{isZh
            ? `“刊例上界”用于横向比较；真正的费用硬闸门采用上方“费用闸门输入/输出上界”做预留，并使用后端冻结换算。长上下文倍率、缓存写入倍率等只会抬高预留，缓存优惠、免费额度、折扣或资源包不会放宽上限。目录快照：${catalog?.pricingSnapshotVersion || '—'}。`
            : `List-rate ceilings support comparison; the hard cost gate reserves against the cost-gate input/output bounds shown above and a frozen backend conversion. Long-context or cache-write multipliers may increase the reserve, while cache discounts, free credits, discounts, and bundles never relax it. Catalog snapshot: ${catalog?.pricingSnapshotVersion || '—'}.`}</Notice>
        </aside>
      </div>

      <section className="ai-contract-panel" aria-labelledby="structured-contract-heading">
        <div className="section-heading">
          <h2 id="structured-contract-heading">{isZh ? '结构化输出与系统提示词契约' : 'Structured output and system-prompt contract'}</h2>
          <p>{isZh ? '供应商返回 JSON object 后，后端仍会执行严格本地 Schema、证据 ID、时间边界和动作权限验证。无效输出最多修复一次，然后显式回退。' : 'After the provider returns a JSON object, the backend still enforces strict local schema, evidence-ID, time-boundary, and action-authority validation. Invalid output receives at most one repair attempt before explicit fallback.'}</p>
        </div>
        <div className="prompt-registry-grid">
          {prompts.map((prompt) => (
            <article key={prompt.name}>
              <div><strong>{prompt.name}</strong><StatusBadge status="VERSIONED" /></div>
              <dl className="definition-list definition-list--compact">
                <div><dt>{isZh ? '提示词版本' : 'Prompt version'}</dt><dd><code>{prompt.version}</code></dd></div>
                <div><dt>{isZh ? '输出 Schema' : 'Output schema'}</dt><dd><code>{prompt.schemaVersion}</code></dd></div>
                <div><dt>{isZh ? '内容哈希' : 'Content hash'}</dt><dd><code title={prompt.promptHash}>{prompt.promptHash.slice(0, 20)}</code></dd></div>
              </dl>
            </article>
          ))}
        </div>
        <div className="ai-authority-map">
          <div><span>{isZh ? '允许' : 'Allowed'}</span><p>{isZh ? '抽取候选事实、引用现有证据 ID、更新有限信念、给出受限行动偏好或 ABSTAIN。' : 'Extract candidate facts, cite existing evidence IDs, update bounded beliefs, return a constrained action preference, or ABSTAIN.'}</p></div>
          <div><span>{isZh ? '禁止' : 'Forbidden'}</span><p>{isZh ? '设定价格、提交最终订单、修改账本、访问券商、冻结 Event Pack、调用任意 URL 或把场景当投资建议。' : 'Set prices, submit final orders, mutate the ledger, access a broker, freeze an Event Pack, call arbitrary URLs, or turn a scenario into investment advice.'}</p></div>
          <div><span>{isZh ? '确定性边界' : 'Deterministic boundary'}</span><p>{isZh ? '政策层把目标仓位偏好转换为订单意图；风险、借券、保证金与撮合代码拥有最终决定权。' : 'Policy converts target-position preferences into order intent. Risk, borrow, margin, and matching code retain final authority.'}</p></div>
        </div>
      </section>

      <section className="ai-contract-panel ai-evaluation-panel" aria-labelledby="evaluation-suite-heading">
        <div className="section-heading">
          <h2 id="evaluation-suite-heading">{isZh ? '可执行认知评估' : 'Executable cognition evaluation'}</h2>
          <p>{isZh ? '代码 grader 自检与真实配置模型评估是两种不同证据，界面不会把前者表述为模型质量。' : 'Code-grader self-test and live configured-model evaluation are different evidence. The interface never presents the former as model quality.'}</p>
        </div>
        <div className="ai-evaluation-controls">
          <NumberInput
            id="evaluation-case-count"
            label={isZh ? '固定用例数量' : 'Fixed case count'}
            min={1}
            max={3}
            step={1}
            value={evaluationMaximumCases}
            disabled={evaluationBusy !== undefined}
            onChange={(_event, state) => { const value = Number(state.value); if (Number.isFinite(value)) setEvaluationMaximumCases(Math.max(1, Math.min(3, Math.round(value)))); }}
          />
          <Button kind="tertiary" disabled={evaluationBusy !== undefined} onClick={() => void runEvaluation('CODE_GRADER_SELF_TEST')}>
            {evaluationBusy === 'CODE_GRADER_SELF_TEST' ? isZh ? '自检中' : 'Running self-test' : isZh ? '运行代码 grader 自检' : 'Run code-grader self-test'}
          </Button>
          <Button disabled={!hasActiveConfig || evaluationBusy !== undefined} onClick={() => void runEvaluation('LIVE_CONFIGURED_MODEL')}>
            {evaluationBusy === 'LIVE_CONFIGURED_MODEL' ? isZh ? '评估模型中' : 'Evaluating model' : isZh ? '运行真实配置模型评估' : 'Run live configured-model evaluation'}
          </Button>
        </div>
        {!hasActiveConfig ? <Notice>{isZh ? '真实模型评估需要先为当前登录临时填写供应商和型号的 API Key。Key 不写入账户、数据库或浏览器存储；代码 grader 自检不需要密钥。' : 'Live-model evaluation requires a temporary provider API key for this sign-in. The key is never written to the account, database, or browser storage; the code-grader self-test does not require it.'}</Notice> : null}
        {evaluationRun ? (
          <div className="ai-evaluation-result">
            <div className="ai-evaluation-result__summary">
              <div><span>{isZh ? '评估对象' : 'Evaluated system'}</span><strong>{evaluationRun.evaluatedSystem.replaceAll('_', ' ')}</strong></div>
              <div><span>{isZh ? '套件版本' : 'Suite version'}</span><strong><code>{evaluationRun.suiteVersion}</code></strong></div>
              <div><span>{isZh ? '通过用例' : 'Passed cases'}</span><strong>{evaluationRun.result.passedCases} / {evaluationRun.result.totalCases}</strong></div>
              <div><span>{isZh ? '通过率' : 'Pass rate'}</span><strong>{new Intl.NumberFormat(language, { style: 'percent', maximumFractionDigits: 1 }).format(evaluationRun.result.passRate)}</strong></div>
            </div>
            <InlineNotification
              kind={evaluationRun.mode === 'LIVE_CONFIGURED_MODEL' ? 'info' : 'warning'}
              lowContrast
              hideCloseButton
              title={evaluationRun.mode === 'LIVE_CONFIGURED_MODEL'
                ? isZh ? '真实配置模型的固定用例结果' : 'Fixed-case result for the live configured model'
                : isZh ? '仅验证 grader 接线' : 'Grader wiring only'}
              subtitle={evaluationRun.interpretationBoundary}
            />
            <div className="ai-evaluation-cases">
              {evaluationRun.result.results.map((caseResult) => (
                <details key={caseResult.caseId}>
                  <summary><span><strong>{caseResult.caseId}</strong><small>{isZh ? '得分' : 'Score'} {caseResult.score.toFixed(2)}</small></span><StatusBadge status={caseResult.passed ? 'PASS' : 'FAIL'} /></summary>
                  <ul>{caseResult.checks.map((check) => <li key={check.name}><StatusBadge status={check.passed ? 'PASS' : 'FAIL'} /><div><strong>{check.name}</strong><p>{check.detail}</p></div></li>)}</ul>
                </details>
              ))}
            </div>
            {evaluationRun.modelRuns.length > 0 ? (
              <div className="ai-model-run-grid">
                {evaluationRun.modelRuns.map((run) => <div key={run.caseId}><strong>{run.caseId}</strong><span>{run.model}</span><span>{run.totalTokens ?? 0} tokens / {run.latencyMs !== undefined ? `${Math.round(run.latencyMs)} ms` : t('common.unavailable')}</span><Tag type={run.fallbackUsed ? 'warm-gray' : 'blue'} size="sm">{run.fallbackUsed ? isZh ? '使用回退' : 'Fallback used' : isZh ? '直接输出' : 'Direct output'}</Tag></div>)}
              </div>
            ) : null}
          </div>
        ) : null}
      </section>
    </div>
  );
}
