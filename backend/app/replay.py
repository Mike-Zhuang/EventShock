"""可复现实验 ZIP 的离线重放与哈希核验。"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import sys
import zipfile
from pathlib import Path
from typing import Any

from backend.app.simulation.engine import runScenario

SUPPORTED_ENGINE_VERSION = "eventshock-simulation-0.3.0"
REQUIRED_MEMBERS = frozenset(
    {
        "manifest.json",
        "event_pack_manifest.json",
        "scenario_baseline.json",
        "scenario_intervention.json",
        "cognitive_decisions.json",
        "random_seeds.csv",
        "run_level_metrics.csv",
    }
)
MAX_BUNDLE_BYTES = 128 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024


class ReplayBundleError(ValueError):
    """导出包不完整、不兼容或不满足重放安全边界。"""


def replayBundle(
    bundlePath: Path,
    *,
    requireExactPython: bool = True,
) -> dict[str, Any]:
    """重跑基准/干预配对，并核对导出时记录的指标与日志哈希。"""

    resolvedPath = bundlePath.expanduser().resolve()
    if not resolvedPath.is_file():
        raise ReplayBundleError(f"bundle does not exist: {resolvedPath}")
    if resolvedPath.stat().st_size > MAX_BUNDLE_BYTES:
        raise ReplayBundleError("bundle exceeds the 128 MiB replay limit")
    if requireExactPython and sys.version_info[:3] != (3, 12, 13):
        raise ReplayBundleError(
            "replay requires CPython 3.12.13; "
            f"current version is {sys.version_info.major}.{sys.version_info.minor}."
            f"{sys.version_info.micro}"
        )

    with zipfile.ZipFile(resolvedPath) as archive:
        _validateArchive(archive)
        manifest = _readJson(archive, "manifest.json")
        eventPack = _readJson(archive, "event_pack_manifest.json")
        baselineScenario = _readJson(archive, "scenario_baseline.json")
        interventionScenario = _readJson(archive, "scenario_intervention.json")
        cognition = _readJson(archive, "cognitive_decisions.json")
        seeds = _readSeeds(archive.read("random_seeds.csv"))
        expectedRows = _readMetricRows(archive.read("run_level_metrics.csv"))

    checks = _validateManifestAndScenarios(
        manifest,
        eventPack,
        baselineScenario,
        interventionScenario,
        seeds,
    )
    requestData = _scenarioRequest(baselineScenario)
    intervention = _mapping(requestData.get("intervention"), "scenario.intervention")
    signals = _listOfMappings(cognition.get("items", []), "cognitive_decisions.items")
    mismatches: list[dict[str, Any]] = []
    replayedRuns: list[dict[str, Any]] = []

    for seed in seeds:
        commonArguments = {
            "seed": seed,
            "populationSize": _integer(requestData.get("populationSize"), "populationSize"),
            "steps": _integer(requestData.get("steps"), "steps"),
            "parameter": _text(intervention.get("parameter"), "intervention.parameter"),
            "eventPack": eventPack,
            "cognitiveSignals": signals,
            "scenarioConfig": requestData,
        }
        baselineRun = runScenario(
            **commonArguments,
            value=_number(intervention.get("baselineValue"), "intervention.baselineValue"),
        )
        interventionRun = runScenario(
            **commonArguments,
            value=_number(
                intervention.get("interventionValue"),
                "intervention.interventionValue",
            ),
        )
        for role, run in (("baseline", baselineRun), ("intervention", interventionRun)):
            expected = expectedRows.get((seed, role))
            if expected is None:
                mismatches.append(
                    {
                        "seed": seed,
                        "scenarioRole": role,
                        "field": "row",
                        "expected": "present",
                        "actual": "missing",
                    }
                )
                continue
            _compareRun(seed, role, run, expected, mismatches)
        replayedRuns.append(
            {
                "seed": seed,
                "baselineEventLogHash": baselineRun["eventLogHash"],
                "interventionEventLogHash": interventionRun["eventLogHash"],
            }
        )

    checks.append(
        {
            "id": "run_hashes_and_metrics",
            "passed": not mismatches,
            "detail": (
                "Every replayed event-log hash and exported run metric matched."
                if not mismatches
                else f"Detected {len(mismatches)} replay mismatch(es)."
            ),
        }
    )
    verified = all(bool(check["passed"]) for check in checks) and not mismatches
    return {
        "verified": verified,
        "bundle": str(resolvedPath),
        "experimentId": manifest.get("experimentId"),
        "engineVersion": manifest.get("engineVersion"),
        "pythonVersion": (
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        ),
        "pairedSeeds": len(seeds),
        "checks": checks,
        "mismatches": mismatches,
        "replayedRuns": replayedRuns,
        "interpretationBoundary": "DETERMINISTIC_INTERNAL_REPLAY_NOT_EXTERNAL_VALIDATION",
    }


def _validateArchive(archive: zipfile.ZipFile) -> None:
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise ReplayBundleError("bundle contains duplicate member names")
    missing = REQUIRED_MEMBERS - set(names)
    if missing:
        raise ReplayBundleError(f"bundle is missing required members: {sorted(missing)}")
    for info in archive.infolist():
        if info.file_size > MAX_MEMBER_BYTES:
            raise ReplayBundleError(f"bundle member is too large: {info.filename}")
        normalized = Path(info.filename)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ReplayBundleError(f"unsafe bundle member path: {info.filename}")


def _validateManifestAndScenarios(
    manifest: dict[str, Any],
    eventPack: dict[str, Any],
    baselineScenario: dict[str, Any],
    interventionScenario: dict[str, Any],
    seeds: list[int],
) -> list[dict[str, Any]]:
    engineVersion = manifest.get("engineVersion")
    if engineVersion != SUPPORTED_ENGINE_VERSION:
        raise ReplayBundleError(
            f"unsupported engine version {engineVersion!r}; expected {SUPPORTED_ENGINE_VERSION!r}"
        )
    baselineRequest = _scenarioRequest(baselineScenario)
    interventionRequest = _scenarioRequest(interventionScenario)
    if baselineRequest != interventionRequest:
        raise ReplayBundleError(
            "baseline and intervention files differ outside active scenario role"
        )
    intervention = _mapping(baselineRequest.get("intervention"), "scenario.intervention")
    expectedHashes = {
        "complete_configuration_hash": (
            manifest.get("completeConfigurationHash"),
            _hashJson(baselineRequest),
        ),
        "seed_list_hash": (manifest.get("seedListHash"), _hashJson(seeds)),
        "event_pack_hash": (manifest.get("eventPackHash"), _hashJson(eventPack)),
        "baseline_scenario_hash": (
            manifest.get("baselineScenarioHash"),
            _hashJson(_minimalScenario(baselineRequest, intervention.get("baselineValue"))),
        ),
        "intervention_scenario_hash": (
            manifest.get("interventionScenarioHash"),
            _hashJson(_minimalScenario(baselineRequest, intervention.get("interventionValue"))),
        ),
    }
    checks = []
    for checkId, (expected, actual) in expectedHashes.items():
        checks.append(
            {
                "id": checkId,
                "passed": expected == actual,
                "detail": (
                    "Recorded SHA-256 matches bundle contents."
                    if expected == actual
                    else "Recorded SHA-256 does not match bundle contents."
                ),
            }
        )
    if not all(bool(check["passed"]) for check in checks):
        raise ReplayBundleError("bundle manifest hashes do not match bundle contents")
    return checks


def _compareRun(
    seed: int,
    role: str,
    run: dict[str, Any],
    expected: dict[str, str],
    mismatches: list[dict[str, Any]],
) -> None:
    expectedHash = expected.get(f"{role}_event_log_hash")
    if expectedHash != run["eventLogHash"]:
        mismatches.append(
            {
                "seed": seed,
                "scenarioRole": role,
                "field": "eventLogHash",
                "expected": expectedHash,
                "actual": run["eventLogHash"],
            }
        )
    for metricName, actual in run["metrics"].items():
        column = f"{role}_{metricName}"
        if column not in expected:
            continue
        expectedValue = expected[column]
        if expectedValue == "" and actual is None:
            continue
        try:
            numericExpected = float(expectedValue)
            numericActual = float(actual)
        except (TypeError, ValueError):
            equal = str(actual) == expectedValue
        else:
            equal = math.isclose(numericExpected, numericActual, rel_tol=0.0, abs_tol=1e-6)
        if not equal:
            mismatches.append(
                {
                    "seed": seed,
                    "scenarioRole": role,
                    "field": metricName,
                    "expected": expectedValue,
                    "actual": actual,
                }
            )


def _minimalScenario(requestData: dict[str, Any], value: Any) -> dict[str, Any]:
    intervention = _mapping(requestData.get("intervention"), "scenario.intervention")
    return {
        "eventPackId": requestData.get("eventPackId"),
        "populationSize": requestData.get("populationSize"),
        "steps": requestData.get("steps"),
        "parameter": intervention.get("parameter"),
        "value": value,
    }


def _scenarioRequest(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in {"scenarioRole", "activeValue"}}


def _readJson(archive: zipfile.ZipFile, name: str) -> dict[str, Any]:
    try:
        value = json.loads(archive.read(name))
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ReplayBundleError(f"invalid JSON member: {name}") from error
    return _mapping(value, name)


def _readSeeds(value: bytes) -> list[int]:
    try:
        rows = list(csv.DictReader(io.StringIO(value.decode("utf-8"))))
        seeds = [_integer(row.get("seed"), "random_seeds.seed") for row in rows]
    except (UnicodeDecodeError, csv.Error) as error:
        raise ReplayBundleError("invalid random_seeds.csv") from error
    if not seeds or len(seeds) != len(set(seeds)):
        raise ReplayBundleError("random_seeds.csv must contain unique seeds")
    return seeds


def _readMetricRows(value: bytes) -> dict[tuple[int, str], dict[str, str]]:
    try:
        rows = list(csv.DictReader(io.StringIO(value.decode("utf-8"))))
    except (UnicodeDecodeError, csv.Error) as error:
        raise ReplayBundleError("invalid run_level_metrics.csv") from error
    result: dict[tuple[int, str], dict[str, str]] = {}
    for row in rows:
        seed = _integer(row.get("seed"), "run_level_metrics.seed")
        for role in ("baseline", "intervention"):
            key = (seed, role)
            if key in result:
                raise ReplayBundleError(f"duplicate run metrics row: {key}")
            result[key] = row
    return result


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReplayBundleError(f"{name} must be an object")
    return value


def _listOfMappings(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ReplayBundleError(f"{name} must be an array of objects")
    return value


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ReplayBundleError(f"{name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ReplayBundleError(f"{name} must be an integer") from error
    return parsed


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ReplayBundleError(f"{name} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ReplayBundleError(f"{name} must be numeric") from error
    if not math.isfinite(parsed):
        raise ReplayBundleError(f"{name} must be finite")
    return parsed


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReplayBundleError(f"{name} must be a non-empty string")
    return value


def _hashJson(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
