"""Light, reproducible load test: real browser-like clients against a local server.

Each room gets two coaches. Every coach keeps a WebSocket open and polls like the
web app (room state, season, preview and, during the match, the live view); both
confirm READY, the round plays to the final whistle. Meanwhile a probe hits
/health every second the way Render's health check does (5 s timeout).

Reports latency (mean/p95/max) per endpoint, requests per second, HTTP errors,
health-check failures, time from the last READY to the round going live, the
frame push rate and the server's CPU and memory (from /proc).

Never point this at production.

    ../.venv/bin/python -m tools.load_test --state /tmp/load.json --base http://127.0.0.1:8010 --pid <uvicorn pid>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from collections import defaultdict

import httpx
import websockets

LAT: dict[str, list[float]] = defaultdict(list)
ERRORS: dict[str, int] = defaultdict(int)
HEALTH: list[float] = []
FRAMES: dict[str, list[float]] = defaultdict(list)
DROPS = {"ws_closed": 0}
START: dict[str, dict[str, float]] = defaultdict(dict)


def label(path: str) -> str:
    parts = path.split("?")[0].split("/")
    if "rooms" in parts:
        i = parts.index("rooms")
        parts = parts[:i + 1] + ["{id}"] + parts[i + 2:]
    return "/".join(parts[3:]) or path


async def call(client: httpx.AsyncClient, method: str, path: str, token: str, **kw) -> httpx.Response | None:
    began = time.perf_counter()
    try:
        response = await client.request(method, path, headers={"authorization": f"Bearer {token}"}, timeout=30, **kw)
    except httpx.HTTPError:
        ERRORS[f"{method} {label(path)} network"] += 1
        return None
    LAT[f"{method} {label(path)}"].append(time.perf_counter() - began)
    if response.status_code >= 500:
        ERRORS[f"{method} {label(path)} {response.status_code}"] += 1
    return response


async def health_probe(client: httpx.AsyncClient, stop: asyncio.Event) -> None:
    while not stop.is_set():
        began = time.perf_counter()
        try:
            await client.get("/api/v1/health", timeout=5)
            HEALTH.append(time.perf_counter() - began)
        except httpx.HTTPError:
            HEALTH.append(float("inf"))
        await asyncio.sleep(1)


async def socket_reader(ws_base: str, room: str, token: str, key: str, stop: asyncio.Event) -> None:
    try:
        async with websockets.connect(f"{ws_base}/api/v1/ws/rooms/{room}?access_token={token}", max_size=2**22) as ws:
            while not stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1)
                except TimeoutError:
                    continue
                if isinstance(raw, str) and raw.startswith("{"):
                    message = json.loads(raw)
                    if message.get("type") == "live.frames" and message.get("frames"):
                        FRAMES[key].append(time.time())
    except (OSError, websockets.WebSocketException):
        DROPS["ws_closed"] += 1


async def coach(client: httpx.AsyncClient, room: dict, index: int, stop: asyncio.Event, ready_delay: float) -> None:
    rid, token = room["room_id"], room["tokens"][index]
    base = f"/api/v1/rooms/{rid}"
    ready_sent = False
    began = time.time()
    next_poll = defaultdict(float)
    while not stop.is_set():
        now = time.time()
        live = None
        if now >= next_poll["state"]:
            await call(client, "GET", base + "/state", token)
            next_poll["state"] = now + 5
        if now >= next_poll["season"]:
            await call(client, "GET", base + "/season", token)
            next_poll["season"] = now + 5
        if now >= next_poll["live"]:
            response = await call(client, "GET", base + "/season/live", token)
            live = response.json().get("data") if response is not None and response.status_code == 200 else None
            on_air = bool(live and live.get("live_round"))
            next_poll["live"] = now + (2 if on_air else 6)
            if on_air and "live" not in START[rid]:
                START[rid]["live"] = time.time()
            if START[rid].get("live") and live and not live.get("live_round"):
                START[rid]["finished"] = time.time()
        if not ready_sent and now - began >= ready_delay:
            await call(client, "GET", base + "/season/preview", token)
            response = await call(client, "POST", base + "/season/ready", token)
            ready_sent = response is not None and response.status_code == 200
            if ready_sent:
                START[rid]["ready"] = max(START[rid].get("ready", 0), time.time())
        await asyncio.sleep(0.25)


def proc_stats(pid: int) -> tuple[float, int]:
    with open(f"/proc/{pid}/stat") as handle:
        fields = handle.read().split(")")[-1].split()
    ticks = int(fields[11]) + int(fields[12])
    with open(f"/proc/{pid}/status") as handle:
        rss = next(int(line.split()[1]) for line in handle if line.startswith("VmRSS"))
    return ticks / os.sysconf("SC_CLK_TCK"), rss * 1024


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(p * len(ordered)))] if ordered else float("nan")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--base", default="http://127.0.0.1:8010")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--max-seconds", type=float, default=200)
    parser.add_argument("--out")
    parser.add_argument("--ready-after", type=float, default=3, help="seconds of preparation before the first READY")
    args = parser.parse_args()
    rooms = json.load(open(args.state))["rooms"]
    stop = asyncio.Event()
    cpu0, _ = proc_stats(args.pid)
    wall0 = time.time()
    rss_peak = 0
    async with httpx.AsyncClient(base_url=args.base) as client:
        ws_base = args.base.replace("http", "ws")
        tasks = [asyncio.create_task(health_probe(client, stop))]
        for room in rooms:
            for index in (0, 1):
                tasks.append(asyncio.create_task(socket_reader(ws_base, room["room_id"], room["tokens"][index], f"{room['room_id']}:{index}", stop)))
                tasks.append(asyncio.create_task(coach(client, room, index, stop, ready_delay=args.ready_after + 2 * index)))
        while time.time() - wall0 < args.max_seconds:
            await asyncio.sleep(1)
            rss_peak = max(rss_peak, proc_stats(args.pid)[1])
            if all("finished" in START[r["room_id"]] for r in rooms):
                break
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            server_metrics = (await client.get("/api/v1/metrics", timeout=30)).json()["data"]
        except (httpx.HTTPError, ValueError, KeyError):
            server_metrics = None
    cpu1, _ = proc_stats(args.pid)
    wall = time.time() - wall0
    total = sum(len(v) for v in LAT.values())
    every = [x for v in LAT.values() for x in v]
    report = {
        "rooms": len(rooms), "wall_seconds": round(wall, 1), "requests": total, "rps": round(total / wall, 2),
        "latency_ms": {"mean": round(1000 * statistics.mean(every), 1) if every else None, "p95": round(1000 * pct(every, .95), 1), "max": round(1000 * max(every), 1) if every else None},
        "per_endpoint_ms": {k: {"n": len(v), "mean": round(1000 * statistics.mean(v), 1), "p95": round(1000 * pct(v, .95), 1)} for k, v in sorted(LAT.items())},
        "http_errors": dict(ERRORS),
        "health": {"probes": len(HEALTH), "p95_ms": round(1000 * pct([h for h in HEALTH if h != float('inf')], .95), 1),
                   "max_ms": round(1000 * max((h for h in HEALTH if h != float('inf')), default=0), 1),
                   "over_5s_or_failed": sum(1 for h in HEALTH if h >= 5)},
        "round": {r["room_id"]: {"ready_to_live_s": round(START[r["room_id"]]["live"] - START[r["room_id"]]["ready"], 2) if {"live", "ready"} <= START[r["room_id"]].keys() else None,
                                 "live_to_finished_s": round(START[r["room_id"]]["finished"] - START[r["room_id"]]["live"], 1) if {"live", "finished"} <= START[r["room_id"]].keys() else None}
                  for r in rooms},
        "frame_pushes_per_s": round(sum(len(v) for v in FRAMES.values()) / max(1, len(FRAMES)) / wall, 2) if FRAMES else 0,
        "max_gap_between_frame_pushes_s": round(max((max((b - a for a, b in zip(v, v[1:])), default=0) for v in FRAMES.values()), default=0), 2),
        "ws_drops": DROPS["ws_closed"],
        "server_cpu_seconds": round(cpu1 - cpu0, 2), "server_cpu_share": round((cpu1 - cpu0) / wall, 3),
        "server_rss_peak_mb": round(rss_peak / 1e6, 1),
        "server_metrics": server_metrics,
    }
    text = json.dumps(report, indent=2, ensure_ascii=False)
    print(text)
    if args.out:
        open(args.out, "w").write(text + "\n")


if __name__ == "__main__":
    asyncio.run(main())
