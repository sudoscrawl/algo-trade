from datetime import datetime
from decimal import Decimal

from sqlalchemy import TIMESTAMP, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.data.engine import Base


class Trades(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exchange_order_id: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)

    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)

    executed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )

    __table_args__ = (Index("idx_trades_executed_at", "executed_at"),)
