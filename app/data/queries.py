"""Stateless async DB query class — all interaction with the five tables goes here."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.data.engine import sessionmaker
from app.data.models.equity import Equity
from app.data.models.orders import Orders
from app.data.models.prices import Prices
from app.data.models.state import State
from app.data.models.trades import Trades


class DB:
    """Async, stateless query service. All methods open their own session."""

    # ── State KV store ────────────────────────────────────────────────────────

    @staticmethod
    async def get_state(key: str, default: str | None = None) -> str | None:
        async with sessionmaker() as session:
            row = await session.get(State, key)
            return row.value if row is not None else default

    @staticmethod
    async def set_state(key: str, value: str) -> None:
        async with sessionmaker.begin() as session:
            row = await session.get(State, key)
            if row is None:
                session.add(State(key=key, value=value))
            else:
                row.value = value

    @staticmethod
    async def set_multiple_states(states: Mapping[str, str]) -> None:
        async with sessionmaker.begin() as session:
            keys = list(states.keys())
            result = await session.execute(select(State).where(State.key.in_(keys)))
            existing = {row.key: row for row in result.scalars().all()}
            for key, value in states.items():
                if key in existing:
                    existing[key].value = value
                else:
                    session.add(State(key=key, value=value))

    # ── Prices ────────────────────────────────────────────────────────────────

    @staticmethod
    async def get_prices(symbol: str, limit: int = 100) -> list[dict[str, Any]]:
        async with sessionmaker() as session:
            result = await session.execute(
                select(Prices)
                .where(Prices.symbol == symbol)
                .order_by(Prices.snapshot_at.desc())
                .limit(limit)
            )
            return [
                {
                    "symbol": p.symbol,
                    "snapshot_at": p.snapshot_at,
                    "exchange": p.exchange,
                    "last_price": p.last_price,
                    "bid_price": p.bid_price,
                    "ask_price": p.ask_price,
                }
                for p in result.scalars().all()
            ]

    @staticmethod
    async def get_recent_prices_bulk(
        symbols: list[str], limit_per_symbol: int = 40
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch recent price snapshots for multiple symbols in one query."""
        result_map: dict[str, list[dict[str, Any]]] = {s: [] for s in symbols}
        if not symbols:
            return result_map

        async with sessionmaker() as session:
            result = await session.execute(
                select(Prices)
                .where(Prices.symbol.in_(symbols))
                .order_by(Prices.snapshot_at.desc())
            )
            for p in result.scalars().all():
                bucket = result_map.get(p.symbol, [])
                if len(bucket) < limit_per_symbol:
                    bucket.append(
                        {
                            "symbol": p.symbol,
                            "snapshot_at": p.snapshot_at,
                            "last_price": p.last_price,
                        }
                    )
                    result_map[p.symbol] = bucket

        return result_map

    # ── Orders ────────────────────────────────────────────────────────────────

    @staticmethod
    async def insert_order(
        exchange_order_id: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        filled_quantity: Decimal,
        price: Decimal | None,
        average_fill_price: Decimal,
        status: str,
        created_at: datetime | None = None,
    ) -> None:
        now = datetime.now(UTC)
        async with sessionmaker.begin() as session:
            session.add(
                Orders(
                    exchange_order_id=exchange_order_id,
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    quantity=quantity,
                    filled_quantity=filled_quantity,
                    price=price,
                    average_fill_price=average_fill_price,
                    status=status,
                    created_at=created_at or now,
                    updated_at=now,
                )
            )

    @staticmethod
    async def update_order_status(
        exchange_order_id: str,
        status: str,
        filled_quantity: Decimal | None = None,
        average_fill_price: Decimal | None = None,
    ) -> None:
        async with sessionmaker.begin() as session:
            result = await session.execute(
                select(Orders).where(Orders.exchange_order_id == exchange_order_id)
            )
            order = result.scalar_one_or_none()
            if order is None:
                return
            order.status = status
            order.updated_at = datetime.now(UTC)
            if filled_quantity is not None:
                order.filled_quantity = filled_quantity
            if average_fill_price is not None:
                order.average_fill_price = average_fill_price

    # ── Trades ────────────────────────────────────────────────────────────────

    @staticmethod
    async def insert_trade(
        exchange_order_id: str,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal,
        executed_at: datetime | None = None,
    ) -> None:
        async with sessionmaker.begin() as session:
            session.add(
                Trades(
                    exchange_order_id=exchange_order_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    price=price,
                    fee=fee,
                    executed_at=executed_at or datetime.now(UTC),
                )
            )

    # ── Equity ────────────────────────────────────────────────────────────────

    @staticmethod
    async def insert_equity(equity: Decimal) -> None:
        async with sessionmaker.begin() as session:
            session.add(Equity(snapshot_at=datetime.now(UTC), equity=equity))

    @staticmethod
    async def get_latest_equity() -> Decimal | None:
        async with sessionmaker() as session:
            result = await session.execute(
                select(Equity).order_by(Equity.snapshot_at.desc()).limit(1)
            )
            row = result.scalar_one_or_none()
            return row.equity if row is not None else None

    # ── Positions (stored as JSON in state KV) ────────────────────────────────

    @staticmethod
    async def get_positions() -> dict[str, float]:
        raw = await DB.get_state("bot_positions", "{}")
        return json.loads(raw or "{}")

    @staticmethod
    async def save_positions(positions: dict[str, float]) -> None:
        await DB.set_state("bot_positions", json.dumps(positions, sort_keys=True))
