"""Collect a price snapshot from in-memory MarketState for DB persistence."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from app.services.state_manager import MarketState


@dataclass(frozen=True, slots=True)
class SnapshotRow:
    exchange: str
    symbol: str
    snapshot_at: datetime
    last_price: Decimal
    bid_price: Decimal
    ask_price: Decimal


def collect_snapshots(state: MarketState) -> list[SnapshotRow]:
    """
    Return one SnapshotRow per instrument that has a non-None last_price.
    Instruments with no price data yet (just initialized) are skipped.
    """
    now = datetime.now(UTC)
    rows: list[SnapshotRow] = []

    for instrument in state.instruments.values():
        if instrument.last_price is None:
            continue
        rows.append(
            SnapshotRow(
                exchange=instrument.exchange,
                symbol=instrument.symbol,
                snapshot_at=now,
                last_price=instrument.last_price,
                bid_price=instrument.bid_price or Decimal(0),
                ask_price=instrument.ask_price or Decimal(0),
            )
        )

    return rows
