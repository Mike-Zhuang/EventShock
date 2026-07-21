export type ClaimReviewStatus = 'AI_PROPOSED' | 'HUMAN_APPROVED' | 'EDITED' | 'REJECTED' | 'FROZEN';

export type ExperimentStatus =
  | 'DRAFT'
  | 'READY'
  | 'QUEUED'
  | 'RUNNING'
  | 'AGGREGATING'
  | 'CANCEL_REQUESTED'
  | 'COMPLETED'
  | 'FAILED'
  | 'FAILED_RETRYABLE'
  | 'FAILED_FINAL'
  | 'CANCELLED'
  | 'INVALIDATED';

export type InvalidationReasonCode =
  | 'DATA_ISSUE'
  | 'MODEL_ISSUE'
  | 'METRIC_ISSUE'
  | 'SECURITY_INCIDENT'
  | 'OTHER';

export interface HealthStatus {
  status: string;
  service?: string;
  version?: string;
}

export type UserRole = 'ADMIN' | 'USER';
export type VerificationPurpose = 'REGISTER' | 'RESET_PASSWORD';

export interface AuthUser {
  id: string;
  email: string;
  role: UserRole;
  emailVerified: boolean;
  createdAt: string;
  lastLoginAt?: string;
}

export interface AuthSession {
  authenticationRequired: boolean;
  authenticated: boolean;
  user?: AuthUser;
  csrfToken?: string;
}

export interface VerificationCodeReceipt {
  accepted: boolean;
  retryAfterSeconds: number;
  expiresInSeconds: number;
}

export interface AdminUserSummary extends AuthUser {
  status: 'ACTIVE' | 'DISABLED';
  lastActivityAt?: string;
  experimentCount: number;
  activityCount: number;
}

export interface AdminUserStatistics {
  totalUsers: number;
  verifiedUsers: number;
  activeUsersLastSevenDays: number;
  totalActivities: number;
}

export interface AdminUserPage {
  items: AdminUserSummary[];
  total: number;
  summary: AdminUserStatistics;
}

export interface AdminActivity {
  id: string;
  userId?: string;
  userEmail?: string;
  action: string;
  entityType?: string;
  entityId?: string;
  outcome: 'SUCCEEDED' | 'FAILED';
  createdAt: string;
}

export interface AdminActivityPage {
  items: AdminActivity[];
  total: number;
}

export interface CaseSummary {
  id: string;
  name: string;
  nameZh?: string;
  description?: string;
  descriptionZh?: string;
  eventPackId?: string;
  status?: string;
  isSynthetic?: boolean;
  syntheticLabel?: string;
  syntheticLabelZh?: string;
  updatedAt?: string;
  featured?: boolean;
  caseRole?: string;
  validationStatus?: string;
}

export interface EventSource {
  id: string;
  title: string;
  titleZh?: string;
  publisher?: string;
  url?: string;
  tier?: string;
  publishedAt?: string;
  hash?: string;
  sourceType?: 'OFFICIAL' | 'ESTIMATE' | 'REPORTING' | string;
  isOfficial?: boolean;
  knownAt?: string;
  retrievedAt?: string;
  license?: string;
  exportAllowed?: boolean;
}

export interface EventClaim {
  id: string;
  text: string;
  textZh?: string;
  status: ClaimReviewStatus;
  sourceId?: string;
  sourceIds?: string[];
  sourceTier?: string;
  publishedAt?: string;
  knownAt?: string;
  confidence?: number;
  impactChannels?: string[];
  editedText?: string;
  isRequired?: boolean;
  claimType?: string;
}

export interface EventPackContentFinding {
  sourceId?: string;
  code: string;
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | string;
  field: string;
  offset: number;
}

export interface EventPackContentSourceReview {
  sourceId: string;
  decision: string;
  sourceReviewLabel?: string;
  officialHost?: string;
  findingCount: number;
}

export interface EventPackContentSecurity {
  schemaVersion: string;
  decision: string;
  acknowledged: boolean;
  sourceCount: number;
  findingCount: number;
  findingsTruncated: boolean;
  rawContentRetained?: boolean;
  findings: EventPackContentFinding[];
  sources: EventPackContentSourceReview[];
}

export interface EventPack {
  id: string;
  caseId?: string;
  name: string;
  nameZh?: string;
  description?: string;
  descriptionZh?: string;
  status: string;
  pointInTime?: string;
  frozenAt?: string;
  extractionMode?: string;
  contentSecurity?: EventPackContentSecurity;
  editableExtraction: boolean;
  instrument?: string;
  isSynthetic?: boolean;
  syntheticLabel?: string;
  syntheticLabelZh?: string;
  limitations: string[];
  limitationsZh: string[];
  sources: EventSource[];
  claims: EventClaim[];
  defaultExperiment?: ScenarioDraft;
}

export type InterventionParameter =
  | 'marketMakerCapacity'
  | 'socialAmplification'
  | 'stopLossSensitivity'
  | 'clarificationDelay'
  | 'liquidityDepthMultiplier'
  | 'passiveFlowMultiplier'
  | 'informationLatency';

export type NetworkTopology =
  | 'ERDOS_RENYI'
  | 'WATTS_STROGATZ'
  | 'BARABASI_ALBERT'
  | 'STOCHASTIC_BLOCK'
  | 'ECHO_CHAMBER'
  | 'CORE_PERIPHERY';

export type AgentMode = 'RULE_ONLY' | 'HYBRID_LLM';
export type LlmProviderId = 'zhipu' | 'openai' | 'anthropic' | 'google' | 'deepseek' | 'alibaba' | 'moonshot';

export interface InterventionDefinition {
  parameter: InterventionParameter;
  baselineValue: number;
  interventionValue: number;
}

export interface ScenarioDraft {
  eventPackId: string;
  question?: string;
  questionZh?: string;
  intervention: InterventionDefinition;
  seedCount: 10 | 25 | 50;
  seedRoot?: number;
  populationSize: number;
  steps: number;
  market?: {
    instrumentId: string;
    benchmarkId: string;
    tickSize: number;
    initialPrice: number;
    feeBps: number;
    latencyMs: number;
    openingAuction: boolean;
    volatilityHalt: boolean;
    priceCollarBps: number;
  };
  population?: {
    profileId: string;
    representativeLlmAgents: number;
    institutionalShare: number;
    leverageEnabled: boolean;
    shortSellingEnabled: boolean;
  };
  network?: {
    topology: NetworkTopology;
    averageDegree: number;
    rewiringProbability: number;
    echoChamberStrength: number;
    correctionReach: number;
  };
  llmPolicy?: {
    mode: AgentMode;
    provider: LlmProviderId;
    modelId: string;
    representativeAgentCount: number;
    decisionIntervalSteps: number;
    callBudget: number;
    maxCostUsd: number;
    fallbackToRules: boolean;
  };
  primaryOutcome?: string;
  secondaryOutcomes?: string[];
  stoppingRule?: {
    minimumPairs: number;
    maximumPairs: number;
    targetCiHalfWidth?: number;
  };
  acknowledgedScenarioNotForecast?: boolean;
  acknowledgedSyntheticAssumptions?: boolean;
}

export interface EventSourceUpload {
  sourceId: string;
  title: string;
  publisher: string;
  url?: string;
  sourceType: 'OFFICIAL' | 'REPORTING' | 'ESTIMATE' | 'USER_PROVIDED';
  publishedAt: string;
  knownAt: string;
  rawText: string;
}

export interface EventPackCreateInput {
  title: string;
  titleZh?: string;
  summary: string;
  summaryZh?: string;
  asOf: string;
  instrument: string;
  sources: EventSourceUpload[];
  acknowledgedContentReview?: boolean;
}

export type ModelQualityTier = 'ECONOMY' | 'BALANCED' | 'PREMIUM';
export type ModelPricingStatus = 'VERIFIED_UPPER_BOUND' | 'UNAVAILABLE_FAIL_CLOSED';

export interface LlmModelDescriptor {
  provider: LlmProviderId;
  id: string;
  name: string;
  contextTokens: number;
  maxOutputTokens?: number;
  officialMaxOutputTokens?: number;
  applicationMaxOutputTokens?: number;
  supportsThinking: boolean;
  thinkingAlwaysOn?: boolean;
  supportsFunctionCalling: boolean;
  recommended: boolean;
  qualityTier: ModelQualityTier;
  freeTier: boolean;
  legacy: boolean;
  deprecationNote?: string;
  capabilityNote?: string;
  officialModelUrl?: string;
  catalogVerifiedAt?: string;
  pricingStatus: ModelPricingStatus;
  billingCurrency?: string;
  inputRateUpperPerMillion?: number;
  outputRateUpperPerMillion?: number;
  budgetInputRateUpperPerMillion?: number;
  budgetOutputRateUpperPerMillion?: number;
  cachedInputRatePerMillion?: number;
  pricingVerifiedAt?: string;
  pricingNote?: string;
}

/** @deprecated 新代码应使用供应商中立的 LlmModelDescriptor。 */
export type ZhipuModelDescriptor = LlmModelDescriptor;

export interface LlmProviderDescriptor {
  id: LlmProviderId;
  name: string;
  baseUrl: string;
  documentationUrl: string;
  pricingUrl: string;
  region: string;
  structuredOutputMode: string;
  structuredOutputNote: string;
  models: LlmModelDescriptor[];
}

export interface LlmCatalog {
  defaultProvider: LlmProviderId;
  providers: LlmProviderDescriptor[];
  /** 以下字段用于兼容旧版单供应商响应和渐进迁移中的调用方。 */
  provider: LlmProviderId;
  providerName: string;
  baseUrl: string;
  documentationUrl: string;
  pricingUrl: string;
  pricingSnapshotVersion: string;
  fxSourceUrl: string;
  officialFxSnapshotCnyPerUsd: number;
  cnyPerUsdBudgetFloor: number;
  costCapSemantics: string;
  models: LlmModelDescriptor[];
}

export interface PromptRegistryItem {
  name: string;
  version: string;
  schemaVersion: string;
  promptHash: string;
}

export interface LlmConfigView {
  configured: boolean;
  provider?: LlmProviderId;
  model?: string;
  thinkingEnabled?: boolean;
  maxTokens?: number;
  credentialHint?: string;
  expiresAt?: string;
}

export interface LlmConfigInput {
  provider: LlmProviderId;
  model: string;
  apiKey: string;
  thinkingEnabled: boolean;
  maxTokens: number;
}

export interface LlmConnectionTest {
  ok: boolean;
  provider: string;
  model: string;
  structuredOutputValidated: boolean;
  responseSchemaVersion?: string;
  latencyMs?: number;
  failureCode?: string;
  message: string;
}

export interface ValidationCheck {
  id: string;
  label: string;
  passed: boolean;
  detail?: string;
  severity?: 'info' | 'warning' | 'error';
}

export interface ScenarioValidation {
  valid: boolean;
  checks: ValidationCheck[];
  estimatedRuntimeSeconds?: number;
  estimatedLlmCalls?: number;
  estimatedRuns?: number;
  llmCostCapUsd?: number;
  llmPricingStatus?: string;
  llmMinimumCallReservationUsd?: number;
  interpretationBoundary?: string;
  warnings?: string[];
}

export interface ExperimentLogEntry {
  timestamp: string;
  level: 'INFO' | 'WARNING' | 'ERROR' | string;
  message: string;
  seed?: number;
}

export interface LiveMarketSnapshot {
  step: number;
  completedSteps: number;
  totalSteps: number;
  price?: number;
  spreadBps?: number;
  depth?: number;
  volume?: number;
  sentiment?: number;
  marketState?: string;
  haltCount?: number;
  activeCognitiveAgents?: number;
}

export interface ExperimentLiveState {
  phase?: 'COGNITION' | 'BASELINE' | 'INTERVENTION' | 'AGGREGATING' | 'COMPLETED' | string;
  pairIndex?: number;
  currentSeed?: number;
  baseline?: LiveMarketSnapshot;
  intervention?: LiveMarketSnapshot;
  resumedFromCheckpoint?: boolean;
  checkpointPairs?: number;
}

export interface Experiment {
  id: string;
  eventPackId: string;
  status: ExperimentStatus;
  createdAt?: string;
  updatedAt?: string;
  completedAt?: string;
  invalidatedAt?: string;
  invalidationReasonCode?: string;
  invalidationReason?: string;
  resultsAvailable?: boolean;
  resultsPreserved?: boolean;
  validForResearchUse?: boolean;
  progress: number;
  completedSeeds?: number;
  validSeeds?: number;
  totalSeeds?: number;
  currentSeed?: number;
  message?: string;
  error?: string;
  scenario?: ScenarioDraft;
  intervention?: InterventionDefinition;
  liveState?: ExperimentLiveState;
  logs: ExperimentLogEntry[];
}

export type MetricDisplayUnit =
  | '%'
  | 'percent'
  | 'ratio'
  | 'bps'
  | 'steps'
  | 'seconds'
  | 's'
  | 'shares'
  | 'score'
  | 'cents'
  | 'count'
  | 'events/s'
  | 'ms';

export interface MetricResult {
  id: string;
  label: string;
  unit?: MetricDisplayUnit;
  baseline?: number;
  intervention?: number;
  delta?: number;
  ciLow?: number;
  ciHigh?: number;
  n?: number;
  stable?: boolean;
  directionConsistencyRate?: number;
  signConsistency?: number;
  bootstrapCiLow?: number;
  bootstrapCiHigh?: number;
  bootstrapContainsZero?: boolean;
  cohensDz?: number;
  matchedRankBiserial?: number;
  standardDeviationDifference?: number;
  positiveTailProbability?: number;
  negativeTailProbability?: number;
  baselineMean?: number;
  interventionMean?: number;
  deltaMean?: number;
  excludedRuns?: number;
  exclusionReasons?: string[];
  sensitivityFlag?: 'STABLE' | 'SENSITIVE' | 'NOT_EVALUATED' | string;
  interpretation?: string;
  interpretationZh?: string;
  limitation?: string;
  limitationZh?: string;
}

export interface PairedSeedPoint {
  seed: number;
  baseline: number;
  intervention: number;
  delta: number;
}

export interface DistributionPoint {
  bin: string | number;
  baseline: number;
  intervention: number;
}

export interface MarketPathPoint {
  step: number;
  time?: string;
  baselinePrice?: number;
  interventionPrice?: number;
  baselineSpread?: number;
  interventionSpread?: number;
  baselineDepth?: number;
  interventionDepth?: number;
}

export interface AgentFlowPoint {
  agentType: string;
  baselineNetFlow?: number;
  interventionNetFlow?: number;
  delta?: number;
}

export interface AgentPnlPoint {
  agentType: string;
  baselineEquityChangeCents?: number;
  interventionEquityChangeCents?: number;
  deltaEquityChangeCents?: number;
  validN?: number;
  directionConsistencyRate?: number;
}

export interface StoppingRuleResult {
  mode?: string;
  triggered: boolean;
  reason: string;
  primaryOutcome?: string;
  completedPairs: number;
  observedCiHalfWidth?: number;
  targetCiHalfWidth?: number;
  minimumPairs?: number;
  maximumPairs?: number;
  bootstrapInterval95?: {
    estimate?: number;
    lower?: number;
    upper?: number;
    confidenceLevel?: number;
    resamples?: number;
    seed?: number;
  };
}

export interface NarrativeReport {
  schemaVersion: string;
  headline: string;
  headlineZh?: string;
  summary: string;
  summaryZh?: string;
  interpretationBoundary: string;
  interpretationBoundaryZh?: string;
  generatedBy: string;
}

export interface TraceNode {
  id: string;
  step?: number;
  time?: string;
  kind?: string;
  title: string;
  summary?: string;
  summaryZh?: string;
  sourceId?: string;
  agentId?: string;
  orderId?: string;
  metricContribution?: number;
  methodNote?: string;
  scenario?: string;
  seed?: number;
  parentId?: string;
  payload?: Record<string, unknown>;
}

export interface ExperimentResults {
  experimentId: string;
  generatedAt?: string;
  validSeedCount?: number;
  scenarioDiff?: InterventionDefinition;
  metrics: MetricResult[];
  pairedSeeds: PairedSeedPoint[];
  distribution: DistributionPoint[];
  marketPaths: MarketPathPoint[];
  agentFlows: AgentFlowPoint[];
  agentPnl: AgentPnlPoint[];
  traces: TraceNode[];
  validationStatus?: string;
  primaryMetricId?: string;
  pairedSeries: Record<string, PairedSeedPoint[]>;
  limitations: string[];
  limitationsZh: string[];
  modelVersions: Record<string, string>;
  dataVersions: Record<string, string>;
  cognition?: CognitionRunMetadata;
  robustness?: RobustnessEvidence;
  stoppingRule?: StoppingRuleResult;
  narrativeReport?: NarrativeReport;
  analysisDiagnostics?: AnalysisDiagnostics;
}

export interface SavedScenario {
  id: string;
  name: string;
  config: ScenarioDraft;
  frozen: boolean;
  contentHash: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface ScenarioDiffChange {
  path: string;
  baseline: unknown;
  intervention: unknown;
}

export interface ScenarioDiffResult {
  changeCount: number;
  changedPaths: string[];
  changes: ScenarioDiffChange[];
  singleInterventionCompliant: boolean;
}

export interface CognitionDecisionSummary {
  agentId?: string;
  representativeIndex?: number;
  role?: string;
  actionPreference?: string;
  direction?: string;
  confidence?: number;
  uncertainty?: number;
  evidenceIds: string[];
  decisionSummary?: string;
  fallbackUsed?: boolean;
  repairUsed?: boolean;
  failureReason?: string;
  failureCodes: string[];
  transportAttempts?: number;
  requestId?: string;
  decisionRound?: number;
  observationAt?: string;
  activeFromStep?: number;
  decisionIntervalSteps?: number;
  evidenceCount?: number;
  socialPostCount?: number;
  memoryCount?: number;
  promptTokens?: number;
  completionTokens?: number;
  cachedTokens?: number;
  costUpperBoundUsd?: number;
}

export interface CognitionCostBudget {
  capUsd: number;
  chargedUsdUpperBound: number;
  activeReservationUsd: number;
  remainingUsd: number;
  estimatedPromptTokens: number;
  estimatedCompletionTokens: number;
  actualPromptTokens: number;
  actualCompletionTokens: number;
  cachedPromptTokens: number;
  reservedCalls: number;
  settledCalls: number;
  blockedCalls: number;
  unknownUsageCalls: number;
  provider?: string;
  billingCurrency: string;
  fxConversionApplied: boolean;
  pricingSnapshotVersion: string;
  pricingVerifiedAt: string;
  priceSourceUrl: string;
  fxSourceUrl: string;
  officialFxSnapshotCnyPerUsd: number;
  cnyPerUsdBudgetFloor: number;
  semantics: string;
}

export interface CognitionRunMetadata {
  requestedMode: string;
  resolvedMode: string;
  provider?: string;
  requestedModel?: string;
  resolvedModel?: string;
  calls: number;
  totalTokens: number;
  promptTokens: number;
  completionTokens: number;
  cachedTokens: number;
  fallbackCount: number;
  fallbackReasons: string[];
  cacheHits: number;
  plannedCalls: number;
  attemptedCalls: number;
  decisionScheduleMode?: string;
  promptVersion?: string;
  promptSchemaVersion?: string;
  failureCode?: string;
  costControl?: string;
  providerPriceEstimateAvailable?: boolean;
  costBudget?: CognitionCostBudget;
  decisions: CognitionDecisionSummary[];
}

export interface RobustnessEvidence {
  sensitivityStatus: string;
  ablationStatus: string;
  negativeControlStatus: string;
  knockoutStatus: string;
  notes: string[];
}

export interface AnalysisDiagnosticControl {
  status: string;
  controlType?: string;
  passed?: boolean;
  reason?: string;
  tolerance?: number;
  interpretation?: string;
  fullEffect?: number;
  knockoutEffect?: number;
  attenuationFraction?: number;
  minimumAttenuationFraction?: number;
  mechanismSupported?: boolean;
}

export interface SensitivityDiagnostic {
  parameter: string;
  spearmanCorrelation?: number;
  direction?: string;
  varianceImportanceProxy?: number;
  sampleSize?: number;
}

export interface MultipleComparisonDiagnostic {
  hypothesisId: string;
  rawPValue?: number;
  adjustedPValue?: number;
  alphaThreshold?: number;
  rejected: boolean;
  rank?: number;
}

export interface AnalysisDiagnostics {
  schemaVersion: string;
  preregisteredPrimaryOutcome: string;
  outcomeFamily: string[];
  negativeControl: AnalysisDiagnosticControl;
  parameterRestorationKnockout: AnalysisDiagnosticControl;
  localSensitivity: {
    status: string;
    design?: string;
    interpretation?: string;
    indices: SensitivityDiagnostic[];
  };
  multipleComparison: {
    method: string;
    alpha?: number;
    items: MultipleComparisonDiagnostic[];
  };
  interpretationBoundary: string;
}

export interface CognitionTelemetry {
  calls: number;
  cacheHits: number;
  fallbacks: number;
  invalidOutputs: number;
  promptTokens: number;
  completionTokens: number;
  cachedTokens: number;
  totalTokens: number;
  totalLatencyMs: number;
  averageLatencyMs: number;
  cacheHitRate: number;
  fallbackRate: number;
  invalidOutputRate: number;
}

export interface SystemMetrics {
  service: string;
  version: string;
  runtime: {
    uptimeSeconds: number;
    requestCount: number;
    clientErrorCount: number;
    serverErrorCount: number;
    serverErrorRate: number;
    latencyWindowSize: number;
    latencyMs: {
      p50: number;
      p95: number;
      maximum: number;
      mean: number;
    };
    privacyBoundary: string;
  };
  experiments: {
    workerConcurrency: number;
    activeOrQueued: number;
    maximumActiveOrQueued: number;
    maximumExperimentsPerSession: number;
  };
  storage: {
    database: string;
    retainedExperiments: number;
    maximumRetainedExperiments: number;
  };
  cognition: CognitionTelemetry;
  sloTargets: {
    availability: number;
    apiP95Milliseconds: number;
    status: string;
  };
}

export interface CognitionEvalSummary {
  telemetry: CognitionTelemetry;
  evaluatedCases: number;
  passedCases: number;
  passRate: number;
}

export interface CognitionEvaluationRun {
  mode: 'CODE_GRADER_SELF_TEST' | 'LIVE_CONFIGURED_MODEL';
  evaluatedSystem: string;
  suiteVersion: string;
  result: {
    totalCases: number;
    passedCases: number;
    passRate: number;
    results: Array<{
      caseId: string;
      passed: boolean;
      score: number;
      checks: Array<{ name: string; passed: boolean; detail: string }>;
    }>;
  };
  modelRuns: Array<{
    caseId: string;
    model: string;
    requestId?: string;
    cacheHit: boolean;
    fallbackUsed: boolean;
    repairUsed: boolean;
    latencyMs?: number;
    totalTokens?: number;
  }>;
  interpretationBoundary: string;
}

export interface GovernanceComponent {
  componentId: string;
  name: string;
  kind: string;
  owner: string;
  purpose: string;
  materiality: string;
  version: string;
  validationStatuses: string[];
  limitations: string[];
  approvalStatus: string;
  external: boolean;
}

export interface GovernanceInventory {
  inventoryHash: string;
  items: GovernanceComponent[];
}

export interface RedTeamDefinition {
  caseId: string;
  title: string;
  category: string;
  severity: string;
  owner: string;
  automationCoverage: string;
  requiresHumanEvidence: boolean;
}

export interface RedTeamResult {
  caseId: string;
  category: string;
  status: string;
  score: number;
  passed: boolean;
  detail: string;
}

export interface RedTeamRegistry {
  definitions: RedTeamDefinition[];
  results: RedTeamResult[];
  notice: string;
}

export interface ReleaseGateResult {
  gateId: string;
  status: string;
  detail: string;
  evidenceIds: string[];
}

export interface ReleaseGateDefinition {
  gateId: string;
  title: string;
  owner: string;
  criterion: string;
  failureEffect: string;
}

export interface ReleaseGateView {
  releaseId: string;
  evaluatedAt?: string;
  decision: string;
  canRelease: boolean;
  inventoryHash: string;
  humanEvidenceComplete: boolean;
  blockerGateIds: string[];
  gateResults: ReleaseGateResult[];
  definitions: ReleaseGateDefinition[];
  interpretationBoundary: string;
}

export interface ValidationLadderLevel {
  level: string;
  title: string;
  status: string;
  boundary: string;
}

export interface ValidationLadderView {
  highestAllowedClaim: string;
  levels: ValidationLadderLevel[];
}

export interface ApiList<T> {
  items: T[];
}

export interface ClaimReviewInput {
  status: Exclude<ClaimReviewStatus, 'AI_PROPOSED' | 'FROZEN'>;
  editedText?: string;
  editedTextZh?: string;
}

export interface BulkClaimApprovalInput {
  acknowledgedBulkApproval: true;
  expectedClaimIds: string[];
  rationale?: string;
}

export type StudyOutcomeId =
  | 'max-drawdown-pct'
  | 'realized-volatility-pct'
  | 'max-spread-bps'
  | 'min-depth'
  | 'recovery-steps'
  | 'total-volume'
  | 'order-imbalance'
  | 'cascade-score'
  | 'network-reach-rate'
  | 'information-delay-steps'
  | 'liquidity-stress-index'
  | 'tail-loss-probability'
  | 'abnormal-return-pct';

export type StudyFactorPath =
  | 'intervention.value'
  | 'market.fee_bps'
  | 'market.latency_ms'
  | 'market.price_collar_bps'
  | 'network.correction_reach'
  | 'network.echo_chamber_strength'
  | 'network.rewiring_probability'
  | 'population.institutional_share';

export type StudyDesignKind = 'FULL_FACTORIAL' | 'LATIN_HYPERCUBE';
export type StudyExpectedDirection = 'INCREASE' | 'DECREASE' | 'TWO_SIDED';
export type StudyEvidenceBasis = 'EVIDENCE_BOUND' | 'ASSUMPTION' | 'SYNTHETIC';

export interface StudyPreset {
  presetId: string;
  eventPackId: string;
  title: string;
  titleZh: string;
  question: string;
  questionZh: string;
  recommendedInterventionParameter: InterventionParameter;
  factorPaths: StudyFactorPath[];
  primaryOutcomeIds: StudyOutcomeId[];
}

export interface StudySupportedOutcome {
  outcomeId: StudyOutcomeId;
  unit: string;
}

export interface StudySupportedFactor {
  parameterPath: StudyFactorPath;
  unit: string;
  minimum: number;
  maximum: number;
}

export interface StudyPresetCatalog {
  schemaVersion: string;
  historicalValidityEstablished: false;
  validityBoundary: string;
  requiredNegativeControlCount: number;
  requiredAblationCount: number;
  supportedOutcomes: StudySupportedOutcome[];
  supportedFactors: StudySupportedFactor[];
  items: StudyPreset[];
}

export interface StudyOutcomeInput {
  outcomeId: StudyOutcomeId;
  familyId: string;
  expectedDirection: StudyExpectedDirection;
  rationale: string;
  minimumEffectOfInterest?: number;
}

export interface StudyPreregistrationInput {
  studyId: string;
  question: string;
  claimLevel: 'MODEL_INTERNAL_SENSITIVITY' | 'MECHANISM_DEMONSTRATION';
  primaryOutcomes: StudyOutcomeInput[];
  secondaryOutcomes: StudyOutcomeInput[];
  exclusionRules: string[];
  supportCriterion: string;
  contradictionCriterion: string;
  inconclusiveCriterion: string;
  knownLimitations: string[];
}

export interface StudyFactorInput {
  parameterPath: StudyFactorPath;
  baselineValue: number;
  levels?: number[];
  lower?: number;
  upper?: number;
  rationale: string;
  evidenceBasis: StudyEvidenceBasis;
  sourceReference?: string;
}

export interface StudyDesignInput {
  kind: StudyDesignKind;
  factors: StudyFactorInput[];
  sampleCount?: number;
  designSeed: number;
}

export interface StudyDesignPreviewInput {
  design: StudyDesignInput;
  matchedSeedCount: number;
  populationSize: number;
  steps: number;
}

export interface StudyParameterSetting {
  path: string;
  value: string | number | boolean;
  unit: string;
  rationale: string;
  evidenceBasis: StudyEvidenceBasis;
  sourceReference?: string;
}

export interface StudyDesignCell {
  cellId: string;
  designKind: StudyDesignKind;
  designIndex: number;
  settings: StudyParameterSetting[];
}

export interface StudyResourceBudget {
  totalExecutionCells: number;
  matchedSeedCount: number;
  expectedRunCount: number;
  estimatedWorkUnits: number;
  maximumRunCount: number;
  maximumWorkUnits: number;
}

export interface StudyDesignPreview extends StudyResourceBudget {
  designKind: StudyDesignKind;
  designCellCount: number;
  requiredNegativeControlCount: number;
  requiredAblationCount: number;
  withinResourceLimits: boolean;
  historicalValidityEstablished: false;
  cells: StudyDesignCell[];
}

export interface StudyExecutionInput {
  interventionParameter: InterventionParameter;
  baselineInterventionValue: number;
  matchedSeedCount: number;
  seedRoot: number;
  populationSize: number;
  steps: number;
  frozenCognitiveRepresentativeCount: number;
}

export interface StudyRunInput {
  eventPackId: string;
  preregistration: StudyPreregistrationInput;
  design: StudyDesignInput;
  execution: StudyExecutionInput;
  nullToleranceByOutcome: Record<string, number>;
  alpha: number;
  bootstrapResamples: number;
  analysisSeed: number;
  acknowledgedModelInternalOnly: true;
  acknowledgedProxyAblations: true;
}

export interface StudyPairedAnalysis {
  sampleSize: number;
  meanDifference: number;
  medianDifference: number;
  percentileLower: number;
  percentileUpper: number;
  bootstrap95: {
    estimate: number;
    lower: number;
    upper: number;
    confidenceLevel: number;
    resamples: number;
    seed: number;
    statisticName: string;
    containsZero?: boolean;
  };
  effectSize: {
    meanDifference: number;
    standardDeviationDifference: number;
    cohensDz?: number;
    matchedRankBiserial: number;
  };
  signConsistency: number;
  positiveTailProbability: number;
  negativeTailProbability: number;
  differences: number[];
}

export interface StudyCellOutcomeAnalysis {
  hypothesisId: string;
  familyId: string;
  cellId: string;
  outcomeId: StudyOutcomeId;
  expectedDirection: StudyExpectedDirection;
  analysis: StudyPairedAnalysis;
  exactSignPValue: number;
}

export interface StudyHolmResult {
  hypothesisId: string;
  rawPValue: number;
  adjustedPValue: number;
  alphaThreshold: number;
  rejected: boolean;
  rank: number;
}

export interface StudyHolmFamily {
  familyId: string;
  alpha: number;
  results: StudyHolmResult[];
}

export interface StudyNegativeControl {
  controlId: string;
  kind: string;
  expectation: 'NULL_EFFECT' | 'MECHANISM_DIAGNOSTIC';
  cellId: string;
  outcomeResults: Array<{
    outcomeId: StudyOutcomeId;
    result: {
      controlName: string;
      tolerance: number;
      analysis: StudyPairedAnalysis;
      passed: boolean;
      reason: string;
    };
  }>;
  interpretationBoundary: string;
}

export interface StudySensitivityOutcome {
  outcomeId: StudyOutcomeId;
  method: string;
  indices: Array<{
    parameter: string;
    spearmanCorrelation: number;
    direction: string;
    varianceImportanceProxy: number;
    sampleSize: number;
  }>;
  dominantParameter?: string;
  dominantEvidenceBasis?: StudyEvidenceBasis;
  interpretation: string;
  warning: string;
}

export interface StudyExecutionCell {
  cellId: string;
  role: 'BASELINE' | 'DESIGN' | 'NEGATIVE_CONTROL' | 'ABLATION';
  sourceId: string;
  sourceKind: string;
  settings: StudyParameterSetting[];
}

export interface StudyCoreResult {
  studyId: string;
  cells: StudyExecutionCell[];
  cellOutcomeAnalyses: StudyCellOutcomeAnalysis[];
  holmFamilies: StudyHolmFamily[];
  negativeControls: StudyNegativeControl[];
  sensitivity: StudySensitivityOutcome[];
  audit: {
    specHash: string;
    resultHash: string;
    runnerName: string;
    expectedRunCount: number;
    completedRunCount: number;
    commonRandomSeedScheduleVerified: boolean;
    historicalValidityEstablished: false;
    validityBoundary: string;
  };
}

export interface StudyResultDocument {
  schemaVersion: string;
  runId: string;
  studyId: string;
  status: 'COMPLETED';
  eventPackId: string;
  historicalValidityEstablished: false;
  validityBoundary: string;
  resourceBudget: StudyResourceBudget;
  executionProtocol: {
    runner: string;
    marketKernel: string;
    cognitionMode: string;
    matchedSeeds: boolean;
    requiredNegativeControlsIncluded: number;
    requiredAblationsIncluded: number;
    proxyAblationsAcknowledged: boolean;
    mechanismSemantics: Array<{ kind: string; status: string; boundary: string }>;
  };
  preregistration: Record<string, unknown>;
  result: StudyCoreResult;
}

export interface StudyRunRecord {
  runId: string;
  eventPackId: string;
  studyId: string;
  status: 'COMPLETED';
  specHash: string;
  resultHash: string;
  historicalValidityEstablished: false;
  createdAt: string;
  spec?: Record<string, unknown>;
  result?: StudyResultDocument;
}
