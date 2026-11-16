"""Lightweight runtime metrics: CPU per subsystem and event-loop lag.

On a 0.1 CPU host the question is always "who is eating the CPU and is the loop
still responsive?". Every hot path is wrapped in `cpu("name")`, which adds its
process CPU time to a counter; a background probe measures how late the event loop
wakes up (lag). Exposed at GET /api/v1/metrics (no personal data).
"""

from __future__ import annotations

import asyncio
import resource
import time
from collections import defaultdict
from contextlib import contextmanager

STARTED = time.time()
CPU: dict[str, float] = defaultdict(float)
CALLS: dict[str, int] = defaultdict(int)
LAG = {"last": 0.0, "max": 0.0, "over_1s": 0, "samples": 0}
# Rendering health reported by browsers (anonymous, aggregated per room, bounded).
CLIENTS: dict[str, dict[str, float]] = {}


def record_client(room_id: str, payload: dict[str, object]) -> None:
    def number(key: str, low: float, high: float) -> float | None:
        value = payload.get(key)
        return float(value) if isinstance(value, (int, float)) and low <= float(value) <= high else None
    sample = {"fps": number("fps", 0, 240), "render_ms": number("render_ms", 0, 1000), "delay_ms": number("delay_ms", 0, 60_000)}
    if len(CLIENTS) > 200 and room_id not in CLIENTS:
        return
    room = CLIENTS.setdefault(room_id, {"reports": 0})
    room["reports"] += 1
    for key, value in sample.items():
        if value is not None:
            room[key] = round(value if key not in room else room[key] * 0.8 + value * 0.2, 2)


@contextmanager
def cpu(name: str):
    began = time.process_time()
    try:
        yield
    finally:
        CPU[name] += time.process_time() - began
        CALLS[name] += 1


async def lag_probe(interval: float = 0.5) -> None:
    """How late does the loop run a timer? (> ~5 s would fail Render's health check)."""
    while True:
        expected = time.perf_counter() + interval
        await asyncio.sleep(interval)
        lag = max(0.0, time.perf_counter() - expected)
        LAG["last"] = lag
        LAG["max"] = max(LAG["max"], lag)
        LAG["samples"] += 1
        if lag > 1.0:
            LAG["over_1s"] += 1


def snapshot() -> dict[str, object]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    total = usage.ru_utime + usage.ru_stime
    uptime = time.time() - STARTED
    return {
        "uptime_seconds": round(uptime, 1),
        "process_cpu_seconds": round(total, 2),
        "cpu_share": round(total / uptime, 3) if uptime else None,
        "max_rss_mb": round(usage.ru_maxrss / 1024, 1),
        "cpu_by_subsystem": {name: {"seconds": round(seconds, 3), "calls": CALLS[name]} for name, seconds in sorted(CPU.items())},
        "event_loop_lag": {key: round(value, 3) if isinstance(value, float) else value for key, value in LAG.items()},
        "client_rendering": [{key: value for key, value in room.items()} for room in CLIENTS.values()],
    }
