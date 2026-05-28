"""Observer — Métricas, health checks y guardia anti memory-leak."""

from __future__ import annotations

import logging

import psutil

log = logging.getLogger("observer")


class Observer:
    def __init__(self) -> None:
        self._proc = psutil.Process()
        self._baseline_rss: int | None = None

    def mark_baseline(self) -> None:
        self._baseline_rss = int(self._proc.memory_info().rss)

    def rss_delta_mb(self) -> float:
        if self._baseline_rss is None:
            return 0.0
        return (int(self._proc.memory_info().rss) - self._baseline_rss) / (1024 * 1024)
