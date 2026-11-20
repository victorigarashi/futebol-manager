"""Dump authoritative engine frames of reproducible plays (run with the project venv)."""
import collections
import json
import sys

sys.path.insert(0, ".")
from pathlib import Path

from app.domain import match_engine as ME
from app.domain.bot_coach import advance_with_bots
from app.domain.catalog import load_catalog
from app.domain.clubs import CLUBS
from app.domain.market import InitialMarket
from app.services.season_service import SeasonService
from app.tests.fixtures.market_catalog import complete_test_market

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
svc = SeasonService(clock=lambda: 1e6); cat = load_catalog(Path("../data/catalogs/players.json"))
m = InitialMarket(cat, "ELEVEN_A_SIDE", dict.fromkeys((c.code for c in CLUBS), 10**10)); complete_test_market(m, "viz"); svc.create("viz", m)
found = {}
for f in svc._season("viz").state.fixtures[:6]:
    h, a, seed, _ = svc._fixture_inputs("viz", m, f, set())
    e = ME.MatchEngine(f.id, "ELEVEN_A_SIDE", h, a, seed); e.record_frames = True; e.frames = collections.deque()
    advance_with_bots(e, ME.FULL_TIME_TICK, (0, 1), (h.tactics, a.tactics))
    fr = {x[0]: x for x in e.frames}
    n0 = len(e.team_agents[0])
    for ev in e.events:
        t = ev["tick"]
        kind = None
        if ev["kind"] == "SHOT" and ev["outcome"] == "GOAL": kind = "gol"
        elif ev["kind"] == "SHOT" and ev["outcome"] == "ON_TARGET": kind = "defesa"
        elif ev["kind"] == "SHOT" and ev["outcome"] == "OFF_TARGET": kind = "chute_fora"
        elif ev["kind"] == "CORNER": kind = "escanteio"
        if not kind or kind in found: continue
        start, end = max(1, t - 14), min(ME.FULL_TIME_TICK, t + 5)
        rows = [fr[k] for k in range(start, end + 1) if k in fr]
        if len(rows) < 10: continue
        found[kind] = {"match": f.id, "tick": t, "home": e.clubs[0], "away": e.clubs[1], "n_home": n0, "L": e.L, "W": e.W,
                       "frames": [{"t": r[0], "b": [r[1], r[2], r[3], r[5]], "p": r[4]} for r in rows],
                       "events": [x for x in e.events if start <= x["tick"] <= end and x["kind"] in ("SHOT", "GOAL", "SAVE", "CORNER", "FOUL")]}
    if len(found) == 4: break
for kind, data in found.items():
    (out / f"{kind}.json").write_text(json.dumps(data, default=list))
print(out, sorted(found))
