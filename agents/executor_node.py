"""Executor Node (Agents layer) — Conecta el event bus con el exchange adapter.

Actúa como puente LangGraph-style: recibe eventos del Omnibus, extrae el payload
Signal, y delega al Executor de la capa execution. Mantiene el conteo de órdenes
emitidas y rechazos para el Command Center.
"""
from __future__ import annotations

import logging

from core.domain import Event, EventType, Signal
from core.the_aegis import Aegis
from core.the_omnibus import TheOmnibus
from execution.executor_node import Executor

log = logging.getLogger("agent.executor")


class ExecutorAgentNode:
    """Nodo agente que suscribe SIGNAL events y los ejecuta via Executor."""

    def __init__(self, bus: TheOmnibus, executor: Executor, aegis: Aegis) -> None:
        self._executor = executor
        self._aegis = aegis
        self._orders: int = 0
        self._rejects: int = 0
        bus.subscribe(EventType.SIGNAL, self._on_signal)
        bus.subscribe(EventType.KILL, self._on_kill)

    async def _on_signal(self, event: Event) -> None:
        if not self._aegis.is_safe():
            log.critical("ExecutorAgentNode: Aegis TRIPPED — señal descartada.")
            self._rejects += 1
            return
        try:
            signal = Signal(**event.payload)
        except Exception as exc:
            log.error("Payload de señal inválido: %s", exc)
            self._rejects += 1
            return
        result = await self._executor.execute(signal)
        self._orders += 1
        log.info("Orden emitida: %s", result)

    async def _on_kill(self, event: Event) -> None:
        log.critical("KillSwitchEvent recibido — ExecutorAgentNode detenido.")

    @property
    def stats(self) -> dict[str, int]:
        return {"orders": self._orders, "rejects": self._rejects}
