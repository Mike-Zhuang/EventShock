from __future__ import annotations

import pytest

from backend.app.observability import RuntimeMetrics


def test_runtime_metrics_records_privacy_safe_sse_terminal_outcomes() -> None:
    metrics = RuntimeMetrics(maximumSamples=100)

    metrics.recordSseTerminal(durationMs=10.0, outcome="success")
    metrics.recordSseTerminal(durationMs=20.0, outcome="error")
    metrics.recordSseTerminal(durationMs=30.0, outcome="cancelled")

    snapshot = metrics.snapshot()
    sse = snapshot["resultInterpretationSse"]
    assert sse == {
        "terminalCount": 3,
        "successCount": 1,
        "errorCount": 1,
        "cancelledCount": 1,
        "latencyWindowSize": 3,
        "latencyMs": {
            "p50": 20.0,
            "p95": 29.0,
            "maximum": 30.0,
            "mean": 20.0,
        },
    }
    assert snapshot["privacyBoundary"] == "NO_PATH_BODY_SESSION_OR_CREDENTIAL_LABELS"
    assert "path" not in sse
    assert "session" not in sse


def test_runtime_metrics_rejects_unknown_sse_terminal_outcome() -> None:
    metrics = RuntimeMetrics(maximumSamples=100)

    with pytest.raises(ValueError, match="outcome must be"):
        metrics.recordSseTerminal(durationMs=1.0, outcome="unknown")
