"""Risk Auditor Node — Intercepta y valida criptográficamente cada señal.

Zero-Trust: verifica la firma HMAC y consulta el estado del Aegis antes de
permitir que una señal llegue al Executor.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os

from core.domain import Signal
from core.the_aegis import Aegis

log = logging.getLogger("risk_auditor")


class RiskAuditor:
    def __init__(self, aegis: Aegis) -> None:
        self._aegis = aegis
        self._secret = os.environ.get("HMAC_SECRET", "").encode()

    def _valid_signature(self, signal: Signal) -> bool:
        if not signal.signature:
            return False
        expected = hmac.new(self._secret, signal.canonical_bytes(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signal.signature)

    def approve(self, signal: Signal) -> bool:
        """True sólo si: Aegis seguro Y firma válida."""
        if not self._aegis.is_safe():
            log.critical("Señal rechazada: Aegis TRIPPED (%s).", self._aegis.reason)
            return False
        if not self._valid_signature(signal):
            log.critical("Señal rechazada: firma HMAC inválida.")
            return False
        return True
