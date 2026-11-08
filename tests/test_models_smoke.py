"""Smoke test: all models import cleanly and are registered with Base.metadata."""

import app.data.models  # noqa: F401 — side-effect import registers all models
from app.data.engine import Base


def test_all_tables_registered():
    table_names = set(Base.metadata.tables.keys())
    assert "prices" in table_names
    assert "orders" in table_names
    assert "trades" in table_names
    assert "equity" in table_names
    assert "state" in table_names


def test_prices_columns():
    table = Base.metadata.tables["prices"]
    col_names = {c.name for c in table.columns}
    assert {
        "symbol",
        "snapshot_at",
        "exchange",
        "last_price",
        "bid_price",
        "ask_price",
    } <= col_names


def test_orders_columns():
    table = Base.metadata.tables["orders"]
    col_names = {c.name for c in table.columns}
    assert {
        "id",
        "exchange_order_id",
        "symbol",
        "side",
        "order_type",
        "quantity",
        "filled_quantity",
        "price",
        "average_fill_price",
        "status",
        "created_at",
        "updated_at",
    } <= col_names


def test_trades_columns():
    table = Base.metadata.tables["trades"]
    col_names = {c.name for c in table.columns}
    assert {
        "id",
        "exchange_order_id",
        "symbol",
        "side",
        "quantity",
        "price",
        "fee",
        "executed_at",
    } <= col_names


def test_equity_columns():
    table = Base.metadata.tables["equity"]
    col_names = {c.name for c in table.columns}
    assert {"snapshot_at", "equity"} <= col_names


def test_state_columns():
    table = Base.metadata.tables["state"]
    col_names = {c.name for c in table.columns}
    assert {"key", "value"} <= col_names
