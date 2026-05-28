"""BinanceWebSocketClient — feed de datos de mercado en tiempo real.

Soporta dos tipos de stream:
  - "aggTrade"   : cada trade agregado (precio+volumen instantáneo).
  - "kline_Xm/h" : velas OHLCV; emite Tick sólo al cierre de cada vela.
                   Ejemplos: "kline_1m", "kline_5m", "kline_1h".

Para estrategias EMA (diseñadas con velas OHLCV) usar kline es lo correcto.
aggTrade produce miles de micro-ticks donde el precio apenas se mueve,
lo que aplana los EMAs y nunca alcanza el umbral de confianza.

Reconexión automática con backoff exponencial (1 s → 60 s).
Binance limita conexiones a 24 h; reconecta antes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import Any

import websockets
import websockets.exceptions

from execution.oracle import Oracle

log = logging.getLogger("binance_ws")

_WS_SINGLE = "wss://stream.binance.com:9443/ws"
_WS_COMBINED = "wss://stream.binance.com:9443/stream"
_MAX_CONN_SECONDS = 23 * 3600
_MAX_BACKOFF = 60.0


def _normalize_aggtrade(msg: dict[str, Any]) -> str | None:
    try:
        price = float(msg["p"])
        volume = float(msg["q"])
        if not math.isfinite(price) or not math.isfinite(volume):
            return None
        return json.dumps(
            {
                "symbol": str(msg["s"]),
                "price": price,
                "volume": volume,
                "timestamp": int(msg["T"]),
            }
        )
    except (KeyError, ValueError, TypeError):
        return None


def _normalize_kline(msg: dict[str, Any]) -> str | None:
    try:
        k = msg["k"]
        if not k["x"]:  # solo velas cerradas
            return None
        return json.dumps(
            {
                "symbol": str(k["s"]),
                "price": float(k["c"]),  # close
                "volume": float(k["v"]),  # volumen total de la vela
                "timestamp": int(k["t"]),  # open time
            }
        )
    except (KeyError, ValueError, TypeError):
        return None


def _normalize(msg: dict[str, Any]) -> str | None:
    event = msg.get("e")
    if event == "aggTrade":
        return _normalize_aggtrade(msg)
    if event == "kline":
        return _normalize_kline(msg)
    return None


def _stream_url(symbols: list[str], stream_type: str) -> str:
    streams = "/".join(f"{s.lower()}@{stream_type}" for s in symbols)
    if len(symbols) == 1:
        return f"{_WS_SINGLE}/{streams}"
    return f"{_WS_COMBINED}?streams={streams}"


class BinanceWebSocketClient:
    def __init__(
        self,
        symbols: list[str],
        oracle: Oracle,
        stream_type: str = "kline_1m",
    ) -> None:
        if not symbols:
            raise ValueError("Se requiere al menos un símbolo")
        self._symbols = [s.strip().upper() for s in symbols]
        self._oracle = oracle
        self._stream_type = stream_type
        self._url = _stream_url(self._symbols, stream_type)

    async def run(self, stop: asyncio.Event) -> None:
        log.info("Binance WS iniciando — symbols=%s stream=%s", self._symbols, self._stream_type)
        backoff = 1.0

        while not stop.is_set():
            try:
                async with websockets.connect(
                    self._url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    backoff = 1.0
                    log.info("Binance WS conectado: %s", self._url)
                    conn_deadline = asyncio.get_event_loop().time() + _MAX_CONN_SECONDS

                    async for raw in ws:
                        if stop.is_set():
                            break
                        if asyncio.get_event_loop().time() >= conn_deadline:
                            log.info("Binance WS: limite de 23h alcanzado, reconectando...")
                            break
                        try:
                            text = raw.decode() if isinstance(raw, bytes) else raw
                            outer: dict[str, Any] = json.loads(text)
                            msg: dict[str, Any] = outer.get("data", outer)
                            normalized = _normalize(msg)
                            if normalized:
                                await self._oracle.ingest(normalized)
                        except Exception:
                            log.debug("Binance WS parse error", exc_info=True)

            except websockets.exceptions.ConnectionClosedOK:
                if stop.is_set():
                    break
                log.info("Binance WS cerrado limpiamente, reconectando...")
                backoff = 1.0
            except websockets.exceptions.ConnectionClosedError as exc:
                if stop.is_set():
                    break
                log.warning("Binance WS conexion cerrada: %s — reintento en %.0fs", exc, backoff)
            except OSError as exc:
                if stop.is_set():
                    break
                log.warning("Binance WS error de red: %s — reintento en %.0fs", exc, backoff)
            except Exception as exc:
                if stop.is_set():
                    break
                log.error("Binance WS error inesperado: %s — reintento en %.0fs", exc, backoff)

            if stop.is_set():
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _MAX_BACKOFF)

        log.info("Binance WS detenido")
