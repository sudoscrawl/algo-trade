"""Drift-correcting snapshot scheduler — the bot's main execution clock."""

import asyncio
import logging

from app.config import config
from app.data.writer import write_snapshots
from app.services.snapshot import collect_snapshots
from app.services.state_manager import MarketState

logger = logging.getLogger(__name__)


async def snapshot_scheduler(
    state: MarketState,
    running: asyncio.Event | None = None,
    executor=None,
) -> None:
    """
    Every `tick_period` seconds:
      1. Collect price snapshots from MarketState and persist to DB.
      2. If an executor is provided, run strategy evaluation for each symbol.

    Uses a drift-correcting sleep so ticks stay aligned even if processing
    takes non-trivial time.
    """
    loop = asyncio.get_running_loop()
    next_run = loop.time() + config.tick_period

    while True:
        if running is not None and not running.is_set():
            break

        await asyncio.sleep(max(0.0, next_run - loop.time()))

        if running is not None and not running.is_set():
            break

        snapshots = collect_snapshots(state)

        try:
            await write_snapshots(snapshots)
            logger.info("Persisted %d price snapshots.", len(snapshots))
        except Exception as exc:
            logger.error("Failed to write snapshots: %s", exc)

        # Strategy evaluation + execution.
        if executor is not None:
            snapshot_map = {s.symbol: s for s in snapshots}
            try:
                await executor.process_all_ticks(snapshot_map)
            except Exception as exc:
                logger.error("Executor error: %s", exc)

        # Drift correction: skip missed ticks rather than catching up in a burst.
        next_run += config.tick_period
        now = loop.time()
        if next_run < now:
            missed = int((now - next_run) // config.tick_period + 1)
            next_run += missed * config.tick_period
            logger.warning(
                "Scheduler fell behind by %d tick(s); skipping ahead.", missed
            )
