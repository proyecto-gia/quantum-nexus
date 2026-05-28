"""Command Center — Estado global consolidado del ecosistema.

Métricas rastreadas en tiempo real:
  - P&L total (USDT) y drawdown desde el pico
  - Win rate y conteo de trades cerrados
  - Señales por minuto (ventana deslizante 60 s)
  - Tiempo desde el último tick (salud del WS feed)
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass
class _TradeMetrics:
    total: int = 0
    wins: int = 0
    total_pnl_usdt: float = 0.0
    peak_pnl_usdt: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.total if self.total else 0.0

    @property
    def drawdown_pct(self) -> float:
        """Drawdown desde el pico, en % (siempre >= 0)."""
        dd = self.peak_pnl_usdt - self.total_pnl_usdt
        return max(dd / self.peak_pnl_usdt * 100.0, 0.0) if self.peak_pnl_usdt > 0 else 0.0


class CommandCenter:
    def __init__(self) -> None:
        self._state: dict[str, Any] = {}
        self._trades = _TradeMetrics()
        self._signal_times: deque[float] = deque(maxlen=200)
        self._last_tick_ts: float = 0.0

    # ── Registro de eventos ───────────────────────────────────────────────────

    def update(self, key: str, value: Any) -> None:
        self._state[key] = value

    def record_tick(self) -> None:
        self._last_tick_ts = time.monotonic()

    def record_signal(self) -> None:
        self._signal_times.append(time.monotonic())

    def record_fill(self, pnl_usdt: float) -> None:
        """Registra un trade cerrado. pnl_usdt=0.0 cuando solo se abre posición."""
        if pnl_usdt == 0.0:
            return
        self._trades.total += 1
        self._trades.total_pnl_usdt += pnl_usdt
        if pnl_usdt > 0.0:
            self._trades.wins += 1
        if self._trades.total_pnl_usdt > self._trades.peak_pnl_usdt:
            self._trades.peak_pnl_usdt = self._trades.total_pnl_usdt

    # ── Propiedades derivadas ─────────────────────────────────────────────────

    @property
    def signals_per_min(self) -> float:
        now = time.monotonic()
        return float(sum(1 for t in self._signal_times if now - t < 60.0))

    @property
    def last_tick_age_s(self) -> float:
        return time.monotonic() - self._last_tick_ts if self._last_tick_ts > 0.0 else -1.0

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        t = self._trades
        return {
            **self._state,
            "trades": t.total,
            "win_rate": f"{t.win_rate:.1%}",
            "total_pnl_usdt": round(t.total_pnl_usdt, 4),
            "drawdown_pct": round(t.drawdown_pct, 2),
            "signals_per_min": round(self.signals_per_min, 1),
            "last_tick_age_s": round(self.last_tick_age_s, 1),
        }
