"""Normalise raw Binance WebSocket payloads into typed dataclasses."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class TradeUpdate:
    exchange: str
    symbol: str  # lower-case, e.g. "btcusdt"
    price: Decimal
    quantity: Decimal
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class BookUpdate:
    exchange: str
    symbol: str  # lower-case, e.g. "btcusdt"
    bid_price: Decimal
    bid_qty: Decimal
    ask_price: Decimal
    ask_qty: Decimal


def parse_trade(data: dict[str, Any], exchange: str) -> TradeUpdate:
    return TradeUpdate(
        exchange=exchange,
        symbol=data["s"].lower(),
        price=Decimal(data["p"]),
        quantity=Decimal(data["q"]),
        timestamp=datetime.fromtimestamp(data["T"] / 1000, tz=UTC),
    )


def parse_book(data: dict[str, Any], exchange: str) -> BookUpdate:
    return BookUpdate(
        exchange=exchange,
        symbol=data["s"].lower(),
        bid_price=Decimal(data["b"]),
        bid_qty=Decimal(data["B"]),
        ask_price=Decimal(data["a"]),
        ask_qty=Decimal(data["A"]),
    )


def normalize(payload: dict[str, Any], exchange: str) -> TradeUpdate | BookUpdate:
    """Dispatch a raw Binance WS payload to the appropriate typed event."""
    # Individual stream messages are wrapped in {"stream": "...", "data": {...}}
    # when using combined streams — unwrap if present.
    if "data" in payload:
        payload = payload["data"]

    event_type = payload.get("e")
    if event_type == "trade":
        return parse_trade(payload, exchange)

    # bookTicker events don't have an "e" field; identify by presence of "b"/"a".
    if "b" in payload and "a" in payload and "s" in payload:
        return parse_book(payload, exchange)

    raise ValueError(f"Unknown Binance payload: {payload}")
