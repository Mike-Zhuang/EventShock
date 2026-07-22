import type {
  AdminActivity,
  AdminActivityPage,
  AdminUserPage,
  AdminUserStatistics,
  AdminUserSummary,
  AgentFlowPoint,
  AgentPnlPoint,
  AnalysisDiagnostics,
  AuthSession,
  AuthUser,
  CaseSummary,
  CognitionDecisionSummary,
  CognitionEvalSummary,
  CognitionEvaluationRun,
  CognitionRunMetadata,
  CognitionTelemetry,
  DistributionPoint,
  EventClaim,
  EventPack,
  EventPackContentSecurity,
  EventSource,
  Experiment,
  ExperimentLogEntry,
  ExperimentResults,
  ExperimentStatus,
  GovernanceComponent,
  GovernanceInventory,
  InterventionDefinition,
  InterventionParameter,
  LlmCatalog,
  LlmConfigView,
  LlmConnectionTest,
  LlmModelDescriptor,
  LlmProviderDescriptor,
  LlmProviderId,
  MarketPathPoint,
  MetricDisplayUnit,
  MetricResult,
  NetworkTopology,
  PairedSeedPoint,
  PromptRegistryItem,
  RedTeamDefinition,
  RedTeamRegistry,
  RedTeamResult,
  ResultInterpretationAssistantMessage,
  ResultInterpretationChatMessage,
  ResultInterpretationChatResponse,
  ResultInterpretationConversation,
  ResultInterpretationConversationDeleteResult,
  ResultInterpretationConversationList,
  ResultInterpretationConversationSummary,
  ResultInterpretationLanguage,
  ResultInterpretationStreamErrorPayload,
  ResultInterpretationStreamProgress,
  ResultInterpretationStreamStage,
  ResultInterpretationToolActivity,
  ReleaseGateDefinition,
  ReleaseGateResult,
  ReleaseGateView,
  RobustnessEvidence,
  SavedScenario,
  ScenarioDiffResult,
  ScenarioDraft,
  ScenarioValidation,
  StudyCellOutcomeAnalysis,
  StudyCoreResult,
  StudyDesignCell,
  StudyDesignKind,
  StudyDesignPreview,
  StudyEvidenceBasis,
  StudyExecutionCell,
  StudyFactorPath,
  StudyNegativeControl,
  StudyOutcomeId,
  StudyPairedAnalysis,
  StudyPreset,
  StudyPresetCatalog,
  StudyResultDocument,
  StudyRunRecord,
  StudySensitivityOutcome,
  SystemMetrics,
  TraceNode,
  ValidationLadderLevel,
  ValidationLadderView,
  ValidationCheck,
  VerificationCodeReceipt,
} from './types';

type JsonRecord = Record<string, unknown>;

const PARAMETER_VALUES: InterventionParameter[] = [
  'marketMakerCapacity',
  'socialAmplification',
  'stopLossSensitivity',
  'clarificationDelay',
  'liquidityDepthMultiplier',
  'passiveFlowMultiplier',
  'informationLatency',
];

const NETWORK_TOPOLOGIES: NetworkTopology[] = [
  'ERDOS_RENYI',
  'WATTS_STROGATZ',
  'BARABASI_ALBERT',
  'STOCHASTIC_BLOCK',
  'ECHO_CHAMBER',
  'CORE_PERIPHERY',
];

const LLM_PROVIDER_IDS: LlmProviderId[] = [
  'zhipu',
  'openai',
  'anthropic',
  'google',
  'deepseek',
  'alibaba',
  'moonshot',
];

const METRIC_UNITS: Record<string, MetricDisplayUnit> = {
  maxDrawdownPct: '%',
  realizedVolatilityPct: '%',
  maxSpreadBps: 'bps',
  minDepth: 'shares',
  recoverySteps: 'steps',
  totalVolume: 'shares',
  orderImbalance: 'ratio',
  cascadeScore: 'score',
  returnQuantile05Pct: '%',
  returnQuantile01Pct: '%',
  expectedShortfallPct: '%',
  drawdownDurationSteps: 'steps',
  relativeSpreadBps: 'bps',
  effectiveSpreadBps: 'bps',
  depth10Bps: 'shares',
  depth25Bps: 'shares',
  cancellationRate: 'ratio',
  fillRate: 'ratio',
  rejectionRate: 'ratio',
  marketOrderShare: 'ratio',
  averageQueueTime: 'steps',
  herdingRate: 'ratio',
  beliefDispersion: 'ratio',
  forcedLiquidations: 'count',
  systemEventsPerSecond: 'events/s',
  networkReachRate: 'ratio',
  informationDelaySteps: 'steps',
  liquidityStressIndex: 'score',
  tailLossProbability: 'ratio',
  agentPnlDispersionCents: 'cents',
  systemEquityChangeCents: 'cents',
  forcedLiquidationVolume: 'shares',
  ledgerRejectedOrders: 'count',
  cognitiveOrderCount: 'count',
  benchmarkReturnPct: '%',
  abnormalReturnPct: '%',
  haltCount: 'count',
  haltedSteps: 'steps',
  totalFeesPaidCents: 'cents',
};

export function isRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function read(value: JsonRecord, ...keys: string[]): unknown {
  for (const key of keys) {
    if (key in value) return value[key];
  }
  return undefined;
}

function asString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function asOptionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}

function asNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}

function asBoolean(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function unwrapItems(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (isRecord(value) && Array.isArray(value.items)) return value.items;
  if (isRecord(value) && Array.isArray(value.data)) return value.data;
  return [];
}

function normalizeAuthUser(value: unknown): AuthUser {
  if (!isRecord(value)) throw new TypeError('Authenticated user is not an object.');
  const id = asString(read(value, 'id', 'userId', 'user_id'));
  const email = asString(read(value, 'email'));
  const rawRole = asString(read(value, 'role')).toUpperCase();
  if (!id || !email || !['ADMIN', 'USER'].includes(rawRole)) {
    throw new TypeError('Authenticated user is missing required account fields.');
  }
  return {
    id,
    email,
    role: rawRole as AuthUser['role'],
    emailVerified: asBoolean(read(value, 'emailVerified', 'email_verified'))
      ?? Boolean(asOptionalString(read(value, 'emailVerifiedAt', 'email_verified_at'))),
    createdAt: asString(read(value, 'createdAt', 'created_at')),
    lastLoginAt: asOptionalString(read(value, 'lastLoginAt', 'last_login_at')),
  };
}

export function normalizeAuthSession(value: unknown): AuthSession {
  if (!isRecord(value)) throw new TypeError('Authentication session response is not an object.');
  const authenticated = asBoolean(read(value, 'authenticated')) ?? false;
  const userValue = read(value, 'user');
  const user = userValue === undefined || userValue === null ? undefined : normalizeAuthUser(userValue);
  if (authenticated && !user) throw new TypeError('Authenticated session is missing its user.');
  return {
    authenticationRequired: asBoolean(
      read(value, 'authenticationRequired', 'authentication_required'),
    ) ?? true,
    authenticated,
    user,
    csrfToken: asOptionalString(read(value, 'csrfToken', 'csrf_token')),
  };
}

export function normalizeVerificationCodeReceipt(value: unknown): VerificationCodeReceipt {
  if (!isRecord(value)) throw new TypeError('Verification-code response is not an object.');
  const now = Date.now();
  const secondsUntil = (rawValue: unknown, fallback: number) => {
    const timestamp = Date.parse(asString(rawValue));
    return Number.isFinite(timestamp) ? Math.max(0, Math.ceil((timestamp - now) / 1_000)) : fallback;
  };
  return {
    accepted: asBoolean(read(value, 'accepted')) ?? true,
    retryAfterSeconds: asNumber(
      read(value, 'retryAfterSeconds', 'retry_after_seconds', 'cooldownSeconds', 'cooldown_seconds'),
    ) ?? secondsUntil(read(value, 'resendAfter', 'resend_after'), 60),
    expiresInSeconds: asNumber(read(value, 'expiresInSeconds', 'expires_in_seconds'))
      ?? secondsUntil(read(value, 'expiresAt', 'expires_at'), 600),
  };
}

function normalizeAdminUser(value: unknown): AdminUserSummary {
  const user = normalizeAuthUser(value);
  if (!isRecord(value)) throw new TypeError('Admin user summary is not an object.');
  const rawStatus = asString(read(value, 'status'), 'ACTIVE').toUpperCase();
  return {
    ...user,
    status: rawStatus === 'DISABLED' ? 'DISABLED' : 'ACTIVE',
    lastActivityAt: asOptionalString(read(value, 'lastActivityAt', 'last_activity_at')),
    experimentCount: asNumber(read(value, 'experimentCount', 'experiment_count')) ?? 0,
    activityCount: asNumber(read(value, 'activityCount', 'activity_count')) ?? 0,
  };
}

function normalizeAdminStatistics(value: unknown, total: number): AdminUserStatistics {
  const summary = isRecord(value) ? value : {};
  return {
    totalUsers: asNumber(read(summary, 'totalUsers', 'total_users')) ?? total,
    verifiedUsers: asNumber(read(summary, 'verifiedUsers', 'verified_users')) ?? 0,
    activeUsersLastSevenDays: asNumber(read(
      summary,
      'activeUsersLastSevenDays',
      'active_users_last_seven_days',
      'activeUsers7d',
      'active_users_7d',
    )) ?? 0,
    totalActivities: asNumber(read(summary, 'totalActivities', 'total_activities')) ?? 0,
  };
}

export function normalizeAdminUserPage(value: unknown): AdminUserPage {
  if (!isRecord(value)) throw new TypeError('Admin users response is not an object.');
  const items = unwrapItems(value).map(normalizeAdminUser);
  const total = asNumber(read(value, 'total')) ?? items.length;
  return {
    items,
    total,
    summary: normalizeAdminStatistics(read(value, 'summary'), total),
  };
}

function normalizeAdminActivity(value: unknown): AdminActivity {
  if (!isRecord(value)) throw new TypeError('Admin activity is not an object.');
  const id = asString(read(value, 'id', 'activityId', 'activity_id'));
  const userId = asOptionalString(read(value, 'userId', 'user_id'));
  const action = asString(read(value, 'action'));
  const createdAt = asString(read(value, 'createdAt', 'created_at'));
  if (!id || !action || !createdAt) {
    throw new TypeError('Admin activity is missing required fields.');
  }
  return {
    id,
    userId,
    userEmail: asOptionalString(read(value, 'userEmail', 'user_email')),
    action,
    entityType: asOptionalString(read(value, 'entityType', 'entity_type')),
    entityId: asOptionalString(read(value, 'entityId', 'entity_id')),
    outcome: asString(read(value, 'outcome', 'status')).toUpperCase() === 'FAILED'
      ? 'FAILED'
      : 'SUCCEEDED',
    createdAt,
  };
}

export function normalizeAdminActivityPage(value: unknown): AdminActivityPage {
  if (!isRecord(value)) throw new TypeError('Admin activity response is not an object.');
  const items = unwrapItems(value).map(normalizeAdminActivity);
  return {
    items,
    total: asNumber(read(value, 'total')) ?? items.length,
  };
}

function asParameter(value: unknown): InterventionParameter | undefined {
  return typeof value === 'string' && PARAMETER_VALUES.includes(value as InterventionParameter)
    ? value as InterventionParameter
    : undefined;
}

function asLlmProviderId(value: unknown): LlmProviderId | undefined {
  if (typeof value !== 'string') return undefined;
  const normalized = value.toLowerCase() as LlmProviderId;
  return LLM_PROVIDER_IDS.includes(normalized) ? normalized : undefined;
}

function normalizeIntervention(value: unknown): InterventionDefinition | undefined {
  if (!isRecord(value)) return undefined;
  const parameter = asParameter(read(value, 'parameter'));
  const baselineValue = asNumber(read(value, 'baselineValue', 'baseline_value'));
  const interventionValue = asNumber(read(value, 'interventionValue', 'intervention_value'));
  if (!parameter || baselineValue === undefined || interventionValue === undefined) return undefined;
  return { parameter, baselineValue, interventionValue };
}

function normalizeMarket(value: unknown): ScenarioDraft['market'] | undefined {
  if (!isRecord(value)) return undefined;
  const instrumentId = asString(read(value, 'instrumentId', 'instrument_id'));
  const benchmarkId = asString(read(value, 'benchmarkId', 'benchmark_id'));
  const tickSize = asNumber(read(value, 'tickSize', 'tick_size'));
  const initialPrice = asNumber(read(value, 'initialPrice', 'initial_price'));
  const feeBps = asNumber(read(value, 'feeBps', 'fee_bps'));
  const latencyMs = asNumber(read(value, 'latencyMs', 'latency_ms'));
  const priceCollarBps = asNumber(read(value, 'priceCollarBps', 'price_collar_bps'));
  if (!instrumentId || !benchmarkId || tickSize === undefined || initialPrice === undefined
    || feeBps === undefined || latencyMs === undefined || priceCollarBps === undefined) return undefined;
  return {
    instrumentId,
    benchmarkId,
    tickSize,
    initialPrice,
    feeBps,
    latencyMs,
    openingAuction: asBoolean(read(value, 'openingAuction', 'opening_auction')) ?? true,
    volatilityHalt: asBoolean(read(value, 'volatilityHalt', 'volatility_halt')) ?? true,
    priceCollarBps,
  };
}

function normalizePopulation(value: unknown): ScenarioDraft['population'] | undefined {
  if (!isRecord(value)) return undefined;
  const profileId = asString(read(value, 'profileId', 'profile_id'));
  const representativeLlmAgents = asNumber(read(value, 'representativeLlmAgents', 'representative_llm_agents'));
  const institutionalShare = asNumber(read(value, 'institutionalShare', 'institutional_share'));
  if (!profileId || representativeLlmAgents === undefined || institutionalShare === undefined) return undefined;
  return {
    profileId,
    representativeLlmAgents,
    institutionalShare,
    leverageEnabled: asBoolean(read(value, 'leverageEnabled', 'leverage_enabled')) ?? true,
    shortSellingEnabled: asBoolean(read(value, 'shortSellingEnabled', 'short_selling_enabled')) ?? true,
  };
}

function normalizeNetwork(value: unknown): ScenarioDraft['network'] | undefined {
  if (!isRecord(value)) return undefined;
  const topologyValue = asString(read(value, 'topology'));
  const topology = NETWORK_TOPOLOGIES.includes(topologyValue as NetworkTopology)
    ? topologyValue as NetworkTopology
    : undefined;
  const averageDegree = asNumber(read(value, 'averageDegree', 'average_degree'));
  const rewiringProbability = asNumber(read(value, 'rewiringProbability', 'rewiring_probability'));
  const echoChamberStrength = asNumber(read(value, 'echoChamberStrength', 'echo_chamber_strength'));
  const correctionReach = asNumber(read(value, 'correctionReach', 'correction_reach'));
  if (!topology || averageDegree === undefined || rewiringProbability === undefined
    || echoChamberStrength === undefined || correctionReach === undefined) return undefined;
  return { topology, averageDegree, rewiringProbability, echoChamberStrength, correctionReach };
}

function normalizeLlmPolicy(value: unknown): ScenarioDraft['llmPolicy'] | undefined {
  if (!isRecord(value)) return undefined;
  const mode = asString(read(value, 'mode'));
  const modelId = asString(read(value, 'modelId', 'model_id'));
  const representativeAgentCount = asNumber(read(value, 'representativeAgentCount', 'representative_agent_count'));
  const decisionIntervalSteps = asNumber(read(value, 'decisionIntervalSteps', 'decision_interval_steps'));
  const callBudget = asNumber(read(value, 'callBudget', 'call_budget'));
  const maxCostUsd = asNumber(read(value, 'maxCostUsd', 'max_cost_usd'));
  if ((mode !== 'RULE_ONLY' && mode !== 'HYBRID_LLM') || !modelId
    || representativeAgentCount === undefined || decisionIntervalSteps === undefined
    || callBudget === undefined || maxCostUsd === undefined) return undefined;
  return {
    mode,
    provider: asLlmProviderId(read(value, 'provider')) ?? 'zhipu',
    modelId,
    representativeAgentCount,
    decisionIntervalSteps,
    callBudget,
    maxCostUsd,
    fallbackToRules: asBoolean(read(value, 'fallbackToRules', 'fallback_to_rules')) ?? true,
  };
}

function normalizeScenario(value: unknown): ScenarioDraft | undefined {
  if (!isRecord(value)) return undefined;
  const eventPackId = asString(read(value, 'eventPackId', 'event_pack_id'));
  const intervention = normalizeIntervention(read(value, 'intervention'));
  const seedCount = asNumber(read(value, 'seedCount', 'seed_count'));
  const populationSize = asNumber(read(value, 'populationSize', 'population_size'));
  const steps = asNumber(read(value, 'steps'));
  if (!eventPackId || !intervention || ![10, 25, 50].includes(seedCount ?? -1) || populationSize === undefined || steps === undefined) return undefined;
  return {
    eventPackId,
    question: asOptionalString(read(value, 'question')),
    questionZh: asOptionalString(read(value, 'questionZh', 'question_zh')),
    intervention,
    seedCount: seedCount as 10 | 25 | 50,
    seedRoot: asNumber(read(value, 'seedRoot', 'seed_root')),
    populationSize,
    steps,
    market: normalizeMarket(read(value, 'market')),
    population: normalizePopulation(read(value, 'population')),
    network: normalizeNetwork(read(value, 'network')),
    llmPolicy: normalizeLlmPolicy(read(value, 'llmPolicy', 'llm_policy')),
    primaryOutcome: asOptionalString(read(value, 'primaryOutcome', 'primary_outcome')),
    secondaryOutcomes: asStringArray(read(value, 'secondaryOutcomes', 'secondary_outcomes')),
    stoppingRule: isRecord(read(value, 'stoppingRule', 'stopping_rule')) ? (() => {
      const stoppingRule = read(value, 'stoppingRule', 'stopping_rule') as JsonRecord;
      const minimumPairs = asNumber(read(stoppingRule, 'minimumPairs', 'minimum_pairs'));
      const maximumPairs = asNumber(read(stoppingRule, 'maximumPairs', 'maximum_pairs'));
      if (minimumPairs === undefined || maximumPairs === undefined) return undefined;
      return {
        minimumPairs,
        maximumPairs,
        targetCiHalfWidth: asNumber(read(stoppingRule, 'targetCiHalfWidth', 'target_ci_half_width')),
      };
    })() : undefined,
    acknowledgedScenarioNotForecast: asBoolean(read(value, 'acknowledgedScenarioNotForecast', 'acknowledged_scenario_not_forecast')),
    acknowledgedSyntheticAssumptions: asBoolean(read(value, 'acknowledgedSyntheticAssumptions', 'acknowledged_synthetic_assumptions')),
  };
}

export function normalizeSavedScenario(value: unknown): SavedScenario {
  if (!isRecord(value)) throw new TypeError('Saved scenario response is not an object.');
  const id = asString(read(value, 'id', 'scenarioId', 'scenario_id'));
  const name = asString(read(value, 'name'));
  const config = normalizeScenario(read(value, 'config'));
  const contentHash = asString(read(value, 'contentHash', 'content_hash'));
  if (!id || !name || !config || !contentHash) {
    throw new TypeError('Saved scenario response is missing required fields.');
  }
  return {
    id,
    name,
    config,
    frozen: asBoolean(read(value, 'frozen')) ?? false,
    contentHash,
    createdAt: asOptionalString(read(value, 'createdAt', 'created_at')),
    updatedAt: asOptionalString(read(value, 'updatedAt', 'updated_at')),
  };
}

export function normalizeSavedScenarios(value: unknown): SavedScenario[] {
  return unwrapItems(value).flatMap((item) => {
    try {
      return [normalizeSavedScenario(item)];
    } catch {
      return [];
    }
  });
}

export function normalizeScenarioDiff(value: unknown): ScenarioDiffResult {
  if (!isRecord(value)) throw new TypeError('Scenario diff response is not an object.');
  const changes = unwrapItems(read(value, 'changes')).flatMap((item) => {
    if (!isRecord(item)) return [];
    const path = asString(read(item, 'path'));
    if (!path) return [];
    return [{ path, baseline: read(item, 'baseline'), intervention: read(item, 'intervention') }];
  });
  return {
    changeCount: asNumber(read(value, 'changeCount', 'change_count')) ?? changes.length,
    changedPaths: asStringArray(read(value, 'changedPaths', 'changed_paths')),
    changes,
    singleInterventionCompliant: asBoolean(read(value, 'singleInterventionCompliant', 'single_intervention_compliant')) ?? false,
  };
}

function normalizeSource(value: unknown): EventSource | null {
  if (!isRecord(value)) return null;
  const id = asString(read(value, 'id', 'sourceId', 'source_id'));
  const title = asString(read(value, 'title', 'name'));
  if (!id || !title) return null;
  return {
    id,
    title,
    titleZh: asOptionalString(read(value, 'titleZh', 'title_zh')),
    publisher: asOptionalString(read(value, 'publisher')),
    url: asOptionalString(read(value, 'url')),
    tier: asOptionalString(read(value, 'tier', 'sourceTier', 'source_tier')),
    publishedAt: asOptionalString(read(value, 'publishedAt', 'published_at', 'knownAt', 'known_at')),
    knownAt: asOptionalString(read(value, 'knownAt', 'known_at')),
    retrievedAt: asOptionalString(read(value, 'retrievedAt', 'retrieved_at')),
    hash: asOptionalString(read(value, 'hash', 'contentHash', 'content_hash')),
    sourceType: asOptionalString(read(value, 'sourceType', 'source_type')),
    isOfficial: asBoolean(read(value, 'isOfficial', 'is_official')),
    license: asOptionalString(read(value, 'license', 'licenseId', 'license_id')),
    exportAllowed: asBoolean(read(value, 'exportAllowed', 'export_allowed')),
  };
}

function normalizeClaim(value: unknown): EventClaim | null {
  if (!isRecord(value)) return null;
  const id = asString(read(value, 'id', 'claimId', 'claim_id'));
  const text = asString(read(value, 'text', 'claim', 'content'));
  if (!id || !text) return null;
  const sourceIds = asStringArray(read(value, 'sourceIds', 'source_ids'));
  return {
    id,
    text,
    textZh: asOptionalString(read(value, 'textZh', 'text_zh')),
    status: asString(read(value, 'reviewStatus', 'review_status', 'status'), 'AI_PROPOSED') as EventClaim['status'],
    sourceId: sourceIds[0] ?? asOptionalString(read(value, 'sourceId', 'source_id')),
    sourceIds,
    sourceTier: asOptionalString(read(value, 'sourceTier', 'source_tier')),
    publishedAt: asOptionalString(read(value, 'publishedAt', 'published_at')),
    knownAt: asOptionalString(read(value, 'knownAt', 'known_at')),
    confidence: asNumber(read(value, 'confidence')),
    impactChannels: asStringArray(read(value, 'impactChannels', 'impact_channels')),
    editedText: asOptionalString(read(value, 'editedText', 'edited_text')),
    isRequired: asBoolean(read(value, 'isRequired', 'is_required')),
    claimType: asOptionalString(read(value, 'claimType', 'claim_type')),
  };
}

export function normalizeCases(value: unknown): CaseSummary[] {
  return unwrapItems(value)
    .map((item): CaseSummary | null => {
      if (!isRecord(item)) return null;
      const id = asString(read(item, 'id', 'caseId', 'case_id'));
      const name = asString(read(item, 'name', 'title'));
      if (!id || !name) return null;
      return {
        id,
        name,
        nameZh: asOptionalString(read(item, 'titleZh', 'nameZh', 'title_zh')),
        description: asOptionalString(read(item, 'description', 'summary')),
        descriptionZh: asOptionalString(read(item, 'summaryZh', 'descriptionZh', 'summary_zh')),
        eventPackId: asOptionalString(read(item, 'eventPackId', 'event_pack_id')),
        status: asOptionalString(read(item, 'status')),
        isSynthetic: asBoolean(read(item, 'synthetic', 'isSynthetic', 'is_synthetic')),
        syntheticLabel: asOptionalString(read(item, 'syntheticLabel')),
        syntheticLabelZh: asOptionalString(read(item, 'syntheticLabelZh')),
        updatedAt: asOptionalString(read(item, 'updatedAt', 'updated_at')),
        featured: asBoolean(read(item, 'featured')),
        caseRole: asOptionalString(read(item, 'caseRole', 'case_role')),
        validationStatus: asOptionalString(read(item, 'validationStatus', 'validation_status')),
      };
    })
    .filter((item): item is CaseSummary => item !== null);
}

export function normalizeEventPack(value: unknown): EventPack {
  if (!isRecord(value)) throw new TypeError('Event Pack response is not an object.');
  const limitations = normalizeLimitations(read(value, 'limitations'));
  const extractionValue = read(value, 'extraction');
  const extraction = isRecord(extractionValue) ? extractionValue : undefined;
  const contentSecurity = normalizeEventPackContentSecurity(
    (extraction ? read(extraction, 'contentSecurity', 'content_security') : undefined)
      ?? read(value, 'contentSecurity', 'content_security'),
  );
  const instrumentValue = read(value, 'instrument');
  const instrument = typeof instrumentValue === 'string'
    ? instrumentValue
    : isRecord(instrumentValue)
      ? asOptionalString(read(instrumentValue, 'symbol', 'instrumentId', 'instrument_id'))
      : undefined;
  return {
    id: asString(read(value, 'id', 'eventPackId', 'event_pack_id')),
    caseId: asOptionalString(read(value, 'caseId', 'case_id')),
    name: asString(read(value, 'name', 'title'), 'Untitled Event Pack'),
    nameZh: asOptionalString(read(value, 'titleZh', 'nameZh', 'title_zh')),
    description: asOptionalString(read(value, 'description', 'summary')),
    descriptionZh: asOptionalString(read(value, 'summaryZh', 'descriptionZh', 'summary_zh')),
    status: asString(read(value, 'status'), 'DRAFT'),
    pointInTime: asOptionalString(read(value, 'asOf', 'pointInTime', 'point_in_time')),
    frozenAt: asOptionalString(read(value, 'frozenAt', 'frozen_at')),
    extractionMode: asOptionalString(read(value, 'extractionMode', 'extraction_mode'))
      ?? (extraction ? asOptionalString(read(extraction, 'mode')) : undefined),
    contentSecurity,
    editableExtraction: asBoolean(read(value, 'editableExtraction', 'editable_extraction'))
      ?? asString(read(value, 'id', 'eventPackId', 'event_pack_id')).startsWith('custom-'),
    instrument,
    isSynthetic: asBoolean(read(value, 'synthetic', 'isSynthetic', 'is_synthetic')),
    syntheticLabel: asOptionalString(read(value, 'syntheticLabel', 'synthetic_label')),
    syntheticLabelZh: asOptionalString(read(value, 'syntheticLabelZh', 'synthetic_label_zh')),
    limitations: limitations.en,
    limitationsZh: limitations.zh,
    sources: unwrapItems(read(value, 'sources')).map(normalizeSource).filter((item): item is EventSource => item !== null),
    claims: unwrapItems(read(value, 'claims')).map(normalizeClaim).filter((item): item is EventClaim => item !== null),
    defaultExperiment: normalizeScenario({
      ...(isRecord(read(value, 'defaultExperiment')) ? read(value, 'defaultExperiment') as JsonRecord : {}),
      eventPackId: asString(read(value, 'id', 'eventPackId', 'event_pack_id')),
    }),
  };
}

function normalizeEventPackContentSecurity(value: unknown): EventPackContentSecurity | undefined {
  if (!isRecord(value)) return undefined;
  const findings = unwrapItems(read(value, 'findings')).flatMap((item) => {
    if (!isRecord(item)) return [];
    const code = asOptionalString(read(item, 'code'));
    const field = asOptionalString(read(item, 'field'));
    if (!code || !field) return [];
    return [{
      sourceId: asOptionalString(read(item, 'sourceId', 'source_id')),
      code,
      severity: asString(read(item, 'severity'), 'UNKNOWN'),
      field,
      offset: asNumber(read(item, 'offset')) ?? 0,
    }];
  });
  const sources = unwrapItems(read(value, 'sources')).flatMap((item) => {
    if (!isRecord(item)) return [];
    const sourceId = asOptionalString(read(item, 'sourceId', 'source_id'));
    if (!sourceId) return [];
    return [{
      sourceId,
      decision: asString(read(item, 'decision'), 'UNKNOWN'),
      sourceReviewLabel: asOptionalString(read(item, 'sourceReviewLabel', 'source_review_label')),
      officialHost: asOptionalString(read(item, 'officialHost', 'official_host')),
      findingCount: asNumber(read(item, 'findingCount', 'finding_count')) ?? 0,
    }];
  });
  return {
    schemaVersion: asString(read(value, 'schemaVersion', 'schema_version'), '1.0.0'),
    decision: asString(read(value, 'decision'), 'UNKNOWN'),
    acknowledged: asBoolean(read(value, 'acknowledged')) ?? false,
    sourceCount: asNumber(read(value, 'sourceCount', 'source_count')) ?? sources.length,
    findingCount: asNumber(read(value, 'findingCount', 'finding_count')) ?? findings.length,
    findingsTruncated: asBoolean(read(value, 'findingsTruncated', 'findings_truncated')) ?? false,
    rawContentRetained: asBoolean(read(value, 'rawContentRetained', 'raw_content_retained')),
    findings,
    sources,
  };
}

function normalizeLog(value: unknown): ExperimentLogEntry | null {
  if (!isRecord(value)) return null;
  const message = asString(read(value, 'message', 'detail'));
  if (!message) return null;
  return {
    timestamp: asString(read(value, 'timestamp', 'createdAt', 'created_at'), ''),
    level: asString(read(value, 'level'), 'INFO'),
    message,
    seed: asNumber(read(value, 'seed')),
  };
}

function normalizeLiveMarketSnapshot(value: unknown) {
  if (!isRecord(value)) return undefined;
  const step = asNumber(read(value, 'step'));
  const completedSteps = asNumber(read(value, 'completedSteps', 'completed_steps'));
  const totalSteps = asNumber(read(value, 'totalSteps', 'total_steps'));
  if (step === undefined || completedSteps === undefined || totalSteps === undefined) return undefined;
  return {
    step,
    completedSteps,
    totalSteps,
    price: asNumber(read(value, 'price')),
    spreadBps: asNumber(read(value, 'spreadBps', 'spread_bps')),
    depth: asNumber(read(value, 'depth')),
    volume: asNumber(read(value, 'volume')),
    sentiment: asNumber(read(value, 'sentiment')),
    marketState: asOptionalString(read(value, 'marketState', 'market_state')),
    haltCount: asNumber(read(value, 'haltCount', 'halt_count')),
    activeCognitiveAgents: asNumber(read(value, 'activeCognitiveAgents', 'active_cognitive_agents')),
  };
}

export function normalizeExperiment(value: unknown): Experiment {
  if (!isRecord(value)) throw new TypeError('Experiment response is not an object.');
  const status = asString(read(value, 'status'), 'READY').toUpperCase() as ExperimentStatus;
  const request = normalizeScenario(read(value, 'request'));
  const totalSeeds = asNumber(read(value, 'totalPairs', 'total_pairs', 'totalSeeds', 'total_seeds')) ?? request?.seedCount;
  const completedSeeds = asNumber(read(value, 'completedPairs', 'completed_pairs', 'completedSeeds', 'completed_seeds'));
  const rawProgress = asNumber(read(value, 'progress', 'progressPercent', 'progress_percent'));
  const runtimeValue = read(value, 'runtime', 'liveState', 'live_state');
  const runtime = isRecord(runtimeValue) ? runtimeValue : {};
  const runtimeLogs = read(runtime, 'logs');
  const progress = rawProgress !== undefined
    ? Math.max(0, Math.min(rawProgress > 1 ? rawProgress : rawProgress * 100, 100))
    : totalSeeds && completedSeeds !== undefined
      ? Math.max(0, Math.min((completedSeeds / totalSeeds) * 100, 100))
      : status === 'COMPLETED' ? 100 : 0;
  return {
    id: asString(read(value, 'id', 'experimentId', 'experiment_id')),
    eventPackId: request?.eventPackId ?? asString(read(value, 'eventPackId', 'event_pack_id')),
    status,
    createdAt: asOptionalString(read(value, 'createdAt', 'created_at')),
    updatedAt: asOptionalString(read(value, 'updatedAt', 'updated_at')),
    completedAt: asOptionalString(read(value, 'completedAt', 'completed_at')),
    invalidatedAt: asOptionalString(read(value, 'invalidatedAt', 'invalidated_at')),
    invalidationReasonCode: asOptionalString(read(value, 'invalidationReasonCode', 'invalidation_reason_code')),
    invalidationReason: asOptionalString(read(value, 'invalidationReason', 'invalidation_reason')),
    resultsAvailable: asBoolean(read(value, 'resultsAvailable', 'results_available')),
    resultsPreserved: asBoolean(read(value, 'resultsPreserved', 'results_preserved')),
    validForResearchUse: asBoolean(read(value, 'validForResearchUse', 'valid_for_research_use')),
    progress,
    completedSeeds,
    validSeeds: completedSeeds,
    totalSeeds,
    currentSeed: asNumber(read(value, 'currentSeed', 'current_seed'))
      ?? asNumber(read(runtime, 'currentSeed', 'current_seed')),
    error: asOptionalString(read(value, 'errorCode', 'error_code', 'error', 'errorMessage', 'error_message')),
    scenario: request,
    intervention: request?.intervention ?? normalizeIntervention(read(value, 'intervention')),
    liveState: Object.keys(runtime).length > 0 ? {
      phase: asOptionalString(read(runtime, 'phase')),
      pairIndex: asNumber(read(runtime, 'pairIndex', 'pair_index')),
      currentSeed: asNumber(read(runtime, 'currentSeed', 'current_seed')),
      baseline: normalizeLiveMarketSnapshot(read(runtime, 'baseline')),
      intervention: normalizeLiveMarketSnapshot(read(runtime, 'intervention')),
      resumedFromCheckpoint: asBoolean(read(runtime, 'resumedFromCheckpoint', 'resumed_from_checkpoint')),
      checkpointPairs: asNumber(read(runtime, 'checkpointPairs', 'checkpoint_pairs')),
    } : undefined,
    logs: unwrapItems(read(value, 'logs')).length > 0
      ? unwrapItems(read(value, 'logs')).map(normalizeLog).filter((item): item is ExperimentLogEntry => item !== null)
      : unwrapItems(runtimeLogs).map(normalizeLog).filter((item): item is ExperimentLogEntry => item !== null),
  };
}

export function normalizeExperiments(value: unknown): Experiment[] {
  return unwrapItems(value).map(normalizeExperiment);
}

function intervalBounds(value: unknown): { lower?: number; upper?: number } {
  if (!isRecord(value)) return {};
  return { lower: asNumber(read(value, 'lower')), upper: asNumber(read(value, 'upper')) };
}

function normalizeMetricSummaries(value: unknown): MetricResult[] {
  if (!isRecord(value)) return [];
  return Object.entries(value).flatMap(([metricId, summary]) => {
    if (!isRecord(summary)) return [];
    const baseline = isRecord(summary.baseline) ? summary.baseline : {};
    const intervention = isRecord(summary.intervention) ? summary.intervention : {};
    const delta = isRecord(summary.delta) ? summary.delta : {};
    const deltaInterval = intervalBounds(read(delta, 'interval95'));
    const bootstrapInterval = intervalBounds(read(delta, 'bootstrap95'));
    const bootstrap = isRecord(read(delta, 'bootstrap95')) ? read(delta, 'bootstrap95') as JsonRecord : {};
    const effectSize = isRecord(read(delta, 'effectSize', 'effect_size')) ? read(delta, 'effectSize', 'effect_size') as JsonRecord : {};
    const exclusions = asStringArray(read(summary, 'exclusionReasons', 'exclusion_reasons'));
    return [{
      id: metricId,
      label: metricId,
      unit: METRIC_UNITS[metricId],
      baseline: asNumber(read(baseline, 'median')),
      intervention: asNumber(read(intervention, 'median')),
      delta: asNumber(read(delta, 'median')),
      baselineMean: asNumber(read(baseline, 'mean')),
      interventionMean: asNumber(read(intervention, 'mean')),
      deltaMean: asNumber(read(delta, 'mean')),
      ciLow: deltaInterval.lower,
      ciHigh: deltaInterval.upper,
      n: asNumber(read(delta, 'validN')),
      stable: asBoolean(read(summary, 'stable')),
      directionConsistencyRate: asNumber(read(delta, 'directionConsistencyRate')),
      signConsistency: asNumber(read(delta, 'signConsistency', 'sign_consistency')),
      bootstrapCiLow: bootstrapInterval.lower,
      bootstrapCiHigh: bootstrapInterval.upper,
      bootstrapContainsZero: asBoolean(read(bootstrap, 'containsZero', 'contains_zero')),
      cohensDz: asNumber(read(effectSize, 'cohensDz', 'cohens_dz')),
      matchedRankBiserial: asNumber(read(effectSize, 'matchedRankBiserial', 'matched_rank_biserial')),
      standardDeviationDifference: asNumber(read(effectSize, 'standardDeviationDifference', 'standard_deviation_difference')),
      positiveTailProbability: asNumber(read(delta, 'positiveTailProbability', 'positive_tail_probability')),
      negativeTailProbability: asNumber(read(delta, 'negativeTailProbability', 'negative_tail_probability')),
      excludedRuns: asNumber(read(summary, 'excludedRuns', 'excluded_runs')),
      exclusionReasons: exclusions,
      sensitivityFlag: asOptionalString(read(summary, 'sensitivityFlag', 'sensitivity_flag')),
      interpretation: asOptionalString(read(summary, 'interpretation')),
      interpretationZh: asOptionalString(read(summary, 'interpretationZh', 'interpretation_zh')),
      limitation: asOptionalString(read(summary, 'limitation')),
      limitationZh: asOptionalString(read(summary, 'limitationZh', 'limitation_zh')),
    }];
  });
}

function normalizePairedRuns(value: unknown, metricId = 'maxSpreadBps'): PairedSeedPoint[] {
  return unwrapItems(value).flatMap((item) => {
    if (!isRecord(item)) return [];
    const seed = asNumber(read(item, 'seed'));
    const baselineRecord = isRecord(item.baseline) ? item.baseline : {};
    const interventionRecord = isRecord(item.intervention) ? item.intervention : {};
    const deltaRecord = isRecord(item.delta) ? item.delta : {};
    const baseline = asNumber(read(baselineRecord, metricId));
    const intervention = asNumber(read(interventionRecord, metricId));
    if (seed === undefined || baseline === undefined || intervention === undefined) return [];
    return [{
      seed,
      baseline,
      intervention,
      delta: asNumber(read(deltaRecord, metricId)) ?? intervention - baseline,
    }];
  });
}

function normalizePairedSeries(value: unknown): Record<string, PairedSeedPoint[]> {
  const pairs = unwrapItems(value);
  const metricIds = new Set<string>();
  pairs.forEach((item) => {
    if (!isRecord(item)) return;
    const delta = isRecord(item.delta) ? item.delta : {};
    Object.entries(delta).forEach(([key, itemValue]) => {
      if (asNumber(itemValue) !== undefined) metricIds.add(key);
    });
  });
  return Object.fromEntries(
    [...metricIds].sort().map((metricId) => [metricId, normalizePairedRuns(pairs, metricId)]),
  );
}

export function buildHistogram(pairs: PairedSeedPoint[], binCount = 7): DistributionPoint[] {
  if (pairs.length === 0) return [];
  const allValues = pairs.flatMap((pair) => [pair.baseline, pair.intervention]);
  const minimum = Math.min(...allValues);
  const maximum = Math.max(...allValues);
  if (minimum === maximum) return [{ bin: Number(minimum.toFixed(3)), baseline: pairs.length, intervention: pairs.length }];
  const safeBinCount = Math.max(1, Math.min(Math.floor(binCount), 20));
  const width = (maximum - minimum) / safeBinCount;
  const bins = Array.from({ length: safeBinCount }, (_, index) => ({
    bin: Number((minimum + width * (index + 0.5)).toFixed(3)),
    baseline: 0,
    intervention: 0,
  }));
  const indexFor = (value: number) => Math.min(Math.floor((value - minimum) / width), safeBinCount - 1);
  pairs.forEach((pair) => {
    bins[indexFor(pair.baseline)].baseline += 1;
    bins[indexFor(pair.intervention)].intervention += 1;
  });
  return bins;
}

function numericArray(record: JsonRecord, key: string): number[] {
  const value = read(record, key);
  return Array.isArray(value) ? value.map(asNumber).filter((item): item is number => item !== undefined) : [];
}

function normalizeMedianPaths(value: unknown): MarketPathPoint[] {
  if (!isRecord(value)) return [];
  const steps = numericArray(value, 'step');
  const baseline = isRecord(value.baseline) ? value.baseline : {};
  const intervention = isRecord(value.intervention) ? value.intervention : {};
  const baselinePrice = numericArray(baseline, 'price');
  const interventionPrice = numericArray(intervention, 'price');
  const baselineSpread = numericArray(baseline, 'spreadBps');
  const interventionSpread = numericArray(intervention, 'spreadBps');
  const baselineDepth = numericArray(baseline, 'depth');
  const interventionDepth = numericArray(intervention, 'depth');
  return steps.map((step, index) => ({
    step,
    baselinePrice: baselinePrice[index],
    interventionPrice: interventionPrice[index],
    baselineSpread: baselineSpread[index],
    interventionSpread: interventionSpread[index],
    baselineDepth: baselineDepth[index],
    interventionDepth: interventionDepth[index],
  }));
}

function normalizeAgentFlows(value: unknown): AgentFlowPoint[] {
  if (!isRecord(value)) return [];
  return Object.entries(value).flatMap(([agentType, flow]) => {
    if (!isRecord(flow)) return [];
    const baseline = isRecord(flow.baseline) ? flow.baseline : {};
    const intervention = isRecord(flow.intervention) ? flow.intervention : {};
    const baselineNetFlow = asNumber(read(baseline, 'netVolume'));
    const interventionNetFlow = asNumber(read(intervention, 'netVolume'));
    return [{
      agentType,
      baselineNetFlow,
      interventionNetFlow,
      delta: baselineNetFlow !== undefined && interventionNetFlow !== undefined
        ? interventionNetFlow - baselineNetFlow
        : undefined,
    }];
  });
}

function normalizeAgentPnl(value: unknown): AgentPnlPoint[] {
  if (!isRecord(value)) return [];
  return Object.entries(value).flatMap(([agentType, metrics]) => {
    if (!isRecord(metrics)) return [];
    const equityChange = isRecord(read(metrics, 'equityChangeCents', 'equity_change_cents'))
      ? read(metrics, 'equityChangeCents', 'equity_change_cents') as JsonRecord
      : {};
    const baseline = isRecord(read(equityChange, 'baseline')) ? read(equityChange, 'baseline') as JsonRecord : {};
    const intervention = isRecord(read(equityChange, 'intervention')) ? read(equityChange, 'intervention') as JsonRecord : {};
    const delta = isRecord(read(equityChange, 'delta')) ? read(equityChange, 'delta') as JsonRecord : {};
    return [{
      agentType,
      baselineEquityChangeCents: asNumber(read(baseline, 'median')),
      interventionEquityChangeCents: asNumber(read(intervention, 'median')),
      deltaEquityChangeCents: asNumber(read(delta, 'median')),
      validN: asNumber(read(delta, 'validN', 'valid_n')),
      directionConsistencyRate: asNumber(read(delta, 'directionConsistencyRate', 'direction_consistency_rate')),
    }];
  });
}

function normalizeStoppingRule(value: unknown): ExperimentResults['stoppingRule'] {
  if (!isRecord(value)) return undefined;
  const bootstrap = isRecord(read(value, 'bootstrapInterval95', 'bootstrap_interval_95'))
    ? read(value, 'bootstrapInterval95', 'bootstrap_interval_95') as JsonRecord
    : undefined;
  return {
    mode: asOptionalString(read(value, 'mode')),
    triggered: asBoolean(read(value, 'triggered')) ?? false,
    reason: asString(read(value, 'reason'), 'NOT_REPORTED'),
    primaryOutcome: asOptionalString(read(value, 'primaryOutcome', 'primary_outcome')),
    completedPairs: asNumber(read(value, 'completedPairs', 'completed_pairs')) ?? 0,
    observedCiHalfWidth: asNumber(read(value, 'observedCiHalfWidth', 'observed_ci_half_width')),
    targetCiHalfWidth: asNumber(read(value, 'targetCiHalfWidth', 'target_ci_half_width')),
    minimumPairs: asNumber(read(value, 'minimumPairs', 'minimum_pairs')),
    maximumPairs: asNumber(read(value, 'maximumPairs', 'maximum_pairs')),
    bootstrapInterval95: bootstrap ? {
      estimate: asNumber(read(bootstrap, 'estimate')),
      lower: asNumber(read(bootstrap, 'lower')),
      upper: asNumber(read(bootstrap, 'upper')),
      confidenceLevel: asNumber(read(bootstrap, 'confidenceLevel', 'confidence_level')),
      resamples: asNumber(read(bootstrap, 'resamples')),
      seed: asNumber(read(bootstrap, 'seed')),
    } : undefined,
  };
}

function normalizeNarrativeReport(value: unknown): ExperimentResults['narrativeReport'] {
  if (!isRecord(value)) return undefined;
  const headline = asString(read(value, 'headline'));
  const summary = asString(read(value, 'summary'));
  const interpretationBoundary = asString(read(value, 'interpretationBoundary', 'interpretation_boundary'));
  if (!headline || !summary || !interpretationBoundary) return undefined;
  return {
    schemaVersion: asString(read(value, 'schemaVersion', 'schema_version'), 'unknown'),
    headline,
    headlineZh: asOptionalString(read(value, 'headlineZh', 'headline_zh')),
    summary,
    summaryZh: asOptionalString(read(value, 'summaryZh', 'summary_zh')),
    interpretationBoundary,
    interpretationBoundaryZh: asOptionalString(read(value, 'interpretationBoundaryZh', 'interpretation_boundary_zh')),
    generatedBy: asString(read(value, 'generatedBy', 'generated_by'), 'UNREPORTED'),
  };
}

function normalizeTrace(value: unknown, index: number): TraceNode | null {
  if (!isRecord(value)) return null;
  const eventType = asString(read(value, 'eventType', 'event_type', 'kind', 'type'));
  const payload = isRecord(read(value, 'payload')) ? read(value, 'payload') as JsonRecord : {};
  if (!eventType) return null;
  return {
    id: asString(read(value, 'traceId', 'trace_id', 'id'), `trace-${index}`),
    step: asNumber(read(value, 'step')),
    time: asOptionalString(read(value, 'time', 'timestamp')),
    kind: eventType,
    title: eventType,
    summary: asOptionalString(read(value, 'summary', 'detail', 'description')),
    summaryZh: asOptionalString(read(value, 'summaryZh', 'summary_zh')),
    sourceId: asOptionalString(read(payload, 'sourceId', 'source_id')),
    agentId: asOptionalString(read(payload, 'agentId', 'agent_id')),
    orderId: asOptionalString(read(payload, 'orderId', 'order_id')),
    metricContribution: asNumber(read(payload, 'metricContribution', 'metric_contribution')),
    methodNote: asOptionalString(read(payload, 'methodNote', 'method_note')),
    scenario: asOptionalString(read(value, 'scenario')),
    seed: asNumber(read(value, 'seed')),
    parentId: asOptionalString(read(value, 'parentId', 'parent_id')),
    payload,
  };
}

function normalizeLimitations(value: unknown): { en: string[]; zh: string[] } {
  const en: string[] = [];
  const zh: string[] = [];
  unwrapItems(value).forEach((item) => {
    if (typeof item === 'string') {
      en.push(item);
      zh.push(item);
      return;
    }
    if (!isRecord(item)) return;
    const text = asOptionalString(read(item, 'text'));
    const textZh = asOptionalString(read(item, 'textZh', 'text_zh'));
    if (text) en.push(text);
    if (textZh) zh.push(textZh);
    else if (text) zh.push(text);
  });
  return { en, zh };
}

function normalizeManifest(value: unknown): { modelVersions: Record<string, string>; dataVersions: Record<string, string>; generatedAt?: string; validSeedCount?: number } {
  if (!isRecord(value)) return { modelVersions: {}, dataVersions: {} };
  const stringify = (input: unknown): string | undefined => {
    if (typeof input === 'string') return input;
    if (typeof input === 'number' || typeof input === 'boolean') return String(input);
    return undefined;
  };
  const modelVersions = Object.fromEntries([
    ['engineVersion', stringify(read(value, 'engineVersion'))],
    ['pythonVersion', stringify(read(value, 'pythonVersion'))],
    ['agentMode', stringify(read(value, 'agentMode'))],
    ['llmProvider', stringify(read(value, 'llmProvider'))],
    ['llmModel', stringify(read(value, 'llmModel'))],
    ['promptVersion', stringify(read(value, 'promptVersion'))],
    ['promptSchemaVersion', stringify(read(value, 'promptSchemaVersion'))],
    ['marketSchemaVersion', stringify(read(value, 'marketSchemaVersion'))],
    ['networkSchemaVersion', stringify(read(value, 'networkSchemaVersion'))],
    ['portfolioLedgerVersion', stringify(read(value, 'portfolioLedgerVersion'))],
  ].filter((entry): entry is [string, string] => entry[1] !== undefined));
  const dataVersions = Object.fromEntries([
    ['schemaVersion', stringify(read(value, 'schemaVersion'))],
    ['eventPackHash', stringify(read(value, 'eventPackHash'))],
    ['seedListHash', stringify(read(value, 'seedListHash'))],
    ['baselineScenarioHash', stringify(read(value, 'baselineScenarioHash'))],
    ['interventionScenarioHash', stringify(read(value, 'interventionScenarioHash'))],
    ['completeConfigurationHash', stringify(read(value, 'completeConfigurationHash'))],
  ].filter((entry): entry is [string, string] => entry[1] !== undefined));
  return {
    modelVersions,
    dataVersions,
    generatedAt: asOptionalString(read(value, 'generatedAt')),
    validSeedCount: asNumber(read(value, 'validPairedSeeds')),
  };
}

function normalizeCognitionDecision(value: unknown): CognitionDecisionSummary | null {
  if (!isRecord(value)) return null;
  const decision = isRecord(read(value, 'decision')) ? read(value, 'decision') as JsonRecord : value;
  const evidence = [
    ...asStringArray(read(value, 'evidenceIds', 'evidence_ids')),
    ...unwrapItems(read(decision, 'evidence')).flatMap((item) => {
    if (typeof item === 'string') return [item];
    if (!isRecord(item)) return [];
    const id = asOptionalString(read(item, 'evidence_id', 'evidenceId'));
    return id ? [id] : [];
    }),
  ];
  return {
    agentId: asOptionalString(read(value, 'agentId', 'agent_id')),
    representativeIndex: asNumber(read(value, 'representativeIndex', 'representative_index')),
    role: asOptionalString(read(value, 'role', 'agentRole', 'agent_role')),
    actionPreference: asOptionalString(read(decision, 'action_preference', 'actionPreference')),
    direction: asOptionalString(read(decision, 'direction')),
    confidence: asNumber(read(decision, 'confidence')),
    uncertainty: asNumber(read(decision, 'uncertainty')),
    evidenceIds: evidence,
    decisionSummary: asOptionalString(read(decision, 'decision_summary', 'decisionSummary')),
    fallbackUsed: asBoolean(read(value, 'fallbackUsed', 'fallback_used')),
    repairUsed: asBoolean(read(value, 'repairUsed', 'repair_used')),
    failureReason: asOptionalString(read(value, 'failureReason', 'failure_reason')),
    failureCodes: asStringArray(read(value, 'failureCodes', 'failure_codes')),
    transportAttempts: asNumber(read(value, 'transportAttempts', 'transport_attempts')),
    requestId: asOptionalString(read(value, 'requestId', 'request_id')),
    decisionRound: asNumber(read(value, 'decisionRound', 'decision_round')),
    observationAt: asOptionalString(read(value, 'observationAt', 'observation_at')),
    activeFromStep: asNumber(read(value, 'activeFromStep', 'active_from_step')),
    decisionIntervalSteps: asNumber(read(value, 'decisionIntervalSteps', 'decision_interval_steps')),
    evidenceCount: asNumber(read(value, 'evidenceCount', 'evidence_count')),
    socialPostCount: asNumber(read(value, 'socialPostCount', 'social_post_count')),
    memoryCount: asNumber(read(value, 'memoryCount', 'memory_count')),
    promptTokens: asNumber(read(value, 'promptTokens', 'prompt_tokens')),
    completionTokens: asNumber(read(value, 'completionTokens', 'completion_tokens')),
    cachedTokens: asNumber(read(value, 'cachedTokens', 'cached_tokens')),
    costUpperBoundUsd: asNumber(read(value, 'costUpperBoundUsd', 'cost_upper_bound_usd')),
  };
}

function normalizeCognitionCostBudget(value: unknown): CognitionRunMetadata['costBudget'] {
  if (!isRecord(value)) return undefined;
  // 多供应商上线前的历史结果没有 fxConversionApplied，且预算只可能来自智谱 CNY
  // 刊例价；因此缺省币种按 CNY 迁移，显式的新字段始终优先。
  const billingCurrency = asString(read(value, 'billingCurrency', 'billing_currency'), 'CNY');
  const explicitFxConversion = asBoolean(read(value, 'fxConversionApplied', 'fx_conversion_applied'));
  return {
    capUsd: asNumber(read(value, 'capUsd', 'cap_usd')) ?? 0,
    chargedUsdUpperBound: asNumber(read(value, 'chargedUsdUpperBound', 'charged_usd_upper_bound')) ?? 0,
    activeReservationUsd: asNumber(read(value, 'activeReservationUsd', 'active_reservation_usd')) ?? 0,
    remainingUsd: asNumber(read(value, 'remainingUsd', 'remaining_usd')) ?? 0,
    estimatedPromptTokens: asNumber(read(value, 'estimatedPromptTokens', 'estimated_prompt_tokens')) ?? 0,
    estimatedCompletionTokens: asNumber(read(value, 'estimatedCompletionTokens', 'estimated_completion_tokens')) ?? 0,
    actualPromptTokens: asNumber(read(value, 'actualPromptTokens', 'actual_prompt_tokens')) ?? 0,
    actualCompletionTokens: asNumber(read(value, 'actualCompletionTokens', 'actual_completion_tokens')) ?? 0,
    cachedPromptTokens: asNumber(read(value, 'cachedPromptTokens', 'cached_prompt_tokens')) ?? 0,
    reservedCalls: asNumber(read(value, 'reservedCalls', 'reserved_calls')) ?? 0,
    settledCalls: asNumber(read(value, 'settledCalls', 'settled_calls')) ?? 0,
    blockedCalls: asNumber(read(value, 'blockedCalls', 'blocked_calls')) ?? 0,
    unknownUsageCalls: asNumber(read(value, 'unknownUsageCalls', 'unknown_usage_calls')) ?? 0,
    provider: asOptionalString(read(value, 'provider')),
    billingCurrency,
    fxConversionApplied: explicitFxConversion ?? billingCurrency.toUpperCase() === 'CNY',
    pricingSnapshotVersion: asString(read(value, 'pricingSnapshotVersion', 'pricing_snapshot_version')),
    pricingVerifiedAt: asString(read(value, 'pricingVerifiedAt', 'pricing_verified_at')),
    priceSourceUrl: asString(read(value, 'priceSourceUrl', 'price_source_url')),
    fxSourceUrl: asString(read(value, 'fxSourceUrl', 'fx_source_url')),
    officialFxSnapshotCnyPerUsd: asNumber(read(value, 'officialFxSnapshotCnyPerUsd', 'official_fx_snapshot_cny_per_usd')) ?? 0,
    cnyPerUsdBudgetFloor: asNumber(read(value, 'cnyPerUsdBudgetFloor', 'cny_per_usd_budget_floor')) ?? 0,
    semantics: asString(read(value, 'semantics')),
  };
}

function normalizeCognition(value: unknown): CognitionRunMetadata | undefined {
  if (!isRecord(value)) return undefined;
  const decisions = unwrapItems(read(value, 'decisions'))
    .map(normalizeCognitionDecision)
    .filter((item): item is CognitionDecisionSummary => item !== null);
  return {
    requestedMode: asString(read(value, 'requestedMode', 'requested_mode'), 'RULE_ONLY'),
    resolvedMode: asString(read(value, 'resolvedMode', 'resolved_mode'), 'RULE_ONLY'),
    provider: asOptionalString(read(value, 'provider')),
    requestedModel: asOptionalString(read(value, 'requestedModel', 'requested_model')),
    resolvedModel: asOptionalString(read(value, 'resolvedModel', 'resolved_model')),
    calls: asNumber(read(value, 'calls')) ?? 0,
    totalTokens: asNumber(read(value, 'totalTokens', 'total_tokens')) ?? 0,
    promptTokens: asNumber(read(value, 'promptTokens', 'prompt_tokens')) ?? 0,
    completionTokens: asNumber(read(value, 'completionTokens', 'completion_tokens')) ?? 0,
    cachedTokens: asNumber(read(value, 'cachedTokens', 'cached_tokens')) ?? 0,
    fallbackCount: asNumber(read(value, 'fallbackCount', 'fallback_count')) ?? 0,
    fallbackReasons: asStringArray(read(value, 'fallbackReasons', 'fallback_reasons')),
    cacheHits: asNumber(read(value, 'cacheHits', 'cache_hits'))
      ?? decisions.filter((decision) => decision.requestId && unwrapItems(read(value, 'decisions')).some((item) => isRecord(item) && asString(read(item, 'requestId', 'request_id')) === decision.requestId && asBoolean(read(item, 'cacheHit', 'cache_hit')))).length,
    plannedCalls: asNumber(read(value, 'plannedCalls', 'planned_calls')) ?? 0,
    attemptedCalls: asNumber(read(value, 'attemptedCalls', 'attempted_calls')) ?? 0,
    decisionScheduleMode: asOptionalString(read(value, 'decisionScheduleMode', 'decision_schedule_mode')),
    promptVersion: asOptionalString(read(value, 'promptVersion', 'prompt_version')),
    promptSchemaVersion: asOptionalString(read(value, 'promptSchemaVersion', 'prompt_schema_version')),
    failureCode: asOptionalString(read(value, 'failureCode', 'failure_code')),
    costControl: asOptionalString(read(value, 'costControl', 'cost_control')),
    providerPriceEstimateAvailable: asBoolean(read(value, 'providerPriceEstimateAvailable', 'provider_price_estimate_available')),
    costBudget: normalizeCognitionCostBudget(read(value, 'costBudget', 'cost_budget')),
    decisions,
  };
}

function normalizeRobustness(value: unknown): RobustnessEvidence | undefined {
  if (!isRecord(value)) return undefined;
  return {
    sensitivityStatus: asString(read(value, 'sensitivityStatus', 'sensitivity_status'), 'NOT_EVALUATED'),
    ablationStatus: asString(read(value, 'ablationStatus', 'ablation_status'), 'NOT_EVALUATED'),
    negativeControlStatus: asString(read(value, 'negativeControlStatus', 'negative_control_status'), 'NOT_EVALUATED'),
    knockoutStatus: asString(read(value, 'knockoutStatus', 'knockout_status'), 'NOT_EVALUATED'),
    notes: asStringArray(read(value, 'notes')),
  };
}

function normalizeAnalysisControl(value: unknown): AnalysisDiagnostics['negativeControl'] {
  const record = isRecord(value) ? value : {};
  return {
    status: asString(read(record, 'status'), 'NOT_REPORTED'),
    controlType: asOptionalString(read(record, 'controlType', 'control_type')),
    passed: asBoolean(read(record, 'passed')),
    reason: asOptionalString(read(record, 'reason')),
    tolerance: asNumber(read(record, 'tolerance')),
    interpretation: asOptionalString(read(record, 'interpretation')),
    fullEffect: asNumber(read(record, 'fullEffect', 'full_effect')),
    knockoutEffect: asNumber(read(record, 'knockoutEffect', 'knockout_effect')),
    attenuationFraction: asNumber(read(record, 'attenuationFraction', 'attenuation_fraction')),
    minimumAttenuationFraction: asNumber(read(record, 'minimumAttenuationFraction', 'minimum_attenuation_fraction')),
    mechanismSupported: asBoolean(read(record, 'mechanismSupported', 'mechanism_supported')),
  };
}

function normalizeAnalysisDiagnostics(value: unknown): AnalysisDiagnostics | undefined {
  if (!isRecord(value)) return undefined;
  const localSensitivity = isRecord(read(value, 'localSensitivity', 'local_sensitivity'))
    ? read(value, 'localSensitivity', 'local_sensitivity') as JsonRecord
    : {};
  const multipleComparison = isRecord(read(value, 'multipleComparison', 'multiple_comparison'))
    ? read(value, 'multipleComparison', 'multiple_comparison') as JsonRecord
    : {};
  return {
    schemaVersion: asString(read(value, 'schemaVersion', 'schema_version'), 'unknown'),
    preregisteredPrimaryOutcome: asString(read(value, 'preregisteredPrimaryOutcome', 'preregistered_primary_outcome')),
    outcomeFamily: asStringArray(read(value, 'outcomeFamily', 'outcome_family')),
    negativeControl: normalizeAnalysisControl(read(value, 'negativeControl', 'negative_control')),
    parameterRestorationKnockout: normalizeAnalysisControl(read(value, 'parameterRestorationKnockout', 'parameter_restoration_knockout')),
    localSensitivity: {
      status: asString(read(localSensitivity, 'status'), 'NOT_REPORTED'),
      design: asOptionalString(read(localSensitivity, 'design')),
      interpretation: asOptionalString(read(localSensitivity, 'interpretation')),
      indices: unwrapItems(read(localSensitivity, 'indices')).flatMap((item) => {
        if (!isRecord(item)) return [];
        const parameter = asString(read(item, 'parameter'));
        if (!parameter) return [];
        return [{
          parameter,
          spearmanCorrelation: asNumber(read(item, 'spearmanCorrelation', 'spearman_correlation')),
          direction: asOptionalString(read(item, 'direction')),
          varianceImportanceProxy: asNumber(read(item, 'varianceImportanceProxy', 'variance_importance_proxy')),
          sampleSize: asNumber(read(item, 'sampleSize', 'sample_size')),
        }];
      }),
    },
    multipleComparison: {
      method: asString(read(multipleComparison, 'method'), 'NOT_REPORTED'),
      alpha: asNumber(read(multipleComparison, 'alpha')),
      items: unwrapItems(read(multipleComparison, 'items')).flatMap((item) => {
        if (!isRecord(item)) return [];
        const hypothesisId = asString(read(item, 'hypothesisId', 'hypothesis_id'));
        if (!hypothesisId) return [];
        return [{
          hypothesisId,
          rawPValue: asNumber(read(item, 'rawPValue', 'raw_p_value')),
          adjustedPValue: asNumber(read(item, 'adjustedPValue', 'adjusted_p_value')),
          alphaThreshold: asNumber(read(item, 'alphaThreshold', 'alpha_threshold')),
          rejected: asBoolean(read(item, 'rejected')) ?? false,
          rank: asNumber(read(item, 'rank')),
        }];
      }),
    },
    interpretationBoundary: asString(read(value, 'interpretationBoundary', 'interpretation_boundary')),
  };
}

export function normalizeResults(value: unknown): ExperimentResults {
  if (!isRecord(value)) throw new TypeError('Results response is not an object.');
  const limitations = normalizeLimitations(read(value, 'limitations'));
  const manifest = normalizeManifest(read(value, 'manifest'));
  const pairedSeries = normalizePairedSeries(read(value, 'pairedRuns', 'paired_runs'));
  const primaryMetricId = asOptionalString(read(value, 'primaryOutcome', 'primary_outcome'))
    ?? (pairedSeries.maxSpreadBps ? 'maxSpreadBps' : Object.keys(pairedSeries)[0]);
  const pairedSeeds = primaryMetricId ? pairedSeries[primaryMetricId] ?? [] : [];
  return {
    experimentId: asString(read(value, 'experimentId', 'experiment_id', 'id')),
    generatedAt: manifest.generatedAt,
    validSeedCount: manifest.validSeedCount ?? pairedSeeds.length,
    scenarioDiff: normalizeIntervention(read(value, 'scenarioDiff', 'scenario_diff')),
    metrics: normalizeMetricSummaries(read(value, 'metricSummaries', 'metric_summaries')),
    pairedSeeds,
    distribution: buildHistogram(pairedSeeds),
    marketPaths: normalizeMedianPaths(read(value, 'medianPaths', 'median_paths')),
    agentFlows: normalizeAgentFlows(read(value, 'agentFlows', 'agent_flows')),
    agentPnl: normalizeAgentPnl(read(value, 'agentPnl', 'agent_pnl')),
    traces: unwrapItems(read(value, 'traces', 'trace')).map(normalizeTrace).filter((item): item is TraceNode => item !== null),
    validationStatus: asOptionalString(read(value, 'validationStatus', 'validation_status')),
    primaryMetricId,
    pairedSeries,
    limitations: limitations.en,
    limitationsZh: limitations.zh,
    modelVersions: manifest.modelVersions,
    dataVersions: manifest.dataVersions,
    cognition: normalizeCognition(read(value, 'cognition')),
    robustness: normalizeRobustness(read(value, 'robustness', 'validationEvidence', 'validation_evidence')),
    stoppingRule: normalizeStoppingRule(read(value, 'stoppingRule', 'stopping_rule')),
    narrativeReport: normalizeNarrativeReport(read(value, 'narrativeReport', 'narrative_report')),
    analysisDiagnostics: normalizeAnalysisDiagnostics(read(value, 'analysisDiagnostics', 'analysis_diagnostics')),
  };
}

/**
 * 结果解释属于付费且面向人的输出，因此拒绝静默填充缺失字段。
 * 这样后端契约漂移时，界面会明确报错，而不会把不完整回答伪装成成功。
 */
function requireResultInterpretationString(record: JsonRecord, ...keys: string[]): string {
  const normalized = asOptionalString(read(record, ...keys))?.trim();
  if (!normalized) throw new TypeError(`Result interpretation is missing ${keys[0]}.`);
  return normalized;
}

function requireResultInterpretationCount(record: JsonRecord, ...keys: string[]): number {
  const normalized = asNumber(read(record, ...keys));
  if (normalized === undefined || !Number.isInteger(normalized) || normalized < 0) {
    throw new TypeError(`Result interpretation has an invalid ${keys[0]}.`);
  }
  return normalized;
}

function requireResultInterpretationNumber(record: JsonRecord, ...keys: string[]): number {
  const normalized = asNumber(read(record, ...keys));
  if (normalized === undefined || normalized < 0) {
    throw new TypeError(`Result interpretation has an invalid ${keys[0]}.`);
  }
  return normalized;
}

function requireResultInterpretationBoolean(record: JsonRecord, ...keys: string[]): boolean {
  const normalized = asBoolean(read(record, ...keys));
  if (normalized === undefined) {
    throw new TypeError(`Result interpretation has an invalid ${keys[0]}.`);
  }
  return normalized;
}

function requireResultInterpretationStringList(record: JsonRecord, ...keys: string[]): string[] {
  const raw = read(record, ...keys);
  if (!Array.isArray(raw)
    || raw.some((item) => typeof item !== 'string' || item.trim().length === 0)) {
    throw new TypeError(`Result interpretation has an invalid ${keys[0]}.`);
  }
  return raw.map((item) => (item as string).trim());
}

function requireResultInterpretationDate(record: JsonRecord, ...keys: string[]): string {
  const normalized = requireResultInterpretationString(record, ...keys);
  if (Number.isNaN(Date.parse(normalized))) {
    throw new TypeError(`Result interpretation has an invalid ${keys[0]}.`);
  }
  return normalized;
}

function requireResultInterpretationLanguage(
  record: JsonRecord,
  ...keys: string[]
): ResultInterpretationLanguage {
  const rawLanguage = read(record, ...keys);
  if (rawLanguage !== 'en' && rawLanguage !== 'zh-CN') {
    throw new TypeError(`Result interpretation has an invalid ${keys[0]}.`);
  }
  return rawLanguage;
}

function requireResultInterpretationSchema(record: JsonRecord): '1.0.0' {
  const schemaVersion = requireResultInterpretationString(
    record,
    'schemaVersion',
    'schema_version',
  );
  if (schemaVersion !== '1.0.0') {
    throw new TypeError('Result interpretation response has an unsupported schemaVersion.');
  }
  return schemaVersion;
}

export function normalizeResultInterpretationAssistantMessage(
  value: unknown,
): ResultInterpretationAssistantMessage {
  if (!isRecord(value)) throw new TypeError('Result interpretation message is not an object.');
  if (read(value, 'role') !== 'assistant') {
    throw new TypeError('Result interpretation message role must be assistant.');
  }
  const language = requireResultInterpretationLanguage(value, 'language');
  const rawAnalysisSummary = read(value, 'analysisSummary', 'analysis_summary');
  if (rawAnalysisSummary !== undefined && rawAnalysisSummary !== null
    && (typeof rawAnalysisSummary !== 'string' || rawAnalysisSummary.trim().length === 0)) {
    throw new TypeError('Result interpretation message has an invalid analysisSummary.');
  }
  const rawToolActivity = read(value, 'toolActivity', 'tool_activity');
  if (!Array.isArray(rawToolActivity)) {
    throw new TypeError('Result interpretation message has an invalid toolActivity.');
  }
  const toolActivity: ResultInterpretationToolActivity[] = rawToolActivity.map((item) => {
    if (!isRecord(item)) throw new TypeError('Result interpretation tool activity is not an object.');
    return {
      tool: requireResultInterpretationString(item, 'tool'),
      label: requireResultInterpretationString(item, 'label'),
      itemCount: requireResultInterpretationCount(item, 'itemCount', 'item_count'),
      truncated: requireResultInterpretationBoolean(item, 'truncated'),
      evidenceId: requireResultInterpretationString(item, 'evidenceId', 'evidence_id'),
    };
  });
  return {
    id: requireResultInterpretationString(value, 'id'),
    role: 'assistant',
    language,
    answer: requireResultInterpretationString(value, 'answer'),
    analysisSummary: typeof rawAnalysisSummary === 'string'
      ? rawAnalysisSummary.trim()
      : undefined,
    groundingReferences: requireResultInterpretationStringList(
      value,
      'groundingReferences',
      'grounding_references',
    ),
    followUpSuggestions: requireResultInterpretationStringList(
      value,
      'followUpSuggestions',
      'follow_up_suggestions',
    ),
    toolActivity,
    provider: requireResultInterpretationString(value, 'provider'),
    model: requireResultInterpretationString(value, 'model'),
    promptTokens: requireResultInterpretationCount(value, 'promptTokens', 'prompt_tokens'),
    completionTokens: requireResultInterpretationCount(
      value,
      'completionTokens',
      'completion_tokens',
    ),
    cachedTokens: requireResultInterpretationCount(value, 'cachedTokens', 'cached_tokens'),
    totalTokens: requireResultInterpretationCount(value, 'totalTokens', 'total_tokens'),
    modelCalls: requireResultInterpretationCount(value, 'modelCalls', 'model_calls'),
    cacheHit: requireResultInterpretationBoolean(value, 'cacheHit', 'cache_hit'),
    repairUsed: requireResultInterpretationBoolean(value, 'repairUsed', 'repair_used'),
    plannerUsed: requireResultInterpretationBoolean(value, 'plannerUsed', 'planner_used'),
    promptVersion: requireResultInterpretationString(value, 'promptVersion', 'prompt_version'),
    latencyMs: requireResultInterpretationNumber(value, 'latencyMs', 'latency_ms'),
    createdAt: requireResultInterpretationDate(value, 'createdAt', 'created_at'),
  };
}

export function normalizeResultInterpretationChatMessage(
  value: unknown,
): ResultInterpretationChatMessage {
  if (!isRecord(value)) throw new TypeError('Result interpretation message is not an object.');
  if (read(value, 'role') === 'assistant') {
    return normalizeResultInterpretationAssistantMessage(value);
  }
  if (read(value, 'role') !== 'user') {
    throw new TypeError('Result interpretation message has an invalid role.');
  }
  return {
    id: requireResultInterpretationString(value, 'id'),
    role: 'user',
    language: requireResultInterpretationLanguage(value, 'language'),
    content: requireResultInterpretationString(value, 'content'),
    createdAt: requireResultInterpretationDate(value, 'createdAt', 'created_at'),
  };
}

export function normalizeResultInterpretationChatResponse(
  value: unknown,
): ResultInterpretationChatResponse {
  if (!isRecord(value)) throw new TypeError('Result interpretation response is not an object.');
  return {
    schemaVersion: requireResultInterpretationSchema(value),
    conversationId: requireResultInterpretationString(value, 'conversationId', 'conversation_id'),
    clientRequestId: requireResultInterpretationString(value, 'clientRequestId', 'client_request_id'),
    experimentId: requireResultInterpretationString(value, 'experimentId', 'experiment_id'),
    resultHash: requireResultInterpretationString(value, 'resultHash', 'result_hash'),
    historyPersisted: requireResultInterpretationBoolean(
      value,
      'historyPersisted',
      'history_persisted',
    ),
    message: normalizeResultInterpretationAssistantMessage(read(value, 'message')),
  };
}

function normalizeResultInterpretationConversationSummary(
  value: unknown,
): ResultInterpretationConversationSummary {
  if (!isRecord(value)) {
    throw new TypeError('Result interpretation conversation summary is not an object.');
  }
  return {
    conversationId: requireResultInterpretationString(value, 'conversationId', 'conversation_id'),
    experimentId: requireResultInterpretationString(value, 'experimentId', 'experiment_id'),
    language: requireResultInterpretationLanguage(value, 'language'),
    exchangeCount: requireResultInterpretationCount(value, 'exchangeCount', 'exchange_count'),
    lastUserMessage: requireResultInterpretationString(
      value,
      'lastUserMessage',
      'last_user_message',
    ),
    createdAt: requireResultInterpretationDate(value, 'createdAt', 'created_at'),
    updatedAt: requireResultInterpretationDate(value, 'updatedAt', 'updated_at'),
  };
}

export function normalizeResultInterpretationConversationList(
  value: unknown,
): ResultInterpretationConversationList {
  if (!isRecord(value)) {
    throw new TypeError('Result interpretation conversation list is not an object.');
  }
  const rawItems = read(value, 'items');
  if (!Array.isArray(rawItems)) {
    throw new TypeError('Result interpretation conversation list has invalid items.');
  }
  return {
    schemaVersion: requireResultInterpretationSchema(value),
    items: rawItems.map(normalizeResultInterpretationConversationSummary),
  };
}

export function normalizeResultInterpretationConversation(
  value: unknown,
): ResultInterpretationConversation {
  if (!isRecord(value)) {
    throw new TypeError('Result interpretation conversation is not an object.');
  }
  const rawMessages = read(value, 'messages');
  if (!Array.isArray(rawMessages) || rawMessages.length === 0 || rawMessages.length % 2 !== 0) {
    throw new TypeError('Result interpretation conversation has invalid messages.');
  }
  const messages = rawMessages.map(normalizeResultInterpretationChatMessage);
  const messageIds = new Set<string>();
  messages.forEach((message, index) => {
    const expectedRole = index % 2 === 0 ? 'user' : 'assistant';
    if (message.role !== expectedRole || messageIds.has(message.id)) {
      throw new TypeError('Result interpretation conversation has invalid message ordering.');
    }
    messageIds.add(message.id);
  });
  return {
    schemaVersion: requireResultInterpretationSchema(value),
    conversationId: requireResultInterpretationString(value, 'conversationId', 'conversation_id'),
    experimentId: requireResultInterpretationString(value, 'experimentId', 'experiment_id'),
    language: requireResultInterpretationLanguage(value, 'language'),
    createdAt: requireResultInterpretationDate(value, 'createdAt', 'created_at'),
    updatedAt: requireResultInterpretationDate(value, 'updatedAt', 'updated_at'),
    messages,
  };
}

export function normalizeResultInterpretationConversationDeleteResult(
  value: unknown,
): ResultInterpretationConversationDeleteResult {
  if (!isRecord(value)) {
    throw new TypeError('Result interpretation conversation deletion is not an object.');
  }
  if (read(value, 'deleted') !== true) {
    throw new TypeError('Result interpretation conversation deletion was not confirmed.');
  }
  return {
    schemaVersion: requireResultInterpretationSchema(value),
    deleted: true,
    conversationId: requireResultInterpretationString(value, 'conversationId', 'conversation_id'),
  };
}

const RESULT_INTERPRETATION_STREAM_STAGES: readonly ResultInterpretationStreamStage[] = [
  'PREPARING',
  'PLANNING',
  'READING_RESULTS',
  'GENERATING',
  'REASONING',
  'VALIDATING',
  'REPAIRING',
  'COMPLETED',
];

function normalizeNonNegativeInteger(value: unknown, field: string): number | undefined {
  if (value === undefined || value === null) return undefined;
  const normalized = asNumber(value);
  if (normalized === undefined || !Number.isInteger(normalized) || normalized < 0) {
    throw new TypeError(`Result interpretation stream has an invalid ${field}.`);
  }
  return normalized;
}

/**
 * 流式阶段只接受公开契约中的固定枚举，并主动丢弃服务端自由文本 message。
 * 这避免把供应商原始输出或内部执行细节误当成安全的进度说明展示给用户。
 */
export function normalizeResultInterpretationStreamProgress(
  value: unknown,
): ResultInterpretationStreamProgress {
  if (!isRecord(value)) throw new TypeError('Result interpretation stream progress is not an object.');
  const schemaVersion = asOptionalString(read(value, 'schemaVersion', 'schema_version'));
  if (schemaVersion !== '1.0.0') {
    throw new TypeError('Result interpretation stream has an invalid schemaVersion.');
  }
  const rawStage = asOptionalString(read(value, 'stage'));
  if (!rawStage || !RESULT_INTERPRETATION_STREAM_STAGES.includes(
    rawStage as ResultInterpretationStreamStage,
  )) {
    throw new TypeError('Result interpretation stream has an invalid stage.');
  }
  const elapsedMs = asNumber(read(value, 'elapsedMs', 'elapsed_ms'));
  if (elapsedMs === undefined || elapsedMs < 0) {
    throw new TypeError('Result interpretation stream has an invalid elapsedMs.');
  }

  return {
    schemaVersion: '1.0.0',
    stage: rawStage as ResultInterpretationStreamStage,
    elapsedMs,
    chunkCount: normalizeNonNegativeInteger(
      read(value, 'chunkCount', 'chunk_count'),
      'chunkCount',
    ),
    answerChunkCount: normalizeNonNegativeInteger(
      read(value, 'answerChunkCount', 'answer_chunk_count'),
      'answerChunkCount',
    ),
    reasoningChunkCount: normalizeNonNegativeInteger(
      read(value, 'reasoningChunkCount', 'reasoning_chunk_count'),
      'reasoningChunkCount',
    ),
  };
}

export function normalizeResultInterpretationStreamError(
  value: unknown,
): ResultInterpretationStreamErrorPayload {
  if (!isRecord(value)) throw new TypeError('Result interpretation stream error is not an object.');
  const code = asOptionalString(read(value, 'code'))?.trim();
  const message = asOptionalString(read(value, 'message'))?.trim();
  const retryable = asBoolean(read(value, 'retryable'));
  const httpStatus = normalizeNonNegativeInteger(
    read(value, 'httpStatus', 'http_status'),
    'httpStatus',
  );
  const uncertainBillableAttempts = normalizeNonNegativeInteger(
    read(value, 'uncertainBillableAttempts', 'uncertain_billable_attempts'),
    'uncertainBillableAttempts',
  ) ?? 0;
  if (!code || !message || retryable === undefined || httpStatus === undefined
  ) {
    throw new TypeError('Result interpretation stream error is incomplete.');
  }
  const traceId = asOptionalString(read(value, 'traceId', 'trace_id'))?.trim();
  return {
    code,
    message,
    retryable,
    httpStatus,
    uncertainBillableAttempts,
    traceId: traceId || undefined,
  };
}

function normalizeValidationItem(value: unknown, passed: boolean, severity: ValidationCheck['severity']): ValidationCheck | null {
  if (!isRecord(value)) return null;
  const code = asString(read(value, 'code'));
  const message = asString(read(value, 'message'));
  if (!code && !message) return null;
  return { id: code || message, label: code || message, passed, detail: message || undefined, severity };
}

function normalizeExplicitCheck(value: unknown): ValidationCheck | null {
  if (!isRecord(value)) return null;
  const code = asString(read(value, 'code'));
  const status = asString(read(value, 'status'), 'FAIL').toUpperCase();
  const message = asString(read(value, 'message'));
  if (!code) return null;
  return {
    id: code,
    label: code,
    passed: status !== 'FAIL',
    detail: message || undefined,
    severity: status === 'FAIL' ? 'error' : status === 'WARN' ? 'warning' : 'info',
  };
}

export function normalizeValidation(value: unknown): ScenarioValidation {
  if (!isRecord(value)) throw new TypeError('Scenario validation response is not an object.');
  const errors = unwrapItems(read(value, 'errors'))
    .map((item) => normalizeValidationItem(item, false, 'error'))
    .filter((item): item is ValidationCheck => item !== null);
  const warnings = unwrapItems(read(value, 'warnings'))
    .map((item) => normalizeValidationItem(item, true, 'warning'))
    .filter((item): item is ValidationCheck => item !== null);
  const explicitChecks = unwrapItems(read(value, 'checks'))
    .map(normalizeExplicitCheck)
    .filter((item): item is ValidationCheck => item !== null);
  const checks = explicitChecks.length > 0 ? explicitChecks : [...errors, ...warnings];
  return {
    valid: asBoolean(read(value, 'valid')) ?? errors.length === 0,
    checks,
    estimatedRuntimeSeconds: asNumber(read(value, 'estimatedRuntimeSeconds', 'estimated_runtime_seconds')),
    estimatedLlmCalls: asNumber(read(value, 'estimatedLlmCalls', 'estimated_llm_calls')),
    estimatedRuns: asNumber(read(value, 'estimatedRuns', 'estimated_runs')),
    llmCostCapUsd: asNumber(read(value, 'llmCostCapUsd', 'llm_cost_cap_usd')),
    llmPricingStatus: asOptionalString(read(value, 'llmPricingStatus', 'llm_pricing_status')),
    llmMinimumCallReservationUsd: asNumber(read(value, 'llmMinimumCallReservationUsd', 'llm_minimum_call_reservation_usd')),
    interpretationBoundary: asOptionalString(read(value, 'interpretationBoundary', 'interpretation_boundary')),
    warnings: warnings.map((item) => item.detail ?? item.label),
  };
}

export function normalizeLlmCatalog(value: unknown): LlmCatalog {
  if (!isRecord(value)) throw new TypeError('Model catalog response is not an object.');

  const normalizeModels = (modelValue: unknown, fallbackProvider: LlmProviderId): LlmModelDescriptor[] => (
    unwrapItems(modelValue).flatMap((item) => {
    if (!isRecord(item)) return [];
    const id = asString(read(item, 'id', 'modelId', 'model_id'));
    const name = asString(read(item, 'name', 'displayName', 'display_name'));
    const contextTokens = asNumber(read(item, 'contextTokens', 'context_tokens'));
    const maxOutputTokens = asNumber(read(item, 'maxOutputTokens', 'max_output_tokens'));
    if (!id || !name || contextTokens === undefined) return [];
    return [{
      provider: asLlmProviderId(read(item, 'provider')) ?? fallbackProvider,
      id,
      name,
      contextTokens,
      maxOutputTokens,
      officialMaxOutputTokens: asNumber(read(item, 'officialMaxOutputTokens', 'official_max_output_tokens')),
      applicationMaxOutputTokens: asNumber(read(
        item,
        'applicationMaxOutputTokens',
        'application_max_output_tokens',
      )),
      supportsThinking: asBoolean(read(item, 'supportsThinking', 'supports_thinking')) ?? false,
      thinkingAlwaysOn: asBoolean(read(item, 'thinkingAlwaysOn', 'thinking_always_on')) ?? false,
      supportsFunctionCalling: asBoolean(read(item, 'supportsFunctionCalling', 'supports_function_calling')) ?? false,
      recommended: asBoolean(read(item, 'recommended')) ?? false,
      qualityTier: ((): LlmModelDescriptor['qualityTier'] => {
        const qualityTier = asString(read(item, 'qualityTier', 'quality_tier')).toUpperCase();
        return qualityTier === 'ECONOMY' || qualityTier === 'PREMIUM' ? qualityTier : 'BALANCED';
      })(),
      freeTier: asBoolean(read(item, 'freeTier', 'free_tier')) ?? false,
      legacy: asBoolean(read(item, 'legacy')) ?? false,
      deprecationNote: asOptionalString(read(item, 'deprecationNote', 'deprecation_note')),
      capabilityNote: asOptionalString(read(item, 'capabilityNote', 'capability_note')),
      officialModelUrl: asOptionalString(read(item, 'officialModelUrl', 'official_model_url')),
      catalogVerifiedAt: asOptionalString(read(item, 'catalogVerifiedAt', 'catalog_verified_at')),
      pricingStatus: asString(read(item, 'pricingStatus', 'pricing_status'), 'UNAVAILABLE_FAIL_CLOSED') === 'VERIFIED_UPPER_BOUND'
        ? 'VERIFIED_UPPER_BOUND' as const
        : 'UNAVAILABLE_FAIL_CLOSED' as const,
      billingCurrency: asOptionalString(read(item, 'billingCurrency', 'billing_currency')),
      inputRateUpperPerMillion: asNumber(read(
        item,
        'inputRateUpperPerMillion',
        'input_rate_upper_per_million',
        'inputRateUpperCnyPerMillion',
        'input_rate_upper_cny_per_million',
      )),
      outputRateUpperPerMillion: asNumber(read(
        item,
        'outputRateUpperPerMillion',
        'output_rate_upper_per_million',
        'outputRateUpperCnyPerMillion',
        'output_rate_upper_cny_per_million',
      )),
      budgetInputRateUpperPerMillion: asNumber(read(
        item,
        'budgetInputRateUpperPerMillion',
        'budget_input_rate_upper_per_million',
      )),
      budgetOutputRateUpperPerMillion: asNumber(read(
        item,
        'budgetOutputRateUpperPerMillion',
        'budget_output_rate_upper_per_million',
      )),
      cachedInputRatePerMillion: asNumber(read(
        item,
        'cachedInputRatePerMillion',
        'cached_input_rate_per_million',
      )),
      pricingVerifiedAt: asOptionalString(read(item, 'pricingVerifiedAt', 'pricing_verified_at')),
      pricingNote: asOptionalString(read(item, 'pricingNote', 'pricing_note')),
    }];
    })
  );

  const providers = unwrapItems(read(value, 'providers')).flatMap((item): LlmProviderDescriptor[] => {
    if (!isRecord(item)) return [];
    const id = asLlmProviderId(read(item, 'id', 'provider'));
    const name = asString(read(item, 'name', 'providerName', 'provider_name'));
    if (!id || !name) return [];
    return [{
      id,
      name,
      baseUrl: asString(read(item, 'baseUrl', 'base_url')),
      documentationUrl: asString(read(item, 'documentationUrl', 'documentation_url')),
      pricingUrl: asString(read(item, 'pricingUrl', 'pricing_url')),
      region: asString(read(item, 'region')),
      structuredOutputMode: asString(
        read(item, 'structuredOutputMode', 'structured_output_mode'),
        'JSON_OBJECT',
      ),
      structuredOutputNote: asString(read(item, 'structuredOutputNote', 'structured_output_note')),
      integrationValidationStatus: asString(
        read(item, 'integrationValidationStatus', 'integration_validation_status'),
      ) === 'REAL_PROJECT_KEY_VERIFIED'
        ? 'REAL_PROJECT_KEY_VERIFIED' as const
        : 'CONTRACT_TESTED_COMMUNITY_PREVIEW' as const,
      feedbackIssueUrl: asString(
        read(item, 'feedbackIssueUrl', 'feedback_issue_url'),
        'https://github.com/Mike-Zhuang/EventShock/issues/new?template=llm-provider-feedback.yml',
      ),
      models: normalizeModels(read(item, 'models'), id),
    }];
  });

  if (providers.length === 0) {
    const legacyProvider = asLlmProviderId(read(value, 'provider')) ?? 'zhipu';
    providers.push({
      id: legacyProvider,
      name: asString(read(value, 'providerName', 'provider_name'), 'Zhipu AI'),
      baseUrl: asString(read(value, 'baseUrl', 'base_url')),
      documentationUrl: asString(read(value, 'documentationUrl', 'documentation_url')),
      pricingUrl: asString(read(value, 'pricingUrl', 'pricing_url')),
      region: asString(read(value, 'region'), 'CN'),
      structuredOutputMode: asString(
        read(value, 'structuredOutputMode', 'structured_output_mode'),
        'JSON_OBJECT',
      ),
      structuredOutputNote: asString(read(value, 'structuredOutputNote', 'structured_output_note')),
      integrationValidationStatus: asString(
        read(value, 'integrationValidationStatus', 'integration_validation_status'),
      ) === 'REAL_PROJECT_KEY_VERIFIED'
        ? 'REAL_PROJECT_KEY_VERIFIED'
        : 'CONTRACT_TESTED_COMMUNITY_PREVIEW',
      feedbackIssueUrl: asString(
        read(value, 'feedbackIssueUrl', 'feedback_issue_url'),
        'https://github.com/Mike-Zhuang/EventShock/issues/new?template=llm-provider-feedback.yml',
      ),
      models: normalizeModels(read(value, 'models'), legacyProvider),
    });
  }

  const requestedDefault = asLlmProviderId(read(value, 'defaultProvider', 'default_provider'));
  const defaultProvider = providers.some((provider) => provider.id === requestedDefault)
    ? requestedDefault as LlmProviderId
    : providers.find((provider) => provider.id === 'zhipu')?.id ?? providers[0].id;
  const defaultDescriptor = providers.find((provider) => provider.id === defaultProvider) ?? providers[0];
  return {
    defaultProvider,
    providers,
    provider: defaultProvider,
    providerName: defaultDescriptor.name,
    baseUrl: defaultDescriptor.baseUrl,
    documentationUrl: defaultDescriptor.documentationUrl,
    pricingUrl: defaultDescriptor.pricingUrl,
    pricingSnapshotVersion: asString(read(value, 'pricingSnapshotVersion', 'pricing_snapshot_version')),
    fxSourceUrl: asString(read(value, 'fxSourceUrl', 'fx_source_url')),
    officialFxSnapshotCnyPerUsd: asNumber(read(value, 'officialFxSnapshotCnyPerUsd', 'official_fx_snapshot_cny_per_usd')) ?? 0,
    cnyPerUsdBudgetFloor: asNumber(read(value, 'cnyPerUsdBudgetFloor', 'cny_per_usd_budget_floor')) ?? 0,
    costCapSemantics: asString(read(value, 'costCapSemantics', 'cost_cap_semantics')),
    models: defaultDescriptor.models,
  };
}

export function normalizePromptRegistry(value: unknown): PromptRegistryItem[] {
  return unwrapItems(value).flatMap((item) => {
    if (!isRecord(item)) return [];
    const name = asString(read(item, 'name'));
    const version = asString(read(item, 'version'));
    const schemaVersion = asString(read(item, 'schema_version', 'schemaVersion'));
    const promptHash = asString(read(item, 'prompt_hash', 'promptHash'));
    if (!name || !version || !schemaVersion || !promptHash) return [];
    return [{ name, version, schemaVersion, promptHash }];
  });
}

export function normalizeLlmConfig(value: unknown): LlmConfigView {
  if (!isRecord(value)) throw new TypeError('Model configuration response is not an object.');
  return {
    configured: asBoolean(read(value, 'configured')) ?? false,
    provider: asLlmProviderId(read(value, 'provider')),
    model: asOptionalString(read(value, 'model')),
    thinkingEnabled: asBoolean(read(value, 'thinkingEnabled', 'thinking_enabled')),
    maxTokens: asNumber(read(value, 'maxTokens', 'max_tokens')),
    credentialHint: asOptionalString(read(value, 'credentialHint', 'credential_hint')),
    expiresAt: asOptionalString(read(value, 'expiresAt', 'expires_at')),
  };
}

export function normalizeLlmConnectionTest(value: unknown): LlmConnectionTest {
  if (!isRecord(value)) throw new TypeError('Model test response is not an object.');
  return {
    ok: asBoolean(read(value, 'ok')) ?? false,
    provider: asString(read(value, 'provider'), 'zhipu'),
    model: asString(read(value, 'model')),
    structuredOutputValidated: asBoolean(read(value, 'structuredOutputValidated', 'structured_output_validated')) ?? false,
    responseSchemaVersion: asOptionalString(read(value, 'responseSchemaVersion', 'response_schema_version')),
    latencyMs: asNumber(read(value, 'latencyMs', 'latency_ms')),
    failureCode: asOptionalString(read(value, 'failureCode', 'failure_code')),
    message: asString(read(value, 'message')),
  };
}

function normalizeTelemetry(value: unknown): CognitionTelemetry {
  const record = isRecord(value) ? value : {};
  return {
    calls: asNumber(read(record, 'calls')) ?? 0,
    cacheHits: asNumber(read(record, 'cache_hits', 'cacheHits')) ?? 0,
    fallbacks: asNumber(read(record, 'fallbacks')) ?? 0,
    invalidOutputs: asNumber(read(record, 'invalid_outputs', 'invalidOutputs')) ?? 0,
    promptTokens: asNumber(read(record, 'prompt_tokens', 'promptTokens')) ?? 0,
    completionTokens: asNumber(read(record, 'completion_tokens', 'completionTokens')) ?? 0,
    cachedTokens: asNumber(read(record, 'cached_tokens', 'cachedTokens')) ?? 0,
    totalTokens: asNumber(read(record, 'total_tokens', 'totalTokens')) ?? 0,
    totalLatencyMs: asNumber(read(record, 'total_latency_ms', 'totalLatencyMs')) ?? 0,
    averageLatencyMs: asNumber(read(record, 'average_latency_ms', 'averageLatencyMs')) ?? 0,
    cacheHitRate: asNumber(read(record, 'cache_hit_rate', 'cacheHitRate')) ?? 0,
    fallbackRate: asNumber(read(record, 'fallback_rate', 'fallbackRate')) ?? 0,
    invalidOutputRate: asNumber(read(record, 'invalid_output_rate', 'invalidOutputRate')) ?? 0,
  };
}

export function normalizeCognitionTelemetry(value: unknown): CognitionTelemetry {
  if (!isRecord(value)) throw new TypeError('Cognition telemetry response is not an object.');
  return normalizeTelemetry(value);
}

export function normalizeSystemMetrics(value: unknown): SystemMetrics {
  if (!isRecord(value)) throw new TypeError('System metrics response is not an object.');
  const runtime = isRecord(read(value, 'runtime')) ? read(value, 'runtime') as JsonRecord : {};
  const latencyMs = isRecord(read(runtime, 'latencyMs', 'latency_ms'))
    ? read(runtime, 'latencyMs', 'latency_ms') as JsonRecord
    : {};
  const experiments = isRecord(read(value, 'experiments')) ? read(value, 'experiments') as JsonRecord : {};
  const storage = isRecord(read(value, 'storage')) ? read(value, 'storage') as JsonRecord : {};
  const sloTargets = isRecord(read(value, 'sloTargets', 'slo_targets'))
    ? read(value, 'sloTargets', 'slo_targets') as JsonRecord
    : {};
  return {
    service: asString(read(value, 'service')),
    version: asString(read(value, 'version')),
    runtime: {
      uptimeSeconds: asNumber(read(runtime, 'uptimeSeconds', 'uptime_seconds')) ?? 0,
      requestCount: asNumber(read(runtime, 'requestCount', 'request_count')) ?? 0,
      clientErrorCount: asNumber(read(runtime, 'clientErrorCount', 'client_error_count')) ?? 0,
      serverErrorCount: asNumber(read(runtime, 'serverErrorCount', 'server_error_count')) ?? 0,
      serverErrorRate: asNumber(read(runtime, 'serverErrorRate', 'server_error_rate')) ?? 0,
      latencyWindowSize: asNumber(read(runtime, 'latencyWindowSize', 'latency_window_size')) ?? 0,
      latencyMs: {
        p50: asNumber(read(latencyMs, 'p50')) ?? 0,
        p95: asNumber(read(latencyMs, 'p95')) ?? 0,
        maximum: asNumber(read(latencyMs, 'maximum')) ?? 0,
        mean: asNumber(read(latencyMs, 'mean')) ?? 0,
      },
      privacyBoundary: asString(read(runtime, 'privacyBoundary', 'privacy_boundary')),
    },
    experiments: {
      workerConcurrency: asNumber(read(experiments, 'workerConcurrency', 'worker_concurrency')) ?? 0,
      activeOrQueued: asNumber(read(experiments, 'activeOrQueued', 'active_or_queued')) ?? 0,
      maximumActiveOrQueued: asNumber(read(experiments, 'maximumActiveOrQueued', 'maximum_active_or_queued')) ?? 0,
      maximumExperimentsPerSession: asNumber(read(experiments, 'maximumExperimentsPerSession', 'maximum_experiments_per_session')) ?? 0,
    },
    storage: {
      database: asString(read(storage, 'database'), 'unknown'),
      retainedExperiments: asNumber(read(storage, 'retainedExperiments', 'retained_experiments')) ?? 0,
      maximumRetainedExperiments: asNumber(read(storage, 'maximumRetainedExperiments', 'maximum_retained_experiments')) ?? 0,
    },
    cognition: normalizeTelemetry(read(value, 'cognition')),
    sloTargets: {
      availability: asNumber(read(sloTargets, 'availability')) ?? 0,
      apiP95Milliseconds: asNumber(read(sloTargets, 'apiP95Milliseconds', 'api_p95_milliseconds')) ?? 0,
      status: asString(read(sloTargets, 'status'), 'TARGETS_NOT_PRODUCTION_EVIDENCE'),
    },
  };
}

export function normalizeCognitionEvalSummary(value: unknown): CognitionEvalSummary {
  if (!isRecord(value)) throw new TypeError('Cognition evaluation response is not an object.');
  return {
    telemetry: normalizeTelemetry(read(value, 'telemetry')),
    evaluatedCases: asNumber(read(value, 'evaluated_cases', 'evaluatedCases')) ?? 0,
    passedCases: asNumber(read(value, 'passed_cases', 'passedCases')) ?? 0,
    passRate: asNumber(read(value, 'pass_rate', 'passRate')) ?? 0,
  };
}

export function normalizeCognitionEvaluationRun(value: unknown): CognitionEvaluationRun {
  if (!isRecord(value)) throw new TypeError('Cognition evaluation response is not an object.');
  const modeValue = asString(read(value, 'mode'));
  const mode = modeValue === 'LIVE_CONFIGURED_MODEL' ? 'LIVE_CONFIGURED_MODEL' : 'CODE_GRADER_SELF_TEST';
  const result = isRecord(read(value, 'result')) ? read(value, 'result') as JsonRecord : {};
  return {
    mode,
    evaluatedSystem: asString(read(value, 'evaluatedSystem', 'evaluated_system')),
    suiteVersion: asString(read(value, 'suiteVersion', 'suite_version')),
    result: {
      totalCases: asNumber(read(result, 'total_cases', 'totalCases')) ?? 0,
      passedCases: asNumber(read(result, 'passed_cases', 'passedCases')) ?? 0,
      passRate: asNumber(read(result, 'pass_rate', 'passRate')) ?? 0,
      results: unwrapItems(read(result, 'results')).flatMap((item) => {
        if (!isRecord(item)) return [];
        const caseId = asString(read(item, 'case_id', 'caseId'));
        if (!caseId) return [];
        return [{
          caseId,
          passed: asBoolean(read(item, 'passed')) ?? false,
          score: asNumber(read(item, 'score')) ?? 0,
          checks: unwrapItems(read(item, 'checks')).flatMap((check) => {
            if (!isRecord(check)) return [];
            const name = asString(read(check, 'name'));
            const detail = asString(read(check, 'detail'));
            if (!name || !detail) return [];
            return [{ name, passed: asBoolean(read(check, 'passed')) ?? false, detail }];
          }),
        }];
      }),
    },
    modelRuns: unwrapItems(read(value, 'modelRuns', 'model_runs')).flatMap((item) => {
      if (!isRecord(item)) return [];
      const caseId = asString(read(item, 'caseId', 'case_id'));
      const model = asString(read(item, 'model'));
      if (!caseId || !model) return [];
      return [{
        caseId,
        model,
        requestId: asOptionalString(read(item, 'requestId', 'request_id')),
        cacheHit: asBoolean(read(item, 'cacheHit', 'cache_hit')) ?? false,
        fallbackUsed: asBoolean(read(item, 'fallbackUsed', 'fallback_used')) ?? false,
        repairUsed: asBoolean(read(item, 'repairUsed', 'repair_used')) ?? false,
        latencyMs: asNumber(read(item, 'latencyMs', 'latency_ms')),
        totalTokens: asNumber(read(item, 'totalTokens', 'total_tokens')),
      }];
    }),
    interpretationBoundary: asString(read(value, 'interpretationBoundary', 'interpretation_boundary')),
  };
}

function normalizeGovernanceComponent(value: unknown): GovernanceComponent | null {
  if (!isRecord(value)) return null;
  const componentId = asString(read(value, 'componentId', 'component_id'));
  const name = asString(read(value, 'name'));
  if (!componentId || !name) return null;
  const validationStatuses = unwrapItems(read(value, 'validation')).flatMap((item) => {
    if (!isRecord(item)) return [];
    const status = asOptionalString(read(item, 'status'));
    return status ? [status] : [];
  });
  return {
    componentId,
    name,
    kind: asString(read(value, 'kind'), 'UNCLASSIFIED'),
    owner: asString(read(value, 'owner'), 'Unassigned'),
    purpose: asString(read(value, 'purpose')),
    materiality: asString(read(value, 'materiality'), 'UNCLASSIFIED'),
    version: asString(read(value, 'version')),
    validationStatuses,
    limitations: asStringArray(read(value, 'limitations')),
    approvalStatus: asString(read(value, 'approvalStatus', 'approval_status'), 'NOT_APPROVED'),
    external: asBoolean(read(value, 'external')) ?? false,
  };
}

export function normalizeGovernanceInventory(value: unknown): GovernanceInventory {
  if (!isRecord(value)) throw new TypeError('Governance inventory response is not an object.');
  return {
    inventoryHash: asString(read(value, 'inventoryHash', 'inventory_hash')),
    items: unwrapItems(read(value, 'items'))
      .map(normalizeGovernanceComponent)
      .filter((item): item is GovernanceComponent => item !== null),
  };
}

function normalizeRedTeamDefinition(value: unknown): RedTeamDefinition | null {
  if (!isRecord(value)) return null;
  const caseId = asString(read(value, 'caseId', 'case_id'));
  if (!caseId) return null;
  return {
    caseId,
    title: asString(read(value, 'title'), caseId),
    category: asString(read(value, 'category'), 'UNCLASSIFIED'),
    severity: asString(read(value, 'severity'), 'UNCLASSIFIED'),
    owner: asString(read(value, 'owner'), 'Unassigned'),
    automationCoverage: asString(read(value, 'automationCoverage', 'automation_coverage'), 'NOT_DEFINED'),
    requiresHumanEvidence: asBoolean(read(value, 'requiresHumanEvidence', 'requires_human_evidence')) ?? false,
  };
}

function normalizeRedTeamResult(value: unknown): RedTeamResult | null {
  if (!isRecord(value)) return null;
  const caseId = asString(read(value, 'caseId', 'case_id'));
  if (!caseId) return null;
  return {
    caseId,
    category: asString(read(value, 'category'), 'UNCLASSIFIED'),
    status: asString(read(value, 'status'), 'NOT_RUN'),
    score: asNumber(read(value, 'score')) ?? 0,
    passed: asBoolean(read(value, 'passed')) ?? false,
    detail: asString(read(value, 'detail')),
  };
}

export function normalizeRedTeamRegistry(value: unknown): RedTeamRegistry {
  if (!isRecord(value)) throw new TypeError('Red-team registry response is not an object.');
  return {
    definitions: unwrapItems(read(value, 'definitions'))
      .map(normalizeRedTeamDefinition)
      .filter((item): item is RedTeamDefinition => item !== null),
    results: unwrapItems(read(value, 'results'))
      .map(normalizeRedTeamResult)
      .filter((item): item is RedTeamResult => item !== null),
    notice: asString(read(value, 'notice')),
  };
}

function normalizeReleaseGateResult(value: unknown): ReleaseGateResult | null {
  if (!isRecord(value)) return null;
  const gateId = asString(read(value, 'gateId', 'gate_id'));
  if (!gateId) return null;
  return {
    gateId,
    status: asString(read(value, 'status'), 'NOT_EVALUATED'),
    detail: asString(read(value, 'detail')),
    evidenceIds: asStringArray(read(value, 'evidenceIds', 'evidence_ids')),
  };
}

function normalizeReleaseGateDefinition(value: unknown): ReleaseGateDefinition | null {
  if (!isRecord(value)) return null;
  const gateId = asString(read(value, 'gateId', 'gate_id'));
  if (!gateId) return null;
  return {
    gateId,
    title: asString(read(value, 'title'), gateId),
    owner: asString(read(value, 'owner'), 'Unassigned'),
    criterion: asString(read(value, 'criterion')),
    failureEffect: asString(read(value, 'failureEffect', 'failure_effect')),
  };
}

export function normalizeReleaseGate(value: unknown): ReleaseGateView {
  if (!isRecord(value)) throw new TypeError('Release gate response is not an object.');
  const reportValue = read(value, 'report');
  const report = isRecord(reportValue) ? reportValue : {};
  return {
    releaseId: asString(read(report, 'releaseId', 'release_id')),
    evaluatedAt: asOptionalString(read(report, 'evaluatedAt', 'evaluated_at')),
    decision: asString(read(report, 'decision'), 'BLOCKED'),
    canRelease: asBoolean(read(report, 'canRelease', 'can_release')) ?? false,
    inventoryHash: asString(read(report, 'inventoryHash', 'inventory_hash')),
    humanEvidenceComplete: asBoolean(read(report, 'humanEvidenceComplete', 'human_evidence_complete')) ?? false,
    blockerGateIds: asStringArray(read(report, 'blockerGateIds', 'blocker_gate_ids')),
    gateResults: unwrapItems(read(report, 'gateResults', 'gate_results'))
      .map(normalizeReleaseGateResult)
      .filter((item): item is ReleaseGateResult => item !== null),
    definitions: unwrapItems(read(value, 'definitions'))
      .map(normalizeReleaseGateDefinition)
      .filter((item): item is ReleaseGateDefinition => item !== null),
    interpretationBoundary: asString(read(value, 'interpretationBoundary', 'interpretation_boundary')),
  };
}

function normalizeValidationLevel(value: unknown): ValidationLadderLevel | null {
  if (!isRecord(value)) return null;
  const level = asString(read(value, 'level'));
  if (!level) return null;
  return {
    level,
    title: asString(read(value, 'title'), level),
    status: asString(read(value, 'status'), 'NOT_STARTED'),
    boundary: asString(read(value, 'boundary')),
  };
}

export function normalizeValidationLadder(value: unknown): ValidationLadderView {
  if (!isRecord(value)) throw new TypeError('Validation ladder response is not an object.');
  return {
    highestAllowedClaim: asString(read(value, 'highestAllowedClaim', 'highest_allowed_claim'), 'MECHANISM_DEMONSTRATION'),
    levels: unwrapItems(read(value, 'levels'))
      .map(normalizeValidationLevel)
      .filter((item): item is ValidationLadderLevel => item !== null),
  };
}

const STUDY_OUTCOMES: StudyOutcomeId[] = [
  'max-drawdown-pct',
  'realized-volatility-pct',
  'max-spread-bps',
  'min-depth',
  'recovery-steps',
  'total-volume',
  'order-imbalance',
  'cascade-score',
  'network-reach-rate',
  'information-delay-steps',
  'liquidity-stress-index',
  'tail-loss-probability',
  'abnormal-return-pct',
];

const STUDY_FACTORS: StudyFactorPath[] = [
  'intervention.value',
  'market.fee_bps',
  'market.latency_ms',
  'market.price_collar_bps',
  'network.correction_reach',
  'network.echo_chamber_strength',
  'network.rewiring_probability',
  'population.institutional_share',
];

function studyOutcome(value: unknown): StudyOutcomeId | undefined {
  return typeof value === 'string' && STUDY_OUTCOMES.includes(value as StudyOutcomeId)
    ? value as StudyOutcomeId
    : undefined;
}

function studyFactor(value: unknown): StudyFactorPath | undefined {
  return typeof value === 'string' && STUDY_FACTORS.includes(value as StudyFactorPath)
    ? value as StudyFactorPath
    : undefined;
}

function studyEvidenceBasis(value: unknown): StudyEvidenceBasis {
  return value === 'EVIDENCE_BOUND' || value === 'SYNTHETIC' ? value : 'ASSUMPTION';
}

function normalizeStudyPreset(value: unknown): StudyPreset | null {
  if (!isRecord(value)) return null;
  const presetId = asString(read(value, 'presetId', 'preset_id'));
  const eventPackId = asString(read(value, 'eventPackId', 'event_pack_id'));
  const title = asString(read(value, 'title'));
  const recommendedInterventionParameter = asString(
    read(value, 'recommendedInterventionParameter', 'recommended_intervention_parameter'),
  ) as InterventionParameter;
  if (!presetId || !eventPackId || !title || !PARAMETER_VALUES.includes(recommendedInterventionParameter)) return null;
  return {
    presetId,
    eventPackId,
    title,
    titleZh: asString(read(value, 'titleZh', 'title_zh'), title),
    question: asString(read(value, 'question')),
    questionZh: asString(read(value, 'questionZh', 'question_zh')),
    recommendedInterventionParameter,
    factorPaths: unwrapItems(read(value, 'factorPaths', 'factor_paths'))
      .map(studyFactor)
      .filter((item): item is StudyFactorPath => item !== undefined),
    primaryOutcomeIds: unwrapItems(read(value, 'primaryOutcomeIds', 'primary_outcome_ids'))
      .map(studyOutcome)
      .filter((item): item is StudyOutcomeId => item !== undefined),
  };
}

export function normalizeStudyPresetCatalog(value: unknown): StudyPresetCatalog {
  if (!isRecord(value)) throw new TypeError('Study preset response is not an object.');
  const historicalValidityEstablished = asBoolean(
    read(value, 'historicalValidityEstablished', 'historical_validity_established'),
  );
  if (historicalValidityEstablished !== false) {
    throw new TypeError('Study preset response must retain historicalValidityEstablished=false.');
  }
  return {
    schemaVersion: asString(read(value, 'schemaVersion', 'schema_version'), 'unknown'),
    historicalValidityEstablished: false,
    validityBoundary: asString(read(value, 'validityBoundary', 'validity_boundary')),
    requiredNegativeControlCount: asNumber(
      read(value, 'requiredNegativeControlCount', 'required_negative_control_count'),
    ) ?? 0,
    requiredAblationCount: asNumber(
      read(value, 'requiredAblationCount', 'required_ablation_count'),
    ) ?? 0,
    supportedOutcomes: unwrapItems(read(value, 'supportedOutcomes', 'supported_outcomes')).flatMap((item) => {
      if (!isRecord(item)) return [];
      const outcomeId = studyOutcome(read(item, 'outcomeId', 'outcome_id'));
      if (!outcomeId) return [];
      return [{ outcomeId, unit: asString(read(item, 'unit')) }];
    }),
    supportedFactors: unwrapItems(read(value, 'supportedFactors', 'supported_factors')).flatMap((item) => {
      if (!isRecord(item)) return [];
      const parameterPath = studyFactor(read(item, 'parameterPath', 'parameter_path'));
      const minimum = asNumber(read(item, 'minimum'));
      const maximum = asNumber(read(item, 'maximum'));
      if (!parameterPath || minimum === undefined || maximum === undefined) return [];
      return [{ parameterPath, unit: asString(read(item, 'unit')), minimum, maximum }];
    }),
    items: unwrapItems(read(value, 'items'))
      .map(normalizeStudyPreset)
      .filter((item): item is StudyPreset => item !== null),
  };
}

function normalizeStudySetting(value: unknown) {
  if (!isRecord(value)) return null;
  const path = asString(read(value, 'path'));
  const unit = asString(read(value, 'unit'));
  const rawValue = read(value, 'value');
  if (!path || !unit || !['string', 'number', 'boolean'].includes(typeof rawValue)) return null;
  return {
    path,
    value: rawValue as string | number | boolean,
    unit,
    rationale: asString(read(value, 'rationale')),
    evidenceBasis: studyEvidenceBasis(read(value, 'evidenceBasis', 'evidence_basis')),
    sourceReference: asOptionalString(read(value, 'sourceReference', 'source_reference')),
  };
}

function normalizeStudyDesignCell(value: unknown): StudyDesignCell | null {
  if (!isRecord(value)) return null;
  const cellId = asString(read(value, 'cellId', 'cell_id'));
  const designKindValue = asString(read(value, 'designKind', 'design_kind'));
  const designKind = designKindValue === 'LATIN_HYPERCUBE' ? designKindValue : 'FULL_FACTORIAL';
  const designIndex = asNumber(read(value, 'designIndex', 'design_index'));
  if (!cellId || designIndex === undefined) return null;
  return {
    cellId,
    designKind,
    designIndex,
    settings: unwrapItems(read(value, 'settings'))
      .map(normalizeStudySetting)
      .filter((item): item is NonNullable<ReturnType<typeof normalizeStudySetting>> => item !== null),
  };
}

function normalizeStudyResourceBudget(value: JsonRecord) {
  return {
    totalExecutionCells: asNumber(read(value, 'totalExecutionCells', 'total_execution_cells')) ?? 0,
    matchedSeedCount: asNumber(read(value, 'matchedSeedCount', 'matched_seed_count')) ?? 0,
    expectedRunCount: asNumber(read(value, 'expectedRunCount', 'expected_run_count')) ?? 0,
    estimatedWorkUnits: asNumber(read(value, 'estimatedWorkUnits', 'estimated_work_units')) ?? 0,
    maximumRunCount: asNumber(read(value, 'maximumRunCount', 'maximum_run_count')) ?? 0,
    maximumWorkUnits: asNumber(read(value, 'maximumWorkUnits', 'maximum_work_units')) ?? 0,
  };
}

export function normalizeStudyDesignPreview(value: unknown): StudyDesignPreview {
  if (!isRecord(value)) throw new TypeError('Study design preview is not an object.');
  const historicalValidityEstablished = asBoolean(
    read(value, 'historicalValidityEstablished', 'historical_validity_established'),
  );
  const rawKind = asString(read(value, 'designKind', 'design_kind'));
  if (historicalValidityEstablished !== false || !['FULL_FACTORIAL', 'LATIN_HYPERCUBE'].includes(rawKind)) {
    throw new TypeError('Study design preview is missing its validity boundary or design kind.');
  }
  return {
    designKind: rawKind as StudyDesignKind,
    designCellCount: asNumber(read(value, 'designCellCount', 'design_cell_count')) ?? 0,
    requiredNegativeControlCount: asNumber(
      read(value, 'requiredNegativeControlCount', 'required_negative_control_count'),
    ) ?? 0,
    requiredAblationCount: asNumber(read(value, 'requiredAblationCount', 'required_ablation_count')) ?? 0,
    ...normalizeStudyResourceBudget(value),
    withinResourceLimits: asBoolean(read(value, 'withinResourceLimits', 'within_resource_limits')) ?? false,
    historicalValidityEstablished: false,
    cells: unwrapItems(read(value, 'cells'))
      .map(normalizeStudyDesignCell)
      .filter((item): item is StudyDesignCell => item !== null),
  };
}

function normalizeStudyPairedAnalysis(value: unknown): StudyPairedAnalysis {
  const record = isRecord(value) ? value : {};
  const bootstrapValue = read(record, 'bootstrap95');
  const bootstrap = isRecord(bootstrapValue) ? bootstrapValue : {};
  const effectValue = read(record, 'effectSize', 'effect_size');
  const effect = isRecord(effectValue) ? effectValue : {};
  return {
    sampleSize: asNumber(read(record, 'sampleSize', 'sample_size')) ?? 0,
    meanDifference: asNumber(read(record, 'meanDifference', 'mean_difference')) ?? 0,
    medianDifference: asNumber(read(record, 'medianDifference', 'median_difference')) ?? 0,
    percentileLower: asNumber(read(record, 'percentileLower', 'percentile_lower')) ?? 0,
    percentileUpper: asNumber(read(record, 'percentileUpper', 'percentile_upper')) ?? 0,
    bootstrap95: {
      estimate: asNumber(read(bootstrap, 'estimate')) ?? 0,
      lower: asNumber(read(bootstrap, 'lower')) ?? 0,
      upper: asNumber(read(bootstrap, 'upper')) ?? 0,
      confidenceLevel: asNumber(read(bootstrap, 'confidenceLevel', 'confidence_level')) ?? 0,
      resamples: asNumber(read(bootstrap, 'resamples')) ?? 0,
      seed: asNumber(read(bootstrap, 'seed')) ?? 0,
      statisticName: asString(read(bootstrap, 'statisticName', 'statistic_name')),
      containsZero: asBoolean(read(bootstrap, 'containsZero', 'contains_zero')),
    },
    effectSize: {
      meanDifference: asNumber(read(effect, 'meanDifference', 'mean_difference')) ?? 0,
      standardDeviationDifference: asNumber(
        read(effect, 'standardDeviationDifference', 'standard_deviation_difference'),
      ) ?? 0,
      cohensDz: asNumber(read(effect, 'cohensDz', 'cohens_dz')),
      matchedRankBiserial: asNumber(read(effect, 'matchedRankBiserial', 'matched_rank_biserial')) ?? 0,
    },
    signConsistency: asNumber(read(record, 'signConsistency', 'sign_consistency')) ?? 0,
    positiveTailProbability: asNumber(
      read(record, 'positiveTailProbability', 'positive_tail_probability'),
    ) ?? 0,
    negativeTailProbability: asNumber(
      read(record, 'negativeTailProbability', 'negative_tail_probability'),
    ) ?? 0,
    differences: Array.isArray(read(record, 'differences'))
      ? (read(record, 'differences') as unknown[]).map(asNumber).filter((item): item is number => item !== undefined)
      : [],
  };
}

function normalizeStudyCellAnalysis(value: unknown): StudyCellOutcomeAnalysis | null {
  if (!isRecord(value)) return null;
  const hypothesisId = asString(read(value, 'hypothesisId', 'hypothesis_id'));
  const outcomeId = studyOutcome(read(value, 'outcomeId', 'outcome_id'));
  const direction = asString(read(value, 'expectedDirection', 'expected_direction'));
  if (!hypothesisId || !outcomeId || !['INCREASE', 'DECREASE', 'TWO_SIDED'].includes(direction)) return null;
  return {
    hypothesisId,
    familyId: asString(read(value, 'familyId', 'family_id')),
    cellId: asString(read(value, 'cellId', 'cell_id')),
    outcomeId,
    expectedDirection: direction as StudyCellOutcomeAnalysis['expectedDirection'],
    analysis: normalizeStudyPairedAnalysis(read(value, 'analysis')),
    exactSignPValue: asNumber(read(value, 'exactSignPValue', 'exact_sign_p_value')) ?? 1,
  };
}

function normalizeStudyNegativeControl(value: unknown): StudyNegativeControl | null {
  if (!isRecord(value)) return null;
  const controlId = asString(read(value, 'controlId', 'control_id'));
  const expectation = asString(read(value, 'expectation'));
  if (!controlId || !['NULL_EFFECT', 'MECHANISM_DIAGNOSTIC'].includes(expectation)) return null;
  return {
    controlId,
    kind: asString(read(value, 'kind')),
    expectation: expectation as StudyNegativeControl['expectation'],
    cellId: asString(read(value, 'cellId', 'cell_id')),
    outcomeResults: unwrapItems(read(value, 'outcomeResults', 'outcome_results')).flatMap((item) => {
      if (!isRecord(item)) return [];
      const outcomeId = studyOutcome(read(item, 'outcomeId', 'outcome_id'));
      const rawResult = read(item, 'result');
      if (!outcomeId || !isRecord(rawResult)) return [];
      return [{
        outcomeId,
        result: {
          controlName: asString(read(rawResult, 'controlName', 'control_name')),
          tolerance: asNumber(read(rawResult, 'tolerance')) ?? 0,
          analysis: normalizeStudyPairedAnalysis(read(rawResult, 'analysis')),
          passed: asBoolean(read(rawResult, 'passed')) ?? false,
          reason: asString(read(rawResult, 'reason')),
        },
      }];
    }),
    interpretationBoundary: asString(read(value, 'interpretationBoundary', 'interpretation_boundary')),
  };
}

function normalizeStudySensitivity(value: unknown): StudySensitivityOutcome | null {
  if (!isRecord(value)) return null;
  const outcomeId = studyOutcome(read(value, 'outcomeId', 'outcome_id'));
  if (!outcomeId) return null;
  return {
    outcomeId,
    method: asString(read(value, 'method')),
    indices: unwrapItems(read(value, 'indices')).flatMap((item) => {
      if (!isRecord(item)) return [];
      const parameter = asString(read(item, 'parameter'));
      if (!parameter) return [];
      return [{
        parameter,
        spearmanCorrelation: asNumber(read(item, 'spearmanCorrelation', 'spearman_correlation')) ?? 0,
        direction: asString(read(item, 'direction')),
        varianceImportanceProxy: asNumber(
          read(item, 'varianceImportanceProxy', 'variance_importance_proxy'),
        ) ?? 0,
        sampleSize: asNumber(read(item, 'sampleSize', 'sample_size')) ?? 0,
      }];
    }),
    dominantParameter: asOptionalString(read(value, 'dominantParameter', 'dominant_parameter')),
    dominantEvidenceBasis: asOptionalString(
      read(value, 'dominantEvidenceBasis', 'dominant_evidence_basis'),
    ) as StudyEvidenceBasis | undefined,
    interpretation: asString(read(value, 'interpretation')),
    warning: asString(read(value, 'warning')),
  };
}

function normalizeStudyExecutionCell(value: unknown): StudyExecutionCell | null {
  if (!isRecord(value)) return null;
  const cellId = asString(read(value, 'cellId', 'cell_id'));
  const role = asString(read(value, 'role'));
  if (!cellId || !['BASELINE', 'DESIGN', 'NEGATIVE_CONTROL', 'ABLATION'].includes(role)) return null;
  return {
    cellId,
    role: role as StudyExecutionCell['role'],
    sourceId: asString(read(value, 'sourceId', 'source_id')),
    sourceKind: asString(read(value, 'sourceKind', 'source_kind')),
    settings: unwrapItems(read(value, 'settings'))
      .map(normalizeStudySetting)
      .filter((item): item is NonNullable<ReturnType<typeof normalizeStudySetting>> => item !== null),
  };
}

function normalizeStudyCoreResult(value: unknown): StudyCoreResult {
  if (!isRecord(value)) throw new TypeError('Study result core is not an object.');
  const auditValue = read(value, 'audit');
  const audit = isRecord(auditValue) ? auditValue : {};
  const historicalValidityEstablished = asBoolean(
    read(audit, 'historicalValidityEstablished', 'historical_validity_established'),
  );
  if (historicalValidityEstablished !== false) {
    throw new TypeError('Study audit must retain historicalValidityEstablished=false.');
  }
  return {
    studyId: asString(read(value, 'studyId', 'study_id')),
    cells: unwrapItems(read(value, 'cells'))
      .map(normalizeStudyExecutionCell)
      .filter((item): item is StudyExecutionCell => item !== null),
    cellOutcomeAnalyses: unwrapItems(read(value, 'cellOutcomeAnalyses', 'cell_outcome_analyses'))
      .map(normalizeStudyCellAnalysis)
      .filter((item): item is StudyCellOutcomeAnalysis => item !== null),
    holmFamilies: unwrapItems(read(value, 'holmFamilies', 'holm_families')).flatMap((family) => {
      if (!isRecord(family)) return [];
      const familyId = asString(read(family, 'familyId', 'family_id'));
      if (!familyId) return [];
      return [{
        familyId,
        alpha: asNumber(read(family, 'alpha')) ?? 0.05,
        results: unwrapItems(read(family, 'results')).flatMap((item) => {
          if (!isRecord(item)) return [];
          const hypothesisId = asString(read(item, 'hypothesisId', 'hypothesis_id'));
          if (!hypothesisId) return [];
          return [{
            hypothesisId,
            rawPValue: asNumber(read(item, 'rawPValue', 'raw_p_value')) ?? 1,
            adjustedPValue: asNumber(read(item, 'adjustedPValue', 'adjusted_p_value')) ?? 1,
            alphaThreshold: asNumber(read(item, 'alphaThreshold', 'alpha_threshold')) ?? 0,
            rejected: asBoolean(read(item, 'rejected')) ?? false,
            rank: asNumber(read(item, 'rank')) ?? 0,
          }];
        }),
      }];
    }),
    negativeControls: unwrapItems(read(value, 'negativeControls', 'negative_controls'))
      .map(normalizeStudyNegativeControl)
      .filter((item): item is StudyNegativeControl => item !== null),
    sensitivity: unwrapItems(read(value, 'sensitivity'))
      .map(normalizeStudySensitivity)
      .filter((item): item is StudySensitivityOutcome => item !== null),
    audit: {
      specHash: asString(read(audit, 'specHash', 'spec_hash')),
      resultHash: asString(read(audit, 'resultHash', 'result_hash')),
      runnerName: asString(read(audit, 'runnerName', 'runner_name')),
      expectedRunCount: asNumber(read(audit, 'expectedRunCount', 'expected_run_count')) ?? 0,
      completedRunCount: asNumber(read(audit, 'completedRunCount', 'completed_run_count')) ?? 0,
      commonRandomSeedScheduleVerified: asBoolean(
        read(audit, 'commonRandomSeedScheduleVerified', 'common_random_seed_schedule_verified'),
      ) ?? false,
      historicalValidityEstablished: false,
      validityBoundary: asString(read(audit, 'validityBoundary', 'validity_boundary')),
    },
  };
}

function normalizeStudyResultDocument(value: unknown): StudyResultDocument {
  if (!isRecord(value)) throw new TypeError('Study result document is not an object.');
  const protocolValue = read(value, 'executionProtocol', 'execution_protocol');
  const protocol = isRecord(protocolValue) ? protocolValue : {};
  const budgetValue = read(value, 'resourceBudget', 'resource_budget');
  const budget = isRecord(budgetValue) ? budgetValue : {};
  if (asBoolean(read(value, 'historicalValidityEstablished', 'historical_validity_established')) !== false) {
    throw new TypeError('Study result must retain historicalValidityEstablished=false.');
  }
  return {
    schemaVersion: asString(read(value, 'schemaVersion', 'schema_version')),
    runId: asString(read(value, 'runId', 'run_id')),
    studyId: asString(read(value, 'studyId', 'study_id')),
    status: 'COMPLETED',
    eventPackId: asString(read(value, 'eventPackId', 'event_pack_id')),
    historicalValidityEstablished: false,
    validityBoundary: asString(read(value, 'validityBoundary', 'validity_boundary')),
    resourceBudget: normalizeStudyResourceBudget(budget),
    executionProtocol: {
      runner: asString(read(protocol, 'runner')),
      marketKernel: asString(read(protocol, 'marketKernel', 'market_kernel')),
      cognitionMode: asString(read(protocol, 'cognitionMode', 'cognition_mode')),
      matchedSeeds: asBoolean(read(protocol, 'matchedSeeds', 'matched_seeds')) ?? false,
      requiredNegativeControlsIncluded: asNumber(
        read(protocol, 'requiredNegativeControlsIncluded', 'required_negative_controls_included'),
      ) ?? 0,
      requiredAblationsIncluded: asNumber(
        read(protocol, 'requiredAblationsIncluded', 'required_ablations_included'),
      ) ?? 0,
      proxyAblationsAcknowledged: asBoolean(
        read(protocol, 'proxyAblationsAcknowledged', 'proxy_ablations_acknowledged'),
      ) ?? false,
      mechanismSemantics: unwrapItems(read(protocol, 'mechanismSemantics', 'mechanism_semantics')).flatMap((item) => {
        if (!isRecord(item)) return [];
        const kind = asString(read(item, 'kind'));
        if (!kind) return [];
        return [{ kind, status: asString(read(item, 'status')), boundary: asString(read(item, 'boundary')) }];
      }),
    },
    preregistration: isRecord(read(value, 'preregistration'))
      ? read(value, 'preregistration') as JsonRecord
      : {},
    result: normalizeStudyCoreResult(read(value, 'result')),
  };
}

export function normalizeStudyRun(value: unknown): StudyRunRecord {
  if (!isRecord(value)) throw new TypeError('Study run response is not an object.');
  const runId = asString(read(value, 'runId', 'run_id'));
  const eventPackId = asString(read(value, 'eventPackId', 'event_pack_id'));
  const studyId = asString(read(value, 'studyId', 'study_id'));
  if (!runId || !eventPackId || !studyId) throw new TypeError('Study run is missing required identifiers.');
  if (asBoolean(read(value, 'historicalValidityEstablished', 'historical_validity_established')) !== false) {
    throw new TypeError('Study run must retain historicalValidityEstablished=false.');
  }
  const resultValue = read(value, 'result');
  return {
    runId,
    eventPackId,
    studyId,
    status: 'COMPLETED',
    specHash: asString(read(value, 'specHash', 'spec_hash')),
    resultHash: asString(read(value, 'resultHash', 'result_hash')),
    historicalValidityEstablished: false,
    createdAt: asString(read(value, 'createdAt', 'created_at')),
    spec: isRecord(read(value, 'spec')) ? read(value, 'spec') as JsonRecord : undefined,
    result: resultValue === undefined ? undefined : normalizeStudyResultDocument(resultValue),
  };
}

export function normalizeStudyRuns(value: unknown): StudyRunRecord[] {
  return unwrapItems(value).map(normalizeStudyRun);
}
