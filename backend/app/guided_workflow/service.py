"""确定性新手工作流控制器；模型只能提出严格草稿，不能迁移状态。"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from backend.app.guided_workflow.models import (
    GuidedAdvanceRequest,
    GuidedArchiveRequest,
    GuidedLinkRequest,
    GuidedProposalActionRequest,
    GuidedStage,
    GuidedTurnOperationView,
    GuidedTurnRecoveryAction,
    GuidedTurnRecoveryRequest,
    GuidedTurnRequest,
    GuidedWorkflowDraft,
    GuidedWorkflowMessage,
    GuidedWorkflowProposal,
    GuidedWorkflowView,
)
from backend.app.guided_workflow.repository import (
    GuidedCachedTurn,
    GuidedTurnClaim,
    GuidedWorkflowRepository,
)
from backend.app.guided_workflow.stage_openings import (
    GuidedLanguage,
    guidedStageOpening,
    guidedStageOpeningMessageId,
)
from backend.app.security import scanTextContent

if TYPE_CHECKING:
    from backend.app.guided_workflow.artifacts import GuidedArtifactValidator
    from backend.app.prepared_guided_path import PreparedGuidedPathService

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
        preparedPath: PreparedGuidedPathService | None = None,
    ) -> None:
        self.repository = repository
        self.artifactValidator = artifactValidator
        self.preparedPath = preparedPath

    def create(self, ownerUserId: str, language: GuidedLanguage) -> GuidedWorkflowView:
        workflowId = f"guided-{uuid.uuid4().hex}"
        initialDraft = (
            self.preparedPath.initialDraft(ownerUserId) if self.preparedPath is not None else None
        )
        return self.repository.create(
            workflowId=workflowId,
            ownerUserId=ownerUserId,
            language=language,
            greeting=guidedStageOpening(GuidedStage.EVENT_GOAL, language),
            now=datetime.now(UTC),
            initialDraft=initialDraft,
        )

    def hasPreparedPath(self, ownerUserId: str) -> bool:
        return (
            self.preparedPath is not None
            and self.preparedPath.configuration(ownerUserId) is not None
        )

    def preparedProposal(
        self,
        *,
        ownerUserId: str,
        workflow: GuidedWorkflowView,
        language: str,
    ) -> GuidedWorkflowProposal | None:
        if self.preparedPath is None:
            return None
        return self.preparedPath.proposal(
            ownerUserId=ownerUserId,
            stage=workflow.stage,
            language="zh-CN" if language == "zh-CN" else "en",
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
            self.cacheValidatedProposal(
                workflowId=workflowId,
                ownerUserId=ownerUserId,
                request=request,
                claim=claim,
                proposal=proposal,
            )
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
            requestMessage=request.message.strip(),
            language=request.language,
            now=datetime.now(UTC),
        )

    def replayTurnIfKnown(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        request: GuidedTurnRequest,
    ) -> GuidedWorkflowView | None:
        """在查凭据前恢复既有幂等结果，不为新请求创建占用记录。"""

        self._validateUserMessage(request.message)
        return self.repository.replayTurnIfKnown(
            workflowId=workflowId,
            ownerUserId=ownerUserId,
            clientRequestId=request.clientRequestId,
            requestHash=self._requestHash(request),
        )

    def cacheValidatedProposal(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        request: GuidedTurnRequest,
        claim: GuidedTurnClaim,
        proposal: GuidedWorkflowProposal,
    ) -> None:
        if claim.replayed or claim.claimToken is None:
            return
        if proposal.stage is not claim.workflow.stage:
            raise ValueError("model proposal stage does not match the deterministic workflow")
        self.repository.cacheValidatedProposal(
            workflowId=workflowId,
            ownerUserId=ownerUserId,
            clientRequestId=request.clientRequestId,
            requestHash=claim.requestHash,
            claimToken=claim.claimToken,
            proposal=proposal,
            now=datetime.now(UTC),
        )

    def recordTurnProviderEvidence(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        request: GuidedTurnRequest,
        claim: GuidedTurnClaim,
        providerRequestId: str | None,
        httpResponseReceived: bool | None,
        usageReceived: bool | None,
        parseCompleted: bool | None,
        failureStage: str,
    ) -> None:
        if claim.replayed or claim.claimToken is None:
            return
        self.repository.recordTurnProviderEvidence(
            workflowId=workflowId,
            ownerUserId=ownerUserId,
            clientRequestId=request.clientRequestId,
            requestHash=claim.requestHash,
            claimToken=claim.claimToken,
            providerRequestId=providerRequestId,
            httpResponseReceived=httpResponseReceived,
            usageReceived=usageReceived,
            parseCompleted=parseCompleted,
            failureStage=failureStage,
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

    def listTurnOperations(
        self,
        workflowId: str,
        ownerUserId: str,
    ) -> list[GuidedTurnOperationView]:
        return self.repository.listTurnOperations(
            workflowId=workflowId,
            ownerUserId=ownerUserId,
        )

    def recoverTurn(
        self,
        *,
        workflowId: str,
        ownerUserId: str,
        clientRequestId: str,
        request: GuidedTurnRecoveryRequest,
    ) -> GuidedWorkflowView | GuidedTurnOperationView:
        if request.action is GuidedTurnRecoveryAction.ABANDON_AND_AUTHORIZE_RETRY:
            return self.repository.abandonAndAuthorizeRetry(
                workflowId=workflowId,
                ownerUserId=ownerUserId,
                clientRequestId=clientRequestId,
                recoveryRequestId=request.recoveryRequestId,
                expectedVersion=request.expectedVersion,
                newClientRequestId=request.newClientRequestId or "",
                now=datetime.now(UTC),
            )
        recovered = self.repository.recoverCachedTurn(
            workflowId=workflowId,
            ownerUserId=ownerUserId,
            clientRequestId=clientRequestId,
            recoveryRequestId=request.recoveryRequestId,
            expectedVersion=request.expectedVersion,
            now=datetime.now(UTC),
        )
        if isinstance(recovered, GuidedWorkflowView):
            return recovered
        if not isinstance(recovered, GuidedCachedTurn):
            raise RuntimeError("guided cached-turn recovery returned an invalid state")
        turnRequest = GuidedTurnRequest(
            message=recovered.message,
            language=recovered.language,
            expectedVersion=request.expectedVersion,
            clientRequestId=clientRequestId,
        )
        try:
            response = self.completeTurn(
                workflowId=workflowId,
                ownerUserId=ownerUserId,
                request=turnRequest,
                claim=recovered.claim,
                proposal=recovered.proposal,
                recordAudit=True,
            )
        except Exception as error:
            self.markTurnUnknown(
                workflowId=workflowId,
                ownerUserId=ownerUserId,
                request=turnRequest,
                claim=recovered.claim,
                errorCode=type(error).__name__,
            )
            raise
        self.repository.completeTurnRecovery(
            workflowId=workflowId,
            ownerUserId=ownerUserId,
            recoveryRequestId=request.recoveryRequestId,
            response=response,
            now=datetime.now(UTC),
        )
        return response

    def archive(
        self,
        workflowId: str,
        ownerUserId: str,
        request: GuidedArchiveRequest,
    ) -> GuidedWorkflowView:
        return self.repository.archive(
            workflowId=workflowId,
            ownerUserId=ownerUserId,
            expectedVersion=request.expectedVersion,
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
            missingFields=(
                ("title", "summary", "instrument", "asOf", "researchQuestion")
                if workflow.stage is GuidedStage.EVENT_GOAL
                else ()
            ),
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
        preparedNextStage = (
            self.preparedPath.nextStage(ownerUserId, current.stage)
            if self.preparedPath is not None
            else None
        )
        if self.artifactValidator is not None and preparedNextStage is None:
            self.artifactValidator.assertStageCompletion(
                workflow=current,
                ownerUserId=ownerUserId,
                credentialSessionId=credentialSessionId,
            )
        nextStage = preparedNextStage or _NEXT_STAGE.get(current.stage)
        if nextStage is None:
            raise ValueError("the guided workflow cannot advance from its current stage")
        now = datetime.now(UTC)
        return self.repository.advance(
            workflowId=workflowId,
            ownerUserId=ownerUserId,
            expectedVersion=request.expectedVersion,
            nextStage=nextStage,
            openingMessage=GuidedWorkflowMessage(
                id=guidedStageOpeningMessageId(workflowId, nextStage),
                role="assistant",
                stage=nextStage,
                content=guidedStageOpening(nextStage, current.language),
                createdAt=now,
            ),
            now=now,
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
