"""Telegram Alerts — Notificaciones críticas e inquebrantables.

El fallo del canal NUNCA tumba el sistema (skill: telegram_alert).
"""

from __future__ import annotations

import asyncio
import logging
import os

log = logging.getLogger("telegram")


class TelegramAlerts:
    def __init__(self) -> None:
        self._token = os.environ.get("TELEGRAM_TOKEN", "")
        self._chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    async def send(self, text: str, level: str = "INFO", retries: int = 3) -> None:
        if not self._token or not self._chat_id:
            log.debug("Telegram no configurado; alerta sólo local: [%s] %s", level, text)
            return
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        payload = {"chat_id": self._chat_id, "text": f"[{level}] {text}"}
        for attempt in range(retries):
            try:
                import aiohttp  # import diferido: el módulo no debe romper si falta

                async with aiohttp.ClientSession() as s:
                    async with s.post(
                        url, json=payload, timeout=aiohttp.ClientTimeout(total=5)
                    ) as r:
                        if r.status == 200:
                            return
            except Exception as exc:  # inquebrantable: jamás propaga
                log.warning("Fallo Telegram (intento %d): %s", attempt + 1, exc)
                await asyncio.sleep(2**attempt)
        log.error("Alerta no entregada tras %d intentos: %s", retries, text)
