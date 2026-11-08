"""In-memory market state, updated on every WebSocket event."""

from dataclasses import dataclass
from decimal import Decimal

from app.services.normalizer import BookUpdate, TradeUpdate


@dataclass(slots=True)
class InstrumentState:
    exchange: str
    symbol: str

    last_price: Decimal | None = None
    bid_price: Decimal | None = None
    ask_price: Decimal | None = None


class MarketState:
    def __init__(self) -> None:
        self.instruments: dict[tuple[str, str], InstrumentState] = {}

    def initialize(
        self,
        exchange: str,
        symbol: str,
        last_price: Decimal = Decimal(0),
        bid_price: Decimal = Decimal(0),
        ask_price: Decimal = Decimal(0),
    ) -> None:
        """Register an instrument before streaming begins."""
        key = (exchange, symbol)
        self.instruments[key] = InstrumentState(
            exchange=exchange,
            symbol=symbol,
            last_price=last_price if last_price else None,
            bid_price=bid_price if bid_price else None,
            ask_price=ask_price if ask_price else None,
        )

    def update_price(self, exchange: str, symbol: str, price: Decimal) -> None:
        key = (exchange, symbol)
        if key not in self.instruments:
            self.instruments[key] = InstrumentState(exchange=exchange, symbol=symbol)
        self.instruments[key].last_price = price

    def update_book(
        self, exchange: str, symbol: str, bid: Decimal, ask: Decimal
    ) -> None:
        key = (exchange, symbol)
        if key not in self.instruments:
            self.instruments[key] = InstrumentState(exchange=exchange, symbol=symbol)
        state = self.instruments[key]
        state.bid_price = bid
        state.ask_price = ask

    def apply_change(self, event: TradeUpdate | BookUpdate) -> None:
        if isinstance(event, TradeUpdate):
            self.update_price(event.exchange, event.symbol, event.price)
        elif isinstance(event, BookUpdate):
            self.update_book(
                event.exchange, event.symbol, event.bid_price, event.ask_price
            )


# Module-level singleton shared across the process.
market_state = MarketState()
