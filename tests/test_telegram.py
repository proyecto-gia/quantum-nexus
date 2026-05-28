"""Tests para TelegramAlerts — sin red real, aiohttp mockeado."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from telemetry.telegram_alerts import TelegramAlerts


def _mock_session(status: int = 200) -> MagicMock:
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.closed = False
    session.post = MagicMock(return_value=mock_resp)
    session.close = AsyncMock()
    return session


# ── Sin configuración ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_telegram_no_config_skips_http() -> None:
    """Sin token/chat_id no se hace ninguna llamada HTTP."""
    alerts = TelegramAlerts()
    session = _mock_session()
    alerts._session = session
    await alerts.send("test message")
    session.post.assert_not_called()


@pytest.mark.asyncio
async def test_telegram_enabled_only_with_both_vars() -> None:
    alerts = TelegramAlerts()
    assert not alerts.enabled
    alerts._token = "tok"
    assert not alerts.enabled
    alerts._chat_id = "123"
    assert alerts.enabled


# ── Envío exitoso ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_telegram_send_success_no_retry() -> None:
    alerts = TelegramAlerts(min_interval_s=0.0)
    alerts._token = "token"
    alerts._chat_id = "123"
    session = _mock_session(status=200)
    alerts._session = session

    await alerts.send("hello", retries=3)
    assert session.post.call_count == 1


@pytest.mark.asyncio
async def test_telegram_send_includes_level_in_text() -> None:
    alerts = TelegramAlerts(min_interval_s=0.0)
    alerts._token = "token"
    alerts._chat_id = "123"
    session = _mock_session(status=200)
    alerts._session = session

    await alerts.send("aegis tripped", level="CRITICAL", retries=1)

    call_kwargs = session.post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
    assert "[CRITICAL]" in payload["text"]
    assert "aegis tripped" in payload["text"]


# ── Reintentos ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_telegram_retries_on_http_error() -> None:
    """HTTP 503 los primeros 2 intentos, 200 al tercero."""
    alerts = TelegramAlerts(min_interval_s=0.0)
    alerts._token = "token"
    alerts._chat_id = "123"

    call_count = 0

    mock_resp_fail = AsyncMock()
    mock_resp_fail.status = 503
    mock_resp_fail.__aenter__ = AsyncMock(return_value=mock_resp_fail)
    mock_resp_fail.__aexit__ = AsyncMock(return_value=False)

    mock_resp_ok = AsyncMock()
    mock_resp_ok.status = 200
    mock_resp_ok.__aenter__ = AsyncMock(return_value=mock_resp_ok)
    mock_resp_ok.__aexit__ = AsyncMock(return_value=False)

    def post_side_effect(*args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        return mock_resp_ok if call_count >= 3 else mock_resp_fail

    session = MagicMock()
    session.closed = False
    session.post = MagicMock(side_effect=post_side_effect)
    session.close = AsyncMock()
    alerts._session = session

    await alerts.send("msg", retries=3)
    assert call_count == 3


@pytest.mark.asyncio
async def test_telegram_exhausts_retries_silently() -> None:
    """Si todos los reintentos fallan, no propaga excepción."""
    alerts = TelegramAlerts(min_interval_s=0.0)
    alerts._token = "token"
    alerts._chat_id = "123"
    session = _mock_session(status=500)
    alerts._session = session

    await alerts.send("msg", retries=2)  # debe terminar sin excepción
    assert session.post.call_count == 2


# ── Rate limiting ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_telegram_rate_limit_delays_second_send() -> None:
    """Dos envíos rápidos deben tardar >= min_interval_s en total."""
    alerts = TelegramAlerts(min_interval_s=0.05)
    alerts._token = "token"
    alerts._chat_id = "123"
    session = _mock_session(status=200)
    alerts._session = session

    start = time.monotonic()
    await alerts.send("msg1", retries=1)
    await alerts.send("msg2", retries=1)
    elapsed = time.monotonic() - start

    assert elapsed >= 0.04  # margen holgado (0.05 nominal, CI puede ser lento)


@pytest.mark.asyncio
async def test_telegram_critical_skips_rate_limit() -> None:
    """CRITICAL no espera el rate limit."""
    alerts = TelegramAlerts(min_interval_s=5.0)
    alerts._token = "token"
    alerts._chat_id = "123"
    session = _mock_session(status=200)
    alerts._session = session
    alerts._last_send = time.monotonic()  # simula envío reciente

    start = time.monotonic()
    await alerts.send("emergency", level="CRITICAL", retries=1)
    elapsed = time.monotonic() - start

    assert elapsed < 1.0  # CRITICAL no esperó los 5s


# ── close() ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_telegram_close_closes_session() -> None:
    alerts = TelegramAlerts()
    session = _mock_session()
    alerts._session = session

    await alerts.close()
    session.close.assert_called_once()


@pytest.mark.asyncio
async def test_telegram_close_noop_without_session() -> None:
    """close() no falla si nunca se abrió sesión."""
    alerts = TelegramAlerts()
    await alerts.close()  # no debe lanzar
