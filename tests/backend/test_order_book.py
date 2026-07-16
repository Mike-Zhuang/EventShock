import pytest

from backend.app.simulation.order_book import LimitOrderBook, Side, TimeInForce


def test_price_priority_beats_arrival_order() -> None:
    orderBook = LimitOrderBook("TEST")
    orderBook.submitLimit(
        orderId="ask-worse",
        agentId="seller-a",
        side=Side.SELL,
        priceTicks=102,
        quantity=2,
        step=0,
    )
    orderBook.submitLimit(
        orderId="ask-better",
        agentId="seller-b",
        side=Side.SELL,
        priceTicks=101,
        quantity=2,
        step=1,
    )

    report = orderBook.submitLimit(
        orderId="buy",
        agentId="buyer",
        side=Side.BUY,
        priceTicks=102,
        quantity=3,
        step=2,
        timeInForce=TimeInForce.IOC,
    )

    assert [trade.priceTicks for trade in report.trades] == [101, 102]
    assert [trade.quantity for trade in report.trades] == [2, 1]


def test_time_priority_and_partial_fill_preserve_remainder() -> None:
    orderBook = LimitOrderBook("TEST")
    orderBook.submitLimit(
        orderId="first",
        agentId="seller-first",
        side=Side.SELL,
        priceTicks=101,
        quantity=4,
        step=0,
    )
    orderBook.submitLimit(
        orderId="second",
        agentId="seller-second",
        side=Side.SELL,
        priceTicks=101,
        quantity=4,
        step=0,
    )

    report = orderBook.submitLimit(
        orderId="buy",
        agentId="buyer",
        side=Side.BUY,
        priceTicks=101,
        quantity=5,
        step=1,
        timeInForce=TimeInForce.IOC,
    )

    assert [trade.sellerAgentId for trade in report.trades] == ["seller-first", "seller-second"]
    assert [trade.quantity for trade in report.trades] == [4, 1]
    assert orderBook.orderIndex["second"].remainingQuantity == 3


def test_protected_market_order_cancels_quantity_outside_collar() -> None:
    orderBook = LimitOrderBook("TEST")
    orderBook.submitLimit(
        orderId="inside",
        agentId="seller-inside",
        side=Side.SELL,
        priceTicks=101,
        quantity=2,
        step=0,
    )
    orderBook.submitLimit(
        orderId="outside",
        agentId="seller-outside",
        side=Side.SELL,
        priceTicks=110,
        quantity=8,
        step=0,
    )

    report = orderBook.submitProtectedMarket(
        orderId="protected-buy",
        agentId="buyer",
        side=Side.BUY,
        quantity=7,
        referencePriceTicks=100,
        collarBps=200,
        step=1,
    )

    assert sum(trade.quantity for trade in report.trades) == 2
    assert report.protectedUnfilledQuantity == 5
    assert report.status == "PARTIALLY_FILLED_CANCELLED"


def test_filled_or_cancelled_order_id_cannot_be_reused() -> None:
    orderBook = LimitOrderBook("TEST")
    orderBook.submitLimit(
        orderId="once-only",
        agentId="buyer",
        side=Side.BUY,
        priceTicks=99,
        quantity=1,
        step=0,
        timeInForce=TimeInForce.IOC,
    )

    try:
        orderBook.submitLimit(
            orderId="once-only",
            agentId="buyer",
            side=Side.BUY,
            priceTicks=99,
            quantity=1,
            step=1,
        )
    except ValueError as error:
        assert "duplicate orderId" in str(error)
    else:
        raise AssertionError("historical order IDs must remain unique")


def test_configured_tick_grid_rejects_off_grid_prices() -> None:
    orderBook = LimitOrderBook("TEST", tickSizeTicks=5)
    orderBook.submitLimit(
        orderId="aligned",
        agentId="buyer",
        side=Side.BUY,
        priceTicks=100,
        quantity=1,
        step=0,
    )

    with pytest.raises(ValueError, match="configured tick grid"):
        orderBook.submitLimit(
            orderId="off-grid",
            agentId="buyer",
            side=Side.BUY,
            priceTicks=101,
            quantity=1,
            step=0,
        )
