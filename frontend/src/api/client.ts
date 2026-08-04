import {
  normalizeAccountDataExport,
  normalizeAccountDeletionReceipt,
  normalizeAdminLlmCredential,
  normalizeAdminActivityPage,
  normalizeAdminUserPage,
  normalizeAuthSession,
  normalizeCases,
  normalizeCognitionEvalSummary,
  normalizeCognitionEvaluationRun,
  normalizeCognitionTelemetry,
  normalizeDeploymentStatus,
  normalizeEventPack,
  normalizeExperiment,
  normalizeExperiments,
  normalizeFactoryBuild,
  normalizeFactoryBuilds,
  normalizeFactoryMutation,
  normalizeFactorySearchEngines,
  normalizeFactorySnapshot,
  normalizeFactorySourceRawText,
  normalizeGovernanceInventory,
  normalizeGuidedWorkflow,
  normalizeGuidedWorkflows,
  normalizeGuidedTurnOperations,
  normalizeGuidedTurnRecoveryResult,
  normalizeLlmCatalog,
  normalizeLlmConfig,
  normalizeLlmConnectionTest,
  normalizeLegalAcceptance,
  normalizeLegalDocument,
  normalizePreferences,
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
  AccountDataExport,
  AccountDataExportInput,
  AccountDeletionInput,
  AccountDeletionReceipt,
  AdminLlmCredentialDeleteInput,
  AdminLlmCredentialInput,
  AdminLlmCredentialPatchInput,
  AdminLlmCredentialView,
  AdminActivityPage,
  AdminUserPage,
  AuthSession,
  BulkClaimApprovalInput,
  CaseSummary,
  ClaimReviewInput,
  EventPack,
  EventPackCreateInput,
  EventPackFactoryBuild,
  EventPackFactoryMaterializeInput,
  EventPackFactoryMutation,
  EventPackFactoryPasteSourceInput,
  EventPackFactorySearchInput,
  EventPackFactorySnapshot,
  EventPackFactorySourceRawText,
  EventSourceUpload,
  Experiment,
  ExperimentResults,
  CognitionEvalSummary,
  CognitionEvaluationRun,
  CognitionTelemetry,
  DeploymentStatus,
  GovernanceInventory,
  GuidedTurnInput,
  GuidedTurnOperation,
  GuidedTurnRecoveryInput,
  GuidedTurnRecoveryResult,
  GuidedWorkflow,
  HealthStatus,
  InvalidationReasonCode,
  LlmCatalog,
  LlmConfigInput,
  LlmConfigView,
  LlmConnectionTest,
  LegalAcceptanceStatus,
  LegalConsentInput,
  LegalDocument,
  PromptRegistryItem,
  FactorySearchEngineDescriptor,
  FactorySourceReviewStatus,
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
  UserPreferences,
  UserPreferencesInput,
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
  readonly failureStage?: string;
  readonly repairAttempted?: boolean;
  readonly repairUsed?: boolean;
  readonly billingConclusion?: string;

  constructor(
    message: string,
    status: number,
    detail?: string,
    code?: string,
    traceId?: string,
    metadata: {
      retryable?: boolean;
      uncertainBillableAttempts?: number;
      failureStage?: string;
      repairAttempted?: boolean;
      repairUsed?: boolean;
      billingConclusion?: string;
    } = {},
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.code = code;
    this.traceId = traceId;
    this.retryable = metadata.retryable;
    this.uncertainBillableAttempts = metadata.uncertainBillableAttempts;
    this.failureStage = metadata.failureStage;
    this.repairAttempted = metadata.repairAttempted;
    this.repairUsed = metadata.repairUsed;
    this.billingConclusion = metadata.billingConclusion;
  }
}

export class ResultInterpretationStreamError extends ApiError {
  readonly retryable: boolean;
  readonly uncertainBillableAttempts: number;
  readonly failureStage?: string;
  readonly repairAttempted?: boolean;
  readonly repairUsed?: boolean;
  readonly billingConclusion?: string;

  constructor(payload: ResultInterpretationStreamErrorPayload) {
    super(payload.message, payload.httpStatus, payload.message, payload.code, payload.traceId, payload);
    this.name = 'ResultInterpretationStreamError';
    this.retryable = payload.retryable;
    this.uncertainBillableAttempts = payload.uncertainBillableAttempts;
    this.failureStage = payload.failureStage;
    this.repairAttempted = payload.repairAttempted;
    this.repairUsed = payload.repairUsed;
    this.billingConclusion = payload.billingConclusion;
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
      const failureStage = typeof nestedError?.failureStage === 'string'
        ? nestedError.failureStage
        : typeof nestedError?.failure_stage === 'string' ? nestedError.failure_stage : undefined;
      const repairAttempted = typeof nestedError?.repairAttempted === 'boolean'
        ? nestedError.repairAttempted
        : typeof nestedError?.repair_attempted === 'boolean' ? nestedError.repair_attempted : undefined;
      const repairUsed = typeof nestedError?.repairUsed === 'boolean'
        ? nestedError.repairUsed
        : typeof nestedError?.repair_used === 'boolean' ? nestedError.repair_used : undefined;
      const billingConclusion = typeof nestedError?.billingConclusion === 'string'
        ? nestedError.billingConclusion
        : typeof nestedError?.billing_conclusion === 'string'
          ? nestedError.billing_conclusion
          : undefined;
      throw new ApiError(
        detail ?? `API request failed with status ${response.status}.`,
        response.status,
        detail,
        code,
        traceId,
        {
          retryable,
          uncertainBillableAttempts,
          failureStage,
          repairAttempted,
          repairUsed,
          billingConclusion,
        },
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
        failureStage: error.failureStage,
        repairAttempted: error.repairAttempted,
        repairUsed: error.repairUsed,
        billingConclusion: error.billingConclusion,
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
  const failureStage = typeof errorRecord?.failureStage === 'string'
    ? errorRecord.failureStage
    : typeof errorRecord?.failure_stage === 'string' ? errorRecord.failure_stage : undefined;
  const repairAttempted = typeof errorRecord?.repairAttempted === 'boolean'
    ? errorRecord.repairAttempted
    : typeof errorRecord?.repair_attempted === 'boolean' ? errorRecord.repair_attempted : undefined;
  const repairUsed = typeof errorRecord?.repairUsed === 'boolean'
    ? errorRecord.repairUsed
    : typeof errorRecord?.repair_used === 'boolean' ? errorRecord.repair_used : undefined;
  const billingConclusion = typeof errorRecord?.billingConclusion === 'string'
    ? errorRecord.billingConclusion
    : typeof errorRecord?.billing_conclusion === 'string'
      ? errorRecord.billing_conclusion
      : undefined;
  return new ResultInterpretationStreamError({
    code,
    message,
    retryable,
    httpStatus: response.status,
    uncertainBillableAttempts,
    failureStage,
    repairAttempted,
    repairUsed,
    billingConclusion,
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

  async exportAccountData(input: AccountDataExportInput): Promise<AccountDataExport> {
    return normalizeAccountDataExport(await requestJson('/v1/account/data-export', {
      method: 'POST',
      body: JSON.stringify({ password: input.currentPassword }),
      // 此端点用 401 同时表示“当前密码错误”，不能把一次输错密码误判为会话失效。
      broadcastUnauthorized: false,
    }));
  },

  async deleteAccount(input: AccountDeletionInput): Promise<AccountDeletionReceipt> {
    return normalizeAccountDeletionReceipt(await requestJson('/v1/account', {
      method: 'DELETE',
      body: JSON.stringify({
        password: input.currentPassword,
        confirmation: input.confirmation,
      }),
      broadcastUnauthorized: false,
    }));
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
  } & LegalConsentInput): Promise<AuthSession> {
    return normalizeAuthSession(await requestJson('/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify(input),
      broadcastUnauthorized: false,
    }));
  },

  async getLegalDocument(language: 'en' | 'zh-CN'): Promise<LegalDocument> {
    const query = new URLSearchParams({ language });
    return normalizeLegalDocument(await requestJson(`/v1/legal/terms?${query.toString()}`, {
      broadcastUnauthorized: false,
    }));
  },

  async acceptLegalDocuments(input: LegalConsentInput): Promise<LegalAcceptanceStatus> {
    return normalizeLegalAcceptance(await requestJson('/v1/auth/legal-acceptance', {
      method: 'POST',
      body: JSON.stringify(input),
    }));
  },

  async getUserPreferences(): Promise<UserPreferences> {
    return normalizePreferences(await requestJson('/v1/auth/preferences'));
  },

  async saveUserPreferences(input: UserPreferencesInput): Promise<UserPreferences> {
    return normalizePreferences(await requestJson('/v1/auth/preferences', {
      method: 'PUT',
      body: JSON.stringify(input),
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

  async getFactorySearchEngines(): Promise<FactorySearchEngineDescriptor[]> {
    return normalizeFactorySearchEngines(
      await requestJson('/v1/event-pack-factory/search-engines'),
    );
  },

  async getFactoryBuilds(): Promise<EventPackFactoryBuild[]> {
    return normalizeFactoryBuilds(await requestJson('/v1/event-pack-factory/builds'));
  },

  async createFactoryBuild(title: string): Promise<EventPackFactoryBuild> {
    return normalizeFactoryBuild(await requestJson('/v1/event-pack-factory/builds', {
      method: 'POST',
      body: JSON.stringify({ title }),
    }));
  },

  async getFactoryBuild(buildId: string): Promise<EventPackFactorySnapshot> {
    return normalizeFactorySnapshot(await requestJson(
      `/v1/event-pack-factory/builds/${encodeURIComponent(buildId)}`,
    ));
  },

  async deleteFactoryBuild(buildId: string, expectedRevision: number): Promise<void> {
    await requestJson(`/v1/event-pack-factory/builds/${encodeURIComponent(buildId)}`, {
      method: 'DELETE',
      body: JSON.stringify({ expectedRevision }),
    });
  },

  async addFactoryPasteSource(
    buildId: string,
    expectedRevision: number,
    source: EventPackFactoryPasteSourceInput,
  ): Promise<EventPackFactoryMutation> {
    return normalizeFactoryMutation(await requestJson(
      `/v1/event-pack-factory/builds/${encodeURIComponent(buildId)}/paste`,
      {
        method: 'POST',
        body: JSON.stringify({ expectedRevision, source }),
        timeoutMs: 30_000,
      },
    ));
  },

  async searchFactorySources(
    buildId: string,
    expectedRevision: number,
    request: EventPackFactorySearchInput,
    clientRequestId: string,
  ): Promise<EventPackFactoryMutation> {
    return normalizeFactoryMutation(await requestJson(
      `/v1/event-pack-factory/builds/${encodeURIComponent(buildId)}/search`,
      {
        method: 'POST',
        body: JSON.stringify({ clientRequestId, expectedRevision, request }),
        timeoutMs: 90_000,
      },
    ));
  },

  async addFactoryReaderSource(
    buildId: string,
    expectedRevision: number,
    searchResultSourceId: string,
    knownAt: string,
    clientRequestId: string,
  ): Promise<EventPackFactoryMutation> {
    return normalizeFactoryMutation(await requestJson(
      `/v1/event-pack-factory/builds/${encodeURIComponent(buildId)}/reader`,
      {
        method: 'POST',
        body: JSON.stringify({
          clientRequestId,
          expectedRevision,
          searchResultSourceId,
          knownAt,
        }),
        timeoutMs: 90_000,
      },
    ));
  },

  async reviewFactorySource(
    buildId: string,
    sourceId: string,
    expectedRevision: number,
    status: Exclude<FactorySourceReviewStatus, 'PENDING'>,
  ): Promise<EventPackFactoryMutation> {
    return normalizeFactoryMutation(await requestJson(
      `/v1/event-pack-factory/builds/${encodeURIComponent(buildId)}/sources/${encodeURIComponent(sourceId)}/review`,
      {
        method: 'POST',
        body: JSON.stringify({ expectedRevision, status }),
      },
    ));
  },

  async setFactorySourceIncluded(
    buildId: string,
    sourceId: string,
    expectedRevision: number,
    included: boolean,
  ): Promise<EventPackFactoryMutation> {
    return normalizeFactoryMutation(await requestJson(
      `/v1/event-pack-factory/builds/${encodeURIComponent(buildId)}/sources/${encodeURIComponent(sourceId)}/selection`,
      {
        method: 'POST',
        body: JSON.stringify({ expectedRevision, included }),
      },
    ));
  },

  async permanentlyDeleteFactorySourceText(
    buildId: string,
    sourceId: string,
    expectedRevision: number,
  ): Promise<EventPackFactoryMutation> {
    return normalizeFactoryMutation(await requestJson(
      `/v1/event-pack-factory/builds/${encodeURIComponent(buildId)}/sources/${encodeURIComponent(sourceId)}/raw-text`,
      {
        method: 'DELETE',
        body: JSON.stringify({ expectedRevision, confirmation: 'DELETE_RAW_TEXT' }),
        cache: 'no-store',
      },
    ));
  },

  async materializeFactoryBuild(
    buildId: string,
    expectedRevision: number,
    input: EventPackFactoryMaterializeInput,
    clientRequestId: string,
  ): Promise<EventPack> {
    return normalizeEventPack(await requestJson(
      `/v1/event-pack-factory/builds/${encodeURIComponent(buildId)}/materialize`,
      {
        method: 'POST',
        body: JSON.stringify({ clientRequestId, expectedRevision, ...input }),
        timeoutMs: 120_000,
      },
    ));
  },

  async getFactorySourceRawText(
    buildId: string,
    sourceId: string,
  ): Promise<EventPackFactorySourceRawText> {
    return normalizeFactorySourceRawText(await requestJson(
      `/v1/event-pack-factory/builds/${encodeURIComponent(buildId)}/sources/${encodeURIComponent(sourceId)}/raw-text`,
      { cache: 'no-store' },
    ));
  },

  async updateFactorySourceRawText(
    buildId: string,
    sourceId: string,
    expectedRevision: number,
    rawText: string,
  ): Promise<EventPackFactoryMutation> {
    return normalizeFactoryMutation(await requestJson(
      `/v1/event-pack-factory/builds/${encodeURIComponent(buildId)}/sources/${encodeURIComponent(sourceId)}/raw-text`,
      {
        method: 'PUT',
        body: JSON.stringify({ expectedRevision, rawText }),
        cache: 'no-store',
      },
    ));
  },

  async getGuidedWorkflows(): Promise<GuidedWorkflow[]> {
    return normalizeGuidedWorkflows(await requestJson('/v1/guided-workflows'));
  },

  async createGuidedWorkflow(language: 'en' | 'zh-CN'): Promise<GuidedWorkflow> {
    return normalizeGuidedWorkflow(await requestJson('/v1/guided-workflows', {
      method: 'POST',
      body: JSON.stringify({ language }),
    }));
  },

  async getGuidedWorkflow(workflowId: string): Promise<GuidedWorkflow> {
    return normalizeGuidedWorkflow(await requestJson(
      `/v1/guided-workflows/${encodeURIComponent(workflowId)}`,
    ));
  },

  async sendGuidedTurn(
    workflowId: string,
    input: GuidedTurnInput,
  ): Promise<GuidedWorkflow> {
    return normalizeGuidedWorkflow(await requestJson(
      `/v1/guided-workflows/${encodeURIComponent(workflowId)}/turn`,
      {
        method: 'POST',
        body: JSON.stringify(input),
        timeoutMs: 120_000,
      },
    ));
  },

  async getGuidedTurnOperations(workflowId: string): Promise<GuidedTurnOperation[]> {
    return normalizeGuidedTurnOperations(await requestJson(
      `/v1/guided-workflows/${encodeURIComponent(workflowId)}/operations`,
      { cache: 'no-store' },
    ));
  },

  async recoverGuidedTurn(
    workflowId: string,
    clientRequestId: string,
    input: GuidedTurnRecoveryInput,
  ): Promise<GuidedTurnRecoveryResult> {
    return normalizeGuidedTurnRecoveryResult(await requestJson(
      `/v1/guided-workflows/${encodeURIComponent(workflowId)}/operations/${encodeURIComponent(clientRequestId)}/recover`,
      {
        method: 'POST',
        body: JSON.stringify(input),
        cache: 'no-store',
      },
    ));
  },

  async archiveGuidedWorkflow(
    workflowId: string,
    expectedVersion: number,
  ): Promise<GuidedWorkflow> {
    return normalizeGuidedWorkflow(await requestJson(
      `/v1/guided-workflows/${encodeURIComponent(workflowId)}/archive`,
      {
        method: 'POST',
        body: JSON.stringify({ expectedVersion }),
      },
    ));
  },

  async applyGuidedProposal(
    workflowId: string,
    proposalId: string,
    expectedVersion: number,
  ): Promise<GuidedWorkflow> {
    return normalizeGuidedWorkflow(await requestJson(
      `/v1/guided-workflows/${encodeURIComponent(workflowId)}/apply`,
      {
        method: 'POST',
        body: JSON.stringify({ proposalId, expectedVersion }),
      },
    ));
  },

  async advanceGuidedWorkflow(
    workflowId: string,
    expectedVersion: number,
  ): Promise<GuidedWorkflow> {
    return normalizeGuidedWorkflow(await requestJson(
      `/v1/guided-workflows/${encodeURIComponent(workflowId)}/advance`,
      {
        method: 'POST',
        body: JSON.stringify({ expectedVersion, acknowledgedHumanReview: true }),
      },
    ));
  },

  async linkGuidedWorkflowArtifacts(
    workflowId: string,
    input: {
      expectedVersion: number;
      eventPackBuildId?: string;
      eventPackId?: string;
      scenarioId?: string;
    },
  ): Promise<GuidedWorkflow> {
    return normalizeGuidedWorkflow(await requestJson(
      `/v1/guided-workflows/${encodeURIComponent(workflowId)}/links`,
      {
        method: 'PATCH',
        body: JSON.stringify(input),
      },
    ));
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

  async getAdminLlmCredential(): Promise<AdminLlmCredentialView> {
    return normalizeAdminLlmCredential(await requestJson('/v1/admin/llm-credential'));
  },

  async saveAdminLlmCredential(input: AdminLlmCredentialInput): Promise<AdminLlmCredentialView> {
    return normalizeAdminLlmCredential(await requestJson('/v1/admin/llm-credential', {
      method: 'PUT',
      body: JSON.stringify(input),
    }));
  },

  async updateAdminLlmCredential(
    input: AdminLlmCredentialPatchInput,
  ): Promise<AdminLlmCredentialView> {
    return normalizeAdminLlmCredential(await requestJson('/v1/admin/llm-credential', {
      method: 'PATCH',
      body: JSON.stringify(input),
    }));
  },

  async deleteAdminLlmCredential(
    input: AdminLlmCredentialDeleteInput,
  ): Promise<AdminLlmCredentialView> {
    return normalizeAdminLlmCredential(await requestJson('/v1/admin/llm-credential', {
      method: 'DELETE',
      body: JSON.stringify(input),
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

  async getDeploymentStatus(): Promise<DeploymentStatus> {
    return normalizeDeploymentStatus(
      await requestJson('/v1/governance/deployment-status'),
    );
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
          editedImpactChannels: input.editedImpactChannels,
          editedImpactChannelRationale: input.editedImpactChannelRationale,
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

  async continueCognitionWithRules(experimentId: string): Promise<Experiment> {
    return normalizeExperiment(await requestJson(
      `/v1/experiments/${encodeURIComponent(experimentId)}/cognition/continue-with-rules`,
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
