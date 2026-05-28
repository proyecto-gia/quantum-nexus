"""Optimizer — grid search de hiperparámetros con split train / test OOS.

Evita overfitting: los parámetros se eligen sobre el conjunto de entrenamiento
(primeros 2/3 de los ticks) y se validan sobre el conjunto de test (último 1/3).

Métricas de ranking (train):
  score = total_return_pct / max(max_drawdown_pct, 1.0)   (Calmar aproximado)

Grilla default para 1h:
  fast       : [8, 12, 16]
  slow       : [20, 26, 34]
  min_conf   : [0.55, 0.60, 0.65, 0.70]
  w_ema      : [0.40, 0.50, 0.60]
  w_vol      : [0.15, 0.25, 0.35]
  (w_roc = 1 - w_ema - w_vol; se descarta si < 0)
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

from backtesting.backtester import BacktestResult, Backtester
from core.cortex_ai import MomentumEMAStrategy
from core.domain import Tick


@dataclass
class ParamGrid:
    fast: list[int] = field(default_factory=lambda: [8, 12, 16])
    slow: list[int] = field(default_factory=lambda: [20, 26, 34])
    min_conf: list[float] = field(default_factory=lambda: [0.55, 0.60, 0.65, 0.70])
    w_ema: list[float] = field(default_factory=lambda: [0.40, 0.50, 0.60])
    w_vol: list[float] = field(default_factory=lambda: [0.15, 0.25, 0.35])


@dataclass
class OptResult:
    params: dict[str, Any]
    train: BacktestResult
    test: BacktestResult | None = None

    @property
    def train_score(self) -> float:
        """Calmar aproximado: retorno / max_drawdown (mayor = mejor)."""
        dd = max(self.train.max_drawdown_pct, 1.0)
        return self.train.total_return_pct / dd

    @property
    def test_score(self) -> float:
        if self.test is None:
            return 0.0
        dd = max(self.test.max_drawdown_pct, 1.0)
        return self.test.total_return_pct / dd


def run_grid(
    ticks: list[Tick],
    grid: ParamGrid,
    symbol: str,
    interval: str,
    days: int,
    train_fraction: float = 0.67,
    top_n: int = 10,
    progress: bool = True,
) -> list[OptResult]:
    """Corre el grid search y devuelve los top_n resultados ordenados por test_score."""
    split = int(len(ticks) * train_fraction)
    train_ticks = ticks[:split]
    test_ticks = ticks[split:]

    combos = list(itertools.product(grid.fast, grid.slow, grid.min_conf, grid.w_ema, grid.w_vol))
    total = len(combos)
    results: list[OptResult] = []

    for i, (fast, slow, min_conf, w_ema, w_vol) in enumerate(combos):
        if progress and (i % max(1, total // 20) == 0 or i == total - 1):
            pct = int((i + 1) / total * 100)
            bar = "#" * (pct // 5) + "." * (20 - pct // 5)
            print(f"\r  [{bar}] {pct:3d}%  {i+1}/{total}", end="", flush=True)

        if fast >= slow:
            continue
        w_roc = round(1.0 - w_ema - w_vol, 6)
        if w_roc < 0.05:  # peso mínimo para ROC
            continue

        params: dict[str, Any] = {
            "fast": fast,
            "slow": slow,
            "min_conf": min_conf,
            "w_ema": w_ema,
            "w_vol": w_vol,
            "w_roc": w_roc,
        }

        def _make_strategy(p: dict[str, Any]) -> MomentumEMAStrategy:
            return MomentumEMAStrategy(
                fast=p["fast"],
                slow=p["slow"],
                min_conf=p["min_conf"],
                w_ema=p["w_ema"],
                w_vol=p["w_vol"],
                w_roc=p["w_roc"],
            )

        train_result = Backtester(_make_strategy(params)).run(
            train_ticks, symbol=symbol, interval=interval, days=days
        )

        if train_result.n_trades < 5:
            continue

        test_result = (
            Backtester(_make_strategy(params)).run(
                test_ticks, symbol=symbol, interval=interval, days=days
            )
            if test_ticks
            else None
        )

        # Descartar si el test tiene muy pocos trades (no estadísticamente significativo)
        if test_result is not None and test_result.n_trades < 3:
            continue

        results.append(OptResult(params=params, train=train_result, test=test_result))

    if progress:
        print()

    results.sort(key=lambda r: r.test_score if r.test is not None else r.train_score, reverse=True)
    return results[:top_n]
