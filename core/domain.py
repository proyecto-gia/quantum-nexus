"""Modelos de dominio compartidos (Clean Architecture: capa interna, sin deps externas salvo pydantic)."""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Env(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class EventType(str, Enum):
    TICK = "TICK"
    SIGNAL = "SIGNAL"
    ORDER = "ORDER"
    REJECT = "REJECT"
    KILL = "KILL"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    FLAT = "FLAT"


def now_ms() -> int:
    return int(time.time() * 1000)


class Tick(BaseModel):
    symbol: str
    price: float
    volume: float
    timestamp: int = Field(default_factory=now_ms)


class Signal(BaseModel):
    symbol: str
    side: Side
    confidence: float = Field(ge=0.0, le=1.0)
    timestamp: int = Field(default_factory=now_ms)
    signature: str | None = None  # HMAC, lo rellena Cortex y lo verifica el Auditor

    def canonical_bytes(self) -> bytes:
        """Representación canónica determinista para firmar/verificar (sin la firma)."""
        return f"{self.symbol}|{self.side.value}|{self.confidence}|{self.timestamp}".encode()


class Event(BaseModel):
    type: EventType
    payload: dict[str, Any]
    timestamp: int = Field(default_factory=now_ms)
