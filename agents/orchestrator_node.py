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
from telemetry.supabase_sink import SupabaseSink

log = logging.getLogger("orchestrator")


class Orchestrator:
    def __init__(
        self,
        cortex: CortexAI,
        auditor: RiskAuditor,
        executor: Executor,
        sink: SupabaseSink | None = None,
    ) -> None:
        self._cortex = cortex
        self._auditor = auditor
        self._executor = executor
        self._sink = sink

    async def handle_tick(self, tick: Tick) -> dict[str, str] | None:
        signal = self._cortex.decide(tick)  # nodo: decide
        if signal is None:
            return None

        if self._sink:
            await self._sink.log(
                symbol=signal.symbol,
                event_type="SIGNAL",
                payload={"side": signal.side.value, "confidence": signal.confidence},
                signature=signal.signature,
            )

        if not self._auditor.approve(signal):  # nodo: audit (Zero-Trust)
            if self._sink:
                await self._sink.log(
                    symbol=signal.symbol,
                    event_type="REJECT",
                    payload={"reason": "auditor_reject"},
                    severity="WARNING",
                )
            return {"status": "REJECTED"}

        result = await self._executor.execute(signal)  # nodo: execute (HitL si LIVE)

        if self._sink:
            await self._sink.log(
                symbol=signal.symbol,
                event_type="ORDER",
                payload=dict(result),
                signature=signal.signature,
            )

        return result
