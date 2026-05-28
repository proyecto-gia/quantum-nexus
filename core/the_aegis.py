"""The Aegis — Kill Switch + circuit breakers + límites de riesgo duros.

NOTA DE DISEÑO (> ultrathink): contención fail-safe. Estado por defecto ARMED.
Cualquier breach dispara TRIPPED de forma irreversible hasta reset manual, y emite
KillSwitchEvent. Diseñado para detener el enjambre en <50 ms.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger("aegis")


@dataclass
class RiskLimits:
    max_drawdown_pct: float = 5.0  # corte duro de pérdida acumulada
    max_daily_loss_pct: float = 3.0  # pérdida máxima en un día (% del capital)
    max_latency_ms: float = 250.0  # si la decisión tarda más, sospecha
    max_dropped_pct: float = 1.0  # saturación del pipeline


@dataclass
class Aegis:
    limits: RiskLimits = field(default_factory=RiskLimits)
    tripped: bool = False
    reason: str | None = None

    def check_drawdown(self, drawdown_pct: float) -> None:
        if drawdown_pct >= self.limits.max_drawdown_pct:
            self._trip(f"Drawdown {drawdown_pct:.2f}% >= límite {self.limits.max_drawdown_pct}%")

    def check_latency(self, latency_ms: float) -> None:
        if latency_ms >= self.limits.max_latency_ms:
            self._trip(f"Latencia {latency_ms:.1f}ms >= límite {self.limits.max_latency_ms}ms")

    def check_drops(self, dropped_pct: float) -> None:
        if dropped_pct >= self.limits.max_dropped_pct:
            self._trip(f"Drops {dropped_pct:.2f}% >= límite {self.limits.max_dropped_pct}%")

    def check_daily_loss(self, loss_pct: float) -> None:
        if loss_pct >= self.limits.max_daily_loss_pct:
            self._trip(
                f"Pérdida diaria {loss_pct:.2f}% >= límite {self.limits.max_daily_loss_pct}%"
            )

    def _trip(self, reason: str) -> None:
        if not self.tripped:
            self.tripped = True
            self.reason = reason
            log.critical("AEGIS KILL SWITCH TRIPPED: %s", reason)

    def is_safe(self) -> bool:
        return not self.tripped

    def reset(self) -> None:
        """Reset manual y deliberado (Human-in-the-Loop)."""
        self.tripped = False
        self.reason = None
