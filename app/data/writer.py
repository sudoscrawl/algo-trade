"""Async DB writer functions for snapshots, orders, trades, and equity."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert

from app.data.engine import sessionmaker
from app.data.models.equity import Equity
from app.data.models.orders import Orders
from app.data.models.prices import Prices
from app.data.models.trades import Trades
from app.services.snapshot import SnapshotRow


async def write_snapshots(snapshots: list[SnapshotRow]) -> None:
    """Bulk-upsert price snapshots into the prices table."""
    if not snapshots:
        return

    rows = [
        {
            "symbol": s.symbol,
            "snapshot_at": s.snapshot_at,
            "exchange": s.exchange,
            "last_price": s.last_price,
            "bid_price": s.bid_price,
            "ask_price": s.ask_price,
        }
        for s in snapshots
    ]

    async with sessionmaker.begin() as session:
        stmt = insert(Prices).values(rows)
        # On conflict (same symbol + snapshot_at), update prices.
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "snapshot_at"],
            set_={
                "last_price": stmt.excluded.last_price,
                "bid_price": stmt.excluded.bid_price,
                "ask_price": stmt.excluded.ask_price,
            },
        )
        await session.execute(stmt)


async def write_equity(equity: Decimal) -> None:
    """Insert the current portfolio equity value with a UTC timestamp."""
    async with sessionmaker.begin() as session:
        session.add(Equity(snapshot_at=datetime.now(UTC), equity=equity))


async def write_order(
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
    """Insert a new order record."""
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


async def write_trade(
    exchange_order_id: str,
    symbol: str,
    side: str,
    quantity: Decimal,
    price: Decimal,
    fee: Decimal,
    executed_at: datetime | None = None,
) -> None:
    """Insert a fill record into the trades table."""
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
