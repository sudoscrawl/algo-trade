"""Tests for app/risk.py — RiskManager."""


from app.config import Config
from app.risk import RiskManager


def _cfg(**overrides) -> Config:
    return Config().model_copy(update=overrides)


def _risk(equity: float = 1000.0, **cfg_overrides) -> RiskManager:
    return RiskManager(equity, _cfg(**cfg_overrides))


# ── Circuit-breaker ───────────────────────────────────────────────────────────


def test_drawdown_halts_trading():
    r = _risk(equity=1000.0, max_drawdown_pct=0.10)
    r.update_equity(800.0)  # 20% drawdown — exceeds 10% threshold
    assert r.halted is True


def test_drawdown_within_limit_does_not_halt():
    r = _risk(equity=1000.0, max_drawdown_pct=0.20)
    r.update_equity(900.0)  # 10% drawdown — within limit
    assert r.halted is False


def test_peak_equity_is_tracked():
    r = _risk(equity=1000.0)
    r.update_equity(1200.0)
    assert r.peak_equity == 1200.0
    r.update_equity(1100.0)
    assert r.peak_equity == 1200.0  # peak doesn't go down


def test_halted_size_returns_zero():
    r = _risk(equity=1000.0, max_drawdown_pct=0.10)
    r.update_equity(500.0)
    assert r.halted is True
    assert r.size_usdt(1000.0, 1000.0, 0.5, 1.0) == 0.0


# ── Position sizing ───────────────────────────────────────────────────────────


def test_size_zero_equity_returns_zero():
    r = _risk(equity=0.0)
    assert r.size_usdt(1000.0, 0.0, 0.5, 1.0) == 0.0


def test_size_respects_max_position_pct():
    r = _risk(
        equity=10000.0,
        max_position_pct=0.10,
        base_position_pct=0.20,  # higher than max — should be capped
        min_order_usdt=1.0,
        reserve_pct=0.0,
    )
    size = r.size_usdt(10000.0, 10000.0, 1.0, 0.0)
    assert size <= 10000.0 * 0.10


def test_size_respects_available_usdt():
    r = _risk(
        equity=10000.0,
        base_position_pct=0.50,  # would want 50% of equity
        max_position_pct=1.0,
        reserve_pct=0.0,
        min_order_usdt=1.0,
    )
    available = 500.0
    size = r.size_usdt(available, 10000.0, 1.0, 0.0)
    assert size <= available


def test_size_below_min_order_returns_zero():
    r = _risk(
        equity=100.0,
        base_position_pct=0.001,
        min_order_usdt=50.0,
        max_position_pct=1.0,
        reserve_pct=0.0,
    )
    size = r.size_usdt(100.0, 100.0, 1.0, 0.0)
    assert size == 0.0


# ── Quantity calculation ──────────────────────────────────────────────────────


def test_quantity_floors_to_precision():
    r = _risk(equity=1000.0, commission_rate=0.0)
    # 100 / 33.3 = 3.003003... → floored to 2 decimals → 3.0
    qty = r.quantity(usdt_amount=100.0, price=33.3, precision=2)
    assert qty == 3.0
    # 100 / 33.4 = 2.994011... → floored to 2 decimals → 2.99
    qty2 = r.quantity(usdt_amount=100.0, price=33.4, precision=2)
    assert qty2 == 2.99


def test_quantity_zero_price_returns_zero():
    r = _risk()
    assert r.quantity(100.0, 0.0, 6) == 0.0


def test_quantity_accounts_for_commission():
    r = _risk(equity=1000.0, commission_rate=0.001)
    qty_with = r.quantity(100.0, 100.0, 6)
    r2 = _risk(equity=1000.0, commission_rate=0.0)
    qty_without = r2.quantity(100.0, 100.0, 6)
    assert qty_with < qty_without
