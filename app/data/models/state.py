from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from app.data.engine import Base


class State(Base):
    __tablename__ = "state"

    key: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
