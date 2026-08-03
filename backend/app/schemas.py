"""公开 API 的 Pydantic 契约，JSON 字段统一使用 camelCase。"""

from __future__ import annotations

import ipaddress
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.cognition.catalog import (
    APPLICATION_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    ProviderId,
    getModel,
)
from backend.app.cognition.gateway import (
    AdvancedModelParameters,
    validateAdvancedModelParameters,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewStatus(StrEnum):
    AI_PROPOSED = "AI_PROPOSED"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    EDITED = "EDITED"
    REJECTED = "REJECTED"


class ClaimImpactChannelRationaleInput(StrictModel):
    channel: str = Field(
        pattern=(
            r"^(belief|liquidity|passiveFlow|stopLoss|"
            r"socialAmplification|informationLatency)$"
        )
    )
    reason: str = Field(min_length=1, max_length=1_000)
    reasonZh: str | None = Field(default=None, min_length=1, max_length=1_000)
    evidenceType: Literal["FACT", "MECHANISM_HYPOTHESIS"]
    simulatorParameter: str = Field(min_length=1, max_length=128)


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
    editedImpactChannels: list[str] | None = Field(default=None, max_length=2)
    editedImpactChannelRationale: list[ClaimImpactChannelRationaleInput] | None = Field(
        default=None,
        max_length=2,
    )
    rationale: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validateEditedClaim(self) -> ClaimReviewRequest:
        allowedChannels = {
            "belief",
            "liquidity",
            "passiveFlow",
            "stopLoss",
            "socialAmplification",
            "informationLatency",
        }
        if self.editedImpactChannels is not None:
            if len(self.editedImpactChannels) != len(set(self.editedImpactChannels)):
                raise ValueError("editedImpactChannels must not contain duplicates")
            if set(self.editedImpactChannels) - allowedChannels:
                raise ValueError("editedImpactChannels contains unsupported values")
        if self.editedImpactChannelRationale is not None:
            rationaleChannels = [item.channel for item in self.editedImpactChannelRationale]
            if len(rationaleChannels) != len(set(rationaleChannels)):
                raise ValueError("editedImpactChannelRationale must contain one entry per channel")
            if self.editedImpactChannels is None:
                raise ValueError("editedImpactChannels is required when editing channel rationales")
            if set(rationaleChannels) != set(self.editedImpactChannels):
                raise ValueError("editedImpactChannelRationale must match editedImpactChannels")
        if (
            self.reviewStatus == ReviewStatus.EDITED
            and not self.editedText
            and self.editedImpactChannels is None
        ):
            raise ValueError(
                "editedText or editedImpactChannels is required when reviewStatus is EDITED"
            )
        return self


ClaimId = Annotated[
    str,
    Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$"),
]


class BulkClaimApprovalRequest(StrictModel):
    acknowledgedBulkApproval: Literal[True]
    expectedClaimIds: list[ClaimId] = Field(min_length=1, max_length=50)
    rationale: str | None = Field(default=None, max_length=500)

    @field_validator("expectedClaimIds")
    @classmethod
    def validateUniqueClaimIds(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("expectedClaimIds must not contain duplicates")
        return value


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
    provider: ProviderId = DEFAULT_PROVIDER
    modelId: str = Field(default=DEFAULT_MODEL, min_length=1, max_length=128)
    representativeAgentCount: int = Field(default=8, ge=0, le=100)
    decisionIntervalSteps: int = Field(default=12, ge=1, le=100)
    callBudget: int = Field(default=24, ge=0, le=500)
    maxCostUsd: float = Field(default=10.0, ge=0, le=100)
    fallbackToRules: bool = True

    @model_validator(mode="after")
    def validateProviderModelPair(self) -> LlmPolicy:
        getModel(self.provider, self.modelId)
        return self


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
    rawText: str = Field(min_length=1, max_length=100_000)
    publicationTimeAssumed: bool = False

    @model_validator(mode="after")
    def validatePointInTime(self) -> EventSourceInput:
        if self.knownAt < self.publishedAt:
            raise ValueError("knownAt must not be earlier than publishedAt")
        if self.url is not None:
            parsed = urlsplit(self.url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.port not in {None, 443}
            ):
                raise ValueError(
                    "source url must be a public HTTPS URL without credentials or a custom port"
                )
            host = parsed.hostname.rstrip(".").casefold()
            if host == "localhost" or host.endswith(".localhost"):
                raise ValueError("source url must not target localhost")
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                address = None
            if address is not None and not address.is_global:
                raise ValueError("source url must not target a private or non-global address")
        return self


class EventPackCreateRequest(StrictModel):
    title: str = Field(min_length=3, max_length=200)
    titleZh: str | None = Field(default=None, max_length=200)
    summary: str = Field(min_length=8, max_length=1_000)
    summaryZh: str | None = Field(default=None, max_length=1_000)
    asOf: datetime
    instrument: str = Field(default="CUSTOM", min_length=1, max_length=32)
    sources: list[EventSourceInput] = Field(min_length=1, max_length=24)
    acknowledgedContentReview: bool = False

    @model_validator(mode="after")
    def validateSourceCollection(self) -> EventPackCreateRequest:
        sourceIds = [source.sourceId for source in self.sources]
        if len(sourceIds) != len(set(sourceIds)):
            raise ValueError("sources must not contain duplicate sourceId values")
        if sum(len(source.rawText) for source in self.sources) > 400_000:
            raise ValueError("sources must not exceed 400000 characters in total")
        return self


class EventPackExtractRequest(StrictModel):
    useLlm: bool = True
    maximumClaims: int = Field(default=16, ge=1, le=50)
    requestedImpactChannels: list[str] = Field(
        default_factory=lambda: ["belief", "liquidity", "passiveFlow", "stopLoss"],
        max_length=12,
    )
    sources: list[EventSourceInput] = Field(default_factory=list, max_length=24)
    acknowledgedContentReview: bool = False

    @model_validator(mode="after")
    def validateSourceCollection(self) -> EventPackExtractRequest:
        sourceIds = [source.sourceId for source in self.sources]
        if len(sourceIds) != len(set(sourceIds)):
            raise ValueError("sources must not contain duplicate sourceId values")
        if sum(len(source.rawText) for source in self.sources) > 400_000:
            raise ValueError("sources must not exceed 400000 characters in total")
        return self


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
    provider: ProviderId = DEFAULT_PROVIDER
    model: str = Field(
        default=DEFAULT_MODEL,
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$",
    )
    apiKey: str = Field(min_length=8, max_length=4_096, repr=False)
    thinkingEnabled: bool = False
    maxTokens: int = Field(default=2_048, ge=256, le=APPLICATION_MAX_OUTPUT_TOKENS)
    advancedParameters: AdvancedModelParameters = Field(default_factory=AdvancedModelParameters)

    @model_validator(mode="after")
    def validateProviderModelPair(self) -> LlmConfigRequest:
        descriptor = getModel(self.provider, self.model)
        if descriptor.max_output_tokens is None:
            raise ValueError(
                f"no verified maximum output limit is available for {self.provider}/{self.model}"
            )
        if self.maxTokens > descriptor.max_output_tokens:
            raise ValueError(
                f"maxTokens exceeds the application limit for {self.provider}/{self.model}"
            )
        if self.thinkingEnabled and not descriptor.supports_thinking:
            raise ValueError(f"{self.provider}/{self.model} does not support thinking")
        validateAdvancedModelParameters(self.provider, self.advancedParameters)
        return self


class AdminLlmCredentialRequest(LlmConfigRequest):
    """管理员将供应商凭据加密保存到服务器时必须重新验证密码。"""

    currentPassword: str = Field(min_length=1, max_length=128, repr=False)


class AdminLlmCredentialDeleteRequest(StrictModel):
    currentPassword: str = Field(min_length=1, max_length=128, repr=False)


class ResultInterpretationMessage(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4_000)

    @field_validator("content")
    @classmethod
    def normalizeMessageContent(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("content must not be blank")
        if any(ord(character) < 32 and character not in {"\n", "\t"} for character in normalized):
            raise ValueError("content contains unsupported control characters")
        return normalized


class ResultInterpretationChatRequest(StrictModel):
    schemaVersion: Literal["1.0.0"] = "1.0.0"
    conversationId: str = Field(
        min_length=8,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,79}$",
    )
    clientRequestId: str = Field(
        min_length=8,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,79}$",
    )
    mode: Literal["INITIAL", "FOLLOW_UP"]
    language: Literal["en", "zh-CN"]
    reasoningSummaryRequested: bool = False
    messages: list[ResultInterpretationMessage] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def validateConversation(self) -> ResultInterpretationChatRequest:
        if sum(len(message.content) for message in self.messages) > 16_000:
            raise ValueError("conversation content exceeds 16000 characters")
        expectedRole = "user"
        for message in self.messages:
            if message.role != expectedRole:
                raise ValueError("messages must alternate user and assistant roles")
            expectedRole = "assistant" if expectedRole == "user" else "user"
        if self.messages[-1].role != "user":
            raise ValueError("messages must end with a user message")
        if self.mode == "INITIAL" and len(self.messages) != 1:
            raise ValueError("INITIAL mode requires exactly one user message")
        if self.mode == "FOLLOW_UP" and len(self.messages) < 3:
            raise ValueError("FOLLOW_UP mode requires at least one completed exchange")
        return self


class EvalRunRequest(StrictModel):
    mode: Literal["CODE_GRADER_SELF_TEST", "LIVE_CONFIGURED_MODEL"] = "CODE_GRADER_SELF_TEST"
    maximumCases: int = Field(default=3, ge=1, le=3)
