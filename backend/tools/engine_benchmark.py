"""Batch calibration of the agent engine using the authorized catalog.

Usage (from backend/):  ../.venv/bin/python -m tools.engine_benchmark --matches 40 --mode ELEVEN_A_SIDE
Prints per-match averages, timing and tactic A/B comparisons. Does not touch game state.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from app.domain.catalog import CatalogPlayer
from app.domain.match_engine import MatchEngine, PlayerInput, TeamInput
from app.domain.squad import formation_slots
from app.domain.tactics import Tactics

CATALOG = Path(__file__).resolve().parents[2] / "data" / "catalogs" / "players.json"


def load_clubs() -> dict[str, list[CatalogPlayer]]:
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    clubs: dict[str, list[CatalogPlayer]] = {}
    for raw in payload["players"]:
        player = CatalogPlayer.model_validate(raw)
        clubs.setdefault(player.club_code, []).append(player)
    return clubs


def team(players: list[CatalogPlayer], mode: str, formation: str, tactics: Tactics, code: str) -> TeamInput:
    pool = sorted(players, key=lambda p: -p.overall)
    starters, used = [], set()
    for index, slot in enumerate(formation_slots(mode, formation)):
        pick = next((p for p in pool if p.id not in used and p.position == slot.position), None) or next(p for p in pool if p.id not in used)
        used.add(pick.id)
        starters.append(PlayerInput(pick.id, pick.name, pick.position, slot.position, slot.x, slot.y, pick.overall, pick.attributes, index + 1))
    bench_size = 5 if mode == "ELEVEN_A_SIDE" else 3
    bench = [PlayerInput(p.id, p.name, p.position, p.position, 50, 50, p.overall, p.attributes, 12 + i) for i, p in enumerate([p for p in pool if p.id not in used][:bench_size])]
    return TeamInput(code, formation, tuple(starters), tuple(bench), tactics)


def run(mode: str, matches: int, home_tactics: Tactics, away_tactics: Tactics, seed0: int = 1) -> dict[str, float]:
    clubs = load_clubs()
    codes = sorted(clubs)
    formation = "4-3-3" if mode == "ELEVEN_A_SIDE" else "2-1-1"
    rows, timings = [], []
    for i in range(matches):
        h, a = codes[i % len(codes)], codes[(i * 7 + 3) % len(codes)]
        if h == a:
            a = codes[(i + 1) % len(codes)]
        engine = MatchEngine(f"bench-{i}", mode, team(clubs[h], mode, formation, home_tactics, h), team(clubs[a], mode, formation, away_tactics, a), seed0 + i)
        start = time.perf_counter()
        engine.run_to_end()
        timings.append(time.perf_counter() - start)
        s = engine.statistics()
        hs, as_ = s[h], s[a]
        rows.append({
            "goals": engine.score[0] + engine.score[1], "home_goals": engine.score[0], "away_goals": engine.score[1],
            "shots": hs["shots"] + as_["shots"], "on_target": hs["shots_on_target"] + as_["shots_on_target"],
            "xg": hs["xg"] + as_["xg"], "home_xg": hs["xg"], "away_xg": as_["xg"], "passes": hs["passes"] + as_["passes"],
            "pass_acc": (hs["passes_completed"] + as_["passes_completed"]) / max(1, hs["passes"] + as_["passes"]),
            "corners": hs["corners"] + as_["corners"], "fouls": hs["fouls"] + as_["fouls"],
            "yellows": hs["yellow_cards"] + as_["yellow_cards"], "reds": hs["red_cards"] + as_["red_cards"],
            "tackles": hs["tackles"] + as_["tackles"], "interceptions": hs["interceptions"] + as_["interceptions"],
            "home_poss": hs["possession"], "home_shots": hs["shots"], "away_shots": as_["shots"],
            "home_high_rec": hs["high_recoveries"], "away_high_rec": as_["high_recoveries"],
            "home_stamina": hs["avg_stamina"], "away_stamina": as_["avg_stamina"],
            "home_passes": hs["passes"], "away_passes": as_["passes"], "home_dist": hs["distance"],
            "events": len(engine.events), "home_box": hs["box_touches"], "away_box": as_["box_touches"],
            "home_win": engine.score[0] > engine.score[1], "draw": engine.score[0] == engine.score[1],
        })
    summary = {key: round(statistics.mean(float(r[key]) for r in rows), 3) for key in rows[0]}
    summary["ms_per_match"] = round(statistics.mean(timings) * 1000, 1)
    summary["ms_per_tick"] = round(statistics.mean(timings) * 1000 / 5400, 4)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matches", type=int, default=30)
    parser.add_argument("--mode", default="ELEVEN_A_SIDE")
    parser.add_argument("--ab", action="store_true", help="tactic A/B comparisons against a balanced opponent")
    args = parser.parse_args()
    print(json.dumps({"baseline": run(args.mode, args.matches, Tactics(), Tactics())}, indent=1))
    if args.ab:
        variants = {
            "very_attacking": Tactics(mentality="VERY_ATTACKING"), "very_defensive": Tactics(mentality="VERY_DEFENSIVE"),
            "high_press": Tactics(pressure="HIGH"), "low_press": Tactics(pressure="LOW"),
            "direct": Tactics(style="DIRECT"), "counter": Tactics(mentality="DEFENSIVE", style="COUNTER"),
            "wide": Tactics(style="WIDE"), "short_buildup": Tactics(style="SHORT_BUILDUP"),
        }
        keys = ("home_goals", "away_goals", "home_xg", "away_xg", "home_poss", "home_shots", "away_shots", "home_passes", "home_high_rec", "home_stamina", "home_box", "away_box", "fouls", "home_win")
        for name, tactics in variants.items():
            result = run(args.mode, args.matches, tactics, Tactics())
            print(name, {k: result[k] for k in keys})


if __name__ == "__main__":
    main()


def counterplay(matches: int = 30) -> None:
    """Every plan should have an answer: compare dominant plans against their counters."""
    pairs = {
        "very_attacking vs counter": (Tactics(mentality="VERY_ATTACKING"), Tactics(mentality="DEFENSIVE", style="COUNTER")),
        "high_press vs direct": (Tactics(pressure="HIGH"), Tactics(style="DIRECT")),
        "very_defensive vs possession": (Tactics(mentality="VERY_DEFENSIVE", style="COUNTER"), Tactics(style="POSSESSION")),
    }
    for name, (home, away) in pairs.items():
        result = run("ELEVEN_A_SIDE", matches, home, away)
        print(name, {k: result[k] for k in ("home_goals", "away_goals", "home_xg", "away_xg", "home_win", "draw", "home_stamina", "away_stamina")})
