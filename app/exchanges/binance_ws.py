"""Binance WebSocket combined stream connector with automatic reconnection."""

import asyncio
import json
import logging

from websockets import connect
from websockets.exceptions import ConnectionClosed

from app.config import config
from app.services.normalizer import normalize
from app.services.state_manager import market_state

logger = logging.getLogger(__name__)

_RECONNECT_BASE_DELAY = 1.0  # seconds
_RECONNECT_MAX_DELAY = 60.0  # seconds


def build_stream_url(symbols: tuple[str, ...]) -> str:
    """Build the Binance combined stream URL for @trade and @bookTicker per symbol."""
    streams = []
    for symbol in symbols:
        s = symbol.lower()
        streams.append(f"{s}@trade")
        streams.append(f"{s}@bookTicker")
    return config.binance_ws_base_url + "/".join(streams)


async def connect_binance(
    symbols: tuple[str, ...],
    running: asyncio.Event | None = None,
) -> None:
    """
    Connect to the Binance combined WebSocket stream and pump messages into
    `market_state` until `running` is cleared or the process is stopped.

    Reconnects automatically on disconnect with exponential backoff.
    """
    url = build_stream_url(symbols)
    delay = _RECONNECT_BASE_DELAY

    while True:
        if running is not None and not running.is_set():
            break
        try:
            async with connect(url, ping_interval=20) as ws:
                logger.info("WebSocket connected: %d symbols", len(symbols))
                delay = _RECONNECT_BASE_DELAY  # reset on successful connection
                async for raw in ws:
                    if running is not None and not running.is_set():
                        return
                    try:
                        payload = json.loads(raw)
                        event = normalize(payload, "binance")
                        market_state.apply_change(event)
                    except ValueError as exc:
                        logger.debug("Skipping unknown payload: %s", exc)
        except ConnectionClosed as exc:
            logger.warning(
                "WebSocket disconnected (%s), reconnecting in %.1fs", exc, delay
            )
        except OSError as exc:
            logger.warning(
                "WebSocket connection error (%s), reconnecting in %.1fs", exc, delay
            )

        if running is not None and not running.is_set():
            break

        await asyncio.sleep(delay)
        delay = min(delay * 2, _RECONNECT_MAX_DELAY)
