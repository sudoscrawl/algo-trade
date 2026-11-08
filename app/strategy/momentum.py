"""Momentum strategy — EMA crossover + RSI + Bollinger Bands + ATR + ROC.

Spot-only: signals are BUY, SELL, or HOLD.  No SHORT/COVER.
"""

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Literal

from app.config import Config

logger = logging.getLogger(__name__)

Signal = Literal["BUY", "SELL", "HOLD"]


# ── Technical indicator functions (pure, no side-effects) ─────────────────────


def ema(prices: list[float], period: int) -> float:
    """Exponential moving average over *prices*."""
    if len(prices) < period:
        return float("nan")
    multiplier = 2 / (period + 1)
    result = prices[0]
    for price in prices[1:]:
        result = price * multiplier + result * (1 - multiplier)
    return result


def rsi(prices: list[float], period: int) -> float:
    """Relative Strength Index using Wilder's smoothed moving average."""
    if len(prices) < period + 1:
        return 50.0

    changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

    # Seed with simple average over the first `period` changes.
    avg_gain = sum(c for c in changes[:period] if c > 0) / period
    avg_loss = sum(-c for c in changes[:period] if c < 0) / period

    # Wilder smoothing over the remaining changes.
    for change in changes[period:]:
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1 + rs)


def bollinger_bands(
    prices: list[float], period: int, num_std: float = 2.0
) -> tuple[float, float, float]:
    """Return (upper, middle, lower) Bollinger Bands."""
    if len(prices) < period:
        return float("nan"), float("nan"), float("nan")
    window = prices[-period:]
    middle = sum(window) / period
    variance = sum((p - middle) ** 2 for p in window) / period
    std = math.sqrt(variance)
    return middle + num_std * std, middle, middle - num_std * std


def atr(prices: list[float], period: int) -> float:
    """Simplified ATR using close-to-close ranges."""
    if len(prices) < period + 1:
        return 0.0
    true_ranges = [abs(prices[i] - prices[i - 1]) for i in range(-period, 0)]
    return sum(true_ranges) / len(true_ranges)


def rate_of_change(prices: list[float], period: int) -> float:
    """Price rate of change over *period* bars, as a percentage."""
    if len(prices) < period + 1 or prices[-(period + 1)] == 0:
        return 0.0
    return (prices[-1] - prices[-(period + 1)]) / prices[-(period + 1)] * 100


# ── Per-symbol state ──────────────────────────────────────────────────────────


@dataclass
class PairState:
    prices: deque[float] = field(default_factory=lambda: deque(maxlen=300))

    entry_price: float = 0.0
    hold_cycles: int = 0
    trailing_high: float = 0.0

    ticks_above_slow: int = 0
    ticks_below_slow: int = 0

    cooldown_cycles: int = 0
    restored: bool = False

    @property
    def in_position(self) -> bool:
        return self.entry_price > 0.0


# ── Strategy ──────────────────────────────────────────────────────────────────


class MomentumStrategy:
    def __init__(self, settings: Config) -> None:
        self.settings = settings
        self._states: dict[str, PairState] = {}

    def _state(self, symbol: str) -> PairState:
        return self._states.setdefault(symbol, PairState())

    # ── Lifecycle notifications ───────────────────────────────────────────────

    def restore(self, symbol: str, prices: list[float]) -> None:
        """Warm up the price window from historical DB data on startup."""
        state = self._state(symbol)
        state.prices.extend(p for p in reversed(prices) if p > 0)
        state.restored = True

    def notify_bought(self, symbol: str, price: float) -> None:
        state = self._state(symbol)
        state.entry_price = price
        state.hold_cycles = 0
        state.trailing_high = price

    def notify_sold(self, symbol: str, was_loss: bool) -> None:
        state = self._state(symbol)
        state.entry_price = 0.0
        state.hold_cycles = 0
        state.trailing_high = 0.0
        if was_loss:
            state.cooldown_cycles = self.settings.loss_cooldown_cycles

    # ── Indicator snapshot (used by executor for scoring) ─────────────────────

    def indicators(self, symbol: str) -> dict[str, Any]:
        state = self._state(symbol)
        prices = list(state.prices)
        cfg = self.settings
        if len(prices) < cfg.min_history:
            return {"warming_up": True}
        fast = ema(prices, cfg.fast_ema_period)
        slow = ema(prices, cfg.slow_ema_period)
        current_rsi = rsi(prices, cfg.rsi_period)
        separation = (fast - slow) / slow * 100 if slow > 0 else 0.0
        return {
            "warming_up": False,
            "fast_ema": fast,
            "slow_ema": slow,
            "rsi": current_rsi,
            "ema_sep_pct": separation,
            "atr": atr(prices, cfg.atr_period),
            "roc": rate_of_change(prices, cfg.roc_period),
        }

    # ── Core signal generation ────────────────────────────────────────────────

    def update(self, symbol: str, price: float) -> Signal:
        if price <= 0:
            return "HOLD"

        state, cfg = self._state(symbol), self.settings
        state.prices.append(price)
        prices = list(state.prices)

        if len(prices) < cfg.min_history:
            return "HOLD"

        # One-tick "restored" guard: skip the first evaluation after a restore
        # so stale indicator windows don't produce phantom signals.
        if state.restored:
            state.restored = False
            return "HOLD"

        # ── Compute indicators ────────────────────────────────────────────────
        fast = ema(prices, cfg.fast_ema_period)
        slow = ema(prices, cfg.slow_ema_period)
        prev_fast = ema(prices[:-1], cfg.fast_ema_period)
        prev_slow = ema(prices[:-1], cfg.slow_ema_period)
        current_rsi = rsi(prices, cfg.rsi_period)
        bb_upper, _bb_mid, bb_lower = bollinger_bands(prices, cfg.bb_period, cfg.bb_std)
        roc = rate_of_change(prices, cfg.roc_period)
        separation = (fast - slow) / slow * 100 if slow > 0 else 0.0

        if fast > slow:
            state.ticks_above_slow += 1
            state.ticks_below_slow = 0
        else:
            state.ticks_below_slow += 1
            state.ticks_above_slow = 0

        state.cooldown_cycles = max(0, state.cooldown_cycles - 1)

        # ── SELL path (exit long position) ────────────────────────────────────
        if state.in_position:
            state.hold_cycles += 1
            state.trailing_high = max(state.trailing_high, price)
            pnl = (price - state.entry_price) / state.entry_price * 100

            # 1. Hard take-profit
            if pnl >= cfg.take_profit_pct:
                logger.info("%s TAKE-PROFIT pnl=%.2f%%", symbol, pnl)
                return "SELL"

            # 2. Hard stop-loss
            if pnl <= -cfg.stop_loss_pct:
                logger.warning("%s STOP-LOSS pnl=%.2f%%", symbol, pnl)
                return "SELL"

            # 3. Trailing stop — only activates once we're profitable enough
            if state.trailing_high > 0:
                trail_pnl = (
                    (state.trailing_high - state.entry_price) / state.entry_price * 100
                )
                if trail_pnl >= cfg.trailing_activate_pct:
                    drawdown = (state.trailing_high - price) / state.trailing_high * 100
                    if drawdown >= cfg.trailing_stop_pct:
                        logger.info(
                            "%s TRAILING-STOP peak_pnl=%.2f%% drawdown=%.2f%%",
                            symbol,
                            trail_pnl,
                            drawdown,
                        )
                        return "SELL"

            # 4. EMA bearish crossover — only exit when position is profitable
            if (
                prev_fast >= prev_slow
                and fast < slow
                and current_rsi >= cfg.rsi_sell_min
                and state.hold_cycles >= cfg.min_hold_cycles
                and pnl > 0
            ):
                logger.info(
                    "%s EMA-CROSSDOWN EXIT pnl=%.2f%% rsi=%.1f",
                    symbol,
                    pnl,
                    current_rsi,
                )
                return "SELL"

            # 5. Stagnant exit — trade not working, EMA turned against us
            if (
                state.hold_cycles >= cfg.stagnant_exit_cycles
                and state.ticks_below_slow >= 2
                and pnl < cfg.min_profit_pct
            ):
                logger.info(
                    "%s STAGNANT EXIT pnl=%.2f%% cycles=%d",
                    symbol,
                    pnl,
                    state.hold_cycles,
                )
                return "SELL"

            return "HOLD"

        # ── BUY path (enter long position) ────────────────────────────────────
        if state.cooldown_cycles > 0:
            return "HOLD"

        crossed_up = prev_fast <= prev_slow and fast > slow
        rsi_ok = cfg.rsi_buy_min <= current_rsi <= cfg.rsi_buy_max
        separation_ok = separation >= cfg.ema_separation_pct
        roc_ok = roc >= cfg.roc_buy_threshold
        confirmed = state.ticks_above_slow >= cfg.confirm_ticks

        # Bollinger lower-band touch adds conviction for mean-reversion entries
        bb_entry = price <= bb_lower if bb_lower == bb_lower else False  # nan guard

        if crossed_up and rsi_ok and (separation_ok or bb_entry):
            logger.info(
                "%s BUY SIGNAL rsi=%.1f sep=%.3f%% roc=%.2f%%",
                symbol,
                current_rsi,
                separation,
                roc,
            )
            return "BUY"

        if confirmed and rsi_ok and separation_ok and roc_ok:
            logger.info(
                "%s BUY CONFIRMED rsi=%.1f sep=%.3f%% roc=%.2f%%",
                symbol,
                current_rsi,
                separation,
                roc,
            )
            return "BUY"

        logger.debug(
            "%s HOLD  price=%.4f  fast=%.4f  slow=%.4f  sep=%.4f%%  "
            "rsi=%.1f  roc=%.3f  ticks_above=%d  crossed_up=%s  "
            "rsi_ok=%s  sep_ok=%s  roc_ok=%s  confirmed=%s  bb_entry=%s",
            symbol,
            price,
            fast,
            slow,
            separation,
            current_rsi,
            roc,
            state.ticks_above_slow,
            crossed_up,
            rsi_ok,
            separation_ok,
            roc_ok,
            confirmed,
            bb_entry,
        )
        return "HOLD"
