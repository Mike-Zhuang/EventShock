import {
  normalizeAdminActivityPage,
  normalizeAdminUserPage,
  normalizeAuthSession,
  normalizeCases,
  normalizeCognitionEvalSummary,
  normalizeCognitionEvaluationRun,
  normalizeCognitionTelemetry,
  normalizeEventPack,
  normalizeExperiment,
  normalizeExperiments,
  normalizeGovernanceInventory,
  normalizeLlmCatalog,
  normalizeLlmConfig,
  normalizeLlmConnectionTest,
  normalizePromptRegistry,
  normalizeResults,
  normalizeRedTeamRegistry,
  normalizeReleaseGate,
  normalizeResultInterpretationChatResponse,
  normalizeResultInterpretationConversation,
  normalizeResultInterpretationConversationDeleteResult,
  normalizeResultInterpretationConversationList,
  normalizeResultInterpretationStreamError,
  normalizeResultInterpretationStreamProgress,
  normalizeSavedScenario,
  normalizeSavedScenarios,
  normalizeScenarioDiff,
  normalizeStudyDesignPreview,
  normalizeStudyPresetCatalog,
  normalizeStudyRun,
  normalizeStudyRuns,
  normalizeSystemMetrics,
  normalizeValidationLadder,
  normalizeValidation,
  normalizeVerificationCodeReceipt,
} from './normalize';
import type {
  AdminActivityPage,
  AdminUserPage,
  AuthSession,
  BulkClaimApprovalInput,
  CaseSummary,
  ClaimReviewInput,
  EventPack,
  EventPackCreateInput,
  EventSourceUpload,
  Experiment,
  ExperimentResults,
  CognitionEvalSummary,
  CognitionEvaluationRun,
  CognitionTelemetry,
  GovernanceInventory,
  HealthStatus,
  InvalidationReasonCode,
  LlmCatalog,
  LlmConfigInput,
  LlmConfigView,
  LlmConnectionTest,
  PromptRegistryItem,
  RedTeamRegistry,
  ReleaseGateView,
  ResultInterpretationChatInput,
  ResultInterpretationChatResponse,
  ResultInterpretationConversation,
  ResultInterpretationConversationDeleteResult,
  ResultInterpretationConversationList,
  ResultInterpretationStreamErrorPayload,
  ResultInterpretationStreamResult,
  ResultInterpretationStreamUpdate,
  SavedScenario,
  ScenarioDiffResult,
  ScenarioDraft,
  ScenarioValidation,
  StudyDesignPreview,
  StudyDesignPreviewInput,
  StudyPresetCatalog,
  StudyRunInput,
  StudyRunRecord,
  SystemMetrics,
  ValidationLadderView,
  VerificationCodeReceipt,
  VerificationPurpose,
} from './types';

const API_BASE = '/api';
const SESSION_STORAGE_KEY = 'eventshockSessionId';
export const AUTH_SESSION_EXPIRED_EVENT = 'eventshock:auth-session-expired';

let csrfToken: string | undefined;

export function setCsrfToken(nextToken?: string): void {
  csrfToken = nextToken;
}

function getSessionId(): string {
  const existing = window.localStorage.getItem(SESSION_STORAGE_KEY);
  if (existing) return existing;
  const sessionId = crypto.randomUUID();
  window.localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
  return sessionId;
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail?: string;
  readonly code?: string;
  readonly traceId?: string;
  readonly retryable?: boolean;
  readonly uncertainBillableAttempts?: number;

  constructor(
    message: string,
    status: number,
    detail?: string,
    code?: string,
    traceId?: string,
    metadata: { retryable?: boolean; uncertainBillableAttempts?: number } = {},
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.code = code;
    this.traceId = traceId;
    this.retryable = metadata.retryable;
    this.uncertainBillableAttempts = metadata.uncertainBillableAttempts;
  }
}

export class ResultInterpretationStreamError extends ApiError {
  readonly retryable: boolean;
  readonly uncertainBillableAttempts: number;

  constructor(payload: ResultInterpretationStreamErrorPayload) {
    super(payload.message, payload.httpStatus, payload.message, payload.code, payload.traceId);
    this.name = 'ResultInterpretationStreamError';
    this.retryable = payload.retryable;
    this.uncertainBillableAttempts = payload.uncertainBillableAttempts;
  }
}

interface RequestOptions extends RequestInit {
  timeoutMs?: number;
  broadcastUnauthorized?: boolean;
}

async function requestJson(path: string, options: RequestOptions = {}): Promise<unknown> {
  const {
    timeoutMs = 12_000,
    broadcastUnauthorized = true,
    ...requestOptions
  } = options;
  const controller = new AbortController();
  const callerSignal = requestOptions.signal;
  const abortFromCaller = () => controller.abort(callerSignal?.reason);
  if (callerSignal?.aborted) abortFromCaller();
  else callerSignal?.addEventListener('abort', abortFromCaller, { once: true });
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const method = (requestOptions.method ?? 'GET').toUpperCase();
    const isWrite = !['GET', 'HEAD', 'OPTIONS'].includes(method);
    const response = await fetch(`${API_BASE}${path}`, {
      ...requestOptions,
      credentials: requestOptions.credentials ?? 'same-origin',
      headers: {
        Accept: 'application/json',
        'X-Session-ID': getSessionId(),
        ...(requestOptions.body ? { 'Content-Type': 'application/json' } : {}),
        ...(isWrite && csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
        ...requestOptions.headers,
      },
      signal: controller.signal,
    });
    const contentType = response.headers.get('content-type') ?? '';
    const payload = contentType.includes('application/json') ? await response.json() as unknown : await response.text();
    if (!response.ok) {
      if (response.status === 401 && broadcastUnauthorized) {
        window.dispatchEvent(new Event(AUTH_SESSION_EXPIRED_EVENT));
      }
      const payloadRecord = typeof payload === 'object' && payload !== null ? payload as Record<string, unknown> : undefined;
      const nestedError = payloadRecord && typeof payloadRecord.error === 'object' && payloadRecord.error !== null
        ? payloadRecord.error as Record<string, unknown>
        : undefined;
      const detail = typeof payload === 'string'
        ? payload
        : typeof nestedError?.message === 'string'
          ? nestedError.message
          : typeof payloadRecord?.detail === 'string'
            ? payloadRecord.detail
            : undefined;
      const code = typeof nestedError?.code === 'string' ? nestedError.code : undefined;
      const traceId = typeof nestedError?.traceId === 'string' ? nestedError.traceId : undefined;
      const retryable = typeof nestedError?.retryable === 'boolean' ? nestedError.retryable : undefined;
      const rawUncertainBillableAttempts = nestedError?.uncertainBillableAttempts
        ?? nestedError?.uncertain_billable_attempts;
      const uncertainBillableAttempts = typeof rawUncertainBillableAttempts === 'number'
        && Number.isInteger(rawUncertainBillableAttempts)
        && rawUncertainBillableAttempts >= 0
        ? rawUncertainBillableAttempts
        : undefined;
      throw new ApiError(
        detail ?? `API request failed with status ${response.status}.`,
        response.status,
        detail,
        code,
        traceId,
        { retryable, uncertainBillableAttempts },
      );
    }
    return payload;
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      if (callerSignal?.aborted) throw error;
      throw new ApiError('API request timed out.', 408);
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
    callerSignal?.removeEventListener('abort', abortFromCaller);
  }
}

const RESULT_INTERPRETATION_STREAM_FALLBACK_STATUSES = new Set([404, 405, 406, 501]);
// 后续追问可能依次经过 Planner 与回答（各自包含一次结构修复），理论上会贴近
// 旧的 290 秒绝对上限。SSE 用心跳驱动的无活动超时，并另设防失控硬上限。
const RESULT_INTERPRETATION_INACTIVITY_TIMEOUT_MS = 30_000;
const RESULT_INTERPRETATION_HARD_TIMEOUT_MS = 600_000;
const RESULT_INTERPRETATION_SSE_MAX_FRAME_CHARACTERS = 256_000;
const RESULT_INTERPRETATION_SSE_MAX_BUFFER_CHARACTERS = 512_000;

async function requestResultInterpretationJson(
  experimentId: string,
  input: ResultInterpretationChatInput,
  signal?: AbortSignal,
): Promise<ResultInterpretationChatResponse> {
  let rawResponse: unknown;
  try {
    rawResponse = await requestJson(
      `/v1/experiments/${encodeURIComponent(experimentId)}/interpretation-chat`,
      {
        method: 'POST',
        body: JSON.stringify(input),
        // 推理模型可能需要较长首字节时间，但仍必须有明确的客户端上限。
        timeoutMs: RESULT_INTERPRETATION_HARD_TIMEOUT_MS,
        signal,
      },
    );
  } catch (error) {
    if (error instanceof ResultInterpretationStreamError) throw error;
    if (error instanceof ApiError) {
      throw new ResultInterpretationStreamError({
        code: error.code ?? (error.status === 408
          ? 'RESULT_INTERPRETATION_STREAM_TIMEOUT'
          : 'RESULT_INTERPRETATION_JSON_HTTP_ERROR'),
        message: error.message,
        retryable: error.retryable
          ?? (error.status === 408 || error.status === 429 || error.status >= 500),
        httpStatus: error.status,
        // POST 超时无法确认供应商是否已完成，必须采用保守计费提示。
        uncertainBillableAttempts: error.uncertainBillableAttempts
          ?? (error.status === 408 ? 1 : 0),
        traceId: error.traceId,
      });
    }
    if (error instanceof TypeError) {
      throw new ResultInterpretationStreamError({
        code: 'RESULT_INTERPRETATION_STREAM_INTERRUPTED',
        message: 'Interpretation JSON connection could not be completed.',
        retryable: true,
        httpStatus: 502,
        // fetch 的网络 TypeError 发生在 POST 发出之后，是否到达供应商不可知。
        uncertainBillableAttempts: 1,
      });
    }
    if (error instanceof SyntaxError) {
      throw new ResultInterpretationStreamError({
        code: 'RESULT_INTERPRETATION_STREAM_CONTRACT_INVALID',
        message: 'Interpretation JSON response was not valid JSON.',
        retryable: true,
        httpStatus: 502,
        uncertainBillableAttempts: 1,
      });
    }
    throw error;
  }
  try {
    return normalizeResultInterpretationChatResponse(rawResponse);
  } catch (error) {
    if (error instanceof TypeError || error instanceof SyntaxError) {
      throw new ResultInterpretationStreamError({
        code: 'RESULT_INTERPRETATION_STREAM_CONTRACT_INVALID',
        message: 'Interpretation JSON response did not match the required contract.',
        retryable: true,
        httpStatus: 502,
        // 已收到成功 HTTP 响应但无法采用，供应商调用很可能已经发生。
        uncertainBillableAttempts: 1,
      });
    }
    throw error;
  }
}

async function resultInterpretationHttpError(response: Response): Promise<ResultInterpretationStreamError> {
  let rawPayload: unknown;
  try {
    rawPayload = await response.json();
  } catch {
    rawPayload = undefined;
  }
  const payloadRecord = typeof rawPayload === 'object' && rawPayload !== null
    ? rawPayload as Record<string, unknown>
    : undefined;
  const errorRecord = payloadRecord && typeof payloadRecord.error === 'object'
    && payloadRecord.error !== null
    ? payloadRecord.error as Record<string, unknown>
    : payloadRecord;
  const code = typeof errorRecord?.code === 'string'
    ? errorRecord.code
    : 'RESULT_INTERPRETATION_STREAM_HTTP_ERROR';
  const message = typeof errorRecord?.message === 'string'
    ? errorRecord.message
    : `Interpretation stream request failed with status ${response.status}.`;
  const retryable = typeof errorRecord?.retryable === 'boolean'
    ? errorRecord.retryable
    : response.status === 408 || response.status === 429 || response.status >= 500;
  const rawUncertainBillableAttempts = errorRecord?.uncertainBillableAttempts
    ?? errorRecord?.uncertain_billable_attempts;
  const uncertainBillableAttempts = typeof rawUncertainBillableAttempts === 'number'
    && Number.isInteger(rawUncertainBillableAttempts)
    && rawUncertainBillableAttempts >= 0
    ? rawUncertainBillableAttempts
    : 0;
  const traceId = typeof errorRecord?.traceId === 'string' ? errorRecord.traceId : undefined;
  return new ResultInterpretationStreamError({
    code,
    message,
    retryable,
    httpStatus: response.status,
    uncertainBillableAttempts,
    traceId,
  });
}

export const api = {
  async getHealth(): Promise<HealthStatus> {
    const payload = await requestJson('/health', { timeoutMs: 5_000 });
    if (typeof payload !== 'object' || payload === null) return { status: 'unknown' };
    const record = payload as Record<string, unknown>;
    return {
      status: typeof record.status === 'string' ? record.status : 'unknown',
      service: typeof record.service === 'string' ? record.service : undefined,
      version: typeof record.version === 'string' ? record.version : undefined,
    };
  },

  async getAuthSession(): Promise<AuthSession> {
    return normalizeAuthSession(await requestJson('/v1/auth/session', {
      timeoutMs: 8_000,
      broadcastUnauthorized: false,
    }));
  },

  async login(input: { email: string; password: string; language: 'en' | 'zh-CN' }): Promise<AuthSession> {
    return normalizeAuthSession(await requestJson('/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify(input),
      broadcastUnauthorized: false,
    }));
  },

  async logout(): Promise<void> {
    await requestJson('/v1/auth/logout', { method: 'POST' });
  },

  async requestVerificationCode(input: {
    email: string;
    purpose: VerificationPurpose;
    language: 'en' | 'zh-CN';
  }): Promise<VerificationCodeReceipt> {
    return normalizeVerificationCodeReceipt(await requestJson('/v1/auth/verification-code', {
      method: 'POST',
      body: JSON.stringify(input),
      broadcastUnauthorized: false,
    }));
  },

  async register(input: {
    email: string;
    password: string;
    verificationCode: string;
    language: 'en' | 'zh-CN';
  }): Promise<AuthSession> {
    return normalizeAuthSession(await requestJson('/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify(input),
      broadcastUnauthorized: false,
    }));
  },

  async resetPassword(input: {
    email: string;
    password: string;
    verificationCode: string;
    language: 'en' | 'zh-CN';
  }): Promise<void> {
    await requestJson('/v1/auth/password-reset', {
      method: 'POST',
      body: JSON.stringify(input),
      broadcastUnauthorized: false,
    });
  },

  async getAdminUsers(limit = 25, offset = 0): Promise<AdminUserPage> {
    const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    return normalizeAdminUserPage(await requestJson(`/v1/admin/users?${query.toString()}`));
  },

  async getAdminActivity(limit = 50, offset = 0, userId?: string): Promise<AdminActivityPage> {
    const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (userId) query.set('userId', userId);
    return normalizeAdminActivityPage(await requestJson(`/v1/admin/activity?${query.toString()}`));
  },

  async getCases(): Promise<CaseSummary[]> {
    return normalizeCases(await requestJson('/v1/cases'));
  },

  async getEventPack(eventPackId: string): Promise<EventPack> {
    return normalizeEventPack(await requestJson(`/v1/event-packs/${encodeURIComponent(eventPackId)}`));
  },

  async createEventPack(input: EventPackCreateInput): Promise<EventPack> {
    return normalizeEventPack(await requestJson('/v1/event-packs', {
      method: 'POST',
      body: JSON.stringify(input),
      timeoutMs: 45_000,
    }));
  },

  async reextractEventPack(
    eventPackId: string,
    sources: EventSourceUpload[],
    useLlm = true,
    maximumClaims = 16,
    acknowledgedContentReview = false,
  ): Promise<EventPack> {
    return normalizeEventPack(await requestJson(`/v1/event-packs/${encodeURIComponent(eventPackId)}/extract`, {
      method: 'POST',
      body: JSON.stringify({ useLlm, maximumClaims, sources, acknowledgedContentReview }),
      timeoutMs: 70_000,
    }));
  },

  async getLlmCatalog(): Promise<LlmCatalog> {
    return normalizeLlmCatalog(await requestJson('/v1/models'));
  },

  async getPromptRegistry(): Promise<PromptRegistryItem[]> {
    return normalizePromptRegistry(await requestJson('/v1/prompts'));
  },

  async getLlmConfig(): Promise<LlmConfigView> {
    return normalizeLlmConfig(await requestJson('/v1/llm/config'));
  },

  async saveLlmConfig(input: LlmConfigInput): Promise<LlmConfigView> {
    return normalizeLlmConfig(await requestJson('/v1/llm/config', {
      method: 'PUT',
      body: JSON.stringify(input),
    }));
  },

  async clearLlmConfig(): Promise<LlmConfigView> {
    return normalizeLlmConfig(await requestJson('/v1/llm/config', { method: 'DELETE' }));
  },

  async testLlmConfig(): Promise<LlmConnectionTest> {
    return normalizeLlmConnectionTest(await requestJson('/v1/llm/test', {
      method: 'POST',
      timeoutMs: 70_000,
    }));
  },

  async getLlmTelemetry(): Promise<CognitionTelemetry> {
    return normalizeCognitionTelemetry(await requestJson('/v1/llm/telemetry'));
  },

  async getEvalSummary(): Promise<CognitionEvalSummary> {
    return normalizeCognitionEvalSummary(await requestJson('/v1/evals'));
  },

  async getSystemMetrics(): Promise<SystemMetrics> {
    return normalizeSystemMetrics(await requestJson('/v1/system/metrics'));
  },

  async runEvaluation(mode: 'CODE_GRADER_SELF_TEST' | 'LIVE_CONFIGURED_MODEL', maximumCases = 3): Promise<CognitionEvaluationRun> {
    return normalizeCognitionEvaluationRun(await requestJson('/v1/evals/run', {
      method: 'POST',
      body: JSON.stringify({ mode, maximumCases }),
      timeoutMs: mode === 'LIVE_CONFIGURED_MODEL' ? 180_000 : 30_000,
    }));
  },

  async getGovernanceInventory(): Promise<GovernanceInventory> {
    return normalizeGovernanceInventory(await requestJson('/v1/governance/components'));
  },

  async getRedTeamRegistry(): Promise<RedTeamRegistry> {
    return normalizeRedTeamRegistry(await requestJson('/v1/governance/red-team'));
  },

  async getReleaseGate(): Promise<ReleaseGateView> {
    return normalizeReleaseGate(await requestJson('/v1/governance/release-gate'));
  },

  async getValidationLadder(): Promise<ValidationLadderView> {
    return normalizeValidationLadder(await requestJson('/v1/validation/ladder'));
  },

  async getStudyPresets(): Promise<StudyPresetCatalog> {
    return normalizeStudyPresetCatalog(await requestJson('/v1/studies/presets'));
  },

  async previewStudyDesign(input: StudyDesignPreviewInput): Promise<StudyDesignPreview> {
    return normalizeStudyDesignPreview(await requestJson('/v1/studies/design-preview', {
      method: 'POST',
      body: JSON.stringify(input),
      timeoutMs: 30_000,
    }));
  },

  async runStudy(input: StudyRunInput): Promise<StudyRunRecord> {
    return normalizeStudyRun(await requestJson('/v1/studies/run', {
      method: 'POST',
      body: JSON.stringify(input),
      timeoutMs: 240_000,
    }));
  },

  async getStudyRuns(): Promise<StudyRunRecord[]> {
    return normalizeStudyRuns(await requestJson('/v1/studies'));
  },

  async getStudyRun(runId: string): Promise<StudyRunRecord> {
    return normalizeStudyRun(await requestJson(`/v1/studies/${encodeURIComponent(runId)}`));
  },

  async reviewClaim(eventPackId: string, claimId: string, input: ClaimReviewInput): Promise<EventPack> {
    return normalizeEventPack(await requestJson(
      `/v1/event-packs/${encodeURIComponent(eventPackId)}/claims/${encodeURIComponent(claimId)}/review`,
      {
        method: 'POST',
        body: JSON.stringify({
          reviewStatus: input.status,
          editedText: input.editedText,
          editedTextZh: input.editedTextZh,
        }),
      },
    ));
  },

  async approveAllClaims(eventPackId: string, input: BulkClaimApprovalInput): Promise<EventPack> {
    return normalizeEventPack(await requestJson(
      `/v1/event-packs/${encodeURIComponent(eventPackId)}/claims/approve-all`,
      {
        method: 'POST',
        body: JSON.stringify(input),
      },
    ));
  },

  async freezeEventPack(eventPackId: string): Promise<EventPack> {
    return normalizeEventPack(await requestJson(
      `/v1/event-packs/${encodeURIComponent(eventPackId)}/freeze`,
      { method: 'POST' },
    ));
  },

  async validateScenario(scenario: ScenarioDraft): Promise<ScenarioValidation> {
    return normalizeValidation(await requestJson('/v1/scenarios/validate', {
      method: 'POST',
      body: JSON.stringify(scenario),
    }));
  },

  async getScenarios(): Promise<SavedScenario[]> {
    return normalizeSavedScenarios(await requestJson('/v1/scenarios'));
  },

  async createScenario(name: string, config: ScenarioDraft, frozen = false): Promise<SavedScenario> {
    return normalizeSavedScenario(await requestJson('/v1/scenarios', {
      method: 'POST',
      body: JSON.stringify({ name, config, frozen }),
    }));
  },

  async getScenario(scenarioId: string): Promise<SavedScenario> {
    return normalizeSavedScenario(await requestJson(`/v1/scenarios/${encodeURIComponent(scenarioId)}`));
  },

  async updateScenario(scenarioId: string, name: string, config: ScenarioDraft): Promise<SavedScenario> {
    return normalizeSavedScenario(await requestJson(`/v1/scenarios/${encodeURIComponent(scenarioId)}`, {
      method: 'PUT',
      body: JSON.stringify({ name, config }),
    }));
  },

  async deleteScenario(scenarioId: string): Promise<void> {
    await requestJson(`/v1/scenarios/${encodeURIComponent(scenarioId)}`, { method: 'DELETE' });
  },

  async cloneScenario(scenarioId: string): Promise<SavedScenario> {
    return normalizeSavedScenario(await requestJson(`/v1/scenarios/${encodeURIComponent(scenarioId)}/clone`, { method: 'POST' }));
  },

  async freezeScenario(scenarioId: string): Promise<SavedScenario> {
    return normalizeSavedScenario(await requestJson(`/v1/scenarios/${encodeURIComponent(scenarioId)}/freeze`, { method: 'POST' }));
  },

  async diffScenarios(baseline: ScenarioDraft, intervention: ScenarioDraft): Promise<ScenarioDiffResult> {
    return normalizeScenarioDiff(await requestJson('/v1/scenarios/diff', {
      method: 'POST',
      body: JSON.stringify({ baseline, intervention }),
    }));
  },

  async getExperiments(): Promise<Experiment[]> {
    return normalizeExperiments(await requestJson('/v1/experiments'));
  },

  async createExperiment(scenario: ScenarioDraft): Promise<Experiment> {
    return normalizeExperiment(await requestJson('/v1/experiments', {
      method: 'POST',
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify(scenario),
    }));
  },

  async getExperiment(experimentId: string): Promise<Experiment> {
    return normalizeExperiment(await requestJson(`/v1/experiments/${encodeURIComponent(experimentId)}`));
  },

  async streamExperiment(
    experimentId: string,
    onUpdate: (experiment: Experiment) => void,
    signal: AbortSignal,
  ): Promise<void> {
    const response = await fetch(
      `${API_BASE}/v1/experiments/${encodeURIComponent(experimentId)}/events`,
      {
        credentials: 'same-origin',
        headers: {
          Accept: 'text/event-stream',
          'X-Session-ID': getSessionId(),
        },
        cache: 'no-store',
        signal,
      },
    );
    if (!response.ok) {
      if (response.status === 401) window.dispatchEvent(new Event(AUTH_SESSION_EXPIRED_EVENT));
      const detail = await response.text();
      throw new ApiError(detail || 'Experiment event stream could not be opened.', response.status, detail);
    }
    if (!response.body) throw new ApiError('Experiment event stream has no readable body.', 502);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    const processFrame = (frame: string) => {
      let eventName = 'message';
      const dataLines: string[] = [];
      for (const line of frame.split('\n')) {
        if (line.startsWith(':')) continue;
        if (line.startsWith('event:')) eventName = line.slice(6).trim();
        if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
      }
      if (eventName !== 'experiment' || dataLines.length === 0) return;
      onUpdate(normalizeExperiment(JSON.parse(dataLines.join('\n')) as unknown));
    };

    try {
      while (true) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value, { stream: !done }).replaceAll('\r\n', '\n');
        let boundary = buffer.indexOf('\n\n');
        while (boundary >= 0) {
          processFrame(buffer.slice(0, boundary));
          buffer = buffer.slice(boundary + 2);
          boundary = buffer.indexOf('\n\n');
        }
        if (done) {
          if (buffer.trim()) processFrame(buffer);
          return;
        }
      }
    } finally {
      reader.releaseLock();
    }
  },

  async startExperiment(experimentId: string): Promise<Experiment> {
    return normalizeExperiment(await requestJson(
      `/v1/experiments/${encodeURIComponent(experimentId)}/start`,
      { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() } },
    ));
  },

  async cancelExperiment(experimentId: string): Promise<Experiment> {
    return normalizeExperiment(await requestJson(
      `/v1/experiments/${encodeURIComponent(experimentId)}/cancel`,
      { method: 'POST' },
    ));
  },

  async invalidateExperiment(
    experimentId: string,
    input: { reasonCode: InvalidationReasonCode; reason: string },
  ): Promise<Experiment> {
    return normalizeExperiment(await requestJson(
      `/v1/experiments/${encodeURIComponent(experimentId)}/invalidate`,
      {
        method: 'POST',
        body: JSON.stringify({ schemaVersion: '1.0.0', ...input }),
      },
    ));
  },

  async getResults(experimentId: string): Promise<ExperimentResults> {
    return normalizeResults(await requestJson(`/v1/experiments/${encodeURIComponent(experimentId)}/results`));
  },

  async getResultInterpretationConversations(
    experimentId: string,
  ): Promise<ResultInterpretationConversationList> {
    return normalizeResultInterpretationConversationList(await requestJson(
      `/v1/experiments/${encodeURIComponent(experimentId)}/interpretation-conversations`,
    ));
  },

  async getResultInterpretationConversation(
    experimentId: string,
    conversationId: string,
  ): Promise<ResultInterpretationConversation> {
    return normalizeResultInterpretationConversation(await requestJson(
      `/v1/experiments/${encodeURIComponent(experimentId)}/interpretation-conversations/${encodeURIComponent(conversationId)}`,
    ));
  },

  async deleteResultInterpretationConversation(
    experimentId: string,
    conversationId: string,
  ): Promise<ResultInterpretationConversationDeleteResult> {
    return normalizeResultInterpretationConversationDeleteResult(await requestJson(
      `/v1/experiments/${encodeURIComponent(experimentId)}/interpretation-conversations/${encodeURIComponent(conversationId)}`,
      { method: 'DELETE' },
    ));
  },

  async chatAboutResults(
    experimentId: string,
    input: ResultInterpretationChatInput,
  ): Promise<ResultInterpretationChatResponse> {
    return requestResultInterpretationJson(experimentId, input);
  },

  async streamChatAboutResults(
    experimentId: string,
    input: ResultInterpretationChatInput,
    onUpdate: (update: ResultInterpretationStreamUpdate) => void,
    signal?: AbortSignal,
  ): Promise<ResultInterpretationStreamResult> {
    const startedAt = performance.now();
    const controller = new AbortController();
    let timedOut: 'inactivity' | 'hard' | undefined;
    let receivedEventCount = 0;
    let responseReceived = false;
    const abortFromCaller = () => controller.abort(signal?.reason);
    if (signal?.aborted) abortFromCaller();
    else signal?.addEventListener('abort', abortFromCaller, { once: true });
    let inactivityTimeout: number | undefined;
    const resetInactivityTimeout = () => {
      if (inactivityTimeout !== undefined) window.clearTimeout(inactivityTimeout);
      inactivityTimeout = window.setTimeout(() => {
        timedOut = 'inactivity';
        controller.abort();
      }, RESULT_INTERPRETATION_INACTIVITY_TIMEOUT_MS);
    };
    const hardTimeout = window.setTimeout(() => {
      timedOut = 'hard';
      controller.abort();
    }, RESULT_INTERPRETATION_HARD_TIMEOUT_MS);
    resetInactivityTimeout();

    try {
      const response = await fetch(
        `${API_BASE}/v1/experiments/${encodeURIComponent(experimentId)}/interpretation-chat/stream`,
        {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            Accept: 'text/event-stream',
            'Content-Type': 'application/json',
            'X-Session-ID': getSessionId(),
            ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
          },
          body: JSON.stringify(input),
          cache: 'no-store',
          signal: controller.signal,
        },
      );
      responseReceived = true;
      resetInactivityTimeout();

      if (RESULT_INTERPRETATION_STREAM_FALLBACK_STATUSES.has(response.status)) {
        if (inactivityTimeout !== undefined) window.clearTimeout(inactivityTimeout);
        inactivityTimeout = undefined;
        onUpdate({
          kind: 'fallback',
          receivedEventCount,
          elapsedMs: performance.now() - startedAt,
        });
        const fallbackResponse = await requestResultInterpretationJson(
          experimentId,
          input,
          controller.signal,
        );
        return {
          response: fallbackResponse,
          transport: 'json-fallback',
          receivedEventCount,
          elapsedMs: performance.now() - startedAt,
        };
      }
      if (!response.ok) {
        if (response.status === 401) window.dispatchEvent(new Event(AUTH_SESSION_EXPIRED_EVENT));
        throw await resultInterpretationHttpError(response);
      }

      const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
      if (contentType.includes('application/json')) {
        if (inactivityTimeout !== undefined) window.clearTimeout(inactivityTimeout);
        inactivityTimeout = undefined;
        onUpdate({
          kind: 'fallback',
          receivedEventCount,
          elapsedMs: performance.now() - startedAt,
        });
        return {
          response: normalizeResultInterpretationChatResponse(await response.json()),
          transport: 'json-fallback',
          receivedEventCount,
          elapsedMs: performance.now() - startedAt,
        };
      }
      if (!contentType.includes('text/event-stream')) {
        throw new ResultInterpretationStreamError({
          code: 'RESULT_INTERPRETATION_STREAM_CONTENT_TYPE_INVALID',
          message: 'Interpretation stream returned an unsupported content type.',
          retryable: true,
          httpStatus: 502,
          uncertainBillableAttempts: 0,
        });
      }
      if (!response.body) {
        throw new ResultInterpretationStreamError({
          code: 'RESULT_INTERPRETATION_STREAM_BODY_MISSING',
          message: 'Interpretation stream has no readable body.',
          retryable: true,
          httpStatus: 502,
          uncertainBillableAttempts: 0,
        });
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let finalResponse: ResultInterpretationChatResponse | undefined;

      const processFrame = (frame: string) => {
        let eventName = 'message';
        const dataLines: string[] = [];
        for (const line of frame.split('\n')) {
          if (line.startsWith(':')) continue;
          if (line.startsWith('event:')) eventName = line.slice(6).trim();
          if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
        }
        if (!['status', 'progress', 'final', 'error'].includes(eventName)
          || dataLines.length === 0) return;

        const rawData = JSON.parse(dataLines.join('\n')) as unknown;
        receivedEventCount += 1;
        if (eventName === 'status' || eventName === 'progress') {
          onUpdate({
            kind: eventName,
            progress: normalizeResultInterpretationStreamProgress(rawData),
            receivedEventCount,
          });
          return;
        }
        if (eventName === 'error') {
          throw new ResultInterpretationStreamError(
            normalizeResultInterpretationStreamError(rawData),
          );
        }
        const finalPayload = typeof rawData === 'object' && rawData !== null
          && 'response' in rawData
          ? (rawData as { response: unknown }).response
          : rawData;
        finalResponse = normalizeResultInterpretationChatResponse(finalPayload);
      };

      try {
        while (true) {
          let readResult: ReadableStreamReadResult<Uint8Array>;
          try {
            readResult = await reader.read();
          } catch (error) {
            if (error instanceof TypeError) {
              throw new ResultInterpretationStreamError({
                code: 'RESULT_INTERPRETATION_STREAM_INTERRUPTED',
                message: 'Interpretation stream connection was interrupted while reading.',
                retryable: true,
                httpStatus: 502,
                uncertainBillableAttempts: 1,
              });
            }
            throw error;
          }
          const { done, value } = readResult;
          if (!done && value && value.byteLength > 0) resetInactivityTimeout();
          buffer += decoder.decode(value, { stream: !done });
          // CRLF 可能刚好跨越网络分块边界。暂时保留尾部孤立的 CR，等下一块
          // 到达后再规范化，避免把一个换行错误拆成两个 SSE 帧分隔符。
          const hasPendingCarriageReturn = !done && buffer.endsWith('\r');
          const normalizableBuffer = hasPendingCarriageReturn ? buffer.slice(0, -1) : buffer;
          buffer = normalizableBuffer
            .replaceAll('\r\n', '\n')
            .replaceAll('\r', '\n')
            + (hasPendingCarriageReturn ? '\r' : '');
          if (buffer.length > RESULT_INTERPRETATION_SSE_MAX_BUFFER_CHARACTERS) {
            throw new ResultInterpretationStreamError({
              code: 'RESULT_INTERPRETATION_STREAM_BUFFER_LIMIT_EXCEEDED',
              message: 'Interpretation stream exceeded the safe buffer limit.',
              retryable: true,
              httpStatus: 502,
              uncertainBillableAttempts: 1,
            });
          }
          let boundary = buffer.indexOf('\n\n');
          while (boundary >= 0) {
            if (boundary > RESULT_INTERPRETATION_SSE_MAX_FRAME_CHARACTERS) {
              throw new ResultInterpretationStreamError({
                code: 'RESULT_INTERPRETATION_STREAM_FRAME_LIMIT_EXCEEDED',
                message: 'Interpretation stream event exceeded the safe frame limit.',
                retryable: true,
                httpStatus: 502,
                uncertainBillableAttempts: 1,
              });
            }
            processFrame(buffer.slice(0, boundary));
            buffer = buffer.slice(boundary + 2);
            if (finalResponse) break;
            boundary = buffer.indexOf('\n\n');
          }
          if (finalResponse) {
            try {
              await reader.cancel();
            } catch {
              // 最终结构已经完成严格校验；清理底层流只能是 best-effort，
              // 不能让取消失败覆盖一个可安全采用的最终回答。
            }
            return {
              response: finalResponse,
              transport: 'sse',
              receivedEventCount,
              elapsedMs: performance.now() - startedAt,
            };
          }
          if (done) {
            if (buffer.trim()) {
              if (buffer.length > RESULT_INTERPRETATION_SSE_MAX_FRAME_CHARACTERS) {
                throw new ResultInterpretationStreamError({
                  code: 'RESULT_INTERPRETATION_STREAM_FRAME_LIMIT_EXCEEDED',
                  message: 'Interpretation stream event exceeded the safe frame limit.',
                  retryable: true,
                  httpStatus: 502,
                  uncertainBillableAttempts: 1,
                });
              }
              processFrame(buffer);
            }
            if (finalResponse) {
              return {
                response: finalResponse,
                transport: 'sse',
                receivedEventCount,
                elapsedMs: performance.now() - startedAt,
              };
            }
            throw new ResultInterpretationStreamError({
              code: 'RESULT_INTERPRETATION_STREAM_ENDED_EARLY',
              message: 'Interpretation stream ended before a final response arrived.',
              retryable: true,
              httpStatus: 502,
              // 连接中断时无法判断供应商是否已经完成计费调用，因此必须提示用户。
              uncertainBillableAttempts: receivedEventCount > 0 ? 1 : 0,
            });
          }
        }
      } finally {
        reader.releaseLock();
      }
    } catch (error) {
      if (error instanceof ResultInterpretationStreamError) throw error;
      if (error instanceof DOMException && error.name === 'AbortError') {
        if (signal?.aborted) throw error;
        throw new ResultInterpretationStreamError({
          code: timedOut
            ? 'RESULT_INTERPRETATION_STREAM_TIMEOUT'
            : 'RESULT_INTERPRETATION_STREAM_INTERRUPTED',
          message: timedOut
            ? timedOut === 'hard'
              ? 'Interpretation stream reached the hard time limit.'
              : 'Interpretation stream had no activity before the timeout.'
            : 'Interpretation stream was interrupted.',
          retryable: true,
          httpStatus: timedOut ? 408 : 502,
          uncertainBillableAttempts: receivedEventCount > 0 ? 1 : 0,
        });
      }
      if (error instanceof SyntaxError || error instanceof TypeError) {
        throw new ResultInterpretationStreamError({
          code: responseReceived
            ? 'RESULT_INTERPRETATION_STREAM_CONTRACT_INVALID'
            : 'RESULT_INTERPRETATION_STREAM_INTERRUPTED',
          message: responseReceived
            ? 'Interpretation stream returned an invalid event.'
            : 'Interpretation stream connection could not be established.',
          retryable: true,
          httpStatus: 502,
          uncertainBillableAttempts: 1,
        });
      }
      throw error;
    } finally {
      if (inactivityTimeout !== undefined) window.clearTimeout(inactivityTimeout);
      window.clearTimeout(hardTimeout);
      signal?.removeEventListener('abort', abortFromCaller);
    }
  },

  async exportExperiment(experimentId: string): Promise<Blob> {
    const response = await fetch(
      `${API_BASE}/v1/experiments/${encodeURIComponent(experimentId)}/export`,
      {
        credentials: 'same-origin',
        headers: { Accept: 'application/zip, application/json', 'X-Session-ID': getSessionId() },
      },
    );
    if (!response.ok) {
      if (response.status === 401) window.dispatchEvent(new Event(AUTH_SESSION_EXPIRED_EVENT));
      throw new ApiError('Export request failed.', response.status);
    }
    return await response.blob();
  },
};
