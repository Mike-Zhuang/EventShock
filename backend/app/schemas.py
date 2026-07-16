"""公开 API 的 Pydantic 契约，JSON 字段统一使用 camelCase。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewStatus(StrEnum):
    HUMAN_APPROVED = "HUMAN_APPROVED"
    EDITED = "EDITED"
    REJECTED = "REJECTED"


class InterventionParameter(StrEnum):
    MARKET_MAKER_CAPACITY = "marketMakerCapacity"
    SOCIAL_AMPLIFICATION = "socialAmplification"
    STOP_LOSS_SENSITIVITY = "stopLossSensitivity"
    CLARIFICATION_DELAY = "clarificationDelay"
    LIQUIDITY_DEPTH_MULTIPLIER = "liquidityDepthMultiplier"
    PASSIVE_FLOW_MULTIPLIER = "passiveFlowMultiplier"
    INFORMATION_LATENCY = "informationLatency"


class NetworkTopology(StrEnum):
    ERDOS_RENYI = "ERDOS_RENYI"
    WATTS_STROGATZ = "WATTS_STROGATZ"
    BARABASI_ALBERT = "BARABASI_ALBERT"
    STOCHASTIC_BLOCK = "STOCHASTIC_BLOCK"
    ECHO_CHAMBER = "ECHO_CHAMBER"
    CORE_PERIPHERY = "CORE_PERIPHERY"


class AgentMode(StrEnum):
    RULE_ONLY = "RULE_ONLY"
    HYBRID_LLM = "HYBRID_LLM"


class InvalidationReasonCode(StrEnum):
    DATA_ISSUE = "DATA_ISSUE"
    MODEL_ISSUE = "MODEL_ISSUE"
    METRIC_ISSUE = "METRIC_ISSUE"
    SECURITY_INCIDENT = "SECURITY_INCIDENT"
    OTHER = "OTHER"


class ClaimReviewRequest(StrictModel):
    reviewStatus: ReviewStatus = Field(validation_alias=AliasChoices("reviewStatus", "status"))
    editedText: str | None = Field(default=None, min_length=1, max_length=1_000)
    editedTextZh: str | None = Field(default=None, min_length=1, max_length=1_000)
    rationale: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validateEditedClaim(self) -> ClaimReviewRequest:
        if self.reviewStatus == ReviewStatus.EDITED and not self.editedText:
            raise ValueError("editedText is required when reviewStatus is EDITED")
        return self


class InterventionConfig(StrictModel):
    parameter: InterventionParameter
    baselineValue: float = Field(gt=0, le=4)
    interventionValue: float = Field(gt=0, le=4)

    @model_validator(mode="after")
    def validateParameterRange(self) -> InterventionConfig:
        parameterMaximum = {
            InterventionParameter.MARKET_MAKER_CAPACITY: 3.0,
            InterventionParameter.SOCIAL_AMPLIFICATION: 3.0,
            InterventionParameter.STOP_LOSS_SENSITIVITY: 3.0,
            InterventionParameter.CLARIFICATION_DELAY: 4.0,
            InterventionParameter.LIQUIDITY_DEPTH_MULTIPLIER: 3.0,
            InterventionParameter.PASSIVE_FLOW_MULTIPLIER: 3.0,
            InterventionParameter.INFORMATION_LATENCY: 4.0,
        }[self.parameter]
        if self.baselineValue > parameterMaximum or self.interventionValue > parameterMaximum:
            raise ValueError(
                f"values for {self.parameter.value} must not exceed {parameterMaximum}"
            )
        return self


class MarketConfig(StrictModel):
    instrumentId: str = Field(default="SPCX", min_length=1, max_length=32)
    benchmarkId: str = Field(default="NDX_SYNTHETIC", min_length=1, max_length=64)
    tickSize: float = Field(default=0.01, gt=0, le=10)
    initialPrice: float = Field(default=135.0, gt=0, le=1_000_000)
    feeBps: float = Field(default=0.3, ge=0, le=100)
    latencyMs: int = Field(default=25, ge=0, le=60_000)
    openingAuction: bool = True
    volatilityHalt: bool = True
    priceCollarBps: float = Field(default=180.0, gt=0, le=5_000)


class PopulationConfig(StrictModel):
    profileId: str = Field(default="mixed-event-risk-v1", min_length=1, max_length=100)
    representativeLlmAgents: int = Field(default=8, ge=0, le=100)
    institutionalShare: float = Field(default=0.2, ge=0, le=1)
    leverageEnabled: bool = True
    shortSellingEnabled: bool = True


class NetworkConfig(StrictModel):
    topology: NetworkTopology = NetworkTopology.WATTS_STROGATZ
    averageDegree: int = Field(default=6, ge=2, le=50)
    rewiringProbability: float = Field(default=0.12, ge=0, le=1)
    echoChamberStrength: float = Field(default=0.35, ge=0, le=1)
    correctionReach: float = Field(default=0.7, ge=0, le=1)


class LlmPolicy(StrictModel):
    mode: AgentMode = AgentMode.RULE_ONLY
    provider: Literal["zhipu"] = "zhipu"
    modelId: str = Field(default="glm-5.2", min_length=1, max_length=100)
    representativeAgentCount: int = Field(default=8, ge=0, le=100)
    decisionIntervalSteps: int = Field(default=12, ge=1, le=100)
    callBudget: int = Field(default=24, ge=0, le=500)
    maxCostUsd: float = Field(default=10.0, ge=0, le=100)
    fallbackToRules: bool = True


class StoppingRule(StrictModel):
    minimumPairs: int = Field(default=10, ge=5, le=50)
    maximumPairs: int = Field(default=10, ge=10, le=50)
    targetCiHalfWidth: float | None = Field(default=None, gt=0, le=100)

    @model_validator(mode="after")
    def validatePairBounds(self) -> StoppingRule:
        if self.minimumPairs > self.maximumPairs:
            raise ValueError("minimumPairs must not exceed maximumPairs")
        return self


class AnalysisPlan(StrictModel):
    runNegativeControl: bool = True
    runParameterRestorationKnockout: bool = True
    runLocalSensitivity: bool = True
    negativeControlTolerance: float = Field(default=0.0, ge=0, le=100)
    minimumKnockoutAttenuationFraction: float = Field(default=0.25, ge=0, le=1)
    multipleComparisonAlpha: float = Field(default=0.05, gt=0, lt=1)


class ExperimentRequest(StrictModel):
    eventPackId: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    question: str = Field(
        default="How does the selected intervention change the simulated risk distribution?",
        min_length=8,
        max_length=500,
    )
    questionZh: str | None = Field(default=None, max_length=500)
    intervention: InterventionConfig
    seedCount: Literal[10, 25, 50] = 10
    populationSize: int = Field(default=56, ge=14, le=250)
    steps: int = Field(default=120, ge=30, le=300)
    seedRoot: int = Field(default=2_026_070_700, ge=1, le=2_147_483_000)
    market: MarketConfig = Field(default_factory=MarketConfig)
    population: PopulationConfig = Field(default_factory=PopulationConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    llmPolicy: LlmPolicy = Field(default_factory=LlmPolicy)
    primaryOutcome: str = Field(default="maxSpreadBps", min_length=1, max_length=100)
    secondaryOutcomes: list[str] = Field(
        default_factory=lambda: ["maxDrawdownPct", "recoverySteps", "cascadeScore"],
        max_length=12,
    )
    stoppingRule: StoppingRule = Field(default_factory=StoppingRule)
    analysisPlan: AnalysisPlan = Field(default_factory=AnalysisPlan)
    acknowledgedScenarioNotForecast: bool = False
    acknowledgedSyntheticAssumptions: bool = False

    @model_validator(mode="after")
    def alignStoppingRule(self) -> ExperimentRequest:
        if self.stoppingRule.maximumPairs != self.seedCount:
            self.stoppingRule.maximumPairs = self.seedCount
        if self.stoppingRule.minimumPairs > self.seedCount:
            self.stoppingRule.minimumPairs = self.seedCount
        return self


class ExperimentInvalidateRequest(StrictModel):
    schemaVersion: Literal["1.0.0"] = "1.0.0"
    reasonCode: InvalidationReasonCode = InvalidationReasonCode.OTHER
    reason: str = Field(min_length=8, max_length=1_000)

    @field_validator("reason")
    @classmethod
    def normalizeReason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 8:
            raise ValueError("reason must contain at least 8 non-whitespace characters")
        if any(ord(character) < 32 for character in normalized):
            raise ValueError("reason must not contain control characters")
        return normalized


class ScenarioValidateRequest(ExperimentRequest):
    pass


class EventSourceInput(StrictModel):
    sourceId: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    title: str = Field(min_length=1, max_length=300)
    publisher: str = Field(min_length=1, max_length=200)
    url: str | None = Field(default=None, max_length=2_000)
    sourceType: Literal["OFFICIAL", "REPORTING", "ESTIMATE", "USER_PROVIDED"]
    publishedAt: datetime
    knownAt: datetime
    rawText: str = Field(min_length=1, max_length=50_000)

    @model_validator(mode="after")
    def validatePointInTime(self) -> EventSourceInput:
        if self.knownAt < self.publishedAt:
            raise ValueError("knownAt must not be earlier than publishedAt")
        return self


class EventPackCreateRequest(StrictModel):
    title: str = Field(min_length=3, max_length=200)
    titleZh: str | None = Field(default=None, max_length=200)
    summary: str = Field(min_length=8, max_length=1_000)
    summaryZh: str | None = Field(default=None, max_length=1_000)
    asOf: datetime
    instrument: str = Field(default="CUSTOM", min_length=1, max_length=32)
    sources: list[EventSourceInput] = Field(min_length=1, max_length=8)
    acknowledgedContentReview: bool = False


class EventPackExtractRequest(StrictModel):
    useLlm: bool = True
    maximumClaims: int = Field(default=16, ge=1, le=50)
    requestedImpactChannels: list[str] = Field(
        default_factory=lambda: ["belief", "liquidity", "passiveFlow", "stopLoss"],
        max_length=12,
    )
    sources: list[EventSourceInput] = Field(default_factory=list, max_length=8)
    acknowledgedContentReview: bool = False


class ScenarioSaveRequest(StrictModel):
    name: str = Field(min_length=1, max_length=150)
    config: ExperimentRequest
    frozen: bool = False


class ScenarioUpdateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=150)
    config: ExperimentRequest


class ScenarioDiffRequest(StrictModel):
    baseline: ExperimentRequest
    intervention: ExperimentRequest


class LlmConfigRequest(StrictModel):
    provider: Literal["zhipu"] = "zhipu"
    model: str = Field(min_length=3, max_length=100, pattern=r"^glm-[a-z0-9.-]+$")
    apiKey: str = Field(min_length=8, max_length=4_096)
    thinkingEnabled: bool = False
    maxTokens: int = Field(default=2_048, ge=256, le=131_072)


class EvalRunRequest(StrictModel):
    mode: Literal["CODE_GRADER_SELF_TEST", "LIVE_CONFIGURED_MODEL"] = "CODE_GRADER_SELF_TEST"
    maximumCases: int = Field(default=3, ge=1, le=3)
