"""Tests for app/config.py."""

import pytest

from app.config import Config


def test_paper_trade_default_is_true():
    cfg = Config()
    assert cfg.paper_trade is True


def test_paper_trade_can_be_overridden():
    cfg = Config().model_copy(update={"paper_trade": False})
    assert cfg.paper_trade is False


def test_db_url_postgresql_rewritten():
    cfg = Config.model_validate(
        {"DB_URL": "postgresql://user:pass@localhost/db"},
        strict=False,
    )
    assert cfg.db_url.startswith("postgresql+asyncpg://")


def test_db_url_postgres_shorthand_rewritten():
    cfg = Config.model_validate(
        {"DB_URL": "postgres://user:pass@localhost/db"},
        strict=False,
    )
    assert cfg.db_url.startswith("postgresql+asyncpg://")


def test_symbols_csv_parsed():
    cfg = Config.model_validate({"SYMBOLS": "BTCUSDT, ethusdt, BNBUSDT"}, strict=False)
    assert cfg.symbols == ("BTCUSDT", "ETHUSDT", "BNBUSDT")


def test_validate_live_execution_ok_in_paper_mode():
    cfg = Config().model_copy(update={"paper_trade": True})
    cfg.validate_live_execution()  # should not raise


def test_validate_live_execution_raises_without_interlock():
    cfg = Config().model_copy(
        update={
            "paper_trade": False,
            "live_trading_enabled": False,
            "api_key": "key",
            "api_secret": "secret",
        }
    )
    with pytest.raises(RuntimeError, match="LIVE_TRADING_ENABLED"):
        cfg.validate_live_execution()


def test_validate_live_execution_raises_without_credentials():
    cfg = Config().model_copy(
        update={
            "paper_trade": False,
            "live_trading_enabled": True,
            "api_key": "",
            "api_secret": "",
        }
    )
    with pytest.raises(RuntimeError, match="API_KEY"):
        cfg.validate_live_execution()


def test_validate_live_execution_passes_with_all_set():
    cfg = Config().model_copy(
        update={
            "paper_trade": False,
            "live_trading_enabled": True,
            "api_key": "mykey",
            "api_secret": "mysecret",
        }
    )
    cfg.validate_live_execution()  # should not raise
