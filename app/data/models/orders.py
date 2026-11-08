from datetime import datetime
from decimal import Decimal

from sqlalchemy import TIMESTAMP, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.data.engine import Base


class Orders(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exchange_order_id: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)

    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    filled_quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), default=Decimal(0), nullable=False
    )
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    average_fill_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), default=Decimal(0), nullable=False
    )

    status: Mapped[str] = mapped_column(String(16), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
