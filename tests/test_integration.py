"""Test de integración end-to-end: Tick → Omnibus → Orchestrator → PAPER_FILL."""

from __future__ import annotations

import asyncio

import pytest

from agents.orchestrator_node import Orchestrator
from agents.risk_auditor_node import RiskAuditor
from core.cortex_ai import CortexAI, _StubStrategy
from core.domain import Event, EventType, Tick
from core.the_aegis import Aegis
from core.the_omnibus import TheOmnibus
from core.domain import Env
from execution.executor_node import Executor
from execution.oracle import Oracle


@pytest.fixture(autouse=True)
def hmac_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMAC_SECRET", "integration-test-secret")
    monkeypatch.setenv("ENV", "PAPER")


@pytest.mark.asyncio
async def test_full_pipeline_paper_fill() -> None:
    """Un tick válido recorre todo el pipeline y produce un PAPER_FILL."""
    bus = TheOmnibus(queue_size=100)
    aegis = Aegis()
    cortex = CortexAI(strategy=_StubStrategy())
    auditor = RiskAuditor(aegis=aegis)
    executor = Executor(env=Env.PAPER)
    oracle = Oracle(bus)
    orchestrator = Orchestrator(cortex=cortex, auditor=auditor, executor=executor)

    results: list[dict[str, str]] = []

    async def on_tick(event: Event) -> None:
        tick = Tick(**event.payload)
        result = await orchestrator.handle_tick(tick)
        if result:
            results.append(result)

    bus.subscribe(EventType.TICK, on_tick)

    bus_task = asyncio.create_task(bus.run())

    # Inyectar un tick con volumen > 0 para que CortexAI genere señal
    await oracle.ingest('{"symbol":"BTCUSDT","price":65000.0,"volume":1.5,"timestamp":1000000}')
    await asyncio.sleep(0.05)

    bus.stop()
    bus_task.cancel()
    try:
        await bus_task
    except asyncio.CancelledError:
        pass

    assert len(results) == 1
    assert results[0]["status"] == "PAPER_FILL"
    assert results[0]["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_pipeline_rejects_zero_volume() -> None:
    """Un tick con volumen 0 no produce resultado (CortexAI devuelve None)."""
    bus = TheOmnibus(queue_size=100)
    aegis = Aegis()
    cortex = CortexAI(strategy=_StubStrategy())
    auditor = RiskAuditor(aegis=aegis)
    executor = Executor(env=Env.PAPER)
    oracle = Oracle(bus)
    orchestrator = Orchestrator(cortex=cortex, auditor=auditor, executor=executor)

    results: list[dict[str, str]] = []

    async def on_tick(event: Event) -> None:
        tick = Tick(**event.payload)
        result = await orchestrator.handle_tick(tick)
        if result:
            results.append(result)

    bus.subscribe(EventType.TICK, on_tick)
    bus_task = asyncio.create_task(bus.run())

    await oracle.ingest('{"symbol":"BTCUSDT","price":65000.0,"volume":0.0,"timestamp":1000000}')
    await asyncio.sleep(0.05)

    bus.stop()
    bus_task.cancel()
    try:
        await bus_task
    except asyncio.CancelledError:
        pass

    assert len(results) == 0


@pytest.mark.asyncio
async def test_pipeline_blocked_when_aegis_tripped() -> None:
    """Con Aegis tripped, el auditor rechaza toda señal."""
    bus = TheOmnibus(queue_size=100)
    aegis = Aegis()
    aegis._trip("test")
    cortex = CortexAI(strategy=_StubStrategy())
    auditor = RiskAuditor(aegis=aegis)
    executor = Executor(env=Env.PAPER)
    oracle = Oracle(bus)
    orchestrator = Orchestrator(cortex=cortex, auditor=auditor, executor=executor)

    results: list[dict[str, str]] = []

    async def on_tick(event: Event) -> None:
        tick = Tick(**event.payload)
        result = await orchestrator.handle_tick(tick)
        if result:
            results.append(result)

    bus.subscribe(EventType.TICK, on_tick)
    bus_task = asyncio.create_task(bus.run())

    await oracle.ingest('{"symbol":"BTCUSDT","price":65000.0,"volume":1.5,"timestamp":1000000}')
    await asyncio.sleep(0.05)

    bus.stop()
    bus_task.cancel()
    try:
        await bus_task
    except asyncio.CancelledError:
        pass

    assert len(results) == 1
    assert results[0]["status"] == "REJECTED"


@pytest.mark.asyncio
async def test_oracle_drops_malformed_tick() -> None:
    """Ticks malformados no rompen el pipeline."""
    bus = TheOmnibus(queue_size=100)
    oracle = Oracle(bus)
    received: list[Event] = []

    async def collect(e: Event) -> None:
        received.append(e)

    bus.subscribe(EventType.TICK, collect)
    bus_task = asyncio.create_task(bus.run())

    await oracle.ingest("not-json-at-all")
    await oracle.ingest('{"missing_fields": true}')
    await asyncio.sleep(0.05)

    bus.stop()
    bus_task.cancel()
    try:
        await bus_task
    except asyncio.CancelledError:
        pass

    assert len(received) == 0
