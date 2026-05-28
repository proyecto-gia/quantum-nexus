"""Tests para BinanceWebSocketClient — sin red, todo mockeado."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from core.the_omnibus import TheOmnibus
from execution.binance_ws import (
    BinanceWebSocketClient,
    _normalize,
    _normalize_aggtrade,
    _normalize_kline,
    _stream_url,
)
from execution.oracle import Oracle


# ── _normalize_aggtrade ───────────────────────────────────────────────────────


def test_normalize_aggtrade_valid() -> None:
    msg = {"e": "aggTrade", "s": "BTCUSDT", "p": "65000.5", "q": "0.15", "T": 1_700_000_000_000}
    result = _normalize_aggtrade(msg)
    assert result is not None
    data = json.loads(result)
    assert data == {
        "symbol": "BTCUSDT",
        "price": 65000.5,
        "volume": 0.15,
        "timestamp": 1_700_000_000_000,
    }


def test_normalize_aggtrade_missing_field() -> None:
    assert _normalize_aggtrade({"s": "BTCUSDT", "p": "65000.0"}) is None


def test_normalize_aggtrade_bad_float() -> None:
    assert _normalize_aggtrade({"s": "X", "p": "NaN", "q": "1.0", "T": 1}) is None


# ── _normalize_kline ──────────────────────────────────────────────────────────


def _kline_msg(closed: bool = True) -> dict[str, Any]:
    return {
        "e": "kline",
        "s": "BTCUSDT",
        "k": {
            "s": "BTCUSDT",
            "i": "1m",
            "t": 1_700_000_000_000,
            "T": 1_700_000_059_999,
            "o": "65000.0",
            "c": "65100.0",
            "h": "65200.0",
            "l": "64900.0",
            "v": "12.5",
            "x": closed,
        },
    }


def test_normalize_kline_closed_emits_tick() -> None:
    result = _normalize_kline(_kline_msg(closed=True))
    assert result is not None
    data = json.loads(result)
    assert data["symbol"] == "BTCUSDT"
    assert data["price"] == 65100.0  # close price
    assert data["volume"] == 12.5
    assert data["timestamp"] == 1_700_000_000_000


def test_normalize_kline_open_returns_none() -> None:
    assert _normalize_kline(_kline_msg(closed=False)) is None


def test_normalize_kline_missing_k_returns_none() -> None:
    assert _normalize_kline({"e": "kline", "s": "BTCUSDT"}) is None


# ── _normalize dispatcher ─────────────────────────────────────────────────────


def test_normalize_dispatches_aggtrade() -> None:
    msg = {"e": "aggTrade", "s": "BTCUSDT", "p": "65000.0", "q": "1.0", "T": 1}
    assert _normalize(msg) is not None


def test_normalize_dispatches_kline() -> None:
    assert _normalize(_kline_msg(closed=True)) is not None


def test_normalize_unknown_event_returns_none() -> None:
    assert _normalize({"e": "bookTicker", "s": "BTCUSDT"}) is None


def test_normalize_combined_stream_wrapper() -> None:
    """Combined stream envuelve en {"stream": ..., "data": {...}}."""
    outer: dict[str, Any] = {
        "stream": "btcusdt@kline_1m",
        "data": _kline_msg(closed=True),
    }
    msg: dict[str, Any] = outer.get("data", outer)
    assert _normalize(msg) is not None


# ── _stream_url ───────────────────────────────────────────────────────────────


def test_stream_url_single_aggtrade() -> None:
    url = _stream_url(["BTCUSDT"], "aggTrade")
    assert "btcusdt@aggTrade" in url
    assert "stream?" not in url


def test_stream_url_single_kline() -> None:
    url = _stream_url(["BTCUSDT"], "kline_1m")
    assert "btcusdt@kline_1m" in url
    assert "stream.binance.com" in url


def test_stream_url_multi_symbol() -> None:
    url = _stream_url(["BTCUSDT", "ETHUSDT"], "kline_1m")
    assert "btcusdt@kline_1m" in url
    assert "ethusdt@kline_1m" in url
    assert "streams=" in url


# ── BinanceWebSocketClient ────────────────────────────────────────────────────


def test_default_stream_type_is_kline_1m() -> None:
    bus = TheOmnibus(queue_size=10)
    client = BinanceWebSocketClient(symbols=["BTCUSDT"], oracle=Oracle(bus))
    assert client._stream_type == "kline_1m"
    assert "kline_1m" in client._url


def test_symbols_normalized_to_upper() -> None:
    bus = TheOmnibus(queue_size=10)
    client = BinanceWebSocketClient(symbols=["btcusdt"], oracle=Oracle(bus))
    assert client._symbols == ["BTCUSDT"]


def test_no_symbols_raises() -> None:
    with pytest.raises(ValueError):
        BinanceWebSocketClient(symbols=[], oracle=Oracle(TheOmnibus(queue_size=10)))


# ── run() con WS mockeado ─────────────────────────────────────────────────────


def _make_fake_ws(messages: list[str]) -> type:
    class FakeWS:
        def __init__(self) -> None:
            self._msgs = iter(messages)

        def __aiter__(self) -> "FakeWS":
            return self

        async def __anext__(self) -> str:
            try:
                return next(self._msgs)
            except StopIteration:
                raise StopAsyncIteration

        async def __aenter__(self) -> "FakeWS":
            return self

        async def __aexit__(self, *_: object) -> None:
            pass

    return FakeWS


@pytest.mark.asyncio
async def test_run_ingests_kline_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Velas cerradas pasan al Oracle; las abiertas se descartan."""
    bus = TheOmnibus(queue_size=100)
    oracle = Oracle(bus)
    client = BinanceWebSocketClient(symbols=["BTCUSDT"], oracle=oracle, stream_type="kline_1m")

    messages = [
        json.dumps(_kline_msg(closed=False)),  # abierta → ignorar
        json.dumps(_kline_msg(closed=True)),  # cerrada → emitir
    ]
    FakeWS = _make_fake_ws(messages)
    monkeypatch.setattr("websockets.connect", lambda *a, **kw: FakeWS())

    stop = asyncio.Event()
    ingested: list[str] = []
    original = oracle.ingest

    async def capture(raw: str | bytes) -> None:
        ingested.append(raw if isinstance(raw, str) else raw.decode())
        await original(raw)
        stop.set()  # terminate after first tick received

    oracle.ingest = capture  # type: ignore[method-assign]

    await client.run(stop)

    assert len(ingested) == 1
    assert json.loads(ingested[0])["price"] == 65100.0


@pytest.mark.asyncio
async def test_run_skips_malformed_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mensajes inválidos no rompen el cliente."""
    bus = TheOmnibus(queue_size=100)
    oracle = Oracle(bus)
    client = BinanceWebSocketClient(symbols=["BTCUSDT"], oracle=oracle, stream_type="kline_1m")

    messages = [
        "not-json",
        json.dumps({"e": "bookTicker"}),
        json.dumps(_kline_msg(closed=True)),
    ]
    FakeWS = _make_fake_ws(messages)
    monkeypatch.setattr("websockets.connect", lambda *a, **kw: FakeWS())

    stop = asyncio.Event()
    ingested: list[str] = []
    original = oracle.ingest

    async def capture(raw: str | bytes) -> None:
        ingested.append(raw if isinstance(raw, str) else raw.decode())
        await original(raw)
        stop.set()  # terminate after first tick received

    oracle.ingest = capture  # type: ignore[method-assign]

    await client.run(stop)

    assert len(ingested) == 1
