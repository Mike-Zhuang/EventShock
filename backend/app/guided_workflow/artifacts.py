"""引导工作流与真实业务对象之间的权限、状态和一致性门禁。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.app.database import Database
from backend.app.errors import ApiError
from backend.app.event_pack_factory import EventPackFactoryService
from backend.app.event_pack_factory.errors import EventPackFactoryError
from backend.app.guided_workflow.models import (
    GuidedLinkRequest,
    GuidedSourceMethod,
    GuidedStage,
    GuidedWorkflowDraft,
    GuidedWorkflowView,
)
from backend.app.scenario_service import ScenarioService
from backend.app.schemas import ExperimentRequest
from backend.app.service import EventPackService

_FINAL_CLAIM_STATUSES = frozenset({"HUMAN_APPROVED", "EDITED", "REJECTED", "FROZEN"})
_ACCEPTED_CLAIM_STATUSES = frozenset({"HUMAN_APPROVED", "EDITED", "FROZEN"})
_BUILD_LINK_STAGES = frozenset({GuidedStage.SOURCE_METHOD, GuidedStage.SOURCE_REVIEW})
_PACK_LINK_STAGES = frozenset({GuidedStage.SOURCE_REVIEW})
_SCENARIO_LINK_STAGES = frozenset(
    {
        GuidedStage.SCENARIO_INTERVENTION,
        GuidedStage.SCENARIO_REVIEW,
    }
)


class GuidedArtifactValidator:
    """只接受当前用户真实持有、且达到当前阶段要求的业务对象。"""

    def __init__(
        self,
        *,
        database: Database,
        factory: EventPackFactoryService,
        eventPacks: EventPackService,
        scenarios: ScenarioService,
    ) -> None:
        self.database = database
        self.factory = factory
        self.eventPacks = eventPacks
        self.scenarios = scenarios

    def assertLinkUpdate(
        self,
        *,
        workflow: GuidedWorkflowView,
        ownerUserId: str,
        request: GuidedLinkRequest,
        draft: GuidedWorkflowDraft,
    ) -> None:
        """验证显式 handoff；不能用任意字符串伪造已完成对象。"""

        self._assertFactoryBuildNotReplaced(
            workflow=workflow,
            ownerUserId=ownerUserId,
            requestedId=request.eventPackBuildId,
        )
        self._assertArtifactNotReplaced(
            currentId=workflow.draft.eventPackId,
            requestedId=request.eventPackId,
            artifactName="Event Pack",
        )
        self._assertScenarioNotReplaced(
            workflow=workflow,
            ownerUserId=ownerUserId,
            requestedId=request.scenarioId,
        )
        if request.eventPackBuildId is not None and workflow.stage not in _BUILD_LINK_STAGES:
            raise ValueError("an Event Pack Factory build cannot be linked at this stage")
        if request.eventPackId is not None and workflow.stage not in _PACK_LINK_STAGES:
            raise ValueError("an Event Pack cannot be linked at this stage")
        if request.scenarioId is not None and workflow.stage not in _SCENARIO_LINK_STAGES:
            raise ValueError("a scenario cannot be linked at this stage")
        self._assertOwnedReferences(draft, ownerUserId)
        self._assertArtifactCoherence(workflow, draft, ownerUserId)

    @staticmethod
    def _assertArtifactNotReplaced(
        *,
        currentId: str | None,
        requestedId: str | None,
        artifactName: str,
    ) -> None:
        if currentId is not None and requestedId is not None and currentId != requestedId:
            raise ValueError(
                f"the linked {artifactName} is immutable; start a new guided workflow "
                "to use a different artifact"
            )

    def _assertFactoryBuildNotReplaced(
        self,
        *,
        workflow: GuidedWorkflowView,
        ownerUserId: str,
        requestedId: str | None,
    ) -> None:
        currentId = workflow.draft.eventPackBuildId
        if currentId is None or requestedId is None or currentId == requestedId:
            return
        if self._factoryBuildExists(ownerUserId=ownerUserId, buildId=currentId):
            raise ValueError(
                "the linked Factory build is immutable while it still exists; "
                "delete or let the unmaterialized build expire before replacing it"
            )
        if workflow.draft.eventPackId is not None:
            raise ValueError(
                "the linked Factory build cannot be replaced after an Event Pack was linked"
            )
        if workflow.stage not in _BUILD_LINK_STAGES:
            raise ValueError(
                "a missing Factory build can only be replaced during source collection"
            )

    def _assertScenarioNotReplaced(
        self,
        *,
        workflow: GuidedWorkflowView,
        ownerUserId: str,
        requestedId: str | None,
    ) -> None:
        currentId = workflow.draft.scenarioId
        if currentId is None or requestedId is None or currentId == requestedId:
            return
        if self._scenarioExists(ownerUserId=ownerUserId, scenarioId=currentId):
            raise ValueError(
                "the linked scenario is immutable while it still exists; "
                "start a new guided workflow to use a different scenario"
            )
        if workflow.stage is not GuidedStage.SCENARIO_INTERVENTION:
            raise ValueError(
                "a missing scenario can only be replaced before scenario freeze review"
            )

    def assertStageCompletion(
        self,
        *,
        workflow: GuidedWorkflowView,
        ownerUserId: str,
        credentialSessionId: str | None,
    ) -> None:
        """按阶段重新读取服务器状态，拒绝旧状态、跨用户对象或伪造 ID。"""

        draft = workflow.draft
        self._assertOwnedReferences(draft, ownerUserId)
        self._assertArtifactCoherence(workflow, draft, ownerUserId)

        if workflow.stage in {GuidedStage.EVENT_GOAL, GuidedStage.SOURCE_METHOD}:
            return
        if workflow.stage is GuidedStage.SOURCE_REVIEW:
            eventPack = self._requireEventPack(draft, ownerUserId)
            if not eventPack.get("sources"):
                raise ValueError("the linked Event Pack does not contain any reviewed source")
            if draft.sourceMethod is not GuidedSourceMethod.MANUAL:
                snapshot = self._getFactoryBuildIfPresent(draft, ownerUserId)
                if snapshot is None:
                    self._assertMissingBuildHasMaterializationAudit(
                        draft=draft,
                        ownerUserId=ownerUserId,
                    )
                    return
                if snapshot.build.status.value != "REVIEW_READY":
                    raise ValueError(
                        "the linked Factory build needs at least one human-approved evidence source"
                    )
                pendingEvidence = [
                    source.id
                    for source in snapshot.sources
                    if source.evidenceRole.value == "EVIDENCE"
                    and source.reviewStatus.value == "PENDING"
                ]
                if pendingEvidence:
                    raise ValueError(
                        "every retained evidence source needs an explicit human review decision"
                    )
                if not self.database.eventPackWasMaterializedFromFactoryBuild(
                    ownerUserId=ownerUserId,
                    buildId=snapshot.build.id,
                    eventPackId=str(eventPack["id"]),
                ):
                    raise ValueError(
                        "the linked Event Pack was not materialized from the linked Factory build"
                    )
            return
        if workflow.stage is GuidedStage.CLAIM_REVIEW:
            self._assertClaimsReviewed(self._requireEventPack(draft, ownerUserId))
            return
        if workflow.stage is GuidedStage.PACK_METADATA_REVIEW:
            eventPack = self._requireEventPack(draft, ownerUserId)
            self._assertClaimsReviewed(eventPack)
            self._assertEventMetadataMatches(draft, eventPack)
            return
        if workflow.stage is GuidedStage.PACK_FREEZE_REVIEW:
            eventPack = self._requireEventPack(draft, ownerUserId)
            self._assertEventMetadataMatches(draft, eventPack)
            self._assertEventPackFrozen(eventPack)
            return
        if workflow.stage is GuidedStage.SCENARIO_INTERVENTION:
            eventPack = self._requireEventPack(draft, ownerUserId)
            self._assertEventMetadataMatches(draft, eventPack)
            self._assertEventPackFrozen(eventPack)
            self._requireScenario(draft, ownerUserId)
            return
        if workflow.stage is GuidedStage.SCENARIO_REVIEW:
            eventPack = self._requireEventPack(draft, ownerUserId)
            self._assertEventMetadataMatches(draft, eventPack)
            self._assertEventPackFrozen(eventPack)
            self._assertScenarioFrozen(self._requireScenario(draft, ownerUserId))
            return
        if workflow.stage in {
            GuidedStage.PREFLIGHT,
            GuidedStage.READY_TO_SUBMIT,
        }:
            eventPack = self._requireEventPack(draft, ownerUserId)
            self._assertEventMetadataMatches(draft, eventPack)
            self._assertEventPackFrozen(eventPack)
            scenario = self._requireScenario(draft, ownerUserId)
            self._assertScenarioFrozen(scenario)
            validation = self.eventPacks.validateExperiment(
                ExperimentRequest.model_validate(scenario["config"]),
                ownerUserId,
                credentialSessionId,
            )
            if not validation.get("valid"):
                errors = validation.get("errors") or []
                firstError = errors[0] if errors else {}
                code = str(firstError.get("code", "PREFLIGHT_FAILED"))
                message = str(
                    firstError.get(
                        "message",
                        "the linked frozen scenario did not pass preflight",
                    )
                )
                raise ValueError(f"preflight failed ({code}): {message}")

    def _assertOwnedReferences(
        self,
        draft: GuidedWorkflowDraft,
        ownerUserId: str,
    ) -> None:
        if draft.eventPackBuildId is not None:
            try:
                self._getFactoryBuild(
                    ownerUserId=ownerUserId,
                    buildId=draft.eventPackBuildId,
                )
            except ValueError:
                self._assertMissingBuildHasMaterializationAudit(
                    draft=draft,
                    ownerUserId=ownerUserId,
                )
        if draft.eventPackId is not None:
            self._getEventPack(draft.eventPackId, ownerUserId)
        if draft.scenarioId is not None:
            self._getScenario(draft.scenarioId, ownerUserId)

    def _assertArtifactCoherence(
        self,
        workflow: GuidedWorkflowView,
        draft: GuidedWorkflowDraft,
        ownerUserId: str,
    ) -> None:
        if draft.scenarioId is None:
            return
        scenario = self._getScenario(draft.scenarioId, ownerUserId)
        config = scenario["config"]
        if draft.eventPackId is None:
            raise ValueError("link an owned Event Pack before linking a scenario")
        if config.get("eventPackId") != draft.eventPackId:
            raise ValueError("the scenario does not use the linked Event Pack")
        intervention = workflow.draft.intervention
        if intervention is None:
            return
        configuredIntervention = config.get("intervention") or {}
        if (
            configuredIntervention.get("parameter") != intervention.parameter
            or float(configuredIntervention.get("baselineValue", float("nan")))
            != intervention.baselineValue
            or float(configuredIntervention.get("interventionValue", float("nan")))
            != intervention.interventionValue
        ):
            raise ValueError(
                "the saved scenario does not match the human-applied guided intervention"
            )

    def _getFactoryBuildIfPresent(
        self,
        draft: GuidedWorkflowDraft,
        ownerUserId: str,
    ) -> Any | None:
        if draft.eventPackBuildId is None:
            raise ValueError("link the reviewed Factory build before continuing")
        try:
            return self._getFactoryBuild(
                ownerUserId=ownerUserId,
                buildId=draft.eventPackBuildId,
            )
        except ValueError:
            return None

    def _assertMissingBuildHasMaterializationAudit(
        self,
        *,
        draft: GuidedWorkflowDraft,
        ownerUserId: str,
    ) -> None:
        if (
            draft.eventPackBuildId is None
            or draft.eventPackId is None
            or not self.database.eventPackWasMaterializedFromFactoryBuild(
                ownerUserId=ownerUserId,
                buildId=draft.eventPackBuildId,
                eventPackId=draft.eventPackId,
            )
        ):
            raise ValueError(
                "the linked Factory build does not exist and no audited Event Pack "
                "materialization can replace that provenance"
            )

    def _requireEventPack(
        self,
        draft: GuidedWorkflowDraft,
        ownerUserId: str,
    ) -> dict[str, Any]:
        if draft.eventPackId is None:
            raise ValueError("link the reviewed Event Pack before continuing")
        return self._getEventPack(draft.eventPackId, ownerUserId)

    def _requireScenario(
        self,
        draft: GuidedWorkflowDraft,
        ownerUserId: str,
    ) -> dict[str, Any]:
        if draft.scenarioId is None:
            raise ValueError("save and link the reviewed scenario before continuing")
        return self._getScenario(draft.scenarioId, ownerUserId)

    def _getFactoryBuild(self, *, ownerUserId: str, buildId: str) -> Any:
        try:
            return self.factory.getBuild(
                ownerUserId=ownerUserId,
                buildId=buildId,
            )
        except EventPackFactoryError as error:
            raise ValueError(
                "the linked Factory build does not exist or is not owned by this account"
            ) from error

    def _getEventPack(
        self,
        eventPackId: str,
        ownerUserId: str,
    ) -> dict[str, Any]:
        try:
            return self.eventPacks.getEventPack(eventPackId, ownerUserId)
        except ApiError as error:
            raise ValueError(
                "the linked Event Pack does not exist or is not available to this account"
            ) from error

    def _getScenario(
        self,
        scenarioId: str,
        ownerUserId: str,
    ) -> dict[str, Any]:
        try:
            return self.scenarios.getScenario(scenarioId, ownerUserId)
        except ApiError as error:
            raise ValueError(
                "the linked scenario does not exist or is not owned by this account"
            ) from error

    def _factoryBuildExists(self, *, ownerUserId: str, buildId: str) -> bool:
        try:
            self.factory.getBuild(ownerUserId=ownerUserId, buildId=buildId)
        except EventPackFactoryError:
            return False
        return True

    def _scenarioExists(self, *, ownerUserId: str, scenarioId: str) -> bool:
        try:
            self.scenarios.getScenario(scenarioId, ownerUserId)
        except ApiError:
            return False
        return True

    @staticmethod
    def _assertClaimsReviewed(eventPack: dict[str, Any]) -> None:
        claims = eventPack.get("claims") or []
        if not claims:
            raise ValueError("the linked Event Pack does not contain candidate claims")
        unresolved = [
            str(claim.get("claimId", "unknown-claim"))
            for claim in claims
            if claim.get("preFreezeReviewStatus", claim.get("reviewStatus"))
            not in _FINAL_CLAIM_STATUSES
        ]
        if unresolved:
            raise ValueError("every candidate claim needs an explicit human review decision")
        if not any(
            claim.get("preFreezeReviewStatus", claim.get("reviewStatus"))
            in _ACCEPTED_CLAIM_STATUSES
            for claim in claims
        ):
            raise ValueError("at least one claim must be human-approved or edited")

    @staticmethod
    def _assertEventMetadataMatches(
        draft: GuidedWorkflowDraft,
        eventPack: dict[str, Any],
    ) -> None:
        metadata = draft.eventMetadata
        if metadata is None:
            raise ValueError("review and apply event metadata before continuing")
        expectedFields = {
            "title": metadata.title,
            "titleZh": metadata.titleZh or metadata.title,
            "summary": metadata.summary,
            "summaryZh": metadata.summaryZh or metadata.summary,
            "instrument": metadata.instrument,
        }
        mismatched = [
            fieldName
            for fieldName, expectedValue in expectedFields.items()
            if eventPack.get(fieldName) != expectedValue
        ]
        try:
            packAsOf = datetime.fromisoformat(str(eventPack.get("asOf", "")).replace("Z", "+00:00"))
            if packAsOf.tzinfo is None:
                packAsOf = packAsOf.replace(tzinfo=UTC)
            metadataAsOf = metadata.asOf
            if metadataAsOf.tzinfo is None:
                metadataAsOf = metadataAsOf.replace(tzinfo=UTC)
            if packAsOf.astimezone(UTC) != metadataAsOf.astimezone(UTC):
                mismatched.append("asOf")
        except ValueError:
            mismatched.append("asOf")
        if mismatched:
            raise ValueError(
                "the linked Event Pack does not match the human-reviewed guided metadata: "
                + ", ".join(sorted(set(mismatched)))
            )

    @staticmethod
    def _assertEventPackFrozen(eventPack: dict[str, Any]) -> None:
        if eventPack.get("status") != "FROZEN":
            raise ValueError("the linked Event Pack must be frozen before continuing")

    @staticmethod
    def _assertScenarioFrozen(scenario: dict[str, Any]) -> None:
        if not scenario.get("frozen"):
            raise ValueError("the linked scenario must be frozen before continuing")
        if not scenario.get("contentHash"):
            raise ValueError("the frozen scenario is missing its immutable content hash")
