import pytest

from backend.app.simulation.ledger import (
    LedgerSide,
    PortfolioLedger,
    RiskDecision,
)


def reserveOrder(
    ledger: PortfolioLedger,
    *,
    orderId: str,
    accountId: str,
    side: LedgerSide,
    quantity: int,
    limitPriceTicks: int,
    allowShortSelling: bool = False,
) -> None:
    result = ledger.evaluateAndReserveOrder(
        orderId=orderId,
        accountId=accountId,
        instrumentId="SPCX",
        side=side,
        quantity=quantity,
        limitPriceTicks=limitPriceTicks,
        maxOrderQuantity=100,
        maxAbsolutePosition=100,
        allowShortSelling=allowShortSelling,
    )
    assert result.decision is RiskDecision.ACCEPT


def test_trade_updates_cash_fees_positions_pnl_and_conserves_assets() -> None:
    ledger = PortfolioLedger(tradeFeeBps=10)
    buyer = ledger.registerAccount("buyer", 100_000)
    seller = ledger.registerAccount(
        "seller",
        10_000,
        initialLongPositions={"SPCX": (20, 800)},
    )
    reserveOrder(
        ledger,
        orderId="buy-1",
        accountId="buyer",
        side=LedgerSide.BUY,
        quantity=5,
        limitPriceTicks=1_050,
    )
    reserveOrder(
        ledger,
        orderId="sell-1",
        accountId="seller",
        side=LedgerSide.SELL,
        quantity=5,
        limitPriceTicks=950,
    )

    ledger.applyTrade(
        buyOrderId="buy-1",
        sellOrderId="sell-1",
        priceTicks=1_000,
        quantity=5,
    )

    assert buyer.cashCents == 94_995
    assert seller.cashCents == 14_995
    assert ledger.feeCollectorCashCents == 10
    assert buyer.getPosition("SPCX").quantity == 5
    assert seller.getPosition("SPCX").quantity == 15
    assert seller.getPosition("SPCX").realizedPnlCents == 1_000
    valuation = ledger.markToMarket("buyer", {"SPCX": 1_100})
    assert valuation.unrealizedPnlCents == 500
    assert valuation.equityCents == 100_495
    assert valuation.feesPaidCents == 5
    assert ledger.checkInvariants().isValid


def test_fractional_basis_point_fee_uses_integer_micro_bps() -> None:
    ledger = PortfolioLedger(tradeFeeMicroBps=300_000)
    buyer = ledger.registerAccount("buyer", 100_000)
    seller = ledger.registerAccount(
        "seller",
        10_000,
        initialLongPositions={"SPCX": (20, 800)},
    )
    reserveOrder(
        ledger,
        orderId="buy-fractional-fee",
        accountId="buyer",
        side=LedgerSide.BUY,
        quantity=5,
        limitPriceTicks=1_050,
    )
    reserveOrder(
        ledger,
        orderId="sell-fractional-fee",
        accountId="seller",
        side=LedgerSide.SELL,
        quantity=5,
        limitPriceTicks=950,
    )

    ledger.applyTrade(
        buyOrderId="buy-fractional-fee",
        sellOrderId="sell-fractional-fee",
        priceTicks=1_000,
        quantity=5,
    )

    assert buyer.feesPaidCents == 1
    assert seller.feesPaidCents == 1
    assert ledger.feeCollectorCashCents == 2
    assert ledger.checkInvariants().isValid


def test_partial_fill_and_cancel_release_exact_resources() -> None:
    ledger = PortfolioLedger()
    buyer = ledger.registerAccount("buyer", 20_000)
    ledger.registerAccount(
        "seller",
        0,
        initialLongPositions={"SPCX": (10, 900)},
    )
    reserveOrder(
        ledger,
        orderId="buy",
        accountId="buyer",
        side=LedgerSide.BUY,
        quantity=10,
        limitPriceTicks=1_000,
    )
    reserveOrder(
        ledger,
        orderId="sell",
        accountId="seller",
        side=LedgerSide.SELL,
        quantity=10,
        limitPriceTicks=900,
    )

    ledger.applyTrade(
        buyOrderId="buy",
        sellOrderId="sell",
        priceTicks=950,
        quantity=4,
    )
    assert buyer.reservedCashCents == 6_000
    assert ledger.accounts["seller"].getPosition("SPCX").reservedQuantity == 6
    ledger.releaseOrder("buy")
    ledger.releaseOrder("sell")
    assert buyer.reservedCashCents == 0
    assert ledger.accounts["seller"].getPosition("SPCX").reservedQuantity == 0
    assert ledger.checkInvariants().isValid


def test_short_sale_borrow_margin_and_cover_are_accounted_for() -> None:
    ledger = PortfolioLedger(initialMarginRateBps=5_000)
    shortSeller = ledger.registerAccount("short-seller", 10_000)
    ledger.registerAccount("long-buyer", 20_000)
    ledger.configureBorrowPool("SPCX", 10)
    reserveOrder(
        ledger,
        orderId="open-short",
        accountId="short-seller",
        side=LedgerSide.SELL,
        quantity=5,
        limitPriceTicks=1_000,
        allowShortSelling=True,
    )
    reserveOrder(
        ledger,
        orderId="buy-short",
        accountId="long-buyer",
        side=LedgerSide.BUY,
        quantity=5,
        limitPriceTicks=1_000,
    )
    assert shortSeller.reservedCashCents == 2_500

    ledger.applyTrade(
        buyOrderId="buy-short",
        sellOrderId="open-short",
        priceTicks=1_000,
        quantity=5,
    )
    shortPosition = shortSeller.getPosition("SPCX")
    assert shortPosition.quantity == -5
    assert shortPosition.borrowedQuantity == 5
    assert shortPosition.marginUsedCents == 2_500
    assert ledger.borrowPools["SPCX"].borrowedQuantity == 5

    reserveOrder(
        ledger,
        orderId="cover",
        accountId="short-seller",
        side=LedgerSide.BUY,
        quantity=5,
        limitPriceTicks=900,
    )
    reserveOrder(
        ledger,
        orderId="sell-back",
        accountId="long-buyer",
        side=LedgerSide.SELL,
        quantity=5,
        limitPriceTicks=900,
    )
    ledger.applyTrade(
        buyOrderId="cover",
        sellOrderId="sell-back",
        priceTicks=900,
        quantity=5,
    )

    assert shortPosition.quantity == 0
    assert shortPosition.borrowedQuantity == 0
    assert shortPosition.marginUsedCents == 0
    assert shortPosition.realizedPnlCents == 500
    assert ledger.borrowPools["SPCX"].borrowedQuantity == 0
    assert ledger.checkInvariants().isValid


def test_risk_checks_modify_or_reject_orders_without_leaking_resources() -> None:
    ledger = PortfolioLedger(initialMarginRateBps=10_000)
    account = ledger.registerAccount("limited", 2_500)
    ledger.configureBorrowPool("SPCX", 2)

    buyResult = ledger.evaluateAndReserveOrder(
        orderId="large-buy",
        accountId="limited",
        instrumentId="SPCX",
        side=LedgerSide.BUY,
        quantity=10,
        limitPriceTicks=1_000,
        maxOrderQuantity=8,
        maxAbsolutePosition=20,
    )
    assert buyResult.decision is RiskDecision.MODIFY
    assert buyResult.approvedQuantity == 2
    assert len(buyResult.modifications) == 2
    ledger.releaseOrder("large-buy")

    shortResult = ledger.evaluateAndReserveOrder(
        orderId="short",
        accountId="limited",
        instrumentId="SPCX",
        side=LedgerSide.SELL,
        quantity=5,
        limitPriceTicks=1_000,
        maxOrderQuantity=10,
        maxAbsolutePosition=10,
        allowShortSelling=True,
    )
    assert shortResult.decision is RiskDecision.MODIFY
    assert shortResult.approvedQuantity == 2
    ledger.releaseOrder("short")

    rejected = ledger.evaluateAndReserveOrder(
        orderId="no-short",
        accountId="limited",
        instrumentId="SPCX",
        side=LedgerSide.SELL,
        quantity=1,
        limitPriceTicks=1_000,
        maxOrderQuantity=1,
        maxAbsolutePosition=10,
        allowShortSelling=False,
    )
    assert rejected.decision is RiskDecision.REJECT
    assert rejected.reservation is None
    assert account.reservedCashCents == 0
    assert ledger.checkInvariants().isValid


def test_invalid_trade_boundaries_and_tampering_are_detected() -> None:
    ledger = PortfolioLedger()
    ledger.registerAccount("buyer", 10_000)
    ledger.registerAccount(
        "seller",
        0,
        initialLongPositions={"SPCX": (2, 800)},
    )
    reserveOrder(
        ledger,
        orderId="buy",
        accountId="buyer",
        side=LedgerSide.BUY,
        quantity=2,
        limitPriceTicks=1_000,
    )
    reserveOrder(
        ledger,
        orderId="sell",
        accountId="seller",
        side=LedgerSide.SELL,
        quantity=2,
        limitPriceTicks=900,
    )

    with pytest.raises(ValueError, match="exceeds the buy limit"):
        ledger.applyTrade(
            buyOrderId="buy",
            sellOrderId="sell",
            priceTicks=1_001,
            quantity=1,
        )
    with pytest.raises(ValueError, match="exceeds buy reservation"):
        ledger.applyTrade(
            buyOrderId="buy",
            sellOrderId="sell",
            priceTicks=950,
            quantity=3,
        )

    ledger.accounts["buyer"].cashCents += 1
    report = ledger.checkInvariants()
    assert not report.cashConserved
    assert not report.isValid


def test_ledger_rejects_non_integer_inputs_without_sealing_configuration() -> None:
    with pytest.raises(TypeError, match="tradeFeeBps must be an integer"):
        PortfolioLedger(tradeFeeBps=0.5)  # type: ignore[arg-type]

    ledger = PortfolioLedger()
    ledger.registerAccount("first", 10_000)
    with pytest.raises(TypeError, match="side must be a LedgerSide"):
        ledger.evaluateAndReserveOrder(
            orderId="invalid-side",
            accountId="first",
            instrumentId="SPCX",
            side="BUY",  # type: ignore[arg-type]
            quantity=1,
            limitPriceTicks=1_000,
            maxOrderQuantity=1,
            maxAbsolutePosition=1,
        )
    # 无效请求不能把尚未启动的账本意外封存。
    ledger.registerAccount("second", 10_000)


def test_settlement_preflight_rejects_margin_shortfall_without_partial_writes() -> None:
    ledger = PortfolioLedger(tradeFeeBps=1_000, initialMarginRateBps=10_000)
    shortSeller = ledger.registerAccount("short-seller", 1_000)
    buyer = ledger.registerAccount("buyer", 30_000)
    ledger.configureBorrowPool("SPCX", 1)
    reserveOrder(
        ledger,
        orderId="short",
        accountId="short-seller",
        side=LedgerSide.SELL,
        quantity=1,
        limitPriceTicks=1_000,
        allowShortSelling=True,
    )
    reserveOrder(
        ledger,
        orderId="buy",
        accountId="buyer",
        side=LedgerSide.BUY,
        quantity=1,
        limitPriceTicks=20_000,
    )
    beforeSeller = (
        shortSeller.cashCents,
        shortSeller.reservedCashCents,
        shortSeller.getPosition("SPCX").quantity,
    )
    beforeBuyer = (buyer.cashCents, buyer.reservedCashCents)

    with pytest.raises(ValueError, match="seller available cash negative"):
        ledger.applyTrade(
            buyOrderId="buy",
            sellOrderId="short",
            priceTicks=20_000,
            quantity=1,
        )

    assert beforeSeller == (
        shortSeller.cashCents,
        shortSeller.reservedCashCents,
        shortSeller.getPosition("SPCX").quantity,
    )
    assert beforeBuyer == (buyer.cashCents, buyer.reservedCashCents)
    assert ledger.reservations["short"].remainingQuantity == 1
    assert ledger.reservations["buy"].remainingQuantity == 1
    assert ledger.checkInvariants().isValid
