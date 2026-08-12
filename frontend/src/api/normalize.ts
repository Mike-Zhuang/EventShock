import type {
  AccountDataExport,
  AccountSession,
  AccountDeletionReceipt,
  AdminActivity,
  AdminActivityPage,
  AdminLlmCredentialView,
  AdminUserPage,
  AdminUserStatistics,
  AdminUserSummary,
  AdvancedModelParameterName,
  AdvancedModelParameters,
  AgentFlowPoint,
  AgentPnlPoint,
  AnalysisDiagnostics,
  AuthSession,
  AuthUser,
  LegalAcceptanceStatus,
  LegalDocument,
  LegalSection,
  UserPreferences,
  CaseSummary,
  ClaimImpactChannelRationale,
  CognitionDecisionSummary,
  CognitionEvalSummary,
  CognitionEvaluationRun,
  CognitionRunMetadata,
  CognitionTelemetry,
  DeploymentCheckStatus,
  DeploymentStatus,
  DistributionPoint,
  EventClaim,
  EventPack,
  EventPackContentSecurity,
  EventPackFactoryBuild,
  EventPackFactoryMutation,
  EventPackFactorySearchRun,
  EventPackFactorySnapshot,
  EventPackFactorySource,
  EventPackFactorySourceRawText,
  EventSource,
  Experiment,
  ExperimentLogEntry,
  ExperimentResults,
  ExperimentStatus,
  GovernanceComponent,
  GovernanceInventory,
  GuidedEventMetadata,
  GuidedIntervention,
  GuidedStage,
  GuidedTurnOperation,
  GuidedTurnRecoveryAction,
  GuidedTurnRecoveryResult,
  GuidedWorkflow,
  GuidedWorkflowArchivedProposal,
  GuidedWorkflowDraft,
  GuidedWorkflowMessage,
  GuidedWorkflowProposal,
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
  OrderExecutionSummary,
  FactorySearchEngineDescriptor,
  FactorySearchEngineId,
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

function normalizeLegalAcceptanceStatus(value: unknown): LegalAcceptanceStatus {
  if (!isRecord(value)) throw new TypeError('Legal acceptance status is not an object.');
  return {
    required: asBoolean(read(value, 'required')) ?? true,
    version: asString(read(value, 'version')),
    acceptedAt: asOptionalString(read(value, 'acceptedAt', 'accepted_at')),
  };
}

function normalizeUserPreferences(value: unknown): UserPreferences {
  if (!isRecord(value)) throw new TypeError('User preferences are not an object.');
  const experienceLevel = asOptionalString(read(value, 'experienceLevel', 'experience_level'));
  const workspaceMode = asOptionalString(read(value, 'workspaceMode', 'workspace_mode'));
  const assistancePreference = asOptionalString(
    read(value, 'assistancePreference', 'assistance_preference'),
  );
  const firstGoal = asOptionalString(read(value, 'firstGoal', 'first_goal'));
  const preferredLlmProvider = asLlmProviderId(
    read(value, 'preferredLlmProvider', 'preferred_llm_provider'),
  );
  if (experienceLevel && !['NEW', 'INTERMEDIATE', 'ADVANCED'].includes(experienceLevel)) {
    throw new TypeError('User preferences contain an unsupported experience level.');
  }
  if (workspaceMode && !['GUIDED', 'EXPERT'].includes(workspaceMode)) {
    throw new TypeError('User preferences contain an unsupported workspace mode.');
  }
  if (
    assistancePreference
    && !['STEP_BY_STEP', 'PROPOSE_AND_ADJUST', 'DIRECT_CONTROL'].includes(assistancePreference)
  ) {
    throw new TypeError('User preferences contain an unsupported assistance preference.');
  }
  if (
    firstGoal
    && !['TRY_DEMO', 'RESEARCH_NEW_EVENT', 'DESIGN_FULL_EXPERIMENT'].includes(firstGoal)
  ) {
    throw new TypeError('User preferences contain an unsupported first goal.');
  }
  return {
    onboardingRequired: asBoolean(
      read(value, 'onboardingRequired', 'onboarding_required'),
    ) ?? true,
    experienceLevel: experienceLevel as UserPreferences['experienceLevel'],
    workspaceMode: workspaceMode as UserPreferences['workspaceMode'],
    assistancePreference: assistancePreference as UserPreferences['assistancePreference'],
    firstGoal: firstGoal as UserPreferences['firstGoal'],
    onboardingVersion: asOptionalString(read(value, 'onboardingVersion', 'onboarding_version')),
    onboardingCompletedAt: asOptionalString(
      read(value, 'onboardingCompletedAt', 'onboarding_completed_at'),
    ),
    updatedAt: asOptionalString(read(value, 'updatedAt', 'updated_at')),
    preferredLlmProvider,
    preferredLlmModel: asOptionalString(
      read(value, 'preferredLlmModel', 'preferred_llm_model'),
    ),
  };
}

function normalizeLegalSection(value: unknown): LegalSection {
  if (!isRecord(value)) throw new TypeError('Legal document section is not an object.');
  return {
    id: asString(read(value, 'id')),
    title: asString(read(value, 'title')),
    body: asStringArray(read(value, 'body')),
  };
}

export function normalizeLegalDocument(value: unknown): LegalDocument {
  if (!isRecord(value)) throw new TypeError('Legal document response is not an object.');
  const locale = asString(read(value, 'locale'));
  if (!['en', 'zh-CN'].includes(locale)) {
    throw new TypeError('Legal document contains an unsupported locale.');
  }
  return {
    schemaVersion: asString(read(value, 'schemaVersion', 'schema_version')),
    version: asString(read(value, 'version')),
    effectiveDate: asString(read(value, 'effectiveDate', 'effective_date')),
    locale: locale as LegalDocument['locale'],
    title: asString(read(value, 'title')),
    summary: asString(read(value, 'summary')),
    operatorLabel: asString(read(value, 'operatorLabel', 'operator_label')),
    minimumAge: asNumber(read(value, 'minimumAge', 'minimum_age')) ?? 18,
    sections: unwrapItems(read(value, 'sections')).map(normalizeLegalSection),
    acceptanceStatements: asStringArray(
      read(value, 'acceptanceStatements', 'acceptance_statements'),
    ),
    legalReviewNotice: asString(read(value, 'legalReviewNotice', 'legal_review_notice')),
    documentHash: asString(read(value, 'documentHash', 'document_hash')),
  };
}

export function normalizeLegalAcceptance(value: unknown): LegalAcceptanceStatus {
  return normalizeLegalAcceptanceStatus(value);
}

export function normalizePreferences(value: unknown): UserPreferences {
  return normalizeUserPreferences(value);
}

const FACTORY_BUILD_STATUSES = ['DRAFT', 'REVIEW_READY'] as const;
const FACTORY_SOURCE_KINDS = ['PASTE', 'SEARCH_RESULT', 'READER'] as const;
const FACTORY_EVIDENCE_ROLES = ['EVIDENCE', 'DISCOVERY_ONLY'] as const;
const FACTORY_REVIEW_STATUSES = ['PENDING', 'APPROVED', 'REJECTED'] as const;
const FACTORY_SELECTION_STATUSES = ['INCLUDED', 'EXCLUDED'] as const;
const FACTORY_SECURITY_DECISIONS = ['ALLOW', 'REVIEW'] as const;
const FACTORY_SEARCH_ENGINES: FactorySearchEngineId[] = [
  'search_std',
  'search_pro',
  'search_pro_sogou',
  'search_pro_quark',
];
const GUIDED_STAGES: GuidedStage[] = [
  'EVENT_GOAL',
  'SOURCE_METHOD',
  'SOURCE_REVIEW',
  'CLAIM_REVIEW',
  'PACK_METADATA_REVIEW',
  'PACK_FREEZE_REVIEW',
  'SCENARIO_INTERVENTION',
  'SCENARIO_REVIEW',
  'PREFLIGHT',
  'READY_TO_SUBMIT',
  'COMPLETED',
];

function requiredString(value: unknown, field: string): string {
  if (typeof value !== 'string' || value.trim().length === 0) {
    throw new TypeError(`${field} must be a non-empty string.`);
  }
  return value;
}

function requiredNumber(value: unknown, field: string, integer = false): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || (integer && !Number.isInteger(value))) {
    throw new TypeError(`${field} must be a finite${integer ? ' integer' : ''} number.`);
  }
  return value;
}

function enumValue<T extends string>(
  value: unknown,
  allowed: readonly T[],
  field: string,
): T {
  if (typeof value !== 'string' || !allowed.includes(value as T)) {
    throw new TypeError(`${field} contains an unsupported value.`);
  }
  return value as T;
}

function normalizeFactorySearchEngine(value: unknown): FactorySearchEngineDescriptor {
  if (!isRecord(value)) throw new TypeError('Factory search-engine item is not an object.');
  const supportedCountsRaw = read(value, 'supportedCounts', 'supported_counts');
  const supportedCounts = supportedCountsRaw === undefined || supportedCountsRaw === null
    ? undefined
    : Array.isArray(supportedCountsRaw)
      ? supportedCountsRaw.map((item) => requiredNumber(item, 'supportedCounts item', true))
      : (() => { throw new TypeError('supportedCounts must be an array.'); })();
  return {
    engine: enumValue(
      read(value, 'engine'),
      FACTORY_SEARCH_ENGINES,
      'engine',
    ),
    displayName: requiredString(read(value, 'displayName', 'display_name'), 'displayName'),
    priceCnyPerCall: requiredNumber(
      read(value, 'priceCnyPerCall', 'price_cny_per_call'),
      'priceCnyPerCall',
    ),
    supportsCount: asBoolean(read(value, 'supportsCount', 'supports_count')) ?? false,
    supportedCounts,
    supportsDomainFilter: asBoolean(
      read(value, 'supportsDomainFilter', 'supports_domain_filter'),
    ) ?? false,
    supportsRecencyFilter: asBoolean(
      read(value, 'supportsRecencyFilter', 'supports_recency_filter'),
    ) ?? false,
    supportsContentSize: asBoolean(
      read(value, 'supportsContentSize', 'supports_content_size'),
    ) ?? false,
  };
}

export function normalizeFactorySearchEngines(value: unknown): FactorySearchEngineDescriptor[] {
  return unwrapItems(value).map(normalizeFactorySearchEngine);
}

export function normalizeFactoryBuild(value: unknown): EventPackFactoryBuild {
  if (!isRecord(value)) throw new TypeError('Factory build is not an object.');
  return {
    id: requiredString(read(value, 'id'), 'build.id'),
    ownerUserId: requiredString(read(value, 'ownerUserId', 'owner_user_id'), 'build.ownerUserId'),
    title: requiredString(read(value, 'title'), 'build.title'),
    status: enumValue(read(value, 'status'), FACTORY_BUILD_STATUSES, 'build.status'),
    revision: requiredNumber(read(value, 'revision'), 'build.revision', true),
    createdAt: requiredString(read(value, 'createdAt', 'created_at'), 'build.createdAt'),
    updatedAt: requiredString(read(value, 'updatedAt', 'updated_at'), 'build.updatedAt'),
    retentionExpiresAt: requiredString(
      read(value, 'retentionExpiresAt', 'retention_expires_at'),
      'build.retentionExpiresAt',
    ),
  };
}

export function normalizeFactoryBuilds(value: unknown): EventPackFactoryBuild[] {
  return unwrapItems(value).map(normalizeFactoryBuild);
}

function normalizeFactorySource(value: unknown): EventPackFactorySource {
  if (!isRecord(value)) throw new TypeError('Factory source is not an object.');
  const quotes = read(value, 'verifiedEvidenceQuotes', 'verified_evidence_quotes');
  if (quotes !== undefined && !Array.isArray(quotes)) {
    throw new TypeError('verifiedEvidenceQuotes must be an array.');
  }
  const securityFindings = unwrapItems(
    read(value, 'securityFindings', 'security_findings'),
  ).flatMap((item) => {
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
      riskCategory: asOptionalString(read(item, 'riskCategory', 'risk_category')),
      recommendedAction: asOptionalString(
        read(item, 'recommendedAction', 'recommended_action'),
      ),
    }];
  });
  return {
    id: requiredString(read(value, 'id'), 'source.id'),
    buildId: requiredString(read(value, 'buildId', 'build_id'), 'source.buildId'),
    kind: enumValue(read(value, 'kind'), FACTORY_SOURCE_KINDS, 'source.kind'),
    evidenceRole: enumValue(
      read(value, 'evidenceRole', 'evidence_role'),
      FACTORY_EVIDENCE_ROLES,
      'source.evidenceRole',
    ),
    reviewStatus: enumValue(
      read(value, 'reviewStatus', 'review_status'),
      FACTORY_REVIEW_STATUSES,
      'source.reviewStatus',
    ),
    selectionStatus: enumValue(
      read(value, 'selectionStatus', 'selection_status') ?? 'INCLUDED',
      FACTORY_SELECTION_STATUSES,
      'source.selectionStatus',
    ),
    securityDecision: enumValue(
      read(value, 'securityDecision', 'security_decision'),
      FACTORY_SECURITY_DECISIONS,
      'source.securityDecision',
    ),
    sourceReviewLabel: asString(
      read(value, 'sourceReviewLabel', 'source_review_label'),
      'URL_MISSING',
    ),
    officialHost: asOptionalString(read(value, 'officialHost', 'official_host')),
    securityFindings,
    title: requiredString(read(value, 'title'), 'source.title'),
    publisher: requiredString(read(value, 'publisher'), 'source.publisher'),
    url: asOptionalString(read(value, 'url')),
    publishedAt: asOptionalString(read(value, 'publishedAt', 'published_at')),
    knownAt: requiredString(read(value, 'knownAt', 'known_at'), 'source.knownAt'),
    contentHash: requiredString(read(value, 'contentHash', 'content_hash'), 'source.contentHash'),
    contentLength: requiredNumber(
      read(value, 'contentLength', 'content_length'),
      'source.contentLength',
      true,
    ),
    reviewSummary: requiredString(
      read(value, 'reviewSummary', 'review_summary'),
      'source.reviewSummary',
    ),
    verifiedEvidenceQuotes: asStringArray(quotes),
    searchRunId: asOptionalString(read(value, 'searchRunId', 'search_run_id')),
    parentSourceId: asOptionalString(read(value, 'parentSourceId', 'parent_source_id')),
    createdAt: requiredString(read(value, 'createdAt', 'created_at'), 'source.createdAt'),
    updatedAt: requiredString(read(value, 'updatedAt', 'updated_at'), 'source.updatedAt'),
  };
}

function normalizeFactorySearchRun(value: unknown): EventPackFactorySearchRun {
  if (!isRecord(value)) throw new TypeError('Factory search run is not an object.');
  const rawParameters = read(value, 'requestParameters', 'request_parameters');
  if (!isRecord(rawParameters)) throw new TypeError('requestParameters must be an object.');
  const requestParameters: Record<string, string | number | boolean | null> = {};
  Object.entries(rawParameters).forEach(([key, item]) => {
    if (
      typeof item === 'string'
      || typeof item === 'number'
      || typeof item === 'boolean'
      || item === null
    ) requestParameters[key] = item;
  });
  return {
    id: requiredString(read(value, 'id'), 'searchRun.id'),
    buildId: requiredString(read(value, 'buildId', 'build_id'), 'searchRun.buildId'),
    engine: enumValue(read(value, 'engine'), FACTORY_SEARCH_ENGINES, 'searchRun.engine'),
    query: requiredString(read(value, 'query'), 'searchRun.query'),
    queryHash: requiredString(read(value, 'queryHash', 'query_hash'), 'searchRun.queryHash'),
    requestParameters,
    providerRequestId: requiredString(
      read(value, 'providerRequestId', 'provider_request_id'),
      'searchRun.providerRequestId',
    ),
    estimatedCostCny: requiredNumber(
      read(value, 'estimatedCostCny', 'estimated_cost_cny'),
      'searchRun.estimatedCostCny',
    ),
    resultCount: requiredNumber(read(value, 'resultCount', 'result_count'), 'resultCount', true),
    droppedResultCount: requiredNumber(
      read(value, 'droppedResultCount', 'dropped_result_count'),
      'droppedResultCount',
      true,
    ),
    createdAt: requiredString(read(value, 'createdAt', 'created_at'), 'searchRun.createdAt'),
  };
}

export function normalizeFactorySnapshot(value: unknown): EventPackFactorySnapshot {
  if (!isRecord(value)) throw new TypeError('Factory snapshot is not an object.');
  const sources = read(value, 'sources');
  const searchRuns = read(value, 'searchRuns', 'search_runs');
  if (!Array.isArray(sources) || !Array.isArray(searchRuns)) {
    throw new TypeError('Factory snapshot collections are invalid.');
  }
  return {
    build: normalizeFactoryBuild(read(value, 'build')),
    sources: sources.map(normalizeFactorySource),
    searchRuns: searchRuns.map(normalizeFactorySearchRun),
  };
}

export function normalizeFactoryMutation(value: unknown): EventPackFactoryMutation {
  if (!isRecord(value)) throw new TypeError('Factory mutation response is not an object.');
  const sources = read(value, 'sources');
  if (!Array.isArray(sources)) throw new TypeError('Factory mutation sources are invalid.');
  const searchRun = read(value, 'searchRun', 'search_run');
  return {
    build: normalizeFactoryBuild(read(value, 'build')),
    sources: sources.map(normalizeFactorySource),
    searchRun: searchRun === undefined || searchRun === null
      ? undefined
      : normalizeFactorySearchRun(searchRun),
    idempotencyReplayed: asBoolean(
      read(value, 'idempotencyReplayed', 'idempotency_replayed'),
    ) ?? false,
  };
}

export function normalizeFactorySourceRawText(value: unknown): EventPackFactorySourceRawText {
  if (!isRecord(value)) throw new TypeError('Factory source raw text is not an object.');
  return {
    buildId: requiredString(read(value, 'buildId', 'build_id'), 'rawText.buildId'),
    sourceId: requiredString(read(value, 'sourceId', 'source_id'), 'rawText.sourceId'),
    revision: requiredNumber(read(value, 'revision'), 'rawText.revision', true),
    rawText: requiredString(read(value, 'rawText', 'raw_text'), 'rawText.rawText'),
    contentHash: requiredString(read(value, 'contentHash', 'content_hash'), 'rawText.contentHash'),
    contentLength: requiredNumber(
      read(value, 'contentLength', 'content_length'),
      'rawText.contentLength',
      true,
    ),
    retentionExpiresAt: requiredString(
      read(value, 'retentionExpiresAt', 'retention_expires_at'),
      'rawText.retentionExpiresAt',
    ),
  };
}

function normalizeGuidedEventMetadata(value: unknown): GuidedEventMetadata {
  if (!isRecord(value)) throw new TypeError('Guided event metadata is not an object.');
  return {
    title: requiredString(read(value, 'title'), 'eventMetadata.title'),
    titleZh: asOptionalString(read(value, 'titleZh', 'title_zh')),
    summary: requiredString(read(value, 'summary'), 'eventMetadata.summary'),
    summaryZh: asOptionalString(read(value, 'summaryZh', 'summary_zh')),
    instrument: requiredString(read(value, 'instrument'), 'eventMetadata.instrument'),
    asOf: requiredString(read(value, 'asOf', 'as_of'), 'eventMetadata.asOf'),
    asOfPrecision: asOptionalString(
      read(value, 'asOfPrecision', 'as_of_precision'),
    ) as GuidedEventMetadata['asOfPrecision'],
    researchQuestion: requiredString(
      read(value, 'researchQuestion', 'research_question'),
      'eventMetadata.researchQuestion',
    ),
  };
}

function normalizeGuidedIntervention(value: unknown): GuidedIntervention {
  if (!isRecord(value)) throw new TypeError('Guided intervention is not an object.');
  const parameter = asString(read(value, 'parameter'));
  if (!PARAMETER_VALUES.includes(parameter as InterventionParameter)) {
    throw new TypeError('Guided intervention contains an unsupported parameter.');
  }
  return {
    parameter: parameter as InterventionParameter,
    baselineValue: requiredNumber(read(value, 'baselineValue', 'baseline_value'), 'baselineValue'),
    interventionValue: requiredNumber(
      read(value, 'interventionValue', 'intervention_value'),
      'interventionValue',
    ),
    explanation: requiredString(read(value, 'explanation'), 'intervention.explanation'),
  };
}

function normalizeGuidedProposal(value: unknown): GuidedWorkflowProposal {
  if (!isRecord(value)) throw new TypeError('Guided proposal is not an object.');
  const schemaVersion = requiredString(
    read(value, 'schemaVersion', 'schema_version'),
    'proposal.schemaVersion',
  );
  if (schemaVersion !== 'guided_proposal_v1.0.0') {
    throw new TypeError('Guided proposal schema version is unsupported.');
  }
  const sourceMethod = asOptionalString(
    read(value, 'proposedSourceMethod', 'proposed_source_method'),
  );
  if (sourceMethod && !['PASTE', 'WEB_SEARCH', 'COMBINED', 'MANUAL'].includes(sourceMethod)) {
    throw new TypeError('Guided proposal source method is unsupported.');
  }
  const reviewItems = unwrapItems(read(value, 'reviewItems', 'review_items'))
    .map((item) => {
      if (!isRecord(item)) return null;
      const category = asOptionalString(read(item, 'category'));
      if (!category || !['SOURCE', 'CLAIM', 'METADATA', 'FREEZE', 'SCENARIO', 'PREFLIGHT'].includes(category)) return null;
      const id = asOptionalString(read(item, 'id'));
      const title = asOptionalString(read(item, 'title'));
      const detail = asOptionalString(read(item, 'detail'));
      if (!id || !title || !detail) return null;
      return {
        id,
        category: category as NonNullable<GuidedWorkflowProposal['reviewItems']>[number]['category'],
        title,
        detail,
        requiresExplicitReview: asBoolean(
          read(item, 'requiresExplicitReview', 'requires_explicit_review'),
        ) ?? true,
      };
    })
    .filter((item): item is NonNullable<GuidedWorkflowProposal['reviewItems']>[number] => item !== null);
  return {
    schemaVersion,
    stage: enumValue(read(value, 'stage'), GUIDED_STAGES, 'proposal.stage'),
    assistantMessage: requiredString(
      read(value, 'assistantMessage', 'assistant_message'),
      'proposal.assistantMessage',
    ),
    clarificationRequired: asBoolean(
      read(value, 'clarificationRequired', 'clarification_required'),
    ) ?? false,
    proposedEventMetadata: read(value, 'proposedEventMetadata', 'proposed_event_metadata')
      ? normalizeGuidedEventMetadata(
        read(value, 'proposedEventMetadata', 'proposed_event_metadata'),
      )
      : undefined,
    proposedSourceMethod: sourceMethod as GuidedWorkflowProposal['proposedSourceMethod'],
    proposedSearchQueries: asStringArray(
      read(value, 'proposedSearchQueries', 'proposed_search_queries'),
    ),
    proposedIntervention: read(value, 'proposedIntervention', 'proposed_intervention')
      ? normalizeGuidedIntervention(read(value, 'proposedIntervention', 'proposed_intervention'))
      : undefined,
    nextQuestionOptions: asStringArray(read(value, 'nextQuestionOptions', 'next_question_options')),
    readyForHumanReview: asBoolean(
      read(value, 'readyForHumanReview', 'ready_for_human_review'),
    ) ?? false,
    blockedReasons: asStringArray(read(value, 'blockedReasons', 'blocked_reasons')),
    missingFields: asStringArray(
      read(value, 'missingFields', 'missing_fields'),
    ) as GuidedWorkflowProposal['missingFields'],
    unresolvedFields: unwrapItems(read(value, 'unresolvedFields', 'unresolved_fields'))
      .map((item) => {
        if (!isRecord(item)) return null;
        const field = asOptionalString(read(item, 'field'));
        const reason = asOptionalString(read(item, 'reason'));
        if (!field || !reason || !['title', 'summary', 'instrument', 'asOf', 'researchQuestion'].includes(field)) return null;
        return { field, reason } as NonNullable<GuidedWorkflowProposal['unresolvedFields']>[number];
      })
      .filter((item): item is NonNullable<GuidedWorkflowProposal['unresolvedFields']>[number] => item !== null),
    reviewItems,
    preparationSteps: asStringArray(read(value, 'preparationSteps', 'preparation_steps')),
  };
}

function normalizeGuidedDraft(value: unknown): GuidedWorkflowDraft {
  if (!isRecord(value)) throw new TypeError('Guided draft is not an object.');
  const sourceMethod = asOptionalString(read(value, 'sourceMethod', 'source_method'));
  if (sourceMethod && !['PASTE', 'WEB_SEARCH', 'COMBINED', 'MANUAL'].includes(sourceMethod)) {
    throw new TypeError('Guided draft source method is unsupported.');
  }
  return {
    eventMetadata: read(value, 'eventMetadata', 'event_metadata')
      ? normalizeGuidedEventMetadata(read(value, 'eventMetadata', 'event_metadata'))
      : undefined,
    sourceMethod: sourceMethod as GuidedWorkflowDraft['sourceMethod'],
    searchQueries: asStringArray(read(value, 'searchQueries', 'search_queries')),
    intervention: read(value, 'intervention')
      ? normalizeGuidedIntervention(read(value, 'intervention'))
      : undefined,
    eventPackBuildId: asOptionalString(read(value, 'eventPackBuildId', 'event_pack_build_id')),
    eventPackId: asOptionalString(read(value, 'eventPackId', 'event_pack_id')),
    scenarioId: asOptionalString(read(value, 'scenarioId', 'scenario_id')),
    experimentId: asOptionalString(read(value, 'experimentId', 'experiment_id')),
  };
}

function normalizeGuidedMessage(value: unknown): GuidedWorkflowMessage {
  if (!isRecord(value)) throw new TypeError('Guided message is not an object.');
  const role = enumValue(read(value, 'role'), ['user', 'assistant'] as const, 'message.role');
  return {
    id: requiredString(read(value, 'id'), 'message.id'),
    role,
    stage: enumValue(read(value, 'stage'), GUIDED_STAGES, 'message.stage'),
    content: requiredString(read(value, 'content'), 'message.content'),
    proposalId: asOptionalString(read(value, 'proposalId', 'proposal_id')),
    createdAt: requiredString(read(value, 'createdAt', 'created_at'), 'message.createdAt'),
  };
}

function normalizeGuidedArchivedProposal(value: unknown): GuidedWorkflowArchivedProposal {
  if (!isRecord(value)) throw new TypeError('Guided archived proposal is not an object.');
  return {
    id: requiredString(read(value, 'id'), 'archivedProposal.id'),
    proposal: normalizeGuidedProposal(read(value, 'proposal')),
    status: requiredString(read(value, 'status'), 'archivedProposal.status'),
    archivedAt: requiredString(
      read(value, 'archivedAt', 'archived_at'),
      'archivedProposal.archivedAt',
    ),
    reason: asOptionalString(read(value, 'reason')),
  };
}

export function normalizeGuidedWorkflow(value: unknown): GuidedWorkflow {
  if (!isRecord(value)) throw new TypeError('Guided workflow is not an object.');
  const schemaVersion = requiredString(
    read(value, 'schemaVersion', 'schema_version'),
    'workflow.schemaVersion',
  );
  if (schemaVersion !== '1.0.0') throw new TypeError('Guided workflow schema is unsupported.');
  const language = enumValue(read(value, 'language'), ['en', 'zh-CN'] as const, 'language');
  const messages = read(value, 'messages');
  if (!Array.isArray(messages)) throw new TypeError('Guided workflow messages are invalid.');
  const pendingProposal = read(value, 'pendingProposal', 'pending_proposal');
  const archivedProposals = read(value, 'archivedProposals', 'archived_proposals');
  if (
    archivedProposals !== undefined
    && archivedProposals !== null
    && !Array.isArray(archivedProposals)
  ) {
    throw new TypeError('Guided archived proposals are invalid.');
  }
  return {
    schemaVersion,
    id: requiredString(read(value, 'id'), 'workflow.id'),
    stage: enumValue(read(value, 'stage'), GUIDED_STAGES, 'workflow.stage'),
    status: enumValue(
      read(value, 'status'),
      ['ACTIVE', 'COMPLETED', 'CANCELLED', 'ARCHIVED'] as const,
      'workflow.status',
    ),
    version: requiredNumber(read(value, 'version'), 'workflow.version', true),
    language,
    draft: normalizeGuidedDraft(read(value, 'draft')),
    pendingProposal: pendingProposal === undefined || pendingProposal === null
      ? undefined
      : normalizeGuidedProposal(pendingProposal),
    pendingProposalId: asOptionalString(
      read(value, 'pendingProposalId', 'pending_proposal_id'),
    ),
    archivedProposals: Array.isArray(archivedProposals)
      ? archivedProposals.map(normalizeGuidedArchivedProposal)
      : undefined,
    messages: messages.map(normalizeGuidedMessage),
    createdAt: requiredString(read(value, 'createdAt', 'created_at'), 'workflow.createdAt'),
    updatedAt: requiredString(read(value, 'updatedAt', 'updated_at'), 'workflow.updatedAt'),
  };
}

export function normalizeGuidedWorkflows(value: unknown): GuidedWorkflow[] {
  return unwrapItems(value).map(normalizeGuidedWorkflow);
}

const GUIDED_TURN_OPERATION_STATUSES = [
  'PENDING',
  'RESULT_READY',
  'SUCCEEDED',
  'UNKNOWN',
  'ABANDONED_BY_USER',
] as const;

const GUIDED_TURN_RECOVERY_ACTIONS = [
  'RETRY_CACHED_COMMIT',
  'ABANDON_AND_AUTHORIZE_RETRY',
] as const;

export function normalizeGuidedTurnOperation(value: unknown): GuidedTurnOperation {
  if (!isRecord(value)) throw new TypeError('Guided turn operation is not an object.');
  const schemaVersion = requiredString(
    read(value, 'schemaVersion', 'schema_version'),
    'operation.schemaVersion',
  );
  if (schemaVersion !== '1.0.0') {
    throw new TypeError('Guided turn operation schema is unsupported.');
  }
  const languageValue = asOptionalString(read(value, 'language'));
  if (languageValue && languageValue !== 'en' && languageValue !== 'zh-CN') {
    throw new TypeError('Guided turn operation language is unsupported.');
  }
  const recoveryOptionsValue = read(value, 'recoveryOptions', 'recovery_options');
  if (!Array.isArray(recoveryOptionsValue)) {
    throw new TypeError('Guided turn recovery options are invalid.');
  }
  const recoveryOptions = recoveryOptionsValue.map((item) => enumValue(
    item,
    GUIDED_TURN_RECOVERY_ACTIONS,
    'operation.recoveryOption',
  )) as GuidedTurnRecoveryAction[];
  return {
    schemaVersion,
    workflowId: requiredString(
      read(value, 'workflowId', 'workflow_id'),
      'operation.workflowId',
    ),
    clientRequestId: requiredString(
      read(value, 'clientRequestId', 'client_request_id'),
      'operation.clientRequestId',
    ),
    expectedVersion: requiredNumber(
      read(value, 'expectedVersion', 'expected_version'),
      'operation.expectedVersion',
      true,
    ),
    status: enumValue(
      read(value, 'status'),
      GUIDED_TURN_OPERATION_STATUSES,
      'operation.status',
    ),
    errorCode: asOptionalString(read(value, 'errorCode', 'error_code')),
    requestMessage: asOptionalString(read(value, 'requestMessage', 'request_message')),
    language: languageValue as GuidedTurnOperation['language'],
    cachedProposalAvailable: asBoolean(
      read(value, 'cachedProposalAvailable', 'cached_proposal_available'),
    ) ?? false,
    supersedesClientRequestId: asOptionalString(
      read(value, 'supersedesClientRequestId', 'supersedes_client_request_id'),
    ),
    authorizedRetryClientRequestId: asOptionalString(
      read(
        value,
        'authorizedRetryClientRequestId',
        'authorized_retry_client_request_id',
      ),
    ),
    recoveryOptions,
    providerRequestId: asOptionalString(
      read(value, 'providerRequestId', 'provider_request_id'),
    ),
    httpResponseReceived: asBoolean(
      read(value, 'httpResponseReceived', 'http_response_received'),
    ),
    usageReceived: asBoolean(read(value, 'usageReceived', 'usage_received')),
    parseCompleted: asBoolean(read(value, 'parseCompleted', 'parse_completed')),
    failureStage: asOptionalString(read(value, 'failureStage', 'failure_stage')),
    createdAt: requiredString(read(value, 'createdAt', 'created_at'), 'operation.createdAt'),
    updatedAt: requiredString(read(value, 'updatedAt', 'updated_at'), 'operation.updatedAt'),
  };
}

export function normalizeGuidedTurnOperations(value: unknown): GuidedTurnOperation[] {
  return unwrapItems(value).map(normalizeGuidedTurnOperation);
}

export function normalizeGuidedTurnRecoveryResult(
  value: unknown,
): GuidedTurnRecoveryResult {
  if (!isRecord(value)) throw new TypeError('Guided turn recovery response is not an object.');
  const kind = enumValue(read(value, 'kind'), ['WORKFLOW', 'OPERATION'] as const, 'kind');
  if (kind === 'WORKFLOW') {
    return {
      kind,
      workflow: normalizeGuidedWorkflow(read(value, 'workflow')),
    };
  }
  return {
    kind,
    operation: normalizeGuidedTurnOperation(read(value, 'operation')),
  };
}

export function normalizeAuthSession(value: unknown): AuthSession {
  if (!isRecord(value)) throw new TypeError('Authentication session response is not an object.');
  const authenticated = asBoolean(read(value, 'authenticated')) ?? false;
  const userValue = read(value, 'user');
  const user = userValue === undefined || userValue === null ? undefined : normalizeAuthUser(userValue);
  if (authenticated && !user) throw new TypeError('Authenticated session is missing its user.');
  const legalValue = read(value, 'legalAcceptance', 'legal_acceptance');
  const preferencesValue = read(value, 'preferences', 'userPreferences', 'user_preferences');
  return {
    authenticationRequired: asBoolean(
      read(value, 'authenticationRequired', 'authentication_required'),
    ) ?? true,
    authenticated,
    user,
    csrfToken: asOptionalString(read(value, 'csrfToken', 'csrf_token')),
    legalAcceptance: legalValue === undefined || legalValue === null
      ? undefined
      : normalizeLegalAcceptanceStatus(legalValue),
    preferences: preferencesValue === undefined || preferencesValue === null
      ? undefined
      : normalizeUserPreferences(preferencesValue),
  };
}

export function normalizeAccountSessions(value: unknown): AccountSession[] {
  if (!isRecord(value) || !Array.isArray(read(value, 'items'))) {
    throw new TypeError('Account session list is invalid.');
  }
  return (read(value, 'items') as unknown[]).map((item, index) => {
    if (!isRecord(item)) throw new TypeError(`Account session ${index} is invalid.`);
    return {
      id: requiredString(read(item, 'id'), `accountSession[${index}].id`),
      current: asBoolean(read(item, 'current')) ?? false,
      createdAt: requiredString(
        read(item, 'createdAt', 'created_at'),
        `accountSession[${index}].createdAt`,
      ),
      lastSeenAt: requiredString(
        read(item, 'lastSeenAt', 'last_seen_at'),
        `accountSession[${index}].lastSeenAt`,
      ),
      expiresAt: requiredString(
        read(item, 'expiresAt', 'expires_at'),
        `accountSession[${index}].expiresAt`,
      ),
    };
  });
}

export function normalizeAccountDataExport(value: unknown): AccountDataExport {
  if (!isRecord(value)) throw new TypeError('Account data export is not an object.');
  const rawData = read(value, 'data');
  if (!isRecord(rawData)) throw new TypeError('Account data export is missing its data object.');
  const data = Object.fromEntries(
    Object.entries(rawData).map(([key, rows]) => {
      if (!Array.isArray(rows)) {
        throw new TypeError(`Account data export section ${key} is not an array.`);
      }
      return [key, rows];
    }),
  );
  return {
    schemaVersion: requiredString(
      read(value, 'schemaVersion', 'schema_version'),
      'accountDataExport.schemaVersion',
    ),
    generatedAt: requiredString(
      read(value, 'generatedAt', 'generated_at'),
      'accountDataExport.generatedAt',
    ),
    retentionNotice: requiredString(
      read(value, 'retentionNotice', 'retention_notice'),
      'accountDataExport.retentionNotice',
    ),
    excludedSecrets: asStringArray(
      read(value, 'excludedSecrets', 'excluded_secrets'),
    ),
    data,
  };
}

export function normalizeAccountDeletionReceipt(value: unknown): AccountDeletionReceipt {
  if (!isRecord(value)) throw new TypeError('Account deletion receipt is not an object.');
  if (read(value, 'deleted') !== true) {
    throw new TypeError('Account deletion receipt did not confirm deletion.');
  }
  const deletedRecordCount = requiredNumber(
    read(value, 'deletedRecordCount', 'deleted_record_count'),
    'accountDeletion.deletedRecordCount',
    true,
  );
  if (deletedRecordCount < 0) {
    throw new TypeError('accountDeletion.deletedRecordCount must not be negative.');
  }
  return {
    deleted: true,
    deletedRecordCount,
    backupRetentionNotice: requiredString(
      read(value, 'backupRetentionNotice', 'backup_retention_notice'),
      'accountDeletion.backupRetentionNotice',
    ),
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
    fallbackToRules: asBoolean(read(value, 'fallbackToRules', 'fallback_to_rules')) ?? false,
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
    questionInterventionParameter: asParameter(
      read(value, 'questionInterventionParameter', 'question_intervention_parameter'),
    ),
    questionReviewMethod: (() => {
      const method = asOptionalString(read(value, 'questionReviewMethod', 'question_review_method'));
      return method === 'GENERATED_ALIGNED' || method === 'USER_CONFIRMED_UNCHANGED'
        ? method
        : undefined;
    })(),
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
  const confidenceComponentsValue = read(
    value,
    'confidenceComponents',
    'confidence_components',
  );
  const confidenceComponents = isRecord(confidenceComponentsValue)
    ? {
      textualFidelity: asNumber(
        read(confidenceComponentsValue, 'textualFidelity', 'textual_fidelity'),
      ),
      sourceTierStrength: asNumber(
        read(confidenceComponentsValue, 'sourceTierStrength', 'source_tier_strength'),
      ),
      timeBoundaryCertainty: asNumber(
        read(
          confidenceComponentsValue,
          'timeBoundaryCertainty',
          'time_boundary_certainty',
        ),
      ),
    }
    : undefined;
  const impactChannelRationale = unwrapItems(
    read(value, 'impactChannelRationale', 'impact_channel_rationale'),
  ).flatMap((item): ClaimImpactChannelRationale[] => {
    if (!isRecord(item)) return [];
    const channel = asOptionalString(read(item, 'channel'));
    const reason = asOptionalString(read(item, 'reason'));
    const evidenceType = asOptionalString(read(item, 'evidenceType', 'evidence_type'));
    const simulatorParameter = asOptionalString(
      read(item, 'simulatorParameter', 'simulator_parameter'),
    );
    if (!channel || !reason || !evidenceType || !simulatorParameter) return [];
    return [{
      channel,
      reason,
      reasonZh: asOptionalString(read(item, 'reasonZh', 'reason_zh')),
      evidenceType,
      simulatorParameter,
    }];
  });
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
    modelReportedConfidence: asNumber(
      read(value, 'modelReportedConfidence', 'model_reported_confidence'),
    ),
    confidenceMeaning: asOptionalString(read(value, 'confidenceMeaning', 'confidence_meaning')),
    confidenceComponents,
    impactChannels: asStringArray(read(value, 'impactChannels', 'impact_channels')),
    impactChannelRationale,
    channelMappingIsInference: asBoolean(
      read(value, 'channelMappingIsInference', 'channel_mapping_is_inference'),
    ),
    extractionQuality: asOptionalString(read(value, 'extractionQuality', 'extraction_quality')),
    bulkApprovalEligible: asBoolean(
      read(value, 'bulkApprovalEligible', 'bulk_approval_eligible'),
    ),
    bulkApprovalExclusionReasons: asStringArray(
      read(value, 'bulkApprovalExclusionReasons', 'bulk_approval_exclusion_reasons'),
    ),
    bulkApprovalMinimumConfidence: asNumber(
      read(value, 'bulkApprovalMinimumConfidence', 'bulk_approval_minimum_confidence'),
    ),
    editedText: asOptionalString(read(value, 'editedText', 'edited_text')),
    isRequired: asBoolean(read(value, 'isRequired', 'is_required')),
    claimType: asOptionalString(read(value, 'claimType', 'claim_type')),
  };
}

function normalizeCaseValidationStatus(
  value: unknown,
): CaseSummary['validationStatus'] {
  if (typeof value === 'string') {
    return { level: value };
  }
  if (!isRecord(value)) return undefined;
  const level = asOptionalString(read(value, 'level'));
  const empiricalCalibration = asOptionalString(
    read(value, 'empiricalCalibration', 'empirical_calibration'),
  );
  const claim = asOptionalString(read(value, 'claim'));
  if (!level && !empiricalCalibration && !claim) return undefined;
  return { level, empiricalCalibration, claim };
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
        instrument: asOptionalString(read(item, 'instrument')),
        status: asOptionalString(read(item, 'status')),
        eventPackReviewState: (() => {
          const state = asOptionalString(read(item, 'eventPackReviewState', 'event_pack_review_state'));
          return state === 'NOT_STARTED' || state === 'IN_PROGRESS' || state === 'FROZEN'
            ? state
            : undefined;
        })(),
        isSynthetic: asBoolean(read(item, 'synthetic', 'isSynthetic', 'is_synthetic')),
        syntheticLabel: asOptionalString(read(item, 'syntheticLabel')),
        syntheticLabelZh: asOptionalString(read(item, 'syntheticLabelZh')),
        updatedAt: asOptionalString(read(item, 'updatedAt', 'updated_at')),
        featured: asBoolean(read(item, 'featured')),
        caseRole: asOptionalString(read(item, 'caseRole', 'case_role')),
        validationStatus: normalizeCaseValidationStatus(
          read(item, 'validationStatus', 'validation_status'),
        ),
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
      riskCategory: asOptionalString(read(item, 'riskCategory', 'risk_category')),
      recommendedAction: asOptionalString(
        read(item, 'recommendedAction', 'recommended_action'),
      ),
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
  const modelInputSummaryValue = read(value, 'modelInputSummary', 'model_input_summary');
  const modelInputSummary = isRecord(modelInputSummaryValue)
    ? {
      retainedFieldCount: asNumber(
        read(modelInputSummaryValue, 'retainedFieldCount', 'retained_field_count'),
      ) ?? 0,
      removedFieldCount: asNumber(
        read(modelInputSummaryValue, 'removedFieldCount', 'removed_field_count'),
      ) ?? 0,
      redactedFieldCount: asNumber(
        read(modelInputSummaryValue, 'redactedFieldCount', 'redacted_field_count'),
      ) ?? 0,
    }
    : undefined;
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
    modelInputSummary,
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
    code: asOptionalString(read(value, 'code')),
    parameters: isRecord(read(value, 'parameters')) ? read(value, 'parameters') as Record<string, unknown> : undefined,
  };
}

function normalizeCognitionProgress(value: unknown) {
  if (!isRecord(value)) return undefined;
  const rawFailureCategoryCounts = read(
    value,
    'failureCategoryCounts',
    'failure_category_counts',
  );
  const failureCategoryCounts = isRecord(rawFailureCategoryCounts)
    ? Object.fromEntries(
      Object.entries(rawFailureCategoryCounts).flatMap(([name, count]) => {
        const normalizedCount = asNumber(count);
        return normalizedCount !== undefined && normalizedCount >= 0
          ? [[name, normalizedCount]]
          : [];
      }),
    )
    : undefined;
  return {
    status: asOptionalString(read(value, 'status')),
    plannedCalls: asNumber(read(value, 'plannedCalls', 'planned_calls')),
    attemptedCalls: asNumber(read(value, 'attemptedCalls', 'attempted_calls')),
    completedCalls: asNumber(read(value, 'completedCalls', 'completed_calls')),
    fallbackCount: asNumber(read(value, 'fallbackCount', 'fallback_count')),
    totalTokens: asNumber(read(value, 'totalTokens', 'total_tokens')),
    structuredValidCalls: asNumber(
      read(value, 'structuredValidCalls', 'structured_valid_calls'),
    ),
    structuredSuccessRate: asNumber(
      read(value, 'structuredSuccessRate', 'structured_success_rate'),
    ),
    structuredSuccessThreshold: asNumber(
      read(value, 'structuredSuccessThreshold', 'structured_success_threshold'),
    ),
    structuredSuccessGateStatus: asOptionalString(
      read(value, 'structuredSuccessGateStatus', 'structured_success_gate_status'),
    ),
    failureCategoryCounts,
    currentCostUsd: asNumber(read(value, 'currentCostUsd', 'current_cost_usd')),
    settledCostUsd: asNumber(read(value, 'settledCostUsd', 'settled_cost_usd')),
    activeReservationUsd: asNumber(
      read(value, 'activeReservationUsd', 'active_reservation_usd'),
    ),
    modelStage: asOptionalString(read(value, 'modelStage', 'model_stage')),
    streamChunkCount: asNumber(read(value, 'streamChunkCount', 'stream_chunk_count')),
    answerChunkCount: asNumber(read(value, 'answerChunkCount', 'answer_chunk_count')),
    reasoningChunkCount: asNumber(
      read(value, 'reasoningChunkCount', 'reasoning_chunk_count'),
    ),
    repairAttempted: asBoolean(read(value, 'repairAttempted', 'repair_attempted')),
    decisionRound: asNumber(read(value, 'decisionRound', 'decision_round')),
    representativeIndex: asNumber(read(value, 'representativeIndex', 'representative_index')),
    failureCode: asOptionalString(read(value, 'failureCode', 'failure_code')),
    resolvedMode: asOptionalString(read(value, 'resolvedMode', 'resolved_mode')),
    userRequestedRuleContinuation: asBoolean(
      read(value, 'userRequestedRuleContinuation', 'user_requested_rule_continuation'),
    ),
    updatedAt: asOptionalString(read(value, 'updatedAt', 'updated_at')),
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
    cognitionFallbackRequested: asBoolean(
      read(value, 'cognitionFallbackRequested', 'cognition_fallback_requested'),
    ),
    progress,
    completedSeeds,
    validSeeds: completedSeeds,
    totalSeeds,
    currentSeed: asNumber(read(value, 'currentSeed', 'current_seed'))
      ?? asNumber(read(runtime, 'currentSeed', 'current_seed')),
    lastCompletedSeed: asNumber(read(value, 'lastCompletedSeed', 'last_completed_seed'))
      ?? asNumber(read(runtime, 'lastCompletedSeed', 'last_completed_seed')),
    error: asOptionalString(read(value, 'errorCode', 'error_code', 'error', 'errorMessage', 'error_message')),
    scenario: request,
    intervention: request?.intervention ?? normalizeIntervention(read(value, 'intervention')),
    liveState: Object.keys(runtime).length > 0 ? {
      phase: asOptionalString(read(runtime, 'phase')),
      pairIndex: asNumber(read(runtime, 'pairIndex', 'pair_index')),
      currentSeed: asNumber(read(runtime, 'currentSeed', 'current_seed')),
      lastCompletedSeed: asNumber(read(runtime, 'lastCompletedSeed', 'last_completed_seed')),
      baseline: normalizeLiveMarketSnapshot(read(runtime, 'baseline')),
      intervention: normalizeLiveMarketSnapshot(read(runtime, 'intervention')),
      resumedFromCheckpoint: asBoolean(read(runtime, 'resumedFromCheckpoint', 'resumed_from_checkpoint')),
      checkpointPairs: asNumber(read(runtime, 'checkpointPairs', 'checkpoint_pairs')),
      cognitionProgress: normalizeCognitionProgress(read(runtime, 'cognitionProgress', 'cognition_progress')),
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
  const conditionEvaluations = unwrapItems(
    read(value, 'conditionEvaluations', 'condition_evaluations'),
  ).flatMap((item) => {
    if (!isRecord(item)) return [];
    const code = asOptionalString(read(item, 'code'));
    const evaluationOrder = asNumber(
      read(item, 'evaluationOrder', 'evaluation_order'),
    );
    if (!code || evaluationOrder === undefined) return [];
    return [{
      code,
      evaluationOrder,
      satisfied: asBoolean(read(item, 'satisfied')) ?? false,
      firstSatisfiedAtPair: asNumber(
        read(item, 'firstSatisfiedAtPair', 'first_satisfied_at_pair'),
      ),
    }];
  });
  const reason = asString(read(value, 'reason'), 'NOT_REPORTED');
  const reasons = asStringArray(read(value, 'reasons'));
  return {
    mode: asOptionalString(read(value, 'mode')),
    triggered: asBoolean(read(value, 'triggered')) ?? false,
    reason,
    primaryReason: asOptionalString(read(value, 'primaryReason', 'primary_reason')),
    reasons: reasons.length > 0 ? reasons : [reason],
    primaryOutcome: asOptionalString(read(value, 'primaryOutcome', 'primary_outcome')),
    completedPairs: asNumber(read(value, 'completedPairs', 'completed_pairs')) ?? 0,
    observedCiHalfWidth: asNumber(read(value, 'observedCiHalfWidth', 'observed_ci_half_width')),
    targetCiHalfWidth: asNumber(read(value, 'targetCiHalfWidth', 'target_ci_half_width')),
    minimumPairs: asNumber(read(value, 'minimumPairs', 'minimum_pairs')),
    maximumPairs: asNumber(read(value, 'maximumPairs', 'maximum_pairs')),
    conditionEvaluations,
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
    globalSequence: asNumber(read(value, 'globalSequence', 'global_sequence')),
    step: asNumber(read(value, 'step')),
    phase: asOptionalString(read(value, 'phase')),
    phaseSequence: asNumber(read(value, 'phaseSequence', 'phase_sequence')),
    time: asOptionalString(read(value, 'time', 'timestamp')),
    kind: eventType,
    title: eventType,
    summary: asOptionalString(read(value, 'summary', 'detail', 'description')),
    summaryZh: asOptionalString(read(value, 'summaryZh', 'summary_zh')),
    sourceId: asOptionalString(read(payload, 'sourceId', 'source_id')),
    agentId: asOptionalString(
      read(value, 'agentId', 'agent_id')
      ?? read(payload, 'agentId', 'agent_id'),
    ),
    orderId: asOptionalString(read(payload, 'orderId', 'order_id')),
    metricContribution: asNumber(read(payload, 'metricContribution', 'metric_contribution')),
    methodNote: asOptionalString(read(payload, 'methodNote', 'method_note')),
    scenario: asOptionalString(read(value, 'scenario')),
    seed: asNumber(read(value, 'seed')),
    parentId: asOptionalString(
      read(value, 'parentTraceId', 'parent_trace_id', 'parentId', 'parent_id')
      ?? read(payload, 'parentTraceId', 'parent_trace_id', 'parentId', 'parent_id'),
    ),
    sourceLayer: asOptionalString(read(value, 'sourceLayer', 'source_layer')),
    isInterventionDifference: asBoolean(
      read(value, 'isInterventionDifference', 'is_intervention_difference'),
    ),
    payload,
  };
}

function normalizeOrderExecutionSummary(value: unknown): OrderExecutionSummary | null {
  if (!isRecord(value)) return null;
  const orderId = asOptionalString(read(value, 'orderId', 'order_id'));
  if (!orderId) return null;
  return {
    orderId,
    orderTraceId: asOptionalString(read(value, 'orderTraceId', 'order_trace_id')),
    agentId: asOptionalString(read(value, 'agentId', 'agent_id')),
    side: asOptionalString(read(value, 'side')),
    submissionStep: asNumber(read(value, 'submissionStep', 'submission_step')),
    submissionSequence: asNumber(read(value, 'submissionSequence', 'submission_sequence')),
    timeInForce: asOptionalString(read(value, 'timeInForce', 'time_in_force')),
    limitPriceTicks: asNumber(read(value, 'limitPriceTicks', 'limit_price_ticks')),
    limitPrice: asNumber(read(value, 'limitPrice', 'limit_price')),
    requestedQuantity: asNumber(read(value, 'requestedQuantity', 'requested_quantity')),
    approvedQuantity: asNumber(read(value, 'approvedQuantity', 'approved_quantity')),
    unapprovedQuantity: asNumber(read(value, 'unapprovedQuantity', 'unapproved_quantity')),
    cumulativeFilledQuantity: asNumber(
      read(value, 'cumulativeFilledQuantity', 'cumulative_filled_quantity'),
    ),
    remainingQuantity: asNumber(read(value, 'remainingQuantity', 'remaining_quantity')),
    vwapPriceTicks: asNumber(read(value, 'vwapPriceTicks', 'vwap_price_ticks')),
    vwapPrice: asNumber(read(value, 'vwapPrice', 'vwap_price')),
    fillCount: asNumber(read(value, 'fillCount', 'fill_count')),
    tradeIds: asStringArray(read(value, 'tradeIds', 'trade_ids')),
    tradeTraceIds: asStringArray(read(value, 'tradeTraceIds', 'trade_trace_ids')),
    riskDecision: asOptionalString(read(value, 'riskDecision', 'risk_decision')),
    finalStatus: asOptionalString(read(value, 'finalStatus', 'final_status')),
    terminal: asBoolean(read(value, 'terminal')),
    closure: asOptionalString(read(value, 'closure')),
    scenario: asOptionalString(read(value, 'scenario')),
    seed: asNumber(read(value, 'seed')),
    isInterventionDifference: asBoolean(
      read(value, 'isInterventionDifference', 'is_intervention_difference'),
    ),
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

function normalizeResultSourceSummary(value: unknown): ExperimentResults['sourceSummary'] {
  if (!isRecord(value)) return undefined;
  return {
    eventPackId: asOptionalString(read(value, 'id', 'eventPackId', 'event_pack_id')),
    title: asOptionalString(read(value, 'title', 'name')),
    titleZh: asOptionalString(read(value, 'titleZh', 'title_zh', 'nameZh', 'name_zh')),
    asOf: asOptionalString(read(value, 'asOf', 'as_of', 'pointInTime', 'point_in_time')),
    frozenAt: asOptionalString(read(value, 'frozenAt', 'frozen_at')),
    sourceCount: unwrapItems(read(value, 'sources')).length,
    claimCount: unwrapItems(read(value, 'claims')).length,
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
    question: asOptionalString(read(value, 'question')),
    questionZh: asOptionalString(read(value, 'questionZh', 'question_zh')),
    generatedAt: manifest.generatedAt,
    validSeedCount: manifest.validSeedCount ?? pairedSeeds.length,
    sourceSummary: normalizeResultSourceSummary(read(value, 'eventPackManifest', 'event_pack_manifest')),
    scenarioDiff: normalizeIntervention(read(value, 'scenarioDiff', 'scenario_diff')),
    metrics: normalizeMetricSummaries(read(value, 'metricSummaries', 'metric_summaries')),
    pairedSeeds,
    distribution: buildHistogram(pairedSeeds),
    marketPaths: normalizeMedianPaths(read(value, 'medianPaths', 'median_paths')),
    agentFlows: normalizeAgentFlows(read(value, 'agentFlows', 'agent_flows')),
    agentPnl: normalizeAgentPnl(read(value, 'agentPnl', 'agent_pnl')),
    traces: unwrapItems(read(value, 'traces', 'trace')).map(normalizeTrace).filter((item): item is TraceNode => item !== null),
    orderExecutionSummary: unwrapItems(
      read(value, 'orderExecutionSummary', 'order_execution_summary'),
    ).map(normalizeOrderExecutionSummary).filter(
      (item): item is OrderExecutionSummary => item !== null,
    ),
    strongestMetricIds: asStringArray(
      read(value, 'strongestMetricIds', 'strongest_metric_ids'),
    ),
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
  const rawSemanticValidationStatus = read(
    value,
    'semanticValidationStatus',
    'semantic_validation_status',
  );
  const semanticValidationStatuses = [
    'PASSED',
    'REPAIRED',
    'COMPLETED_WITH_WARNINGS',
    'DETERMINISTIC_FALLBACK',
    'NOT_RECORDED',
  ] as const;
  const semanticValidationStatus = typeof rawSemanticValidationStatus === 'string'
    && semanticValidationStatuses.includes(
      rawSemanticValidationStatus as (typeof semanticValidationStatuses)[number],
    )
    ? rawSemanticValidationStatus as (typeof semanticValidationStatuses)[number]
    : undefined;
  if (rawSemanticValidationStatus !== undefined && semanticValidationStatus === undefined) {
    throw new TypeError('Result interpretation message has an invalid semanticValidationStatus.');
  }
  const rawDeterministicFallbackUsed = read(
    value,
    'deterministicFallbackUsed',
    'deterministic_fallback_used',
  );
  if (rawDeterministicFallbackUsed !== undefined
    && typeof rawDeterministicFallbackUsed !== 'boolean') {
    throw new TypeError('Result interpretation message has an invalid deterministicFallbackUsed.');
  }
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
    semanticValidationStatus,
    deterministicFallbackUsed: rawDeterministicFallbackUsed as boolean | undefined,
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
  const failureStage = asOptionalString(read(value, 'failureStage', 'failure_stage'))?.trim();
  const billingConclusion = asOptionalString(
    read(value, 'billingConclusion', 'billing_conclusion'),
  )?.trim();
  return {
    code,
    message,
    retryable,
    httpStatus,
    uncertainBillableAttempts,
    failureStage: failureStage || undefined,
    repairAttempted: asBoolean(read(value, 'repairAttempted', 'repair_attempted')),
    repairUsed: asBoolean(read(value, 'repairUsed', 'repair_used')),
    billingConclusion: billingConclusion || undefined,
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
  const explicitCheckIds = new Set(explicitChecks.map((item) => item.id));
  // 结构化 checks 与顶层 errors/warnings 承载不同信息。尤其是机制禁用只出现在
  // errors，不能因为响应同时包含 checks 就丢失这个可操作的失败原因。
  const checks = explicitChecks.length > 0
    ? [
        ...explicitChecks,
        ...errors.filter((item) => !explicitCheckIds.has(item.id)),
        ...warnings.filter((item) => !explicitCheckIds.has(item.id)),
      ]
    : [...errors, ...warnings];
  const valid = asBoolean(read(value, 'valid')) ?? errors.length === 0;
  const rawCheckpointCapacity = read(
    value,
    'checkpointCapacity',
    'checkpoint_capacity',
  );
  const checkpointCapacity = isRecord(rawCheckpointCapacity)
    ? {
        sampleCount: asNumber(read(rawCheckpointCapacity, 'sampleCount', 'sample_count')) ?? 0,
        confidence: asOptionalString(read(rawCheckpointCapacity, 'confidence')) ?? 'LOW',
        estimatedStoredBytes: asNumber(
          read(rawCheckpointCapacity, 'estimatedStoredBytes', 'estimated_stored_bytes'),
        ),
        estimatedPairStoredBytes: asNumber(
          read(rawCheckpointCapacity, 'estimatedPairStoredBytes', 'estimated_pair_stored_bytes'),
        ),
        warning: asBoolean(read(rawCheckpointCapacity, 'warning')) ?? false,
      }
    : undefined;
  return {
    valid,
    simulationRunnable: asBoolean(
      read(value, 'simulationRunnable', 'simulation_runnable'),
    ) ?? valid,
    requestedCognitionRunnable: asBoolean(
      read(value, 'requestedCognitionRunnable', 'requested_cognition_runnable'),
    ) ?? valid,
    effectiveCognitionMode: asOptionalString(
      read(value, 'effectiveCognitionMode', 'effective_cognition_mode'),
    ),
    degradationReasons: asStringArray(
      read(value, 'degradationReasons', 'degradation_reasons'),
    ),
    requiresExplicitRuleFallbackConfirmation: asBoolean(
      read(
        value,
        'requiresExplicitRuleFallbackConfirmation',
        'requires_explicit_rule_fallback_confirmation',
      ),
    ) ?? false,
    checks,
    estimatedRuntimeSeconds: asNumber(read(value, 'estimatedRuntimeSeconds', 'estimated_runtime_seconds')),
    estimatedLlmCalls: asNumber(read(value, 'estimatedLlmCalls', 'estimated_llm_calls')),
    estimatedRuns: asNumber(read(value, 'estimatedRuns', 'estimated_runs')),
    llmCostCapUsd: asNumber(read(value, 'llmCostCapUsd', 'llm_cost_cap_usd')),
    llmPricingStatus: asOptionalString(read(value, 'llmPricingStatus', 'llm_pricing_status')),
    llmMinimumCallReservationUsd: asNumber(read(value, 'llmMinimumCallReservationUsd', 'llm_minimum_call_reservation_usd')),
    checkpointCapacity,
    interpretationBoundary: asOptionalString(read(value, 'interpretationBoundary', 'interpretation_boundary')),
    warnings: warnings.map((item) => item.detail ?? item.label),
  };
}

export function normalizeLlmCatalog(value: unknown): LlmCatalog {
  if (!isRecord(value)) throw new TypeError('Model catalog response is not an object.');

  const advancedParameterNames = new Set<AdvancedModelParameterName>([
    'temperature',
    'topP',
    'presencePenalty',
    'frequencyPenalty',
    'seed',
    'timeoutSeconds',
  ]);

  const normalizeAdvancedParameterNames = (
    parameterValue: unknown,
  ): AdvancedModelParameterName[] | undefined => {
    if (parameterValue === undefined || parameterValue === null) return undefined;
    return unwrapItems(parameterValue).flatMap((item) => {
      const name = asOptionalString(item);
      return name && advancedParameterNames.has(name as AdvancedModelParameterName)
        ? [name as AdvancedModelParameterName]
        : [];
    });
  };

  const normalizeModels = (modelValue: unknown, fallbackProvider: LlmProviderId): LlmModelDescriptor[] => (
    unwrapItems(modelValue).flatMap((item) => {
    if (!isRecord(item)) return [];
    const id = asString(read(item, 'id', 'modelId', 'model_id'));
    const name = asString(read(item, 'name', 'displayName', 'display_name'));
    const contextTokens = asNumber(read(item, 'contextTokens', 'context_tokens'));
    const maxOutputTokens = asNumber(read(item, 'maxOutputTokens', 'max_output_tokens'));
    const validationValue = read(item, 'validationEvidence', 'validation_evidence');
    const validation = isRecord(validationValue) ? validationValue : undefined;
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
      pricingStatus: ((): LlmModelDescriptor['pricingStatus'] => {
        const status = asString(
          read(item, 'pricingStatus', 'pricing_status'),
          'UNAVAILABLE_FAIL_CLOSED',
        );
        return status === 'VERIFIED_UPPER_BOUND' || status === 'STALE_FAIL_CLOSED'
          ? status
          : 'UNAVAILABLE_FAIL_CLOSED';
      })(),
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
      pricingValidUntil: asOptionalString(
        read(item, 'pricingValidUntil', 'pricing_valid_until'),
      ),
      pricingNote: asOptionalString(read(item, 'pricingNote', 'pricing_note')),
      validationEvidence: validation ? {
        knownModel: asBoolean(read(validation, 'knownModel', 'known_model')) ?? false,
        officialDocumentationStatus: asString(
          read(validation, 'officialDocumentationStatus', 'official_documentation_status'),
          'UNVERIFIED',
        ),
        adapterContractStatus: asString(
          read(validation, 'adapterContractStatus', 'adapter_contract_status'),
          'NOT_RUN',
        ),
        liveKeyE2eStatus: asString(
          read(validation, 'liveKeyE2eStatus', 'live_key_e2e_status'),
          'NOT_RUN',
        ),
        structuredOutputStatus: asString(
          read(validation, 'structuredOutputStatus', 'structured_output_status'),
          'UNVERIFIED',
        ),
        streamingStatus: asString(
          read(validation, 'streamingStatus', 'streaming_status'),
          'UNVERIFIED',
        ),
        thinkingJsonStatus: asString(
          read(validation, 'thinkingJsonStatus', 'thinking_json_status'),
          'UNVERIFIED',
        ),
        usageCostStatus: asString(
          read(validation, 'usageCostStatus', 'usage_cost_status'),
          'UNVERIFIED',
        ),
        evidenceSourceUrl: asOptionalString(
          read(validation, 'evidenceSourceUrl', 'evidence_source_url'),
        ),
        verifiedAt: asOptionalString(read(validation, 'verifiedAt', 'verified_at')),
        verificationScope: asString(
          read(validation, 'verificationScope', 'verification_scope'),
          'UNKNOWN_MODEL_UNVERIFIED',
        ),
      } : undefined,
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
      supportedAdvancedParameters: normalizeAdvancedParameterNames(
        read(item, 'supportedAdvancedParameters', 'supported_advanced_parameters'),
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
      supportedAdvancedParameters: normalizeAdvancedParameterNames(
        read(value, 'supportedAdvancedParameters', 'supported_advanced_parameters'),
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
    pricingSnapshotStatus: asOptionalString(
      read(value, 'pricingSnapshotStatus', 'pricing_snapshot_status'),
    ),
    pricingSnapshotValidUntil: asOptionalString(
      read(value, 'pricingSnapshotValidUntil', 'pricing_snapshot_valid_until'),
    ),
    pricingReviewCadenceDays: asNumber(
      read(value, 'pricingReviewCadenceDays', 'pricing_review_cadence_days'),
    ),
    capabilitySnapshotVersion: asOptionalString(
      read(value, 'capabilitySnapshotVersion', 'capability_snapshot_version'),
    ),
    capabilitySnapshotStatus: asOptionalString(
      read(value, 'capabilitySnapshotStatus', 'capability_snapshot_status'),
    ),
    capabilitySnapshotValidUntil: asOptionalString(
      read(value, 'capabilitySnapshotValidUntil', 'capability_snapshot_valid_until'),
    ),
    capabilityReviewCadenceDays: asNumber(
      read(value, 'capabilityReviewCadenceDays', 'capability_review_cadence_days'),
    ),
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
  const advancedValue = read(value, 'advancedParameters', 'advanced_parameters');
  const advancedRecord = isRecord(advancedValue) ? advancedValue : {};
  const advancedParameters: AdvancedModelParameters = {
    temperature: asNumber(read(advancedRecord, 'temperature')),
    topP: asNumber(read(advancedRecord, 'topP', 'top_p')),
    presencePenalty: asNumber(read(advancedRecord, 'presencePenalty', 'presence_penalty')),
    frequencyPenalty: asNumber(read(advancedRecord, 'frequencyPenalty', 'frequency_penalty')),
    seed: asNumber(read(advancedRecord, 'seed')),
    timeoutSeconds: asNumber(read(advancedRecord, 'timeoutSeconds', 'timeout_seconds')),
  };
  return {
    configured: asBoolean(read(value, 'configured')) ?? false,
    credentialStatus: asOptionalString(
      read(value, 'credentialStatus', 'credential_status'),
    ) as LlmConfigView['credentialStatus'],
    provider: asLlmProviderId(read(value, 'provider')),
    model: asOptionalString(read(value, 'model')),
    thinkingEnabled: asBoolean(read(value, 'thinkingEnabled', 'thinking_enabled')),
    maxTokens: asNumber(read(value, 'maxTokens', 'max_tokens')),
    advancedParameters,
    credentialHint: normalizeCredentialHint(read(value, 'credentialHint', 'credential_hint')),
    credentialSource: (() => {
      const source = asOptionalString(read(value, 'credentialSource', 'credential_source'));
      return source === 'SESSION' || source === 'ADMIN_SERVER_ENCRYPTED' ? source : undefined;
    })(),
    expiresAt: asOptionalString(read(value, 'expiresAt', 'expires_at')),
    absoluteExpiresAt: asOptionalString(
      read(value, 'absoluteExpiresAt', 'absolute_expires_at'),
    ),
  };
}

export function normalizeAdminLlmCredential(value: unknown): AdminLlmCredentialView {
  if (!isRecord(value)) {
    throw new TypeError('Administrator model credential response is not an object.');
  }
  const advancedValue = read(value, 'advancedParameters', 'advanced_parameters');
  const advancedRecord = isRecord(advancedValue) ? advancedValue : {};
  const configured = asBoolean(read(value, 'configured')) ?? false;
  const storageScope = asOptionalString(read(value, 'storageScope', 'storage_scope'));
  if (storageScope !== 'ADMIN_SERVER_ENCRYPTED') {
    throw new TypeError('Administrator model credential storage scope is invalid.');
  }
  return {
    available: asBoolean(read(value, 'available')) ?? false,
    configured,
    storageScope,
    provider: asLlmProviderId(read(value, 'provider')),
    model: asOptionalString(read(value, 'model')),
    thinkingEnabled: asBoolean(read(value, 'thinkingEnabled', 'thinking_enabled')),
    maxTokens: asNumber(read(value, 'maxTokens', 'max_tokens')),
    advancedParameters: {
      temperature: asNumber(read(advancedRecord, 'temperature')),
      topP: asNumber(read(advancedRecord, 'topP', 'top_p')),
      presencePenalty: asNumber(read(advancedRecord, 'presencePenalty', 'presence_penalty')),
      frequencyPenalty: asNumber(read(advancedRecord, 'frequencyPenalty', 'frequency_penalty')),
      seed: asNumber(read(advancedRecord, 'seed')),
      timeoutSeconds: asNumber(read(advancedRecord, 'timeoutSeconds', 'timeout_seconds')),
    },
    credentialHint: normalizeCredentialHint(read(value, 'credentialHint', 'credential_hint')),
    persistedAt: asOptionalString(read(value, 'persistedAt', 'persisted_at')),
    updatedAt: asOptionalString(read(value, 'updatedAt', 'updated_at')),
  };
}

function normalizeCredentialHint(value: unknown): string | undefined {
  const hint = asOptionalString(value);
  // API 只能展示四个固定掩码字符和最多四位 ASCII 后缀；任何异常响应都
  // 失败关闭为不显示，避免后端回归时把完整凭据误当作 hint 渲染。
  return hint && /^••••[A-Za-z0-9_-]{4}$/.test(hint) ? hint : undefined;
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
  const rawFailureCategoryCounts = read(
    record,
    'failure_category_counts',
    'failureCategoryCounts',
  );
  const failureCategoryCounts = isRecord(rawFailureCategoryCounts)
    ? Object.fromEntries(
      Object.entries(rawFailureCategoryCounts).flatMap(([name, count]) => {
        const normalizedCount = asNumber(count);
        return normalizedCount !== undefined && normalizedCount >= 0
          ? [[name, normalizedCount]]
          : [];
      }),
    )
    : {};
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
    structuredSuccesses: asNumber(
      read(record, 'structured_successes', 'structuredSuccesses'),
    ) ?? 0,
    structuredSuccessRate: asNumber(
      read(record, 'structured_success_rate', 'structuredSuccessRate'),
    ) ?? 0,
    structuredSuccessThreshold: asNumber(
      read(record, 'structured_success_threshold', 'structuredSuccessThreshold'),
    ) ?? 0.95,
    structuredSuccessGateStatus: asString(
      read(record, 'structured_success_gate_status', 'structuredSuccessGateStatus'),
      'NOT_EVALUATED',
    ),
    failureCategoryCounts,
    observationScope: asString(
      read(record, 'observation_scope', 'observationScope'),
      'PROCESS_LOCAL',
    ),
    observedSince: asOptionalString(read(record, 'observed_since', 'observedSince')),
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

function normalizeDeploymentCheckStatus(value: unknown): DeploymentCheckStatus {
  const status = asString(value, 'UNKNOWN');
  return ['PASS', 'FAIL', 'PENDING', 'UNKNOWN'].includes(status)
    ? status as DeploymentCheckStatus
    : 'UNKNOWN';
}

export function normalizeDeploymentStatus(value: unknown): DeploymentStatus {
  if (!isRecord(value)) throw new TypeError('Deployment status response is not an object.');
  const requiredChecks = unwrapItems(read(value, 'requiredChecks', 'required_checks'))
    .flatMap((item) => {
      if (!isRecord(item)) return [];
      const name = asOptionalString(read(item, 'name'));
      if (!name) return [];
      return [{
        name,
        status: normalizeDeploymentCheckStatus(read(item, 'status')),
        completedAt: asOptionalString(read(item, 'completedAt', 'completed_at')),
      }];
    });
  const requiredChecksStatusValue = asString(
    read(value, 'requiredChecksStatus', 'required_checks_status'),
    'UNKNOWN',
  );
  const lastSyncResultValue = asString(
    read(value, 'lastSyncResult', 'last_sync_result'),
    'UNKNOWN',
  );
  return {
    schemaVersion: asString(read(value, 'schemaVersion', 'schema_version'), '1.0.0'),
    deployedCommit: asString(read(value, 'deployedCommit', 'deployed_commit'), 'unknown'),
    healthCommit: asString(read(value, 'healthCommit', 'health_commit'), 'unknown'),
    reportedDeployedCommit: asOptionalString(
      read(value, 'reportedDeployedCommit', 'reported_deployed_commit'),
    ),
    githubMainCommit: asOptionalString(
      read(value, 'githubMainCommit', 'github_main_commit'),
    ),
    branch: asOptionalString(read(value, 'branch')),
    commitAlignment: asString(
      read(value, 'commitAlignment', 'commit_alignment'),
      'HEALTH_ONLY',
    ),
    requiredChecks,
    requiredChecksStatus: [
      'PASS',
      'FAIL',
      'PENDING',
      'UNKNOWN',
      'INCOMPLETE',
    ].includes(requiredChecksStatusValue)
      ? requiredChecksStatusValue as DeploymentStatus['requiredChecksStatus']
      : 'UNKNOWN',
    lastSyncAt: asOptionalString(read(value, 'lastSyncAt', 'last_sync_at')),
    lastSyncResult: [
      'SUCCEEDED',
      'FAILED',
      'PENDING',
      'NOT_RUN',
      'UNKNOWN',
    ].includes(lastSyncResultValue)
      ? lastSyncResultValue as DeploymentStatus['lastSyncResult']
      : 'UNKNOWN',
    lastDeployAt: asOptionalString(read(value, 'lastDeployAt', 'last_deploy_at')),
    lastFailureAt: asOptionalString(read(value, 'lastFailureAt', 'last_failure_at')),
    lastFailureCode: asOptionalString(
      read(value, 'lastFailureCode', 'last_failure_code'),
    ),
    evidenceObservedAt: asOptionalString(
      read(value, 'evidenceObservedAt', 'evidence_observed_at'),
    ),
    statusSource: asString(
      read(value, 'statusSource', 'status_source'),
      'RELEASE_ENVIRONMENT_ONLY',
    ),
    statusFileState: asString(
      read(value, 'statusFileState', 'status_file_state'),
      'NOT_CONFIGURED',
    ),
    statusErrorCode: asOptionalString(
      read(value, 'statusErrorCode', 'status_error_code'),
    ),
    observedAt: asString(read(value, 'observedAt', 'observed_at')),
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
  const rawCategoryCounts = read(
    report,
    'blockerCategoryCounts',
    'blocker_category_counts',
  );
  const blockerCategoryCounts = isRecord(rawCategoryCounts)
    ? Object.fromEntries(
      Object.entries(rawCategoryCounts).flatMap(([name, count]) => {
        const normalizedCount = asNumber(count);
        return normalizedCount !== undefined && normalizedCount >= 0
          ? [[name, normalizedCount]]
          : [];
      }),
    )
    : {};
  return {
    releaseId: asString(read(report, 'releaseId', 'release_id')),
    evaluatedAt: asOptionalString(read(report, 'evaluatedAt', 'evaluated_at')),
    decision: asString(read(report, 'decision'), 'BLOCKED'),
    canRelease: asBoolean(read(report, 'canRelease', 'can_release')) ?? false,
    inventoryHash: asString(read(report, 'inventoryHash', 'inventory_hash')),
    humanEvidenceComplete: asBoolean(read(report, 'humanEvidenceComplete', 'human_evidence_complete')) ?? false,
    blockerGateIds: asStringArray(read(report, 'blockerGateIds', 'blocker_gate_ids')),
    blockerCategoryCounts,
    blockerSummaries: unwrapItems(
      read(report, 'blockerSummaries', 'blocker_summaries'),
    ).flatMap((item) => {
      if (!isRecord(item)) return [];
      const gateId = asOptionalString(read(item, 'gateId', 'gate_id'));
      if (!gateId) return [];
      return [{
        gateId,
        category: asString(read(item, 'category'), 'UNCLASSIFIED'),
        status: asString(read(item, 'status'), 'NOT_EVALUATED'),
        owner: asString(read(item, 'owner'), 'Unassigned'),
        requiredEvidence: asString(
          read(item, 'requiredEvidence', 'required_evidence'),
        ),
        evidenceIds: asStringArray(read(item, 'evidenceIds', 'evidence_ids')),
        actionTarget: asString(
          read(item, 'actionTarget', 'action_target'),
          `#gate-${gateId}`,
        ),
      }];
    }),
    useCaseAxes: unwrapItems(read(report, 'useCaseAxes', 'use_case_axes')).flatMap(
      (item) => {
        if (!isRecord(item)) return [];
        const axisId = asOptionalString(read(item, 'axisId', 'axis_id'));
        if (!axisId) return [];
        return [{
          axisId,
          label: asString(read(item, 'label'), axisId),
          status: asString(read(item, 'status'), 'BLOCKED'),
          boundary: asString(read(item, 'boundary')),
        }];
      },
    ),
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
