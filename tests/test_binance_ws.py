"""Tests para BinanceWebSocketClient — sin red, todo mockeado."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from core.the_omnibus import TheOmnibus
from execution.binance_ws import BinanceWebSocketClient, _normalize, _stream_url
from execution.oracle import Oracle


# ── _normalize ────────────────────────────────────────────────────────────────


def test_normalize_valid_aggtrade() -> None:
    msg = {"s": "BTCUSDT", "p": "65000.5", "q": "0.15", "T": 1_700_000_000_000}
    result = _normalize(msg)
    assert result is not None
    data = json.loads(result)
    assert data["symbol"] == "BTCUSDT"
    assert data["price"] == 65000.5
    assert data["volume"] == 0.15
    assert data["timestamp"] == 1_700_000_000_000


def test_normalize_missing_field_returns_none() -> None:
    assert _normalize({"s": "BTCUSDT", "p": "65000.0"}) is None  # sin q y T


def test_normalize_bad_float_returns_none() -> None:
    assert _normalize({"s": "BTCUSDT", "p": "not-a-number", "q": "1.0", "T": 1}) is None


def test_normalize_combined_stream_wrapper() -> None:
    """Combined stream envuelve en {"stream": ..., "data": {...}}."""
    outer: dict[str, Any] = {
        "stream": "btcusdt@aggTrade",
        "data": {"s": "BTCUSDT", "p": "65000.0", "q": "1.0", "T": 1},
    }
    msg: dict[str, Any] = outer.get("data", outer)
    result = _normalize(msg)
    assert result is not None
    assert json.loads(result)["symbol"] == "BTCUSDT"


# ── _stream_url ───────────────────────────────────────────────────────────────


def test_stream_url_single_symbol() -> None:
    url = _stream_url(["BTCUSDT"])
    assert "btcusdt@aggTrade" in url
    assert "stream.binance.com" in url
    assert "stream?" not in url  # single → directo, no combined


def test_stream_url_multi_symbol() -> None:
    url = _stream_url(["BTCUSDT", "ETHUSDT"])
    assert "btcusdt@aggTrade" in url
    assert "ethusdt@aggTrade" in url
    assert "streams=" in url  # combined stream


def test_symbols_normalized_to_upper() -> None:
    bus = TheOmnibus(queue_size=10)
    oracle = Oracle(bus)
    client = BinanceWebSocketClient(symbols=["btcusdt"], oracle=oracle)
    assert client._symbols == ["BTCUSDT"]


def test_no_symbols_raises() -> None:
    bus = TheOmnibus(queue_size=10)
    oracle = Oracle(bus)
    with pytest.raises(ValueError):
        BinanceWebSocketClient(symbols=[], oracle=oracle)


# ── run() con WS mockeado ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_ingests_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    """El cliente normaliza y entrega ticks al Oracle."""
    bus = TheOmnibus(queue_size=100)
    oracle = Oracle(bus)
    client = BinanceWebSocketClient(symbols=["BTCUSDT"], oracle=oracle)

    messages = [
        json.dumps({"s": "BTCUSDT", "p": "65000.0", "q": "1.5", "T": 1_000}),
        json.dumps({"s": "BTCUSDT", "p": "65100.0", "q": "0.5", "T": 2_000}),
    ]

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

    monkeypatch.setattr("websockets.connect", lambda *a, **kw: FakeWS())

    stop = asyncio.Event()
    ingested: list[str] = []
    original_ingest = oracle.ingest

    async def capture(raw: str | bytes) -> None:
        ingested.append(raw if isinstance(raw, str) else raw.decode())
        await original_ingest(raw)

    oracle.ingest = capture  # type: ignore[method-assign]

    await client.run(stop)

    assert len(ingested) == 2
    first = json.loads(ingested[0])
    assert first["price"] == 65000.0
    assert first["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_run_skips_malformed_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mensajes malformados no rompen el cliente."""
    bus = TheOmnibus(queue_size=100)
    oracle = Oracle(bus)
    client = BinanceWebSocketClient(symbols=["BTCUSDT"], oracle=oracle)

    messages = [
        "not-json-at-all",
        json.dumps({"bad": "payload"}),
        json.dumps({"s": "BTCUSDT", "p": "65000.0", "q": "1.5", "T": 1_000}),
    ]

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

    monkeypatch.setattr("websockets.connect", lambda *a, **kw: FakeWS())

    stop = asyncio.Event()
    ingested: list[str] = []
    original_ingest = oracle.ingest

    async def capture(raw: str | bytes) -> None:
        ingested.append(raw if isinstance(raw, str) else raw.decode())
        await original_ingest(raw)

    oracle.ingest = capture  # type: ignore[method-assign]

    await client.run(stop)

    # Solo el mensaje válido llega al Oracle
    assert len(ingested) == 1
    assert json.loads(ingested[0])["price"] == 65000.0
