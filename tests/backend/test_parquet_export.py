from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pytest

from backend.app.export import buildParquetArtifacts
from backend.app.export.parquet import ARTIFACT_SCHEMAS, PARQUET_SCHEMA_VERSION


@pytest.fixture
def representativeResult() -> dict[str, Any]:
    metricNames = {
        "maxDrawdownPct": 4.2,
        "realizedVolatilityPct": 8.5,
        "returnPct": -1.2,
        "valueAtRisk95Pct": -0.8,
        "expectedShortfall95Pct": -1.1,
        "drawdownDurationSteps": 7,
        "averageSpreadBps": 5.5,
        "maxSpreadBps": 12.0,
        "minDepth": 40,
        "amihudIlliquidity": 0.003,
        "kyleLambda": 0.07,
        "recoverySteps": 6,
        "totalVolume": 600,
        "buyVolume": 280,
        "sellVolume": 320,
        "orderImbalance": -0.066667,
        "cascadeScore": 22.5,
    }

    def pairedRun(seed: int, multiplier: float) -> dict[str, Any]:
        baseline = {
            key: value * multiplier if isinstance(value, float) else value
            for key, value in metricNames.items()
        }
        intervention = {
            key: value * multiplier * 1.1 if isinstance(value, float) else value + 1
            for key, value in metricNames.items()
        }
        delta = {key: intervention[key] - baseline[key] for key in metricNames}
        return {
            "seed": seed,
            "baseline": baseline,
            "intervention": intervention,
            "delta": delta,
            "baselineEventLogHash": f"baseline-{seed}",
            "interventionEventLogHash": f"intervention-{seed}",
        }

    return {
        "experimentId": "exp-parquet-001",
        "scenarioDiff": {
            "parameter": "marketMakerCapacity",
            "baselineValue": 1.0,
            "interventionValue": 0.65,
        },
        "pairedRuns": [pairedRun(101, 1.0), pairedRun(202, 1.2)],
        "medianPaths": {
            "step": [0, 1],
            "baseline": {
                "price": [135.0, 134.8],
                "fundamentalPrice": [135.0, 134.9],
                "spreadBps": [4.4, 5.2],
                "depth": [120, 100],
                "volume": [10, 20],
                "sentiment": [0.02, -0.08],
            },
            "intervention": {
                "price": [135.0, 134.5],
                "fundamentalPrice": [135.0, 134.9],
                "spreadBps": [6.2, 8.1],
                "depth": [80, 55],
                "volume": [12, 30],
                "sentiment": [0.02, -0.08],
            },
            "delta": {
                "price": [0.0, -0.3],
                "fundamentalPrice": [0.0, 0.0],
                "spreadBps": [1.8, 2.9],
                "depth": [-40, -45],
                "volume": [2, 10],
                "sentiment": [0.0, 0.0],
            },
        },
        "traces": [
            {
                "scenario": "baseline",
                "seed": 101,
                "traceId": "trace-order-1",
                "parentTraceId": "trace-risk-1",
                "step": 3,
                "eventType": "ORDER_SUBMITTED",
                "agentId": "agent-001",
                "important": False,
                "summary": "Order submitted.",
                "summaryZh": "订单已提交。",
                "payload": {
                    "orderId": "order-001",
                    "agentType": "MOMENTUM",
                    "side": "SELL",
                    "quantity": 12,
                    "orderType": "LIMIT",
                    "timeInForce": "GTC",
                    "limitPriceTicks": 13_490,
                    "referencePriceTicks": 13_500,
                    "reasonCode": "risk-off",
                    "riskStatus": "APPROVED",
                },
            },
            {
                "scenario": "intervention",
                "seed": 101,
                "traceId": "trace-system-order-1",
                "parentTraceId": None,
                "step": 4,
                "eventType": "SYSTEM_ORDER_SUBMITTED",
                "agentId": "synthetic-event-flow",
                "important": True,
                "summary": "Declared scenario flow submitted.",
                "summaryZh": "已声明场景资金流已提交。",
                "payload": {"side": "SELL", "quantity": 20, "reasonCode": "declared-flow"},
            },
            {
                "scenario": "baseline",
                "seed": 101,
                "traceId": "trace-trade-1",
                "parentTraceId": "trace-order-1",
                "step": 3,
                "eventType": "TRADE_EXECUTED",
                "agentId": "agent-001",
                "important": False,
                "summary": "Trade executed.",
                "summaryZh": "交易已成交。",
                "payload": {
                    "tradeId": "trade-001",
                    "makerOrderId": "maker-order-001",
                    "takerOrderId": "order-001",
                    "buyerAgentId": "maker-001",
                    "sellerAgentId": "agent-001",
                    "makerAgentId": "maker-001",
                    "takerAgentId": "agent-001",
                    "aggressiveSide": "SELL",
                    "priceTicks": 13_490,
                    "quantity": 12,
                },
            },
            {
                "scenario": "baseline",
                "seed": 101,
                "traceId": "trace-fact-1",
                "parentTraceId": None,
                "step": 1,
                "eventType": "FACT_ARRIVED",
                "agentId": None,
                "important": True,
                "summary": "Official fact arrived.",
                "summaryZh": "官方事实到达。",
                "payload": {"claimId": "claim-001"},
            },
        ],
        "cognition": {
            "decisions": [
                {
                    "decisionId": "decision-001",
                    "observationId": "observation-001",
                    "agentId": "llm-agent-001",
                    "role": "event_risk_analyst",
                    "direction": "NEGATIVE",
                    "actionPreference": "REDUCE",
                    "targetPositionFraction": -0.25,
                    "urgency": 0.7,
                    "uncertainty": 0.35,
                    "tailRisk": 0.72,
                    "confidence": 0.8,
                    "decisionSummary": "Approved evidence implies bounded downside risk.",
                    "evidenceIds": ["claim-001"],
                    "model": "glm-5.2",
                    "requestId": "request-001",
                    "cacheHit": False,
                    "fallbackUsed": False,
                    "repairUsed": False,
                    "latencyMs": 125.5,
                    "totalTokens": 321,
                }
            ]
        },
    }


def _writeArtifacts(directory: Path, artifacts: dict[str, bytes]) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for name, content in artifacts.items():
        path = directory / name
        path.write_bytes(content)
        paths[name] = path
    return paths


def _describe(connection: duckdb.DuckDBPyConnection, path: Path) -> list[tuple[str, str]]:
    rows = connection.execute(
        "DESCRIBE SELECT * FROM read_parquet(?)",
        [str(path)],
    ).fetchall()
    return [(str(row[0]), str(row[1])) for row in rows]


def test_artifacts_have_fixed_schemas_and_expected_rows(
    representativeResult: dict[str, Any], tmp_path: Path
) -> None:
    artifacts = buildParquetArtifacts(representativeResult)
    paths = _writeArtifacts(tmp_path, artifacts)

    assert tuple(artifacts) == tuple(name for name, _schema in ARTIFACT_SCHEMAS)
    assert all(
        content.startswith(b"PAR1") and content.endswith(b"PAR1") for content in artifacts.values()
    )

    expectedCounts = {
        "run_level_metrics.parquet": 6,
        "market_snapshots.parquet": 6,
        "trace_index.parquet": 4,
        "orders.parquet": 2,
        "trades.parquet": 1,
        "agent_decisions.parquet": 1,
    }
    connection = duckdb.connect(":memory:")
    try:
        for name, schema in ARTIFACT_SCHEMAS:
            assert _describe(connection, paths[name]) == list(schema)
            rowCount = connection.execute(
                "SELECT count(*) FROM read_parquet(?)", [str(paths[name])]
            ).fetchone()[0]
            assert rowCount == expectedCounts[name]
    finally:
        connection.close()


def test_typed_trace_projection_and_core_columns_are_queryable(
    representativeResult: dict[str, Any], tmp_path: Path
) -> None:
    paths = _writeArtifacts(tmp_path, buildParquetArtifacts(representativeResult))
    connection = duckdb.connect(":memory:")
    try:
        orderRows = connection.execute(
            """
            SELECT event_type, order_id, side, quantity, limit_price_ticks
            FROM read_parquet(?)
            ORDER BY event_type
            """,
            [str(paths["orders.parquet"])],
        ).fetchall()
        assert orderRows == [
            ("ORDER_SUBMITTED", "order-001", "SELL", 12, 13_490),
            ("SYSTEM_ORDER_SUBMITTED", None, "SELL", 20, None),
        ]

        tradeRow = connection.execute(
            """
            SELECT trade_id, aggressive_side, price_ticks, quantity, notional_ticks
            FROM read_parquet(?)
            """,
            [str(paths["trades.parquet"])],
        ).fetchone()
        assert tradeRow == ("trade-001", "SELL", 13_490, 12, 161_880)

        decisionRow = connection.execute(
            """
            SELECT agent_id, action_preference, evidence_ids_json, model, total_tokens
            FROM read_parquet(?)
            """,
            [str(paths["agent_decisions.parquet"])],
        ).fetchone()
        assert decisionRow == (
            "llm-agent-001",
            "REDUCE",
            '["claim-001"]',
            "glm-5.2",
            321,
        )
    finally:
        connection.close()


def test_same_input_produces_byte_identical_parquet(
    representativeResult: dict[str, Any],
) -> None:
    first = buildParquetArtifacts(representativeResult)
    second = buildParquetArtifacts(representativeResult)

    assert first == second


def test_empty_collections_still_produce_readable_typed_parquet(tmp_path: Path) -> None:
    artifacts = buildParquetArtifacts(
        {
            "experimentId": "exp-empty-001",
            "pairedRuns": [],
            "medianPaths": {},
            "traces": [],
            "cognition": {"decisions": []},
        }
    )
    paths = _writeArtifacts(tmp_path, artifacts)

    connection = duckdb.connect(":memory:")
    try:
        for name, schema in ARTIFACT_SCHEMAS:
            assert _describe(connection, paths[name]) == list(schema)
            assert (
                connection.execute(
                    "SELECT count(*) FROM read_parquet(?)", [str(paths[name])]
                ).fetchone()[0]
                == 0
            )
            schemaVersion = connection.execute(
                """
                SELECT column_name
                FROM (DESCRIBE SELECT * FROM read_parquet(?))
                WHERE column_name = ?
                """,
                [str(paths[name]), "schema_version"],
            ).fetchone()
            assert schemaVersion == ("schema_version",)
    finally:
        connection.close()


def test_schema_version_is_embedded_in_every_nonempty_table(
    representativeResult: dict[str, Any], tmp_path: Path
) -> None:
    paths = _writeArtifacts(tmp_path, buildParquetArtifacts(representativeResult))
    connection = duckdb.connect(":memory:")
    try:
        for name, _schema in ARTIFACT_SCHEMAS:
            versions = connection.execute(
                "SELECT DISTINCT schema_version FROM read_parquet(?)",
                [str(paths[name])],
            ).fetchall()
            assert versions == [(PARQUET_SCHEMA_VERSION,)]
    finally:
        connection.close()
