"""Tactical A/B on the V8 engine: does each choice change behaviour on the pitch?

Same clubs, same opponents, same seeds; only ONE tactical choice changes between A and B.
Behaviour is measured on the official state after every action (engine frame: the attack
goes to x = L), plus the match outcomes. Multi-seed (default 30 matches per variant);
mean and standard deviation are reported — no cherry-picking.

    cd backend && ../.venv/bin/python tools/tactics_ab.py [matches]
"""

import dataclasses
import json
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


def run(variant_team, catalog, clubs, m, side_under_test: int):
    """side_under_test: 0 = the variant attacks (its own attacks measured), 1 = it defends."""
    base = _team(catalog, "ELEVEN_A_SIDE", clubs[m % len(clubs)])
    rival = _team(catalog, "ELEVEN_A_SIDE", clubs[(m * 7 + 5) % len(clubs)])
    team = variant_team(base)
    home, away = team, rival
    match = HighlightMatch.create(f"AB{m}", "ELEVEN_A_SIDE", home, away, team_input_view(home), team_input_view(away), [], 9000 + m, "ARCADE", 10,
                                  False, 0.0, engine="v8")
    rows = {"block_depth": [], "def_spread": [], "att_width": [], "att_height": [], "fb_advance": []}
    acts = {"PASS": 0, "LOFT": 0, "CARRY": 0, "SHOT": 0, "long_pass": 0}
    original = match._resolve

    def spy(choice, by, at):
        step = original(choice, by, at)
        opp = match.opportunity
        mine_attacking = opp["attacking"] == team.club_code
        bodies = opp["bodies"]
        roles = (opp.get("tactics") or {}).get("roles", {})
        if side_under_test == 1 and not mine_attacking:
            dfs = [b for b in bodies if b["team"] == "D" and b["role"] != "GK"]
            backs = [b for b in dfs if roles.get(b["id"]) in ("CB", "FB")] or dfs
            rows["block_depth"].append(statistics.mean(L - b["x"] for b in backs))
            rows["def_spread"].append(statistics.pstdev(b["y"] for b in dfs))
        if side_under_test == 0 and mine_attacking:
            atts = [b for b in bodies if b["team"] == "A" and b["role"] != "GK"]
            rows["att_width"].append(statistics.pstdev(b["y"] for b in atts))
            rows["att_height"].append(statistics.mean(b["x"] for b in atts))
            fbs = [b for b in atts if roles.get(b["id"]) == "FB"]
            if fbs:
                rows["fb_advance"].append(max(b["x"] for b in fbs))
            acts[str(choice["type"])] += 1
            car = next((b for b in bodies if b["id"] == step["carrier"]), None)
            if choice["type"] in ("PASS", "LOFT") and car is not None and abs(float(choice["x"]) - car["x"]) > 25:
                acts["long_pass"] += 1
        return step

    match._resolve = spy
    match.advance(1e6)
    me = match.side_of(team.club_code)
    return {k: (statistics.mean(v) if v else None) for k, v in rows.items()} | acts | {
        "goals_for": match.score[me], "goals_against": match.score[1 - me],
        "shots_for": match.stats[team.club_code]["shots"], "shots_against": match.stats[match.clubs[1 - me]]["shots"],
        "interceptions": match.stats[team.club_code]["interceptions"], "tackles": match.stats[team.club_code]["tackles"]}


def tactics(team, **kw):
    return dataclasses.replace(team, tactics=Tactics(**{**team.tactics.view(), **kw}))


def instruct(team, code):
    fbs = [p.id for p in team.starters if p.slot_position == "DF" and (p.slot_x <= 25 or p.slot_x >= 75)]
    return dataclasses.replace(team, instructions={**dict(team.instructions), **dict.fromkeys(fbs, code)})


EXPERIMENTS = [
    ("Pressão (defendendo)", 1, ("ALTA", lambda t: tactics(t, pressure="HIGH")), ("BAIXA", lambda t: tactics(t, pressure="LOW")),
     ["block_depth", "def_spread", "interceptions", "tackles", "shots_against", "goals_against"]),
    ("Mentalidade (defendendo)", 1, ("OFENSIVA", lambda t: tactics(t, mentality="ATTACKING")), ("DEFENSIVA", lambda t: tactics(t, mentality="DEFENSIVE")),
     ["block_depth", "shots_against", "goals_against"]),
    ("Estilo (atacando)", 0, ("PELAS LATERAIS", lambda t: tactics(t, style="WIDE")), ("POSSE", lambda t: tactics(t, style="POSSESSION")),
     ["att_width", "LOFT", "PASS", "long_pass", "shots_for", "goals_for"]),
    ("Estilo (atacando)", 0, ("DIRETO", lambda t: tactics(t, style="DIRECT")), ("POSSE", lambda t: tactics(t, style="POSSESSION")),
     ["long_pass", "PASS", "CARRY", "shots_for", "goals_for"]),
    ("Mentalidade (atacando)", 0, ("MUITO OFENSIVA", lambda t: tactics(t, mentality="VERY_ATTACKING")), ("MUITO DEFENSIVA", lambda t: tactics(t, mentality="VERY_DEFENSIVE")),
     ["att_height", "shots_for", "goals_for"]),
    ("Laterais (atacando)", 0, ("AVANÇAR SEMPRE", lambda t: instruct(t, "OVERLAP")), ("FICAR NA DEFESA", lambda t: instruct(t, "STAY_BACK")),
     ["fb_advance", "att_width", "shots_for"]),
]


def main(n: int = 30):
    catalog = load_catalog(Path("../data/catalogs/players.json"))
    clubs = sorted({p.club_code for p in catalog.players})
    report = []
    for name, side, (la, fa), (lb, fb), keys in EXPERIMENTS:
        a = [run(fa, catalog, clubs, m, side) for m in range(n)]
        b = [run(fb, catalog, clubs, m, side) for m in range(n)]
        row = {"experiment": name, "A": la, "B": lb, "matches_per_variant": n, "metrics": {}}
        for k in keys:
            va = [x[k] for x in a if x[k] is not None]
            vb = [x[k] for x in b if x[k] is not None]
            row["metrics"][k] = {"A_mean": round(statistics.mean(va), 2), "A_sd": round(statistics.pstdev(va), 2),
                                 "B_mean": round(statistics.mean(vb), 2), "B_sd": round(statistics.pstdev(vb), 2)}
        report.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    return report


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
