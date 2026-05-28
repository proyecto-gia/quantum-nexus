"""Data Loader — descarga klines históricos de Binance y los convierte en Ticks.

Usa la API pública REST (no requiere autenticación).
Pagina automáticamente para superar el límite de 1000 velas por request.
"""

from __future__ import annotations

import time
from typing import Any

import aiohttp

from core.domain import Tick

BINANCE_API = "https://api.binance.com"
_KLINES_ENDPOINT = "/api/v3/klines"
_MAX_PER_REQUEST = 1000

_INTERVAL_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


def interval_to_ms(interval: str) -> int:
    ms = _INTERVAL_MS.get(interval)
    if ms is None:
        raise ValueError(f"Intervalo no soportado: {interval}. Válidos: {list(_INTERVAL_MS)}")
    return ms


async def fetch_klines(
    symbol: str,
    interval: str,
    days: int,
    *,
    base_url: str = BINANCE_API,
) -> list[Tick]:
    """Descarga `days` días de klines y devuelve una lista de Ticks (close price + volume)."""
    interval_ms = interval_to_ms(interval)
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 86_400_000

    ticks: list[Tick] = []
    url = f"{base_url}{_KLINES_ENDPOINT}"

    async with aiohttp.ClientSession() as session:
        cursor = start_ms
        while cursor < end_ms:
            params: dict[str, Any] = {
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": _MAX_PER_REQUEST,
            }
            async with session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                resp.raise_for_status()
                raw: list[list[Any]] = await resp.json()

            if not raw:
                break

            for candle in raw:
                # [open_time, open, high, low, close, volume, close_time, ...]
                open_time = int(candle[0])
                close_price = float(candle[4])
                volume = float(candle[5])
                ticks.append(
                    Tick(symbol=symbol, price=close_price, volume=volume, timestamp=open_time)
                )

            last_open_time = int(raw[-1][0])
            cursor = last_open_time + interval_ms

            if len(raw) < _MAX_PER_REQUEST:
                break

    return ticks
