import pytest

from backend.app.simulation.event_queue import (
    DeterministicEventQueue,
    EventPriority,
    SimulationClock,
)


def test_queue_orders_by_timestamp_priority_and_insertion_sequence() -> None:
    queue = DeterministicEventQueue()
    queue.schedule(
        timestamp=20,
        priority=EventPriority.ORDER_ARRIVAL,
        eventType="late-order",
    )
    firstSameKey = queue.schedule(
        timestamp=10,
        priority=EventPriority.AGENT_ACTIVATION,
        eventType="first-agent",
    )
    queue.schedule(
        timestamp=10,
        priority=EventPriority.INFORMATION_RELEASE,
        eventType="fact",
    )
    secondSameKey = queue.schedule(
        timestamp=10,
        priority=EventPriority.AGENT_ACTIVATION,
        eventType="second-agent",
    )

    assert firstSameKey.sequence < secondSameKey.sequence
    assert [event.eventType for event in queue.drain()] == [
        "fact",
        "first-agent",
        "second-agent",
        "late-order",
    ]
    assert queue.clock.now == 20


def test_cancellation_snapshot_and_payload_are_stable() -> None:
    queue = DeterministicEventQueue()
    mutablePayload = {"quantity": 10}
    retained = queue.schedule(
        timestamp=5,
        priority=EventPriority.MATCHING,
        eventType="retained",
        payload=mutablePayload,
        eventId="retained-id",
    )
    cancelled = queue.schedule(
        timestamp=4,
        priority=EventPriority.MATCHING,
        eventType="cancelled",
        eventId="cancelled-id",
    )
    mutablePayload["quantity"] = 999

    assert queue.cancel(cancelled.eventId) is True
    assert queue.cancel(cancelled.eventId) is False
    assert len(queue) == 1
    assert queue.snapshot() == (retained,)
    assert retained.payload["quantity"] == 10
    with pytest.raises(TypeError):
        retained.payload["quantity"] = 11  # type: ignore[index]
    assert queue.popNext() == retained
    assert not queue


def test_clock_rejects_backward_movement_and_past_scheduling() -> None:
    clock = SimulationClock(now=7)
    queue = DeterministicEventQueue(clock)
    clock.advanceTo(9)

    with pytest.raises(ValueError, match="cannot move backwards"):
        clock.advanceTo(8)
    with pytest.raises(ValueError, match="before the current clock"):
        queue.schedule(timestamp=8, priority=1, eventType="past")
    with pytest.raises(IndexError, match="empty event queue"):
        queue.popNext()


def test_event_ids_are_never_reused_and_time_inputs_are_strict() -> None:
    queue = DeterministicEventQueue()
    event = queue.schedule(
        timestamp=1,
        priority=EventPriority.MARKET_STATE,
        eventType="open",
        eventId="stable-id",
    )
    queue.popNext()
    assert event.eventId == "stable-id"
    with pytest.raises(ValueError, match="already been used"):
        queue.schedule(
            timestamp=2,
            priority=EventPriority.MARKET_STATE,
            eventType="reused",
            eventId="stable-id",
        )
    with pytest.raises(TypeError, match="timestamp must be an integer"):
        queue.schedule(
            timestamp=2.5,  # type: ignore[arg-type]
            priority=EventPriority.MARKET_STATE,
            eventType="fractional-time",
        )


def test_two_queues_with_identical_inputs_produce_identical_snapshots() -> None:
    def build() -> DeterministicEventQueue:
        queue = DeterministicEventQueue()
        queue.scheduleMany(
            (
                (3, EventPriority.NETWORK_DELIVERY, "delivery-a", {"node": "a"}),
                (3, EventPriority.NETWORK_DELIVERY, "delivery-b", {"node": "b"}),
                (1, EventPriority.MARKET_STATE, "open", None),
            )
        )
        return queue

    left = build()
    right = build()
    assert left.snapshot() == right.snapshot()
    assert tuple(left.drain()) == tuple(right.drain())
