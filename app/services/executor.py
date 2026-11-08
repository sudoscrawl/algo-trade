"""Trade executor — dispatches strategy signals to paper or live order execution."""

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.config import config
from app.data.queries import DB
from app.exchanges.binance_rest import BinanceClient
from app.risk import RiskManager
from app.services.snapshot import SnapshotRow
from app.services.state_manager import MarketState
from app.strategy.momentum import MomentumStrategy

logger = logging.getLogger(__name__)


def _signal_strength(indicators: dict[str, Any]) -> float:
    """Map indicator values to a 0–1 signal strength score for position sizing."""
    separation = abs(float(indicators.get("ema_sep_pct", 0.0)))
    rsi_value = float(indicators.get("rsi", 50.0))
    return min(
        1.0, separation / 0.12 * 0.6 + max(0.0, 1 - abs(rsi_value - 52) / 20) * 0.4
    )


def _volatility_pct(prices: list[float]) -> float:
    """Estimate recent volatility as mean absolute return."""
    if len(prices) < 3:
        return 1.0
    recent = prices[-12:]
    returns = [
        abs(recent[i] / recent[i - 1] - 1) * 100
        for i in range(1, len(recent))
        if recent[i - 1] > 0
    ]
    return sum(returns) / len(returns) if returns else 1.0


def _score_opportunity(indicators: dict[str, Any], volatility: float) -> float:
    """Score a BUY signal for candidate ranking (higher = better opportunity)."""
    if indicators.get("warming_up", False):
        return 0.0

    ema_sep = max(0.0, float(indicators.get("ema_sep_pct", 0.0)))
    rsi_val = float(indicators.get("rsi", 50.0))
    roc = float(indicators.get("roc", 0.0))

    trend = max(0.1, 1.0 + ema_sep * 10.0)
    rsi_factor = max(0.1, 1.0 - abs(rsi_val - 55.0) / 30.0)
    roc_factor = max(0.2, 1.0 + roc / 10.0)
    vol_factor = min(2.0, max(0.6, volatility / 1.2))

    return round(max(0.0, trend * rsi_factor * roc_factor * vol_factor), 4)


class TradeExecutor:
    """
    Evaluates strategy signals for each symbol on every scheduler tick and
    executes orders via the paper or live path.

    Paper path  (PAPER_TRADE=true):  synthetic fill with configurable slippage.
    Live path   (PAPER_TRADE=false): Binance REST API via BinanceClient.
    """

    def __init__(
        self,
        client: BinanceClient,
        risk: RiskManager,
        strategy: MomentumStrategy,
        state: MarketState,
        cfg=None,
    ) -> None:
        self._client = client
        self._risk = risk
        self._strategy = strategy
        self._state = state
        self._config = cfg if cfg is not None else config
        # In-memory position cache keyed by symbol (entry price as float).
        self._positions: dict[str, float] = {}
        # Quantity held per symbol (paper trade tracking).
        self._quantities: dict[str, float] = {}
        # Available USDT balance (refreshed each tick via live or estimated paper).
        self.available_usdt: float = 0.0
        self.equity: float = 0.0

    # ── Position state ────────────────────────────────────────────────────────

    def load_positions(self, positions: dict[str, float]) -> None:
        """Restore positions from DB on startup."""
        self._positions = dict(positions)
        for symbol, entry_price in positions.items():
            self._strategy.notify_bought(symbol, entry_price)

    async def persist_positions(self) -> None:
        await DB.save_positions(self._positions)

    # ── Main tick ─────────────────────────────────────────────────────────────

    async def process_tick(self, symbol: str, snapshot: SnapshotRow) -> None:
        """
        Evaluate strategy for *symbol* using the latest snapshot price and
        execute BUY or SELL if signalled.
        """
        price = float(snapshot.last_price)
        if price <= 0:
            return

        signal = self._strategy.update(symbol, price)

        # ── SELL ─────────────────────────────────────────────────────────────
        if signal == "SELL" and symbol in self._positions:
            await self._execute_sell(symbol, price)
            return

        # ── BUY candidates — collected and ranked in process_all_ticks ───────
        # process_tick handles individual symbols; multi-symbol ranking happens
        # in process_all_ticks which calls this per symbol and collects candidates.

    async def process_all_ticks(self, snapshots: dict[str, SnapshotRow]) -> None:
        """
        Run a full strategy cycle across all symbols:
          1. Execute SELL signals immediately.
          2. Collect BUY candidates, rank by score, execute top ones.
          3. Update equity, persist positions, log portfolio summary.
        """
        buy_candidates: list[dict] = []

        for symbol, snapshot in snapshots.items():
            price = float(snapshot.last_price)
            if price <= 0:
                continue

            signal = self._strategy.update(symbol, price)

            if signal == "SELL" and symbol in self._positions:
                await self._execute_sell(symbol, price)
                continue

            if signal == "BUY" and symbol not in self._positions:
                indicators = self._strategy.indicators(symbol)
                prices_window = list(self._strategy._state(symbol).prices)
                vol = _volatility_pct(prices_window)
                score = _score_opportunity(indicators, vol)
                buy_candidates.append(
                    {
                        "symbol": symbol,
                        "price": price,
                        "score": score,
                        "indicators": indicators,
                        "volatility": vol,
                    }
                )

        # Rank and execute top BUY candidates within open-position limit.
        buy_candidates.sort(key=lambda c: c["score"], reverse=True)
        open_slots = self._config.max_open_positions - len(self._positions)

        for candidate in buy_candidates[:open_slots]:
            if self._risk.halted:
                logger.warning("Risk circuit-breaker is active — no new positions.")
                break
            await self._execute_buy(
                candidate["symbol"],
                candidate["price"],
                candidate["indicators"],
                candidate["volatility"],
            )

        await self.persist_positions()

        # ── Equity update + portfolio summary ────────────────────────────────
        if self._config.paper_trade:
            self._update_paper_equity(snapshots)
            await self._log_portfolio_summary(snapshots)
        else:
            try:
                await self._refresh_equity_live()
                await self._log_portfolio_summary(snapshots)
            except Exception as exc:
                logger.warning("Failed to refresh equity: %s", exc)

    # ── Execution helpers ─────────────────────────────────────────────────────

    async def _execute_sell(self, symbol: str, price: float) -> None:
        entry_price = self._positions.get(symbol, price)
        was_loss = price < entry_price

        if self._config.paper_trade:
            fill = self._paper_fill(price, "SELL")
            order_id = self._synthetic_order_id(symbol, "SELL")
            quantity = Decimal(str(self._quantities.get(symbol, 1.0)))
            fee = fill * quantity * Decimal(str(self._config.commission_rate))
            await self._persist_fill(
                order_id=order_id,
                symbol=symbol,
                side="SELL",
                order_type="MARKET",
                quantity=quantity,
                fill_price=fill,
                fee=fee,
            )
            proceeds = (
                float(fill) * float(quantity) * (1 - self._config.commission_rate)
            )
            self.available_usdt += proceeds
            pnl_pct = (
                (price - entry_price) / entry_price * 100 if entry_price > 0 else 0.0
            )
            logger.info(
                "PAPER SELL %s qty=%s @ %.8f  entry=%.8f  pnl=%+.2f%%",
                symbol,
                quantity,
                fill,
                entry_price,
                pnl_pct,
            )
        else:
            try:
                qty_str = "1"  # TODO: track actual quantity from buy record
                result = await self._client.place_order(
                    symbol, "SELL", "MARKET", qty_str
                )
                fill = Decimal(
                    str(
                        result.get("fills", [{}])[0].get("price", price)
                        if result.get("fills")
                        else price
                    )
                )
                order_id = str(
                    result.get("orderId", self._synthetic_order_id(symbol, "SELL"))
                )
                quantity = Decimal(str(result.get("executedQty", "1")))
                fee = Decimal(
                    str(
                        result.get("fills", [{}])[0].get("commission", "0")
                        if result.get("fills")
                        else "0"
                    )
                )
                await self._persist_fill(
                    order_id=order_id,
                    symbol=symbol,
                    side="SELL",
                    order_type="MARKET",
                    quantity=quantity,
                    fill_price=fill,
                    fee=fee,
                )
                logger.info("LIVE SELL %s qty=%s @ %.8f", symbol, quantity, fill)
            except Exception as exc:
                logger.error("SELL order failed for %s: %s", symbol, exc)
                return

        self._positions.pop(symbol, None)
        self._quantities.pop(symbol, None)
        self._strategy.notify_sold(symbol, was_loss=was_loss)

    async def _execute_buy(
        self,
        symbol: str,
        price: float,
        indicators: dict,
        volatility: float,
    ) -> None:
        strength = _signal_strength(indicators)
        budget = self._risk.size_usdt(
            self.available_usdt, self.equity, strength, volatility
        )
        if budget <= 0:
            return

        # Precision 5 is a safe default; production should read from exchange info.
        quantity_float = self._risk.quantity(budget, price, precision=5)
        if quantity_float <= 0 or quantity_float * price < self._config.min_order_usdt:
            return

        quantity = Decimal(str(quantity_float))

        if self._config.paper_trade:
            fill = self._paper_fill(price, "BUY")
            order_id = self._synthetic_order_id(symbol, "BUY")
            fee = fill * quantity * Decimal(str(self._config.commission_rate))
            await self._persist_fill(
                order_id=order_id,
                symbol=symbol,
                side="BUY",
                order_type="MARKET",
                quantity=quantity,
                fill_price=fill,
                fee=fee,
            )
            cost = float(fill) * float(quantity) * (1 + self._config.commission_rate)
            self.available_usdt -= cost
            logger.info("PAPER BUY %s qty=%s @ %.8f", symbol, quantity, fill)
        else:
            try:
                result = await self._client.place_order(
                    symbol, "BUY", "MARKET", str(quantity_float)
                )
                fill = Decimal(
                    str(
                        result.get("fills", [{}])[0].get("price", price)
                        if result.get("fills")
                        else price
                    )
                )
                order_id = str(
                    result.get("orderId", self._synthetic_order_id(symbol, "BUY"))
                )
                quantity = Decimal(str(result.get("executedQty", str(quantity_float))))
                fee = Decimal(
                    str(
                        result.get("fills", [{}])[0].get("commission", "0")
                        if result.get("fills")
                        else "0"
                    )
                )
                await self._persist_fill(
                    order_id=order_id,
                    symbol=symbol,
                    side="BUY",
                    order_type="MARKET",
                    quantity=quantity,
                    fill_price=fill,
                    fee=fee,
                )
                self.available_usdt -= (
                    float(fill) * float(quantity) * (1 + self._config.commission_rate)
                )
                logger.info("LIVE BUY %s qty=%s @ %.8f", symbol, quantity, fill)
            except Exception as exc:
                logger.error("BUY order failed for %s: %s", symbol, exc)
                return

        self._positions[symbol] = price
        self._quantities[symbol] = float(quantity)
        self._strategy.notify_bought(symbol, price)

    # ── Paper-trade helpers ───────────────────────────────────────────────────

    def _paper_fill(self, price: float, side: str) -> Decimal:
        """Apply slippage to a paper-trade fill price."""
        slip = self._config.slippage_bps / 10_000
        if side == "BUY":
            return Decimal(str(round(price * (1 + slip), 10)))
        else:
            return Decimal(str(round(price * (1 - slip), 10)))

    @staticmethod
    def _synthetic_order_id(symbol: str, side: str) -> str:
        return f"PAPER-{symbol}-{side}-{uuid.uuid4().hex[:12].upper()}"

    # ── DB persistence ────────────────────────────────────────────────────────

    @staticmethod
    async def _persist_fill(
        order_id: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        fill_price: Decimal,
        fee: Decimal,
    ) -> None:
        now = datetime.now(UTC)
        await DB.insert_order(
            exchange_order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            filled_quantity=quantity,
            price=None,
            average_fill_price=fill_price,
            status="FILLED",
            created_at=now,
        )
        await DB.insert_trade(
            exchange_order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=fill_price,
            fee=fee,
            executed_at=now,
        )

    def _update_paper_equity(self, snapshots: dict[str, SnapshotRow]) -> None:
        """
        Recompute equity for paper trading:
          equity = free USDT + sum(current_price × quantity) for each open position.
        """
        position_value = 0.0
        for symbol, qty in self._quantities.items():
            snapshot = snapshots.get(symbol)
            if snapshot is not None:
                position_value += float(snapshot.last_price) * qty
            else:
                # Fall back to entry price if no snapshot this tick.
                position_value += self._positions.get(symbol, 0.0) * qty

        self.equity = self.available_usdt + position_value
        self._risk.update_equity(self.equity)

    async def _log_portfolio_summary(self, snapshots: dict[str, SnapshotRow]) -> None:
        """Log a one-line portfolio summary and per-position PnL after every tick."""
        mode = "PAPER" if self._config.paper_trade else "LIVE"
        start = self._config.paper_trade_balance if self._config.paper_trade else 0.0
        pnl_usdt = self.equity - start if start > 0 else 0.0
        pnl_pct = pnl_usdt / start * 100 if start > 0 else 0.0
        drawdown_pct = (
            (self._risk.peak_equity - self.equity) / self._risk.peak_equity * 100
            if self._risk.peak_equity > 0
            else 0.0
        )

        logger.info(
            "[%s] equity=%.2f USDT  free=%.2f  positions=%d  "
            "pnl=%+.2f USDT (%+.2f%%)  drawdown=%.2f%%  halted=%s",
            mode,
            self.equity,
            self.available_usdt,
            len(self._positions),
            pnl_usdt,
            pnl_pct,
            drawdown_pct,
            self._risk.halted,
        )

        # Per-position breakdown.
        for symbol, entry_price in self._positions.items():
            snapshot = snapshots.get(symbol)
            current_price = float(snapshot.last_price) if snapshot else entry_price
            qty = self._quantities.get(symbol, 0.0)
            pos_pnl_pct = (
                (current_price - entry_price) / entry_price * 100
                if entry_price > 0
                else 0.0
            )
            pos_value = current_price * qty
            logger.info(
                "  %-12s  qty=%-10.5f  entry=%-12.4f  now=%-12.4f  "
                "value=%-10.2f USDT  pnl=%+.2f%%",
                symbol,
                qty,
                entry_price,
                current_price,
                pos_value,
                pos_pnl_pct,
            )

        # Persist equity to DB.
        try:
            await DB.insert_equity(Decimal(str(round(self.equity, 8))))
        except Exception as exc:
            logger.warning("Failed to persist equity: %s", exc)

    async def _refresh_equity_live(self) -> None:
        account = await self._client.get_account()
        balances = {
            b["asset"]: float(b["free"])
            for b in account.get("balances", [])
            if float(b["free"]) > 0
        }
        usdt = balances.get("USDT", 0.0)
        self.available_usdt = usdt
        # Approximate equity: USDT + estimated value of open positions.
        position_value = sum(
            price * 1.0  # TODO: multiply by actual quantity from DB
            for price in self._positions.values()
        )
        self.equity = usdt + position_value
        self._risk.update_equity(self.equity)
        await DB.insert_equity(Decimal(str(round(self.equity, 8))))
