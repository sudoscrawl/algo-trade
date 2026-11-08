"""Async Binance Spot REST API client with HMAC-SHA256 authentication."""

import hashlib
import hmac
import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import config

logger = logging.getLogger(__name__)


class BinanceClient:
    """Async httpx client for the Binance Spot REST API.

    Authentication uses HMAC-SHA256:
      - All signed endpoints require a `timestamp` param.
      - The signature is the HMAC-SHA256 hex digest of the query string.
      - The API key is sent in the `X-MBX-APIKEY` header.

    Clock sync is performed on initialisation to correct for local drift.
    """

    def __init__(self) -> None:
        self._api_key = config.api_key
        self._api_secret = config.api_secret
        self._time_offset_ms: int = 0

        self._client = httpx.AsyncClient(
            base_url=config.binance_rest_url,
            timeout=config.request_timeout_seconds,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _timestamp_ms(self) -> int:
        """Return the current ms timestamp adjusted for server clock drift."""
        return int(time.time() * 1000) + self._time_offset_ms

    def _sign(self, params: dict[str, Any]) -> dict[str, Any]:
        """Append HMAC-SHA256 `signature` to *params* and return the updated dict."""
        query_string = urlencode(params)
        signature = hmac.new(
            self._api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {**params, "signature": signature}

    def _auth_headers(self) -> dict[str, str]:
        return {"X-MBX-APIKEY": self._api_key}

    async def _request(
        self,
        method: str,
        endpoint: str,
        signed: bool = False,
        **kwargs: Any,
    ) -> Any:
        """
        Execute an HTTP request, raise on non-2xx, and return parsed JSON.

        When *signed=True*, a `timestamp` is injected and the full parameter
        set is HMAC-SHA256 signed before the request is sent.
        """
        if signed:
            params = kwargs.pop("params", {})
            params["timestamp"] = self._timestamp_ms()
            params = self._sign(params)
            kwargs["params"] = params
            kwargs.setdefault("headers", {}).update(self._auth_headers())

        try:
            response = await self._client.request(method, endpoint, **kwargs)
            response.raise_for_status()
            logger.debug("%s %s → %d", method, endpoint, response.status_code)
            return response.json()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "%s %s failed: HTTP %d — %s",
                method,
                endpoint,
                exc.response.status_code,
                exc.response.text[:200],
            )
            raise
        except httpx.RequestError as exc:
            logger.error("%s %s request error: %s", method, endpoint, exc)
            raise

    # ── Clock sync ────────────────────────────────────────────────────────────

    async def sync_clock(self) -> None:
        """Compute clock offset by comparing local time to the Binance server time."""
        local_before = int(time.time() * 1000)
        data = await self._request("GET", "/api/v3/time")
        local_after = int(time.time() * 1000)
        server_time: int = data["serverTime"]
        local_mid = (local_before + local_after) // 2
        self._time_offset_ms = server_time - local_mid
        logger.debug("Clock offset: %d ms", self._time_offset_ms)

    # ── Public endpoints ──────────────────────────────────────────────────────

    async def ping(self) -> dict[str, Any]:
        """Check connectivity and return server time."""
        return await self._request("GET", "/api/v3/time")

    async def get_exchange_info(self, symbol: str | None = None) -> dict[str, Any]:
        """Return exchange info (trading rules, filters, precision) for all or one symbol."""
        params = {}
        if symbol:
            params["symbol"] = symbol.upper()
        return await self._request("GET", "/api/v3/exchangeInfo", params=params)

    async def get_ticker(self, symbol: str) -> dict[str, Any]:
        """Return the latest price ticker for *symbol*."""
        return await self._request(
            "GET", "/api/v3/ticker/bookTicker", params={"symbol": symbol.upper()}
        )

    # ── Authenticated endpoints ───────────────────────────────────────────────

    async def get_account(self) -> dict[str, Any]:
        """Return account information including balances."""
        return await self._request("GET", "/api/v3/account", signed=True, params={})

    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: str,
        price: str | None = None,
        time_in_force: str = "GTC",
    ) -> dict[str, Any]:
        """
        Place a Spot order.

        Args:
            symbol: e.g. "BTCUSDT"
            side: "BUY" or "SELL"
            order_type: "MARKET" or "LIMIT"
            quantity: base-asset quantity as a string (respects lot size precision)
            price: limit price as a string; required for LIMIT orders
            time_in_force: "GTC" (default), "IOC", or "FOK"
        """
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": quantity,
        }
        if order_type.upper() == "LIMIT":
            if price is None:
                raise ValueError("price is required for LIMIT orders")
            params["price"] = price
            params["timeInForce"] = time_in_force

        return await self._request("POST", "/api/v3/order", signed=True, params=params)

    async def cancel_order(self, symbol: str, order_id: int) -> dict[str, Any]:
        """Cancel an open order by its Binance order ID."""
        return await self._request(
            "DELETE",
            "/api/v3/order",
            signed=True,
            params={"symbol": symbol.upper(), "orderId": order_id},
        )

    async def query_order(self, symbol: str, order_id: int) -> dict[str, Any]:
        """Query a single order by its Binance order ID."""
        return await self._request(
            "GET",
            "/api/v3/order",
            signed=True,
            params={"symbol": symbol.upper(), "orderId": order_id},
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()
