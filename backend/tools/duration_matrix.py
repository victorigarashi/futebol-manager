"""Competitive duration (A + C) test matrix: every approved duration x format x coach profile.

Server logical time (no browser). For each cell: real duration, overrun past the limit,
opportunities per match, goals per opportunity (must not be inflated or deflated by the
duration: the chance of each opportunity is untouched), share of matches that hit the limit
and how many decisions the AI concluded because of it.

    cd backend && ../.venv/bin/python tools/duration_matrix.py [matches] [engine]
"""

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, ".")

from app.domain.catalog import load_catalog  # noqa: E402
from app.domain.highlights import HL_PITCH, HighlightMatch  # noqa: E402
from app.services.lab_service import _team  # noqa: E402
from app.services.season_service import team_input_view  # noqa: E402

PROFILES = {"bots": None, "humanos rápidos (1 s)": 1.0, "humanos lentos (5 s)": 5.0, "humanos deixam o tempo esgotar": 99.0}


def play(engine, mode, m, duration, think, catalog, clubs):
    ht, at = _team(catalog, mode, clubs[m % len(clubs)]), _team(catalog, mode, clubs[(m * 7 + 3) % len(clubs)])
    humans = [] if think is None else [ht.club_code, at.club_code]
    limited = duration is not None
    match = HighlightMatch.create(f"T{m}", mode, ht, at, team_input_view(ht), team_input_view(at), humans, 11000 + m, "ARCADE", 10, False, 0.0,
                                  engine=engine, duration_seconds=duration or 0, limited=limited)
    L, W = HL_PITCH[mode]["length"], HL_PITCH[mode]["width"]
    now, dt, opened = 0.0, 0.05, None
    while not match.finished and now < 4000:
        for c in humans:
            match.seen(c, now)
        match.advance(now)
        if match.state == "DECISION" and think is not None and think < 50:
            opened = now if opened is None else opened
            if now - opened >= think:
                opp = match.opportunity
                car = next(b for b in opp["bodies"] if b["id"] == opp["carrier"])
                x, y = HighlightMatch.to_world(min(1.0, (car["x"] + 14) / L), car["y"] / W, bool(opp["right"]))
                try:
                    match.submit(str(opp["attacking"]), {"action_id": f"{opp['id']}-{opp['actions']}", "opportunity_id": opp["id"],
                                                         "revision": match.revision, "type": "PASS", "x": x, "y": y, "power": 0.4}, now)
                except ValueError:
                    pass
                opened = None
        else:
            opened = None
        now += dt
    chances = sum(match.stats[c]["chances"] for c in match.clubs)
    by_limit = sum(1 for a in match.action_log if a["by"] == "TIME_LIMIT")
    limit_minute = next((e["minute"] for e in match.events if e["kind"] == "TIME_LIMIT"), None)
    return {"real": match.finished_at, "chances": chances, "goals": sum(match.score), "limit": match.limit_reached, "by_limit": by_limit,
            "limit_minute": limit_minute, "dropped": match.paced_dropped}


def main(n=8, engine="v8"):
    catalog = load_catalog(Path("../data/catalogs/players.json"))
    clubs = sorted({p.club_code for p in catalog.players})
    rows = []
    for mode in ("FIVE_A_SIDE", "ELEVEN_A_SIDE"):
        for duration in (60, 90, 120, 180, None):
            for label, think in PROFILES.items():
                res = [play(engine, mode, m, duration, think, catalog, clubs) for m in range(n)]
                real = [r["real"] for r in res]
                chances = sum(r["chances"] for r in res)
                row = {"engine": engine, "mode": mode, "duration": duration or "livre (B)", "coaches": label, "matches": n,
                       "real_mean_s": round(statistics.mean(real), 1), "real_max_s": round(max(real), 1),
                       "overrun_max_s": round(max(0.0, max(real) - duration), 1) if duration else None,
                       "chances_per_match": round(chances / n, 2), "goals_per_chance": round(sum(r["goals"] for r in res) / max(1, chances), 3),
                       "goals_per_match": round(sum(r["goals"] for r in res) / n, 2),
                       "hit_limit": f"{sum(r['limit'] for r in res)}/{n}", "decisions_by_limit": sum(r["by_limit"] for r in res),
                       "limit_minute_min": min((r["limit_minute"] for r in res if r["limit_minute"] is not None), default=None),
                       "moments_dropped_per_match": round(sum(r["dropped"] for r in res) / n, 2)}
                rows.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
    return rows


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8, sys.argv[2] if len(sys.argv) > 2 else "v8")
