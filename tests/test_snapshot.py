"""Tests for app/services/snapshot.py."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

from app.services.snapshot import collect_snapshots
from app.services.state_manager import MarketState


def _make_state() -> MarketState:
    ms = MarketState()
    # Instrument with prices set
    ms.initialize("binance", "btcusdt")
    ms.update_price("binance", "btcusdt", Decimal(50000))
    ms.update_book("binance", "btcusdt", Decimal(49999), Decimal(50001))
    # Instrument with no prices yet
    ms.initialize("binance", "ethusdt")
    return ms


def test_collect_snapshots_returns_only_priced_instruments():
    ms = _make_state()
    rows = collect_snapshots(ms)
    symbols = [r.symbol for r in rows]
    assert "btcusdt" in symbols
    assert "ethusdt" not in symbols


def test_collect_snapshots_correct_values():
    ms = _make_state()
    rows = collect_snapshots(ms)
    row = next(r for r in rows if r.symbol == "btcusdt")
    assert row.last_price == Decimal(50000)
    assert row.bid_price == Decimal(49999)
    assert row.ask_price == Decimal(50001)
    assert row.exchange == "binance"


def test_collect_snapshots_empty_state():
    ms = MarketState()
    assert collect_snapshots(ms) == []


def test_collect_snapshots_bid_ask_default_to_zero_when_none():
    ms = MarketState()
    ms.initialize("binance", "bnbusdt")
    ms.update_price("binance", "bnbusdt", Decimal(300))
    rows = collect_snapshots(ms)
    assert len(rows) == 1
    assert rows[0].bid_price == Decimal(0)
    assert rows[0].ask_price == Decimal(0)


async def test_write_snapshots_called_with_correct_data():
    ms = _make_state()
    snapshots = collect_snapshots(ms)

    with patch("app.data.writer.write_snapshots", new_callable=AsyncMock) as mock_write:
        await mock_write(snapshots)
        mock_write.assert_called_once_with(snapshots)
        args = mock_write.call_args[0][0]
        assert len(args) == 1
        assert args[0].symbol == "btcusdt"
