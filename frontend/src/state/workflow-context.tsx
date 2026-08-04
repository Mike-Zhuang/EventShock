import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { api } from '../api/client';
import type {
  BulkClaimApprovalInput,
  CaseSummary,
  ClaimReviewInput,
  EventPack,
  EventPackCreateInput,
  EventSourceUpload,
  Experiment,
  ExperimentResults,
  HealthStatus,
  InvalidationReasonCode,
  ScenarioDraft,
  ScenarioValidation,
} from '../api/types';
import { downloadFilename } from '../utils/format';

export type RequestState = 'idle' | 'loading' | 'success' | 'error';
export type ApiConnectionState = 'checking' | 'online' | 'offline';

export type ScenarioValidationOrigin =
  | {
      kind: 'saved';
      scenarioId: string;
      scenarioName: string;
      contentHash: string;
    }
  | { kind: 'unsaved-draft' };

export type ScenarioValidationBinding = ScenarioValidationOrigin & {
  draftDigest: string;
};

function canonicalizeScenarioValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalizeScenarioValue);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== undefined)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, canonicalizeScenarioValue(item)]),
  );
}

export function scenarioContentSignature(scenario: ScenarioDraft): string {
  return JSON.stringify(canonicalizeScenarioValue(scenario));
}

export function scenarioContentDigest(scenario: ScenarioDraft): string {
  const signature = scenarioContentSignature(scenario);
  let hash = 2_166_136_261;
  for (let index = 0; index < signature.length; index += 1) {
    hash ^= signature.charCodeAt(index);
    hash = Math.imul(hash, 16_777_619);
  }
  return `draft-${(hash >>> 0).toString(16).padStart(8, '0')}`;
}

const DEFAULT_SCENARIO: ScenarioDraft = {
  eventPackId: '',
  questionInterventionParameter: 'marketMakerCapacity',
  intervention: {
    parameter: 'marketMakerCapacity',
    baselineValue: 1,
    interventionValue: 0.45,
  },
  seedCount: 10,
  seedRoot: 2_026_070_700,
  populationSize: 56,
  steps: 120,
  market: {
    instrumentId: 'SPCX',
    benchmarkId: 'NDX_SYNTHETIC',
    tickSize: 0.01,
    initialPrice: 135,
    feeBps: 0.3,
    latencyMs: 25,
    openingAuction: true,
    volatilityHalt: true,
    priceCollarBps: 180,
  },
  population: {
    profileId: 'mixed-event-risk-v1',
    representativeLlmAgents: 8,
    institutionalShare: 0.2,
    leverageEnabled: true,
    shortSellingEnabled: true,
  },
  network: {
    topology: 'WATTS_STROGATZ',
    averageDegree: 6,
    rewiringProbability: 0.12,
    echoChamberStrength: 0.35,
    correctionReach: 0.7,
  },
  llmPolicy: {
    mode: 'RULE_ONLY',
    provider: 'zhipu',
    modelId: 'glm-5.2',
    representativeAgentCount: 8,
    decisionIntervalSteps: 12,
    callBudget: 24,
    maxCostUsd: 10,
    fallbackToRules: true,
  },
  primaryOutcome: 'maxSpreadBps',
  secondaryOutcomes: ['maxDrawdownPct', 'recoverySteps', 'cascadeScore'],
  stoppingRule: {
    minimumPairs: 10,
    maximumPairs: 10,
  },
  acknowledgedScenarioNotForecast: false,
  acknowledgedSyntheticAssumptions: false,
};

function withScenarioDefaults(input: ScenarioDraft): ScenarioDraft {
  return {
    ...DEFAULT_SCENARIO,
    ...input,
    intervention: { ...DEFAULT_SCENARIO.intervention, ...input.intervention },
    market: { ...DEFAULT_SCENARIO.market!, ...input.market },
    population: { ...DEFAULT_SCENARIO.population!, ...input.population },
    network: { ...DEFAULT_SCENARIO.network!, ...input.network },
    llmPolicy: { ...DEFAULT_SCENARIO.llmPolicy!, ...input.llmPolicy },
    stoppingRule: { ...DEFAULT_SCENARIO.stoppingRule!, ...input.stoppingRule },
  };
}

interface WorkflowContextValue {
  apiConnection: ApiConnectionState;
  health?: HealthStatus;
  cases: CaseSummary[];
  casesState: RequestState;
  casesError?: string;
  selectedCase?: CaseSummary;
  eventPack?: EventPack;
  eventPackState: RequestState;
  eventPackError?: string;
  claimBusyId?: string;
  scenario: ScenarioDraft;
  validation?: ScenarioValidation;
  validationBinding?: ScenarioValidationBinding;
  validationState: RequestState;
  validationError?: string;
  experiments: Experiment[];
  experimentsState: RequestState;
  experimentsError?: string;
  activeExperiment?: Experiment;
  results?: ExperimentResults;
  resultsState: RequestState;
  resultsError?: string;
  refreshAll: () => Promise<void>;
  refreshCases: () => Promise<void>;
  selectCase: (caseItem: CaseSummary) => Promise<void>;
  createEventPack: (input: EventPackCreateInput) => Promise<EventPack>;
  reextractEventPack: (
    sources: EventSourceUpload[],
    useLlm?: boolean,
    maximumClaims?: number,
    acknowledgedContentReview?: boolean,
  ) => Promise<EventPack>;
  reviewClaim: (claimId: string, input: ClaimReviewInput) => Promise<void>;
  approveAllPendingClaims: (input: BulkClaimApprovalInput) => Promise<void>;
  freezeEventPack: () => Promise<void>;
  setScenario: (scenario: ScenarioDraft) => void;
  validateScenario: (origin?: ScenarioValidationOrigin) => Promise<ScenarioValidation>;
  refreshExperiments: () => Promise<void>;
  selectExperiment: (experimentId: string) => Promise<Experiment | undefined>;
  cancelPendingExperimentRequests: () => void;
  createAndStartExperiment: (scenarioOverride?: ScenarioDraft) => Promise<Experiment>;
  cancelActiveExperiment: () => Promise<void>;
  continueActiveCognitionWithRules: () => Promise<void>;
  invalidateActiveExperiment: (reasonCode: InvalidationReasonCode, reason: string) => Promise<void>;
  loadResults: (experimentId?: string) => Promise<ExperimentResults | undefined>;
  exportExperiment: (experimentId: string) => Promise<void>;
}

const WorkflowContext = createContext<WorkflowContextValue | null>(null);

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function upsertExperiment(experiments: Experiment[], updated: Experiment): Experiment[] {
  const existingIndex = experiments.findIndex((item) => item.id === updated.id);
  if (existingIndex < 0) return [updated, ...experiments];
  return experiments.map((item) => item.id === updated.id ? updated : item);
}

export function WorkflowProvider({ children }: { children: ReactNode }) {
  const [apiConnection, setApiConnection] = useState<ApiConnectionState>('checking');
  const [health, setHealth] = useState<HealthStatus>();
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [casesState, setCasesState] = useState<RequestState>('idle');
  const [casesError, setCasesError] = useState<string>();
  const [selectedCase, setSelectedCase] = useState<CaseSummary>();
  const [eventPack, setEventPack] = useState<EventPack>();
  const [eventPackState, setEventPackState] = useState<RequestState>('idle');
  const [eventPackError, setEventPackError] = useState<string>();
  const [claimBusyId, setClaimBusyId] = useState<string>();
  const [scenario, setScenarioState] = useState<ScenarioDraft>(DEFAULT_SCENARIO);
  const [validation, setValidation] = useState<ScenarioValidation>();
  const [validationBinding, setValidationBinding] = useState<ScenarioValidationBinding>();
  const [validationState, setValidationState] = useState<RequestState>('idle');
  const [validationError, setValidationError] = useState<string>();
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [experimentsState, setExperimentsState] = useState<RequestState>('idle');
  const [experimentsError, setExperimentsError] = useState<string>();
  const [activeExperiment, setActiveExperiment] = useState<Experiment>();
  const [results, setResults] = useState<ExperimentResults>();
  const [resultsState, setResultsState] = useState<RequestState>('idle');
  const [resultsError, setResultsError] = useState<string>();
  const resultsRequestGeneration = useRef(0);
  const experimentSelectionGeneration = useRef(0);
  const activeExperimentIdRef = useRef<string | undefined>(undefined);
  const pollTimer = useRef<number | undefined>(undefined);
  const streamAbortController = useRef<AbortController | null>(null);
  const validationGeneration = useRef(0);

  const clearScenarioValidation = useCallback(() => {
    validationGeneration.current += 1;
    setValidation(undefined);
    setValidationBinding(undefined);
    setValidationError(undefined);
    setValidationState('idle');
  }, []);

  const checkHealth = useCallback(async () => {
    setApiConnection('checking');
    try {
      const nextHealth = await api.getHealth();
      setHealth(nextHealth);
      setApiConnection('online');
    } catch {
      setHealth(undefined);
      setApiConnection('offline');
    }
  }, []);

  const refreshCases = useCallback(async () => {
    setCasesState('loading');
    setCasesError(undefined);
    try {
      const nextCases = await api.getCases();
      setCases(nextCases);
      setCasesState('success');
    } catch (error) {
      setCases([]);
      setCasesState('error');
      setCasesError(errorMessage(error));
    }
  }, []);

  const refreshExperiments = useCallback(async () => {
    setExperimentsState('loading');
    setExperimentsError(undefined);
    try {
      const nextExperiments = await api.getExperiments();
      setExperiments(nextExperiments);
      setExperimentsState('success');
      setActiveExperiment((current) => {
        if (!current) return undefined;
        return nextExperiments.find((item) => item.id === current.id) ?? current;
      });
    } catch (error) {
      setExperimentsState('error');
      setExperimentsError(errorMessage(error));
    }
  }, []);

  const refreshAll = useCallback(async () => {
    await checkHealth();
    await Promise.all([refreshCases(), refreshExperiments()]);
  }, [checkHealth, refreshCases, refreshExperiments]);

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  useEffect(() => {
    if (pollTimer.current) window.clearInterval(pollTimer.current);
    streamAbortController.current?.abort();
    if (!activeExperiment || !['QUEUED', 'RUNNING', 'AGGREGATING', 'CANCEL_REQUESTED'].includes(activeExperiment.status)) return;
    const experimentId = activeExperiment.id;
    const controller = new AbortController();
    streamAbortController.current = controller;
    const applyUpdate = (updated: Experiment) => {
      setActiveExperiment((current) => current?.id === updated.id ? updated : current);
      setExperiments((current) => upsertExperiment(current, updated));
    };
    const followStream = async () => {
      while (!controller.signal.aborted) {
        try {
          await api.streamExperiment(experimentId, applyUpdate, controller.signal);
        } catch {
          if (controller.signal.aborted) return;
          // SSE 失败时保留轮询兜底；短暂退避后重连，避免代理重启造成进度中断。
        }
        if (controller.signal.aborted) return;
        await new Promise((resolve) => window.setTimeout(resolve, 1_500));
      }
    };
    void followStream();
    pollTimer.current = window.setInterval(() => {
      void api.getExperiment(experimentId).then((updated) => {
        applyUpdate(updated);
      }).catch((error: unknown) => {
        setExperimentsError(errorMessage(error));
      });
    }, 10_000);
    return () => {
      controller.abort();
      if (pollTimer.current) window.clearInterval(pollTimer.current);
    };
  }, [activeExperiment?.id, activeExperiment?.status]);

  useEffect(() => {
    if (activeExperiment?.status !== 'INVALIDATED') return;
    // 无论作废来自当前标签页还是刷新对账，都不能继续展示内存中的旧结果。
    setResults(undefined);
    setResultsState('idle');
    setResultsError(undefined);
  }, [activeExperiment?.id, activeExperiment?.status]);

  const selectCase = useCallback(async (caseItem: CaseSummary) => {
    // 切换业务上下文时让仍在途的实验选择与结果请求失效，避免迟到响应重新污染界面。
    experimentSelectionGeneration.current += 1;
    resultsRequestGeneration.current += 1;
    setSelectedCase(caseItem);
    setEventPack(undefined);
    clearScenarioValidation();
    setResults(undefined);
    setResultsState('idle');
    setResultsError(undefined);
    if (!caseItem.eventPackId) {
      setEventPackState('error');
      setEventPackError('The selected case does not include an Event Pack identifier.');
      return;
    }
    setEventPackState('loading');
    setEventPackError(undefined);
    try {
      const nextPack = await api.getEventPack(caseItem.eventPackId);
      setEventPack(nextPack);
      setScenarioState((current) => nextPack.defaultExperiment
        ? withScenarioDefaults(nextPack.defaultExperiment)
        : { ...current, eventPackId: nextPack.id });
      setEventPackState('success');
    } catch (error) {
      setEventPackState('error');
      setEventPackError(errorMessage(error));
    }
  }, [clearScenarioValidation]);

  const reviewClaim = useCallback(async (claimId: string, input: ClaimReviewInput) => {
    if (!eventPack) return;
    setClaimBusyId(claimId);
    setEventPackError(undefined);
    try {
      const nextPack = await api.reviewClaim(eventPack.id, claimId, input);
      setEventPack(nextPack);
      clearScenarioValidation();
    } catch (error) {
      setEventPackError(errorMessage(error));
      throw error;
    } finally {
      setClaimBusyId(undefined);
    }
  }, [clearScenarioValidation, eventPack]);

  const approveAllPendingClaims = useCallback(async (input: BulkClaimApprovalInput) => {
    if (!eventPack) return;
    setClaimBusyId('ALL_PENDING_CLAIMS');
    setEventPackError(undefined);
    try {
      const nextPack = await api.approveAllClaims(eventPack.id, input);
      setEventPack(nextPack);
      clearScenarioValidation();
    } catch (error) {
      setEventPackError(errorMessage(error));
      throw error;
    } finally {
      setClaimBusyId(undefined);
    }
  }, [clearScenarioValidation, eventPack]);

  const createEventPack = useCallback(async (input: EventPackCreateInput) => {
    setEventPackState('loading');
    setEventPackError(undefined);
    try {
      const nextPack = await api.createEventPack(input);
      setEventPack(nextPack);
      setSelectedCase({
        id: nextPack.caseId ?? `case-${nextPack.id}`,
        eventPackId: nextPack.id,
        name: nextPack.name,
        nameZh: nextPack.nameZh,
        description: nextPack.description,
        descriptionZh: nextPack.descriptionZh,
        isSynthetic: false,
      });
      setScenarioState(withScenarioDefaults({
        ...(nextPack.defaultExperiment ?? DEFAULT_SCENARIO),
        eventPackId: nextPack.id,
      }));
      clearScenarioValidation();
      setEventPackState('success');
      await refreshCases();
      return nextPack;
    } catch (createError) {
      setEventPackState('error');
      setEventPackError(errorMessage(createError));
      throw createError;
    }
  }, [clearScenarioValidation, refreshCases]);

  const reextractEventPack = useCallback(async (
    sources: EventSourceUpload[],
    useLlm = true,
    maximumClaims = 16,
    acknowledgedContentReview = false,
  ) => {
    if (!eventPack) throw new Error('Select an Event Pack before extracting claims.');
    setEventPackState('loading');
    setEventPackError(undefined);
    try {
      const nextPack = await api.reextractEventPack(
        eventPack.id,
        sources,
        useLlm,
        maximumClaims,
        acknowledgedContentReview,
      );
      setEventPack(nextPack);
      clearScenarioValidation();
      setEventPackState('success');
      return nextPack;
    } catch (extractError) {
      setEventPackState('error');
      setEventPackError(errorMessage(extractError));
      throw extractError;
    }
  }, [clearScenarioValidation, eventPack]);

  const freezeEventPack = useCallback(async () => {
    if (!eventPack) return;
    setEventPackState('loading');
    setEventPackError(undefined);
    try {
      const nextPack = await api.freezeEventPack(eventPack.id);
      setEventPack(nextPack);
      clearScenarioValidation();
      setEventPackState('success');
    } catch (error) {
      setEventPackState('error');
      setEventPackError(errorMessage(error));
      throw error;
    }
  }, [clearScenarioValidation, eventPack]);

  const setScenario = useCallback((nextScenario: ScenarioDraft) => {
    setScenarioState(nextScenario);
    clearScenarioValidation();
  }, [clearScenarioValidation]);

  const validateScenario = useCallback(async (
    origin: ScenarioValidationOrigin = { kind: 'unsaved-draft' },
  ) => {
    const requestGeneration = ++validationGeneration.current;
    const draftDigest = scenarioContentDigest(scenario);
    setValidation(undefined);
    setValidationBinding(undefined);
    setValidationState('loading');
    setValidationError(undefined);
    try {
      const nextValidation = await api.validateScenario(scenario);
      if (requestGeneration !== validationGeneration.current) {
        throw new Error('Scenario changed while validation was in progress.');
      }
      setValidation(nextValidation);
      setValidationBinding({ ...origin, draftDigest });
      setValidationState('success');
      return nextValidation;
    } catch (error) {
      if (requestGeneration === validationGeneration.current) {
        setValidationState('error');
        setValidationError(errorMessage(error));
      }
      throw error;
    }
  }, [scenario]);

  const selectExperiment = useCallback(async (experimentId: string) => {
    const selectionGeneration = ++experimentSelectionGeneration.current;
    resultsRequestGeneration.current += 1;
    setExperimentsError(undefined);
    try {
      const nextExperiment = await api.getExperiment(experimentId);
      if (selectionGeneration !== experimentSelectionGeneration.current) return undefined;
      activeExperimentIdRef.current = nextExperiment.id;
      setActiveExperiment(nextExperiment);
      setExperiments((current) => upsertExperiment(current, nextExperiment));
      setResults(undefined);
      setResultsState('idle');
      setResultsError(undefined);
      return nextExperiment;
    } catch (error) {
      if (selectionGeneration !== experimentSelectionGeneration.current) return undefined;
      setExperimentsError(errorMessage(error));
      throw error;
    }
  }, []);

  const cancelPendingExperimentRequests = useCallback(() => {
    experimentSelectionGeneration.current += 1;
    resultsRequestGeneration.current += 1;
    setResultsState((current) => current === 'loading' ? 'idle' : current);
  }, []);

  const createAndStartExperiment = useCallback(async (scenarioOverride?: ScenarioDraft) => {
    setExperimentsState('loading');
    setExperimentsError(undefined);
    try {
      const effectiveScenario = scenarioOverride
        ? withScenarioDefaults(scenarioOverride)
        : scenario;
      const created = await api.createExperiment(effectiveScenario);
      const started = await api.startExperiment(created.id);
      // 新实验成为活动实验时，必须同时让旧选择与旧结果请求失效，避免把上一场实验的
      // 结果短暂或永久显示在新实验上下文中。
      experimentSelectionGeneration.current += 1;
      resultsRequestGeneration.current += 1;
      activeExperimentIdRef.current = started.id;
      setActiveExperiment(started);
      setExperiments((current) => upsertExperiment(current, started));
      setResults(undefined);
      setResultsState('idle');
      setResultsError(undefined);
      if (scenarioOverride) {
        // 显式规则降级必须同步回当前草稿，避免启动后的界面仍把本次实验标成
        // HYBRID_LLM。后端会再次校验同一份 effectiveScenario。
        setScenarioState(effectiveScenario);
        clearScenarioValidation();
      }
      setExperimentsState('success');
      return started;
    } catch (error) {
      setExperimentsState('error');
      setExperimentsError(errorMessage(error));
      throw error;
    }
  }, [clearScenarioValidation, scenario]);

  const cancelActiveExperiment = useCallback(async () => {
    if (!activeExperiment) return;
    try {
      const cancelled = await api.cancelExperiment(activeExperiment.id);
      setActiveExperiment(cancelled);
      setExperiments((current) => upsertExperiment(current, cancelled));
    } catch (error) {
      setExperimentsError(errorMessage(error));
      throw error;
    }
  }, [activeExperiment]);

  const continueActiveCognitionWithRules = useCallback(async () => {
    if (!activeExperiment) return;
    try {
      const updated = await api.continueCognitionWithRules(activeExperiment.id);
      setActiveExperiment(updated);
      setExperiments((current) => upsertExperiment(current, updated));
    } catch (error) {
      setExperimentsError(errorMessage(error));
      throw error;
    }
  }, [activeExperiment]);

  const invalidateActiveExperiment = useCallback(async (reasonCode: InvalidationReasonCode, reason: string) => {
    if (!activeExperiment) throw new Error('Select a completed experiment before invalidation.');
    try {
      const invalidated = await api.invalidateExperiment(activeExperiment.id, { reasonCode, reason });
      setActiveExperiment(invalidated);
      setExperiments((current) => upsertExperiment(current, invalidated));
      setResults(undefined);
      setResultsState('idle');
      setResultsError(undefined);
    } catch (error) {
      setExperimentsError(errorMessage(error));
      throw error;
    }
  }, [activeExperiment]);

  const loadResults = useCallback(async (experimentId?: string) => {
    const targetId = experimentId ?? activeExperimentIdRef.current;
    if (!targetId) throw new Error('Select an experiment before loading results.');
    const selectionGeneration = experimentSelectionGeneration.current;
    if (activeExperimentIdRef.current !== targetId) return undefined;
    const requestGeneration = ++resultsRequestGeneration.current;
    setResultsState('loading');
    setResultsError(undefined);
    try {
      const nextResults = await api.getResults(targetId);
      if (
        requestGeneration !== resultsRequestGeneration.current
        || selectionGeneration !== experimentSelectionGeneration.current
        || activeExperimentIdRef.current !== targetId
      ) return undefined;
      if (nextResults.experimentId !== targetId) {
        throw new Error('The results response does not match the selected experiment.');
      }
      setResults(nextResults);
      setResultsState('success');
      return nextResults;
    } catch (error) {
      if (
        requestGeneration !== resultsRequestGeneration.current
        || selectionGeneration !== experimentSelectionGeneration.current
        || activeExperimentIdRef.current !== targetId
      ) return undefined;
      setResultsState('error');
      setResultsError(errorMessage(error));
      throw error;
    }
  }, []);

  const exportExperiment = useCallback(async (experimentId: string) => {
    const blob = await api.exportExperiment(experimentId);
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = objectUrl;
    link.download = downloadFilename(experimentId);
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
  }, []);

  const contextValue = useMemo<WorkflowContextValue>(() => ({
    apiConnection,
    health,
    cases,
    casesState,
    casesError,
    selectedCase,
    eventPack,
    eventPackState,
    eventPackError,
    claimBusyId,
    approveAllPendingClaims,
    scenario,
    validation,
    validationBinding,
    validationState,
    validationError,
    experiments,
    experimentsState,
    experimentsError,
    activeExperiment,
    results,
    resultsState,
    resultsError,
    refreshAll,
    refreshCases,
    selectCase,
    createEventPack,
    reextractEventPack,
    reviewClaim,
    freezeEventPack,
    setScenario,
    validateScenario,
    refreshExperiments,
    selectExperiment,
    cancelPendingExperimentRequests,
    createAndStartExperiment,
    cancelActiveExperiment,
    continueActiveCognitionWithRules,
    invalidateActiveExperiment,
    loadResults,
    exportExperiment,
  }), [
    activeExperiment,
    approveAllPendingClaims,
    apiConnection,
    cases,
    casesError,
    casesState,
    claimBusyId,
    createAndStartExperiment,
    createEventPack,
    reextractEventPack,
    eventPack,
    eventPackError,
    eventPackState,
    exportExperiment,
    freezeEventPack,
    health,
    loadResults,
    refreshAll,
    refreshCases,
    refreshExperiments,
    results,
    resultsError,
    resultsState,
    reviewClaim,
    scenario,
    selectCase,
    selectExperiment,
    setScenario,
    validation,
    validationBinding,
    validationError,
    validationState,
    validateScenario,
    experiments,
    experimentsError,
    experimentsState,
    cancelActiveExperiment,
    continueActiveCognitionWithRules,
    cancelPendingExperimentRequests,
    invalidateActiveExperiment,
  ]);

  return <WorkflowContext.Provider value={contextValue}>{children}</WorkflowContext.Provider>;
}

export function useWorkflow(): WorkflowContextValue {
  const context = useContext(WorkflowContext);
  if (!context) throw new Error('useWorkflow must be used inside WorkflowProvider.');
  return context;
}
