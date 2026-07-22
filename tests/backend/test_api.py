from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.cognition import (
    ModelUsage,
    ResultEvidenceTool,
    ResultInterpretationAnswer,
    ResultInterpretationRun,
    ResultToolActivity,
)
from backend.app.main import createApp
from backend.app.replay import replayBundle
from backend.app.service import _hashJson
from backend.app.simulation.engine import runScenario

SESSION_A = "test-session-a-12345"
SESSION_B = "test-session-b-12345"
PACK_ID = "spacex-synthetic-v1"
BULK_REVIEW_PACK_ID = "gamestop-meme-2021-v1"


def experimentPayload() -> dict:
    return {
        "eventPackId": PACK_ID,
        "question": "How does lower liquidity change the simulated distribution?",
        "intervention": {
            "parameter": "marketMakerCapacity",
            "baselineValue": 1.0,
            "interventionValue": 0.45,
        },
        "seedCount": 10,
        "populationSize": 14,
        "steps": 30,
        "seedRoot": 123_000,
    }


def approveAndFreeze(client: TestClient, sessionId: str) -> None:
    reviewResponse = client.post(
        f"/api/v1/event-packs/{PACK_ID}/claims/claim-limited-depth/review",
        headers={"X-Session-ID": sessionId},
        json={"status": "HUMAN_APPROVED"},
    )
    assert reviewResponse.status_code == 200
    freezeResponse = client.post(
        f"/api/v1/event-packs/{PACK_ID}/freeze",
        headers={"X-Session-ID": sessionId},
    )
    assert freezeResponse.status_code == 200
    assert freezeResponse.json()["status"] == "FROZEN"


def test_health_and_synthetic_case(tmp_path: Path) -> None:
    with TestClient(createApp(tmp_path)) as client:
        healthResponse = client.get("/api/health")
        casesResponse = client.get("/api/v1/cases")
        metricsResponse = client.get("/api/v1/system/metrics")

    assert healthResponse.status_code == 200
    assert healthResponse.json()["status"] == "ok"
    assert healthResponse.json()["releaseCommit"] == "development"
    assert healthResponse.headers["X-Trace-ID"].startswith("http-")
    assert casesResponse.json()["items"][0]["synthetic"] is True
    assert casesResponse.json()["items"][0]["titleZh"]
    metrics = metricsResponse.json()
    assert metrics["runtime"]["requestCount"] >= 2
    assert metrics["runtime"]["privacyBoundary"] == "NO_PATH_BODY_SESSION_OR_CREDENTIAL_LABELS"
    assert metrics["experiments"]["workerConcurrency"] == 1
    assert metrics["sloTargets"]["status"] == "TARGETS_NOT_PRODUCTION_EVIDENCE"


def test_unknown_api_route_is_structured_404(tmp_path: Path) -> None:
    with TestClient(createApp(tmp_path)) as client:
        response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "API_ROUTE_NOT_FOUND"


def test_experiment_sse_emits_terminal_public_state_and_closes(tmp_path: Path) -> None:
    with TestClient(createApp(tmp_path)) as client:
        database = client.app.state.database
        database.createExperiment(
            "exp-sse-terminal",
            SESSION_A,
            experimentPayload(),
            None,
        )
        database.updateExperiment(
            "exp-sse-terminal",
            SESSION_A,
            status="COMPLETED",
            progress=1.0,
            completed_pairs=10,
            result_json={"privateResult": "must-not-enter-status-stream"},
            completed_at="2026-07-15T12:00:00+00:00",
            runtime_json={"phase": "COMPLETED", "logs": [{"message": "done"}]},
        )
        response = client.get(
            "/api/v1/experiments/exp-sse-terminal/events",
            headers={"X-Session-ID": SESSION_A},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    assert "event: experiment" in response.text
    assert '"status":"COMPLETED"' in response.text
    assert '"resultsAvailable":true' in response.text
    assert "must-not-enter-status-stream" not in response.text
    assert SESSION_A not in response.text


def test_spa_root_supports_head_without_capturing_api_paths(tmp_path: Path) -> None:
    frontendDist = tmp_path / "frontend-dist"
    frontendDist.mkdir()
    (frontendDist / "index.html").write_text("<html>EventShock</html>", encoding="utf-8")
    (frontendDist / "favicon.svg").write_text("<svg></svg>", encoding="utf-8")
    with TestClient(createApp(tmp_path / "data", frontendDist=frontendDist)) as client:
        rootResponse = client.head("/")
        legacyFaviconResponse = client.get("/favicon.ico")
        apiResponse = client.head("/api/v1/unknown-route")
        scannerResponse = client.get("/.git/HEAD")

    assert rootResponse.status_code == 200
    assert rootResponse.content == b""
    assert legacyFaviconResponse.status_code == 200
    assert legacyFaviconResponse.headers["content-type"].startswith("image/svg+xml")
    assert apiResponse.status_code == 404
    assert apiResponse.headers["X-Trace-ID"].startswith("http-")
    assert scannerResponse.status_code == 404
    assert b"EventShock" not in scannerResponse.content


def test_experiment_create_rate_limit_returns_retry_after(tmp_path: Path) -> None:
    with TestClient(createApp(tmp_path)) as client:
        approveAndFreeze(client, SESSION_A)
        responses = [
            client.post(
                "/api/v1/experiments",
                headers={
                    "X-Session-ID": SESSION_A,
                    "Idempotency-Key": f"rate-limit-create-{index:02d}",
                    "X-Forwarded-For": "203.0.113.10",
                },
                json=experimentPayload(),
            )
            for index in range(6)
        ]

    assert [response.status_code for response in responses[:5]] == [201] * 5
    assert responses[5].status_code == 429
    assert responses[5].json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert int(responses[5].headers["Retry-After"]) >= 1


def test_unfrozen_pack_blocks_experiment_and_multiple_interventions_are_rejected(
    tmp_path: Path,
) -> None:
    with TestClient(createApp(tmp_path)) as client:
        validateResponse = client.post(
            "/api/v1/scenarios/validate",
            headers={"X-Session-ID": SESSION_A},
            json=experimentPayload(),
        )
        createResponse = client.post(
            "/api/v1/experiments",
            headers={"X-Session-ID": SESSION_A},
            json=experimentPayload(),
        )
        invalidPayload = {
            **experimentPayload(),
            "interventions": [experimentPayload()["intervention"]],
        }
        multiResponse = client.post(
            "/api/v1/scenarios/validate",
            headers={"X-Session-ID": SESSION_A},
            json=invalidPayload,
        )

    assert validateResponse.status_code == 200
    assert validateResponse.json()["valid"] is False
    assert validateResponse.json()["errors"][0]["code"] == "EVENT_PACK_NOT_FROZEN"
    assert createResponse.status_code == 422
    assert createResponse.json()["error"]["code"] == "EVENT_PACK_NOT_FROZEN"
    assert multiResponse.status_code == 422
    assert multiResponse.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"


def test_event_pack_review_and_freeze_are_session_isolated(tmp_path: Path) -> None:
    with TestClient(createApp(tmp_path)) as client:
        approveAndFreeze(client, SESSION_A)
        sessionA = client.get(
            f"/api/v1/event-packs/{PACK_ID}", headers={"X-Session-ID": SESSION_A}
        ).json()
        sessionB = client.get(
            f"/api/v1/event-packs/{PACK_ID}", headers={"X-Session-ID": SESSION_B}
        ).json()

    assert sessionA["status"] == "FROZEN"
    assert sessionB["status"] == "DRAFT"
    sessionBClaim = next(
        claim for claim in sessionB["claims"] if claim["claimId"] == "claim-limited-depth"
    )
    assert sessionBClaim["reviewStatus"] == "AI_PROPOSED"


def test_bulk_claim_approval_preserves_resolved_claims_and_is_auditable(
    tmp_path: Path,
) -> None:
    with TestClient(createApp(tmp_path)) as client:
        initial = client.get(
            f"/api/v1/event-packs/{BULK_REVIEW_PACK_ID}",
            headers={"X-Session-ID": SESSION_A},
        ).json()
        rejectedClaimId = "claim-board-refreshment"
        editedClaimId = "claim-account-participation"
        rejectResponse = client.post(
            f"/api/v1/event-packs/{BULK_REVIEW_PACK_ID}/claims/{rejectedClaimId}/review",
            headers={"X-Session-ID": SESSION_A},
            json={"status": "REJECTED"},
        )
        editResponse = client.post(
            f"/api/v1/event-packs/{BULK_REVIEW_PACK_ID}/claims/{editedClaimId}/review",
            headers={"X-Session-ID": SESSION_A},
            json={
                "status": "EDITED",
                "editedText": "A human-bounded account participation claim.",
            },
        )
        assert rejectResponse.status_code == 200
        assert editResponse.status_code == 200

        pendingClaimIds = [
            claim["claimId"]
            for claim in editResponse.json()["claims"]
            if claim["reviewStatus"] == "AI_PROPOSED"
        ]
        assert len(pendingClaimIds) == len(initial["claims"]) - 2
        bulkResponse = client.post(
            f"/api/v1/event-packs/{BULK_REVIEW_PACK_ID}/claims/approve-all",
            headers={"X-Session-ID": SESSION_A},
            json={
                "acknowledgedBulkApproval": True,
                # 顺序不属于确认契约；集合必须与当前待审核队列完全一致。
                "expectedClaimIds": list(reversed(pendingClaimIds)),
                "rationale": "Confirmed after reading the bulk-approval warning.",
            },
        )

        assert bulkResponse.status_code == 200
        reviewedClaims = {claim["claimId"]: claim for claim in bulkResponse.json()["claims"]}
        assert reviewedClaims[rejectedClaimId]["reviewStatus"] == "REJECTED"
        assert reviewedClaims[editedClaimId]["reviewStatus"] == "EDITED"
        assert reviewedClaims[editedClaimId]["reviewedBy"] == SESSION_A
        assert all(
            reviewedClaims[claimId]["reviewStatus"] == "HUMAN_APPROVED"
            and reviewedClaims[claimId]["reviewedBy"] == SESSION_A
            for claimId in pendingClaimIds
        )
        assert len({reviewedClaims[claimId]["reviewedAt"] for claimId in pendingClaimIds}) == 1

        auditEvents = client.app.state.database.listAuditEvents(SESSION_A)
        bulkAudit = next(
            event for event in auditEvents if event["action"] == "BULK_CLAIMS_APPROVED"
        )
        assert bulkAudit["entityType"] == "EVENT_PACK"
        assert bulkAudit["entityId"] == BULK_REVIEW_PACK_ID
        assert bulkAudit["payload"] == {
            "claimCount": len(pendingClaimIds),
            "claimIds": pendingClaimIds,
            "reviewStatus": "HUMAN_APPROVED",
            "warningAcknowledged": True,
            "rationale": "Confirmed after reading the bulk-approval warning.",
        }
        assert client.app.state.database.verifyAuditChain(SESSION_A)["valid"] is True

        otherOwner = client.get(
            f"/api/v1/event-packs/{BULK_REVIEW_PACK_ID}",
            headers={"X-Session-ID": SESSION_B},
        ).json()
        assert all(claim["reviewStatus"] == "AI_PROPOSED" for claim in otherOwner["claims"])
        freezeResponse = client.post(
            f"/api/v1/event-packs/{BULK_REVIEW_PACK_ID}/freeze",
            headers={"X-Session-ID": SESSION_A},
        )

    assert freezeResponse.status_code == 200
    assert freezeResponse.json()["status"] == "FROZEN"


def test_bulk_claim_approval_requires_confirmation_and_exact_pending_queue(
    tmp_path: Path,
) -> None:
    endpoint = f"/api/v1/event-packs/{PACK_ID}/claims/approve-all"
    headers = {"X-Session-ID": SESSION_A}
    expectedClaimIds = ["claim-limited-depth"]
    with TestClient(createApp(tmp_path)) as client:
        missingConfirmation = client.post(
            endpoint,
            headers=headers,
            json={"expectedClaimIds": expectedClaimIds},
        )
        falseConfirmation = client.post(
            endpoint,
            headers=headers,
            json={
                "acknowledgedBulkApproval": False,
                "expectedClaimIds": expectedClaimIds,
            },
        )
        duplicateIds = client.post(
            endpoint,
            headers=headers,
            json={
                "acknowledgedBulkApproval": True,
                "expectedClaimIds": ["claim-limited-depth", "claim-limited-depth"],
            },
        )
        changedQueue = client.post(
            endpoint,
            headers=headers,
            json={
                "acknowledgedBulkApproval": True,
                "expectedClaimIds": ["claim-different"],
            },
        )
        validLlmIdentifierShape = client.post(
            endpoint,
            headers=headers,
            json={
                "acknowledgedBulkApproval": True,
                # LLM 抽取契约允许冒号和最多 128 字符；批量接口必须接受同一标识空间。
                "expectedClaimIds": ["c:" + ("a" * 126)],
            },
        )
        unchanged = client.get(
            f"/api/v1/event-packs/{PACK_ID}",
            headers=headers,
        ).json()

    assert missingConfirmation.status_code == 422
    assert falseConfirmation.status_code == 422
    assert duplicateIds.status_code == 422
    assert changedQueue.status_code == 409
    assert changedQueue.json()["error"]["code"] == "CLAIM_QUEUE_CHANGED"
    assert validLlmIdentifierShape.status_code == 409
    assert validLlmIdentifierShape.json()["error"]["code"] == "CLAIM_QUEUE_CHANGED"
    pending = next(
        claim for claim in unchanged["claims"] if claim["claimId"] == "claim-limited-depth"
    )
    assert pending["reviewStatus"] == "AI_PROPOSED"
    assert unchanged["status"] == "DRAFT"


def test_bulk_claim_approval_rejects_empty_and_frozen_queues(tmp_path: Path) -> None:
    endpoint = f"/api/v1/event-packs/{PACK_ID}/claims/approve-all"
    headers = {"X-Session-ID": SESSION_A}
    payload = {
        "acknowledgedBulkApproval": True,
        "expectedClaimIds": ["claim-limited-depth"],
    }
    with TestClient(createApp(tmp_path)) as client:
        approved = client.post(endpoint, headers=headers, json=payload)
        assert approved.status_code == 200
        noPending = client.post(endpoint, headers=headers, json=payload)
        frozen = client.post(
            f"/api/v1/event-packs/{PACK_ID}/freeze",
            headers=headers,
        )
        afterFreeze = client.post(endpoint, headers=headers, json=payload)

    assert noPending.status_code == 409
    assert noPending.json()["error"]["code"] == "NO_PENDING_CLAIMS"
    assert frozen.status_code == 200
    assert afterFreeze.status_code == 409
    assert afterFreeze.json()["error"]["code"] == "EVENT_PACK_FROZEN"


def test_bulk_claim_approval_uses_the_standard_write_rate_limit(tmp_path: Path) -> None:
    endpoint = f"/api/v1/event-packs/{PACK_ID}/claims/approve-all"
    headers = {"X-Session-ID": SESSION_A}
    stalePayload = {
        "acknowledgedBulkApproval": True,
        "expectedClaimIds": ["claim-different"],
    }
    with TestClient(createApp(tmp_path)) as client:
        responses = [client.post(endpoint, headers=headers, json=stalePayload) for _ in range(31)]

    assert all(response.status_code == 409 for response in responses[:30])
    assert responses[30].status_code == 429
    assert responses[30].json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"


def test_rejected_clarification_blocks_clarification_delay_intervention(
    tmp_path: Path,
) -> None:
    with TestClient(createApp(tmp_path)) as client:
        client.post(
            f"/api/v1/event-packs/{PACK_ID}/claims/claim-limited-depth/review",
            headers={"X-Session-ID": SESSION_A},
            json={"status": "HUMAN_APPROVED"},
        )
        client.post(
            f"/api/v1/event-packs/{PACK_ID}/claims/claim-clarification/review",
            headers={"X-Session-ID": SESSION_A},
            json={"status": "REJECTED"},
        )
        freezeResponse = client.post(
            f"/api/v1/event-packs/{PACK_ID}/freeze",
            headers={"X-Session-ID": SESSION_A},
        )
        payload = experimentPayload()
        payload["intervention"] = {
            "parameter": "clarificationDelay",
            "baselineValue": 1.0,
            "interventionValue": 2.0,
        }
        validationResponse = client.post(
            "/api/v1/scenarios/validate",
            headers={"X-Session-ID": SESSION_A},
            json=payload,
        )

    assert freezeResponse.status_code == 200
    assert validationResponse.status_code == 200
    assert validationResponse.json()["valid"] is False
    assert any(
        error["code"] == "INTERVENTION_MECHANISM_DISABLED"
        for error in validationResponse.json()["errors"]
    )


def test_experiment_lifecycle_is_idempotent_and_exports_zip(tmp_path: Path) -> None:
    with TestClient(createApp(tmp_path)) as client:
        approveAndFreeze(client, SESSION_A)
        headers = {
            "X-Session-ID": SESSION_A,
            "Idempotency-Key": "experiment-test-0001",
        }
        firstCreate = client.post("/api/v1/experiments", headers=headers, json=experimentPayload())
        secondCreate = client.post("/api/v1/experiments", headers=headers, json=experimentPayload())
        assert firstCreate.status_code == 201
        assert secondCreate.status_code == 200
        assert firstCreate.json()["id"] == secondCreate.json()["id"]
        experimentId = firstCreate.json()["id"]

        startResponse = client.post(
            f"/api/v1/experiments/{experimentId}/start",
            headers={"X-Session-ID": SESSION_A},
        )
        assert startResponse.status_code == 200
        deadline = time.monotonic() + 20
        status = startResponse.json()["status"]
        latestStatusPayload = startResponse.json()
        while status not in {"COMPLETED", "FAILED_FINAL"} and time.monotonic() < deadline:
            time.sleep(0.05)
            statusResponse = client.get(
                f"/api/v1/experiments/{experimentId}",
                headers={"X-Session-ID": SESSION_A},
            )
            latestStatusPayload = statusResponse.json()
            status = latestStatusPayload["status"]
        assert status == "COMPLETED"
        assert "checkpoint" not in latestStatusPayload
        assert "checkpointCorrupted" not in latestStatusPayload
        assert latestStatusPayload["runtime"]["phase"] == "COMPLETED"
        assert latestStatusPayload["runtime"]["checkpointPairs"] == 10
        assert latestStatusPayload["runtime"]["baseline"]["completedSteps"] == 30
        assert latestStatusPayload["runtime"]["intervention"]["completedSteps"] == 30
        assert any(
            "checkpointed" in entry["message"] for entry in latestStatusPayload["runtime"]["logs"]
        )

        resultsResponse = client.get(
            f"/api/v1/experiments/{experimentId}/results",
            headers={"X-Session-ID": SESSION_A},
        )
        exportResponse = client.get(
            f"/api/v1/experiments/{experimentId}/export",
            headers={"X-Session-ID": SESSION_A},
        )

    results = resultsResponse.json()
    assert len(results["pairedRuns"]) == 10
    assert results["scenarioDiff"]["changeCount"] == 1
    assert results["manifest"]["validPairedSeeds"] == 10
    assert results["metricSummaries"]["maxSpreadBps"]["delta"]["validN"] == 10
    assert exportResponse.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exportResponse.content)) as archive:
        names = set(archive.namelist())
        exportedEventPack = json.loads(archive.read("event_pack_manifest.json"))
    assert {
        "manifest.json",
        "scenario_baseline.json",
        "scenario_intervention.json",
        "run_level_metrics.csv",
        "analysis_diagnostics.json",
        "selected_traces.jsonl",
        "limitations.md",
        "event_pack_manifest.json",
        "source_hashes.csv",
        "cognitive_decisions.json",
        "model_and_prompt_versions.json",
        "validation_report.md",
        "parquet/schema_manifest.json",
        "parquet/run_level_metrics.parquet",
        "parquet/market_snapshots.parquet",
        "parquet/trace_index.parquet",
        "parquet/orders.parquet",
        "parquet/trades.parquet",
        "parquet/agent_decisions.parquet",
    }.issubset(names)
    expectedEventPackHash = hashlib.sha256(
        json.dumps(
            exportedEventPack,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert results["manifest"]["eventPackHash"] == expectedEventPackHash
    bundlePath = tmp_path / "experiment-export.zip"
    bundlePath.write_bytes(exportResponse.content)
    replayReport = replayBundle(bundlePath)
    assert replayReport["verified"] is True
    assert replayReport["pairedSeeds"] == 10
    assert replayReport["mismatches"] == []
    assert results["analysisDiagnostics"]["negativeControl"]["status"] == "COMPLETED"
    assert results["analysisDiagnostics"]["negativeControl"]["passed"] is True
    assert (
        results["analysisDiagnostics"]["multipleComparison"]["method"]
        == "HOLM_BONFERRONI_ON_EXACT_TWO_SIDED_SIGN_TESTS"
    )


def test_experiment_subresources_and_invalidation_contract(tmp_path: Path) -> None:
    persistedResult = {
        "pairedRuns": [{"seed": 101, "baseline": {"x": 1}, "intervention": {"x": 2}}],
        "metricSummaries": {"x": {"delta": {"median": 1.0, "validN": 1}}},
        "medianPaths": {"baseline": [{"step": 0, "price": 100.0}]},
        "analysisDiagnostics": {"negativeControl": {"status": "COMPLETED"}},
        "stoppingRule": {"reason": "FIXED_PAIR_COUNT_REACHED"},
        "manifest": {
            "eventPackHash": "event-pack-hash",
            "engineVersion": "engine-test-v1",
            "llmModel": "RULE_ONLY",
            "promptVersion": "belief-test-v1",
        },
        "traces": [{"traceId": "trace-1", "eventType": "ORDER_ARRIVED"}],
    }
    with TestClient(createApp(tmp_path)) as client:
        approveAndFreeze(client, SESSION_A)
        created = client.post(
            "/api/v1/experiments",
            headers={
                "X-Session-ID": SESSION_A,
                "Idempotency-Key": "invalidation-contract-0001",
            },
            json=experimentPayload(),
        )
        experimentId = created.json()["id"]
        invalidationPayload = {
            "schemaVersion": "1.0.0",
            "reasonCode": "MODEL_ISSUE",
            "reason": "The configured model failed a post-release validation check.",
        }

        prematureInvalidation = client.post(
            f"/api/v1/experiments/{experimentId}/invalidate",
            headers={"X-Session-ID": SESSION_A},
            json=invalidationPayload,
        )
        client.app.state.database.updateExperiment(
            experimentId,
            SESSION_A,
            status="COMPLETED",
            result_json=persistedResult,
            progress=1.0,
            completed_pairs=1,
            completed_at="2026-07-15T00:00:00+00:00",
        )

        runs = client.get(
            f"/api/v1/experiments/{experimentId}/runs",
            headers={"X-Session-ID": SESSION_A},
        )
        metrics = client.get(
            f"/api/v1/experiments/{experimentId}/metrics",
            headers={"X-Session-ID": SESSION_A},
        )
        traces = client.get(
            f"/api/v1/experiments/{experimentId}/traces",
            headers={"X-Session-ID": SESSION_A},
        )
        crossSessionRead = client.get(
            f"/api/v1/experiments/{experimentId}/runs",
            headers={"X-Session-ID": SESSION_B},
        )
        crossSessionInvalidation = client.post(
            f"/api/v1/experiments/{experimentId}/invalidate",
            headers={"X-Session-ID": SESSION_B},
            json=invalidationPayload,
        )

        invalidated = client.post(
            f"/api/v1/experiments/{experimentId}/invalidate",
            headers={"X-Session-ID": SESSION_A},
            json=invalidationPayload,
        )
        repeatedInvalidation = client.post(
            f"/api/v1/experiments/{experimentId}/invalidate",
            headers={"X-Session-ID": SESSION_A},
            json={
                **invalidationPayload,
                "reasonCode": "OTHER",
                "reason": "This repeated call must not overwrite the first reason.",
            },
        )
        cancelAfterInvalidation = client.post(
            f"/api/v1/experiments/{experimentId}/cancel",
            headers={"X-Session-ID": SESSION_A},
        )
        blockedResponses = [
            client.get(
                f"/api/v1/experiments/{experimentId}/{resource}",
                headers={"X-Session-ID": SESSION_A},
            )
            for resource in ("results", "runs", "metrics", "traces", "export")
        ]
        auditEvents = client.get(
            "/api/v1/audit-events",
            headers={"X-Session-ID": SESSION_A},
        ).json()["items"]
        auditVerification = client.get(
            "/api/v1/audit-events/verify",
            headers={"X-Session-ID": SESSION_A},
        )
        stored = client.app.state.database.getExperiment(experimentId, SESSION_A)

    assert created.status_code == 201
    assert prematureInvalidation.status_code == 409
    assert prematureInvalidation.json()["error"]["code"] == "EXPERIMENT_NOT_INVALIDATABLE"
    assert runs.status_code == 200
    assert runs.json() == {
        "schemaVersion": "1.0.0",
        "experimentId": experimentId,
        "status": "COMPLETED",
        "validForResearchUse": True,
        "count": 1,
        "pairedRuns": persistedResult["pairedRuns"],
    }
    assert metrics.status_code == 200
    assert metrics.json()["metricSummaries"] == persistedResult["metricSummaries"]
    assert metrics.json()["medianPaths"] == persistedResult["medianPaths"]
    assert metrics.json()["validForResearchUse"] is True
    assert traces.status_code == 200
    assert traces.json()["count"] == 1
    assert traces.json()["traces"] == persistedResult["traces"]
    assert crossSessionRead.status_code == 404
    assert crossSessionInvalidation.status_code == 404

    assert invalidated.status_code == 200
    assert invalidated.json()["status"] == "INVALIDATED"
    assert invalidated.json()["resultsAvailable"] is False
    assert invalidated.json()["resultsPreserved"] is True
    assert invalidated.json()["validForResearchUse"] is False
    assert invalidated.json()["invalidationReasonCode"] == "MODEL_ISSUE"
    assert invalidated.json()["invalidatedAt"] is not None
    assert repeatedInvalidation.status_code == 200
    assert repeatedInvalidation.json()["invalidationReasonCode"] == "MODEL_ISSUE"
    assert cancelAfterInvalidation.status_code == 200
    assert cancelAfterInvalidation.json()["status"] == "INVALIDATED"
    assert [response.status_code for response in blockedResponses] == [409] * 5
    assert {response.json()["error"]["code"] for response in blockedResponses} == {
        "EXPERIMENT_INVALIDATED"
    }
    invalidationEvents = [
        event for event in auditEvents if event["action"] == "EXPERIMENT_INVALIDATED"
    ]
    assert len(invalidationEvents) == 1
    assert invalidationEvents[0]["payload"]["reasonCode"] == "MODEL_ISSUE"
    assert invalidationEvents[0]["payload"]["resultHash"] == _hashJson(persistedResult)
    assert auditVerification.status_code == 200
    assert auditVerification.json()["valid"] is True
    assert stored is not None
    assert stored["result"] == persistedResult
    assert stored["checkpoint"] is None


def test_result_interpretation_chat_uses_owned_server_result_and_redacted_audit(
    tmp_path: Path,
) -> None:
    experimentId = "exp-interpretation-api"
    persistedResult = {
        "experimentId": experimentId,
        "metricSummaries": {"maxSpreadBps": {"delta": {"median": 1.5}}},
        "pairedRuns": [{"seed": 101, "delta": {"maxSpreadBps": 1.5}}],
        "limitations": ["Synthetic scenario analysis only."],
        "manifest": {"validPairedSeeds": 1},
    }
    requestPayload = {
        "schemaVersion": "1.0.0",
        "conversationId": "conversation-api-001",
        "clientRequestId": "request-api-001",
        "mode": "INITIAL",
        "language": "zh-CN",
        "reasoningSummaryRequested": True,
        "messages": [{"role": "user", "content": "请解释这次结果。"}],
    }
    captured: dict[str, object] = {}

    async def fakeInterpretation(**kwargs: object) -> ResultInterpretationRun:
        captured.update(kwargs)
        return ResultInterpretationRun(
            interpretation=ResultInterpretationAnswer(
                answer="这是有条件的情景分析，不是预测或投资建议。[result:overview]",
                analysis_summary="核对了实验边界和有效配对数量。",
                grounding_references=("result:overview",),
                follow_up_suggestions=("要继续查看配对差异吗？",),
            ),
            result_hash=_hashJson(persistedResult),
            provider="zhipu",
            model="glm-5.2",
            tool_activity=(
                ResultToolActivity(
                    tool=ResultEvidenceTool.OVERVIEW,
                    label="实验概览",
                    item_count=1,
                    truncated=False,
                    evidence_id="result:overview",
                ),
            ),
            usage=ModelUsage(promptTokens=100, completionTokens=50, cachedTokens=0),
            latency_ms=12.5,
            model_calls=1,
            cache_hit=False,
            repair_used=False,
            planner_used=False,
            prompt_version="result_interpretation_v1.0.0",
        )

    with TestClient(createApp(tmp_path)) as client:
        database = client.app.state.database
        database.createExperiment(experimentId, SESSION_A, experimentPayload(), None)
        database.updateExperiment(
            experimentId,
            SESSION_A,
            status="COMPLETED",
            result_json=persistedResult,
            progress=1.0,
            completed_pairs=1,
            completed_at="2026-07-20T20:00:00+00:00",
        )
        missingCredential = client.post(
            f"/api/v1/experiments/{experimentId}/interpretation-chat",
            headers={"X-Session-ID": SESSION_A},
            json=requestPayload,
        )
        crossOwner = client.post(
            f"/api/v1/experiments/{experimentId}/interpretation-chat",
            headers={"X-Session-ID": SESSION_B},
            json=requestPayload,
        )
        client.app.state.cognitionService.interpretExperimentResult = fakeInterpretation
        response = client.post(
            f"/api/v1/experiments/{experimentId}/interpretation-chat",
            headers={"X-Session-ID": SESSION_A},
            # 同一 clientRequestId 的失败会短期重放，避免供应商可能已经计费时
            # 浏览器无意中重复调用；用户明确重试必须使用新的请求 ID。
            json={**requestPayload, "clientRequestId": "request-api-002"},
        )
        auditItems = client.get("/api/v1/audit-events", headers={"X-Session-ID": SESSION_A}).json()[
            "items"
        ]

    assert missingCredential.status_code == 409
    assert missingCredential.json()["error"]["code"] == "LLM_CREDENTIAL_NOT_CONFIGURED"
    assert crossOwner.status_code == 404
    assert response.status_code == 200
    body = response.json()
    assert body["resultHash"] == _hashJson(persistedResult)
    assert body["message"]["language"] == "zh-CN"
    assert body["message"]["analysisSummary"] == "核对了实验边界和有效配对数量。"
    assert body["message"]["groundingReferences"] == ["result:overview"]
    assert body["message"]["followUpSuggestions"] == ["要继续查看配对差异吗？"]
    assert captured["result"] == persistedResult
    assert "apiKey" not in captured
    auditEvent = next(item for item in auditItems if item["action"] == "INTERPRETATION_GENERATED")
    auditText = json.dumps(auditEvent, ensure_ascii=False)
    assert "请解释这次结果" not in auditText
    assert "核对了实验边界" not in auditText


def test_idempotency_key_cannot_be_reused_for_different_payload(tmp_path: Path) -> None:
    with TestClient(createApp(tmp_path)) as client:
        approveAndFreeze(client, SESSION_A)
        headers = {
            "X-Session-ID": SESSION_A,
            "Idempotency-Key": "different-payload-key",
        }
        firstResponse = client.post(
            "/api/v1/experiments", headers=headers, json=experimentPayload()
        )
        changedPayload = {**experimentPayload(), "populationSize": 28}
        secondResponse = client.post("/api/v1/experiments", headers=headers, json=changedPayload)

    assert firstResponse.status_code == 201
    assert secondResponse.status_code == 409
    assert secondResponse.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_preregistered_ci_stopping_rule_can_end_after_minimum_pairs(tmp_path: Path) -> None:
    with TestClient(createApp(tmp_path)) as client:
        approveAndFreeze(client, SESSION_A)
        payload = {
            **experimentPayload(),
            "primaryOutcome": "maxSpreadBps",
            "stoppingRule": {
                "minimumPairs": 5,
                "maximumPairs": 10,
                "targetCiHalfWidth": 100.0,
            },
        }
        createResponse = client.post(
            "/api/v1/experiments",
            headers={
                "X-Session-ID": SESSION_A,
                "Idempotency-Key": "sequential-stop-0001",
            },
            json=payload,
        )
        assert createResponse.status_code == 201
        experimentId = createResponse.json()["id"]
        client.post(
            f"/api/v1/experiments/{experimentId}/start",
            headers={"X-Session-ID": SESSION_A},
        )
        deadline = time.monotonic() + 20
        status = "QUEUED"
        while status not in {"COMPLETED", "FAILED_FINAL"} and time.monotonic() < deadline:
            time.sleep(0.05)
            status = client.get(
                f"/api/v1/experiments/{experimentId}",
                headers={"X-Session-ID": SESSION_A},
            ).json()["status"]
        assert status == "COMPLETED"
        results = client.get(
            f"/api/v1/experiments/{experimentId}/results",
            headers={"X-Session-ID": SESSION_A},
        ).json()

    assert len(results["pairedRuns"]) == 5
    assert results["stoppingRule"]["triggered"] is True
    assert results["stoppingRule"]["reason"] == "TARGET_CI_HALF_WIDTH_REACHED"
    assert results["manifest"]["validPairedSeeds"] == 5
    assert results["manifest"]["requestedMaximumPairs"] == 10


def test_retryable_experiment_resumes_verified_matched_pair_checkpoint(tmp_path: Path) -> None:
    with TestClient(createApp(tmp_path)) as client:
        approveAndFreeze(client, SESSION_A)
        created = client.post(
            "/api/v1/experiments",
            headers={
                "X-Session-ID": SESSION_A,
                "Idempotency-Key": "checkpoint-resume-0001",
            },
            json=experimentPayload(),
        )
        assert created.status_code == 201
        experimentId = created.json()["id"]
        service = client.app.state.experimentService
        database = client.app.state.database
        experiment = database.getExperiment(experimentId, SESSION_A)
        assert experiment is not None
        requestData = experiment["request"]
        eventPack = service.eventPacks.getEventPack(PACK_ID, SESSION_A)
        seed = requestData["seedRoot"]
        commonArguments = {
            "seed": seed,
            "populationSize": requestData["populationSize"],
            "steps": requestData["steps"],
            "parameter": requestData["intervention"]["parameter"],
            "eventPack": eventPack,
            "cognitiveSignals": [],
            "scenarioConfig": requestData,
        }
        baselineRun = runScenario(
            **commonArguments,
            value=requestData["intervention"]["baselineValue"],
        )
        interventionRun = runScenario(
            **commonArguments,
            value=requestData["intervention"]["interventionValue"],
        )
        cognitionRun = service._prepareCognitiveSignals(
            experimentId,
            SESSION_A,
            requestData,
            eventPack,
        )
        stoppingDecision = service._initialStoppingDecision(requestData)
        stoppingDecision["completedPairs"] = 1
        seeds = [
            requestData["seedRoot"] + index * 1_009 for index in range(requestData["seedCount"])
        ]
        checkpoint = service._checkpointPayload(
            requestHash=_hashJson(requestData),
            eventPackHash=_hashJson(eventPack),
            seedListHash=_hashJson(seeds),
            baselineRuns=[baselineRun],
            interventionRuns=[interventionRun],
            cognitionRun=cognitionRun,
            stoppingDecision=stoppingDecision,
        )
        database.updateExperiment(
            experimentId,
            SESSION_A,
            status="FAILED_RETRYABLE",
            error_code="SERVER_RESTARTED",
            completed_pairs=1,
            checkpoint_blob=checkpoint,
            runtime_json={
                "phase": "FAILED_RETRYABLE",
                "checkpointPairs": 1,
                "logs": [],
            },
        )

        started = client.post(
            f"/api/v1/experiments/{experimentId}/start",
            headers={"X-Session-ID": SESSION_A},
        )
        assert started.status_code == 200
        deadline = time.monotonic() + 20
        statusPayload = started.json()
        while (
            statusPayload["status"] not in {"COMPLETED", "FAILED_FINAL"}
            and time.monotonic() < deadline
        ):
            time.sleep(0.05)
            statusPayload = client.get(
                f"/api/v1/experiments/{experimentId}",
                headers={"X-Session-ID": SESSION_A},
            ).json()
        results = client.get(
            f"/api/v1/experiments/{experimentId}/results",
            headers={"X-Session-ID": SESSION_A},
        )
        audit = client.get(
            "/api/v1/audit-events",
            headers={"X-Session-ID": SESSION_A},
        ).json()["items"]
        persisted = database.getExperiment(experimentId, SESSION_A)

    assert statusPayload["status"] == "COMPLETED"
    assert statusPayload["runtime"]["resumedFromCheckpoint"] is True
    assert any(
        "Resumed from a verified checkpoint" in entry["message"]
        for entry in statusPayload["runtime"]["logs"]
    )
    assert results.status_code == 200
    assert len(results.json()["pairedRuns"]) == 10
    assert any(item["action"] == "RUN_RESUMED_FROM_CHECKPOINT" for item in audit)
    assert persisted is not None
    assert persisted["checkpoint"] is None
