"""Tests unitarios para el núcleo de Quantum Nexus."""
from __future__ import annotations

import asyncio
import os

import pytest

from core.domain import Env, Event, EventType, Side, Signal, Tick
from core.the_aegis import Aegis, RiskLimits
from core.the_omnibus import TheOmnibus
from core.cortex_ai import CortexAI
from agents.risk_auditor_node import RiskAuditor
from execution.executor_node import Executor, HitLDenied


# ── Domain ──────────────────────────────────────────────────────────────────

def test_tick_defaults():
    t = Tick(symbol="BTCUSDT", price=60000.0, volume=1.0)
    assert t.symbol == "BTCUSDT"
    assert t.timestamp > 0


def test_signal_canonical_bytes_stable():
    s = Signal(symbol="BTCUSDT", side=Side.BUY, confidence=0.9, timestamp=1_000_000)
    b1 = s.canonical_bytes()
    b2 = s.canonical_bytes()
    assert b1 == b2


# ── Aegis ────────────────────────────────────────────────────────────────────

def test_aegis_safe_by_default():
    aegis = Aegis()
    assert aegis.is_safe()


def test_aegis_trips_on_drawdown():
    aegis = Aegis(limits=RiskLimits(max_drawdown_pct=3.0))
    aegis.check_drawdown(3.5)
    assert aegis.tripped
    assert "Drawdown" in (aegis.reason or "")


def test_aegis_trips_on_latency():
    aegis = Aegis(limits=RiskLimits(max_latency_ms=100.0))
    aegis.check_latency(200.0)
    assert aegis.tripped


def test_aegis_trips_on_drops():
    aegis = Aegis(limits=RiskLimits(max_dropped_pct=0.5))
    aegis.check_drops(1.0)
    assert aegis.tripped


def test_aegis_reset():
    aegis = Aegis()
    aegis.check_drawdown(99.0)
    assert aegis.tripped
    aegis.reset()
    assert not aegis.tripped
    assert aegis.reason is None


def test_aegis_only_trips_once():
    aegis = Aegis()
    aegis.check_drawdown(99.0)
    first_reason = aegis.reason
    aegis.check_latency(9999.0)
    assert aegis.reason == first_reason  # primera causa preservada


# ── Risk Auditor ─────────────────────────────────────────────────────────────

def test_risk_auditor_rejects_tripped_aegis(monkeypatch):
    monkeypatch.setenv("HMAC_SECRET", "test-secret")
    aegis = Aegis()
    aegis._trip("forced")
    auditor = RiskAuditor(aegis=aegis)
    signal = Signal(symbol="BTCUSDT", side=Side.BUY, confidence=0.8, signature="any")
    assert not auditor.approve(signal)


def test_risk_auditor_rejects_invalid_signature(monkeypatch):
    monkeypatch.setenv("HMAC_SECRET", "test-secret")
    aegis = Aegis()
    auditor = RiskAuditor(aegis=aegis)
    signal = Signal(symbol="BTCUSDT", side=Side.BUY, confidence=0.8, signature="bad-sig")
    assert not auditor.approve(signal)


def test_risk_auditor_approves_valid_signature(monkeypatch):
    import hashlib
    import hmac as hmac_mod
    secret = "test-secret"
    monkeypatch.setenv("HMAC_SECRET", secret)
    aegis = Aegis()
    auditor = RiskAuditor(aegis=aegis)
    signal = Signal(symbol="BTCUSDT", side=Side.BUY, confidence=0.8, timestamp=1_000_000)
    sig = hmac_mod.new(secret.encode(), signal.canonical_bytes(), hashlib.sha256).hexdigest()
    signal.signature = sig
    assert auditor.approve(signal)


# ── CortexAI ─────────────────────────────────────────────────────────────────

def test_cortex_decide_returns_signed_signal(monkeypatch):
    monkeypatch.setenv("HMAC_SECRET", "nexus-secret")
    cortex = CortexAI()
    tick = Tick(symbol="BTCUSDT", price=60000.0, volume=1.0)
    signal = cortex.decide(tick)
    assert signal is not None
    assert signal.signature is not None
    assert len(signal.signature) == 64  # SHA-256 hex digest


def test_cortex_decide_returns_none_on_zero_volume(monkeypatch):
    monkeypatch.setenv("HMAC_SECRET", "nexus-secret")
    cortex = CortexAI()
    tick = Tick(symbol="BTCUSDT", price=60000.0, volume=0.0)
    assert cortex.decide(tick) is None


# ── Executor ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_executor_paper_fill(monkeypatch):
    monkeypatch.setenv("ENV", "PAPER")
    executor = Executor(env=Env.PAPER)
    signal = Signal(symbol="ETHUSDT", side=Side.SELL, confidence=0.7)
    result = await executor.execute(signal)
    assert result["status"] == "PAPER_FILL"
    assert result["symbol"] == "ETHUSDT"


# ── The Omnibus ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_omnibus_pub_sub():
    bus = TheOmnibus(queue_size=100)
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(EventType.TICK, handler)

    task = asyncio.create_task(bus.run())
    await bus.publish(Event(type=EventType.TICK, payload={"symbol": "BTCUSDT"}))
    await asyncio.sleep(0.05)
    bus.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(received) == 1
    assert received[0].type == EventType.TICK


@pytest.mark.asyncio
async def test_omnibus_drops_when_full():
    bus = TheOmnibus(queue_size=1)
    # Llenar la cola sin consumir
    await bus.publish(Event(type=EventType.TICK, payload={}))
    await bus.publish(Event(type=EventType.TICK, payload={}))  # debe dropearse
    assert bus.dropped >= 1
