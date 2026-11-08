"""Position sizing and portfolio circuit-breaker."""

from math import floor

from app.config import Config


class RiskManager:
    def __init__(self, initial_equity: float, settings: Config) -> None:
        self.settings = settings
        self.peak_equity = initial_equity
        self.halted = False

    def update_equity(self, equity: float) -> None:
        """Update peak equity and check drawdown circuit-breaker."""
        self.peak_equity = max(self.peak_equity, equity)
        if equity > 0 and self.peak_equity > 0:
            drawdown = (self.peak_equity - equity) / self.peak_equity
            self.halted = drawdown >= self.settings.max_drawdown_pct

    def size_usdt(
        self,
        available_usdt: float,
        equity: float,
        signal_strength: float,
        volatility_pct: float,
    ) -> float:
        """
        Return the USDT amount to allocate to a position.

        Scales with signal conviction and shrinks under high volatility.
        Returns 0 when the circuit-breaker is active or equity is zero.
        """
        if self.halted or equity <= 0:
            return 0.0

        cfg = self.settings
        # Conviction: 0.80 base, up to 1.30 at max signal strength.
        conviction = 0.80 + min(max(signal_strength, 0.0), 1.0) * 0.50
        # Volatility adjustment: reduces size as volatility rises.
        vol_adj = max(0.45, 1 / (1 + max(volatility_pct, 0.0) * 0.25))

        size = equity * cfg.base_position_pct * conviction * vol_adj
        size = min(
            size,
            equity * cfg.max_position_pct,
            available_usdt * (1 - cfg.reserve_pct),
        )
        return size if size >= cfg.min_order_usdt else 0.0

    def quantity(self, usdt_amount: float, price: float, precision: int) -> float:
        """Convert a USDT budget to base-asset quantity, floored to *precision* decimals."""
        if price <= 0:
            return 0.0
        raw = usdt_amount / (price * (1 + self.settings.commission_rate))
        factor = 10**precision
        return floor(raw * factor) / factor
