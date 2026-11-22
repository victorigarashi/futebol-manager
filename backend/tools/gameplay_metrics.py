"""Gameplay naturalness + balance metrics of the Modo Jogável engine (AI vs AI, official frames).

Measures what the eye calls "robotic": accelerations above what an athlete can do, instant
stops, snap turns, the ball jumping (teleport) between frames, ball glued/sawtooth during a
carry, keeper speed, overlaps; plus balance (goals, saves, pass completion, actions per chance).

    cd backend && ../.venv/bin/python tools/gameplay_metrics.py [matches] [mode]
"""

import json
import math
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, ".")

from app.domain.catalog import load_catalog  # noqa: E402
from app.domain.highlights import DT, HL_PITCH, HighlightMatch  # noqa: E402
from app.services.lab_service import _team  # noqa: E402
from app.services.season_service import team_input_view  # noqa: E402


def frame_metrics(step, roster, L, W, acc):
    frames = step["frames"]
    n = len(roster)
    k = 4 if step.get("layout") in ("v7", "v8") else 2
    for f in range(2, len(frames)):
        a, b, c = frames[f - 2], frames[f - 1], frames[f]
        dt1, dt2 = max(1e-3, b[0] - a[0]), max(1e-3, c[0] - b[0])
        # ball
        bv1 = math.hypot((b[1] - a[1]) * L, (b[2] - a[2]) * W) / dt1
        bv2 = math.hypot((c[1] - b[1]) * L, (c[2] - b[2]) * W) / dt2
        acc["ball_jump"] += bv2 > 45            # faster than any shot = teleport
        acc["ball_instant_stop"] += bv1 > 6 and bv2 < 0.3
        acc["ball_frames"] += 1
        for i in range(n):
            ix, iy = 4 + k * i, 5 + k * i
            v1 = ((b[ix] - a[ix]) * L / dt1, (b[iy] - a[iy]) * W / dt1)
            v2 = ((c[ix] - b[ix]) * L / dt2, (c[iy] - b[iy]) * W / dt2)
            s1, s2 = math.hypot(*v1), math.hypot(*v2)
            accel = math.hypot(v2[0] - v1[0], v2[1] - v1[1]) / dt2
            acc["frames"] += 1
            acc["accel_over_10"] += accel > 10.0          # elite athletes ~ 6-8 m/s²
            acc["instant_stop"] += s1 > 3.0 and s2 < 0.3
            acc["instant_start"] += s1 < 0.3 and s2 > 3.0
            if s1 > 2.5 and s2 > 2.5:
                turn = abs(math.atan2(v1[0] * v2[1] - v1[1] * v2[0], v1[0] * v2[0] + v1[1] * v2[1]))
                acc["snap_turn"] += turn > math.radians(35) * (dt2 / 0.1) and s2 > 4.0
            acc["max_speed"] = max(acc["max_speed"], s2)
            if roster[i]["role"] == "GK":
                acc["gk_speed_max"] = max(acc["gk_speed_max"], s2)
                acc["gk_teleport"] += s2 > 9.0
        # overlaps
        for i in range(n):
            for j in range(i + 1, n):
                if math.hypot((c[4 + k * i] - c[4 + k * j]) * L, (c[5 + k * i] - c[5 + k * j]) * W) < 0.6:
                    acc["overlap"] += 1
    if step["type"] == "CARRY":
        idx = next(i for i, r in enumerate(roster) if r["id"] == step["carrier"])
        gaps = []
        for f in range(1, len(frames)):
            fr = frames[f]
            gaps.append(math.hypot((fr[1] - fr[4 + k * idx]) * L, (fr[2] - fr[5 + k * idx]) * W))
        if len(gaps) > 3:
            acc["carry_gap_sd"].append(statistics.pstdev(gaps))
            acc["carry_gap_max"].append(max(gaps))
            # sawtooth: ball moving backwards relative to the carrier's motion by > 0.3 m in one frame
            acc["carry_ball_snapback"] += sum(1 for k in range(1, len(gaps)) if gaps[k - 1] - gaps[k] > 0.3)


def run(matches=30, mode="ELEVEN_A_SIDE"):
    catalog = load_catalog(Path("../data/catalogs/players.json"))
    clubs = sorted({p.club_code for p in catalog.players})
    L, W = HL_PITCH[mode]["length"], HL_PITCH[mode]["width"]
    acc = {k: 0 for k in ("ball_jump", "ball_instant_stop", "ball_frames", "frames", "accel_over_10", "instant_stop", "instant_start",
                          "snap_turn", "gk_teleport", "overlap", "carry_ball_snapback")}
    acc.update(max_speed=0.0, gk_speed_max=0.0, carry_gap_sd=[], carry_gap_max=[])
    bal = {k: 0 for k in ("goals", "shots", "on_target", "saves", "passes", "passes_completed", "chances", "actions", "interceptions", "tackles",
                          "rebound_continuations", "carries", "carries_kept")}
    outcomes, durations = {}, []
    for m in range(matches):
        home, away = clubs[m % len(clubs)], clubs[(m * 7 + 3) % len(clubs)]
        if home == away:
            away = clubs[(m + 1) % len(clubs)]
        ht, at = _team(catalog, mode, home), _team(catalog, mode, away)
        match = HighlightMatch.create(f"M{m}", mode, ht, at, team_input_view(ht), team_input_view(at), [], 1000 + m, "TRADITIONAL", 10, False, 0.0,
                                      engine=os.environ.get("ENGINE", "v6"))
        now = 0.0
        seen = set()
        while not match.finished and now < 4000:
            now += 0.5
            match.advance(now)
            opp = match.opportunity
            if opp and opp.get("replay") and opp["id"] not in seen:
                seen.add(opp["id"])
                roster = opp["bodies"]
                durations.append(sum(s["duration"] for s in opp["replay"]))
                bal["actions"] += len(opp["replay"])
                for step in opp["replay"]:
                    frame_metrics(step, roster, L, W, acc)
                    outcomes[step["outcome"]] = outcomes.get(step["outcome"], 0) + 1
                    if step["type"] == "CARRY":
                        bal["carries"] += 1
                        bal["carries_kept"] += step["outcome"] == "CONTROLLED"
                    if "rebote" in (step["detail"] or "").lower():
                        bal["rebound_continuations"] += step["outcome"] == "CONTROLLED"
        for club in match.clubs:
            st = match.stats[club]
            bal["goals"] += match.score[match.side_of(club)]
            bal["shots"] += st["shots"]
            bal["on_target"] += st["shots_on_target"]
            bal["saves"] += st["saves"]
            bal["passes"] += st["passes"]
            bal["passes_completed"] += st["passes_completed"]
            bal["chances"] += st["chances"]
            bal["interceptions"] += st["interceptions"]
            bal["tackles"] += st["tackles"]
    fr = max(1, acc["frames"])
    out = {
        "mode": mode, "matches": matches, "dt": DT, "engine": os.environ.get("ENGINE", "v6"),
        "naturalness_per_1000_player_frames": {k: round(acc[k] * 1000 / fr, 2) for k in ("accel_over_10", "instant_stop", "instant_start", "snap_turn", "overlap")},
        "ball_per_1000_frames": {k: round(acc[k] * 1000 / max(1, acc["ball_frames"]), 2) for k in ("ball_jump", "ball_instant_stop")},
        "carry": {"snapbacks_per_carry": round(acc["carry_ball_snapback"] / max(1, len(acc["carry_gap_sd"])), 2),
                  "ball_gap_sd_m": round(statistics.mean(acc["carry_gap_sd"]), 3) if acc["carry_gap_sd"] else None,
                  "ball_gap_max_m": round(statistics.mean(acc["carry_gap_max"]), 3) if acc["carry_gap_max"] else None},
        "max_player_speed": round(acc["max_speed"], 2), "gk_max_speed": round(acc["gk_speed_max"], 2), "gk_teleport_frames": acc["gk_teleport"],
        "balance_per_match": {k: round(v / matches, 2) for k, v in bal.items()},
        "pass_completion": round(bal["passes_completed"] / max(1, bal["passes"]), 3),
        "conversion": round(bal["goals"] / max(1, bal["shots"]), 3),
        "save_rate": round(bal["saves"] / max(1, bal["on_target"]), 3),
        "actions_per_chance": round(bal["actions"] / max(1, bal["chances"]), 2),
        "chance_seconds_mean": round(statistics.mean(durations), 2) if durations else None,
        "step_outcomes": outcomes,
    }
    return out


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    modes = [sys.argv[2]] if len(sys.argv) > 2 else ["ELEVEN_A_SIDE", "FIVE_A_SIDE"]
    print(json.dumps([run(n, m) for m in modes], indent=1, ensure_ascii=False))
