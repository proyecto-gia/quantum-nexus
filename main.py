"""Quantum Nexus v9 — Entrypoint principal.

Levanta el pipeline completo:
  Oracle (ticks) → Omnibus (bus) → Orchestrator (decide/audit/execute)
  → Observer + CommandCenter (telemetría) → Telegram (alertas)

El estado por defecto es PAPER. Ctrl+C detiene el sistema limpiamente.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from agents.executor_node import ExecutorAgentNode
from agents.orchestrator_node import Orchestrator
from agents.risk_auditor_node import RiskAuditor
from core.cortex_ai import CortexAI
from core.domain import Event, EventType, Tick
from core.the_aegis import Aegis, RiskLimits
from core.the_omnibus import TheOmnibus
from execution.binance_ws import BinanceWebSocketClient
from execution.executor_node import Executor
from execution.oracle import Oracle
from telemetry.command_center import CommandCenter
from telemetry.observer import Observer
from telemetry.supabase_sink import SupabaseSink
from telemetry.telegram_alerts import TelegramAlerts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("main")

ENV = os.environ.get("ENV", "PAPER")
# SYMBOLS=BTCUSDT  o  SYMBOLS=BTCUSDT,ETHUSDT  →  feed real de Binance
# Vacío → modo demo con ticks sintéticos
SYMBOLS = [s.strip() for s in os.environ.get("SYMBOLS", "").split(",") if s.strip()]


async def _demo_tick_producer(bus: TheOmnibus, oracle: Oracle, stop: asyncio.Event) -> None:
    """Genera ticks sintéticos cuando no hay WS_URL configurada (modo demo)."""
    import json
    import random
    import time

    log.info("Modo demo: produciendo ticks sintéticos a 10 ticks/s.")
    while not stop.is_set():
        raw = json.dumps(
            {
                "symbol": "BTCUSDT",
                "price": random.uniform(58_000.0, 72_000.0),
                "volume": random.uniform(0.01, 2.0),
                "timestamp": int(time.time() * 1000),
            }
        )
        await oracle.ingest(raw)
        await asyncio.sleep(0.1)


async def _tick_handler(event: Event, orchestrator: Orchestrator, center: CommandCenter) -> None:
    tick = Tick(**event.payload)
    result = await orchestrator.handle_tick(tick)
    if result:
        center.update("last_result", result)
        log.info("Pipeline result: %s", result)


async def run() -> None:
    log.info("Quantum Nexus v9 arrancando — ENV=%s", ENV)

    # ── Wiring ────────────────────────────────────────────────────────────────
    bus = TheOmnibus(queue_size=10_000)
    aegis = Aegis(limits=RiskLimits())
    cortex = CortexAI()
    auditor = RiskAuditor(aegis=aegis)
    executor = Executor()
    sink = SupabaseSink()
    oracle = Oracle(bus)
    orchestrator = Orchestrator(cortex=cortex, auditor=auditor, executor=executor, sink=sink)
    observer = Observer()
    center = CommandCenter()
    telegram = TelegramAlerts()
    ExecutorAgentNode(bus=bus, executor=executor, aegis=aegis)

    if sink.enabled:
        log.info("Supabase sink activo — telemetria habilitada.")
    else:
        log.info("Supabase sink deshabilitado (SUPABASE_URL/KEY no configuradas).")

    observer.mark_baseline()

    # Suscribir el pipeline al bus
    async def on_tick(event: Event) -> None:
        await _tick_handler(event, orchestrator, center)

    bus.subscribe(EventType.TICK, on_tick)

    # ── Señal de parada limpia ────────────────────────────────────────────────
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
    except NotImplementedError:
        # Windows no soporta add_signal_handler; KeyboardInterrupt detiene el loop.
        pass

    await telegram.send("Quantum Nexus v9 iniciado", level="INFO")
    log.info("Pipeline listo. Ctrl+C para detener.")

    # ── Tareas concurrentes ───────────────────────────────────────────────────
    bus_task = asyncio.create_task(bus.run(), name="omnibus")

    if SYMBOLS:
        log.info("Binance feed activo — symbols=%s", SYMBOLS)
        ws_client = BinanceWebSocketClient(symbols=SYMBOLS, oracle=oracle)
        producer_task = asyncio.create_task(ws_client.run(stop), name="binance_ws")
    else:
        log.info("Modo demo: ticks sinteticos a 10 ticks/s.")
        producer_task = asyncio.create_task(
            _demo_tick_producer(bus, oracle, stop), name="demo_producer"
        )

    # ── Health report cada 30 s ───────────────────────────────────────────────
    async def health_loop() -> None:
        while not stop.is_set():
            await asyncio.sleep(30)
            delta = observer.rss_delta_mb()
            dropped = bus.dropped
            snap = center.snapshot()
            log.info(
                "HEALTH | aegis=%s | dropped=%d | ram_delta=%.2fMB | last=%s",
                "OK" if aegis.is_safe() else f"TRIPPED({aegis.reason})",
                dropped,
                delta,
                snap.get("last_result", "—"),
            )
            if not aegis.is_safe():
                await telegram.send(f"AEGIS TRIPPED: {aegis.reason}", level="CRITICAL")

    health_task = asyncio.create_task(health_loop(), name="health")

    await stop.wait()

    log.info("Deteniendo Quantum Nexus...")
    producer_task.cancel()
    health_task.cancel()
    bus.stop()
    bus_task.cancel()

    await asyncio.gather(producer_task, health_task, bus_task, return_exceptions=True)

    await sink.close()

    log.info(
        "Apagado limpio | dropped=%d | ram_delta=%.2fMB",
        bus.dropped,
        observer.rss_delta_mb(),
    )
    await telegram.send("Quantum Nexus detenido", level="INFO")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
