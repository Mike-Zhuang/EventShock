from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import createApp

SESSION_ID = "study-api-session-12345"
OTHER_SESSION_ID = "study-api-other-session-12345"
EVENT_PACK_ID = "spacex-synthetic-v1"


def studyPayload() -> dict:
    return {
        "eventPackId": EVENT_PACK_ID,
        "preregistration": {
            "studyId": "spacex-liquidity-study-v1",
            "question": (
                "How does market-maker capacity change the model-internal liquidity response?"
            ),
            "claimLevel": "MODEL_INTERNAL_SENSITIVITY",
            "primaryOutcomes": [
                {
                    "outcomeId": "max-spread-bps",
                    "familyId": "primary-liquidity",
                    "expectedDirection": "INCREASE",
                    "rationale": "Preregister maximum spread before any Study run is observed.",
                    "minimumEffectOfInterest": 1.0,
                },
                {
                    "outcomeId": "max-drawdown-pct",
                    "familyId": "primary-liquidity",
                    "expectedDirection": "INCREASE",
                    "rationale": "Preregister maximum drawdown before any Study run is observed.",
                    "minimumEffectOfInterest": 0.1,
                },
            ],
            "secondaryOutcomes": [
                {
                    "outcomeId": "total-volume",
                    "familyId": "secondary-activity",
                    "expectedDirection": "TWO_SIDED",
                    "rationale": "Treat total volume as a secondary exploratory outcome.",
                }
            ],
            "exclusionRules": ["Exclude only explicit simulator invariant failures."],
            "supportCriterion": "Matched effects follow the preregistered direction.",
            "contradictionCriterion": "Matched effects follow the opposite direction.",
            "inconclusiveCriterion": "Intervals remain wide or a negative control fails.",
            "knownLimitations": [
                "This is a synthetic mechanism Study, not a forecast or causal proof."
            ],
        },
        "design": {
            "kind": "FULL_FACTORIAL",
            "factors": [
                {
                    "parameterPath": "intervention.value",
                    "baselineValue": 1.0,
                    "levels": [0.5, 1.0, 1.5],
                    "rationale": ("Vary market-maker capacity across three preregistered levels."),
                    "evidenceBasis": "ASSUMPTION",
                }
            ],
            "designSeed": 719,
        },
        "execution": {
            "interventionParameter": "marketMakerCapacity",
            "baselineInterventionValue": 1.0,
            "matchedSeedCount": 2,
            "seedRoot": 123_000,
            "populationSize": 14,
            "steps": 30,
            "frozenCognitiveRepresentativeCount": 2,
        },
        "nullToleranceByOutcome": {
            "max-spread-bps": 0.01,
            "max-drawdown-pct": 0.01,
        },
        "alpha": 0.05,
        "bootstrapResamples": 100,
        "analysisSeed": 719,
        "acknowledgedModelInternalOnly": True,
        "acknowledgedProxyAblations": True,
    }


def freezeSyntheticPack(client: TestClient) -> None:
    review = client.post(
        f"/api/v1/event-packs/{EVENT_PACK_ID}/claims/claim-limited-depth/review",
        headers={"X-Session-ID": SESSION_ID},
        json={"status": "HUMAN_APPROVED"},
    )
    assert review.status_code == 200
    frozen = client.post(
        f"/api/v1/event-packs/{EVENT_PACK_ID}/freeze",
        headers={"X-Session-ID": SESSION_ID},
    )
    assert frozen.status_code == 200
    assert frozen.json()["status"] == "FROZEN"


def canonicalHash(value: object) -> str:
    serialized = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(serialized).hexdigest()}"


def test_study_presets_publish_every_required_boundary(tmp_path: Path) -> None:
    with TestClient(createApp(tmp_path)) as client:
        response = client.get("/api/v1/studies/presets")

    assert response.status_code == 200
    payload = response.json()
    assert payload["historicalValidityEstablished"] is False
    assert payload["requiredNegativeControlCount"] == 8
    assert payload["requiredAblationCount"] == 10
    assert {item["presetId"] for item in payload["items"]} == {
        "spacex-s1-index-demand-liquidity",
        "spacex-s2-analyst-disagreement-narrative",
        "spacex-s3-misinformation-clarification",
        "crowdstrike-c1-communication-timing",
        "crowdstrike-c2-damage-uncertainty",
        "gamestop-g1-network-topology",
        "gamestop-g2-market-mechanisms",
    }
    assert all(item["titleZh"] for item in payload["items"])
    assert {item["outcomeId"] for item in payload["supportedOutcomes"]}.issuperset(
        {"max-spread-bps", "max-drawdown-pct", "recovery-steps"}
    )


def test_design_preview_is_deterministic_and_fail_closed_on_size(tmp_path: Path) -> None:
    previewRequest = {
        "design": studyPayload()["design"],
        "matchedSeedCount": 2,
        "populationSize": 14,
        "steps": 30,
    }
    with TestClient(createApp(tmp_path)) as client:
        first = client.post("/api/v1/studies/design-preview", json=previewRequest)
        second = client.post("/api/v1/studies/design-preview", json=previewRequest)
        tooSmallRequest = json.loads(json.dumps(previewRequest))
        tooSmallRequest["design"]["factors"][0]["levels"] = [0.5, 1.0]
        tooSmall = client.post("/api/v1/studies/design-preview", json=tooSmallRequest)
        tooLargeRequest = json.loads(json.dumps(previewRequest))
        tooLargeRequest["design"]["factors"] = [
            {
                "parameterPath": path,
                "baselineValue": 0.5,
                "levels": [0.1, 0.5, 0.9],
                "rationale": "Exercise a bounded preregistered factor range.",
            }
            for path in (
                "network.correction_reach",
                "network.echo_chamber_strength",
                "network.rewiring_probability",
                "population.institutional_share",
            )
        ]
        tooLarge = client.post("/api/v1/studies/design-preview", json=tooLargeRequest)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["designCellCount"] == 3
    assert first.json()["totalExecutionCells"] == 22
    assert first.json()["expectedRunCount"] == 44
    assert first.json()["estimatedWorkUnits"] == 18_480
    assert tooSmall.status_code == 422
    assert tooSmall.json()["error"]["code"] == "STUDY_DESIGN_TOO_SMALL"
    assert tooLarge.status_code == 422
    assert tooLarge.json()["error"]["code"] == "STUDY_DESIGN_LIMIT"


def test_study_run_is_persisted_auditable_and_session_isolated(tmp_path: Path) -> None:
    databasePath = tmp_path / "eventshock.db"
    with TestClient(createApp(tmp_path)) as client:
        freezeSyntheticPack(client)
        response = client.post(
            "/api/v1/studies/run",
            headers={"X-Session-ID": SESSION_ID},
            json=studyPayload(),
        )
        assert response.status_code == 201, response.text
        payload = response.json()
        runId = payload["runId"]
        listed = client.get(
            "/api/v1/studies",
            headers={"X-Session-ID": SESSION_ID},
        )
        fetched = client.get(
            f"/api/v1/studies/{runId}",
            headers={"X-Session-ID": SESSION_ID},
        )
        otherSession = client.get(
            f"/api/v1/studies/{runId}",
            headers={"X-Session-ID": OTHER_SESSION_ID},
        )
        audit = client.get(
            "/api/v1/audit-events",
            headers={"X-Session-ID": SESSION_ID},
        )

        coreResult = payload["result"]["result"]
        assert payload["historicalValidityEstablished"] is False
        assert coreResult["audit"]["historicalValidityEstablished"] is False
        assert coreResult["audit"]["commonRandomSeedScheduleVerified"] is True
        assert coreResult["audit"]["expectedRunCount"] == 44
        assert coreResult["audit"]["completedRunCount"] == 44
        assert len(coreResult["cells"]) == 22
        assert len(coreResult["runs"]) == 44
        assert len(coreResult["negativeControls"]) == 8
        assert {cell["role"] for cell in coreResult["cells"]} == {
            "BASELINE",
            "DESIGN",
            "NEGATIVE_CONTROL",
            "ABLATION",
        }
        assert payload["specHash"] == canonicalHash(payload["spec"])
        assert payload["resultHash"] == canonicalHash(payload["result"])
        assert payload["result"]["executionProtocol"]["requiredAblationsIncluded"] == 10
        assert "NOT_LIVE_LLM" in payload["result"]["executionProtocol"]["cognitionMode"]
        assert listed.status_code == 200
        assert listed.json()["items"][0]["runId"] == runId
        assert "result" not in listed.json()["items"][0]
        assert "spec" not in listed.json()["items"][0]
        assert fetched.status_code == 200
        assert fetched.json() == payload
        assert otherSession.status_code == 404
        studyAudit = next(
            item for item in audit.json()["items"] if item["action"] == "STUDY_COMPLETED"
        )
        assert studyAudit["entityId"] == runId
        assert studyAudit["payload"]["resultHash"] == payload["resultHash"]
        assert studyAudit["payload"]["historicalValidityEstablished"] is False

        with sqlite3.connect(databasePath) as connection:
            connection.execute(
                "UPDATE study_runs SET result_json='{}' WHERE run_id=?",
                (runId,),
            )
        tampered = client.get(
            f"/api/v1/studies/{runId}",
            headers={"X-Session-ID": SESSION_ID},
        )

    assert tampered.status_code == 500
    assert tampered.json()["error"]["code"] == "STUDY_INTEGRITY_FAILURE"


def test_study_run_requires_frozen_pack_and_explicit_boundaries(tmp_path: Path) -> None:
    payload = studyPayload()
    with TestClient(createApp(tmp_path)) as client:
        notFrozen = client.post(
            "/api/v1/studies/run",
            headers={"X-Session-ID": SESSION_ID},
            json=payload,
        )
        payload["acknowledgedModelInternalOnly"] = False
        unacknowledged = client.post(
            "/api/v1/studies/run",
            headers={"X-Session-ID": SESSION_ID},
            json=payload,
        )

    assert notFrozen.status_code == 422
    assert notFrozen.json()["error"]["code"] == "STUDY_EVENT_PACK_NOT_FROZEN"
    assert unacknowledged.status_code == 422
    assert unacknowledged.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"
