"""Orchestrator Node — Gestiona el flujo de estado global y la delegación.

Esqueleto compatible con un grafo de estados estilo LangGraph: define los nodos
(decide -> audit -> execute) y el cableado. La lógica de grafo real se inyecta
respetando estos contratos.
"""

from __future__ import annotations

import logging

from agents.risk_auditor_node import RiskAuditor
from core.cortex_ai import CortexAI
from core.domain import Tick
from execution.executor_node import Executor

log = logging.getLogger("orchestrator")


class Orchestrator:
    def __init__(self, cortex: CortexAI, auditor: RiskAuditor, executor: Executor) -> None:
        self._cortex = cortex
        self._auditor = auditor
        self._executor = executor

    async def handle_tick(self, tick: Tick) -> dict[str, str] | None:
        signal = self._cortex.decide(tick)  # nodo: decide
        if signal is None:
            return None
        if not self._auditor.approve(signal):  # nodo: audit (Zero-Trust)
            return {"status": "REJECTED"}
        return await self._executor.execute(signal)  # nodo: execute (HitL si LIVE)
