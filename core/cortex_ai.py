"""Cortex AI — Motor de decisión cuantitativa.

NOTA DE DISEÑO (> ultrathink): aquí vive la arquitectura matemática. El skeleton
expone la interfaz y un scorer multifactor stub. La lógica real (microestructura,
order-flow imbalance, modelos RL) se inyecta respetando la interfaz Strategy.

Cada Signal se firma con HMAC antes de emitirse (skill: zero_trust).
"""
from __future__ import annotations

import hashlib
import hmac
import os
from abc import ABC, abstractmethod

from core.domain import Side, Signal, Tick


class Strategy(ABC):
    """Interfaz de estrategia. Implementaciones: VolatilitySniper, GridTrader, etc."""

    @abstractmethod
    def evaluate(self, tick: Tick) -> Signal | None:
        """Devuelve una Signal (sin firmar) o None si no hay edge."""
        ...


class _BaselineScorer(Strategy):
    """Stub determinista de ejemplo. Reemplazar por el motor cuantitativo real."""

    def evaluate(self, tick: Tick) -> Signal | None:
        # Placeholder: sin edge real. Sólo demuestra el contrato.
        if tick.volume <= 0:
            return None
        side = Side.FLAT
        return Signal(symbol=tick.symbol, side=side, confidence=0.0)


class CortexAI:
    def __init__(self, strategy: Strategy | None = None) -> None:
        self._strategy = strategy or _BaselineScorer()
        self._secret = os.environ.get("HMAC_SECRET", "").encode()

    def _sign(self, signal: Signal) -> str:
        return hmac.new(self._secret, signal.canonical_bytes(), hashlib.sha256).hexdigest()

    def decide(self, tick: Tick) -> Signal | None:
        signal = self._strategy.evaluate(tick)
        if signal is None:
            return None
        signal.signature = self._sign(signal)
        return signal
