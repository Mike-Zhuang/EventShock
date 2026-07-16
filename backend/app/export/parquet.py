"""把实验结果编码为固定数据契约的确定性 Parquet 产物。"""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import duckdb

PARQUET_SCHEMA_VERSION = "eventshock_parquet_v1.0.0"

ORDER_EVENT_TYPES = frozenset(
    {
        "ORDER_SUBMITTED",
        "SYSTEM_ORDER_SUBMITTED",
    }
)
TRADE_EVENT_TYPES = frozenset({"TRADE_EXECUTED"})

TableSchema = tuple[tuple[str, str], ...]

RUN_LEVEL_SCHEMA: TableSchema = (
    ("schema_version", "VARCHAR"),
    ("experiment_id", "VARCHAR"),
    ("seed", "BIGINT"),
    ("scenario_role", "VARCHAR"),
    ("intervention_parameter", "VARCHAR"),
    ("scenario_value", "DOUBLE"),
    ("event_log_hash", "VARCHAR"),
    ("max_drawdown_pct", "DOUBLE"),
    ("realized_volatility_pct", "DOUBLE"),
    ("return_pct", "DOUBLE"),
    ("value_at_risk_95_pct", "DOUBLE"),
    ("expected_shortfall_95_pct", "DOUBLE"),
    ("drawdown_duration_steps", "BIGINT"),
    ("average_spread_bps", "DOUBLE"),
    ("max_spread_bps", "DOUBLE"),
    ("minimum_depth", "BIGINT"),
    ("amihud_illiquidity", "DOUBLE"),
    ("kyle_lambda", "DOUBLE"),
    ("recovery_steps", "BIGINT"),
    ("total_volume", "BIGINT"),
    ("buy_volume", "BIGINT"),
    ("sell_volume", "BIGINT"),
    ("order_imbalance", "DOUBLE"),
    ("cascade_score", "DOUBLE"),
    ("metrics_json", "VARCHAR"),
)

MARKET_SNAPSHOT_SCHEMA: TableSchema = (
    ("schema_version", "VARCHAR"),
    ("experiment_id", "VARCHAR"),
    ("scenario_role", "VARCHAR"),
    ("statistic", "VARCHAR"),
    ("step", "INTEGER"),
    ("price", "DOUBLE"),
    ("fundamental_price", "DOUBLE"),
    ("spread_bps", "DOUBLE"),
    ("depth", "BIGINT"),
    ("volume", "BIGINT"),
    ("sentiment", "DOUBLE"),
)

TRACE_INDEX_SCHEMA: TableSchema = (
    ("schema_version", "VARCHAR"),
    ("experiment_id", "VARCHAR"),
    ("scenario_role", "VARCHAR"),
    ("seed", "BIGINT"),
    ("trace_id", "VARCHAR"),
    ("parent_trace_id", "VARCHAR"),
    ("step", "INTEGER"),
    ("event_type", "VARCHAR"),
    ("agent_id", "VARCHAR"),
    ("important", "BOOLEAN"),
    ("summary", "VARCHAR"),
    ("summary_zh", "VARCHAR"),
    ("payload_sha256", "VARCHAR"),
    ("payload_json", "VARCHAR"),
)

ORDER_SCHEMA: TableSchema = (
    ("schema_version", "VARCHAR"),
    ("experiment_id", "VARCHAR"),
    ("scenario_role", "VARCHAR"),
    ("seed", "BIGINT"),
    ("trace_id", "VARCHAR"),
    ("parent_trace_id", "VARCHAR"),
    ("step", "INTEGER"),
    ("event_type", "VARCHAR"),
    ("order_id", "VARCHAR"),
    ("agent_id", "VARCHAR"),
    ("agent_type", "VARCHAR"),
    ("side", "VARCHAR"),
    ("quantity", "BIGINT"),
    ("order_type", "VARCHAR"),
    ("time_in_force", "VARCHAR"),
    ("limit_price_ticks", "BIGINT"),
    ("reference_price_ticks", "BIGINT"),
    ("reason_code", "VARCHAR"),
    ("risk_status", "VARCHAR"),
    ("payload_json", "VARCHAR"),
)

TRADE_SCHEMA: TableSchema = (
    ("schema_version", "VARCHAR"),
    ("experiment_id", "VARCHAR"),
    ("scenario_role", "VARCHAR"),
    ("seed", "BIGINT"),
    ("trace_id", "VARCHAR"),
    ("parent_trace_id", "VARCHAR"),
    ("step", "INTEGER"),
    ("trade_id", "VARCHAR"),
    ("maker_order_id", "VARCHAR"),
    ("taker_order_id", "VARCHAR"),
    ("buyer_agent_id", "VARCHAR"),
    ("seller_agent_id", "VARCHAR"),
    ("maker_agent_id", "VARCHAR"),
    ("taker_agent_id", "VARCHAR"),
    ("aggressive_side", "VARCHAR"),
    ("price_ticks", "BIGINT"),
    ("quantity", "BIGINT"),
    ("notional_ticks", "BIGINT"),
    ("payload_json", "VARCHAR"),
)

AGENT_DECISION_SCHEMA: TableSchema = (
    ("schema_version", "VARCHAR"),
    ("experiment_id", "VARCHAR"),
    ("decision_id", "VARCHAR"),
    ("observation_id", "VARCHAR"),
    ("agent_id", "VARCHAR"),
    ("representative_index", "INTEGER"),
    ("decision_round", "INTEGER"),
    ("observation_at", "TIMESTAMP WITH TIME ZONE"),
    ("active_from_step", "INTEGER"),
    ("decision_interval_steps", "INTEGER"),
    ("evidence_count", "INTEGER"),
    ("social_post_count", "INTEGER"),
    ("memory_count", "INTEGER"),
    ("role", "VARCHAR"),
    ("direction", "VARCHAR"),
    ("action_preference", "VARCHAR"),
    ("target_position_fraction", "DOUBLE"),
    ("urgency", "DOUBLE"),
    ("uncertainty", "DOUBLE"),
    ("tail_risk", "DOUBLE"),
    ("confidence", "DOUBLE"),
    ("decision_summary", "VARCHAR"),
    ("evidence_ids_json", "VARCHAR"),
    ("model", "VARCHAR"),
    ("request_id", "VARCHAR"),
    ("cache_hit", "BOOLEAN"),
    ("fallback_used", "BOOLEAN"),
    ("repair_used", "BOOLEAN"),
    ("latency_ms", "DOUBLE"),
    ("total_tokens", "BIGINT"),
    ("payload_json", "VARCHAR"),
)

ARTIFACT_SCHEMAS: tuple[tuple[str, TableSchema], ...] = (
    ("run_level_metrics.parquet", RUN_LEVEL_SCHEMA),
    ("market_snapshots.parquet", MARKET_SNAPSHOT_SCHEMA),
    ("trace_index.parquet", TRACE_INDEX_SCHEMA),
    ("orders.parquet", ORDER_SCHEMA),
    ("trades.parquet", TRADE_SCHEMA),
    ("agent_decisions.parquet", AGENT_DECISION_SCHEMA),
)


def buildParquetArtifacts(result: Mapping[str, Any]) -> dict[str, bytes]:
    """生成六个具有固定 schema 的 Parquet 文件。

    输入应是实验结果对象，而不是数据库连接或运行时服务。函数不修改输入；
    DuckDB 连接和临时目录都只在本次调用中存活。
    """

    if not isinstance(result, Mapping):
        raise TypeError("result must be a mapping")

    tableRows: dict[str, list[tuple[Any, ...]]] = {
        "run_level_metrics.parquet": _buildRunLevelRows(result),
        "market_snapshots.parquet": _buildMarketSnapshotRows(result),
        "trace_index.parquet": _buildTraceRows(result),
        "orders.parquet": _buildOrderRows(result),
        "trades.parquet": _buildTradeRows(result),
        "agent_decisions.parquet": _buildAgentDecisionRows(result),
    }
    artifacts: dict[str, bytes] = {}
    with tempfile.TemporaryDirectory(prefix="eventshock-parquet-") as temporaryDirectory:
        connection = duckdb.connect(":memory:")
        try:
            connection.execute("SET preserve_insertion_order = true")
            for index, (artifactName, schema) in enumerate(ARTIFACT_SCHEMAS):
                tableName = f"artifact_{index}"
                _createTable(connection, tableName, schema)
                _insertRows(connection, tableName, schema, tableRows[artifactName])
                outputPath = Path(temporaryDirectory) / artifactName
                connection.execute(
                    f"COPY {tableName} TO ? "
                    "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880)",
                    [str(outputPath)],
                )
                artifacts[artifactName] = outputPath.read_bytes()
        finally:
            connection.close()
    return artifacts


def _buildRunLevelRows(result: Mapping[str, Any]) -> list[tuple[Any, ...]]:
    experimentId = _text(result.get("experimentId"))
    scenarioDiff = _mapping(result.get("scenarioDiff"))
    parameter = _text(scenarioDiff.get("parameter"))
    scenarioValues = {
        "baseline": _number(scenarioDiff.get("baselineValue")),
        "intervention": _number(scenarioDiff.get("interventionValue")),
        "delta": _numericDifference(
            scenarioDiff.get("interventionValue"), scenarioDiff.get("baselineValue")
        ),
    }
    rows: list[tuple[Any, ...]] = []
    for pairedRun in _mappingItems(result.get("pairedRuns")):
        seed = _integer(pairedRun.get("seed"))
        eventHashes = {
            "baseline": _text(pairedRun.get("baselineEventLogHash")),
            "intervention": _text(pairedRun.get("interventionEventLogHash")),
            "delta": None,
        }
        for scenarioRole in ("baseline", "intervention", "delta"):
            metrics = _mapping(pairedRun.get(scenarioRole))
            rows.append(
                (
                    PARQUET_SCHEMA_VERSION,
                    experimentId,
                    seed,
                    scenarioRole,
                    parameter,
                    scenarioValues[scenarioRole],
                    eventHashes[scenarioRole],
                    _metricNumber(metrics, "maxDrawdownPct"),
                    _metricNumber(metrics, "realizedVolatilityPct"),
                    _metricNumber(metrics, "returnPct", "totalReturnPct"),
                    _metricNumber(metrics, "valueAtRisk95Pct", "var95Pct"),
                    _metricNumber(metrics, "expectedShortfall95Pct", "expectedShortfallPct"),
                    _metricInteger(metrics, "drawdownDurationSteps", "maxDrawdownDurationSteps"),
                    _metricNumber(metrics, "averageSpreadBps", "avgSpreadBps"),
                    _metricNumber(metrics, "maxSpreadBps"),
                    _metricInteger(metrics, "minDepth", "minimumDepth"),
                    _metricNumber(metrics, "amihudIlliquidity", "amihud"),
                    _metricNumber(metrics, "kyleLambda"),
                    _metricInteger(metrics, "recoverySteps"),
                    _metricInteger(metrics, "totalVolume"),
                    _metricInteger(metrics, "buyVolume", "totalBuyVolume"),
                    _metricInteger(metrics, "sellVolume", "totalSellVolume"),
                    _metricNumber(metrics, "orderImbalance"),
                    _metricNumber(metrics, "cascadeScore"),
                    _canonicalJson(metrics),
                )
            )
    return rows


def _buildMarketSnapshotRows(result: Mapping[str, Any]) -> list[tuple[Any, ...]]:
    experimentId = _text(result.get("experimentId"))
    paths = _mapping(result.get("medianPaths"))
    steps = _sequence(paths.get("step"))
    rows: list[tuple[Any, ...]] = []
    for scenarioRole in ("baseline", "intervention", "delta"):
        scenarioPaths = _mapping(paths.get(scenarioRole))
        for index, rawStep in enumerate(steps):
            step = _integer(rawStep)
            if step is None:
                step = index
            rows.append(
                (
                    PARQUET_SCHEMA_VERSION,
                    experimentId,
                    scenarioRole,
                    "median" if scenarioRole != "delta" else "paired_median_delta",
                    step,
                    _pathNumber(scenarioPaths, "price", index),
                    _pathNumber(scenarioPaths, "fundamentalPrice", index),
                    _pathNumber(scenarioPaths, "spreadBps", index),
                    _pathInteger(scenarioPaths, "depth", index),
                    _pathInteger(scenarioPaths, "volume", index),
                    _pathNumber(scenarioPaths, "sentiment", index),
                )
            )
    return rows


def _buildTraceRows(result: Mapping[str, Any]) -> list[tuple[Any, ...]]:
    experimentId = _text(result.get("experimentId"))
    traces = sorted(_mappingItems(result.get("traces")), key=_traceSortKey)
    return [_traceRow(experimentId, trace) for trace in traces]


def _buildOrderRows(result: Mapping[str, Any]) -> list[tuple[Any, ...]]:
    experimentId = _text(result.get("experimentId"))
    rows: list[tuple[Any, ...]] = []
    for trace in sorted(_mappingItems(result.get("traces")), key=_traceSortKey):
        eventType = _text(trace.get("eventType"))
        if eventType not in ORDER_EVENT_TYPES:
            continue
        payload = _mapping(trace.get("payload"))
        rows.append(
            (
                PARQUET_SCHEMA_VERSION,
                experimentId,
                _text(trace.get("scenario")),
                _integer(trace.get("seed")),
                _text(trace.get("traceId")),
                _text(trace.get("parentTraceId")),
                _integer(trace.get("step")),
                eventType,
                _text(_first(payload, "orderId", "order_id")),
                _text(trace.get("agentId") or _first(payload, "agentId", "agent_id")),
                _text(_first(payload, "agentType", "agent_type")),
                _text(payload.get("side")),
                _integer(payload.get("quantity")),
                _text(_first(payload, "orderType", "order_type")),
                _text(_first(payload, "timeInForce", "time_in_force")),
                _integer(_first(payload, "limitPriceTicks", "limit_price_ticks", "priceTicks")),
                _integer(_first(payload, "referencePriceTicks", "reference_price_ticks")),
                _text(_first(payload, "reasonCode", "reason_code", "reason")),
                _text(_first(payload, "riskStatus", "risk_status")),
                _canonicalJson(payload),
            )
        )
    return rows


def _buildTradeRows(result: Mapping[str, Any]) -> list[tuple[Any, ...]]:
    experimentId = _text(result.get("experimentId"))
    rows: list[tuple[Any, ...]] = []
    for trace in sorted(_mappingItems(result.get("traces")), key=_traceSortKey):
        eventType = _text(trace.get("eventType"))
        if eventType not in TRADE_EVENT_TYPES:
            continue
        payload = _mapping(trace.get("payload"))
        priceTicks = _integer(_first(payload, "priceTicks", "price_ticks"))
        quantity = _integer(payload.get("quantity"))
        notionalTicks = (
            priceTicks * quantity if priceTicks is not None and quantity is not None else None
        )
        rows.append(
            (
                PARQUET_SCHEMA_VERSION,
                experimentId,
                _text(trace.get("scenario")),
                _integer(trace.get("seed")),
                _text(trace.get("traceId")),
                _text(trace.get("parentTraceId")),
                _integer(trace.get("step")),
                _text(_first(payload, "tradeId", "trade_id")),
                _text(_first(payload, "makerOrderId", "maker_order_id")),
                _text(_first(payload, "takerOrderId", "taker_order_id")),
                _text(_first(payload, "buyerAgentId", "buyer_agent_id")),
                _text(_first(payload, "sellerAgentId", "seller_agent_id")),
                _text(_first(payload, "makerAgentId", "maker_agent_id")),
                _text(_first(payload, "takerAgentId", "taker_agent_id")),
                _text(_first(payload, "aggressiveSide", "aggressive_side")),
                priceTicks,
                quantity,
                notionalTicks,
                _canonicalJson(payload),
            )
        )
    return rows


def _buildAgentDecisionRows(result: Mapping[str, Any]) -> list[tuple[Any, ...]]:
    experimentId = _text(result.get("experimentId"))
    cognition = _mapping(result.get("cognition"))
    decisions = sorted(
        _mappingItems(cognition.get("decisions")),
        key=lambda item: (
            _text(item.get("agentId")) or "",
            _text(item.get("decisionId")) or "",
        ),
    )
    rows: list[tuple[Any, ...]] = []
    for decision in decisions:
        evidenceIds = _sequence(_first(decision, "evidenceIds", "evidence_ids"))
        rows.append(
            (
                PARQUET_SCHEMA_VERSION,
                experimentId,
                _text(_first(decision, "decisionId", "decision_id")),
                _text(_first(decision, "observationId", "observation_id")),
                _text(_first(decision, "agentId", "agent_id")),
                _integer(_first(decision, "representativeIndex", "representative_index")),
                _integer(_first(decision, "decisionRound", "decision_round")),
                _text(_first(decision, "observationAt", "observation_at")),
                _integer(_first(decision, "activeFromStep", "active_from_step")),
                _integer(_first(decision, "decisionIntervalSteps", "decision_interval_steps")),
                _integer(_first(decision, "evidenceCount", "evidence_count")),
                _integer(_first(decision, "socialPostCount", "social_post_count")),
                _integer(_first(decision, "memoryCount", "memory_count")),
                _text(decision.get("role")),
                _text(decision.get("direction")),
                _text(_first(decision, "actionPreference", "action_preference")),
                _number(_first(decision, "targetPositionFraction", "target_position_fraction")),
                _number(decision.get("urgency")),
                _number(decision.get("uncertainty")),
                _number(_first(decision, "tailRisk", "tail_risk", "perceived_tail_risk")),
                _number(decision.get("confidence")),
                _text(_first(decision, "decisionSummary", "decision_summary")),
                _canonicalJson(list(evidenceIds)),
                _text(decision.get("model")),
                _text(_first(decision, "requestId", "request_id")),
                _boolean(_first(decision, "cacheHit", "cache_hit")),
                _boolean(_first(decision, "fallbackUsed", "fallback_used")),
                _boolean(_first(decision, "repairUsed", "repair_used")),
                _number(_first(decision, "latencyMs", "latency_ms")),
                _integer(_first(decision, "totalTokens", "total_tokens")),
                _canonicalJson(decision),
            )
        )
    return rows


def _traceRow(experimentId: str | None, trace: Mapping[str, Any]) -> tuple[Any, ...]:
    payload = _mapping(trace.get("payload"))
    payloadJson = _canonicalJson(payload)
    return (
        PARQUET_SCHEMA_VERSION,
        experimentId,
        _text(trace.get("scenario")),
        _integer(trace.get("seed")),
        _text(trace.get("traceId")),
        _text(trace.get("parentTraceId")),
        _integer(trace.get("step")),
        _text(trace.get("eventType")),
        _text(trace.get("agentId")),
        _boolean(trace.get("important")),
        _text(trace.get("summary")),
        _text(trace.get("summaryZh")),
        hashlib.sha256(payloadJson.encode()).hexdigest(),
        payloadJson,
    )


def _traceSortKey(trace: Mapping[str, Any]) -> tuple[int, int, int, str]:
    scenarioOrder = {"baseline": 0, "intervention": 1}
    scenario = _text(trace.get("scenario"))
    seed = _integer(trace.get("seed"))
    step = _integer(trace.get("step"))
    return (
        scenarioOrder.get(scenario or "", 2),
        seed if seed is not None else -1,
        step if step is not None else -1,
        _text(trace.get("traceId")) or "",
    )


def _createTable(
    connection: duckdb.DuckDBPyConnection,
    tableName: str,
    schema: TableSchema,
) -> None:
    columns = ", ".join(f'"{name}" {dataType}' for name, dataType in schema)
    connection.execute(f"CREATE TABLE {tableName} ({columns})")


def _insertRows(
    connection: duckdb.DuckDBPyConnection,
    tableName: str,
    schema: TableSchema,
    rows: list[tuple[Any, ...]],
) -> None:
    if not rows:
        return
    if any(len(row) != len(schema) for row in rows):
        raise RuntimeError(f"row does not match fixed schema for {tableName}")
    placeholders = ", ".join("?" for _ in schema)
    connection.executemany(f"INSERT INTO {tableName} VALUES ({placeholders})", rows)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mappingItems(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Enum):
        value = value.value
    if isinstance(value, str):
        return value
    if isinstance(value, (bool, int, float)):
        return str(value)
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def _boolean(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _numericDifference(minuend: Any, subtrahend: Any) -> float | None:
    left = _number(minuend)
    right = _number(subtrahend)
    return left - right if left is not None and right is not None else None


def _metricNumber(metrics: Mapping[str, Any], *keys: str) -> float | None:
    return _number(_first(metrics, *keys))


def _metricInteger(metrics: Mapping[str, Any], *keys: str) -> int | None:
    return _integer(_first(metrics, *keys))


def _pathNumber(paths: Mapping[str, Any], key: str, index: int) -> float | None:
    values = _sequence(paths.get(key))
    return _number(values[index]) if index < len(values) else None


def _pathInteger(paths: Mapping[str, Any], key: str, index: int) -> int | None:
    values = _sequence(paths.get(key))
    return _integer(values[index]) if index < len(values) else None


def _canonicalJson(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_jsonDefault,
    )


def _jsonDefault(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, set | frozenset):
        return sorted(value)
    raise TypeError(f"value is not JSON serializable: {type(value).__name__}")
