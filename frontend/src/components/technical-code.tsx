import type { Language } from '../i18n';

const TECHNICAL_CODE_LABELS: Record<string, [english: string, chinese: string]> = {
  CLOSED_LOOP_PILOT_FAILED: ['Cognition pilot could not complete', '认知试运行未能完成'],
  COGNITION_REPEATED_FAILURE_CIRCUIT_OPEN: ['Repeated model failures stopped further calls', '模型连续失败，已停止后续调用'],
  COGNITION_RULE_CONTINUATION_REQUESTED: ['The remaining cognition used deterministic rules', '剩余认知过程已改用确定性规则'],
  CREDENTIAL_PATTERN: ['The response resembled a credential', '回复疑似包含凭据格式'],
  DATABASE_COMMIT_PENDING: ['Waiting to save the validated candidate', '正在等待保存已校验候选'],
  DANGEROUS_URL: ['The response contained an unsafe link', '回复包含不安全链接'],
  DETERMINISTIC_PROPOSAL_READY: ['A deterministic proposal is ready for review', '确定性候选已可供审核'],
  EXTRACTION_NOT_ELIGIBLE: ['This source is not eligible for evidence extraction', '该来源暂不符合证据抽取条件'],
  FALLBACK_USED: ['A safe fallback was used', '已使用安全回退'],
  HYBRID_LLM_PARTIAL_RULE_FALLBACK: ['Some cognition decisions used deterministic rules after model validation failed', '部分认知决策在模型校验失败后改用确定性规则'],
  INVISIBLE_CONTROL: ['The response contained invisible control characters', '回复包含不可见控制字符'],
  LICENSE_REVIEW_REQUIRED_FOR_REDISTRIBUTION: ['Redistribution permission requires human review', '公开再分发许可仍需人工审核'],
  LLM_CALL_BUDGET_TOO_SMALL: ['The model-call budget is too small', '模型调用预算不足'],
  LLM_COST_CAP_INSUFFICIENT: ['The cost cap cannot reserve a safe model call', '费用上限不足以安全预留一次模型调用'],
  LLM_CREDENTIAL_NOT_CONFIGURED: ['No model credential is configured for this session', '当前会话尚未配置模型凭据'],
  LLM_CREDENTIAL_STORAGE_UNAVAILABLE: ['Secure credential storage is unavailable', '安全凭据存储暂不可用'],
  LLM_OUTPUT_LIMIT_UNAVAILABLE: ['The provider output limit is unavailable', '供应商输出上限信息不可用'],
  LLM_PRICE_UNAVAILABLE: ['Verified model pricing is unavailable', '模型价格尚未通过核验'],
  LLM_PROVIDER_MODEL_CONFIG_MISMATCH: ['The configured provider and model do not match', '已配置的供应商与模型不匹配'],
  MODEL_PRICING_UNAVAILABLE: ['Verified model pricing is unavailable', '模型价格尚未通过核验'],
  MODELGATEWAYERROR: ['The model service could not complete the request', '模型服务未能完成请求'],
  MODEL_RESPONSE_INVALID: ['The model response could not be validated', '模型回复未通过校验'],
  MODEL_TIMEOUT: ['The model did not respond before the timeout', '模型未在超时时间内返回'],
  MODEL_USAGE_MISSING: ['The provider did not return auditable usage', '供应商未返回可审计用量'],
  NO_APPROVED_EVIDENCE: ['No approved evidence is available', '没有可用的已批准证据'],
  PROMPT_CONTROL_LANGUAGE: ['The response exposed control-instruction language', '回复疑似暴露控制指令'],
  PROMPT_DISCLOSURE_BLOCKED: ['The response was blocked by prompt-disclosure protection', '回复被提示词泄露防护拦截'],
  PROMPT_FRAGMENT_OVERLAP: ['The response overlapped protected instructions', '回复与受保护指令存在重复'],
  PROMPT_NGRAM_OVERLAP: ['The response resembled protected instruction text', '回复疑似复述受保护指令'],
  PROVIDER_DISPATCHED: ['Model request sent to the provider', '模型请求已发送给供应商'],
  PROVIDER_REQUEST: ['The model provider request did not complete normally', '模型供应商请求未正常完成'],
  PROTECTED_SECRET: ['The response matched a protected secret', '回复疑似包含受保护秘密'],
  RAW_HTML: ['The response contained unsafe raw HTML', '回复包含不安全的原始 HTML'],
  REPAIRING: ['The server was validating a repaired model response', '服务器正在校验修复后的模型回复'],
  RULE_FALLBACK_USED: ['A deterministic rule completed this decision', '本次决策由确定性规则完成'],
  SAFETY_OR_REFUSAL: ['The provider refused or safety checks blocked the response', '供应商拒绝回复或安全检查将其拦截'],
  SCHEMA_INVALID: ['The structured response did not match the required format', '结构化回复不符合规定格式'],
  SIMULATION_FAILED: ['The simulation stopped safely after an error', '仿真发生错误并已安全停止'],
  TRANSPORT_FAILURE: ['The provider request could not complete', '供应商请求未能完成'],
  UNKNOWN: ['An unclassified technical condition occurred', '发生了尚未分类的技术状况'],
  UNKNOWN_AFTER_DISPATCH: ['The request outcome is unknown after dispatch', '请求发出后的结果尚无法确认'],
};

const TECHNICAL_TOKEN_PATTERN = /\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/g;

function fallbackTechnicalCodeLabel(code: string, language: Language): string {
  const words = code
    .trim()
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .toLowerCase()
    .split(/[_\s-]+/)
    .filter(Boolean)
    .join(' ');
  if (!words) return language === 'zh-CN' ? '未报告具体原因' : 'No specific reason reported';
  return language === 'zh-CN'
    ? `未收录的技术状态：${words}`
    : `${words.charAt(0).toUpperCase()}${words.slice(1)}`;
}

export function technicalCodeLabel(code: string | undefined, language: Language): string {
  if (!code) return language === 'zh-CN' ? '未报告具体原因' : 'No specific reason reported';
  const normalized = code.trim().toUpperCase();
  return TECHNICAL_CODE_LABELS[normalized]?.[language === 'zh-CN' ? 1 : 0]
    ?? fallbackTechnicalCodeLabel(code, language);
}

export function humanizeTechnicalText(value: string | undefined, language: Language): string {
  if (!value) return technicalCodeLabel(undefined, language);
  return value.replace(TECHNICAL_TOKEN_PATTERN, (code) => technicalCodeLabel(code, language));
}

export function extractTechnicalCodes(value: string | undefined): string[] {
  if (!value) return [];
  return [...new Set(value.match(TECHNICAL_TOKEN_PATTERN) ?? [])];
}

export function TechnicalCodeDisplay({
  codes,
  language,
}: {
  codes: Array<string | undefined>;
  language: Language;
}) {
  const uniqueCodes = [...new Set(codes.filter((code): code is string => Boolean(code?.trim())))];
  if (uniqueCodes.length === 0) return <span>{technicalCodeLabel(undefined, language)}</span>;
  return (
    <span className="technical-code-display">
      <span>{uniqueCodes.map((code) => technicalCodeLabel(code, language)).join(language === 'zh-CN' ? '；' : '; ')}</span>
      <details className="technical-code-display__details">
        <summary>{language === 'zh-CN' ? '技术详情' : 'Technical details'}</summary>
        <code>{uniqueCodes.join(', ')}</code>
      </details>
    </span>
  );
}
