"""Cortex AI — Motor de decisión cuantitativa.

Estrategia por defecto: MomentumEMAStrategy — scoring multifactor que combina
EMA crossover (12/26), confirmación de volumen y Rate-of-Change a 5 períodos.

_StubStrategy queda disponible para tests que verifican el pipeline, no la matemática.
Cada Signal se firma con HMAC antes de emitirse (skill: zero_trust).
"""

from __future__ import annotations

import hashlib
import hmac
import os
from abc import ABC, abstractmethod
from collections import deque

from core.domain import Side, Signal, Tick


class Strategy(ABC):
    @abstractmethod
    def evaluate(self, tick: Tick) -> Signal | None: ...


class _StubStrategy(Strategy):
    """Stub determinista para tests de pipeline. No usar en producción."""

    def evaluate(self, tick: Tick) -> Signal | None:
        if tick.volume <= 0:
            return None
        return Signal(symbol=tick.symbol, side=Side.FLAT, confidence=0.75)


class MomentumEMAStrategy(Strategy):
    """Estrategia multifactor para paper trading (fase bootstrapping).

    Factores y pesos:
      - EMA crossover fast(12) / slow(26)  → W = 0.50  dirección de tendencia
      - Volume surge vs media móvil(20)    → W = 0.25  confirma fuerza
      - Rate of Change(5 períodos)         → W = 0.25  momentum a corto plazo

    Reglas:
      - Warm-up: requiere SLOW ticks antes de emitir la primera señal.
      - Si ROC contradice la dirección del EMA crossover su peso se anula.
      - Solo se emite señal cuando confidence >= MIN_CONF.
    """

    FAST: int = 12
    SLOW: int = 26
    VOL_MA: int = 20
    ROC_N: int = 5
    MIN_CONF: float = 0.55

    W_EMA: float = 0.50
    W_VOL: float = 0.25
    W_ROC: float = 0.25

    def __init__(self) -> None:
        self._prices: deque[float] = deque(maxlen=self.SLOW + self.ROC_N + 1)
        self._volumes: deque[float] = deque(maxlen=self.VOL_MA)
        self._ema_fast: float | None = None
        self._ema_slow: float | None = None
        self._alpha_fast: float = 2.0 / (self.FAST + 1)
        self._alpha_slow: float = 2.0 / (self.SLOW + 1)

    def _update_emas(self, price: float) -> None:
        if self._ema_fast is None or self._ema_slow is None:
            self._ema_fast = price
            self._ema_slow = price
        else:
            self._ema_fast = self._alpha_fast * price + (1.0 - self._alpha_fast) * self._ema_fast
            self._ema_slow = self._alpha_slow * price + (1.0 - self._alpha_slow) * self._ema_slow

    def evaluate(self, tick: Tick) -> Signal | None:
        self._prices.append(tick.price)
        self._volumes.append(tick.volume)
        self._update_emas(tick.price)

        if len(self._prices) < self.SLOW or self._ema_fast is None or self._ema_slow is None:
            return None  # warm-up

        # ── Factor 1: EMA crossover ──────────────────────────────────────────
        ema_diff_rel = (self._ema_fast - self._ema_slow) / self._ema_slow
        ema_strength = min(abs(ema_diff_rel) * 100.0, 1.0)
        side = Side.BUY if ema_diff_rel > 0.0 else Side.SELL

        # ── Factor 2: Volume surge ───────────────────────────────────────────
        avg_vol = sum(self._volumes) / len(self._volumes) if self._volumes else 1.0
        vol_ratio = tick.volume / avg_vol if avg_vol > 0.0 else 1.0
        vol_strength = min(vol_ratio / 2.0, 1.0)

        # ── Factor 3: Rate of Change ─────────────────────────────────────────
        prices_list = list(self._prices)
        roc_strength = 0.0
        roc_confirms = True
        if len(prices_list) >= self.ROC_N + 1:
            past = prices_list[-(self.ROC_N + 1)]
            if past > 0.0:
                roc = (tick.price - past) / past
                roc_strength = min(abs(roc) * 50.0, 1.0)
                roc_confirms = (roc > 0.0) == (side == Side.BUY)

        if not roc_confirms:
            roc_strength = 0.0  # momentum contradice al EMA → descuento

        # ── Confianza ponderada ──────────────────────────────────────────────
        confidence = (
            self.W_EMA * ema_strength + self.W_VOL * vol_strength + self.W_ROC * roc_strength
        )

        if confidence < self.MIN_CONF:
            return None

        return Signal(symbol=tick.symbol, side=side, confidence=round(confidence, 4))


class CortexAI:
    def __init__(self, strategy: Strategy | None = None) -> None:
        self._strategy = strategy or MomentumEMAStrategy()
        self._secret = os.environ.get("HMAC_SECRET", "").encode()

    def _sign(self, signal: Signal) -> str:
        return hmac.new(self._secret, signal.canonical_bytes(), hashlib.sha256).hexdigest()

    def decide(self, tick: Tick) -> Signal | None:
        signal = self._strategy.evaluate(tick)
        if signal is None:
            return None
        signal.signature = self._sign(signal)
        return signal
