"""Tests for app/services/executor.py — paper and live dispatch."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import Config
from app.exchanges.binance_rest import BinanceClient
from app.risk import RiskManager
from app.services.executor import TradeExecutor
from app.services.snapshot import SnapshotRow
from app.services.state_manager import MarketState
from app.strategy.momentum import MomentumStrategy


def _cfg(**overrides) -> Config:
    return Config().model_copy(update=overrides)


def _make_executor(paper_trade: bool = True, equity: float = 10_000.0, **cfg_overrides):
    cfg = _cfg(paper_trade=paper_trade, **cfg_overrides)
    client = MagicMock(spec=BinanceClient)
    risk = RiskManager(equity, cfg)
    strategy = MomentumStrategy(cfg)
    state = MarketState()

    executor = TradeExecutor(client, risk, strategy, state, cfg=cfg)
    executor.available_usdt = equity
    executor.equity = equity
    return executor, cfg


def _snapshot(symbol: str, price: float) -> SnapshotRow:
    return SnapshotRow(
        exchange="binance",
        symbol=symbol,
        snapshot_at=datetime.now(UTC),
        last_price=Decimal(str(price)),
        bid_price=Decimal(str(price * 0.9999)),
        ask_price=Decimal(str(price * 1.0001)),
    )


def _warm_up_strategy(executor: TradeExecutor, symbol: str, price: float, n: int = 30):
    for _ in range(n):
        executor._strategy.update(symbol, price)


# ── Paper fill slippage ────────────────────────────────────────────────────────


def test_paper_fill_buy_adds_slippage():
    executor, cfg = _make_executor(slippage_bps=10.0)
    # Use the default slippage (5 bps) since config singleton is not patched here
    fill = executor._paper_fill(100.0, "BUY")
    # Fill should be strictly above market price for a BUY
    assert fill > Decimal(100)


def test_paper_fill_sell_subtracts_slippage():
    executor, cfg = _make_executor(slippage_bps=10.0)
    fill = executor._paper_fill(100.0, "SELL")
    # Fill should be strictly below market price for a SELL
    assert fill < Decimal(100)


# ── Circuit-breaker ────────────────────────────────────────────────────────────


async def test_circuit_breaker_halts_buy():
    executor, cfg = _make_executor(max_drawdown_pct=0.10, equity=1000.0)
    executor._risk.update_equity(500.0)  # 50% drawdown → halted
    assert executor._risk.halted is True

    symbol = "BTCUSDT"
    _warm_up_strategy(executor, symbol, 100.0, 30)
    executor._strategy.notify_bought(symbol, 100.0)
    executor._strategy.notify_sold(symbol, was_loss=False)

    snapshots = {symbol: _snapshot(symbol, 100.0)}

    with (
        patch.object(executor, "_execute_buy", new_callable=AsyncMock) as mock_buy,
        patch.object(executor, "_execute_sell", new_callable=AsyncMock),
        patch("app.services.executor.DB.save_positions", new_callable=AsyncMock),
    ):
        await executor.process_all_ticks(snapshots)

    mock_buy.assert_not_called()


# ── Paper BUY persists order + trade ──────────────────────────────────────────


async def test_paper_buy_persists_records():
    executor, cfg = _make_executor(
        paper_trade=True,
        equity=10_000.0,
        base_position_pct=0.10,
        min_order_usdt=5.0,
        max_position_pct=1.0,
        reserve_pct=0.0,
    )

    symbol = "ETHUSDT"
    _warm_up_strategy(executor, symbol, 2000.0, 30)

    with (
        patch(
            "app.services.executor.DB.insert_order", new_callable=AsyncMock
        ) as mock_order,
        patch(
            "app.services.executor.DB.insert_trade", new_callable=AsyncMock
        ) as mock_trade,
        patch("app.services.executor.DB.save_positions", new_callable=AsyncMock),
    ):
        await executor._execute_buy(
            symbol=symbol,
            price=2000.0,
            indicators={"ema_sep_pct": 0.05, "rsi": 52.0, "roc": 2.0},
            volatility=1.0,
        )

    mock_order.assert_called_once()
    mock_trade.assert_called_once()

    # Verify order args
    order_kwargs = mock_order.call_args[1]
    assert order_kwargs["symbol"] == symbol
    assert order_kwargs["side"] == "BUY"
    assert order_kwargs["status"] == "FILLED"
    # Fill price should have slippage applied (higher than market)
    assert order_kwargs["average_fill_price"] > Decimal(2000)

    # Position should be recorded
    assert symbol in executor._positions


# ── Paper SELL removes position ────────────────────────────────────────────────


async def test_paper_sell_removes_position():
    executor, cfg = _make_executor(paper_trade=True)
    symbol = "SOLUSDT"
    executor._positions[symbol] = 100.0
    executor._strategy.notify_bought(symbol, 100.0)
    _warm_up_strategy(executor, symbol, 100.0, 30)

    with (
        patch("app.services.executor.DB.insert_order", new_callable=AsyncMock),
        patch("app.services.executor.DB.insert_trade", new_callable=AsyncMock),
        patch("app.services.executor.config", cfg),
    ):
        await executor._execute_sell(symbol, 105.0)
    assert symbol not in executor._positions


async def test_paper_sell_fill_price_has_slippage():
    executor, cfg = _make_executor(paper_trade=True, slippage_bps=20.0)
    symbol = "BNBUSDT"
    executor._positions[symbol] = 300.0
    executor._strategy.notify_bought(symbol, 300.0)
    _warm_up_strategy(executor, symbol, 300.0, 30)

    captured_fill = {}

    async def capture_order(**kwargs):
        captured_fill["price"] = kwargs.get("average_fill_price")

    with (
        patch("app.services.executor.DB.insert_order", side_effect=capture_order),
        patch("app.services.executor.DB.insert_trade", new_callable=AsyncMock),
        patch("app.services.executor.config", cfg),
    ):
        await executor._execute_sell(symbol, 300.0)
    # Sell fill should be below market price (slippage on sell)
    assert captured_fill["price"] < Decimal(300)


# ── Load / persist positions ───────────────────────────────────────────────────


def test_load_positions_restores_strategy_state():
    executor, _ = _make_executor()
    executor.load_positions({"BTCUSDT": 50000.0, "ETHUSDT": 3000.0})
    assert executor._positions == {"BTCUSDT": 50000.0, "ETHUSDT": 3000.0}
    assert executor._strategy._state("BTCUSDT").in_position is True
    assert executor._strategy._state("ETHUSDT").in_position is True
