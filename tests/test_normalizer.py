"""Tests for app/services/normalizer.py and app/services/state_manager.py."""

from decimal import Decimal

import pytest

from app.services.normalizer import BookUpdate, TradeUpdate, normalize
from app.services.state_manager import MarketState

# ── normalize() ──────────────────────────────────────────────────────────────

TRADE_PAYLOAD = {
    "e": "trade",
    "s": "BTCUSDT",
    "p": "50000.12345678",
    "q": "0.00100000",
    "T": 1700000000000,
}

BOOK_PAYLOAD = {
    "s": "ETHUSDT",
    "b": "2000.50000000",
    "B": "5.00000000",
    "a": "2001.00000000",
    "A": "3.00000000",
    "u": 123456,
}

COMBINED_TRADE_PAYLOAD = {
    "stream": "btcusdt@trade",
    "data": TRADE_PAYLOAD,
}

COMBINED_BOOK_PAYLOAD = {
    "stream": "ethusdt@bookTicker",
    "data": BOOK_PAYLOAD,
}


def test_normalize_trade_event():
    event = normalize(TRADE_PAYLOAD, "binance")
    assert isinstance(event, TradeUpdate)
    assert event.exchange == "binance"
    assert event.symbol == "btcusdt"
    assert event.price == Decimal("50000.12345678")
    assert event.quantity == Decimal("0.00100000")


def test_normalize_book_event():
    event = normalize(BOOK_PAYLOAD, "binance")
    assert isinstance(event, BookUpdate)
    assert event.exchange == "binance"
    assert event.symbol == "ethusdt"
    assert event.bid_price == Decimal("2000.50000000")
    assert event.ask_price == Decimal("2001.00000000")
    assert event.bid_qty == Decimal("5.00000000")
    assert event.ask_qty == Decimal("3.00000000")


def test_normalize_combined_stream_trade():
    event = normalize(COMBINED_TRADE_PAYLOAD, "binance")
    assert isinstance(event, TradeUpdate)
    assert event.symbol == "btcusdt"


def test_normalize_combined_stream_book():
    event = normalize(COMBINED_BOOK_PAYLOAD, "binance")
    assert isinstance(event, BookUpdate)
    assert event.symbol == "ethusdt"


def test_normalize_unknown_payload_raises():
    with pytest.raises(ValueError, match="Unknown"):
        normalize({"unexpected": "payload"}, "binance")


# ── MarketState ───────────────────────────────────────────────────────────────


def test_market_state_apply_trade_update():
    ms = MarketState()
    ms.initialize("binance", "btcusdt")
    trade = normalize(TRADE_PAYLOAD, "binance")
    ms.apply_change(trade)
    state = ms.instruments[("binance", "btcusdt")]
    assert state.last_price == Decimal("50000.12345678")


def test_market_state_apply_book_update():
    ms = MarketState()
    ms.initialize("binance", "ethusdt")
    book = normalize(BOOK_PAYLOAD, "binance")
    ms.apply_change(book)
    state = ms.instruments[("binance", "ethusdt")]
    assert state.bid_price == Decimal("2000.50000000")
    assert state.ask_price == Decimal("2001.00000000")


def test_market_state_auto_creates_instrument_on_update():
    """An instrument not explicitly initialized is created on first update."""
    ms = MarketState()
    trade = normalize(TRADE_PAYLOAD, "binance")
    ms.apply_change(trade)
    assert ("binance", "btcusdt") in ms.instruments


def test_market_state_initialize_sets_none_for_zero_prices():
    ms = MarketState()
    ms.initialize("binance", "btcusdt")
    state = ms.instruments[("binance", "btcusdt")]
    assert state.last_price is None
    assert state.bid_price is None
    assert state.ask_price is None
