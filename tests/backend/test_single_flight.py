from __future__ import annotations

import asyncio

import pytest

from backend.app.errors import ApiError
from backend.app.single_flight import (
    ResultInterpretationSingleFlight,
    SingleFlightRequestConflictError,
    canonicalRequestHash,
)


def test_canonical_request_hash_is_independent_of_mapping_order() -> None:
    assert canonicalRequestHash({"b": 2, "a": {"value": "中文"}}) == canonicalRequestHash(
        {"a": {"value": "中文"}, "b": 2}
    )


def test_single_flight_merges_duplicates_and_rejects_active_id_conflict() -> None:
    async def exercise() -> None:
        singleFlight = ResultInterpretationSingleFlight()
        started = asyncio.Event()
        release = asyncio.Event()
        callCount = 0

        async def operation() -> dict[str, str]:
            nonlocal callCount
            callCount += 1
            started.set()
            await release.wait()
            return {"messageId": "shared-response"}

        first = asyncio.create_task(
            singleFlight.execute(
                principalKey="session-a",
                clientRequestId="request-001",
                requestHash="hash-a",
                operation=operation,
            )
        )
        await started.wait()
        duplicate = asyncio.create_task(
            singleFlight.execute(
                principalKey="session-a",
                clientRequestId="request-001",
                requestHash="hash-a",
                operation=operation,
            )
        )
        with pytest.raises(SingleFlightRequestConflictError):
            await singleFlight.execute(
                principalKey="session-a",
                clientRequestId="request-001",
                requestHash="hash-b",
                operation=operation,
            )

        release.set()
        firstResult, duplicateResult = await asyncio.gather(first, duplicate)
        assert firstResult == duplicateResult == {"messageId": "shared-response"}
        assert callCount == 1
        for _ in range(3):
            await asyncio.sleep(0)
        assert singleFlight.activeCount == 0
        assert singleFlight.completedCount == 1
        assert await singleFlight.execute(
            principalKey="session-a",
            clientRequestId="request-001",
            requestHash="hash-a",
            operation=operation,
        ) == {"messageId": "shared-response"}
        assert callCount == 1
        with pytest.raises(SingleFlightRequestConflictError):
            await singleFlight.execute(
                principalKey="session-a",
                clientRequestId="request-001",
                requestHash="hash-b",
                operation=operation,
            )

    asyncio.run(exercise())


def test_completed_idempotency_response_expires() -> None:
    async def exercise() -> None:
        now = [1_000.0]
        singleFlight = ResultInterpretationSingleFlight(
            completedTtlSeconds=30,
            clock=lambda: now[0],
        )
        callCount = 0

        async def operation() -> int:
            nonlocal callCount
            callCount += 1
            return callCount

        arguments = {
            "principalKey": "session-a",
            "clientRequestId": "request-expiring",
            "requestHash": "hash-a",
            "operation": operation,
        }
        assert await singleFlight.execute(**arguments) == 1
        assert await singleFlight.execute(**arguments) == 1
        assert callCount == 1

        now[0] += 31
        assert await singleFlight.purgeExpired() == 1
        assert singleFlight.completedCount == 0
        assert await singleFlight.execute(**arguments) == 2
        assert callCount == 2

    asyncio.run(exercise())


def test_completed_failure_is_replayed_without_reexecuting_operation() -> None:
    async def exercise() -> None:
        singleFlight = ResultInterpretationSingleFlight()
        callCount = 0
        providerError = RuntimeError("provider timeout after uncertain billing")

        async def operation() -> None:
            nonlocal callCount
            callCount += 1
            raise providerError

        arguments = {
            "principalKey": "session-a",
            "clientRequestId": "request-failed",
            "requestHash": "hash-a",
            "operation": operation,
        }
        with pytest.raises(RuntimeError) as firstError:
            await singleFlight.execute(**arguments)
        with pytest.raises(RuntimeError) as replayedError:
            await singleFlight.execute(**arguments)

        assert firstError.value is providerError
        assert replayedError.value is not providerError
        assert type(replayedError.value) is type(providerError)
        assert replayedError.value.args == providerError.args
        assert callCount == 1
        assert singleFlight.activeCount == 0
        assert singleFlight.completedCount == 1

    asyncio.run(exercise())


def test_completed_failure_new_id_reexecutes_and_payload_conflict_is_rejected() -> None:
    async def exercise() -> None:
        singleFlight = ResultInterpretationSingleFlight()
        callCount = 0

        async def operation() -> None:
            nonlocal callCount
            callCount += 1
            raise RuntimeError(f"provider failure {callCount}")

        with pytest.raises(RuntimeError, match="provider failure 1"):
            await singleFlight.execute(
                principalKey="session-a",
                clientRequestId="request-failed",
                requestHash="hash-a",
                operation=operation,
            )
        with pytest.raises(SingleFlightRequestConflictError):
            await singleFlight.execute(
                principalKey="session-a",
                clientRequestId="request-failed",
                requestHash="hash-b",
                operation=operation,
            )
        with pytest.raises(RuntimeError, match="provider failure 2"):
            await singleFlight.execute(
                principalKey="session-a",
                clientRequestId="request-new",
                requestHash="hash-a",
                operation=operation,
            )

        assert callCount == 2

    asyncio.run(exercise())


def test_completed_api_error_replay_preserves_public_contract() -> None:
    async def exercise() -> None:
        singleFlight = ResultInterpretationSingleFlight()
        callCount = 0

        async def operation() -> None:
            nonlocal callCount
            callCount += 1
            raise ApiError(
                "MODEL_TIMEOUT",
                504,
                "The model provider did not finish within the bounded time.",
                details={
                    "retryable": True,
                    "uncertainBillableAttempts": 1,
                },
            )

        arguments = {
            "principalKey": "session-a",
            "clientRequestId": "request-api-error",
            "requestHash": "hash-a",
            "operation": operation,
        }
        with pytest.raises(ApiError) as firstError:
            await singleFlight.execute(**arguments)
        with pytest.raises(ApiError) as replayedError:
            await singleFlight.execute(**arguments)

        assert replayedError.value is not firstError.value
        assert replayedError.value.code == "MODEL_TIMEOUT"
        assert replayedError.value.statusCode == 504
        assert replayedError.value.message == firstError.value.message
        assert replayedError.value.details == {
            "retryable": True,
            "uncertainBillableAttempts": 1,
        }
        assert callCount == 1

    asyncio.run(exercise())


def test_completed_failure_can_retry_after_ttl() -> None:
    async def exercise() -> None:
        now = [1_000.0]
        singleFlight = ResultInterpretationSingleFlight(
            completedTtlSeconds=30,
            clock=lambda: now[0],
        )
        callCount = 0

        async def operation() -> None:
            nonlocal callCount
            callCount += 1
            raise RuntimeError(f"provider failure {callCount}")

        arguments = {
            "principalKey": "session-a",
            "clientRequestId": "request-expiring-failure",
            "requestHash": "hash-a",
            "operation": operation,
        }
        with pytest.raises(RuntimeError, match="provider failure 1"):
            await singleFlight.execute(**arguments)
        with pytest.raises(RuntimeError, match="provider failure 1"):
            await singleFlight.execute(**arguments)
        assert callCount == 1

        now[0] += 31
        assert await singleFlight.purgeExpired() == 1
        with pytest.raises(RuntimeError, match="provider failure 2"):
            await singleFlight.execute(**arguments)
        assert callCount == 2

    asyncio.run(exercise())


def test_single_flight_shields_provider_task_from_cancelled_waiter() -> None:
    async def exercise() -> None:
        singleFlight = ResultInterpretationSingleFlight()
        started = asyncio.Event()
        release = asyncio.Event()
        callCount = 0

        async def operation() -> str:
            nonlocal callCount
            callCount += 1
            started.set()
            await release.wait()
            return "finished"

        abandonedWaiter = asyncio.create_task(
            singleFlight.execute(
                principalKey="session-a",
                clientRequestId="request-001",
                requestHash="hash-a",
                operation=operation,
            )
        )
        await started.wait()
        abandonedWaiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await abandonedWaiter

        retry = asyncio.create_task(
            singleFlight.execute(
                principalKey="session-a",
                clientRequestId="request-001",
                requestHash="hash-a",
                operation=operation,
            )
        )
        release.set()
        assert await retry == "finished"
        assert callCount == 1

    asyncio.run(exercise())
