from datetime import datetime
from decimal import Decimal

from sqlalchemy import TIMESTAMP, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.data.engine import Base


class Prices(Base):
    __tablename__ = "prices"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True, nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), primary_key=True, nullable=False
    )

    exchange: Mapped[str] = mapped_column(String(20), nullable=False)

    last_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    bid_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    ask_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)

    __table_args__ = (
        Index("idx_prices_exchange_symbol_ts", "exchange", "symbol", "snapshot_at"),
    )
