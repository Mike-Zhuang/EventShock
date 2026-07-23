"""确定性新手工作流控制器；模型只能提出严格草稿，不能迁移状态。"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from backend.app.guided_workflow.models import (
    GuidedAdvanceRequest,
    GuidedLinkRequest,
    GuidedProposalActionRequest,
    GuidedStage,
    GuidedTurnRequest,
    GuidedWorkflowDraft,
    GuidedWorkflowMessage,
    GuidedWorkflowProposal,
    GuidedWorkflowView,
)
from backend.app.guided_workflow.repository import GuidedTurnClaim, GuidedWorkflowRepository
from backend.app.security import scanTextContent

if TYPE_CHECKING:
    from backend.app.guided_workflow.artifacts import GuidedArtifactValidator

_NEXT_STAGE: dict[GuidedStage, GuidedStage] = {
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


class GuidedWorkflowService:
    def __init__(
        self,
        repository: GuidedWorkflowRepository,
        artifactValidator: GuidedArtifactValidator | None = None,
    ) -> None:
        self.repository = repository
        self.artifactValidator = artifactValidator

    def create(self, ownerUserId: str, language: str) -> GuidedWorkflowView:
        workflowId = f"guided-{uuid.uuid4().hex}"
        greeting = (
            "我们会分阶段完成事件目标、来源、主张、事件包、单一干预和运行前检查。"
            "AI 只能提出草稿；每次应用、审核、冻结和运行都由你明确确认。先用一两句话"
            "说明你想研究的事件、对象和问题。"
            if language == "zh-CN"
            else "We will work through the event goal, sources, claims, Event Pack, one "
            "intervention, and preflight in bounded stages. AI can only propose drafts; "
            "you explicitly apply, review, freeze, and run every consequential step. Start "
            "with one or two sentences describing the event, instrument, and question."
        )
        return self.repository.create(
            workflowId=workflowId,
            ownerUserId=ownerUserId,
            language=language,
            greeting=greeting,
            now=datetime.now(UTC),
        )

    def get(self, workflowId: str, ownerUserId: str) -> GuidedWorkflowView:
        return self.repository.get(workflowId, ownerUserId)

    def list(self, ownerUserId: str) -> list[GuidedWorkflowView]:
        return self.repository.list(ownerUserId)

    def saveTurn(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        request: GuidedTurnRequest,
        proposal: GuidedWorkflowProposal,
    ) -> GuidedWorkflowView:
        """兼容直接 service 调用：本地提议先校验，再自行 claim 并提交。"""

        self._validateUserMessage(request.message)
        current = self.repository.get(workflowId, ownerUserId)
        if proposal.stage is not current.stage:
            raise ValueError("model proposal stage does not match the deterministic workflow")
        claim = self.claimTurn(
            workflowId=workflowId,
            ownerUserId=ownerUserId,
            request=request,
        )
        if claim.replayed:
            return claim.workflow
        try:
            return self.completeTurn(
                workflowId=workflowId,
                ownerUserId=ownerUserId,
                request=request,
                claim=claim,
                proposal=proposal,
                recordAudit=False,
            )
        except Exception as error:
            self.markTurnUnknown(
                workflowId=workflowId,
                ownerUserId=ownerUserId,
                request=request,
                claim=claim,
                errorCode=type(error).__name__,
            )
            raise

    def claimTurn(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        request: GuidedTurnRequest,
    ) -> GuidedTurnClaim:
        """在模型调用前完成二次内容扫描和持久化幂等占用。"""

        self._validateUserMessage(request.message)
        return self.repository.claimTurn(
            workflowId=workflowId,
            ownerUserId=ownerUserId,
            expectedVersion=request.expectedVersion,
            clientRequestId=request.clientRequestId,
            requestHash=self._requestHash(request),
            now=datetime.now(UTC),
        )

    def completeTurn(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        request: GuidedTurnRequest,
        claim: GuidedTurnClaim,
        proposal: GuidedWorkflowProposal,
        recordAudit: bool,
    ) -> GuidedWorkflowView:
        if claim.replayed or claim.claimToken is None:
            return claim.workflow
        if proposal.stage is not claim.workflow.stage:
            raise ValueError("model proposal stage does not match the deterministic workflow")
        now = datetime.now(UTC)
        proposalId = f"proposal-{uuid.uuid4().hex}"
        auditPayload = (
            {
                "stage": claim.workflow.stage.value,
                "proposalId": proposalId,
                "messageHash": hashlib.sha256(request.message.encode()).hexdigest(),
                "messageLength": len(request.message),
            }
            if recordAudit
            else None
        )
        return self.repository.completeTurn(
            workflowId=workflowId,
            ownerUserId=ownerUserId,
            expectedVersion=request.expectedVersion,
            clientRequestId=request.clientRequestId,
            requestHash=claim.requestHash,
            claimToken=claim.claimToken,
            userMessage=GuidedWorkflowMessage(
                id=f"msg-{uuid.uuid4().hex}",
                role="user",
                stage=claim.workflow.stage,
                content=request.message.strip(),
                createdAt=now,
            ),
            assistantMessage=GuidedWorkflowMessage(
                id=f"msg-{uuid.uuid4().hex}",
                role="assistant",
                stage=claim.workflow.stage,
                content=proposal.assistantMessage,
                proposalId=proposalId,
                createdAt=now,
            ),
            proposal=proposal,
            proposalId=proposalId,
            language=request.language,
            now=now,
            auditPayload=auditPayload,
        )

    def markTurnUnknown(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        request: GuidedTurnRequest,
        claim: GuidedTurnClaim,
        errorCode: str,
    ) -> None:
        if claim.replayed or claim.claimToken is None:
            return
        self.repository.markTurnUnknown(
            workflowId=workflowId,
            ownerUserId=ownerUserId,
            clientRequestId=request.clientRequestId,
            requestHash=claim.requestHash,
            claimToken=claim.claimToken,
            errorCode=errorCode,
            now=datetime.now(UTC),
        )

    def deterministicProposal(
        self,
        *,
        workflow: GuidedWorkflowView,
        language: str,
    ) -> GuidedWorkflowProposal:
        """没有临时 API 凭据时仍给出透明、非 AI 的下一步引导。"""

        stageLabels = {
            GuidedStage.EVENT_GOAL: (
                "请先配置 AI，再让我从描述中提议事件元数据；你也可以继续使用专家手动入口。"
                if language == "zh-CN"
                else "Configure an AI provider so I can propose event metadata from your "
                "description, or continue through the expert manual entry."
            ),
            GuidedStage.SOURCE_METHOD: (
                "请选择粘贴原文、联网搜索、两者结合或手动来源。"
                if language == "zh-CN"
                else "Choose pasted text, web search, a combination, or manual sources."
            ),
        }
        return GuidedWorkflowProposal(
            stage=workflow.stage,
            assistantMessage=stageLabels.get(
                workflow.stage,
                (
                    "当前阶段需要你在对应审核页面完成明确人工操作，再回来继续。"
                    if language == "zh-CN"
                    else "This stage requires an explicit human action in the linked review "
                    "page before the workflow can continue."
                ),
            ),
            clarificationRequired=True,
            readyForHumanReview=False,
            blockedReasons=("LLM_CREDENTIAL_NOT_CONFIGURED",),
        )

    def applyProposal(
        self,
        workflowId: str,
        ownerUserId: str,
        request: GuidedProposalActionRequest,
    ) -> GuidedWorkflowView:
        return self.repository.applyProposal(
            workflowId=workflowId,
            ownerUserId=ownerUserId,
            proposalId=request.proposalId,
            expectedVersion=request.expectedVersion,
            now=datetime.now(UTC),
        )

    def advance(
        self,
        workflowId: str,
        ownerUserId: str,
        request: GuidedAdvanceRequest,
        credentialSessionId: str | None = None,
    ) -> GuidedWorkflowView:
        if not request.acknowledgedHumanReview:
            raise ValueError("advancing requires explicit human review acknowledgement")
        current = self.repository.get(workflowId, ownerUserId)
        self._validateStageCompletion(current)
        if self.artifactValidator is not None:
            self.artifactValidator.assertStageCompletion(
                workflow=current,
                ownerUserId=ownerUserId,
                credentialSessionId=credentialSessionId,
            )
        nextStage = _NEXT_STAGE.get(current.stage)
        if nextStage is None:
            raise ValueError("the guided workflow cannot advance from its current stage")
        return self.repository.advance(
            workflowId=workflowId,
            ownerUserId=ownerUserId,
            expectedVersion=request.expectedVersion,
            nextStage=nextStage,
            now=datetime.now(UTC),
        )

    def linkArtifacts(
        self,
        workflowId: str,
        ownerUserId: str,
        request: GuidedLinkRequest,
    ) -> GuidedWorkflowView:
        current = self.repository.get(workflowId, ownerUserId)
        draft = current.draft.model_copy(
            update={
                "eventPackBuildId": request.eventPackBuildId
                if request.eventPackBuildId is not None
                else current.draft.eventPackBuildId,
                "eventPackId": request.eventPackId
                if request.eventPackId is not None
                else current.draft.eventPackId,
                "scenarioId": request.scenarioId
                if request.scenarioId is not None
                else current.draft.scenarioId,
            }
        )
        validatedDraft = GuidedWorkflowDraft.model_validate(draft)
        if self.artifactValidator is not None:
            self.artifactValidator.assertLinkUpdate(
                workflow=current,
                ownerUserId=ownerUserId,
                request=request,
                draft=validatedDraft,
            )
        return self.repository.linkArtifacts(
            workflowId=workflowId,
            ownerUserId=ownerUserId,
            expectedVersion=request.expectedVersion,
            draft=validatedDraft,
            now=datetime.now(UTC),
        )

    @staticmethod
    def _validateUserMessage(value: str) -> None:
        result = scanTextContent(value, field="guidedWorkflowMessage")
        if result.decision.value != "ALLOW":
            raise ValueError(
                "guided workflow messages must not contain secrets, personal data, "
                "executable content, or prompt-injection instructions"
            )

    @staticmethod
    def _requestHash(request: GuidedTurnRequest) -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "message": request.message,
                    "language": request.language,
                    "expectedVersion": request.expectedVersion,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    @staticmethod
    def _validateStageCompletion(workflow: GuidedWorkflowView) -> None:
        draft = workflow.draft
        requirements: dict[GuidedStage, bool] = {
            GuidedStage.EVENT_GOAL: draft.eventMetadata is not None,
            GuidedStage.SOURCE_METHOD: draft.sourceMethod is not None,
            GuidedStage.SOURCE_REVIEW: draft.eventPackBuildId is not None
            or draft.eventPackId is not None,
            GuidedStage.CLAIM_REVIEW: draft.eventPackId is not None,
            GuidedStage.PACK_METADATA_REVIEW: draft.eventMetadata is not None,
            GuidedStage.PACK_FREEZE_REVIEW: draft.eventPackId is not None,
            GuidedStage.SCENARIO_INTERVENTION: draft.intervention is not None,
            GuidedStage.SCENARIO_REVIEW: draft.scenarioId is not None,
            GuidedStage.PREFLIGHT: draft.scenarioId is not None,
            GuidedStage.READY_TO_SUBMIT: draft.scenarioId is not None,
        }
        if not requirements.get(workflow.stage, False):
            raise ValueError(
                "the current stage is incomplete; review and link the required draft first"
            )
