"""低内存单进程部署使用的有界运行指标。"""

from __future__ import annotations

import statistics
import threading
import time
from collections import deque
from typing import Any, Literal

SseTerminalOutcome = Literal["success", "error", "cancelled"]


class RuntimeMetrics:
    """只保存最近延迟样本和聚合计数，不记录 URL、正文或会话标识。"""

    def __init__(self, *, maximumSamples: int = 1_000) -> None:
        if maximumSamples < 100:
            raise ValueError("maximumSamples must be at least 100")
        self._startedAt = time.monotonic()
        self._latenciesMs: deque[float] = deque(maxlen=maximumSamples)
        self._requestCount = 0
        self._clientErrorCount = 0
        self._serverErrorCount = 0
        self._sseTerminalLatenciesMs: deque[float] = deque(maxlen=maximumSamples)
        self._sseTerminalSuccessCount = 0
        self._sseTerminalErrorCount = 0
        self._sseTerminalCancelledCount = 0
        self._lock = threading.RLock()

    def record(self, *, durationMs: float, statusCode: int) -> None:
        with self._lock:
            self._requestCount += 1
            self._latenciesMs.append(max(0.0, float(durationMs)))
            self._clientErrorCount += int(400 <= statusCode < 500)
            self._serverErrorCount += int(statusCode >= 500)

    def recordSseTerminal(
        self,
        *,
        durationMs: float,
        outcome: SseTerminalOutcome,
    ) -> None:
        """记录 SSE 应用层终态，不接收路径、正文、身份或供应商字段。"""

        if outcome not in {"success", "error", "cancelled"}:
            raise ValueError("outcome must be success, error, or cancelled")
        with self._lock:
            self._sseTerminalLatenciesMs.append(max(0.0, float(durationMs)))
            self._sseTerminalSuccessCount += int(outcome == "success")
            self._sseTerminalErrorCount += int(outcome == "error")
            self._sseTerminalCancelledCount += int(outcome == "cancelled")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            values = sorted(self._latenciesMs)
            requestCount = self._requestCount
            clientErrors = self._clientErrorCount
            serverErrors = self._serverErrorCount
            sseValues = sorted(self._sseTerminalLatenciesMs)
            sseSuccesses = self._sseTerminalSuccessCount
            sseErrors = self._sseTerminalErrorCount
            sseCancellations = self._sseTerminalCancelledCount
        return {
            "uptimeSeconds": round(max(0.0, time.monotonic() - self._startedAt), 3),
            "requestCount": requestCount,
            "clientErrorCount": clientErrors,
            "serverErrorCount": serverErrors,
            "serverErrorRate": round(serverErrors / requestCount, 6) if requestCount else 0.0,
            "latencyWindowSize": len(values),
            "latencyMs": _latencySummary(values),
            "resultInterpretationSse": {
                "terminalCount": sseSuccesses + sseErrors + sseCancellations,
                "successCount": sseSuccesses,
                "errorCount": sseErrors,
                "cancelledCount": sseCancellations,
                "latencyWindowSize": len(sseValues),
                "latencyMs": _latencySummary(sseValues),
            },
            "privacyBoundary": "NO_PATH_BODY_SESSION_OR_CREDENTIAL_LABELS",
        }


def _latencySummary(values: list[float]) -> dict[str, float]:
    return {
        "p50": _quantile(values, 0.5),
        "p95": _quantile(values, 0.95),
        "maximum": round(max(values), 3) if values else 0.0,
        "mean": round(statistics.fmean(values), 3) if values else 0.0,
    }


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    position = (len(values) - 1) * probability
    lowerIndex = int(position)
    upperIndex = min(lowerIndex + 1, len(values) - 1)
    fraction = position - lowerIndex
    return round(values[lowerIndex] * (1 - fraction) + values[upperIndex] * fraction, 3)
