"""Tests for app/exchanges/binance_rest.py."""

import hashlib
import hmac
import time
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlencode

import httpx
import pytest

from app.exchanges.binance_rest import BinanceClient


def _make_response(data: dict, status_code: int = 200) -> MagicMock:
    mock = MagicMock(spec=httpx.Response)
    mock.status_code = status_code
    mock.json.return_value = data
    mock.raise_for_status = MagicMock()
    if status_code >= 400:
        mock.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=mock
        )
        mock.text = str(data)
    return mock


@pytest.fixture
def client():
    return BinanceClient()


# ── _sign ─────────────────────────────────────────────────────────────────────


def test_sign_appends_signature(client):
    params = {"symbol": "BTCUSDT", "timestamp": 1700000000000}
    signed = client._sign(params)
    assert "signature" in signed

    expected_qs = urlencode(params)
    expected_sig = hmac.new(
        client._api_secret.encode(),
        expected_qs.encode(),
        hashlib.sha256,
    ).hexdigest()
    assert signed["signature"] == expected_sig


def test_sign_does_not_mutate_original(client):
    params = {"symbol": "BTCUSDT", "timestamp": 123}
    original = dict(params)
    client._sign(params)
    assert params == original


# ── _timestamp_ms ─────────────────────────────────────────────────────────────


def test_timestamp_ms_applies_offset(client):
    client._time_offset_ms = 5000
    ts = client._timestamp_ms()
    now_ms = int(time.time() * 1000)
    # Should be within 2 seconds of now + 5000 ms offset
    assert abs(ts - (now_ms + 5000)) < 2000


# ── sync_clock ────────────────────────────────────────────────────────────────


async def test_sync_clock_sets_offset(client):
    server_time = int(time.time() * 1000) + 3000  # server 3s ahead
    mock_response = _make_response({"serverTime": server_time})

    with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_response
        await client.sync_clock()

    # Offset should be close to 3000 ms (some small tolerance for test execution time)
    assert abs(client._time_offset_ms - 3000) < 200


# ── ping ─────────────────────────────────────────────────────────────────────


async def test_ping_calls_correct_endpoint(client):
    mock_response = _make_response({"serverTime": 1700000000000})

    with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_response
        result = await client.ping()

    mock_req.assert_called_once()
    call_args = mock_req.call_args
    assert call_args[0][0] == "GET"
    assert "/api/v3/time" in call_args[0][1]
    assert result == {"serverTime": 1700000000000}


# ── place_order ───────────────────────────────────────────────────────────────


async def test_place_order_market_sends_signed_params(client):
    mock_response = _make_response({"orderId": 12345, "status": "FILLED"})

    with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_response
        await client.place_order("BTCUSDT", "BUY", "MARKET", "0.001")

    mock_req.assert_called_once()
    call_kwargs = mock_req.call_args[1]
    params = call_kwargs.get("params", {})

    assert params.get("symbol") == "BTCUSDT"
    assert params.get("side") == "BUY"
    assert params.get("type") == "MARKET"
    assert params.get("quantity") == "0.001"
    assert "timestamp" in params
    assert "signature" in params
    # Auth header present
    headers = call_kwargs.get("headers", {})
    assert "X-MBX-APIKEY" in headers


async def test_place_order_limit_requires_price(client):
    with pytest.raises(ValueError, match="price is required"):
        await client.place_order("BTCUSDT", "BUY", "LIMIT", "0.001", price=None)


async def test_place_order_limit_sends_price_and_tif(client):
    mock_response = _make_response({"orderId": 99, "status": "NEW"})

    with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_response
        await client.place_order("ETHUSDT", "SELL", "LIMIT", "1.0", price="2000.00")

    params = mock_req.call_args[1].get("params", {})
    assert params.get("price") == "2000.00"
    assert params.get("timeInForce") == "GTC"


# ── _request raises on error ──────────────────────────────────────────────────


async def test_request_raises_on_http_error(client):
    mock_response = _make_response({"code": -1100, "msg": "Illegal characters"}, 400)

    with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_response
        with pytest.raises(httpx.HTTPStatusError):
            await client._request("GET", "/api/v3/order", params={})
