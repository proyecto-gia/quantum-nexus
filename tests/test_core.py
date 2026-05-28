"""Tests unitarios para el núcleo de Quantum Nexus."""

from __future__ import annotations

import asyncio
import hashlib
import hmac as hmac_mod

import pytest

from agents.risk_auditor_node import RiskAuditor
from core.cortex_ai import CortexAI, MomentumEMAStrategy, _StubStrategy
from core.domain import Env, Event, EventType, Side, Signal, Tick
from core.the_aegis import Aegis, RiskLimits
from core.the_omnibus import TheOmnibus
from execution.executor_node import Executor


# ── Domain ──────────────────────────────────────────────────────────────────


def test_tick_defaults() -> None:
    t = Tick(symbol="BTCUSDT", price=60000.0, volume=1.0)
    assert t.symbol == "BTCUSDT"
    assert t.timestamp > 0


def test_signal_canonical_bytes_stable() -> None:
    s = Signal(symbol="BTCUSDT", side=Side.BUY, confidence=0.9, timestamp=1_000_000)
    b1 = s.canonical_bytes()
    b2 = s.canonical_bytes()
    assert b1 == b2


# ── Aegis ────────────────────────────────────────────────────────────────────


def test_aegis_safe_by_default() -> None:
    aegis = Aegis()
    assert aegis.is_safe()


def test_aegis_trips_on_drawdown() -> None:
    aegis = Aegis(limits=RiskLimits(max_drawdown_pct=3.0))
    aegis.check_drawdown(3.5)
    assert aegis.tripped
    assert "Drawdown" in (aegis.reason or "")


def test_aegis_trips_on_latency() -> None:
    aegis = Aegis(limits=RiskLimits(max_latency_ms=100.0))
    aegis.check_latency(200.0)
    assert aegis.tripped


def test_aegis_trips_on_drops() -> None:
    aegis = Aegis(limits=RiskLimits(max_dropped_pct=0.5))
    aegis.check_drops(1.0)
    assert aegis.tripped


def test_aegis_reset() -> None:
    aegis = Aegis()
    aegis.check_drawdown(99.0)
    assert aegis.tripped
    aegis.reset()
    assert not aegis.tripped
    assert aegis.reason is None


def test_aegis_only_trips_once() -> None:
    aegis = Aegis()
    aegis.check_drawdown(99.0)
    first_reason = aegis.reason
    aegis.check_latency(9999.0)
    assert aegis.reason == first_reason


# ── Risk Auditor ─────────────────────────────────────────────────────────────


def test_risk_auditor_rejects_tripped_aegis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMAC_SECRET", "test-secret")
    aegis = Aegis()
    aegis._trip("forced")
    auditor = RiskAuditor(aegis=aegis)
    signal = Signal(symbol="BTCUSDT", side=Side.BUY, confidence=0.8, signature="any")
    assert not auditor.approve(signal)


def test_risk_auditor_rejects_invalid_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMAC_SECRET", "test-secret")
    aegis = Aegis()
    auditor = RiskAuditor(aegis=aegis)
    signal = Signal(symbol="BTCUSDT", side=Side.BUY, confidence=0.8, signature="bad-sig")
    assert not auditor.approve(signal)


def test_risk_auditor_approves_valid_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "test-secret"  # pragma: allowlist secret
    monkeypatch.setenv("HMAC_SECRET", secret)
    aegis = Aegis()
    auditor = RiskAuditor(aegis=aegis, min_signal_interval_s=0.0)
    signal = Signal(symbol="BTCUSDT", side=Side.BUY, confidence=0.8, timestamp=1_000_000)
    sig = hmac_mod.new(secret.encode(), signal.canonical_bytes(), hashlib.sha256).hexdigest()
    signal.signature = sig
    assert auditor.approve(signal)


def test_risk_auditor_rejects_low_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "test-secret"  # pragma: allowlist secret
    monkeypatch.setenv("HMAC_SECRET", secret)
    aegis = Aegis()
    auditor = RiskAuditor(aegis=aegis, min_confidence=0.75, min_signal_interval_s=0.0)
    signal = Signal(symbol="BTCUSDT", side=Side.BUY, confidence=0.70, timestamp=1_000_000)
    sig = hmac_mod.new(secret.encode(), signal.canonical_bytes(), hashlib.sha256).hexdigest()
    signal.signature = sig
    assert not auditor.approve(signal)


def test_risk_auditor_rejects_signal_spam(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "test-secret"  # pragma: allowlist secret
    monkeypatch.setenv("HMAC_SECRET", secret)
    aegis = Aegis()
    auditor = RiskAuditor(aegis=aegis, min_signal_interval_s=60.0)

    def _signed(ts: int) -> Signal:
        s = Signal(symbol="BTCUSDT", side=Side.BUY, confidence=0.8, timestamp=ts)
        s.signature = hmac_mod.new(secret.encode(), s.canonical_bytes(), hashlib.sha256).hexdigest()
        return s

    assert auditor.approve(_signed(1_000_000))
    assert not auditor.approve(_signed(1_000_001))


def test_risk_auditor_record_fill_tracks_pnl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMAC_SECRET", "test-secret")
    auditor = RiskAuditor(aegis=Aegis(), capital_usdt=100.0, max_position_pct=0.10)
    auditor.record_fill(Side.BUY, 100.0)
    auditor.record_fill(Side.SELL, 110.0)  # +10% en 10 USDT notional = +1 USDT
    assert auditor._daily_pnl_usdt == pytest.approx(1.0)
    assert auditor._consecutive_losses == 0


def test_risk_auditor_resets_streak_on_profit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMAC_SECRET", "test-secret")
    auditor = RiskAuditor(aegis=Aegis(), capital_usdt=100.0, max_consecutive_losses=5)
    auditor.record_fill(Side.BUY, 100.0)
    auditor.record_fill(Side.SELL, 90.0)  # pérdida → consecutivas=1
    assert auditor._consecutive_losses == 1
    auditor.record_fill(Side.BUY, 90.0)
    auditor.record_fill(Side.SELL, 100.0)  # ganancia → consecutivas=0
    assert auditor._consecutive_losses == 0


def test_risk_auditor_trips_aegis_on_consecutive_losses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMAC_SECRET", "test-secret")
    aegis = Aegis()
    auditor = RiskAuditor(aegis=aegis, capital_usdt=100.0, max_consecutive_losses=2)
    auditor.record_fill(Side.BUY, 100.0)
    auditor.record_fill(Side.SELL, 95.0)  # pérdida #1
    assert auditor._consecutive_losses == 1
    assert aegis.is_safe()
    auditor.record_fill(Side.BUY, 95.0)
    auditor.record_fill(Side.SELL, 90.0)  # pérdida #2 → trip (límite=2)
    assert not aegis.is_safe()
    assert "consecutivas" in (aegis.reason or "")


def test_risk_auditor_trips_aegis_on_daily_loss(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMAC_SECRET", "test-secret")
    aegis = Aegis(limits=RiskLimits(max_daily_loss_pct=3.0))
    # capital=100, max_position=50% → notional=50 USDT; daily_loss_limit=3 USDT
    auditor = RiskAuditor(
        aegis=aegis,
        capital_usdt=100.0,
        max_position_pct=0.50,
        daily_loss_limit_pct=0.03,
        max_consecutive_losses=99,
    )
    auditor.record_fill(Side.BUY, 100.0)
    auditor.record_fill(Side.SELL, 90.0)  # -10% * 50 USDT = -5 USDT > 3 USDT límite
    assert not aegis.is_safe()
    assert "diaria" in (aegis.reason or "")


# ── Aegis daily loss ──────────────────────────────────────────────────────────


def test_aegis_trips_on_daily_loss() -> None:
    aegis = Aegis(limits=RiskLimits(max_daily_loss_pct=2.0))
    aegis.check_daily_loss(2.5)
    assert aegis.tripped
    assert "diaria" in (aegis.reason or "")


def test_aegis_safe_below_daily_loss() -> None:
    aegis = Aegis(limits=RiskLimits(max_daily_loss_pct=3.0))
    aegis.check_daily_loss(2.9)
    assert not aegis.tripped


# ── CortexAI ─────────────────────────────────────────────────────────────────


def test_cortex_decide_returns_signed_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMAC_SECRET", "nexus-secret")
    cortex = CortexAI(strategy=_StubStrategy())
    tick = Tick(symbol="BTCUSDT", price=60000.0, volume=1.0)
    signal = cortex.decide(tick)
    assert signal is not None
    assert signal.signature is not None
    assert len(signal.signature) == 64


def test_cortex_decide_returns_none_on_zero_volume(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMAC_SECRET", "nexus-secret")
    cortex = CortexAI(strategy=_StubStrategy())
    tick = Tick(symbol="BTCUSDT", price=60000.0, volume=0.0)
    assert cortex.decide(tick) is None


# ── MomentumEMAStrategy ───────────────────────────────────────────────────────


def _make_ticks(symbol: str, start_price: float, pct_change: float, n: int) -> list[Tick]:
    ticks = []
    price = start_price
    for _ in range(n):
        ticks.append(Tick(symbol=symbol, price=price, volume=1.0))
        price *= 1.0 + pct_change
    return ticks


def test_momentum_ema_no_signal_during_warmup() -> None:
    strategy = MomentumEMAStrategy()
    for tick in _make_ticks("BTCUSDT", 60000.0, 0.005, MomentumEMAStrategy.SLOW - 1):
        assert strategy.evaluate(tick) is None


def test_momentum_ema_buy_on_uptrend() -> None:
    strategy = MomentumEMAStrategy()
    ticks = _make_ticks("BTCUSDT", 60000.0, 0.005, 40)
    signals = [strategy.evaluate(t) for t in ticks]
    buy_signals = [s for s in signals if s is not None and s.side == Side.BUY]
    assert len(buy_signals) > 0
    for s in buy_signals:
        assert MomentumEMAStrategy.MIN_CONF <= s.confidence <= 1.0


def test_momentum_ema_sell_on_downtrend() -> None:
    strategy = MomentumEMAStrategy()
    ticks = _make_ticks("BTCUSDT", 60000.0, -0.005, 40)
    signals = [strategy.evaluate(t) for t in ticks]
    sell_signals = [s for s in signals if s is not None and s.side == Side.SELL]
    assert len(sell_signals) > 0


def test_momentum_ema_no_signal_on_flat_price() -> None:
    strategy = MomentumEMAStrategy()
    ticks = _make_ticks("BTCUSDT", 60000.0, 0.0, 50)
    signals = [s for s in (strategy.evaluate(t) for t in ticks) if s is not None]
    assert len(signals) == 0


# ── Executor ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_executor_paper_fill(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "PAPER")
    executor = Executor(env=Env.PAPER)
    signal = Signal(symbol="ETHUSDT", side=Side.SELL, confidence=0.7)
    result = await executor.execute(signal)
    assert result["status"] == "PAPER_FILL"
    assert result["symbol"] == "ETHUSDT"


# ── The Omnibus ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_omnibus_pub_sub() -> None:
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
async def test_omnibus_drops_when_full() -> None:
    bus = TheOmnibus(queue_size=1)
    await bus.publish(Event(type=EventType.TICK, payload={}))
    await bus.publish(Event(type=EventType.TICK, payload={}))
    assert bus.dropped >= 1
