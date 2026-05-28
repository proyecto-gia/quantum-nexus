"""The Omnibus — Bus de eventos asíncrono central (Pub/Sub en memoria).

Punto único de coordinación entre módulos. Aplica backpressure con colas
acotadas y cuenta los drops (skill: hft_async). El core NO conoce a execution
ni telemetry: éstos se suscriben hacia adentro.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable

from core.domain import Event, EventType

log = logging.getLogger("omnibus")
Handler = Callable[[Event], Awaitable[None]]


class TheOmnibus:
    def __init__(self, queue_size: int = 10_000) -> None:
        self._subs: dict[EventType, list[Handler]] = defaultdict(list)
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=queue_size)
        self._dropped: int = 0
        self._running: bool = False

    @property
    def dropped(self) -> int:
        return self._dropped

    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        self._subs[event_type].append(handler)

    async def publish(self, event: Event) -> None:
        """No bloquea al productor: si la cola está llena, descarta y cuenta el drop."""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._dropped += 1

    async def run(self) -> None:
        self._running = True
        while self._running:
            event = await self._queue.get()
            handlers = self._subs.get(event.type, [])
            if handlers:
                await asyncio.gather(*(h(event) for h in handlers), return_exceptions=True)
            self._queue.task_done()

    def stop(self) -> None:
        self._running = False


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    log.info("The Omnibus inicializado (ENV por defecto: PAPER).")
