"""Tests para el motor de backtesting (sin red — datos sintéticos)."""

from __future__ import annotations

import math


from backtesting.backtester import Backtester, BacktestResult
from core.cortex_ai import MomentumEMAStrategy
from core.domain import Tick


def _ticks(prices: list[float], symbol: str = "BTCUSDT", volume: float = 1.0) -> list[Tick]:
    return [
        Tick(symbol=symbol, price=p, volume=volume, timestamp=i * 3_600_000)
        for i, p in enumerate(prices)
    ]


def _uptrend(n: int, start: float = 60_000.0, step_pct: float = 0.006) -> list[float]:
    prices = [start]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + step_pct))
    return prices


def _downtrend(n: int, start: float = 60_000.0, step_pct: float = 0.006) -> list[float]:
    prices = [start]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 - step_pct))
    return prices


def _flat(n: int, price: float = 60_000.0) -> list[float]:
    return [price] * n


# ── BacktestResult structure ──────────────────────────────────────────────────


def test_empty_ticks_returns_zero_result() -> None:
    bt = Backtester(MomentumEMAStrategy())
    result = bt.run([], symbol="BTCUSDT", interval="1h", days=1)
    assert result.n_ticks == 0
    assert result.n_trades == 0
    assert result.total_return_pct == 0.0


def test_no_signal_during_warmup() -> None:
    """Menos de SLOW ticks → sin trades."""
    bt = Backtester(MomentumEMAStrategy())
    ticks = _ticks(_uptrend(MomentumEMAStrategy.SLOW - 1))
    result = bt.run(ticks, symbol="BTCUSDT")
    assert result.n_signals == 0
    assert result.n_trades == 0


# ── Trade mechanics ───────────────────────────────────────────────────────────


def test_uptrend_then_downtrend_produces_buy_trade() -> None:
    """Up → down: abre BUY durante uptrend, lo cierra cuando llega la señal SELL."""
    bt = Backtester(MomentumEMAStrategy())
    # 60 ticks subiendo, luego 60 ticks bajando → garantiza flip BUY→SELL
    prices = _uptrend(60) + _downtrend(60, start=_uptrend(60)[-1])
    result = bt.run(_ticks(prices), symbol="BTCUSDT")
    buy_trades = [t for t in result.trades if t.side.value == "BUY"]
    assert len(buy_trades) > 0


def test_downtrend_then_uptrend_produces_sell_trade() -> None:
    """Down → up: abre SELL durante downtrend, lo cierra cuando llega la señal BUY."""
    bt = Backtester(MomentumEMAStrategy())
    prices = _downtrend(60) + _uptrend(60, start=_downtrend(60)[-1])
    result = bt.run(_ticks(prices), symbol="BTCUSDT")
    sell_trades = [t for t in result.trades if t.side.value == "SELL"]
    assert len(sell_trades) > 0


def test_flat_produces_no_trades() -> None:
    bt = Backtester(MomentumEMAStrategy())
    ticks = _ticks(_flat(100))
    result = bt.run(ticks, symbol="BTCUSDT")
    assert result.n_trades == 0


# ── Metrics correctness ───────────────────────────────────────────────────────


def test_total_return_positive_on_uptrend() -> None:
    bt = Backtester(MomentumEMAStrategy())
    prices = _uptrend(80) + _downtrend(40, start=_uptrend(80)[-1])
    result = bt.run(_ticks(prices), symbol="BTCUSDT")
    if result.n_trades > 0:
        assert result.total_return_pct > 0.0


def test_buy_hold_computed_correctly() -> None:
    prices = _uptrend(80)
    bt = Backtester(MomentumEMAStrategy())
    result = bt.run(_ticks(prices), symbol="BTCUSDT")
    expected = round((prices[-1] - prices[0]) / prices[0] * 100, 2)
    assert result.buy_hold_pct == expected


def test_win_rate_between_0_and_100() -> None:
    bt = Backtester(MomentumEMAStrategy())
    ticks = _ticks(_uptrend(100))
    result = bt.run(ticks, symbol="BTCUSDT")
    if result.n_trades > 0:
        assert 0.0 <= result.win_rate <= 100.0


def test_max_drawdown_non_negative() -> None:
    bt = Backtester(MomentumEMAStrategy())
    ticks = _ticks(_uptrend(100))
    result = bt.run(ticks, symbol="BTCUSDT")
    assert result.max_drawdown_pct >= 0.0


def test_sharpe_zero_when_all_returns_identical() -> None:
    """Si todos los trades tienen el mismo retorno → std=0 → Sharpe=0."""
    from backtesting.backtester import Trade, _fill_metrics
    from core.domain import Side

    trades = [
        Trade(symbol="X", side=Side.BUY, entry_price=100.0, exit_price=101.0, entry_ts=0, exit_ts=1)
        for _ in range(5)
    ]
    result = BacktestResult(symbol="X", interval="1h", days=1, n_ticks=10, n_signals=5, n_trades=5)
    _fill_metrics(result, trades)
    assert result.sharpe_ratio == 0.0


def test_trade_pnl_long_profitable() -> None:
    from backtesting.backtester import Trade
    from core.domain import Side

    t = Trade(symbol="X", side=Side.BUY, entry_price=100.0, exit_price=110.0, entry_ts=0, exit_ts=1)
    assert math.isclose(t.pnl_pct, 0.10, rel_tol=1e-6)


def test_trade_pnl_short_profitable() -> None:
    from backtesting.backtester import Trade
    from core.domain import Side

    t = Trade(
        symbol="X", side=Side.SELL, entry_price=110.0, exit_price=100.0, entry_ts=0, exit_ts=1
    )
    assert math.isclose(t.pnl_pct, 10.0 / 110.0, rel_tol=1e-6)
