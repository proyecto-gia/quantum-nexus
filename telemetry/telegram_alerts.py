"""Telegram Alerts — Notificaciones críticas e inquebrantables.

Mejoras sobre el stub original:
  - Sesión aiohttp reutilizada (no crea una por mensaje).
  - Rate limiter: min 1 s entre mensajes para respetar límites de Telegram.
    Mensajes CRITICAL saltan el rate limit.
  - close() para apagado limpio.
  - El fallo del canal NUNCA tumba el sistema.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

import aiohttp

log = logging.getLogger("telegram")

_SEND_PATH = "/sendMessage"


class TelegramAlerts:
    def __init__(self, min_interval_s: float = 1.0) -> None:
        self._token = os.environ.get("TELEGRAM_TOKEN", "")
        self._chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        self._min_interval_s = min_interval_s
        self._session: aiohttp.ClientSession | None = None
        self._last_send: float = 0.0
        self._lock: asyncio.Lock | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._token and self._chat_id)

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
            )
        return self._session

    async def send(self, text: str, level: str = "INFO", retries: int = 3) -> None:
        if not self.enabled:
            log.debug("Telegram no configurado; alerta local: [%s] %s", level, text)
            return

        # Rate limit: esperar si el último envío fue hace menos de min_interval_s
        # CRITICAL salta la cola para llegar siempre de inmediato.
        if level != "CRITICAL":
            async with self._get_lock():
                now = time.monotonic()
                wait = self._min_interval_s - (now - self._last_send)
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last_send = time.monotonic()
        else:
            async with self._get_lock():
                self._last_send = time.monotonic()

        url = f"https://api.telegram.org/bot{self._token}{_SEND_PATH}"
        payload = {"chat_id": self._chat_id, "text": f"[{level}] {text}"}

        for attempt in range(retries):
            try:
                session = self._get_session()
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        return
                    log.warning(
                        "Telegram HTTP %d (intento %d/%d)", resp.status, attempt + 1, retries
                    )
            except Exception as exc:
                log.warning("Fallo Telegram (intento %d/%d): %s", attempt + 1, retries, exc)
            if attempt < retries - 1:
                await asyncio.sleep(2**attempt)

        log.error("Alerta no entregada tras %d intentos: [%s] %s", retries, level, text)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
