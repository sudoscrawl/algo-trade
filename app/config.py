"""Application configuration — the single source of truth for all settings."""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Exchange connectivity ─────────────────────────────────────────────────
    api_key: str = Field(default="", alias="API_KEY")
    api_secret: str = Field(default="", alias="API_SECRET")

    binance_rest_url: str = Field(
        default="https://api.binance.com",
        alias="BINANCE_REST_URL",
    )
    binance_ws_base_url: str = Field(
        default="wss://stream.binance.com:9443/stream?streams=",
        alias="BINANCE_WS_BASE_URL",
    )
    request_timeout_seconds: float = Field(
        default=10.0,
        alias="REQUEST_TIMEOUT_SECONDS",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    db_url: str = Field(
        default="postgresql+asyncpg://algo_trade:algo_trade@localhost:5432/algo_trade",
        alias="DB_URL",
    )

    # ── Execution mode ────────────────────────────────────────────────────────
    paper_trade: bool = Field(default=True, alias="PAPER_TRADE")
    live_trading_enabled: bool = Field(default=False, alias="LIVE_TRADING_ENABLED")

    # Paper-trade starting balance in USDT.
    paper_trade_balance: float = Field(default=10_000.0, alias="PAPER_TRADE_BALANCE")

    # Slippage applied to synthetic paper-trade fills (basis points).
    # e.g. 5 bps = 0.05% slippage per side.
    slippage_bps: float = Field(default=5.0, alias="SLIPPAGE_BPS")

    # ── Symbols ───────────────────────────────────────────────────────────────
    # Declared as str so pydantic-settings passes the raw comma-separated env
    # value through without attempting JSON decode. The validator below coerces
    # it to tuple[str, ...].
    symbols: str | tuple[str, ...] = Field(
        default="BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,AVAXUSDT,LINKUSDT,DOTUSDT",
        alias="SYMBOLS",
    )
    max_open_positions: int = Field(default=5, alias="MAX_OPEN_POSITIONS")

    # ── Scheduler ─────────────────────────────────────────────────────────────
    # How often (in seconds) the snapshot + strategy evaluation loop runs.
    tick_period: int = Field(default=60, alias="TICK_PERIOD")

    # ── Strategy: EMA ────────────────────────────────────────────────────────
    fast_ema_period: int = Field(default=8, alias="FAST_EMA_PERIOD")
    slow_ema_period: int = Field(default=21, alias="SLOW_EMA_PERIOD")

    # ── Strategy: RSI ─────────────────────────────────────────────────────────
    rsi_period: int = Field(default=14, alias="RSI_PERIOD")
    rsi_buy_min: float = Field(default=20.0, alias="RSI_BUY_MIN")
    rsi_buy_max: float = Field(default=75.0, alias="RSI_BUY_MAX")
    rsi_sell_threshold: float = Field(default=45.0, alias="RSI_SELL_THRESHOLD")
    rsi_sell_min: float = Field(default=25.0, alias="RSI_SELL_MIN")

    # ── Strategy: Bollinger Bands ─────────────────────────────────────────────
    bb_period: int = Field(default=20, alias="BB_PERIOD")
    bb_std: float = Field(default=2.0, alias="BB_STD")

    # ── Strategy: ATR ────────────────────────────────────────────────────────
    atr_period: int = Field(default=14, alias="ATR_PERIOD")

    # ── Strategy: Rate of Change ─────────────────────────────────────────────
    roc_period: int = Field(default=10, alias="ROC_PERIOD")
    roc_buy_threshold: float = Field(default=0.1, alias="ROC_BUY_THRESHOLD")

    # ── Strategy: entry / exit thresholds ────────────────────────────────────
    min_history: int = Field(default=50, alias="MIN_HISTORY")
    ema_separation_pct: float = Field(default=0.005, alias="EMA_SEPARATION_PCT")
    confirm_ticks: int = Field(default=1, alias="CONFIRM_TICKS")

    min_hold_cycles: int = Field(default=3, alias="MIN_HOLD_CYCLES")
    min_profit_pct: float = Field(default=0.15, alias="MIN_PROFIT_PCT")
    stop_loss_pct: float = Field(default=2.5, alias="STOP_LOSS_PCT")
    take_profit_pct: float = Field(default=4.0, alias="TAKE_PROFIT_PCT")
    stagnant_exit_cycles: int = Field(default=20, alias="STAGNANT_EXIT_CYCLES")

    trailing_activate_pct: float = Field(default=1.5, alias="TRAILING_ACTIVATE_PCT")
    trailing_stop_pct: float = Field(default=1.0, alias="TRAILING_STOP_PCT")

    loss_cooldown_cycles: int = Field(default=3, alias="LOSS_COOLDOWN_CYCLES")

    # ── Risk / sizing ────────────────────────────────────────────────────────
    max_position_pct: float = Field(default=0.18, alias="MAX_POSITION_PCT")
    base_position_pct: float = Field(default=0.055, alias="BASE_POSITION_PCT")
    min_order_usdt: float = Field(default=10.0, alias="MIN_ORDER_USDT")
    max_drawdown_pct: float = Field(default=0.15, alias="MAX_DRAWDOWN_PCT")
    commission_rate: float = Field(default=0.001, alias="COMMISSION_RATE")
    reserve_pct: float = Field(default=0.03, alias="RESERVE_PCT")

    # ── Logging ───────────────────────────────────────────────────────────────
    log_file: str = Field(default="logs/algo-trade.log", alias="LOG_FILE")

    # ── Validators ───────────────────────────────────────────────────────────

    @field_validator("db_url", mode="before")
    @classmethod
    def ensure_asyncpg_driver(cls, value: str) -> str:
        """Accept bare postgresql:// URLs and rewrite to asyncpg driver."""
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        return value

    @field_validator("symbols", mode="before")
    @classmethod
    def parse_symbols(cls, value: str | tuple | list) -> tuple[str, ...]:
        """Accept a comma-separated string or a sequence; normalise to uppercase tuple."""
        if isinstance(value, str):
            return tuple(s.strip().upper() for s in value.split(",") if s.strip())
        return tuple(str(s).strip().upper() for s in value)

    # ── Guards ────────────────────────────────────────────────────────────────

    def validate_live_execution(self) -> None:
        """Raise before starting any order-capable process without proper config."""
        if self.paper_trade:
            return
        if not self.live_trading_enabled:
            raise RuntimeError(
                "Set LIVE_TRADING_ENABLED=true in .env before running in live mode."
            )
        if not self.api_key or not self.api_secret:
            raise RuntimeError("API_KEY and API_SECRET must be set for live execution.")


config = Config()
