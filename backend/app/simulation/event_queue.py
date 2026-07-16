"""确定性离散事件队列与单调仿真时钟。

队列使用 ``(timestamp, priority, sequence)`` 作为唯一排序键。相同时间、相同
优先级的事件严格按进入队列的顺序执行，避免 Python 对 payload 或 event ID 的
比较影响重放结果。
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import IntEnum
from types import MappingProxyType
from typing import Any


class EventPriority(IntEnum):
    """蓝图规定的同时间事件处理优先级，数值越小越先执行。"""

    MARKET_STATE = 10
    INFORMATION_RELEASE = 20
    NETWORK_DELIVERY = 30
    AGENT_ACTIVATION = 40
    ORDER_ARRIVAL = 50
    MATCHING = 60
    ACCOUNT_UPDATE = 70
    METRIC_AND_CHECKPOINT = 80


@dataclass(order=True, frozen=True, slots=True)
class ScheduledEvent:
    """已排程事件；只有前三个字段参与比较。"""

    timestamp: int
    priority: int
    sequence: int
    eventId: str = field(compare=False)
    eventType: str = field(compare=False)
    payload: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({}), compare=False, repr=False
    )

    def __post_init__(self) -> None:
        _requireInteger(self.timestamp, "timestamp")
        _requireInteger(self.priority, "priority")
        _requireInteger(self.sequence, "sequence")
        if self.timestamp < 0:
            raise ValueError("timestamp must be non-negative")
        if self.priority < 0:
            raise ValueError("priority must be non-negative")
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        if not self.eventId:
            raise ValueError("eventId must not be empty")
        if not self.eventType:
            raise ValueError("eventType must not be empty")
        # 防止调用方在排程后修改 dict，破坏重放的确定性。
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(slots=True)
class SimulationClock:
    """只允许向前推进的整数仿真时钟。"""

    now: int = 0

    def __post_init__(self) -> None:
        _requireInteger(self.now, "initial clock value")
        if self.now < 0:
            raise ValueError("initial clock value must be non-negative")

    def advanceTo(self, timestamp: int) -> None:
        _requireInteger(timestamp, "timestamp")
        if timestamp < self.now:
            raise ValueError(
                f"simulation clock cannot move backwards: current={self.now}, target={timestamp}"
            )
        self.now = timestamp


class DeterministicEventQueue:
    """支持取消、窥视和稳定快照的确定性最小堆事件队列。"""

    def __init__(self, clock: SimulationClock | None = None) -> None:
        self.clock = clock or SimulationClock()
        self._heap: list[ScheduledEvent] = []
        self._sequence = 0
        self._activeEventIds: set[str] = set()
        self._cancelledEventIds: set[str] = set()
        self._usedEventIds: set[str] = set()

    def __len__(self) -> int:
        return len(self._activeEventIds)

    def __bool__(self) -> bool:
        return bool(self._activeEventIds)

    def schedule(
        self,
        *,
        timestamp: int,
        priority: int | EventPriority,
        eventType: str,
        payload: Mapping[str, Any] | None = None,
        eventId: str | None = None,
    ) -> ScheduledEvent:
        """排程一个事件并返回包含稳定 sequence 的不可变对象。"""

        _requireInteger(timestamp, "timestamp")
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise TypeError("priority must be an integer")
        if timestamp < self.clock.now:
            raise ValueError(
                f"cannot schedule an event before the current clock: {timestamp} < {self.clock.now}"
            )
        resolvedEventId = eventId or f"event-{self._sequence + 1:012d}"
        if resolvedEventId in self._usedEventIds:
            raise ValueError(f"eventId has already been used: {resolvedEventId}")

        self._sequence += 1
        event = ScheduledEvent(
            timestamp=timestamp,
            priority=int(priority),
            sequence=self._sequence,
            eventId=resolvedEventId,
            eventType=eventType,
            payload=payload or {},
        )
        heapq.heappush(self._heap, event)
        self._activeEventIds.add(event.eventId)
        self._usedEventIds.add(event.eventId)
        return event

    def scheduleMany(
        self,
        events: Iterable[tuple[int, int | EventPriority, str, Mapping[str, Any] | None]],
    ) -> tuple[ScheduledEvent, ...]:
        """按输入迭代顺序批量排程，保证同键事件顺序可预测。"""

        return tuple(
            self.schedule(
                timestamp=timestamp,
                priority=priority,
                eventType=eventType,
                payload=payload,
            )
            for timestamp, priority, eventType, payload in events
        )

    def cancel(self, eventId: str) -> bool:
        """惰性取消尚未弹出的事件；取消同一事件第二次返回 ``False``。"""

        if eventId not in self._activeEventIds:
            return False
        self._activeEventIds.remove(eventId)
        self._cancelledEventIds.add(eventId)
        return True

    def peekNext(self) -> ScheduledEvent | None:
        self._discardCancelledHead()
        return self._heap[0] if self._heap else None

    def popNext(self) -> ScheduledEvent:
        self._discardCancelledHead()
        if not self._heap:
            raise IndexError("pop from an empty event queue")
        event = heapq.heappop(self._heap)
        self._activeEventIds.remove(event.eventId)
        self.clock.advanceTo(event.timestamp)
        return event

    def drain(self) -> Iterator[ScheduledEvent]:
        """按执行顺序取出剩余事件，并同步推进时钟。"""

        while self:
            yield self.popNext()

    def snapshot(self) -> tuple[ScheduledEvent, ...]:
        """返回不改变队列的稳定有序快照，不包含已取消事件。"""

        return tuple(sorted(event for event in self._heap if event.eventId in self._activeEventIds))

    def _discardCancelledHead(self) -> None:
        while self._heap and self._heap[0].eventId in self._cancelledEventIds:
            cancelled = heapq.heappop(self._heap)
            self._cancelledEventIds.remove(cancelled.eventId)


def _requireInteger(value: object, fieldName: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{fieldName} must be an integer")
