from datetime import datetime
from decimal import Decimal

from sqlalchemy import TIMESTAMP, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.data.engine import Base


class Equity(Base):
    __tablename__ = "equity"

    snapshot_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), primary_key=True, nullable=False
    )
    equity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
