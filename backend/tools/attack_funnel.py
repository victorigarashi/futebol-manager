"""Attack funnel of the Modo Jogável engines (AI vs AI): where do the moves die?

For every opportunity: did it progress, reach the final third, reach a shooting zone (the
box or 25 m central), produce a shot, on target, a goal — and how did it end (interception,
tackle, keeper, ball out, guard). Plus per-action rates (pass completion, interceptions,
receptions, dribbles, saves, rebounds). Same matches/seeds for every engine.

    cd backend && ../.venv/bin/python tools/attack_funnel.py [matches] [mode] [engines]
"""

import collections
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, ".")

from app.domain.catalog import load_catalog  # noqa: E402
from app.domain.highlights import HL_PITCH, HighlightMatch  # noqa: E402
from app.services.lab_service import _team  # noqa: E402
from app.services.season_service import team_input_view  # noqa: E402


def stride(step):
    return 4 if step.get("layout") in ("v7", "v8") else 2


def run(engine: str, matches: int, mode: str) -> dict:
    catalog = load_catalog(Path("../data/catalogs/players.json"))
    clubs = sorted({p.club_code for p in catalog.players})
    L, W = HL_PITCH[mode]["length"], HL_PITCH[mode]["width"]
    funnel = collections.Counter()
    ends = collections.Counter()
    acts = collections.Counter()
    goals = 0
    for m in range(matches):
        home, away = clubs[m % len(clubs)], clubs[(m * 7 + 3) % len(clubs)]
        if home == away:
            away = clubs[(m + 1) % len(clubs)]
        ht, at = _team(catalog, mode, home), _team(catalog, mode, away)
        match = HighlightMatch.create(f"F{m}", mode, ht, at, team_input_view(ht), team_input_view(at), [], 4000 + m, "TRADITIONAL", 10, False, 0.0,
                                      engine=engine)
        seen = set()
        now = 0.0
        while not match.finished and now < 4000:
            now += 0.5
            match.advance(now)
            opp = match.opportunity
            if not (opp and opp.get("replay")) or opp["id"] in seen:
                continue
            seen.add(opp["id"])
            right = bool(opp.get("right", True))
            funnel["opportunities"] += 1
            best_x = 0.0
            central = False
            shot = on = goal = False
            for step in opp["replay"]:
                acts[step["type"]] += 1
                acts[f"{step['type']}:{step['outcome']}"] += 1
                for row in step["frames"]:
                    bx = row[1] if right else 1 - row[1]
                    by = row[2] if right else 1 - row[2]
                    best_x = max(best_x, bx)
                    if bx * L > L - 25 * L / 105 and abs(by * W - W / 2) < 14 * W / 68:
                        central = True
                for cue in step.get("cues", []):
                    acts[f"cue:{cue['kind']}"] += 1
                if step["type"] == "SHOT" or any(c["kind"] == "HEADER" for c in step.get("cues", [])) and step["shooter"]:
                    shot = True
                if step["outcome"] == "GOAL":
                    goal = True
                if any(c["kind"] in ("SAVE", "POST", "BAR") for c in step.get("cues", [])) or step["outcome"] in ("GOAL", "SAVED_HELD"):
                    on = on or step["outcome"] != "OUT"
            last = opp["replay"][-1]
            start_x = opp["replay"][0]["frames"][0][1] if right else 1 - opp["replay"][0]["frames"][0][1]
            funnel["progressed_10m"] += best_x * L - start_x * L > 10
            funnel["final_third"] += best_x > 2 / 3
            funnel["shooting_zone"] += central
            funnel["shot"] += shot
            funnel["on_target"] += on
            funnel["goal"] += goal
            goals += goal
            reason = last["outcome"]
            if reason == "LOST":
                kinds = [c["kind"] for c in last.get("cues", [])]
                reason = "LOST:" + next((k for k in reversed(kinds) if k in ("INTERCEPT", "TACKLE", "CLAIM", "HEADER", "SAVE")), "recovery")
            ends[reason if opp.get("status") != "STALLED" else "STALLED"] += 1
    n = max(1, funnel["opportunities"])
    passes = acts["PASS"] + acts["LOFT"]
    done = sum(v for k, v in acts.items() if k in ("PASS:CONTROLLED", "LOFT:CONTROLLED"))
    return {
        "engine": engine, "mode": mode, "matches": matches, "goals_per_match": round(goals / matches, 2),
        "funnel_per_opportunity": {k: round(v / n, 3) for k, v in funnel.items() if k != "opportunities"},
        "opportunities_per_match": round(n / matches, 2),
        "end_reasons": {k: round(v / n, 3) for k, v in ends.most_common()},
        "actions_per_match": {k: round(acts[k] / matches, 2) for k in ("PASS", "LOFT", "CARRY", "SHOT")},
        "pass_completion_controlled": round(done / max(1, passes), 3),
        "cues_per_match": {k[4:]: round(v / matches, 2) for k, v in sorted(acts.items()) if k.startswith("cue:")},
    }


if __name__ == "__main__":
    matches = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    mode = sys.argv[2] if len(sys.argv) > 2 else "ELEVEN_A_SIDE"
    engines = sys.argv[3].split(",") if len(sys.argv) > 3 else ["v6", "v7"]
    print(json.dumps([run(e, matches, mode) for e in engines], indent=1, ensure_ascii=False))
    _ = math
