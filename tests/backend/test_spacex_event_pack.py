from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.service import EventPackService

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVENT_PACKS_ROOT = REPOSITORY_ROOT / "event-packs"
PACK_ROOT = EVENT_PACKS_ROOT / "spacex-nasdaq100-2026-v1"
PACK_ID = "spacex-nasdaq100-2026-v1"
ANNOUNCEMENT_KNOWN_AT = "2026-06-27T00:00:00Z"
OBSERVATION_CUTOFF = "2026-07-07T13:30:00Z"
REQUIRED_JSON_FILES = {
    "manifest.json",
    "event.json",
    "timeline.json",
    "entities.json",
    "sources.json",
    "claims.json",
    "market.json",
    "benchmark.json",
    "instrument.json",
    "calibration.json",
    "defaults.json",
    "validation.json",
    "limitations.json",
    "checksums.json",
}


def loadJson(fileName: str) -> Any:
    return json.loads((PACK_ROOT / fileName).read_text(encoding="utf-8"))


def parseUtc(value: str) -> datetime:
    assert value.endswith("Z"), value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo == UTC
    return parsed


def test_required_files_are_present_and_valid_json() -> None:
    actualFiles = {path.name for path in PACK_ROOT.glob("*.json")}
    assert actualFiles == REQUIRED_JSON_FILES

    for fileName in sorted(REQUIRED_JSON_FILES):
        document = loadJson(fileName)
        assert document is not None

    manifest = loadJson("manifest.json")
    assert manifest["id"] == PACK_ID
    assert set(manifest["fileInventory"]) == REQUIRED_JSON_FILES


def test_claims_and_manifest_sources_resolve_to_canonical_source_registry() -> None:
    sources = loadJson("sources.json")["items"]
    claims = loadJson("claims.json")
    manifestSources = loadJson("manifest.json")["sources"]
    sourceIds = [source["sourceId"] for source in sources]

    assert len(sourceIds) == len(set(sourceIds))
    assert {source["sourceId"] for source in manifestSources} == set(sourceIds)

    for claim in claims:
        assert claim["sourceIds"]
        assert set(claim["sourceIds"]).issubset(sourceIds)


def test_official_facts_and_synthetic_assumptions_are_strictly_separated() -> None:
    sources = {source["sourceId"]: source for source in loadJson("sources.json")["items"]}
    claims = loadJson("claims.json")
    cutoff = parseUtc(OBSERVATION_CUTOFF)

    officialClaims = [claim for claim in claims if claim["claimType"].startswith("OFFICIAL_")]
    syntheticClaims = [claim for claim in claims if claim["synthetic"]]

    assert officialClaims
    assert syntheticClaims
    assert all(claim["synthetic"] is False for claim in officialClaims)
    assert all(parseUtc(claim["knownAt"]) <= cutoff for claim in officialClaims)
    assert all(
        sources[sourceId]["isOfficial"] is True
        for claim in officialClaims
        for sourceId in claim["sourceIds"]
    )
    assert all(
        claim["claimType"]
        in {"MODEL_ASSUMPTION", "SCENARIO_ASSUMPTION", "SYNTHETIC_MARKET_CONDITION"}
        for claim in syntheticClaims
    )
    assert all(
        sources[sourceId]["sourceType"] == "SYNTHETIC_RESEARCH_FIXTURE"
        for claim in syntheticClaims
        for sourceId in claim["sourceIds"]
    )


def test_canonical_claims_never_impersonate_human_review() -> None:
    claims = loadJson("claims.json")

    # 仓库内整理出的事实与假设仍只是候选项；真正的批准必须发生在用户会话中。
    assert all(claim["reviewStatus"] == "AI_PROPOSED" for claim in claims)
    assert all(claim["reviewedBy"] is None for claim in claims)


def test_nasdaq_announcement_cannot_leak_before_official_publication_time() -> None:
    sources = {source["sourceId"]: source for source in loadJson("sources.json")["items"]}
    claims = loadJson("claims.json")
    timeline = loadJson("timeline.json")["items"]

    assert sources["source-nasdaq-inclusion-20260626"]["knownAt"] == ANNOUNCEMENT_KNOWN_AT
    assert (
        sources["source-globenewswire-inclusion-time-20260626"]["knownAt"] == ANNOUNCEMENT_KNOWN_AT
    )

    announcementClaims = [
        claim for claim in claims if "source-nasdaq-inclusion-20260626" in claim["sourceIds"]
    ]
    assert announcementClaims
    assert all(
        parseUtc(claim["knownAt"]) >= parseUtc(ANNOUNCEMENT_KNOWN_AT)
        for claim in announcementClaims
    )

    announcementTimeline = next(
        item for item in timeline if item["timelineId"] == "timeline-nasdaq100-announcement"
    )
    inclusionTimeline = next(
        item for item in timeline if item["timelineId"] == "timeline-nasdaq100-effective"
    )
    assert announcementTimeline["knownAt"] == ANNOUNCEMENT_KNOWN_AT
    assert announcementTimeline["eventAt"] == ANNOUNCEMENT_KNOWN_AT
    assert inclusionTimeline["knownAt"] == ANNOUNCEMENT_KNOWN_AT


def test_post_event_estimate_is_source_metadata_only() -> None:
    sources = {source["sourceId"]: source for source in loadJson("sources.json")["items"]}
    claims = loadJson("claims.json")
    calibration = loadJson("calibration.json")
    postEventSourceId = "source-reuters-jpm-estimate-20260707"

    assert sources[postEventSourceId]["simulationEligibility"] == "POST_EVENT_VALIDATION_ONLY"
    assert parseUtc(sources[postEventSourceId]["knownAt"]) > parseUtc(OBSERVATION_CUTOFF)
    assert all(postEventSourceId not in claim["sourceIds"] for claim in claims)
    excludedSourceIds = {estimate["sourceId"] for estimate in calibration["excludedEstimates"]}
    assert postEventSourceId in excludedSourceIds


def test_market_and_benchmark_are_unambiguously_synthetic() -> None:
    market = loadJson("market.json")
    benchmark = loadJson("benchmark.json")

    for series in (market, benchmark):
        assert series["dataMode"] == "SYNTHETIC"
        assert series["isHistoricalMarketData"] is False
        assert series["isObserved"] is False
        assert series["observations"]
        assert all(observation["synthetic"] is True for observation in series["observations"])
        assert all(
            parseUtc(observation["timestamp"]).tzinfo == UTC
            for observation in series["observations"]
        )

    instrument = loadJson("instrument.json")
    assert instrument["unknownOrUnlicensed"]["freeFloatShares"] is None
    assert instrument["unknownOrUnlicensed"]["july7ObservedPrice"] is None
    assert instrument["simulationReference"]["isJuly7Observation"] is False


def test_default_experiment_changes_only_synthetic_market_maker_capacity() -> None:
    manifestDefault = loadJson("manifest.json")["defaultExperiment"]
    defaultsDefault = loadJson("defaults.json")["defaultExperiment"]
    calibration = loadJson("calibration.json")

    assert manifestDefault == defaultsDefault
    assert manifestDefault["intervention"] == {
        "parameter": "marketMakerCapacity",
        "baselineValue": 1.0,
        "interventionValue": 0.65,
    }
    assert calibration["intervention"]["parameterClass"] == "SYNTHETIC_DEPTH_PROXY"
    assert calibration["intervention"]["observedSpcxStatistic"] is False


def test_event_pack_service_loads_manifest_sources_defaults_rules_and_limitations() -> None:
    packs = EventPackService._loadCanonicalPacks(EVENT_PACKS_ROOT)
    eventPack = packs[PACK_ID]

    assert eventPack["id"] == PACK_ID
    assert eventPack["claims"]
    assert eventPack["sources"]
    assert eventPack["defaultExperiment"]["intervention"]["parameter"] == "marketMakerCapacity"
    assert eventPack["mechanismRules"]["riskOffClaimId"] == "claim-risk-off"
    assert eventPack["mechanismRules"]["clarificationClaimId"] == "claim-clarification"
    assert eventPack["limitations"]


def test_local_pack_checksums_match_file_bytes() -> None:
    checksums = loadJson("checksums.json")
    expectedFiles = REQUIRED_JSON_FILES - {"checksums.json"}

    assert checksums["algorithm"] == "SHA-256"
    assert set(checksums["files"]) == expectedFiles
    for fileName, expectedDigest in checksums["files"].items():
        actualDigest = hashlib.sha256((PACK_ROOT / fileName).read_bytes()).hexdigest()
        assert expectedDigest == f"sha256:{actualDigest}"
