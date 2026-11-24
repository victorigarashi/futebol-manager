"""Playing-style signatures on the V8 engine: do possession, direct, counter and wide play
produce clearly different football? Same clubs, opponents and seeds; only the style changes.

Measured on the official state at every action of the team under test (engine frame):
  pass_len      mean length of passes/lofts (m)
  passes_per_ch passes per opportunity
  supports      team-mates within 12 m of the ball carrier at the moment he decides
  runners       team-mates beyond the defensive line (in behind) at that moment
  width         lateral spread of the attackers (sd, m)
  flank_share   share of actions taken within 15 m of a touchline
  crosses       lofted balls into the box per match
  long_balls    forward passes > 25 m per match
  carries       carries per match
  chance_s      seconds of play per opportunity

    cd backend && ../.venv/bin/python tools/style_profile.py [matches]
"""

import dataclasses
import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, ".")

from app.domain.catalog import load_catalog  # noqa: E402
from app.domain.highlights import HighlightMatch  # noqa: E402
from app.domain.tactics import Tactics  # noqa: E402
from app.services.lab_service import _team  # noqa: E402
from app.services.season_service import team_input_view  # noqa: E402

L, W = 105.0, 68.0
STYLES = ("POSSESSION", "DIRECT", "COUNTER", "WIDE")


def run(style, catalog, clubs, m):
    base = _team(catalog, "ELEVEN_A_SIDE", clubs[m % len(clubs)])
    team = dataclasses.replace(base, tactics=Tactics(**{**base.tactics.view(), "style": style}))
    rival = _team(catalog, "ELEVEN_A_SIDE", clubs[(m * 7 + 5) % len(clubs)])
    match = HighlightMatch.create(f"S{m}", "ELEVEN_A_SIDE", team, rival, team_input_view(team), team_input_view(rival), [], 12000 + m, "ARCADE", 10,
                                  False, 0.0, engine="v8")
    acc = {"pass_len": [], "supports": [], "runners": [], "width": [], "flank": [], "crosses": 0, "long_balls": 0, "carries": 0, "passes": 0,
           "chances": 0, "seconds": 0.0}
    seen = set()
    original = match._resolve

    def spy(choice, by, at):
        opp = match.opportunity
        if opp["attacking"] == team.club_code:
            if opp["id"] not in seen:
                seen.add(opp["id"])
                acc["chances"] += 1
            bodies = opp["bodies"]
            car = next(b for b in bodies if b["id"] == opp["carrier"])
            mates = [b for b in bodies if b["team"] == "A" and b["role"] != "GK" and b["id"] != car["id"]]
            dfs = sorted((b["x"] for b in bodies if b["team"] == "D" and b["role"] != "GK"), reverse=True)
            line = dfs[1] if len(dfs) > 1 else L - 12
            acc["supports"].append(sum(1 for b in mates if math.hypot(b["x"] - car["x"], b["y"] - car["y"]) < 12))
            acc["runners"].append(sum(1 for b in mates if b["x"] > line))
            acc["width"].append(statistics.pstdev([b["y"] for b in mates + [car]]))
            acc["flank"].append(min(car["y"], W - car["y"]) < 15)
            kind = str(choice["type"])
            length = math.hypot(float(choice["x"]) - car["x"], float(choice["y"]) - car["y"])
            if kind in ("PASS", "LOFT"):
                acc["pass_len"].append(length)
                acc["passes"] += 1
                if float(choice["x"]) - car["x"] > 25:
                    acc["long_balls"] += 1
            if kind == "LOFT" and float(choice["x"]) > L - 16.5 and abs(float(choice["y"]) - W / 2) < 20:
                acc["crosses"] += 1
            if kind == "CARRY":
                acc["carries"] += 1
            step = original(choice, by, at)
            acc["seconds"] += float(step["duration"])
            return step
        return original(choice, by, at)

    match._resolve = spy
    match.advance(1e6)
    return acc


def main(n=30):
    catalog = load_catalog(Path("../data/catalogs/players.json"))
    clubs = sorted({p.club_code for p in catalog.players})
    out = {}
    for style in STYLES:
        runs = [run(style, catalog, clubs, m) for m in range(n)]
        flat = lambda k, runs=runs: [v for r in runs for v in r[k]]  # noqa: E731
        chances = sum(r["chances"] for r in runs) or 1
        out[style] = {
            "pass_len": round(statistics.mean(flat("pass_len")), 1), "passes_per_ch": round(sum(r["passes"] for r in runs) / chances, 2),
            "supports": round(statistics.mean(flat("supports")), 2), "runners": round(statistics.mean(flat("runners")), 2),
            "width": round(statistics.mean(flat("width")), 2), "flank_share": round(statistics.mean(flat("flank")), 2),
            "crosses": round(sum(r["crosses"] for r in runs) / n, 2), "long_balls": round(sum(r["long_balls"] for r in runs) / n, 2),
            "carries": round(sum(r["carries"] for r in runs) / n, 2), "chance_s": round(sum(r["seconds"] for r in runs) / chances, 1), "matches": n,
        }
        print(style, json.dumps(out[style]), flush=True)
    return out


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
