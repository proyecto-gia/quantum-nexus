"""backtest.py — CLI para correr MomentumEMAStrategy sobre datos históricos de Binance.

Uso:
    python backtest.py                            # BTCUSDT 1h 90 días
    python backtest.py --symbol ETHUSDT --days 30
    python backtest.py --symbol BTCUSDT --interval 4h --days 180
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from backtesting.backtester import BacktestResult, Backtester
from backtesting.data_loader import fetch_klines
from core.cortex_ai import MomentumEMAStrategy


def _print_report(r: BacktestResult) -> None:
    sep = "-" * 44
    alpha = round(r.total_return_pct - r.buy_hold_pct, 2)
    alpha_sign = "+" if alpha >= 0 else ""
    ret_sign = "+" if r.total_return_pct >= 0 else ""
    bh_sign = "+" if r.buy_hold_pct >= 0 else ""

    print(f"\nBacktest: {r.symbol} | {r.interval} | {r.days} dias")
    print(sep)
    print(f"  Ticks procesados : {r.n_ticks:,}")
    print(f"  Senales emitidas : {r.n_signals:,}")
    print(f"  Trades cerrados  : {r.n_trades:,}")
    print(sep)
    if r.n_trades == 0:
        print("  Sin trades — periodo demasiado corto para el warm-up.")
    else:
        print(f"  Retorno total    : {ret_sign}{r.total_return_pct:.2f}%")
        print(f"  Buy & hold       : {bh_sign}{r.buy_hold_pct:.2f}%")
        print(f"  Alpha            : {alpha_sign}{alpha:.2f}%")
        print(sep)
        print(f"  Win rate         : {r.win_rate:.1f}%")
        print(f"  Avg ganancia     : +{r.avg_win_pct:.2f}%")
        print(f"  Avg perdida      : -{r.avg_loss_pct:.2f}%")
        print(f"  Max drawdown     : -{r.max_drawdown_pct:.2f}%")
        print(f"  Sharpe (x-trade) : {r.sharpe_ratio:.2f}")
    print(sep)


async def run(symbol: str, interval: str, days: int) -> int:
    print(
        f"Descargando {days} dias de klines {symbol}/{interval} desde Binance...",
        end=" ",
        flush=True,
    )
    try:
        ticks = await fetch_klines(symbol=symbol, interval=interval, days=days)
    except Exception as exc:
        print(f"\nError al descargar datos: {exc}", file=sys.stderr)
        return 1

    print(f"{len(ticks):,} velas OK")

    strategy = MomentumEMAStrategy()
    backtester = Backtester(strategy)
    result = backtester.run(ticks, symbol=symbol, interval=interval, days=days)
    _print_report(result)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest de MomentumEMAStrategy")
    parser.add_argument("--symbol", default="BTCUSDT", help="Par (ej. BTCUSDT, ETHUSDT)")
    parser.add_argument(
        "--interval",
        default="1h",
        choices=["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
        help="Intervalo de velas",
    )
    parser.add_argument("--days", type=int, default=90, help="Dias de historia a analizar")
    args = parser.parse_args()

    sys.exit(asyncio.run(run(args.symbol, args.interval, args.days)))


if __name__ == "__main__":
    main()
