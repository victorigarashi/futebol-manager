"""Real duration of a Modo Jogável match, split by component (server logical time).

For each engine and coach profile, plays full matches through HighlightMatch.advance /
submit with a fake clock and accumulates the real seconds spent in each official state:

  CLOCK       fast simulation between decisive moments (90' at 4'/s = 22.5 s)
  HALF_TIME   fixed 6 s
  DECISION    waiting for the human coach (depends on the coach: instant, 2 s, 5 s, timer)
  EXECUTING   the human's actions being played (physics duration of each action)
  REPLAY      bot attacks shown as highlights
  OUTCOME     the result banner after each opportunity (1.8 s)

No browser, no test driver: this isolates the game's own time from automation and
rendering. Compare with the room's configured durations (1:00/1:30/2:00/3:00).

    cd backend && ../.venv/bin/python tools/match_duration.py [matches]
"""

import collections
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, ".")

from app.domain.catalog import load_catalog  # noqa: E402
from app.domain.highlights import HighlightMatch  # noqa: E402
from app.services.lab_service import _team  # noqa: E402
from app.services.season_service import team_input_view  # noqa: E402

PROFILES = {"bots only": None, "humans instant": 0.0, "humans 2 s": 2.0, "humans 5 s": 5.0, "humans let timer expire (10 s)": 99.0}


def play(engine: str, mode: str, m: int, think: float | None, catalog, clubs) -> tuple[float, dict]:
    ht, at = _team(catalog, mode, clubs[m % len(clubs)]), _team(catalog, mode, clubs[(m * 7 + 3) % len(clubs)])
    humans = [] if think is None else [ht.club_code, at.club_code]
    match = HighlightMatch.create(f"D{m}", mode, ht, at, team_input_view(ht), team_input_view(at), humans, 7000 + m, "ARCADE", 10, False, 0.0,
                                  engine=engine)
    dt, now, spent = 0.05, 0.0, collections.Counter()
    opened = None
    while not match.finished and now < 3600:
        for c in humans:
            match.seen(c, now)
        match.advance(now)
        spent[match.state] += dt
        if match.state == "DECISION" and think is not None and think < 50:
            opened = opened if opened is not None else now
            if now - opened >= think:
                opp = match.opportunity
                club = str(opp["attacking"])
                carrier = next(b for b in opp["bodies"] if b["id"] == opp["carrier"])
                x, y = HighlightMatch.to_world(min(1.0, (carrier["x"] + 14) / (105 if mode == "ELEVEN_A_SIDE" else 50)), carrier["y"] / (68 if mode == "ELEVEN_A_SIDE" else 32), bool(opp["right"]))
                try:
                    match.submit(club, {"action_id": f"{opp['id']}-{opp['actions']}", "opportunity_id": opp["id"], "revision": match.revision,
                                        "type": "PASS", "x": x, "y": y, "power": 0.4}, now)
                except ValueError:
                    pass
                opened = None
        else:
            opened = None
        now += dt
    return match.finished_at or now, spent


def main(n: int = 10):
    catalog = load_catalog(Path("../data/catalogs/players.json"))
    clubs = sorted({p.club_code for p in catalog.players})
    out = []
    for mode in ("ELEVEN_A_SIDE", "FIVE_A_SIDE"):
        for engine in ("v6", "v7", "v8"):
            for label, think in PROFILES.items():
                totals, states = [], collections.Counter()
                for m in range(n):
                    total, spent = play(engine, mode, m, think, catalog, clubs)
                    totals.append(total)
                    states.update(spent)
                out.append({"mode": mode, "engine": engine, "coaches": label, "matches": n,
                            "real_seconds_mean": round(statistics.mean(totals), 1), "min": round(min(totals), 1), "max": round(max(totals), 1),
                            "seconds_per_state_mean": {k: round(v / n, 1) for k, v in sorted(states.items())}})
                print(json.dumps(out[-1], ensure_ascii=False), flush=True)
    return out


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 10)
