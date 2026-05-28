"""Risk Auditor Node — Intercepta y valida criptográficamente cada señal.

Zero-Trust: verifica la firma HMAC, consulta el Aegis y aplica límites de riesgo
duros antes de permitir que una señal llegue al Executor.

Límites gestionados:
  - Firma HMAC-SHA256 del Cortex
  - Confianza mínima (belt-and-suspenders, Cortex ya filtra)
  - Frecuencia máxima de señales (previene estrategia desbocada)
  - Pérdida diaria máxima (trips Aegis si se supera)
  - Pérdidas consecutivas máximas (circuit breaker)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from datetime import date

from core.domain import Side, Signal
from core.the_aegis import Aegis

log = logging.getLogger("risk_auditor")


class RiskAuditor:
    def __init__(
        self,
        aegis: Aegis,
        capital_usdt: float = 100.0,
        max_position_pct: float = 0.10,
        daily_loss_limit_pct: float = 0.03,
        max_consecutive_losses: int = 3,
        min_confidence: float = 0.60,
        min_signal_interval_s: float = 5.0,
    ) -> None:
        self._aegis = aegis
        self._secret = os.environ.get("HMAC_SECRET", "").encode()
        self._capital = capital_usdt
        self._max_notional = capital_usdt * max_position_pct
        self._daily_loss_limit_usdt = capital_usdt * daily_loss_limit_pct
        self._max_consecutive_losses = max_consecutive_losses
        self._min_confidence = min_confidence
        self._min_signal_interval_s = min_signal_interval_s

        self._daily_pnl_usdt: float = 0.0
        self._today: date = date.today()
        self._consecutive_losses: int = 0
        self._last_signal_ts: float = 0.0
        self._open_side: Side | None = None
        self._open_price: float = 0.0
        # Tracking acumulado para drawdown
        self._cumulative_pnl_usdt: float = 0.0
        self._peak_pnl_usdt: float = 0.0

    def _reset_daily_if_needed(self) -> None:
        today = date.today()
        if today != self._today:
            self._daily_pnl_usdt = 0.0
            self._today = today

    def _valid_signature(self, signal: Signal) -> bool:
        if not signal.signature:
            return False
        expected = hmac.new(self._secret, signal.canonical_bytes(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signal.signature)

    def approve(self, signal: Signal) -> bool:
        """True sólo si: Aegis seguro + HMAC válido + todos los límites de riesgo OK."""
        if not self._aegis.is_safe():
            log.critical("Señal rechazada: Aegis TRIPPED (%s).", self._aegis.reason)
            return False

        if not self._valid_signature(signal):
            log.critical("Señal rechazada: firma HMAC inválida.")
            return False

        if signal.confidence < self._min_confidence:
            log.warning(
                "Señal rechazada: confianza %.3f < mínimo %.3f.",
                signal.confidence,
                self._min_confidence,
            )
            return False

        now = time.monotonic()
        elapsed = now - self._last_signal_ts
        if self._last_signal_ts > 0.0 and elapsed < self._min_signal_interval_s:
            log.warning("Señal rechazada: frecuencia excesiva (%.2fs desde última señal).", elapsed)
            return False
        self._last_signal_ts = now

        self._reset_daily_if_needed()
        daily_loss = -self._daily_pnl_usdt
        if daily_loss >= self._daily_loss_limit_usdt:
            loss_pct = daily_loss / self._capital * 100.0
            self._aegis.check_daily_loss(loss_pct)
            log.critical(
                "Señal rechazada: pérdida diaria %.2f USDT >= límite %.2f USDT.",
                daily_loss,
                self._daily_loss_limit_usdt,
            )
            return False

        return True

    def record_fill(self, side: Side, price: float) -> float:
        """Registra un fill ejecutado. Retorna P&L en USDT del trade cerrado (0.0 si solo abre).

        Debe llamarse después de cada ejecución exitosa en el Orchestrator.
        """
        if side not in (Side.BUY, Side.SELL) or price <= 0.0:
            return 0.0

        pnl_usdt = 0.0

        if self._open_side is not None and self._open_side != side and self._open_price > 0.0:
            if self._open_side == Side.BUY:
                pnl_pct = (price - self._open_price) / self._open_price
            else:
                pnl_pct = (self._open_price - price) / self._open_price

            pnl_usdt = pnl_pct * self._max_notional
            self._daily_pnl_usdt += pnl_usdt
            self._cumulative_pnl_usdt += pnl_usdt
            if self._cumulative_pnl_usdt > self._peak_pnl_usdt:
                self._peak_pnl_usdt = self._cumulative_pnl_usdt

            if pnl_usdt < 0.0:
                self._consecutive_losses += 1
                log.warning(
                    "Trade pérdida: %.4f%% (%.4f USDT) — consecutivas: %d",
                    pnl_pct * 100.0,
                    pnl_usdt,
                    self._consecutive_losses,
                )
                if self._consecutive_losses >= self._max_consecutive_losses:
                    self._aegis._trip(
                        f"{self._consecutive_losses} pérdidas consecutivas — circuit breaker"
                    )
            elif pnl_usdt > 0.0:
                self._consecutive_losses = 0
                log.info("Trade ganancia: %.4f%% (%.4f USDT)", pnl_pct * 100.0, pnl_usdt)

            daily_loss = -self._daily_pnl_usdt
            if daily_loss > 0.0:
                self._aegis.check_daily_loss(daily_loss / self._capital * 100.0)

            # Drawdown acumulado desde el pico (puede dispararse incluso sin pérdida diaria)
            dd_usdt = self._peak_pnl_usdt - self._cumulative_pnl_usdt
            if dd_usdt > 0.0:
                self._aegis.check_drawdown(dd_usdt / self._capital * 100.0)

        self._open_side = side
        self._open_price = price
        return pnl_usdt
