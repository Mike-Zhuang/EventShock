"""整数 tick、价格—时间优先的限价订单簿。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class TimeInForce(StrEnum):
    GTC = "GTC"
    IOC = "IOC"


@dataclass(slots=True)
class Order:
    orderId: str
    agentId: str
    side: Side
    priceTicks: int
    quantity: int
    remainingQuantity: int
    sequence: int
    step: int
    timeInForce: TimeInForce


@dataclass(slots=True, frozen=True)
class Trade:
    tradeId: str
    buyOrderId: str
    sellOrderId: str
    buyerAgentId: str
    sellerAgentId: str
    priceTicks: int
    quantity: int
    aggressiveSide: Side
    makerAgentId: str
    takerAgentId: str
    step: int


@dataclass(slots=True)
class ExecutionReport:
    order: Order
    trades: list[Trade] = field(default_factory=list)
    status: str = "OPEN"
    protectedUnfilledQuantity: int = 0


class LimitOrderBook:
    """单资产订单簿；成交价采用先到达的 resting order 价格。"""

    def __init__(self, instrumentId: str, *, tickSizeTicks: int = 1) -> None:
        if isinstance(tickSizeTicks, bool) or not isinstance(tickSizeTicks, int):
            raise TypeError("tickSizeTicks must be an integer")
        if tickSizeTicks <= 0:
            raise ValueError("tickSizeTicks must be positive")
        self.instrumentId = instrumentId
        self.tickSizeTicks = tickSizeTicks
        self.bids: dict[int, deque[Order]] = {}
        self.asks: dict[int, deque[Order]] = {}
        self.orderIndex: dict[str, Order] = {}
        self.seenOrderIds: set[str] = set()
        self.sequenceCounter = 0
        self.tradeCounter = 0
        self.lastTradePriceTicks: int | None = None

    def submitLimit(
        self,
        *,
        orderId: str,
        agentId: str,
        side: Side,
        priceTicks: int,
        quantity: int,
        step: int,
        timeInForce: TimeInForce = TimeInForce.GTC,
    ) -> ExecutionReport:
        if priceTicks <= 0:
            raise ValueError("priceTicks must be positive")
        if priceTicks % self.tickSizeTicks:
            raise ValueError(
                f"priceTicks must align to the configured tick grid: {self.tickSizeTicks}"
            )
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if orderId in self.seenOrderIds:
            raise ValueError(f"duplicate orderId: {orderId}")
        self.seenOrderIds.add(orderId)

        self.sequenceCounter += 1
        incomingOrder = Order(
            orderId=orderId,
            agentId=agentId,
            side=side,
            priceTicks=priceTicks,
            quantity=quantity,
            remainingQuantity=quantity,
            sequence=self.sequenceCounter,
            step=step,
            timeInForce=timeInForce,
        )
        executionReport = ExecutionReport(order=incomingOrder)
        self._matchIncoming(incomingOrder, executionReport, step)

        if incomingOrder.remainingQuantity == 0:
            executionReport.status = "FILLED"
        elif timeInForce == TimeInForce.IOC:
            executionReport.status = (
                "PARTIALLY_FILLED_CANCELLED" if executionReport.trades else "CANCELLED"
            )
        else:
            self._restOrder(incomingOrder)
            executionReport.status = "PARTIALLY_FILLED_OPEN" if executionReport.trades else "OPEN"
        return executionReport

    def submitProtectedMarket(
        self,
        *,
        orderId: str,
        agentId: str,
        side: Side,
        quantity: int,
        referencePriceTicks: int,
        collarBps: float,
        step: int,
    ) -> ExecutionReport:
        if referencePriceTicks <= 0:
            raise ValueError("referencePriceTicks must be positive")
        if not 0 <= collarBps <= 5_000:
            raise ValueError("collarBps must be between 0 and 5000")
        collarMultiplier = collarBps / 10_000
        if side == Side.BUY:
            rawProtectedPrice = max(1, round(referencePriceTicks * (1 + collarMultiplier)))
            protectedPriceTicks = self._ceilToTick(rawProtectedPrice)
        else:
            rawProtectedPrice = max(1, round(referencePriceTicks * (1 - collarMultiplier)))
            protectedPriceTicks = self._floorToTick(rawProtectedPrice)
        executionReport = self.submitLimit(
            orderId=orderId,
            agentId=agentId,
            side=side,
            priceTicks=protectedPriceTicks,
            quantity=quantity,
            step=step,
            timeInForce=TimeInForce.IOC,
        )
        # IOC 未成交余量必须显式记录，避免薄簿中剩余数量静默消失。
        executionReport.protectedUnfilledQuantity = executionReport.order.remainingQuantity
        return executionReport

    def cancelOrder(self, orderId: str) -> bool:
        order = self.orderIndex.pop(orderId, None)
        if order is None:
            return False
        sideLevels = self.bids if order.side == Side.BUY else self.asks
        level = sideLevels.get(order.priceTicks)
        if level is None:
            return False
        try:
            level.remove(order)
        except ValueError:
            return False
        if not level:
            del sideLevels[order.priceTicks]
        return True

    def cancelAgentOrders(self, agentId: str) -> int:
        orderIds = [
            orderId for orderId, order in self.orderIndex.items() if order.agentId == agentId
        ]
        return sum(1 for orderId in orderIds if self.cancelOrder(orderId))

    def bestBid(self) -> int | None:
        return max(self.bids, default=None)

    def bestAsk(self) -> int | None:
        return min(self.asks, default=None)

    def midPrice(self, fallbackPriceTicks: int) -> float:
        bestBid = self.bestBid()
        bestAsk = self.bestAsk()
        if bestBid is not None and bestAsk is not None:
            return (bestBid + bestAsk) / 2
        if self.lastTradePriceTicks is not None:
            return float(self.lastTradePriceTicks)
        return float(fallbackPriceTicks)

    def depth(self, levels: int = 3) -> int:
        bidPrices = sorted(self.bids, reverse=True)[:levels]
        askPrices = sorted(self.asks)[:levels]
        return sum(
            order.remainingQuantity
            for priceTicks in [*bidPrices, *askPrices]
            for order in (self.bids if priceTicks in self.bids else self.asks)[priceTicks]
        )

    def snapshot(self, fallbackPriceTicks: int, levels: int = 3) -> dict[str, int | float | None]:
        bestBid = self.bestBid()
        bestAsk = self.bestAsk()
        midPriceTicks = self.midPrice(fallbackPriceTicks)
        spreadTicks = bestAsk - bestBid if bestBid is not None and bestAsk is not None else None
        spreadBps = (
            spreadTicks / midPriceTicks * 10_000
            if spreadTicks is not None and midPriceTicks > 0
            else None
        )
        return {
            "bestBidTicks": bestBid,
            "bestAskTicks": bestAsk,
            "midPriceTicks": midPriceTicks,
            "lastTradePriceTicks": self.lastTradePriceTicks,
            "spreadTicks": spreadTicks,
            "spreadBps": spreadBps,
            "depth": self.depth(levels),
        }

    def _matchIncoming(
        self, incomingOrder: Order, executionReport: ExecutionReport, step: int
    ) -> None:
        oppositeLevels = self.asks if incomingOrder.side == Side.BUY else self.bids
        while incomingOrder.remainingQuantity > 0 and oppositeLevels:
            bestOppositePrice = (
                min(oppositeLevels) if incomingOrder.side == Side.BUY else max(oppositeLevels)
            )
            crosses = (
                incomingOrder.priceTicks >= bestOppositePrice
                if incomingOrder.side == Side.BUY
                else incomingOrder.priceTicks <= bestOppositePrice
            )
            if not crosses:
                break

            restingQueue = oppositeLevels[bestOppositePrice]
            restingOrder = restingQueue[0]
            tradeQuantity = min(incomingOrder.remainingQuantity, restingOrder.remainingQuantity)
            incomingOrder.remainingQuantity -= tradeQuantity
            restingOrder.remainingQuantity -= tradeQuantity
            self.tradeCounter += 1
            if incomingOrder.side == Side.BUY:
                buyOrder, sellOrder = incomingOrder, restingOrder
            else:
                buyOrder, sellOrder = restingOrder, incomingOrder
            trade = Trade(
                tradeId=f"trade-{self.tradeCounter:08d}",
                buyOrderId=buyOrder.orderId,
                sellOrderId=sellOrder.orderId,
                buyerAgentId=buyOrder.agentId,
                sellerAgentId=sellOrder.agentId,
                priceTicks=restingOrder.priceTicks,
                quantity=tradeQuantity,
                aggressiveSide=incomingOrder.side,
                makerAgentId=restingOrder.agentId,
                takerAgentId=incomingOrder.agentId,
                step=step,
            )
            executionReport.trades.append(trade)
            self.lastTradePriceTicks = trade.priceTicks

            if restingOrder.remainingQuantity == 0:
                restingQueue.popleft()
                self.orderIndex.pop(restingOrder.orderId, None)
                if not restingQueue:
                    del oppositeLevels[bestOppositePrice]

    def _restOrder(self, order: Order) -> None:
        sideLevels = self.bids if order.side == Side.BUY else self.asks
        sideLevels.setdefault(order.priceTicks, deque()).append(order)
        self.orderIndex[order.orderId] = order

    def _ceilToTick(self, priceTicks: int) -> int:
        return max(
            self.tickSizeTicks,
            ((priceTicks + self.tickSizeTicks - 1) // self.tickSizeTicks) * self.tickSizeTicks,
        )

    def _floorToTick(self, priceTicks: int) -> int:
        return max(self.tickSizeTicks, (priceTicks // self.tickSizeTicks) * self.tickSizeTicks)
