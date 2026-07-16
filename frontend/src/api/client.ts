import {
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
} from './normalize';
import type {
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
} from './types';

const API_BASE = '/api';
const SESSION_STORAGE_KEY = 'eventshockSessionId';

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
}

async function requestJson(path: string, options: RequestOptions = {}): Promise<unknown> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), options.timeoutMs ?? 12_000);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        Accept: 'application/json',
        'X-Session-ID': getSessionId(),
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
      signal: controller.signal,
    });
    const contentType = response.headers.get('content-type') ?? '';
    const payload = contentType.includes('application/json') ? await response.json() as unknown : await response.text();
    if (!response.ok) {
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
        headers: {
          Accept: 'text/event-stream',
          'X-Session-ID': getSessionId(),
        },
        cache: 'no-store',
        signal,
      },
    );
    if (!response.ok) {
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

  async exportExperiment(experimentId: string): Promise<Blob> {
    const response = await fetch(
      `${API_BASE}/v1/experiments/${encodeURIComponent(experimentId)}/export`,
      { headers: { Accept: 'application/zip, application/json', 'X-Session-ID': getSessionId() } },
    );
    if (!response.ok) throw new ApiError('Export request failed.', response.status);
    return await response.blob();
  },
};
