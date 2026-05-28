"""BinanceWebSocketClient — feed de datos de mercado en tiempo real.

Conecta al stream aggTrade de Binance (precios + volumen por trade agregado).
Normaliza cada mensaje al formato que Oracle.ingest() espera y lo entrega.

Reconexión automática con backoff exponencial (1 s → 2 s → … → 60 s).
Binance limita las conexiones a 24 h; el cliente reconecta antes de ese límite.

Uso:
    client = BinanceWebSocketClient(symbols=["BTCUSDT"], oracle=oracle)
    await client.run(stop_event)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import websockets
import websockets.exceptions

from execution.oracle import Oracle

log = logging.getLogger("binance_ws")

_WS_SINGLE = "wss://stream.binance.com:9443/ws"
_WS_COMBINED = "wss://stream.binance.com:9443/stream"

# Binance cierra la conexión a las 24 h; reconectamos antes.
_MAX_CONN_SECONDS = 23 * 3600
_MAX_BACKOFF = 60.0


def _normalize(msg: dict[str, Any]) -> str | None:
    """Convierte un mensaje aggTrade de Binance al JSON que Oracle espera."""
    try:
        return json.dumps(
            {
                "symbol": str(msg["s"]),
                "price": float(msg["p"]),
                "volume": float(msg["q"]),
                "timestamp": int(msg["T"]),
            }
        )
    except (KeyError, ValueError, TypeError):
        return None


def _stream_url(symbols: list[str]) -> str:
    streams = "/".join(f"{s.lower()}@aggTrade" for s in symbols)
    if len(symbols) == 1:
        return f"{_WS_SINGLE}/{streams}"
    return f"{_WS_COMBINED}?streams={streams}"


class BinanceWebSocketClient:
    def __init__(self, symbols: list[str], oracle: Oracle) -> None:
        if not symbols:
            raise ValueError("Se requiere al menos un símbolo")
        self._symbols = [s.strip().upper() for s in symbols]
        self._oracle = oracle
        self._url = _stream_url(self._symbols)

    async def run(self, stop: asyncio.Event) -> None:
        log.info("Binance WS iniciando — symbols=%s", self._symbols)
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
                            # Combined stream wraps: {"stream": ..., "data": {...}}
                            msg = outer.get("data", outer)
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
