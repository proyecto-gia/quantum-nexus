"""Tests unitarios para CommandCenter."""

from __future__ import annotations


import pytest

from telemetry.command_center import CommandCenter


def test_snapshot_empty_defaults() -> None:
    center = CommandCenter()
    snap = center.snapshot()
    assert snap["trades"] == 0
    assert snap["win_rate"] == "0.0%"
    assert snap["total_pnl_usdt"] == 0.0
    assert snap["drawdown_pct"] == 0.0
    assert snap["signals_per_min"] == 0.0


def test_record_tick_updates_age() -> None:
    center = CommandCenter()
    assert center.last_tick_age_s == pytest.approx(-1.0)
    center.record_tick()
    assert 0.0 <= center.last_tick_age_s < 1.0


def test_record_signal_counts_within_window() -> None:
    center = CommandCenter()
    for _ in range(5):
        center.record_signal()
    assert center.signals_per_min == pytest.approx(5.0)


def test_record_fill_zero_pnl_ignored() -> None:
    center = CommandCenter()
    center.record_fill(0.0)
    snap = center.snapshot()
    assert snap["trades"] == 0


def test_record_fill_win() -> None:
    center = CommandCenter()
    center.record_fill(1.5)
    snap = center.snapshot()
    assert snap["trades"] == 1
    assert snap["win_rate"] == "100.0%"
    assert snap["total_pnl_usdt"] == pytest.approx(1.5)
    assert snap["drawdown_pct"] == 0.0


def test_record_fill_loss() -> None:
    center = CommandCenter()
    center.record_fill(2.0)
    center.record_fill(-1.0)
    snap = center.snapshot()
    assert snap["trades"] == 2
    assert snap["win_rate"] == "50.0%"
    assert snap["total_pnl_usdt"] == pytest.approx(1.0)


def test_drawdown_calculation() -> None:
    center = CommandCenter()
    center.record_fill(10.0)  # peak = 10
    center.record_fill(-4.0)  # pnl = 6, dd = 4/10 = 40%
    snap = center.snapshot()
    assert snap["drawdown_pct"] == pytest.approx(40.0)


def test_drawdown_zero_when_at_peak() -> None:
    center = CommandCenter()
    center.record_fill(5.0)
    center.record_fill(3.0)  # new peak = 8, dd = 0
    snap = center.snapshot()
    assert snap["drawdown_pct"] == 0.0


def test_update_arbitrary_key() -> None:
    center = CommandCenter()
    center.update("last_result", {"status": "FILLED"})
    snap = center.snapshot()
    assert snap["last_result"] == {"status": "FILLED"}
