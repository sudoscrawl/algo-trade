"""Comprehensive tests for MomentumStrategy."""


from app.config import Config
from app.strategy.momentum import (
    MomentumStrategy,
    atr,
    bollinger_bands,
    ema,
    rate_of_change,
    rsi,
)


def _cfg(**overrides) -> Config:
    return Config().model_copy(update=overrides)


def _strategy(**cfg_overrides) -> MomentumStrategy:
    return MomentumStrategy(_cfg(**cfg_overrides))


def _warm_up(strategy: MomentumStrategy, symbol: str, price: float, n: int) -> None:
    """Feed *n* identical prices to warm up the indicator window."""
    for _ in range(n):
        strategy.update(symbol, price)


# ── Indicator unit tests ──────────────────────────────────────────────────────


def test_ema_insufficient_data_returns_nan():
    import math

    assert math.isnan(ema([1.0, 2.0], period=5))


def test_ema_flat_series():
    result = ema([100.0] * 10, period=5)
    assert abs(result - 100.0) < 0.01


def test_rsi_insufficient_returns_50():
    assert rsi([1.0, 2.0], period=14) == 50.0


def test_rsi_all_gains_returns_100():
    prices = list(range(1, 20))
    assert rsi(prices, period=14) == 100.0


def test_bollinger_bands_flat_series():
    prices = [100.0] * 20
    upper, middle, lower = bollinger_bands(prices, period=20)
    assert abs(middle - 100.0) < 0.01
    assert abs(upper - lower) < 0.01  # zero std → bands collapse to middle


def test_atr_returns_zero_insufficient_data():
    assert atr([100.0], period=14) == 0.0


def test_rate_of_change_flat_series():
    prices = [100.0] * 15
    assert rate_of_change(prices, period=10) == 0.0


# ── Warmup guard ──────────────────────────────────────────────────────────────


def test_warmup_guard_holds_until_min_history():
    s = _strategy(min_history=5)
    # Feed 4 prices — should all be HOLD (not enough history)
    for i in range(4):
        assert s.update("BTC", float(100 + i)) == "HOLD"


# ── Hard stop-loss ────────────────────────────────────────────────────────────


def test_stop_loss_triggers_sell():
    s = _strategy(stop_loss_pct=2.0, min_history=5)
    _warm_up(s, "BTC", 100.0, 30)
    s.notify_bought("BTC", 100.0)
    # Price drops 3% — past the 2% stop
    result = s.update("BTC", 97.0)
    assert result == "SELL"


# ── Hard take-profit ──────────────────────────────────────────────────────────


def test_take_profit_triggers_sell():
    s = _strategy(take_profit_pct=3.0, min_history=5)
    _warm_up(s, "BTC", 100.0, 30)
    s.notify_bought("BTC", 100.0)
    result = s.update("BTC", 104.0)
    assert result == "SELL"


# ── Trailing stop ─────────────────────────────────────────────────────────────


def test_trailing_stop_does_not_trigger_before_activation():
    s = _strategy(trailing_activate_pct=2.0, trailing_stop_pct=1.0, min_history=5)
    _warm_up(s, "BTC", 100.0, 30)
    s.notify_bought("BTC", 100.0)
    # Only 1% gain — trailing not activated yet
    s.update("BTC", 101.0)
    result = s.update("BTC", 100.5)
    assert result == "HOLD"


def test_trailing_stop_triggers_after_activation():
    s = _strategy(
        trailing_activate_pct=2.0,
        trailing_stop_pct=1.0,
        take_profit_pct=99.0,  # disable hard TP
        stop_loss_pct=99.0,  # disable hard SL
        min_history=5,
        min_hold_cycles=0,
    )
    _warm_up(s, "BTC", 100.0, 30)
    s.notify_bought("BTC", 100.0)
    # Push price up 3% — activates trailing (threshold is 2%)
    s._state("BTC").trailing_high = 103.0
    # Now drop back 1.5% from the high
    result = s.update("BTC", 101.45)
    assert result == "SELL"


# ── Restore guard ─────────────────────────────────────────────────────────────


def test_restore_guard_holds_on_first_tick_after_restore():
    s = _strategy(min_history=5)
    prices = [100.0] * 30
    s.restore("BTC", prices)
    # First tick after restore should be HOLD regardless of price
    result = s.update("BTC", 100.0)
    assert result == "HOLD"


def test_restore_guard_clears_after_first_tick():
    s = _strategy(min_history=5)
    s.restore("BTC", [100.0] * 30)
    s.update("BTC", 100.0)  # consume the restore guard
    # State should now evaluate normally (not stuck in restored=True)
    assert s._state("BTC").restored is False


# ── Stagnant exit ─────────────────────────────────────────────────────────────


def test_stagnant_exit_triggers():
    s = _strategy(
        stagnant_exit_cycles=3,
        min_profit_pct=1.0,
        stop_loss_pct=99.0,
        take_profit_pct=99.0,
        min_history=5,
        slow_ema_period=5,
        fast_ema_period=3,
    )
    # Warm up with a declining price series so fast EMA stays below slow EMA.
    declining = [100.0 - i * 0.5 for i in range(30)]
    for p in declining:
        s.update("BTC", p)
    s.notify_bought("BTC", 85.5)
    state = s._state("BTC")
    # Manually set hold_cycles to just below the trigger so update() tips it over.
    state.hold_cycles = 2
    # After 30 declining prices, fast EMA should already be below slow EMA,
    # so ticks_below_slow should be > 0.  Force it to meet the threshold.
    state.ticks_below_slow = 2
    # Continue declining — still below min_profit_pct relative to entry
    result = s.update("BTC", 85.4)
    assert result == "SELL"


# ── notify_sold / cooldown ────────────────────────────────────────────────────


def test_notify_sold_clears_position():
    s = _strategy(min_history=5)
    s.notify_bought("BTC", 100.0)
    assert s._state("BTC").in_position is True
    s.notify_sold("BTC", was_loss=False)
    assert s._state("BTC").in_position is False


def test_notify_sold_with_loss_sets_cooldown():
    s = _strategy(loss_cooldown_cycles=5, min_history=5)
    s.notify_bought("BTC", 100.0)
    s.notify_sold("BTC", was_loss=True)
    assert s._state("BTC").cooldown_cycles == 5


def test_cooldown_prevents_buy_signal():
    s = _strategy(loss_cooldown_cycles=10, min_history=5)
    _warm_up(s, "BTC", 100.0, 30)
    s.notify_bought("BTC", 100.0)
    s.notify_sold("BTC", was_loss=True)
    result = s.update("BTC", 100.0)
    assert result == "HOLD"
