"""BinanceRestClient — Adaptador HTTP para la API REST de Binance.

Soporta market orders (BUY y SELL) con firma HMAC-SHA256.
Usa testnet cuando BINANCE_TESTNET=true (para ENV=PAPER con claves reales).

Seguridad:
  - Las claves API/secret NUNCA se loguean.
  - recvWindow=5000 ms para tolerar desfase de reloj.
  - Errores de la API se propagan como BinanceAPIError.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import math
import time
import urllib.parse
from typing import Any

import aiohttp

log = logging.getLogger("binance_rest")

_BASE_LIVE = "https://api.binance.com"
_BASE_TEST = "https://testnet.binance.vision"
_ORDER_PATH = "/api/v3/order"
_RECV_WINDOW = 5000


class BinanceAPIError(Exception):
    def __init__(self, message: str, code: int = -1) -> None:
        super().__init__(f"[{code}] {message}")
        self.message = message
        self.code = code


def _truncate(value: float, decimals: int) -> float:
    """Trunca (no redondea) al número de decimales dado — previene lot-size errors."""
    factor = 10**decimals
    return float(math.floor(value * factor) / factor)


def _avg_fill_price(fills: list[dict[str, Any]]) -> float:
    """Precio medio ponderado por cantidad de los fills."""
    total_qty: float = sum((float(f.get("qty", 0)) for f in fills), 0.0)
    if total_qty == 0.0:
        return 0.0
    weighted: float = sum((float(f.get("price", 0)) * float(f.get("qty", 0)) for f in fills), 0.0)
    return weighted / total_qty


class BinanceRestClient:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        testnet: bool = False,
        qty_decimals: int = 5,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret.encode()
        self._base = _BASE_TEST if testnet else _BASE_LIVE
        self._qty_decimals = qty_decimals
        self._session: aiohttp.ClientSession | None = None
        log.info("BinanceRestClient listo (testnet=%s)", testnet)

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"X-MBX-APIKEY": self._api_key},
                timeout=aiohttp.ClientTimeout(total=10),
            )
        return self._session

    def _sign(self, params: dict[str, str | int | float]) -> str:
        query = urllib.parse.urlencode(params)
        return hmac.new(self._api_secret, query.encode(), hashlib.sha256).hexdigest()

    async def _post_order(self, params: dict[str, str | int | float]) -> dict[str, Any]:
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = _RECV_WINDOW
        params["signature"] = self._sign(params)
        session = self._get_session()
        async with session.post(f"{self._base}{_ORDER_PATH}", data=params) as resp:
            data: dict[str, Any] = await resp.json()
            if resp.status != 200:
                raise BinanceAPIError(data.get("msg", "error desconocido"), data.get("code", -1))
            return data

    async def market_buy(self, symbol: str, quote_qty: float) -> dict[str, Any]:
        """Market BUY gastando quote_qty USDT."""
        params: dict[str, str | int | float] = {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": f"{quote_qty:.2f}",
        }
        result = await self._post_order(params)
        log.info(
            "BUY ejecutado: %s qty=%s precio_medio=%.4f",
            symbol,
            result.get("executedQty", "?"),
            _avg_fill_price(result.get("fills", [])),
        )
        return result

    async def market_sell(self, symbol: str, quantity: float) -> dict[str, Any]:
        """Market SELL de quantity unidades del activo base."""
        qty = _truncate(quantity, self._qty_decimals)
        params: dict[str, str | int | float] = {
            "symbol": symbol,
            "side": "SELL",
            "type": "MARKET",
            "quantity": f"{qty:.{self._qty_decimals}f}",
        }
        result = await self._post_order(params)
        log.info(
            "SELL ejecutado: %s qty=%s precio_medio=%.4f",
            symbol,
            result.get("executedQty", "?"),
            _avg_fill_price(result.get("fills", [])),
        )
        return result

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
