"""Executor — Adaptador de exchange con gate Human-in-the-Loop PAPER->LIVE.

PROHIBIDO pasar de PAPER a LIVE sin input() explícito + 2FA simulada.
"""
from __future__ import annotations

import logging
import os

from core.domain import Env, Signal

log = logging.getLogger("executor")


class HitLDenied(RuntimeError):
    """Se intentó operar en LIVE sin autorización humana válida."""


class Executor:
    def __init__(self, env: Env | None = None) -> None:
        raw = os.environ.get("ENV", "PAPER")
        self._env = env or Env(raw)

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
            return {"status": "LIVE_ORDER_SENT", "symbol": signal.symbol, "side": signal.side.value}
        return {"status": "PAPER_FILL", "symbol": signal.symbol, "side": signal.side.value}
