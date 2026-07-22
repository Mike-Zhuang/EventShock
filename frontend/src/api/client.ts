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

  constructor(message: string, status: number, detail?: string, code?: string, traceId?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.code = code;
    this.traceId = traceId;
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
      throw new ApiError(detail ?? `API request failed with status ${response.status}.`, response.status, detail, code, traceId);
    }
    return payload;
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError('API request timed out.', 408);
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
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

  async chatAboutResults(
    experimentId: string,
    input: ResultInterpretationChatInput,
  ): Promise<ResultInterpretationChatResponse> {
    return normalizeResultInterpretationChatResponse(await requestJson(
      `/v1/experiments/${encodeURIComponent(experimentId)}/interpretation-chat`,
      {
        method: 'POST',
        body: JSON.stringify(input),
        // 推理模型可能需要较长首字节时间，但仍必须有明确的客户端上限。
        timeoutMs: 120_000,
      },
    ));
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
