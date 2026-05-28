"""Backtester — motor de simulación de trades sobre datos históricos.

Modelo de posición: siempre invertido (flip en cada señal).
  FLAT → BUY (long) → SELL (flip a short) → BUY (flip a long) → ...

Métricas calculadas:
  total_return_pct   — retorno compuesto de todos los trades
  buy_hold_pct       — retorno de comprar en T0 y vender en T_final
  win_rate           — porcentaje de trades positivos
  avg_win_pct        — ganancia media de trades ganadores
  avg_loss_pct       — pérdida media de trades perdedores (valor positivo)
  max_drawdown_pct   — máxima caída desde un pico de equity
  sharpe_ratio       — Sharpe por trade (sin anualizar)
  n_trades           — número de trades cerrados
  n_signals          — número total de señales emitidas
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from core.cortex_ai import Strategy
from core.domain import Side, Tick


@dataclass
class Trade:
    symbol: str
    side: Side
    entry_price: float
    exit_price: float
    entry_ts: int
    exit_ts: int

    @property
    def pnl_pct(self) -> float:
        if self.side == Side.BUY:
            return (self.exit_price - self.entry_price) / self.entry_price
        return (self.entry_price - self.exit_price) / self.entry_price


@dataclass
class BacktestResult:
    symbol: str
    interval: str
    days: int
    n_ticks: int
    n_signals: int
    n_trades: int
    trades: list[Trade] = field(default_factory=list, repr=False)

    total_return_pct: float = 0.0
    buy_hold_pct: float = 0.0
    win_rate: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0


class Backtester:
    def __init__(self, strategy: Strategy) -> None:
        self._strategy = strategy

    def run(
        self, ticks: list[Tick], symbol: str, interval: str = "1h", days: int = 0
    ) -> BacktestResult:
        if not ticks:
            return BacktestResult(
                symbol=symbol,
                interval=interval,
                days=days,
                n_ticks=0,
                n_signals=0,
                n_trades=0,
            )

        trades: list[Trade] = []
        n_signals = 0
        position_side: Side | None = None
        entry_price: float = 0.0
        entry_ts: int = 0

        for tick in ticks:
            signal = self._strategy.evaluate(tick)
            if signal is None or signal.side == Side.FLAT:
                continue

            n_signals += 1
            new_side = signal.side

            if position_side is None:
                # Abrir primera posición
                position_side = new_side
                entry_price = tick.price
                entry_ts = tick.timestamp
            elif new_side != position_side:
                # Flip: cerrar posición actual y abrir la opuesta
                trades.append(
                    Trade(
                        symbol=tick.symbol,
                        side=position_side,
                        entry_price=entry_price,
                        exit_price=tick.price,
                        entry_ts=entry_ts,
                        exit_ts=tick.timestamp,
                    )
                )
                position_side = new_side
                entry_price = tick.price
                entry_ts = tick.timestamp

        buy_hold_pct = (
            (ticks[-1].price - ticks[0].price) / ticks[0].price if len(ticks) > 1 else 0.0
        )

        result = BacktestResult(
            symbol=symbol,
            interval=interval,
            days=days,
            n_ticks=len(ticks),
            n_signals=n_signals,
            n_trades=len(trades),
            trades=trades,
            buy_hold_pct=round(buy_hold_pct * 100, 2),
        )

        if not trades:
            return result

        _fill_metrics(result, trades)
        return result


def _fill_metrics(result: BacktestResult, trades: list[Trade]) -> None:
    returns = [t.pnl_pct for t in trades]

    # Equity curve (starts at 1.0)
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        equity *= 1.0 + r
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak
        if dd > max_dd:
            max_dd = dd

    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]

    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    std_r = math.sqrt(variance) if variance > 0 else 0.0

    result.total_return_pct = round((equity - 1.0) * 100, 2)
    result.win_rate = round(len(wins) / len(trades) * 100, 1)
    result.avg_win_pct = round(sum(wins) / len(wins) * 100, 2) if wins else 0.0
    result.avg_loss_pct = round(abs(sum(losses) / len(losses)) * 100, 2) if losses else 0.0
    result.max_drawdown_pct = round(max_dd * 100, 2)
    result.sharpe_ratio = round(mean_r / std_r, 2) if std_r > 0 else 0.0
