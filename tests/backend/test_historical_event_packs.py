from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.main import createApp
from backend.app.service import EventPackService

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVENT_PACKS_ROOT = REPOSITORY_ROOT / "event-packs"
PACK_EXPECTATIONS = {
    "crowdstrike-outage-2024-v1": {
        "parameter": "clarificationDelay",
        "instrumentId": "CRWD",
        "sessionId": "historical-crowdstrike-session",
    },
    "gamestop-meme-2021-v1": {
        "parameter": "socialAmplification",
        "instrumentId": "GME",
        "sessionId": "historical-gamestop-session",
    },
}


def loadJson(packId: str, fileName: str) -> Any:
    return json.loads((EVENT_PACKS_ROOT / packId / fileName).read_text(encoding="utf-8"))


def parseUtc(value: str) -> datetime:
    assert value.endswith("Z"), value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo == UTC
    return parsed


@pytest.mark.parametrize("packId", PACK_EXPECTATIONS)
def test_historical_pack_has_canonical_manifest_and_claims(packId: str) -> None:
    packRoot = EVENT_PACKS_ROOT / packId
    assert {path.name for path in packRoot.glob("*.json")} == {
        "manifest.json",
        "claims.json",
    }

    manifest = loadJson(packId, "manifest.json")
    claims = loadJson(packId, "claims.json")
    expectation = PACK_EXPECTATIONS[packId]

    assert manifest["id"] == packId
    assert manifest["fileInventory"] == ["manifest.json", "claims.json"]
    assert manifest["instrument"]["id"] == expectation["instrumentId"]
    assert manifest["instrument"]["marketDataMode"] == "SYNTHETIC"
    assert manifest["defaultExperiment"]["intervention"]["parameter"] == expectation["parameter"]
    assert manifest["validationStatus"]["level"] == "L5_CASE_AVAILABLE"
    assert manifest["validationStatus"]["empiricalCalibration"] == ("PENDING_HUMAN_STUDY")
    assert claims
    assert all(claim["reviewStatus"] == "AI_PROPOSED" for claim in claims)


@pytest.mark.parametrize("packId", PACK_EXPECTATIONS)
def test_official_facts_and_synthetic_mechanisms_are_strictly_separated(
    packId: str,
) -> None:
    manifest = loadJson(packId, "manifest.json")
    claims = loadJson(packId, "claims.json")
    sources = {source["sourceId"]: source for source in manifest["sources"]}
    cutoff = parseUtc(manifest["asOf"])

    assert len(sources) == len(manifest["sources"])
    assert all(parseUtc(source["knownAt"]) <= cutoff for source in sources.values())

    officialClaims = [claim for claim in claims if claim["synthetic"] is False]
    syntheticClaims = [claim for claim in claims if claim["synthetic"] is True]
    assert officialClaims
    assert syntheticClaims

    for claim in claims:
        assert claim["sourceIds"]
        assert set(claim["sourceIds"]).issubset(sources)
        assert parseUtc(claim["knownAt"]) <= cutoff

    assert all(
        sources[sourceId]["isOfficial"] is True
        for claim in officialClaims
        for sourceId in claim["sourceIds"]
    )
    assert all(
        sources[sourceId]["sourceType"] == "SYNTHETIC_RESEARCH_FIXTURE"
        for claim in syntheticClaims
        for sourceId in claim["sourceIds"]
    )
    assert all(
        claim["claimType"] in {"SCENARIO_ASSUMPTION", "MODEL_ASSUMPTION"}
        for claim in syntheticClaims
    )
    assert manifest["instrument"]["initialPriceMeaning"].startswith(
        "A normalized synthetic simulator reference"
    )


def test_case_specific_factual_boundaries_are_explicit() -> None:
    crowdstrike = loadJson("crowdstrike-outage-2024-v1", "manifest.json")
    crowdstrikeClaims = loadJson("crowdstrike-outage-2024-v1", "claims.json")
    gameStop = loadJson("gamestop-meme-2021-v1", "manifest.json")
    gameStopClaims = loadJson("gamestop-meme-2021-v1", "claims.json")

    assert crowdstrike["eventWindow"]["updateReleasedAt"] == "2024-07-19T04:09:00Z"
    assert crowdstrike["eventWindow"]["updateRevertedAt"] == "2024-07-19T05:27:00Z"
    assert any(
        claim["claimId"] == "claim-microsoft-device-estimate"
        and "not mapped" in claim["limitations"][0]
        for claim in crowdstrikeClaims
    )

    assert gameStop["defaultExperiment"]["intervention"] == {
        "parameter": "socialAmplification",
        "baselineValue": 1.0,
        "interventionValue": 1.8,
    }
    qualifiedClaim = next(
        claim for claim in gameStopClaims if claim["claimId"] == "claim-short-covering-qualified"
    )
    assert "small fraction of overall buy volume" in qualifiedClaim["text"]
    assert any(
        limitation["code"] == "DIRECTIONAL_MODEL_LIMIT" for limitation in gameStop["limitations"]
    )


@pytest.mark.parametrize("packId,expectation", PACK_EXPECTATIONS.items())
def test_human_review_freeze_and_default_preflight_succeed(
    tmp_path: Path,
    packId: str,
    expectation: dict[str, str],
) -> None:
    sessionId = expectation["sessionId"]
    with TestClient(createApp(tmp_path / packId)) as client:
        draft = client.get(
            f"/api/v1/event-packs/{packId}",
            headers={"X-Session-ID": sessionId},
        ).json()
        unresolvedFreeze = client.post(
            f"/api/v1/event-packs/{packId}/freeze",
            headers={"X-Session-ID": sessionId},
        )
        assert unresolvedFreeze.status_code == 422
        assert unresolvedFreeze.json()["error"]["code"] == ("CLAIMS_REQUIRE_HUMAN_REVIEW")

        for claim in draft["claims"]:
            review = client.post(
                f"/api/v1/event-packs/{packId}/claims/{claim['claimId']}/review",
                headers={"X-Session-ID": sessionId},
                json={
                    "status": "HUMAN_APPROVED",
                    "rationale": (
                        "Verified against the linked official source or accepted as "
                        "a synthetic scenario assumption."
                    ),
                },
            )
            assert review.status_code == 200

        frozen = client.post(
            f"/api/v1/event-packs/{packId}/freeze",
            headers={"X-Session-ID": sessionId},
        )
        assert frozen.status_code == 200
        assert frozen.json()["status"] == "FROZEN"

        defaultExperiment = frozen.json()["defaultExperiment"]
        validation = client.post(
            "/api/v1/scenarios/validate",
            headers={"X-Session-ID": sessionId},
            json={
                "eventPackId": packId,
                "question": defaultExperiment["question"],
                "questionZh": defaultExperiment["questionZh"],
                "intervention": defaultExperiment["intervention"],
                "seedCount": 10,
                "populationSize": 14,
                "steps": 30,
                "seedRoot": defaultExperiment["seedRoot"],
                "market": {
                    "instrumentId": expectation["instrumentId"],
                    "benchmarkId": defaultExperiment["market"]["benchmarkId"],
                    "initialPrice": 100.0,
                },
            },
        )

    assert validation.status_code == 200
    body = validation.json()
    assert body["valid"] is True
    assert body["errors"] == []
    assert body["scenarioDiff"]["parameter"] == expectation["parameter"]


def test_event_pack_service_loads_both_historical_cases() -> None:
    packs = EventPackService._loadCanonicalPacks(EVENT_PACKS_ROOT)

    for packId, expectation in PACK_EXPECTATIONS.items():
        eventPack = packs[packId]
        assert eventPack["claims"]
        assert eventPack["mechanismRules"]["riskOffClaimId"] == "claim-risk-off"
        assert eventPack["mechanismRules"]["clarificationClaimId"] == ("claim-clarification")
        assert (
            eventPack["defaultExperiment"]["intervention"]["parameter"]
            == (expectation["parameter"])
        )
