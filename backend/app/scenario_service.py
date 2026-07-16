"""会话级场景草稿、冻结、克隆与结构化差异服务。"""

from __future__ import annotations

import uuid
from typing import Any

from backend.app.database import Database
from backend.app.errors import ApiError
from backend.app.schemas import ExperimentRequest, ScenarioSaveRequest, ScenarioUpdateRequest
from backend.app.service import EventPackService


class ScenarioService:
    def __init__(self, database: Database, eventPacks: EventPackService) -> None:
        self.database = database
        self.eventPacks = eventPacks

    def createScenario(self, requestData: ScenarioSaveRequest, sessionId: str) -> dict[str, Any]:
        if requestData.frozen:
            self._requireValid(requestData.config, sessionId)
        scenarioId = f"scn-{uuid.uuid4().hex[:16]}"
        scenario = self.database.saveScenario(
            scenarioId,
            sessionId,
            requestData.name,
            requestData.config.model_dump(mode="json"),
            requestData.frozen,
        )
        self.database.appendAuditEvent(
            sessionId,
            "SCENARIO",
            scenarioId,
            "CREATED_FROZEN" if requestData.frozen else "CREATED",
            {"contentHash": scenario["contentHash"]},
        )
        return scenario

    def listScenarios(self, sessionId: str) -> list[dict[str, Any]]:
        return self.database.listScenarios(sessionId)

    def getScenario(self, scenarioId: str, sessionId: str) -> dict[str, Any]:
        scenario = self.database.getScenario(scenarioId, sessionId)
        if scenario is None:
            raise ApiError("SCENARIO_NOT_FOUND", 404, "The scenario does not exist.")
        return scenario

    def updateScenario(
        self,
        scenarioId: str,
        requestData: ScenarioUpdateRequest,
        sessionId: str,
    ) -> dict[str, Any]:
        existing = self.getScenario(scenarioId, sessionId)
        if existing["frozen"]:
            raise ApiError("SCENARIO_FROZEN", 409, "A frozen scenario cannot be edited.")
        updated = self.database.saveScenario(
            scenarioId,
            sessionId,
            requestData.name,
            requestData.config.model_dump(mode="json"),
            False,
        )
        self.database.appendAuditEvent(
            sessionId,
            "SCENARIO",
            scenarioId,
            "UPDATED",
            {"previousHash": existing["contentHash"], "contentHash": updated["contentHash"]},
        )
        return updated

    def cloneScenario(self, scenarioId: str, sessionId: str) -> dict[str, Any]:
        source = self.getScenario(scenarioId, sessionId)
        cloneId = f"scn-{uuid.uuid4().hex[:16]}"
        clone = self.database.saveScenario(
            cloneId,
            sessionId,
            f"{source['name']} copy",
            source["config"],
            False,
        )
        self.database.appendAuditEvent(
            sessionId,
            "SCENARIO",
            cloneId,
            "CLONED",
            {"sourceScenarioId": scenarioId, "contentHash": clone["contentHash"]},
        )
        return clone

    def freezeScenario(self, scenarioId: str, sessionId: str) -> dict[str, Any]:
        existing = self.getScenario(scenarioId, sessionId)
        if existing["frozen"]:
            return existing
        config = ExperimentRequest.model_validate(existing["config"])
        self._requireValid(config, sessionId)
        frozen = self.database.saveScenario(
            scenarioId,
            sessionId,
            existing["name"],
            existing["config"],
            True,
        )
        self.database.appendAuditEvent(
            sessionId,
            "SCENARIO",
            scenarioId,
            "FROZEN",
            {"contentHash": frozen["contentHash"]},
        )
        return frozen

    def deleteScenario(self, scenarioId: str, sessionId: str) -> None:
        existing = self.getScenario(scenarioId, sessionId)
        if existing["frozen"]:
            raise ApiError("SCENARIO_FROZEN", 409, "A frozen scenario cannot be deleted.")
        if not self.database.deleteScenario(scenarioId, sessionId):
            raise ApiError("SCENARIO_DELETE_CONFLICT", 409, "The scenario could not be deleted.")
        self.database.appendAuditEvent(
            sessionId,
            "SCENARIO",
            scenarioId,
            "DELETED",
            {"contentHash": existing["contentHash"]},
        )

    @staticmethod
    def diffConfigs(baseline: ExperimentRequest, intervention: ExperimentRequest) -> dict[str, Any]:
        changes: list[dict[str, Any]] = []
        _collectDiff(
            baseline.model_dump(mode="json"),
            intervention.model_dump(mode="json"),
            "",
            changes,
        )
        return {
            "changeCount": len(changes),
            "changedPaths": [change["path"] for change in changes],
            "changes": changes,
            "singleInterventionCompliant": len(changes) == 1
            and changes[0]["path"].startswith("intervention."),
        }

    def _requireValid(self, config: ExperimentRequest, sessionId: str) -> None:
        validation = self.eventPacks.validateExperiment(config, sessionId)
        if not validation["valid"]:
            firstError = validation["errors"][0]
            raise ApiError(firstError["code"], 422, firstError["message"])


def _collectDiff(
    baseline: Any,
    intervention: Any,
    path: str,
    changes: list[dict[str, Any]],
) -> None:
    if isinstance(baseline, dict) and isinstance(intervention, dict):
        for key in sorted(set(baseline) | set(intervention)):
            childPath = f"{path}.{key}" if path else key
            _collectDiff(baseline.get(key), intervention.get(key), childPath, changes)
        return
    if isinstance(baseline, list) and isinstance(intervention, list):
        if baseline != intervention:
            changes.append({"path": path, "baseline": baseline, "intervention": intervention})
        return
    if baseline != intervention:
        changes.append({"path": path, "baseline": baseline, "intervention": intervention})
