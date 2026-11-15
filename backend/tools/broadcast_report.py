"""Broadcast director report: duration accuracy, highlights shown and importance prior.

    cd backend && ../.venv/bin/python -m tools.broadcast_report --matches 20
"""

from __future__ import annotations

import argparse
import statistics
import time
from collections import Counter

from app.domain.bot_coach import advance_with_bots
from app.domain.broadcast import DURATIONS, Director, moment_importance
from app.domain.match_engine import MatchEngine
from app.domain.tactics import Tactics
from tools.engine_benchmark import load_clubs, team


def broadcast(engine: MatchEngine, duration: int, step: float = 0.2) -> tuple[Director, float]:
    director = Director(0.0, duration)
    baselines = (engine.inputs[0].tactics, engine.inputs[1].tactics)
    def advance(tick: int) -> None:
        advance_with_bots(engine, tick, (0, 1), baselines)
    engine.enable_snapshots()
    now, cpu = 0.0, 0.0
    while not director.complete and now < duration + 30:
        start = time.perf_counter()
        director.plan(engine, advance, now)
        engine.prune_snapshots(director.shown_tick(now))
        cpu += time.perf_counter() - start
        now += step
    return director, cpu


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matches", type=int, default=12)
    parser.add_argument("--mode", default="ELEVEN_A_SIDE")
    args = parser.parse_args()
    clubs = load_clubs()
    codes = sorted(clubs)
    formation = "4-3-3" if args.mode == "ELEVEN_A_SIDE" else "2-1-1"
    prior = Counter()
    for duration in DURATIONS:
        rows = []
        for i in range(args.matches):
            h, a = codes[i % len(codes)], codes[(i * 7 + 3) % len(codes)]
            if h == a:
                a = codes[(i + 1) % len(codes)]
            engine = MatchEngine(f"b{i}", args.mode, team(clubs[h], args.mode, formation, Tactics(), h), team(clubs[a], args.mode, formation, Tactics(), a), 100 + i)
            director, cpu = broadcast(engine, duration)
            segs = director.segments
            play = sum(s["r1"] - s["r0"] for s in segs if s["k"] == "PLAY")
            ticks_play = sum(s["t1"] - s["t0"] for s in segs if s["k"] == "PLAY")
            labels = Counter(s["label"] for s in segs if s["k"] == "PLAY")
            goals = [e for e in engine.events if e["kind"] == "GOAL"]
            shown_goals = sum(1 for g in goals if any(s["k"] == "PLAY" and s["t0"] <= g["tick"] <= s["t1"] for s in segs))
            if duration == DURATIONS[0]:
                for e in engine.events:
                    value = moment_importance(e)
                    for level in (1.0, 0.8, 0.6, 0.45, 0.35, 0.25):
                        if value >= level:
                            prior[level] += 1
            rows.append({"end": segs[-1]["r1"], "final_hold": segs[-1]["r1"] - segs[-1]["r0"], "play_s": play, "play_ticks": ticks_play,
                         "cuts": sum(1 for s in segs if s["k"] == "CUT"), "chances": labels["CHANCE"], "goals": len(goals), "goals_shown": shown_goals,
                         "attacks": labels["ATTACK"], "speed": ticks_play / max(1e-6, play), "cpu": cpu})
        print(f"\n== {duration}s ({args.matches} partidas, {args.mode})")
        for key in rows[0]:
            values = [float(r[key]) for r in rows]
            print(f"{key:12s} média {statistics.mean(values):8.2f}  min {min(values):8.2f}  max {max(values):8.2f}")
    print("\nprior (eventos por partida com importância >=):", {k: round(v / args.matches, 1) for k, v in sorted(prior.items(), reverse=True)})


if __name__ == "__main__":
    main()
