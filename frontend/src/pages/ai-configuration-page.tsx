import {
  Accordion,
  AccordionItem,
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
  AdvancedModelParameterName,
  AdvancedModelParameters,
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

const ADVANCED_PARAMETER_NAMES: readonly AdvancedModelParameterName[] = [
  'temperature',
  'topP',
  'presencePenalty',
  'frequencyPenalty',
  'seed',
  'timeoutSeconds',
];

const CONSERVATIVE_ADVANCED_PARAMETER_CAPABILITIES: Record<
  LlmProviderId,
  readonly AdvancedModelParameterName[]
> = {
  zhipu: ['temperature', 'topP', 'timeoutSeconds'],
  openai: ['temperature', 'topP', 'timeoutSeconds'],
  anthropic: ['temperature', 'topP', 'timeoutSeconds'],
  google: ADVANCED_PARAMETER_NAMES,
  deepseek: ['temperature', 'topP', 'presencePenalty', 'frequencyPenalty', 'timeoutSeconds'],
  alibaba: ADVANCED_PARAMETER_NAMES,
  moonshot: ['temperature', 'topP', 'presencePenalty', 'frequencyPenalty', 'timeoutSeconds'],
};

export function supportedAdvancedParameters(
  provider: LlmProviderDescriptor | undefined,
): ReadonlySet<AdvancedModelParameterName> {
  if (!provider) return new Set();
  return new Set(
    provider.supportedAdvancedParameters
      ?? CONSERVATIVE_ADVANCED_PARAMETER_CAPABILITIES[provider.id]
      ?? [],
  );
}

function advancedParametersEqual(
  first: AdvancedModelParameters | undefined,
  second: AdvancedModelParameters | undefined,
): boolean {
  return ADVANCED_PARAMETER_NAMES.every((name) => first?.[name] === second?.[name]);
}

function optionalNumber(value: string | number): number | undefined {
  if (String(value).trim() === '') return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
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
  advancedParameters: AdvancedModelParameters = {},
): boolean {
  return Boolean(
    config?.configured
    && config.provider === provider
    && config.model === modelId
    && effectiveThinkingSetting(model, config.thinkingEnabled) === effectiveThinkingSetting(model, thinkingEnabled)
    && config.maxTokens === maxTokens
    && advancedParametersEqual(config.advancedParameters, advancedParameters)
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
  const [advancedParameters, setAdvancedParameters] = useState<AdvancedModelParameters>({});
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
          setAdvancedParameters(configuredModel ? nextConfig.advancedParameters ?? {} : {});
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
  const supportedAdvancedParameterSet = useMemo(
    () => supportedAdvancedParameters(selectedProvider),
    [selectedProvider],
  );
  const hasActiveConfig = Boolean(config?.configured);
  const hasMatchingConfig = configurationMatchesDraft(
    config,
    provider,
    model,
    selectedModel,
    thinkingEnabled,
    maxTokens,
    advancedParameters,
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
    setAdvancedParameters({});
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
        advancedParameters,
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
      {catalog ? (
        <InlineNotification
          kind={catalog.pricingSnapshotStatus === 'CURRENT'
            && catalog.capabilitySnapshotStatus === 'CURRENT' ? 'info' : 'error'}
          lowContrast
          hideCloseButton
          title={isZh ? '价格与能力快照定期校验' : 'Periodic pricing and capability verification'}
          subtitle={isZh
            ? `价格：${catalog.pricingSnapshotStatus ?? 'UNKNOWN'}（有效至 ${catalog.pricingSnapshotValidUntil ?? '未记录'}，周期 ${catalog.pricingReviewCadenceDays ?? '—'} 天）；能力：${catalog.capabilitySnapshotStatus ?? 'UNKNOWN'}（有效至 ${catalog.capabilitySnapshotValidUntil ?? '未记录'}，周期 ${catalog.capabilityReviewCadenceDays ?? '—'} 天）。过期后调用前失败关闭。`
            : `Pricing: ${catalog.pricingSnapshotStatus ?? 'UNKNOWN'} (valid until ${catalog.pricingSnapshotValidUntil ?? 'not recorded'}, ${catalog.pricingReviewCadenceDays ?? '—'}-day cadence); capabilities: ${catalog.capabilitySnapshotStatus ?? 'UNKNOWN'} (valid until ${catalog.capabilitySnapshotValidUntil ?? 'not recorded'}, ${catalog.capabilityReviewCadenceDays ?? '—'}-day cadence). Stale snapshots fail closed before dispatch.`}
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
          {selectedModel && selectedModel.validationEvidence?.liveKeyE2eStatus !== 'PASS' ? (
            <InlineNotification
              kind="warning"
              lowContrast
              hideCloseButton
              title={isZh
                ? '该具体模型尚无真实 Key 端到端通过证据'
                : 'No real-key end-to-end pass is recorded for this exact model'}
              subtitle={isZh
                ? `${selectedProvider?.id ?? provider} / ${selectedModel?.id ?? model} 当前状态为 ${selectedModel?.validationEvidence?.liveKeyE2eStatus ?? 'UNVERIFIED'}；供应商级或 mock 契约测试不会被当作该型号的真实验证。`
                : `${selectedProvider?.id ?? provider} / ${selectedModel?.id ?? model} is ${selectedModel?.validationEvidence?.liveKeyE2eStatus ?? 'UNVERIFIED'}; provider-level or mocked adapter tests are not presented as real validation of this exact model.`}
            />
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
          <Accordion className="advanced-settings" align="start">
            <AccordionItem title={isZh ? '高级请求参数（可选）' : 'Advanced request parameters (optional)'}>
              <p>
                {isZh
                  ? '留空时使用供应商默认值。调整采样参数可能降低跨次调用的一致性；供应商未明确支持的字段会被禁用，后端仍会在发送请求前再次校验。'
                  : 'Leave fields blank to use provider defaults. Sampling changes can reduce consistency across calls. Fields without explicit provider support are disabled, and the backend validates them again before dispatch.'}
              </p>
              <div className="config-form-grid">
                <NumberInput
                  id="llm-temperature"
                  label={isZh ? '随机性（temperature）' : 'Randomness (temperature)'}
                  helperText={supportedAdvancedParameterSet.has('temperature')
                    ? isZh ? '0–2。值越低通常越稳定；不建议同时调整 top P。' : '0–2. Lower values are usually more stable; avoid tuning top P at the same time.'
                    : isZh ? '当前供应商端点未明确支持。' : 'Not explicitly supported by this provider endpoint.'}
                  min={0}
                  max={2}
                  step={0.1}
                  value={advancedParameters.temperature ?? ''}
                  disabled={!supportedAdvancedParameterSet.has('temperature')}
                  onChange={(_event, state) => setAdvancedParameters((current) => ({
                    ...current,
                    temperature: optionalNumber(state.value),
                  }))}
                />
                <NumberInput
                  id="llm-top-p"
                  label={isZh ? '核采样阈值（top P）' : 'Nucleus threshold (top P)'}
                  helperText={supportedAdvancedParameterSet.has('topP')
                    ? isZh ? '大于 0 且不超过 1。通常只调整它或 temperature 之一。' : 'Greater than 0 and at most 1. Usually tune either this or temperature, not both.'
                    : isZh ? '当前供应商端点未明确支持。' : 'Not explicitly supported by this provider endpoint.'}
                  min={0.01}
                  max={1}
                  step={0.05}
                  value={advancedParameters.topP ?? ''}
                  disabled={!supportedAdvancedParameterSet.has('topP')}
                  onChange={(_event, state) => setAdvancedParameters((current) => ({
                    ...current,
                    topP: optionalNumber(state.value),
                  }))}
                />
                <NumberInput
                  id="llm-presence-penalty"
                  label={isZh ? '主题重复惩罚（presence penalty）' : 'Topic repetition penalty (presence penalty)'}
                  helperText={supportedAdvancedParameterSet.has('presencePenalty')
                    ? isZh ? '−2 至 2。正值倾向引入尚未出现的内容。' : '−2 to 2. Positive values favor content not yet mentioned.'
                    : isZh ? '当前供应商端点未明确支持。' : 'Not explicitly supported by this provider endpoint.'}
                  min={-2}
                  max={2}
                  step={0.1}
                  value={advancedParameters.presencePenalty ?? ''}
                  disabled={!supportedAdvancedParameterSet.has('presencePenalty')}
                  onChange={(_event, state) => setAdvancedParameters((current) => ({
                    ...current,
                    presencePenalty: optionalNumber(state.value),
                  }))}
                />
                <NumberInput
                  id="llm-frequency-penalty"
                  label={isZh ? '词频重复惩罚（frequency penalty）' : 'Token repetition penalty (frequency penalty)'}
                  helperText={supportedAdvancedParameterSet.has('frequencyPenalty')
                    ? isZh ? '−2 至 2。正值按既有出现次数抑制重复。' : '−2 to 2. Positive values discourage repetition based on prior frequency.'
                    : isZh ? '当前供应商端点未明确支持。' : 'Not explicitly supported by this provider endpoint.'}
                  min={-2}
                  max={2}
                  step={0.1}
                  value={advancedParameters.frequencyPenalty ?? ''}
                  disabled={!supportedAdvancedParameterSet.has('frequencyPenalty')}
                  onChange={(_event, state) => setAdvancedParameters((current) => ({
                    ...current,
                    frequencyPenalty: optionalNumber(state.value),
                  }))}
                />
                <NumberInput
                  id="llm-seed"
                  label={isZh ? '供应商随机种子（seed）' : 'Provider random seed (seed)'}
                  helperText={supportedAdvancedParameterSet.has('seed')
                    ? isZh ? '0–2,147,483,647。只能提高复现概率，不保证输出完全一致。' : '0–2,147,483,647. It may improve repeatability but cannot guarantee identical output.'
                    : isZh ? '当前供应商端点未明确支持。' : 'Not explicitly supported by this provider endpoint.'}
                  min={0}
                  max={2_147_483_647}
                  step={1}
                  value={advancedParameters.seed ?? ''}
                  disabled={!supportedAdvancedParameterSet.has('seed')}
                  onChange={(_event, state) => {
                    const value = optionalNumber(state.value);
                    setAdvancedParameters((current) => ({
                      ...current,
                      seed: value === undefined ? undefined : Math.round(value),
                    }));
                  }}
                />
                <NumberInput
                  id="llm-timeout-seconds"
                  label={isZh ? '单次请求超时（秒）' : 'Per-request timeout (seconds)'}
                  helperText={supportedAdvancedParameterSet.has('timeoutSeconds')
                    ? isZh ? '1–300 秒。达到上限会中止等待，但不能保证供应商不计费。' : '1–300 seconds. The wait stops at the limit, but provider billing may still occur.'
                    : isZh ? '当前供应商端点未明确支持。' : 'Not explicitly supported by this provider endpoint.'}
                  min={1}
                  max={300}
                  step={1}
                  value={advancedParameters.timeoutSeconds ?? ''}
                  disabled={!supportedAdvancedParameterSet.has('timeoutSeconds')}
                  onChange={(_event, state) => setAdvancedParameters((current) => ({
                    ...current,
                    timeoutSeconds: optionalNumber(state.value),
                  }))}
                />
              </div>
              <Button
                kind="ghost"
                size="sm"
                disabled={ADVANCED_PARAMETER_NAMES.every(
                  (name) => advancedParameters[name] === undefined,
                )}
                onClick={() => setAdvancedParameters({})}
              >
                {isZh ? '恢复供应商默认值' : 'Restore provider defaults'}
              </Button>
              <InlineNotification
                kind="info"
                lowContrast
                hideCloseButton
                title={isZh ? '固定的安全边界' : 'Fixed security boundary'}
                subtitle={isZh
                  ? '不接受自定义 base URL 或请求头，以防止服务端请求伪造（SSRF）和凭据外泄；系统提示词与工具权限由应用版本控制，不能在此改写，以避免权限扩大。API Key 仍只在当前登录的服务器内存中短时保存。'
                  : 'Custom base URLs and headers are not accepted, preventing server-side request forgery (SSRF) and credential leakage. System prompts and tool permissions remain application-versioned and cannot be overridden here, preventing privilege expansion. The API key still lives briefly in server memory for this sign-in only.'}
              />
            </AccordionItem>
          </Accordion>
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
              <div><dt>{isZh ? '价格有效期' : 'Pricing valid until'}</dt><dd>{selectedModel.pricingValidUntil ?? '—'}</dd></div>
            </dl>
          ) : null}
          {selectedModel ? (
            <div className="governance-table-wrap">
              <table className="governance-table">
                <thead><tr><th>{isZh ? '逐模型能力' : 'Per-model capability'}</th><th>{isZh ? '验证状态' : 'Validation status'}</th></tr></thead>
                <tbody>
                  {([
                    ['official documentation', selectedModel.validationEvidence?.officialDocumentationStatus ?? 'UNVERIFIED'],
                    ['adapter contract', selectedModel.validationEvidence?.adapterContractStatus ?? 'NOT_RUN'],
                    ['real-key E2E', selectedModel.validationEvidence?.liveKeyE2eStatus ?? 'NOT_RUN'],
                    ['structured output', selectedModel.validationEvidence?.structuredOutputStatus ?? 'UNVERIFIED'],
                    ['streaming', selectedModel.validationEvidence?.streamingStatus ?? 'UNVERIFIED'],
                    ['thinking + JSON', selectedModel.validationEvidence?.thinkingJsonStatus ?? 'UNVERIFIED'],
                    ['usage / cost', selectedModel.validationEvidence?.usageCostStatus ?? 'UNVERIFIED'],
                  ] as const).map(([capability, status]) => (
                    <tr key={capability}><td>{capability}</td><td><code>{status}</code></td></tr>
                  ))}
                </tbody>
              </table>
              <p>{selectedModel.validationEvidence?.verificationScope
                ?? 'UNKNOWN_MODEL_UNVERIFIED'}</p>
              {selectedModel.validationEvidence?.evidenceSourceUrl ? (
                <a
                  href={selectedModel.validationEvidence.evidenceSourceUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  {isZh ? '打开该型号能力证据' : 'Open exact-model capability evidence'}
                </a>
              ) : null}
            </div>
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
