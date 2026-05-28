"""Oracle — Ingesta de datos de mercado vía WebSocket asíncrono.

Productor de TickEvents hacia The Omnibus. No bloquea el loop (skill: hft_async).
"""

from __future__ import annotations

import json
import logging

from core.domain import Event, EventType, Tick
from core.the_omnibus import TheOmnibus

log = logging.getLogger("oracle")


class Oracle:
    def __init__(self, bus: TheOmnibus) -> None:
        self._bus = bus

    async def ingest(self, raw: str | bytes) -> None:
        """Parsea un mensaje crudo del WS y publica un TickEvent."""
        try:
            data = json.loads(raw)
            tick = Tick(**data)
        except (ValueError, TypeError) as exc:
            log.debug("Tick malformado descartado: %s", exc)
            return
        await self._bus.publish(Event(type=EventType.TICK, payload=tick.model_dump()))
