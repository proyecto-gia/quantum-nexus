"""Tests para SupabaseSink y la integración con Orchestrator."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.orchestrator_node import Orchestrator
from agents.risk_auditor_node import RiskAuditor
from core.cortex_ai import CortexAI, _StubStrategy
from core.domain import Env, Tick
from core.the_aegis import Aegis
from execution.executor_node import Executor
from telemetry.supabase_sink import SupabaseSink


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_mock_session(status: int = 201) -> MagicMock:
    """Returns a fake aiohttp.ClientSession whose post() is a context manager."""
    resp = AsyncMock()
    resp.status = status
    resp.text = AsyncMock(return_value="")
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    session.post = MagicMock(return_value=resp)
    return session


# ── SupabaseSink unit tests ───────────────────────────────────────────────────


def test_sink_disabled_without_env_vars() -> None:
    sink = SupabaseSink()
    assert not sink.enabled


def test_sink_enabled_with_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "fake-key")
    sink = SupabaseSink()
    assert sink.enabled


@pytest.mark.asyncio
async def test_sink_log_noop_when_disabled() -> None:
    sink = SupabaseSink()
    assert not sink.enabled
    # Should complete without error and make no HTTP calls
    await sink.log("BTCUSDT", "ORDER", {"status": "PAPER_FILL"})
    assert len(sink._tasks) == 0


@pytest.mark.asyncio
async def test_sink_log_posts_correct_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "fake-key")
    monkeypatch.setenv("ENV", "PAPER")

    sink = SupabaseSink()
    mock_session = _make_mock_session(201)
    sink._session = mock_session

    await sink.log(
        symbol="BTCUSDT",
        event_type="ORDER",
        payload={"status": "PAPER_FILL"},
        signature="abc123",
        severity="INFO",
    )
    await asyncio.sleep(0.02)

    mock_session.post.assert_called_once()
    _, kwargs = mock_session.post.call_args
    body: dict[str, Any] = kwargs["json"]
    assert body["symbol"] == "BTCUSDT"
    assert body["event_type"] == "ORDER"
    assert body["env"] == "PAPER"
    assert body["signature"] == "abc123"
    assert body["severity"] == "INFO"
    assert body["payload"] == {"status": "PAPER_FILL"}


@pytest.mark.asyncio
async def test_sink_log_omits_signature_when_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "fake-key")

    sink = SupabaseSink()
    mock_session = _make_mock_session(201)
    sink._session = mock_session

    await sink.log("BTCUSDT", "REJECT", {"reason": "auditor_reject"}, signature=None)
    await asyncio.sleep(0.02)

    _, kwargs = mock_session.post.call_args
    assert "signature" not in kwargs["json"]


@pytest.mark.asyncio
async def test_sink_swallows_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "fake-key")

    sink = SupabaseSink()
    mock_session = _make_mock_session(status=500)
    sink._session = mock_session

    # Should not raise
    await sink.log("BTCUSDT", "ORDER", {})
    await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_sink_swallows_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "fake-key")

    sink = SupabaseSink()
    broken_session = MagicMock()
    broken_session.closed = False
    broken_session.post = MagicMock(side_effect=OSError("connection refused"))
    sink._session = broken_session

    # Should not raise
    await sink.log("BTCUSDT", "ORDER", {})
    await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_sink_close_awaits_pending_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "fake-key")

    sink = SupabaseSink()
    mock_session = _make_mock_session(201)
    sink._session = mock_session

    await sink.log("BTCUSDT", "ORDER", {})
    await sink.close()

    mock_session.close.assert_called_once()


# ── Orchestrator + sink integration ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_orchestrator_logs_signal_and_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMAC_SECRET", "test-secret")  # pragma: allowlist secret
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "fake-key")

    logged: list[tuple[str, str]] = []

    sink = SupabaseSink()
    sink.enabled = False  # intercept at log() level

    original_log = sink.log

    async def capture(
        symbol: str,
        event_type: str,
        payload: dict[str, Any],
        signature: str | None = None,
        severity: str = "INFO",
    ) -> None:
        logged.append((symbol, event_type))
        await original_log(symbol, event_type, payload, signature, severity)

    sink.log = capture  # type: ignore[method-assign]

    cortex = CortexAI(strategy=_StubStrategy())
    auditor = RiskAuditor(aegis=Aegis())
    executor = Executor(env=Env.PAPER)
    orchestrator = Orchestrator(cortex=cortex, auditor=auditor, executor=executor, sink=sink)

    tick = Tick(symbol="BTCUSDT", price=65000.0, volume=1.5)
    result = await orchestrator.handle_tick(tick)

    assert result is not None
    assert result["status"] == "PAPER_FILL"
    assert ("BTCUSDT", "SIGNAL") in logged
    assert ("BTCUSDT", "ORDER") in logged


@pytest.mark.asyncio
async def test_orchestrator_logs_reject(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMAC_SECRET", "test-secret")  # pragma: allowlist secret

    logged: list[tuple[str, str]] = []

    sink = SupabaseSink()
    sink.enabled = False

    async def capture(
        symbol: str,
        event_type: str,
        payload: dict[str, Any],
        signature: str | None = None,
        severity: str = "INFO",
    ) -> None:
        logged.append((symbol, event_type))

    sink.log = capture  # type: ignore[method-assign]

    aegis = Aegis()
    aegis._trip("test")
    cortex = CortexAI(strategy=_StubStrategy())
    auditor = RiskAuditor(aegis=aegis)
    executor = Executor(env=Env.PAPER)
    orchestrator = Orchestrator(cortex=cortex, auditor=auditor, executor=executor, sink=sink)

    tick = Tick(symbol="BTCUSDT", price=65000.0, volume=1.5)
    result = await orchestrator.handle_tick(tick)

    assert result == {"status": "REJECTED"}
    assert ("BTCUSDT", "SIGNAL") in logged
    assert ("BTCUSDT", "REJECT") in logged
