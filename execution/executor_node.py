"""Executor — Adaptador de exchange con gate Human-in-the-Loop PAPER->LIVE.

Modos de operación:
  1. Sin BinanceRestClient: mock puro (PAPER_FILL / LIVE_ORDER_SENT).
  2. Con BinanceRestClient (testnet): órdenes reales en testnet de Binance (PAPER).
  3. Con BinanceRestClient (mainnet): órdenes reales en producción (requiere HitL+2FA).

PROHIBIDO pasar de PAPER a LIVE sin input() explícito + 2FA simulada.
"""

from __future__ import annotations

import logging
import os

from core.domain import Env, Side, Signal
from execution.binance_rest import BinanceAPIError, BinanceRestClient, _avg_fill_price

log = logging.getLogger("executor")


class HitLDenied(RuntimeError):
    """Se intentó operar en LIVE sin autorización humana válida."""


class Executor:
    def __init__(
        self,
        env: Env | None = None,
        binance: BinanceRestClient | None = None,
        notional_usdt: float = 10.0,
    ) -> None:
        raw = os.environ.get("ENV", "PAPER")
        self._env = env or Env(raw)
        self._binance = binance
        self._notional = notional_usdt
        self._open_qty: dict[str, float] = {}  # symbol → unidades del activo base en posición

    def _require_hitl(self) -> None:
        """Gate irreversible: input explícito + 2FA simulada para habilitar LIVE."""
        log.warning("Solicitud de transición a ENV=LIVE.")
        confirm = input("Escribe 'CONFIRMO LIVE' para continuar: ").strip()
        if confirm != "CONFIRMO LIVE":
            raise HitLDenied("Confirmación humana no válida.")
        code = input("Código 2FA (simulado): ").strip()
        expected = os.environ.get("TWO_FA_CODE", "")
        if not expected or code != expected:
            raise HitLDenied("2FA inválido.")
        log.warning("Transición a LIVE autorizada por humano + 2FA.")

    async def execute(self, signal: Signal) -> dict[str, str]:
        """Ejecuta una señal YA VALIDADA por el Risk Auditor."""
        if self._env is Env.LIVE:
            self._require_hitl()

        if self._binance is not None:
            return await self._execute_via_binance(signal)

        # Modo mock (sin claves API)
        if self._env is Env.LIVE:
            return {
                "status": "LIVE_ORDER_SENT",
                "symbol": signal.symbol,
                "side": signal.side.value,
            }
        return {"status": "PAPER_FILL", "symbol": signal.symbol, "side": signal.side.value}

    async def _execute_via_binance(self, signal: Signal) -> dict[str, str]:
        assert self._binance is not None
        try:
            if signal.side == Side.BUY:
                result = await self._binance.market_buy(signal.symbol, self._notional)
                self._open_qty[signal.symbol] = float(result.get("executedQty", 0.0))
                avg_price = _avg_fill_price(result.get("fills", []))
                return {
                    "status": "FILLED",
                    "symbol": signal.symbol,
                    "side": "BUY",
                    "executedQty": str(result.get("executedQty", "0")),
                    "price": f"{avg_price:.4f}",
                }

            if signal.side == Side.SELL:
                open_qty = self._open_qty.get(signal.symbol, 0.0)
                if open_qty <= 0.0:
                    log.warning(
                        "SELL solicitado sin posición abierta en %s — omitiendo.", signal.symbol
                    )
                    return {"status": "NO_POSITION", "symbol": signal.symbol, "side": "SELL"}
                result = await self._binance.market_sell(signal.symbol, open_qty)
                self._open_qty.pop(signal.symbol, None)
                avg_price = _avg_fill_price(result.get("fills", []))
                return {
                    "status": "FILLED",
                    "symbol": signal.symbol,
                    "side": "SELL",
                    "executedQty": str(result.get("executedQty", "0")),
                    "price": f"{avg_price:.4f}",
                }

            # FLAT u otros
            return {"status": "SKIPPED", "symbol": signal.symbol, "side": signal.side.value}

        except BinanceAPIError as exc:
            log.error("Binance API error %d: %s", exc.code, exc.message)
            return {"status": "API_ERROR", "symbol": signal.symbol, "reason": str(exc)}
        except Exception as exc:
            log.error("Executor error inesperado: %s", exc)
            return {"status": "ERROR", "symbol": signal.symbol, "reason": str(exc)}

    async def close(self) -> None:
        if self._binance is not None:
            await self._binance.close()
