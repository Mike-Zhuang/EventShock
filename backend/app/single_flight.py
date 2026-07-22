"""仅合并进行中请求的异步单飞协调器。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any


class SingleFlightRequestConflictError(Exception):
    """同一请求 ID 在尚未完成时被用于不同负载。"""


class SingleFlightCapacityError(Exception):
    """进行中的单飞任务已达到内存上限。"""


@dataclass(slots=True)
class _ActiveFlight:
    requestHash: str
    task: asyncio.Task[Any]


@dataclass(slots=True)
class _CompletedFlight:
    requestHash: str
    result: Any
    expiresAt: float


def canonicalRequestHash(payload: Mapping[str, Any]) -> str:
    """对不含密钥的请求上下文生成稳定哈希，避免依赖对象地址或字段顺序。"""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ResultInterpretationSingleFlight:
    """按登录会话和客户端请求 ID 合并结果解释请求。

    调用方取消等待时，底层任务仍继续；成功响应只在内存保留一分钟，以覆盖
    “供应商已计费、HTTP 响应丢失”后的同 ID 重试，不写数据库或长期聊天缓存。
    """

    def __init__(
        self,
        *,
        maxActiveFlights: int = 1_024,
        maxCompletedFlights: int = 1_024,
        completedTtlSeconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if maxActiveFlights < 1:
            raise ValueError("maxActiveFlights must be positive")
        if maxCompletedFlights < 1:
            raise ValueError("maxCompletedFlights must be positive")
        if not 1 <= completedTtlSeconds <= 300:
            raise ValueError("completedTtlSeconds must be between 1 and 300")
        self._maxActiveFlights = maxActiveFlights
        self._maxCompletedFlights = maxCompletedFlights
        self._completedTtlSeconds = completedTtlSeconds
        self._clock = clock
        self._stateLock = asyncio.Lock()
        self._activeFlights: dict[tuple[str, str], _ActiveFlight] = {}
        self._completedFlights: dict[tuple[str, str], _CompletedFlight] = {}
        self._principalLocks: dict[str, asyncio.Lock] = {}

    @property
    def activeCount(self) -> int:
        return len(self._activeFlights)

    @property
    def completedCount(self) -> int:
        return len(self._completedFlights)

    async def purgeExpired(self) -> int:
        """主动清理超过重试窗口的响应，避免无后续请求时继续驻留内存。"""

        async with self._stateLock:
            before = len(self._completedFlights)
            self._purgeCompletedLocked()
            return before - len(self._completedFlights)

    async def clearPrincipal(self, principalKey: str) -> int:
        """退出登录时移除该会话已经完成的短期幂等响应。"""

        async with self._stateLock:
            keys = [key for key in self._completedFlights if key[0] == principalKey]
            for key in keys:
                self._completedFlights.pop(key, None)
            return len(keys)

    async def execute[ResultT](
        self,
        *,
        principalKey: str,
        clientRequestId: str,
        requestHash: str,
        operation: Callable[[], Awaitable[ResultT]],
    ) -> ResultT:
        key = (principalKey, clientRequestId)
        async with self._stateLock:
            self._purgeCompletedLocked()
            completedFlight = self._completedFlights.get(key)
            if completedFlight is not None:
                if completedFlight.requestHash != requestHash:
                    raise SingleFlightRequestConflictError(
                        "clientRequestId is bound to a different recent request"
                    )
                # 仅保留一分钟，覆盖“服务端完成但响应在网络中丢失”的付费重试窗口。
                return completedFlight.result  # type: ignore[return-value]
            activeFlight = self._activeFlights.get(key)
            if activeFlight is not None:
                if activeFlight.requestHash != requestHash:
                    raise SingleFlightRequestConflictError(
                        "clientRequestId is already in use by a different active request"
                    )
                task = activeFlight.task
            else:
                if len(self._activeFlights) >= self._maxActiveFlights:
                    raise SingleFlightCapacityError(
                        "too many result interpretation requests are currently active"
                    )
                principalLock = self._principalLocks.setdefault(
                    principalKey,
                    asyncio.Lock(),
                )
                # 同一 BYOK 会话最多执行一个供应商请求；不同 request ID 排队但不合并。
                task = asyncio.create_task(
                    self._runForPrincipal(principalLock, operation),
                    name=f"result-interpretation:{clientRequestId[:32]}",
                )
                self._activeFlights[key] = _ActiveFlight(
                    requestHash=requestHash,
                    task=task,
                )
                task.add_done_callback(
                    lambda completedTask, flightKey=key: self._scheduleCleanup(
                        flightKey,
                        completedTask,
                    )
                )

        # HTTP 客户端断开只能取消本次等待，不能取消已经计费的供应商调用。
        try:
            return await asyncio.shield(task)
        finally:
            # 正常等待方返回前立即移除完成项；回调负责所有等待方均取消的情况。
            if task.done():
                await self._cleanup(key, task)

    @staticmethod
    async def _runForPrincipal[ResultT](
        principalLock: asyncio.Lock,
        operation: Callable[[], Awaitable[ResultT]],
    ) -> ResultT:
        async with principalLock:
            return await operation()

    def _scheduleCleanup(
        self,
        key: tuple[str, str],
        completedTask: asyncio.Task[Any],
    ) -> None:
        # 若所有 HTTP 等待方都已断开，主动取出异常，避免后台任务产生未消费异常告警。
        if not completedTask.cancelled():
            completedTask.exception()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._cleanup(key, completedTask))

    async def _cleanup(
        self,
        key: tuple[str, str],
        completedTask: asyncio.Task[Any],
    ) -> None:
        async with self._stateLock:
            activeFlight = self._activeFlights.get(key)
            if activeFlight is None or activeFlight.task is not completedTask:
                return
            self._activeFlights.pop(key, None)
            if not completedTask.cancelled() and completedTask.exception() is None:
                if len(self._completedFlights) >= self._maxCompletedFlights:
                    oldestKey = min(
                        self._completedFlights,
                        key=lambda item: self._completedFlights[item].expiresAt,
                    )
                    self._completedFlights.pop(oldestKey, None)
                self._completedFlights[key] = _CompletedFlight(
                    requestHash=activeFlight.requestHash,
                    result=completedTask.result(),
                    expiresAt=self._clock() + self._completedTtlSeconds,
                )
            principalKey = key[0]
            if not any(activeKey[0] == principalKey for activeKey in self._activeFlights):
                principalLock = self._principalLocks.get(principalKey)
                if principalLock is not None and not principalLock.locked():
                    self._principalLocks.pop(principalKey, None)

    def _purgeCompletedLocked(self) -> None:
        now = self._clock()
        expiredKeys = [
            key
            for key, completedFlight in self._completedFlights.items()
            if completedFlight.expiresAt <= now
        ]
        for key in expiredKeys:
            self._completedFlights.pop(key, None)
