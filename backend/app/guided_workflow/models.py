"""新手引导工作流的严格状态与模型提议契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GuidedStage(StrEnum):
    EVENT_GOAL = "EVENT_GOAL"
    SOURCE_METHOD = "SOURCE_METHOD"
    SOURCE_REVIEW = "SOURCE_REVIEW"
    CLAIM_REVIEW = "CLAIM_REVIEW"
    PACK_METADATA_REVIEW = "PACK_METADATA_REVIEW"
    PACK_FREEZE_REVIEW = "PACK_FREEZE_REVIEW"
    SCENARIO_INTERVENTION = "SCENARIO_INTERVENTION"
    SCENARIO_REVIEW = "SCENARIO_REVIEW"
    PREFLIGHT = "PREFLIGHT"
    READY_TO_SUBMIT = "READY_TO_SUBMIT"
    COMPLETED = "COMPLETED"


class GuidedWorkflowStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ARCHIVED = "ARCHIVED"


class GuidedArchivedProposalStatus(StrEnum):
    APPLIED = "APPLIED"
    SUPERSEDED = "SUPERSEDED"
    DISMISSED = "DISMISSED"


class GuidedArchivedProposalReason(StrEnum):
    APPLIED_BY_HUMAN = "APPLIED_BY_HUMAN"
    REPLACED_BY_NEW_PROPOSAL = "REPLACED_BY_NEW_PROPOSAL"
    STAGE_ADVANCED_BY_HUMAN = "STAGE_ADVANCED_BY_HUMAN"
    WORKFLOW_ARCHIVED_BY_HUMAN = "WORKFLOW_ARCHIVED_BY_HUMAN"


class GuidedTurnOperationStatus(StrEnum):
    PENDING = "PENDING"
    RESULT_READY = "RESULT_READY"
    SUCCEEDED = "SUCCEEDED"
    UNKNOWN = "UNKNOWN"
    ABANDONED_BY_USER = "ABANDONED_BY_USER"


class GuidedTurnRecoveryAction(StrEnum):
    RETRY_CACHED_COMMIT = "RETRY_CACHED_COMMIT"
    ABANDON_AND_AUTHORIZE_RETRY = "ABANDON_AND_AUTHORIZE_RETRY"


class GuidedSourceMethod(StrEnum):
    PASTE = "PASTE"
    WEB_SEARCH = "WEB_SEARCH"
    COMBINED = "COMBINED"
    MANUAL = "MANUAL"


class ProposedEventMetadata(StrictModel):
    title: str = Field(min_length=3, max_length=200)
    titleZh: str | None = Field(default=None, max_length=200)
    summary: str = Field(min_length=8, max_length=1_000)
    summaryZh: str | None = Field(default=None, max_length=1_000)
    instrument: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    asOf: datetime
    asOfPrecision: Literal["DAY", "SECOND"] = "SECOND"
    researchQuestion: str = Field(min_length=8, max_length=500)


class ProposedIntervention(StrictModel):
    parameter: Literal[
        "marketMakerCapacity",
        "socialAmplification",
        "stopLossSensitivity",
        "clarificationDelay",
        "liquidityDepthMultiplier",
        "passiveFlowMultiplier",
        "informationLatency",
    ]
    baselineValue: float = Field(gt=0.0, le=4.0)
    interventionValue: float = Field(gt=0.0, le=4.0)
    explanation: str = Field(min_length=8, max_length=500)

    @model_validator(mode="after")
    def requireDifference(self) -> ProposedIntervention:
        if self.baselineValue == self.interventionValue:
            raise ValueError("baselineValue and interventionValue must differ")
        # 与 schemas.InterventionConfig 保持相同边界，但不能直接导入后者：
        # cognition.prompts 在包初始化期间会导入本模型，直接引用 schemas 会形成循环导入。
        parameterMaximum = {
            "marketMakerCapacity": 3.0,
            "socialAmplification": 3.0,
            "stopLossSensitivity": 3.0,
            "clarificationDelay": 4.0,
            "liquidityDepthMultiplier": 3.0,
            "passiveFlowMultiplier": 3.0,
            "informationLatency": 4.0,
        }[self.parameter]
        if self.baselineValue > parameterMaximum or self.interventionValue > parameterMaximum:
            raise ValueError(f"values for {self.parameter} must not exceed {parameterMaximum}")
        return self


class GuidedWorkflowProposal(StrictModel):
    schemaVersion: Literal["guided_proposal_v1.0.0"] = "guided_proposal_v1.0.0"
    stage: GuidedStage
    assistantMessage: str = Field(min_length=8, max_length=2_000)
    clarificationRequired: bool
    proposedEventMetadata: ProposedEventMetadata | None = None
    proposedSourceMethod: GuidedSourceMethod | None = None
    proposedSearchQueries: tuple[str, ...] = Field(default=(), max_length=4)
    proposedIntervention: ProposedIntervention | None = None
    nextQuestionOptions: tuple[str, ...] = Field(default=(), max_length=5)
    readyForHumanReview: bool
    blockedReasons: tuple[str, ...] = Field(default=(), max_length=8)
    missingFields: tuple[
        Literal["title", "summary", "instrument", "asOf", "researchQuestion"], ...
    ] = Field(default=(), max_length=5)

    @model_validator(mode="after")
    def validateStageAuthority(self) -> GuidedWorkflowProposal:
        if self.proposedEventMetadata is not None and self.stage not in {
            GuidedStage.EVENT_GOAL,
            GuidedStage.PACK_METADATA_REVIEW,
        }:
            raise ValueError("event metadata may only be proposed in an event metadata stage")
        if self.proposedSourceMethod is not None and self.stage is not GuidedStage.SOURCE_METHOD:
            raise ValueError("source method may only be proposed in SOURCE_METHOD")
        if self.proposedSearchQueries and self.stage not in {
            GuidedStage.SOURCE_METHOD,
            GuidedStage.SOURCE_REVIEW,
        }:
            raise ValueError("search queries may only be proposed during source collection")
        if (
            self.proposedIntervention is not None
            and self.stage is not GuidedStage.SCENARIO_INTERVENTION
        ):
            raise ValueError("an intervention may only be proposed in SCENARIO_INTERVENTION")
        for query in self.proposedSearchQueries:
            if not 2 <= len(query.strip()) <= 70:
                raise ValueError("each proposed search query must contain 2 to 70 characters")
        if self.proposedEventMetadata is not None and self.missingFields:
            raise ValueError("a complete event metadata proposal cannot declare missing fields")
        if self.readyForHumanReview and self.missingFields:
            raise ValueError("a proposal with missing fields cannot be ready for human review")
        return self


class GuidedWorkflowMessage(StrictModel):
    id: str
    role: Literal["user", "assistant"]
    stage: GuidedStage
    content: str
    proposalId: str | None = None
    createdAt: datetime


class GuidedWorkflowDraft(StrictModel):
    eventMetadata: ProposedEventMetadata | None = None
    sourceMethod: GuidedSourceMethod | None = None
    searchQueries: tuple[str, ...] = ()
    intervention: ProposedIntervention | None = None
    eventPackBuildId: str | None = None
    eventPackId: str | None = None
    scenarioId: str | None = None


class GuidedArchivedProposal(StrictModel):
    schemaVersion: Literal["guided_archived_proposal_v1.0.0"] = "guided_archived_proposal_v1.0.0"
    id: str = Field(
        min_length=8,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,79}$",
    )
    proposal: GuidedWorkflowProposal
    status: GuidedArchivedProposalStatus
    archivedAt: datetime
    reason: GuidedArchivedProposalReason


class GuidedWorkflowView(StrictModel):
    schemaVersion: Literal["1.0.0"] = "1.0.0"
    id: str
    stage: GuidedStage
    status: GuidedWorkflowStatus
    version: int = Field(ge=1)
    language: Literal["en", "zh-CN"]
    draft: GuidedWorkflowDraft
    pendingProposal: GuidedWorkflowProposal | None = None
    pendingProposalId: str | None = None
    archivedProposals: tuple[GuidedArchivedProposal, ...] = ()
    messages: tuple[GuidedWorkflowMessage, ...]
    createdAt: datetime
    updatedAt: datetime


class GuidedCreateRequest(StrictModel):
    language: Literal["en", "zh-CN"] = "en"


class GuidedTurnRequest(StrictModel):
    message: str = Field(min_length=1, max_length=2_000)
    language: Literal["en", "zh-CN"]
    expectedVersion: int = Field(ge=1)
    clientRequestId: str = Field(
        min_length=8,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,79}$",
    )


class GuidedTurnOperationView(StrictModel):
    schemaVersion: Literal["1.0.0"] = "1.0.0"
    workflowId: str
    clientRequestId: str
    expectedVersion: int = Field(ge=1)
    status: GuidedTurnOperationStatus
    errorCode: str | None = None
    requestMessage: str | None = None
    language: Literal["en", "zh-CN"] | None = None
    cachedProposalAvailable: bool
    supersedesClientRequestId: str | None = None
    authorizedRetryClientRequestId: str | None = None
    recoveryOptions: tuple[GuidedTurnRecoveryAction, ...] = ()
    providerRequestId: str | None = None
    httpResponseReceived: bool | None = None
    usageReceived: bool | None = None
    parseCompleted: bool | None = None
    failureStage: str | None = None
    createdAt: datetime
    updatedAt: datetime


class GuidedTurnRecoveryRequest(StrictModel):
    recoveryRequestId: str = Field(
        min_length=8,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,79}$",
    )
    action: GuidedTurnRecoveryAction
    expectedVersion: int = Field(ge=1)
    newClientRequestId: str | None = Field(
        default=None,
        min_length=8,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,79}$",
    )

    @model_validator(mode="after")
    def validateRecoveryAction(self) -> GuidedTurnRecoveryRequest:
        if (
            self.action is GuidedTurnRecoveryAction.ABANDON_AND_AUTHORIZE_RETRY
            and self.newClientRequestId is None
        ):
            raise ValueError("newClientRequestId is required when authorizing a retry")
        if (
            self.action is GuidedTurnRecoveryAction.RETRY_CACHED_COMMIT
            and self.newClientRequestId is not None
        ):
            raise ValueError("newClientRequestId is only valid when authorizing a retry")
        return self


class GuidedArchiveRequest(StrictModel):
    expectedVersion: int = Field(ge=1)


class GuidedProposalActionRequest(StrictModel):
    proposalId: str = Field(
        min_length=8,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,79}$",
    )
    expectedVersion: int = Field(ge=1)


class GuidedAdvanceRequest(StrictModel):
    expectedVersion: int = Field(ge=1)
    acknowledgedHumanReview: StrictBool

    @field_validator("acknowledgedHumanReview")
    @classmethod
    def requireExplicitHumanReview(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("acknowledgedHumanReview must be true")
        return value


class GuidedLinkRequest(StrictModel):
    expectedVersion: int = Field(ge=1)
    eventPackBuildId: str | None = Field(default=None, min_length=8, max_length=128)
    eventPackId: str | None = Field(default=None, min_length=3, max_length=128)
    scenarioId: str | None = Field(default=None, min_length=3, max_length=128)

    @model_validator(mode="after")
    def requireArtifact(self) -> GuidedLinkRequest:
        if self.eventPackBuildId is None and self.eventPackId is None and self.scenarioId is None:
            raise ValueError("at least one artifact identifier is required")
        return self
