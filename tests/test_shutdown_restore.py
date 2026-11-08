"""Tests for startup restore and validate_live_execution guard."""

import pytest

from app.config import Config
from app.strategy.momentum import MomentumStrategy


def _cfg(**overrides) -> Config:
    return Config().model_copy(update=overrides)


# ── validate_live_execution ───────────────────────────────────────────────────


def test_validate_live_passes_in_paper_mode():
    cfg = _cfg(paper_trade=True)
    cfg.validate_live_execution()  # must not raise


def test_validate_live_raises_without_interlock():
    cfg = _cfg(
        paper_trade=False, live_trading_enabled=False, api_key="k", api_secret="s"
    )
    with pytest.raises(RuntimeError, match="LIVE_TRADING_ENABLED"):
        cfg.validate_live_execution()


def test_validate_live_raises_without_credentials():
    cfg = _cfg(paper_trade=False, live_trading_enabled=True, api_key="", api_secret="")
    with pytest.raises(RuntimeError, match="API_KEY"):
        cfg.validate_live_execution()


def test_validate_live_passes_with_all_set():
    cfg = _cfg(
        paper_trade=False, live_trading_enabled=True, api_key="k", api_secret="s"
    )
    cfg.validate_live_execution()


# ── Strategy restore guard ────────────────────────────────────────────────────


def test_first_update_after_restore_returns_hold():
    """After notify_bought + restore, the first update() must return HOLD."""
    cfg = _cfg(min_history=5)
    strategy = MomentumStrategy(cfg)

    # Warm up with 30 prices
    prices = [100.0 + i * 0.1 for i in range(30)]
    strategy.notify_bought("BTCUSDT", 100.0)
    strategy.restore("BTCUSDT", prices)

    # First tick after restore must not generate a phantom signal
    result = strategy.update("BTCUSDT", 103.0)
    assert result == "HOLD"


def test_strategy_evaluates_normally_after_restore_guard_clears():
    cfg = _cfg(min_history=5, stop_loss_pct=2.0)
    strategy = MomentumStrategy(cfg)

    prices = [100.0] * 30
    strategy.notify_bought("BTCUSDT", 100.0)
    strategy.restore("BTCUSDT", prices)

    strategy.update("BTCUSDT", 100.0)  # consume restore guard
    # Now a severe drop should trigger stop-loss
    result = strategy.update("BTCUSDT", 95.0)  # 5% drop > 2% stop-loss
    assert result == "SELL"
