"""Tests para BinanceRestClient y Executor — sin red real, todo mockeado."""

from __future__ import annotations

import hashlib
import hmac
import urllib.parse
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.domain import Env, Side, Signal
from execution.binance_rest import BinanceAPIError, BinanceRestClient, _avg_fill_price, _truncate
from execution.executor_node import Executor


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_fill(price: str, qty: str) -> dict[str, str]:
    return {"price": price, "qty": qty, "commission": "0", "commissionAsset": "BNB"}


def _buy_response(executed_qty: str = "0.00015384") -> dict[str, Any]:
    price = str(round(10.0 / float(executed_qty), 2))
    return {
        "symbol": "BTCUSDT",
        "orderId": 1001,
        "side": "BUY",
        "type": "MARKET",
        "status": "FILLED",
        "executedQty": executed_qty,
        "cummulativeQuoteQty": "10.00",
        "fills": [_make_fill(price, executed_qty)],
    }


def _sell_response(executed_qty: str = "0.00015384") -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT",
        "orderId": 1002,
        "side": "SELL",
        "type": "MARKET",
        "status": "FILLED",
        "executedQty": executed_qty,
        "cummulativeQuoteQty": "9.98",
        "fills": [_make_fill("64870.0", executed_qty)],
    }


def _mock_session(response_data: dict[str, Any], status: int = 200) -> MagicMock:
    """Construye un aiohttp.ClientSession mockeado que devuelve response_data."""
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=response_data)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.closed = False
    session.post = MagicMock(return_value=mock_resp)
    session.close = AsyncMock()
    return session


# ── _truncate ─────────────────────────────────────────────────────────────────


def test_truncate_floors_not_rounds() -> None:
    assert _truncate(0.000159999, 5) == pytest.approx(0.00015)


def test_truncate_zero_decimals() -> None:
    assert _truncate(3.9, 0) == 3.0


# ── _avg_fill_price ───────────────────────────────────────────────────────────


def test_avg_fill_price_single_fill() -> None:
    fills = [_make_fill("65000.0", "0.001")]
    assert _avg_fill_price(fills) == pytest.approx(65000.0)


def test_avg_fill_price_multiple_fills() -> None:
    fills = [_make_fill("64000.0", "0.001"), _make_fill("66000.0", "0.001")]
    assert _avg_fill_price(fills) == pytest.approx(65000.0)


def test_avg_fill_price_empty_fills() -> None:
    assert _avg_fill_price([]) == 0.0


# ── BinanceRestClient._sign ───────────────────────────────────────────────────


def test_sign_matches_manual_hmac() -> None:
    client = BinanceRestClient(api_key="key", api_secret="secret", testnet=True)
    params: dict[str, str | int | float] = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "MARKET",
        "timestamp": 1_700_000_000_000,
    }
    expected = hmac.new(
        b"secret",
        urllib.parse.urlencode(params).encode(),
        hashlib.sha256,
    ).hexdigest()
    assert client._sign(params) == expected


# ── BinanceRestClient.market_buy ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_market_buy_success() -> None:
    client = BinanceRestClient(api_key="key", api_secret="secret", testnet=True)
    client._session = _mock_session(_buy_response())

    result = await client.market_buy("BTCUSDT", 10.0)
    assert result["status"] == "FILLED"
    assert result["side"] == "BUY"
    assert float(result["executedQty"]) > 0


@pytest.mark.asyncio
async def test_market_buy_api_error_raises() -> None:
    client = BinanceRestClient(api_key="key", api_secret="secret", testnet=True)
    client._session = _mock_session(
        {"code": -2010, "msg": "Account has insufficient balance"},
        status=400,
    )
    with pytest.raises(BinanceAPIError) as exc_info:
        await client.market_buy("BTCUSDT", 10.0)
    assert exc_info.value.code == -2010


# ── BinanceRestClient.market_sell ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_market_sell_success() -> None:
    client = BinanceRestClient(api_key="key", api_secret="secret", testnet=True)
    client._session = _mock_session(_sell_response())

    result = await client.market_sell("BTCUSDT", 0.00015)
    assert result["status"] == "FILLED"
    assert result["side"] == "SELL"


@pytest.mark.asyncio
async def test_market_sell_truncates_qty() -> None:
    """Verifica que la cantidad enviada está truncada, no redondeada."""
    client = BinanceRestClient(api_key="k", api_secret="s", testnet=True, qty_decimals=5)
    captured: dict[str, Any] = {}

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=_sell_response("0.00015"))
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    def capture_post(url: str, data: dict[str, Any]) -> Any:
        captured.update(data)
        return mock_resp

    session = MagicMock()
    session.closed = False
    session.post = MagicMock(side_effect=capture_post)
    client._session = session

    await client.market_sell("BTCUSDT", 0.000159999)
    assert captured.get("quantity") == "0.00015"


# ── Executor (mock mode) ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_executor_paper_fill_no_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "PAPER")
    executor = Executor(env=Env.PAPER)
    signal = Signal(symbol="BTCUSDT", side=Side.BUY, confidence=0.8)
    result = await executor.execute(signal)
    assert result["status"] == "PAPER_FILL"


# ── Executor (Binance client) ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_executor_filled_buy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "PAPER")
    client = BinanceRestClient(api_key="k", api_secret="s", testnet=True)
    client._session = _mock_session(_buy_response("0.00015384"))

    executor = Executor(env=Env.PAPER, binance=client, notional_usdt=10.0)
    signal = Signal(symbol="BTCUSDT", side=Side.BUY, confidence=0.8, price=65000.0)
    result = await executor.execute(signal)

    assert result["status"] == "FILLED"
    assert result["side"] == "BUY"
    assert float(result["executedQty"]) > 0
    assert executor._open_qty == pytest.approx(0.00015384)


@pytest.mark.asyncio
async def test_executor_filled_sell_after_buy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "PAPER")
    client = BinanceRestClient(api_key="k", api_secret="s", testnet=True)

    # Primera llamada: BUY; segunda: SELL
    responses = [_buy_response("0.00015384"), _sell_response("0.00015384")]
    call_count = 0

    async def multi_response(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal call_count
        resp = responses[call_count]
        call_count += 1
        return resp

    client.market_buy = multi_response  # type: ignore[method-assign]
    client.market_sell = multi_response  # type: ignore[method-assign]

    executor = Executor(env=Env.PAPER, binance=client, notional_usdt=10.0)

    buy_signal = Signal(symbol="BTCUSDT", side=Side.BUY, confidence=0.8, price=65000.0)
    await executor.execute(buy_signal)
    assert executor._open_qty > 0

    sell_signal = Signal(symbol="BTCUSDT", side=Side.SELL, confidence=0.8, price=64870.0)
    result = await executor.execute(sell_signal)
    assert result["status"] == "FILLED"
    assert result["side"] == "SELL"
    assert executor._open_qty == 0.0


@pytest.mark.asyncio
async def test_executor_sell_without_position(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "PAPER")
    client = BinanceRestClient(api_key="k", api_secret="s", testnet=True)
    executor = Executor(env=Env.PAPER, binance=client, notional_usdt=10.0)

    signal = Signal(symbol="BTCUSDT", side=Side.SELL, confidence=0.8, price=65000.0)
    result = await executor.execute(signal)
    assert result["status"] == "NO_POSITION"


@pytest.mark.asyncio
async def test_executor_handles_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "PAPER")
    client = BinanceRestClient(api_key="k", api_secret="s", testnet=True)
    client._session = _mock_session(
        {"code": -2010, "msg": "Account has insufficient balance"},
        status=400,
    )
    executor = Executor(env=Env.PAPER, binance=client, notional_usdt=10.0)
    signal = Signal(symbol="BTCUSDT", side=Side.BUY, confidence=0.8)
    result = await executor.execute(signal)
    assert result["status"] == "API_ERROR"
    assert "-2010" in result.get("reason", "")
