"""Supabase Sink — Telemetría inmutable de señales y órdenes.

Escribe en `trade_logs` via PostgREST (INSERT-only, RLS activo).
Fire-and-forget: nunca bloquea ni propaga excepciones al pipeline.
Se deshabilita automáticamente si SUPABASE_URL o SUPABASE_KEY no están seteadas.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import aiohttp

log = logging.getLogger("supabase_sink")

_ENDPOINT = "rest/v1/trade_logs"


class SupabaseSink:
    def __init__(self) -> None:
        self._url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        self._key = os.environ.get("SUPABASE_KEY", "")
        self._env = os.environ.get("ENV", "PAPER")
        self._session: aiohttp.ClientSession | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self.enabled: bool = bool(self._url and self._key)

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "apikey": self._key,
                    "Authorization": f"Bearer {self._key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                }
            )
        return self._session

    async def log(
        self,
        symbol: str,
        event_type: str,
        payload: dict[str, Any],
        signature: str | None = None,
        severity: str = "INFO",
    ) -> None:
        if not self.enabled:
            return
        task = asyncio.create_task(self._insert(symbol, event_type, payload, signature, severity))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _insert(
        self,
        symbol: str,
        event_type: str,
        payload: dict[str, Any],
        signature: str | None,
        severity: str,
    ) -> None:
        body: dict[str, Any] = {
            "env": self._env,
            "symbol": symbol,
            "event_type": event_type,
            "payload": payload,
            "severity": severity,
        }
        if signature is not None:
            body["signature"] = signature
        try:
            session = self._get_session()
            async with session.post(
                f"{self._url}/{_ENDPOINT}",
                json=body,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status not in (200, 201):
                    text = await resp.text()
                    log.warning("Supabase insert failed: HTTP %d — %s", resp.status, text[:200])
        except Exception:
            log.warning("Supabase insert error", exc_info=True)

    async def close(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
