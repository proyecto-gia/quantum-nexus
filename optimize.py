"""optimize.py — CLI para grid search de hiperparámetros de MomentumEMAStrategy.

Uso:
    python optimize.py                              # BTCUSDT 1h 180d top 10
    python optimize.py --symbol ETHUSDT --days 270
    python optimize.py --top 5 --days 365

Split: 67% train → 33% test (out-of-sample).
Los parámetros se eligen por Calmar (retorno/drawdown) en train y
se ranquean por Calmar en test para evitar overfitting.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from backtesting.data_loader import fetch_klines
from backtesting.optimizer import ParamGrid, run_grid


def _fmt(val: float, pct: bool = True, sign: bool = True) -> str:
    s = f"{val:+.2f}%" if sign and pct else f"{val:.2f}%" if pct else f"{val:.2f}"
    return s


def _print_table(results: list, train_days: int, test_days: int) -> None:  # type: ignore[type-arg]
    from backtesting.optimizer import OptResult

    typed: list[OptResult] = results

    header = (
        f"{'#':>3}  {'fast':>4}  {'slow':>4}  {'min_c':>5}  "
        f"{'w_ema':>5}  {'w_vol':>5}  {'w_roc':>5}  "
        f"{'TRAIN ret':>9}  {'TRAIN mdd':>9}  {'TRAIN sh':>8}  "
        f"{'TEST ret':>8}  {'TEST mdd':>8}  {'TEST sh':>7}  {'trades':>6}"
    )
    sep = "-" * len(header)
    print(f"\n  Train: {train_days}d   Test (OOS): {test_days}d")
    print(sep)
    print(header)
    print(sep)

    for rank, r in enumerate(typed, 1):
        p = r.params
        tr = r.train
        te = r.test
        test_ret = _fmt(te.total_return_pct) if te else "  n/a  "
        test_mdd = f"-{te.max_drawdown_pct:.2f}%" if te else "  n/a  "
        test_sh = f"{te.sharpe_ratio:.2f}" if te else "  n/a"
        test_tr = te.n_trades if te else 0

        marker = " *" if rank == 1 else "  "
        print(
            f"{rank:>3}{marker}"
            f"{p['fast']:>4}  {p['slow']:>4}  {p['min_conf']:>5.2f}  "
            f"{p['w_ema']:>5.2f}  {p['w_vol']:>5.2f}  {p['w_roc']:>5.2f}  "
            f"{_fmt(tr.total_return_pct):>9}  -{tr.max_drawdown_pct:.2f}%{'':<3}  "
            f"{tr.sharpe_ratio:>8.2f}  "
            f"{test_ret:>8}  {test_mdd:>8}  {test_sh:>7}  {test_tr:>6}"
        )
    print(sep)

    if typed:
        best = typed[0]
        p = best.params
        print(
            f"\n  Mejor configuracion OOS:\n"
            f"    MomentumEMAStrategy(\n"
            f"        fast={p['fast']}, slow={p['slow']},\n"
            f"        min_conf={p['min_conf']},\n"
            f"        w_ema={p['w_ema']}, w_vol={p['w_vol']}, w_roc={p['w_roc']}\n"
            f"    )\n"
        )


async def run(symbol: str, interval: str, days: int, top: int) -> int:
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

    grid = ParamGrid()
    n_combos = (
        len(grid.fast) * len(grid.slow) * len(grid.min_conf) * len(grid.w_ema) * len(grid.w_vol)
    )
    print(f"Grid search: ~{n_combos} combinaciones (fast×slow×min_conf×w_ema×w_vol)")

    results = run_grid(
        ticks=ticks,
        grid=grid,
        symbol=symbol,
        interval=interval,
        days=days,
        top_n=top,
    )

    if not results:
        print("Sin resultados validos (pocos trades). Prueba con mas dias.")
        return 1

    train_days = int(days * 0.67)
    test_days = days - train_days
    _print_table(results, train_days, test_days)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Grid search de MomentumEMAStrategy")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument(
        "--interval",
        default="1h",
        choices=["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
    )
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    sys.exit(asyncio.run(run(args.symbol, args.interval, args.days, args.top)))


if __name__ == "__main__":
    main()
