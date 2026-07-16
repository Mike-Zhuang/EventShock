"""Study HTTP API 的严格请求契约。

这些模型只允许当前确定性内核能够审计的参数。设计预览和正式运行共用同一
因子定义，避免预览通过、运行时却悄悄解释成另一组参数。
"""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.schemas import InterventionParameter, MarketConfig, NetworkConfig, PopulationConfig
from backend.app.study.models import DesignKind, EvidenceBasis, ExpectedDirection, StudyClaimLevel

StudyOutcomeId = Literal[
    "max-drawdown-pct",
    "realized-volatility-pct",
    "max-spread-bps",
    "min-depth",
    "recovery-steps",
    "total-volume",
    "order-imbalance",
    "cascade-score",
    "network-reach-rate",
    "information-delay-steps",
    "liquidity-stress-index",
    "tail-loss-probability",
    "abnormal-return-pct",
]

StudyFactorPath = Literal[
    "intervention.value",
    "market.fee_bps",
    "market.latency_ms",
    "market.price_collar_bps",
    "network.correction_reach",
    "network.echo_chamber_strength",
    "network.rewiring_probability",
    "population.institutional_share",
]
StudyStatement = Annotated[str, Field(min_length=8, max_length=500)]


class StrictStudyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StudyOutcomeInput(StrictStudyModel):
    outcomeId: StudyOutcomeId
    familyId: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_.-]*$")
    expectedDirection: ExpectedDirection
    rationale: str = Field(min_length=8, max_length=500)
    minimumEffectOfInterest: float | None = Field(default=None, ge=0, le=1_000_000)


class StudyPreregistrationInput(StrictStudyModel):
    studyId: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_.-]*$")
    question: str = Field(min_length=12, max_length=1_000)
    claimLevel: StudyClaimLevel = StudyClaimLevel.MODEL_INTERNAL_SENSITIVITY
    primaryOutcomes: list[StudyOutcomeInput] = Field(min_length=2, max_length=4)
    secondaryOutcomes: list[StudyOutcomeInput] = Field(min_length=1, max_length=8)
    exclusionRules: list[StudyStatement] = Field(min_length=1, max_length=12)
    supportCriterion: str = Field(min_length=8, max_length=500)
    contradictionCriterion: str = Field(min_length=8, max_length=500)
    inconclusiveCriterion: str = Field(min_length=8, max_length=500)
    knownLimitations: list[StudyStatement] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def validateOutcomeIds(self) -> StudyPreregistrationInput:
        outcomeIds = [
            outcome.outcomeId for outcome in (*self.primaryOutcomes, *self.secondaryOutcomes)
        ]
        if len(set(outcomeIds)) != len(outcomeIds):
            raise ValueError("primary and secondary outcome IDs must be unique")
        return self


class StudyFactorInput(StrictStudyModel):
    parameterPath: StudyFactorPath
    baselineValue: float = Field(ge=0, le=60_000)
    levels: list[float] | None = Field(default=None, min_length=2, max_length=4)
    lower: float | None = Field(default=None, ge=0, le=60_000)
    upper: float | None = Field(default=None, ge=0, le=60_000)
    rationale: str = Field(min_length=8, max_length=500)
    evidenceBasis: EvidenceBasis = EvidenceBasis.ASSUMPTION
    sourceReference: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validateEvidenceAndShape(self) -> StudyFactorInput:
        if self.evidenceBasis is EvidenceBasis.EVIDENCE_BOUND and not self.sourceReference:
            raise ValueError("sourceReference is required for evidence-bound factors")
        if self.levels is not None:
            if self.lower is not None or self.upper is not None:
                raise ValueError("factor levels cannot be combined with lower/upper")
            if len(set(self.levels)) != len(self.levels):
                raise ValueError("factor levels must be unique")
        elif self.lower is None or self.upper is None:
            raise ValueError("a factor requires either levels or both lower and upper")
        elif self.lower >= self.upper:
            raise ValueError("factor lower must be smaller than upper")
        return self


class StudyDesignInput(StrictStudyModel):
    kind: DesignKind
    factors: list[StudyFactorInput] = Field(min_length=1, max_length=4)
    sampleCount: int | None = Field(default=None, ge=3, le=16)
    designSeed: int = Field(default=2_026_070_700, ge=0, le=2_147_483_000)

    @model_validator(mode="after")
    def validateDesignShape(self) -> StudyDesignInput:
        paths = [factor.parameterPath for factor in self.factors]
        if len(set(paths)) != len(paths):
            raise ValueError("study factor paths must be unique")
        if self.kind is DesignKind.FULL_FACTORIAL:
            if self.sampleCount is not None:
                raise ValueError("sampleCount is only valid for LATIN_HYPERCUBE")
            if any(factor.levels is None for factor in self.factors):
                raise ValueError("FULL_FACTORIAL factors require levels")
        else:
            if self.sampleCount is None:
                raise ValueError("LATIN_HYPERCUBE requires sampleCount")
            if any(factor.lower is None or factor.upper is None for factor in self.factors):
                raise ValueError("LATIN_HYPERCUBE factors require lower and upper")
        return self


class StudyDesignPreviewRequest(StrictStudyModel):
    design: StudyDesignInput
    matchedSeedCount: int = Field(default=2, ge=2, le=4)
    populationSize: int = Field(default=14, ge=14, le=28)
    steps: int = Field(default=30, ge=30, le=60)


class StudyExecutionInput(StrictStudyModel):
    interventionParameter: InterventionParameter = InterventionParameter.MARKET_MAKER_CAPACITY
    baselineInterventionValue: float = Field(default=1.0, gt=0, le=4)
    matchedSeedCount: int = Field(default=2, ge=2, le=4)
    seedRoot: int = Field(default=2_026_070_700, ge=1, le=2_147_483_000)
    populationSize: int = Field(default=14, ge=14, le=28)
    steps: int = Field(default=30, ge=30, le=60)
    frozenCognitiveRepresentativeCount: int = Field(default=2, ge=0, le=4)
    market: MarketConfig = Field(default_factory=MarketConfig)
    population: PopulationConfig = Field(default_factory=PopulationConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)


class StudyRunApiRequest(StrictStudyModel):
    eventPackId: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    preregistration: StudyPreregistrationInput
    design: StudyDesignInput
    execution: StudyExecutionInput = Field(default_factory=StudyExecutionInput)
    nullToleranceByOutcome: dict[str, float] = Field(min_length=2, max_length=4)
    alpha: float = Field(default=0.05, gt=0, lt=1)
    bootstrapResamples: int = Field(default=100, ge=100, le=500)
    analysisSeed: int = Field(default=719, ge=0, le=2_147_483_000)
    acknowledgedModelInternalOnly: bool
    acknowledgedProxyAblations: bool

    @model_validator(mode="after")
    def validatePreregistrationBoundary(self) -> StudyRunApiRequest:
        expectedIds = {outcome.outcomeId for outcome in self.preregistration.primaryOutcomes}
        if set(self.nullToleranceByOutcome) != expectedIds:
            raise ValueError(
                "nullToleranceByOutcome must exactly match preregistered primary outcomes"
            )
        if any(
            not math.isfinite(value) or value < 0 or value > 1_000_000
            for value in self.nullToleranceByOutcome.values()
        ):
            raise ValueError("negative-control tolerances must be between 0 and 1,000,000")
        if not self.acknowledgedModelInternalOnly:
            raise ValueError("acknowledgedModelInternalOnly must be true")
        if not self.acknowledgedProxyAblations:
            raise ValueError("acknowledgedProxyAblations must be true")
        return self
