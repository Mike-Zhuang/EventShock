"""整数记账、先验风控与守恒检查。

账本通过 ``priceScale`` 把整数 ``priceTicks`` 转换为现金分，避免浮点数舍入
破坏可重放性。现金、费用、成本基础与保证金均使用整数；费用和保证金在需要
向上取整时采用统一规则。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum


class LedgerSide(StrEnum):
    """订单方向。"""

    BUY = "BUY"
    SELL = "SELL"


class RiskDecision(StrEnum):
    """订单风控结论。"""

    ACCEPT = "ACCEPT"
    MODIFY = "MODIFY"
    REJECT = "REJECT"


@dataclass(slots=True)
class PositionState:
    """单账户、单资产的头寸和盈亏状态。"""

    quantity: int = 0
    reservedQuantity: int = 0
    borrowedQuantity: int = 0
    entryNotionalCents: int = 0
    marginUsedCents: int = 0
    realizedPnlCents: int = 0

    @property
    def availableLongQuantity(self) -> int:
        return max(0, self.quantity) - self.reservedQuantity

    @property
    def averageEntryPriceTicks(self) -> float:
        if self.quantity == 0:
            return 0.0
        return self.entryNotionalCents / abs(self.quantity)


@dataclass(slots=True)
class AccountState:
    """账户现金和各资产头寸；锁定现金仍属于账户现金。"""

    accountId: str
    cashCents: int
    reservedCashCents: int = 0
    feesPaidCents: int = 0
    positions: dict[str, PositionState] = field(default_factory=dict)

    @property
    def marginUsedCents(self) -> int:
        return sum(position.marginUsedCents for position in self.positions.values())

    @property
    def availableCashCents(self) -> int:
        return self.cashCents - self.reservedCashCents - self.marginUsedCents

    def getPosition(self, instrumentId: str) -> PositionState:
        return self.positions.setdefault(instrumentId, PositionState())


@dataclass(slots=True)
class BorrowPoolState:
    """可借券库存；reserved 与 borrowed 不能超过 total。"""

    totalQuantity: int
    reservedQuantity: int = 0
    borrowedQuantity: int = 0

    @property
    def availableQuantity(self) -> int:
        return self.totalQuantity - self.reservedQuantity - self.borrowedQuantity


@dataclass(slots=True)
class OrderReservation:
    """通过风控后为未成交订单保留的资源。"""

    orderId: str
    accountId: str
    instrumentId: str
    side: LedgerSide
    limitPriceTicks: int
    originalQuantity: int
    remainingQuantity: int
    reservedCashCents: int = 0
    reservedLongQuantity: int = 0
    reservedBorrowQuantity: int = 0
    reservedMarginCents: int = 0


@dataclass(frozen=True, slots=True)
class OrderRiskResult:
    """订单在进入撮合前的可审计风控结果。"""

    decision: RiskDecision
    requestedQuantity: int
    approvedQuantity: int
    modifications: tuple[str, ...] = ()
    rejectionReason: str | None = None
    reservation: OrderReservation | None = None


@dataclass(frozen=True, slots=True)
class AccountValuation:
    """给定盯市价格下的账户估值。"""

    accountId: str
    cashCents: int
    marketValueCents: int
    equityCents: int
    realizedPnlCents: int
    unrealizedPnlCents: int
    feesPaidCents: int
    marginUsedCents: int


@dataclass(frozen=True, slots=True)
class LedgerInvariantReport:
    """账本守恒与资源锁定一致性报告。"""

    cashConserved: bool
    positionsConserved: bool
    borrowInventoryValid: bool
    reservationsValid: bool
    initialTotalCashCents: int
    currentTotalCashCents: int
    violations: tuple[str, ...]

    @property
    def isValid(self) -> bool:
        return not self.violations


class PortfolioLedger:
    """支持多账户、多资产、借券和保证金的确定性账本。"""

    def __init__(
        self,
        *,
        tradeFeeBps: int = 0,
        tradeFeeMicroBps: int | None = None,
        initialMarginRateBps: int = 5_000,
        priceScale: int = 100,
    ) -> None:
        _requireInteger(tradeFeeBps, "tradeFeeBps")
        if tradeFeeMicroBps is not None:
            _requireInteger(tradeFeeMicroBps, "tradeFeeMicroBps")
        _requireInteger(initialMarginRateBps, "initialMarginRateBps")
        _requireInteger(priceScale, "priceScale")
        if not 0 <= tradeFeeBps <= 1_000:
            raise ValueError("tradeFeeBps must be between 0 and 1000")
        if tradeFeeMicroBps is not None and not 0 <= tradeFeeMicroBps <= 1_000_000_000:
            raise ValueError("tradeFeeMicroBps must be between 0 and 1000000000")
        if tradeFeeMicroBps is not None and tradeFeeBps:
            raise ValueError("set either tradeFeeBps or tradeFeeMicroBps, not both")
        if not 0 <= initialMarginRateBps <= 10_000:
            raise ValueError("initialMarginRateBps must be between 0 and 10000")
        if priceScale <= 0:
            raise ValueError("priceScale must be positive")
        self.tradeFeeBps = tradeFeeBps
        self.tradeFeeMicroBps = (
            tradeFeeBps * 1_000_000 if tradeFeeMicroBps is None else tradeFeeMicroBps
        )
        self.initialMarginRateBps = initialMarginRateBps
        self.priceScale = priceScale
        self.accounts: dict[str, AccountState] = {}
        self.borrowPools: dict[str, BorrowPoolState] = {}
        self.reservations: dict[str, OrderReservation] = {}
        self.feeCollectorCashCents = 0
        self._sealed = False
        self._initialTotalCashCents = 0
        self._initialNetPositions: dict[str, int] = {}

    def registerAccount(
        self,
        accountId: str,
        cashCents: int,
        *,
        initialLongPositions: Mapping[str, tuple[int, int]] | None = None,
    ) -> AccountState:
        """登记账户；初始头寸为 ``资产 -> (数量, 每单位成本)``。"""

        if self._sealed:
            raise RuntimeError("cannot register an account after ledger activity has started")
        self._validateIdentifier(accountId, "accountId")
        _requireInteger(cashCents, "cashCents")
        if accountId in self.accounts:
            raise ValueError(f"accountId already exists: {accountId}")
        if cashCents < 0:
            raise ValueError("cashCents must be non-negative")

        account = AccountState(accountId=accountId, cashCents=cashCents)
        for instrumentId, (quantity, entryPriceTicks) in (initialLongPositions or {}).items():
            self._validateInstrument(instrumentId)
            _requireInteger(quantity, "initial position quantity")
            _requireInteger(entryPriceTicks, "entryPriceTicks")
            if quantity < 0:
                raise ValueError("initial positions must be long or flat")
            if entryPriceTicks <= 0 and quantity:
                raise ValueError("entryPriceTicks must be positive for a non-zero position")
            account.positions[instrumentId] = PositionState(
                quantity=quantity,
                entryNotionalCents=self._notionalCents(entryPriceTicks, quantity),
            )
            self._initialNetPositions[instrumentId] = (
                self._initialNetPositions.get(instrumentId, 0) + quantity
            )
        self.accounts[accountId] = account
        self._initialTotalCashCents += cashCents
        return account

    def configureBorrowPool(self, instrumentId: str, totalQuantity: int) -> BorrowPoolState:
        if self._sealed:
            raise RuntimeError(
                "cannot configure borrow inventory after ledger activity has started"
            )
        self._validateInstrument(instrumentId)
        _requireInteger(totalQuantity, "totalQuantity")
        if totalQuantity < 0:
            raise ValueError("totalQuantity must be non-negative")
        if instrumentId in self.borrowPools:
            raise ValueError(f"borrow pool already exists: {instrumentId}")
        pool = BorrowPoolState(totalQuantity=totalQuantity)
        self.borrowPools[instrumentId] = pool
        return pool

    def evaluateAndReserveOrder(
        self,
        *,
        orderId: str,
        accountId: str,
        instrumentId: str,
        side: LedgerSide,
        quantity: int,
        limitPriceTicks: int,
        maxOrderQuantity: int,
        maxAbsolutePosition: int,
        allowShortSelling: bool = False,
    ) -> OrderRiskResult:
        """执行现金、仓位、借券、保证金限制，并原子化锁定获批资源。"""

        self._validateOrderInputs(
            orderId=orderId,
            accountId=accountId,
            instrumentId=instrumentId,
            side=side,
            quantity=quantity,
            limitPriceTicks=limitPriceTicks,
            maxOrderQuantity=maxOrderQuantity,
            maxAbsolutePosition=maxAbsolutePosition,
        )
        if orderId in self.reservations:
            raise ValueError(f"orderId already has a reservation: {orderId}")
        if not isinstance(allowShortSelling, bool):
            raise TypeError("allowShortSelling must be a boolean")
        self._seal()

        account = self.accounts[accountId]
        position = account.getPosition(instrumentId)
        modifications: list[str] = []
        approvedQuantity = min(quantity, maxOrderQuantity)
        if approvedQuantity < quantity:
            modifications.append("quantity reduced by maxOrderQuantity")

        projectedPosition = self._projectedPosition(accountId, instrumentId)
        positionCapacity = (
            maxAbsolutePosition - projectedPosition
            if side is LedgerSide.BUY
            else maxAbsolutePosition + projectedPosition
        )
        approvedQuantity = min(approvedQuantity, max(0, positionCapacity))
        if approvedQuantity < min(quantity, maxOrderQuantity):
            modifications.append("quantity reduced by maxAbsolutePosition")
        if approvedQuantity <= 0:
            return self._rejection(quantity, "position limit leaves no executable quantity")

        if side is LedgerSide.BUY:
            affordableQuantity = self._maxAffordableBuyQuantity(
                account.availableCashCents,
                limitPriceTicks,
                approvedQuantity,
            )
            if affordableQuantity < approvedQuantity:
                modifications.append("quantity reduced by available cash")
                approvedQuantity = affordableQuantity
            if approvedQuantity <= 0:
                return self._rejection(quantity, "insufficient available cash")
            reservedCashCents = self._buyCashRequirement(limitPriceTicks, approvedQuantity)
            reservation = OrderReservation(
                orderId=orderId,
                accountId=accountId,
                instrumentId=instrumentId,
                side=side,
                limitPriceTicks=limitPriceTicks,
                originalQuantity=approvedQuantity,
                remainingQuantity=approvedQuantity,
                reservedCashCents=reservedCashCents,
            )
            account.reservedCashCents += reservedCashCents
        else:
            availableLongQuantity = position.availableLongQuantity
            longQuantity = min(approvedQuantity, availableLongQuantity)
            shortQuantity = approvedQuantity - longQuantity
            if shortQuantity and not allowShortSelling:
                approvedQuantity = longQuantity
                shortQuantity = 0
                modifications.append("short portion removed because short selling is disabled")
            if approvedQuantity <= 0:
                return self._rejection(quantity, "no available long position to sell")

            if shortQuantity:
                borrowPool = self.borrowPools.get(instrumentId)
                availableBorrow = borrowPool.availableQuantity if borrowPool else 0
                availableMarginQuantity = self._maxAffordableMarginQuantity(
                    account.availableCashCents,
                    limitPriceTicks,
                    shortQuantity,
                )
                approvedShortQuantity = min(shortQuantity, availableBorrow, availableMarginQuantity)
                if approvedShortQuantity < shortQuantity:
                    modifications.append("short portion reduced by borrow or margin availability")
                shortQuantity = approvedShortQuantity
                approvedQuantity = longQuantity + shortQuantity
            if approvedQuantity <= 0:
                return self._rejection(quantity, "insufficient borrow inventory or margin")

            reservedMarginCents = self._marginRequirement(limitPriceTicks, shortQuantity)
            reservation = OrderReservation(
                orderId=orderId,
                accountId=accountId,
                instrumentId=instrumentId,
                side=side,
                limitPriceTicks=limitPriceTicks,
                originalQuantity=approvedQuantity,
                remainingQuantity=approvedQuantity,
                reservedLongQuantity=longQuantity,
                reservedBorrowQuantity=shortQuantity,
                reservedMarginCents=reservedMarginCents,
            )
            position.reservedQuantity += longQuantity
            account.reservedCashCents += reservedMarginCents
            if shortQuantity:
                self.borrowPools[instrumentId].reservedQuantity += shortQuantity

        self.reservations[orderId] = reservation
        decision = RiskDecision.MODIFY if approvedQuantity < quantity else RiskDecision.ACCEPT
        return OrderRiskResult(
            decision=decision,
            requestedQuantity=quantity,
            approvedQuantity=approvedQuantity,
            modifications=tuple(modifications),
            # 风控结果保存当时的不可变语义快照，后续部分成交不会改写历史结论。
            reservation=replace(reservation),
        )

    def releaseOrder(self, orderId: str) -> OrderReservation:
        """撤单或到期时释放尚未成交部分的全部资源。"""

        reservation = self.reservations.pop(orderId)
        account = self.accounts[reservation.accountId]
        position = account.getPosition(reservation.instrumentId)
        account.reservedCashCents -= reservation.reservedCashCents + reservation.reservedMarginCents
        position.reservedQuantity -= reservation.reservedLongQuantity
        if reservation.reservedBorrowQuantity:
            self.borrowPools[
                reservation.instrumentId
            ].reservedQuantity -= reservation.reservedBorrowQuantity
        reservation.remainingQuantity = 0
        reservation.reservedCashCents = 0
        reservation.reservedLongQuantity = 0
        reservation.reservedBorrowQuantity = 0
        reservation.reservedMarginCents = 0
        return reservation

    def applyTrade(
        self,
        *,
        buyOrderId: str,
        sellOrderId: str,
        priceTicks: int,
        quantity: int,
    ) -> None:
        """结算一笔已撮合成交，并同步更新费用、借券、保证金和盈亏。"""

        self._validateIdentifier(buyOrderId, "buyOrderId")
        self._validateIdentifier(sellOrderId, "sellOrderId")
        _requireInteger(priceTicks, "priceTicks")
        _requireInteger(quantity, "quantity")
        if priceTicks <= 0:
            raise ValueError("priceTicks must be positive")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        buyReservation = self._getReservation(buyOrderId, LedgerSide.BUY)
        sellReservation = self._getReservation(sellOrderId, LedgerSide.SELL)
        if buyReservation.accountId == sellReservation.accountId:
            raise ValueError("self-trades are not supported by the scientific ledger")
        if buyReservation.instrumentId != sellReservation.instrumentId:
            raise ValueError("buy and sell reservations use different instruments")
        if quantity > buyReservation.remainingQuantity:
            raise ValueError("trade quantity exceeds buy reservation")
        if quantity > sellReservation.remainingQuantity:
            raise ValueError("trade quantity exceeds sell reservation")
        if priceTicks > buyReservation.limitPriceTicks:
            raise ValueError("trade price exceeds the buy limit")
        if priceTicks < sellReservation.limitPriceTicks:
            raise ValueError("trade price is below the sell limit")

        buyer = self.accounts[buyReservation.accountId]
        seller = self.accounts[sellReservation.accountId]
        instrumentId = buyReservation.instrumentId
        buyerPosition = buyer.getPosition(instrumentId)
        sellerPosition = seller.getPosition(instrumentId)
        notionalCents = self._notionalCents(priceTicks, quantity)
        buyerFeeCents = self._feeCents(notionalCents)
        sellerFeeCents = self._feeCents(notionalCents)
        self._preflightSettlement(
            buyer,
            seller,
            buyReservation,
            sellReservation,
            priceTicks,
            quantity,
            buyerFeeCents,
            sellerFeeCents,
        )

        self._consumeBuyReservation(buyer, buyReservation, quantity)
        shortFillQuantity = self._consumeSellReservation(
            seller, sellerPosition, sellReservation, priceTicks, quantity
        )

        buyer.cashCents -= notionalCents + buyerFeeCents
        seller.cashCents += notionalCents - sellerFeeCents
        buyer.feesPaidCents += buyerFeeCents
        seller.feesPaidCents += sellerFeeCents
        self.feeCollectorCashCents += buyerFeeCents + sellerFeeCents

        self._applyBuy(buyerPosition, instrumentId, priceTicks, quantity)
        self._applySell(
            sellerPosition,
            instrumentId,
            priceTicks,
            quantity,
            shortFillQuantity,
        )
        self._removeFilledReservation(buyReservation)
        self._removeFilledReservation(sellReservation)
        self.assertInvariants()

    def markToMarket(
        self,
        accountId: str,
        markPrices: Mapping[str, int],
    ) -> AccountValuation:
        account = self.accounts[accountId]
        marketValueCents = 0
        unrealizedPnlCents = 0
        realizedPnlCents = 0
        for instrumentId, markPrice in markPrices.items():
            self._validateInstrument(instrumentId)
            _requireInteger(markPrice, f"mark price for {instrumentId}")
        for instrumentId, position in account.positions.items():
            if position.quantity and instrumentId not in markPrices:
                raise ValueError(f"missing mark price for {instrumentId}")
            markPrice = markPrices.get(instrumentId, 0)
            if markPrice < 0:
                raise ValueError("mark prices must be non-negative")
            absoluteMarketValueCents = self._notionalCents(markPrice, abs(position.quantity))
            marketValueCents += (
                absoluteMarketValueCents if position.quantity >= 0 else -absoluteMarketValueCents
            )
            if position.quantity > 0:
                unrealizedPnlCents += absoluteMarketValueCents - position.entryNotionalCents
            elif position.quantity < 0:
                unrealizedPnlCents += position.entryNotionalCents - absoluteMarketValueCents
            realizedPnlCents += position.realizedPnlCents
        return AccountValuation(
            accountId=accountId,
            cashCents=account.cashCents,
            marketValueCents=marketValueCents,
            equityCents=account.cashCents + marketValueCents,
            realizedPnlCents=realizedPnlCents,
            unrealizedPnlCents=unrealizedPnlCents,
            feesPaidCents=account.feesPaidCents,
            marginUsedCents=account.marginUsedCents,
        )

    def checkInvariants(self) -> LedgerInvariantReport:
        self._seal()
        violations: list[str] = []
        currentTotalCashCents = (
            sum(account.cashCents for account in self.accounts.values())
            + self.feeCollectorCashCents
        )
        cashConserved = currentTotalCashCents == self._initialTotalCashCents
        if not cashConserved:
            violations.append("cash is not conserved")

        currentNetPositions: dict[str, int] = {}
        for account in self.accounts.values():
            if account.cashCents < 0 or account.availableCashCents < 0:
                violations.append(f"account {account.accountId} has negative available cash")
            for instrumentId, position in account.positions.items():
                currentNetPositions[instrumentId] = (
                    currentNetPositions.get(instrumentId, 0) + position.quantity
                )
        allInstruments = set(currentNetPositions) | set(self._initialNetPositions)
        positionsConserved = all(
            currentNetPositions.get(instrumentId, 0)
            == self._initialNetPositions.get(instrumentId, 0)
            for instrumentId in allInstruments
        )
        if not positionsConserved:
            violations.append("net positions are not conserved")

        borrowInventoryValid = self._checkBorrowInventory(violations)
        reservationsValid = self._checkReservations(violations)
        return LedgerInvariantReport(
            cashConserved=cashConserved,
            positionsConserved=positionsConserved,
            borrowInventoryValid=borrowInventoryValid,
            reservationsValid=reservationsValid,
            initialTotalCashCents=self._initialTotalCashCents,
            currentTotalCashCents=currentTotalCashCents,
            violations=tuple(violations),
        )

    def assertInvariants(self) -> None:
        report = self.checkInvariants()
        if not report.isValid:
            raise AssertionError("; ".join(report.violations))

    def _consumeBuyReservation(
        self,
        account: AccountState,
        reservation: OrderReservation,
        quantity: int,
    ) -> None:
        oldReservedCash = reservation.reservedCashCents
        reservation.remainingQuantity -= quantity
        reservation.reservedCashCents = self._buyCashRequirement(
            reservation.limitPriceTicks,
            reservation.remainingQuantity,
        )
        account.reservedCashCents -= oldReservedCash - reservation.reservedCashCents

    def _preflightSettlement(
        self,
        buyer: AccountState,
        seller: AccountState,
        buyReservation: OrderReservation,
        sellReservation: OrderReservation,
        priceTicks: int,
        quantity: int,
        buyerFeeCents: int,
        sellerFeeCents: int,
    ) -> None:
        """在写入任何字段前验证成交后的现金和保证金，保证失败时原子回滚。"""

        notionalCents = self._notionalCents(priceTicks, quantity)
        buyRemainingQuantity = buyReservation.remainingQuantity - quantity
        buyRemainingCash = self._buyCashRequirement(
            buyReservation.limitPriceTicks,
            buyRemainingQuantity,
        )
        buyerReservedAfter = (
            buyer.reservedCashCents - buyReservation.reservedCashCents + buyRemainingCash
        )
        buyerCashAfter = buyer.cashCents - notionalCents - buyerFeeCents
        if buyerCashAfter - buyerReservedAfter - buyer.marginUsedCents < 0:
            raise ValueError("trade would make buyer available cash negative")

        longFillQuantity = min(quantity, sellReservation.reservedLongQuantity)
        shortFillQuantity = quantity - longFillQuantity
        remainingBorrowQuantity = sellReservation.reservedBorrowQuantity - shortFillQuantity
        sellRemainingMargin = self._marginRequirement(
            sellReservation.limitPriceTicks,
            remainingBorrowQuantity,
        )
        sellerReservedAfter = (
            seller.reservedCashCents - sellReservation.reservedMarginCents + sellRemainingMargin
        )
        sellerMarginAfter = seller.marginUsedCents + self._marginRequirement(
            priceTicks,
            shortFillQuantity,
        )
        sellerCashAfter = seller.cashCents + notionalCents - sellerFeeCents
        if sellerCashAfter - sellerReservedAfter - sellerMarginAfter < 0:
            raise ValueError("trade would make seller available cash negative")

    def _consumeSellReservation(
        self,
        account: AccountState,
        position: PositionState,
        reservation: OrderReservation,
        priceTicks: int,
        quantity: int,
    ) -> int:
        longFillQuantity = min(quantity, reservation.reservedLongQuantity)
        shortFillQuantity = quantity - longFillQuantity
        reservation.remainingQuantity -= quantity
        reservation.reservedLongQuantity -= longFillQuantity
        position.reservedQuantity -= longFillQuantity

        if shortFillQuantity:
            reservation.reservedBorrowQuantity -= shortFillQuantity
            pool = self.borrowPools[reservation.instrumentId]
            pool.reservedQuantity -= shortFillQuantity
            pool.borrowedQuantity += shortFillQuantity

        oldReservedMargin = reservation.reservedMarginCents
        reservation.reservedMarginCents = self._marginRequirement(
            reservation.limitPriceTicks,
            reservation.reservedBorrowQuantity,
        )
        account.reservedCashCents -= oldReservedMargin - reservation.reservedMarginCents
        actualMarginCents = self._marginRequirement(priceTicks, shortFillQuantity)
        position.marginUsedCents += actualMarginCents
        return shortFillQuantity

    def _applyBuy(
        self,
        position: PositionState,
        instrumentId: str,
        priceTicks: int,
        quantity: int,
    ) -> None:
        remainingQuantity = quantity
        if position.quantity < 0:
            previousShortQuantity = abs(position.quantity)
            coverQuantity = min(previousShortQuantity, remainingQuantity)
            allocatedEntryNotional = self._allocatedBasis(
                position.entryNotionalCents,
                coverQuantity,
                previousShortQuantity,
            )
            position.realizedPnlCents += allocatedEntryNotional - self._notionalCents(
                priceTicks, coverQuantity
            )
            position.entryNotionalCents -= allocatedEntryNotional
            position.quantity += coverQuantity
            remainingQuantity -= coverQuantity

            releasedMargin = self._allocatedBasis(
                position.marginUsedCents,
                coverQuantity,
                previousShortQuantity,
            )
            position.marginUsedCents -= releasedMargin
            position.borrowedQuantity -= coverQuantity
            self.borrowPools[instrumentId].borrowedQuantity -= coverQuantity
            if position.quantity == 0:
                position.entryNotionalCents = 0
                position.marginUsedCents = 0

        if remainingQuantity:
            position.quantity += remainingQuantity
            position.entryNotionalCents += self._notionalCents(priceTicks, remainingQuantity)

    def _applySell(
        self,
        position: PositionState,
        instrumentId: str,
        priceTicks: int,
        quantity: int,
        shortFillQuantity: int,
    ) -> None:
        remainingQuantity = quantity
        if position.quantity > 0:
            previousLongQuantity = position.quantity
            closeQuantity = min(previousLongQuantity, remainingQuantity)
            allocatedEntryNotional = self._allocatedBasis(
                position.entryNotionalCents,
                closeQuantity,
                previousLongQuantity,
            )
            position.realizedPnlCents += (
                self._notionalCents(priceTicks, closeQuantity) - allocatedEntryNotional
            )
            position.entryNotionalCents -= allocatedEntryNotional
            position.quantity -= closeQuantity
            remainingQuantity -= closeQuantity
            if position.quantity == 0:
                position.entryNotionalCents = 0

        if remainingQuantity:
            if remainingQuantity != shortFillQuantity:
                raise AssertionError("short fill does not match the position transition")
            position.quantity -= remainingQuantity
            position.borrowedQuantity += remainingQuantity
            position.entryNotionalCents += self._notionalCents(priceTicks, remainingQuantity)
            if instrumentId not in self.borrowPools:
                raise AssertionError("short position has no borrow pool")

    def _removeFilledReservation(self, reservation: OrderReservation) -> None:
        if reservation.remainingQuantity == 0:
            if any(
                (
                    reservation.reservedCashCents,
                    reservation.reservedLongQuantity,
                    reservation.reservedBorrowQuantity,
                    reservation.reservedMarginCents,
                )
            ):
                raise AssertionError("filled reservation still holds resources")
            self.reservations.pop(reservation.orderId)

    def _projectedPosition(self, accountId: str, instrumentId: str) -> int:
        position = self.accounts[accountId].getPosition(instrumentId).quantity
        pendingChange = sum(
            reservation.remainingQuantity * (1 if reservation.side is LedgerSide.BUY else -1)
            for reservation in self.reservations.values()
            if reservation.accountId == accountId and reservation.instrumentId == instrumentId
        )
        return position + pendingChange

    def _maxAffordableBuyQuantity(
        self,
        availableCashCents: int,
        limitPriceTicks: int,
        maximumQuantity: int,
    ) -> int:
        return self._binarySearchQuantity(
            maximumQuantity,
            lambda quantity: (
                self._buyCashRequirement(limitPriceTicks, quantity) <= availableCashCents
            ),
        )

    def _maxAffordableMarginQuantity(
        self,
        availableCashCents: int,
        limitPriceTicks: int,
        maximumQuantity: int,
    ) -> int:
        return self._binarySearchQuantity(
            maximumQuantity,
            lambda quantity: (
                self._marginRequirement(limitPriceTicks, quantity) <= availableCashCents
            ),
        )

    @staticmethod
    def _binarySearchQuantity(
        maximumQuantity: int,
        fits: Callable[[int], bool],
    ) -> int:
        low = 0
        high = maximumQuantity
        while low < high:
            middle = (low + high + 1) // 2
            if fits(middle):
                low = middle
            else:
                high = middle - 1
        return low

    def _buyCashRequirement(self, priceTicks: int, quantity: int) -> int:
        notionalCents = self._notionalCents(priceTicks, quantity)
        return notionalCents + self._feeCents(notionalCents)

    def _marginRequirement(self, priceTicks: int, quantity: int) -> int:
        return self._ceilBps(
            self._notionalCents(priceTicks, quantity),
            self.initialMarginRateBps,
        )

    def _feeCents(self, notionalCents: int) -> int:
        if notionalCents == 0 or self.tradeFeeMicroBps == 0:
            return 0
        denominator = 10_000 * 1_000_000
        return (notionalCents * self.tradeFeeMicroBps + denominator - 1) // denominator

    def notionalCents(self, priceTicks: int, quantity: int) -> int:
        """按账本价格精度返回可审计的整数现金名义金额。"""

        _requireInteger(priceTicks, "priceTicks")
        _requireInteger(quantity, "quantity")
        if priceTicks < 0 or quantity < 0:
            raise ValueError("priceTicks and quantity must be non-negative")
        return self._notionalCents(priceTicks, quantity)

    def _notionalCents(self, priceTicks: int, quantity: int) -> int:
        # 半分向上取整；同一转换同时用于预留、成交和盯市，保证单调与守恒。
        numerator = priceTicks * quantity * 100
        return (numerator * 2 + self.priceScale) // (2 * self.priceScale)

    @staticmethod
    def _ceilBps(value: int, rateBps: int) -> int:
        if value == 0 or rateBps == 0:
            return 0
        return (value * rateBps + 9_999) // 10_000

    @staticmethod
    def _allocatedBasis(totalBasis: int, closeQuantity: int, openQuantity: int) -> int:
        if closeQuantity == openQuantity:
            return totalBasis
        return totalBasis * closeQuantity // openQuantity

    @staticmethod
    def _rejection(requestedQuantity: int, reason: str) -> OrderRiskResult:
        return OrderRiskResult(
            decision=RiskDecision.REJECT,
            requestedQuantity=requestedQuantity,
            approvedQuantity=0,
            rejectionReason=reason,
        )

    def _getReservation(
        self,
        orderId: str,
        expectedSide: LedgerSide,
    ) -> OrderReservation:
        try:
            reservation = self.reservations[orderId]
        except KeyError as error:
            raise KeyError(f"unknown order reservation: {orderId}") from error
        if reservation.side is not expectedSide:
            raise ValueError(f"order {orderId} is not a {expectedSide.value} order")
        return reservation

    def _checkBorrowInventory(self, violations: list[str]) -> bool:
        valid = True
        for instrumentId, pool in self.borrowPools.items():
            if min(pool.totalQuantity, pool.reservedQuantity, pool.borrowedQuantity) < 0:
                violations.append(f"borrow pool {instrumentId} contains a negative value")
                valid = False
            if pool.reservedQuantity + pool.borrowedQuantity > pool.totalQuantity:
                violations.append(f"borrow pool {instrumentId} exceeds total inventory")
                valid = False
            positionBorrowed = sum(
                account.positions.get(instrumentId, PositionState()).borrowedQuantity
                for account in self.accounts.values()
            )
            if positionBorrowed != pool.borrowedQuantity:
                violations.append(f"borrowed positions do not match pool {instrumentId}")
                valid = False
        for account in self.accounts.values():
            for instrumentId, position in account.positions.items():
                if position.borrowedQuantity != max(0, -position.quantity):
                    violations.append(
                        f"borrowed quantity does not match short position for "
                        f"{account.accountId}/{instrumentId}"
                    )
                    valid = False
                if position.borrowedQuantity and instrumentId not in self.borrowPools:
                    violations.append(f"short position has no borrow pool: {instrumentId}")
                    valid = False
        return valid

    def _checkReservations(self, violations: list[str]) -> bool:
        valid = True
        expectedCashByAccount = {accountId: 0 for accountId in self.accounts}
        expectedLongByPosition: dict[tuple[str, str], int] = {}
        expectedBorrowByInstrument: dict[str, int] = {}
        for reservation in self.reservations.values():
            if reservation.remainingQuantity <= 0:
                violations.append(f"reservation {reservation.orderId} has no remaining quantity")
                valid = False
            heldQuantity = (
                reservation.reservedLongQuantity + reservation.reservedBorrowQuantity
                if reservation.side is LedgerSide.SELL
                else reservation.remainingQuantity
            )
            if heldQuantity != reservation.remainingQuantity:
                violations.append(f"reservation {reservation.orderId} has inconsistent resources")
                valid = False
            expectedCashByAccount[reservation.accountId] += (
                reservation.reservedCashCents + reservation.reservedMarginCents
            )
            positionKey = (reservation.accountId, reservation.instrumentId)
            expectedLongByPosition[positionKey] = (
                expectedLongByPosition.get(positionKey, 0) + reservation.reservedLongQuantity
            )
            expectedBorrowByInstrument[reservation.instrumentId] = (
                expectedBorrowByInstrument.get(reservation.instrumentId, 0)
                + reservation.reservedBorrowQuantity
            )
        for accountId, account in self.accounts.items():
            if account.reservedCashCents != expectedCashByAccount[accountId]:
                violations.append(f"reserved cash does not match orders for {accountId}")
                valid = False
            for instrumentId, position in account.positions.items():
                expectedLong = expectedLongByPosition.get((accountId, instrumentId), 0)
                if position.reservedQuantity != expectedLong:
                    violations.append(
                        f"reserved position does not match orders for {accountId}/{instrumentId}"
                    )
                    valid = False
                if not 0 <= position.reservedQuantity <= max(0, position.quantity):
                    violations.append(f"invalid reserved position for {accountId}/{instrumentId}")
                    valid = False
                if (
                    min(
                        position.entryNotionalCents,
                        position.marginUsedCents,
                        position.borrowedQuantity,
                    )
                    < 0
                ):
                    violations.append("position contains a negative accounting field")
                    valid = False
        for instrumentId, pool in self.borrowPools.items():
            if pool.reservedQuantity != expectedBorrowByInstrument.get(instrumentId, 0):
                violations.append(f"reserved borrow does not match orders for {instrumentId}")
                valid = False
        return valid

    def _validateOrderInputs(
        self,
        *,
        orderId: str,
        accountId: str,
        instrumentId: str,
        side: LedgerSide,
        quantity: int,
        limitPriceTicks: int,
        maxOrderQuantity: int,
        maxAbsolutePosition: int,
    ) -> None:
        self._validateIdentifier(orderId, "orderId")
        self._validateIdentifier(accountId, "accountId")
        if accountId not in self.accounts:
            raise KeyError(f"unknown accountId: {accountId}")
        self._validateInstrument(instrumentId)
        if not isinstance(side, LedgerSide):
            raise TypeError("side must be a LedgerSide")
        _requireInteger(quantity, "quantity")
        _requireInteger(limitPriceTicks, "limitPriceTicks")
        _requireInteger(maxOrderQuantity, "maxOrderQuantity")
        _requireInteger(maxAbsolutePosition, "maxAbsolutePosition")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if limitPriceTicks <= 0:
            raise ValueError("limitPriceTicks must be positive")
        if maxOrderQuantity <= 0:
            raise ValueError("maxOrderQuantity must be positive")
        if maxAbsolutePosition < 0:
            raise ValueError("maxAbsolutePosition must be non-negative")

    @staticmethod
    def _validateInstrument(instrumentId: str) -> None:
        PortfolioLedger._validateIdentifier(instrumentId, "instrumentId")

    @staticmethod
    def _validateIdentifier(value: object, fieldName: str) -> None:
        if not isinstance(value, str):
            raise TypeError(f"{fieldName} must be a string")
        if not value:
            raise ValueError(f"{fieldName} must not be empty")

    def _seal(self) -> None:
        self._sealed = True


def _requireInteger(value: object, fieldName: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{fieldName} must be an integer")
