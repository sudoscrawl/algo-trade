"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prices",
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column(
            "snapshot_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
        ),
        sa.Column("exchange", sa.String(20), nullable=False),
        sa.Column("last_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("bid_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("ask_price", sa.Numeric(38, 18), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "snapshot_at"),
    )
    op.create_index(
        "idx_prices_exchange_symbol_ts",
        "prices",
        ["exchange", "symbol", "snapshot_at"],
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("exchange_order_id", sa.String(128), nullable=False, unique=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("order_type", sa.String(16), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("filled_quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("price", sa.Numeric(20, 8), nullable=True),
        sa.Column("average_fill_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )

    op.create_table(
        "trades",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("exchange_order_id", sa.String(128), nullable=False, unique=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("price", sa.Numeric(20, 8), nullable=False),
        sa.Column("fee", sa.Numeric(20, 8), nullable=False),
        sa.Column("executed_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index("idx_trades_executed_at", "trades", ["executed_at"])

    op.create_table(
        "equity",
        sa.Column(
            "snapshot_at",
            sa.TIMESTAMP(timezone=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("equity", sa.Numeric(20, 8), nullable=False),
    )

    op.create_table(
        "state",
        sa.Column("key", sa.Text, primary_key=True, nullable=False),
        sa.Column("value", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("state")
    op.drop_table("equity")
    op.drop_index("idx_trades_executed_at", table_name="trades")
    op.drop_table("trades")
    op.drop_table("orders")
    op.drop_index("idx_prices_exchange_symbol_ts", table_name="prices")
    op.drop_table("prices")
