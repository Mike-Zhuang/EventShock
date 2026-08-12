"""复用已审核研究资产的确定性引导路径。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.account_capabilities import AccountCapabilityRepository
from backend.app.database import Database
from backend.app.guided_workflow.models import (
    GuidedReviewItem,
    GuidedSourceMethod,
    GuidedStage,
    GuidedWorkflowDraft,
    GuidedWorkflowProposal,
    ProposedEventMetadata,
    ProposedIntervention,
)

if TYPE_CHECKING:
    from backend.app.guided_workflow.models import GuidedWorkflowView

PREPARED_GUIDED_PATH_CAPABILITY = "PREPARED_GUIDED_PATH_V1"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreparedStageCopy(_StrictModel):
    assistantMessage: str = Field(min_length=8, max_length=2_000)
    nextQuestionOptions: tuple[str, ...] = Field(default=(), max_length=5)
    reviewItems: tuple[GuidedReviewItem, ...] = Field(default=(), max_length=24)
    preparationSteps: tuple[str, ...] = Field(default=(), max_length=6)


class PreparedGuidedPathConfiguration(_StrictModel):
    schemaVersion: Literal["prepared_guided_path_v1.0.0"] = "prepared_guided_path_v1.0.0"
    eventPackId: str = Field(min_length=1, max_length=100)
    scenarioId: str = Field(min_length=1, max_length=100)
    experimentId: str = Field(min_length=1, max_length=100)
    eventMetadata: ProposedEventMetadata
    sourceMethod: GuidedSourceMethod
    intervention: ProposedIntervention
    stageCopy: dict[Literal["en", "zh-CN"], dict[GuidedStage, PreparedStageCopy]]


class PreparedGuidedPathService:
    """只在服务器显式授权且资产仍完整时启用预制路径。"""

    def __init__(
        self,
        database: Database,
        capabilities: AccountCapabilityRepository,
    ) -> None:
        self.database = database
        self.capabilities = capabilities

    def configuration(self, ownerUserId: str) -> PreparedGuidedPathConfiguration | None:
        raw = self.capabilities.getConfiguration(
            userId=ownerUserId,
            capability=PREPARED_GUIDED_PATH_CAPABILITY,
        )
        if raw is None:
            return None
        configuration = PreparedGuidedPathConfiguration.model_validate(raw)
        self._assertReady(ownerUserId, configuration)
        return configuration

    def initialDraft(self, ownerUserId: str) -> GuidedWorkflowDraft | None:
        configuration = self.configuration(ownerUserId)
        if configuration is None:
            return None
        # 元数据和干预仍由用户在正常候选卡中明确应用；这里只关联已经审核、
        # 冻结并完成的服务器资产，保证展示路径与保存的结果属于同一研究对象。
        return GuidedWorkflowDraft(
            eventPackId=configuration.eventPackId,
            scenarioId=configuration.scenarioId,
            experimentId=configuration.experimentId,
        )

    def proposal(
        self,
        *,
        ownerUserId: str,
        stage: GuidedStage,
        language: Literal["en", "zh-CN"],
    ) -> GuidedWorkflowProposal | None:
        configuration = self.configuration(ownerUserId)
        if configuration is None:
            return None
        stageCopy = configuration.stageCopy.get(language, {}).get(stage)
        if stageCopy is None:
            return None
        common: dict[str, Any] = {
            "stage": stage,
            "assistantMessage": stageCopy.assistantMessage,
            "clarificationRequired": False,
            "nextQuestionOptions": stageCopy.nextQuestionOptions,
            "readyForHumanReview": True,
            "reviewItems": stageCopy.reviewItems,
            "preparationSteps": stageCopy.preparationSteps,
        }
        if stage is GuidedStage.EVENT_GOAL:
            return GuidedWorkflowProposal(
                **common,
                proposedEventMetadata=configuration.eventMetadata,
            )
        if stage is GuidedStage.SOURCE_METHOD:
            return GuidedWorkflowProposal(
                **common,
                proposedSourceMethod=configuration.sourceMethod,
            )
        if stage is GuidedStage.SCENARIO_INTERVENTION:
            return GuidedWorkflowProposal(
                **common,
                proposedIntervention=configuration.intervention,
            )
        return GuidedWorkflowProposal(**common)

    def nextStage(self, ownerUserId: str, currentStage: GuidedStage) -> GuidedStage | None:
        configuration = self.configuration(ownerUserId)
        if configuration is None:
            return None
        fullReviewStages = {
            GuidedStage.EVENT_GOAL: GuidedStage.SOURCE_METHOD,
            GuidedStage.SOURCE_METHOD: GuidedStage.SOURCE_REVIEW,
            GuidedStage.SOURCE_REVIEW: GuidedStage.CLAIM_REVIEW,
            GuidedStage.CLAIM_REVIEW: GuidedStage.PACK_METADATA_REVIEW,
            GuidedStage.PACK_METADATA_REVIEW: GuidedStage.PACK_FREEZE_REVIEW,
            GuidedStage.PACK_FREEZE_REVIEW: GuidedStage.SCENARIO_INTERVENTION,
            GuidedStage.SCENARIO_INTERVENTION: GuidedStage.SCENARIO_REVIEW,
            GuidedStage.SCENARIO_REVIEW: GuidedStage.PREFLIGHT,
            GuidedStage.PREFLIGHT: GuidedStage.READY_TO_SUBMIT,
            GuidedStage.READY_TO_SUBMIT: GuidedStage.COMPLETED,
        }
        return fullReviewStages.get(currentStage)

    def assertStageReviewComplete(
        self,
        ownerUserId: str,
        workflow: GuidedWorkflowView,
    ) -> None:
        """受控路径也必须留下当前阶段候选已被人工应用的证据。"""

        if self.configuration(ownerUserId) is None:
            return
        if not any(
            archived.status.value == "APPLIED" and archived.proposal.stage is workflow.stage
            for archived in workflow.archivedProposals
        ):
            raise ValueError(
                "the current guided stage requires an explicitly reviewed and applied proposal"
            )

    def _assertReady(
        self,
        ownerUserId: str,
        configuration: PreparedGuidedPathConfiguration,
    ) -> None:
        eventPackDraft = self.database.getEventPackDraft(
            ownerUserId,
            configuration.eventPackId,
        )
        if eventPackDraft is None or not eventPackDraft["frozen"]:
            raise ValueError("prepared guided path Event Pack must remain frozen and owned")
        scenario = self.database.getScenario(configuration.scenarioId, ownerUserId)
        if scenario is None or not scenario["frozen"]:
            raise ValueError("prepared guided path scenario must remain frozen and owned")
        if scenario["config"].get("eventPackId") != configuration.eventPackId:
            raise ValueError("prepared guided path scenario and Event Pack do not match")
        experiment = self.database.getExperiment(configuration.experimentId, ownerUserId)
        if (
            experiment is None
            or experiment["status"] != "COMPLETED"
            or experiment.get("result") is None
        ):
            raise ValueError("prepared guided path experiment must remain completed and owned")
        if experiment["request"].get("eventPackId") != configuration.eventPackId:
            raise ValueError("prepared guided path experiment and Event Pack do not match")
        llmPolicy = experiment["request"].get("llmPolicy") or {}
        manifest = (experiment.get("result") or {}).get("manifest") or {}
        cognition = (experiment.get("result") or {}).get("cognition") or {}
        if llmPolicy.get("mode") != "HYBRID_LLM":
            raise ValueError("guided path experiment must use hybrid LLM cognition")
        if manifest.get("agentMode") != "HYBRID_LLM" or not manifest.get("llmExternalModelUsed"):
            raise ValueError("guided path experiment must contain verified external LLM decisions")
        if (
            int(manifest.get("llmFallbackCount") or 0) != 0
            or int(cognition.get("fallbackCount") or 0) != 0
        ):
            raise ValueError("guided path experiment must not contain rule fallbacks")
        if (
            cognition.get("resolvedMode") != "HYBRID_LLM"
            or int(cognition.get("attemptedCalls") or 0) <= 0
            or int(cognition.get("structuredValidCalls") or 0) <= 0
            or int(cognition.get("calls") or 0) <= 0
        ):
            raise ValueError("guided path experiment must contain validated LLM cognition calls")
