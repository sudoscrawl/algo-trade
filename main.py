"""
algo-trade — Binance Spot algorithmic trading bot.

Entry point.  Run with:  uv run python main.py
"""

import asyncio
import logging
import signal
from pathlib import Path

from app.config import config
from app.data.queries import DB
from app.exchanges.binance_rest import BinanceClient
from app.exchanges.binance_ws import connect_binance
from app.risk import RiskManager
from app.services.executor import TradeExecutor
from app.services.scheduler import snapshot_scheduler
from app.services.state_manager import market_state
from app.strategy.momentum import MomentumStrategy

logger = logging.getLogger(__name__)


# ── Logging setup ─────────────────────────────────────────────────────────────


def _configure_logging() -> None:
    log_path = Path(config.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=formatter,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_path),
        ],
        force=True,
    )
    # Keep third-party libraries quiet at INFO so the debug output isn't buried.
    for noisy in ("websockets", "asyncio", "httpx", "sqlalchemy"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ── Startup restore ───────────────────────────────────────────────────────────


async def _restore_state(
    strategy: MomentumStrategy, risk: RiskManager
) -> dict[str, float]:
    """
    Reload persisted positions and warm up strategy indicator windows from DB.
    Returns the restored positions dict.
    """
    # 1. Restore open positions.
    positions = await DB.get_positions()
    for symbol, entry_price in positions.items():
        strategy.notify_bought(symbol, float(entry_price))
    if positions:
        logger.info(
            "Restored %d open position(s): %s", len(positions), list(positions.keys())
        )

    # 2. Warm up indicator windows from recent price history.
    symbols = list(config.symbols)
    history = await DB.get_recent_prices_bulk(
        symbols, limit_per_symbol=config.min_history * 2
    )
    warmed = 0
    for symbol in symbols:
        rows = history.get(symbol.lower(), []) or history.get(symbol, [])
        prices = [float(r["last_price"]) for r in rows if r.get("last_price")]
        if prices:
            strategy.restore(symbol.lower(), prices)
            warmed += 1
    if warmed:
        logger.info("Warmed up indicator windows for %d symbol(s).", warmed)

    # 3. Initialise RiskManager from last recorded equity.
    last_equity = await DB.get_latest_equity()
    if last_equity is not None:
        risk.update_equity(float(last_equity))
        logger.info("Restored peak equity: %.2f USDT", risk.peak_equity)

    return positions


# ── Main ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    _configure_logging()

    # Validate live execution guards before doing anything order-capable.
    config.validate_live_execution()

    logger.info(
        "Starting algo-trade | mode=%s | symbols=%d | tick=%ds",
        "PAPER" if config.paper_trade else "LIVE",
        len(config.symbols),
        config.tick_period,
    )

    # ── Initialise market state ───────────────────────────────────────────────
    symbols_lower = tuple(s.lower() for s in config.symbols)
    for symbol in symbols_lower:
        market_state.initialize("binance", symbol)

    # ── Build components ──────────────────────────────────────────────────────
    client = BinanceClient()
    strategy = MomentumStrategy(config)
    risk = RiskManager(initial_equity=0.0, settings=config)

    # ── Restore persisted state ───────────────────────────────────────────────
    positions = await _restore_state(strategy, risk)

    # ── Sync clock (non-fatal if it fails) ────────────────────────────────────
    try:
        await client.sync_clock()
    except Exception as exc:
        logger.warning("Clock sync failed, using local time: %s", exc)

    # ── Bootstrap equity from live account (or paper default) ─────────────────
    if not config.paper_trade:
        try:
            account = await client.get_account()
            usdt_balance = next(
                (
                    float(b["free"])
                    for b in account.get("balances", [])
                    if b["asset"] == "USDT"
                ),
                0.0,
            )
            risk.peak_equity = max(risk.peak_equity, usdt_balance)
            available_usdt = usdt_balance
        except Exception as exc:
            logger.warning("Failed to fetch initial balance: %s", exc)
            available_usdt = 0.0
    else:
        available_usdt = config.paper_trade_balance  # paper-trade starting balance

    # ── Build executor ────────────────────────────────────────────────────────
    executor = TradeExecutor(client, risk, strategy, market_state, cfg=config)
    executor.load_positions(positions)
    executor.available_usdt = available_usdt
    executor.equity = available_usdt
    risk.peak_equity = max(risk.peak_equity, available_usdt)

    # ── Graceful shutdown ─────────────────────────────────────────────────────
    running = asyncio.Event()
    running.set()

    def _stop(*_) -> None:
        logger.info("Shutdown signal received — stopping bot.")
        running.clear()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _stop)

    logger.info("Bot initialised. Entering main loop.")

    try:
        await asyncio.gather(
            connect_binance(symbols_lower, running=running),
            snapshot_scheduler(market_state, running=running, executor=executor),
        )
    finally:
        await client.close()
        logger.info("Bot stopped cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
