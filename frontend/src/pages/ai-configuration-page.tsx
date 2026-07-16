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
  PromptRegistryItem,
} from '../api/types';
import { ErrorPanel, LoadingPanel, Notice, PageHeader, StatusBadge } from '../components/common';
import { useI18n } from '../i18n';

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function AiConfigurationPage() {
  const { language, t } = useI18n();
  const isZh = language === 'zh-CN';
  const [catalog, setCatalog] = useState<LlmCatalog>();
  const [config, setConfig] = useState<LlmConfigView>();
  const [prompts, setPrompts] = useState<PromptRegistryItem[]>([]);
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
      if (nextConfig.model) setModel(nextConfig.model);
      if (nextConfig.thinkingEnabled !== undefined) setThinkingEnabled(nextConfig.thinkingEnabled);
      if (nextConfig.maxTokens) setMaxTokens(nextConfig.maxTokens);
    } catch (loadError) {
      setError(messageOf(loadError));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const selectedModel = useMemo(
    () => catalog?.models.find((item) => item.id === model),
    [catalog, model],
  );

  const save = async () => {
    setBusyAction('save');
    setError(undefined);
    setTestResult(undefined);
    try {
      const nextConfig = await api.saveLlmConfig({
        provider: 'zhipu',
        model,
        apiKey,
        thinkingEnabled,
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
          subtitle={isZh ? '正在加载智谱模型目录。' : 'Loading the Zhipu model catalog.'}
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
          ? '配置用于证据抽取与代表性认知智能体的智谱 API。密钥只在本服务器内存中短时保存。'
          : 'Configure Zhipu API access for evidence extraction and representative cognitive agents. The key remains only in short-lived server memory.'}
        actions={<StatusBadge status={config?.configured ? 'CONFIGURED' : 'RULE ONLY'} />}
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
          subtitle={`${testResult.message}${testResult.latencyMs ? ` (${Math.round(testResult.latencyMs)} ms)` : ''}`}
        />
      ) : null}

      <div className="ai-config-layout">
        <section className="ai-config-panel" aria-labelledby="provider-settings-heading">
          <div className="section-heading">
            <h2 id="provider-settings-heading">{isZh ? '供应商与凭据' : 'Provider and credential'}</h2>
            <p>{isZh ? '浏览器只把密钥发送到同源后端，不直接请求智谱。' : 'The browser sends the key only to the same-origin backend and never calls Zhipu directly.'}</p>
          </div>
          <div className="config-form-grid">
            <TextInput
              id="llm-provider"
              labelText={isZh ? '供应商' : 'Provider'}
              value="Zhipu AI"
              readOnly
            />
            <Select
              id="llm-model"
              labelText={isZh ? '模型' : 'Model'}
              value={model}
              onChange={(event) => {
                setModel(event.target.value);
                const descriptor = catalog?.models.find((item) => item.id === event.target.value);
                if (descriptor && !descriptor.supportsThinking) setThinkingEnabled(false);
              }}
            >
              {catalog?.models.map((item) => (
                <SelectItem
                  key={item.id}
                  value={item.id}
                  disabled={item.pricingStatus !== 'VERIFIED_UPPER_BOUND'}
                  text={`${item.name}${item.recommended ? isZh ? '（推荐）' : ' (Recommended)' : ''}${item.freeTier ? isZh ? '（免费层）' : ' (Free tier)' : ''}${item.pricingStatus !== 'VERIFIED_UPPER_BOUND' ? isZh ? '（价格未知，禁止调用）' : ' (Unpriced — blocked)' : ''}`}
                />
              ))}
            </Select>
            <TextInput
              id="llm-api-key"
              type="password"
              labelText={isZh ? '智谱 API Key' : 'Zhipu API key'}
              helperText={config?.configured
                ? `${isZh ? '当前配置' : 'Current credential'}: ${config.credentialHint ?? 'hidden'}`
                : isZh ? '保存后输入框会立即清空。' : 'The field clears immediately after saving.'}
              value={apiKey}
              autoComplete="off"
              onChange={(event) => setApiKey(event.target.value)}
            />
            <NumberInput
              id="llm-max-tokens"
              label={isZh ? '最大输出 token' : 'Maximum output tokens'}
              min={256}
              max={Math.min(selectedModel?.maxOutputTokens ?? 131_072, 32_768)}
              step={256}
              value={maxTokens}
              onChange={(_event, state) => {
                const value = Number(state.value);
                if (Number.isFinite(value)) setMaxTokens(Math.round(value));
              }}
            />
          </div>
          <Toggle
            id="llm-thinking"
            labelText={isZh ? '思考模式' : 'Thinking mode'}
            labelA={isZh ? '关闭' : 'Off'}
            labelB={isZh ? '开启' : 'On'}
            toggled={thinkingEnabled}
            disabled={!selectedModel?.supportsThinking}
            onToggle={setThinkingEnabled}
          />
          <div className="ai-config-actions">
            <Button
              renderIcon={FloppyDisk}
              disabled={!apiKey.trim() || busyAction !== undefined || selectedModel?.pricingStatus !== 'VERIFIED_UPPER_BOUND'}
              onClick={() => void save()}
            >
              {busyAction === 'save' ? isZh ? '保存中' : 'Saving' : isZh ? '保存到会话' : 'Save for session'}
            </Button>
            <Button
              kind="tertiary"
              renderIcon={Plug}
              disabled={!config?.configured || busyAction !== undefined}
              onClick={() => void test()}
            >
              {busyAction === 'test' ? isZh ? '测试中' : 'Testing' : isZh ? '测试 JSON 输出' : 'Test JSON output'}
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
            <p>{isZh ? '模型能力来自后端固定的官方目录。' : 'Capabilities come from the backend official model catalog.'}</p>
          </div>
          {selectedModel ? (
            <dl className="definition-list">
              <div><dt>{isZh ? '模型 ID' : 'Model ID'}</dt><dd><code>{selectedModel.id}</code></dd></div>
              <div><dt>{isZh ? '上下文' : 'Context'}</dt><dd>{selectedModel.contextTokens.toLocaleString(language)} {isZh ? '个 token' : 'tokens'}</dd></div>
              <div><dt>{isZh ? '最大输出' : 'Maximum output'}</dt><dd>{selectedModel.maxOutputTokens.toLocaleString(language)} {isZh ? '个 token' : 'tokens'}</dd></div>
              <div><dt>{isZh ? 'JSON 对象' : 'JSON object'}</dt><dd><CheckCircle size={17} weight="fill" /> {isZh ? '支持' : 'Supported'}</dd></div>
              <div><dt>{isZh ? '函数调用' : 'Function calling'}</dt><dd>{selectedModel.supportsFunctionCalling ? isZh ? '支持' : 'Supported' : isZh ? '不支持' : 'Not supported'}</dd></div>
              <div><dt>{isZh ? '思考模式' : 'Thinking mode'}</dt><dd>{selectedModel.supportsThinking ? isZh ? '支持' : 'Supported' : isZh ? '不支持' : 'Not supported'}</dd></div>
              <div><dt>{isZh ? '价格状态' : 'Pricing status'}</dt><dd>{selectedModel.pricingStatus === 'VERIFIED_UPPER_BOUND' ? isZh ? '已核验上界' : 'Verified upper bound' : isZh ? '不可用；调用前关闭' : 'Unavailable; fail-closed'}</dd></div>
              {selectedModel.inputRateUpperCnyPerMillion !== undefined ? <div><dt>{isZh ? '输入刊例上界' : 'Input list-rate ceiling'}</dt><dd>¥{selectedModel.inputRateUpperCnyPerMillion} / 1M tokens</dd></div> : null}
              {selectedModel.outputRateUpperCnyPerMillion !== undefined ? <div><dt>{isZh ? '输出刊例上界' : 'Output list-rate ceiling'}</dt><dd>¥{selectedModel.outputRateUpperCnyPerMillion} / 1M tokens</dd></div> : null}
            </dl>
          ) : null}
          {selectedModel?.legacy ? (
            <InlineNotification
              kind="warning"
              lowContrast
              hideCloseButton
              title={isZh ? '旧模型' : 'Legacy model'}
              subtitle={selectedModel.deprecationNote ?? (isZh ? '不建议用于新实验。' : 'Not recommended for new experiments.')}
            />
          ) : null}
          {selectedModel?.pricingStatus !== 'VERIFIED_UPPER_BOUND' ? (
            <InlineNotification
              kind="error"
              lowContrast
              hideCloseButton
              title={isZh ? '价格未知，拒绝模型调用' : 'Unpriced model calls are blocked'}
              subtitle={isZh ? '官方公开页面未提供可稳定核验的精确 token 单价；系统不会猜价，也不会保存该型号用于真实调用。' : 'The official public page does not provide a stable exact token rate. The system will neither invent a price nor save this model for live calls.'}
            />
          ) : null}
          {config?.configured ? (
            <div className="credential-state">
              <Key size={20} />
              <div>
                <strong>{isZh ? '会话凭据已配置' : 'Session credential configured'}</strong>
                <span>{config.expiresAt ? new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(config.expiresAt)) : ''}</span>
              </div>
            </div>
          ) : (
            <Notice>{isZh ? '未配置密钥时，系统保持可运行并明确降级为规则智能体。' : 'Without a key, the system remains usable and explicitly falls back to rule agents.'}</Notice>
          )}
          <a className="official-doc-link" href={catalog?.documentationUrl} target="_blank" rel="noreferrer">
            {isZh ? '打开智谱官方文档' : 'Open official Zhipu documentation'}
          </a>
          <a className="official-doc-link" href={catalog?.pricingUrl} target="_blank" rel="noreferrer">
            {isZh ? '打开智谱官方价格页' : 'Open official Zhipu pricing'}
          </a>
          <Notice>{isZh
            ? `硬上限采用公开人民币刊例价的最高分档，并以 ¥${catalog?.cnyPerUsdBudgetFloor.toFixed(2) ?? '—'}/$ 的保守冻结换算记账；它不包含税费、支付手续费、折扣或资源包。`
            : `The hard cap uses the highest public CNY list-price tier and a conservative frozen ¥${catalog?.cnyPerUsdBudgetFloor.toFixed(2) ?? '—'}/$ conversion. Taxes, payment fees, discounts, and bundles are excluded.`}</Notice>
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
          <p>{isZh ? '代码 grader 自检与真实智谱模型评估是两种不同证据，界面不会把前者表述为模型质量。' : 'Code-grader self-test and live Zhipu evaluation are different evidence. The interface never presents the former as model quality.'}</p>
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
          <Button disabled={!config?.configured || evaluationBusy !== undefined} onClick={() => void runEvaluation('LIVE_CONFIGURED_MODEL')}>
            {evaluationBusy === 'LIVE_CONFIGURED_MODEL' ? isZh ? '评估模型中' : 'Evaluating model' : isZh ? '运行真实智谱模型评估' : 'Run live Zhipu evaluation'}
          </Button>
        </div>
        {!config?.configured ? <Notice>{isZh ? '真实模型评估需要先保存当前会话的智谱 API Key。代码 grader 自检不需要密钥。' : 'Live-model evaluation requires a session-scoped Zhipu API key. The code-grader self-test does not require a key.'}</Notice> : null}
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
