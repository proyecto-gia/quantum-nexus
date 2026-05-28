"""stress_test.py — MAX CAPACITY TEST para Quantum Nexus.

Mock server (productor de ticks) + cliente receptor, comunicados por una
asyncio.Queue acotada que emula el transporte WebSocket local sin dependencias
de red (determinista y reproducible en CI).

Carga objetivo: 10.000 ticks/s sostenidos durante 60 s.
Payload: {"symbol":"BTCUSDT","price":<float>,"volume":<float>,"timestamp":<ms_unix>}
Métricas: latencia máx/media (ms), % dropped, Δ RAM (memory-leak guard).

Uso:
    python stress_test.py            # corrida completa (10k x 60s)
    python stress_test.py --quick    # corrida corta de humo (10k x 2s)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import time

import psutil

SYMBOL = "BTCUSDT"
TARGET_TPS = 10_000          # ticks por segundo
DEFAULT_DURATION_S = 60      # duración sostenida
QUEUE_SIZE = 10_000          # backpressure: cola acotada


def make_tick() -> bytes:
    payload = {
        "symbol": SYMBOL,
        "price": random.uniform(50_000.0, 70_000.0),
        "volume": random.uniform(0.001, 5.0),
        "timestamp": time.perf_counter_ns(),  # monotónico, para medir latencia real
    }
    return json.dumps(payload).encode()


async def producer(q: asyncio.Queue[bytes], duration_s: int, stats: dict) -> None:
    """Inyecta TARGET_TPS ticks/s. Si la cola está llena -> drop contado (backpressure)."""
    interval = 1.0 / TARGET_TPS
    deadline = time.perf_counter() + duration_s
    next_send = time.perf_counter()
    while time.perf_counter() < deadline:
        try:
            q.put_nowait(make_tick())
            stats["sent"] += 1
        except asyncio.QueueFull:
            stats["dropped"] += 1
        next_send += interval
        sleep_for = next_send - time.perf_counter()
        if sleep_for > 0:
            await asyncio.sleep(sleep_for)
    await q.put(b"__STOP__")


async def consumer(q: asyncio.Queue[bytes], stats: dict) -> None:
    """Recibe, parsea y mide latencia end-to-end por tick."""
    while True:
        raw = await q.get()
        if raw == b"__STOP__":
            q.task_done()
            break
        data = json.loads(raw)
        latency_ms = (time.perf_counter_ns() - data["timestamp"]) / 1_000_000
        stats["received"] += 1
        stats["lat_sum"] += latency_ms
        if latency_ms > stats["lat_max"]:
            stats["lat_max"] = latency_ms
        q.task_done()


async def run(duration_s: int) -> None:
    proc = psutil.Process()
    rss_before = proc.memory_info().rss

    q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=QUEUE_SIZE)
    stats = {"sent": 0, "received": 0, "dropped": 0, "lat_sum": 0.0, "lat_max": 0.0}

    print(f">> Stress test: {TARGET_TPS:,} ticks/s x {duration_s}s "
          f"(objetivo {TARGET_TPS * duration_s:,} ticks)")
    t0 = time.perf_counter()
    await asyncio.gather(producer(q, duration_s, stats), consumer(q, stats))
    wall = time.perf_counter() - t0

    rss_after = proc.memory_info().rss
    rss_delta_mb = (rss_after - rss_before) / (1024 * 1024)

    sent = stats["sent"] or 1
    received = stats["received"] or 1
    dropped_pct = stats["dropped"] / sent * 100
    lat_avg = stats["lat_sum"] / received

    print("\n---------- MAX CAPACITY REPORT ----------")
    print(f"  Wall time            : {wall:.2f} s")
    print(f"  Ticks enviados       : {stats['sent']:,}")
    print(f"  Ticks recibidos      : {stats['received']:,}")
    print(f"  Throughput efectivo  : {stats['received'] / wall:,.0f} ticks/s")
    print(f"  Latencia promedio    : {lat_avg:.4f} ms")
    print(f"  Latencia maxima      : {stats['lat_max']:.4f} ms")
    print(f"  % Paquetes perdidos  : {dropped_pct:.3f} %")
    print(f"  Delta RAM (leak)     : {rss_delta_mb:+.2f} MB")
    print("-----------------------------------------")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="corrida corta de humo (2s)")
    args = ap.parse_args()
    asyncio.run(run(2 if args.quick else DEFAULT_DURATION_S))


if __name__ == "__main__":
    main()
