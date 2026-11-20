"""Dump the authoritative engine frames of reproducible plays (goal, save, miss, corner).

Same seeds and real squads every run, so a change to the engine can be compared visually
(see docs/evidencias/2d/README.md and render.py there).

    cd backend && ../.venv/bin/python tools/visual_scenarios.py /tmp/quadros
"""

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

from app.domain import match_engine as engine_module  # noqa: E402
from app.domain.bot_coach import advance_with_bots  # noqa: E402
from app.domain.catalog import load_catalog  # noqa: E402
from app.domain.clubs import CLUBS  # noqa: E402
from app.domain.market import InitialMarket  # noqa: E402
from app.services.season_service import SeasonService  # noqa: E402
from app.tests.fixtures.market_catalog import complete_test_market  # noqa: E402

KINDS = {("SHOT", "GOAL"): "gol", ("SHOT", "ON_TARGET"): "defesa", ("SHOT", "OFF_TARGET"): "chute_fora"}


def scene_kind(event: dict) -> str | None:
    if event["kind"] == "CORNER":
        return "escanteio"
    return KINDS.get((event["kind"], event.get("outcome")))


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    service = SeasonService(clock=lambda: 1e6)
    catalog = load_catalog(Path("../data/catalogs/players.json"))
    market = InitialMarket(catalog, "ELEVEN_A_SIDE", dict.fromkeys((club.code for club in CLUBS), 10**10))
    complete_test_market(market, "viz")
    service.create("viz", market)
    found: dict[str, dict] = {}
    for fixture in service._season("viz").state.fixtures[:6]:
        home, away, seed, _ = service._fixture_inputs("viz", market, fixture, set())
        engine = engine_module.MatchEngine(fixture.id, "ELEVEN_A_SIDE", home, away, seed)
        engine.record_frames = True
        engine.frames = collections.deque()
        advance_with_bots(engine, engine_module.FULL_TIME_TICK, (0, 1), (home.tactics, away.tactics))
        frames = {row[0]: row for row in engine.frames}
        for event in engine.events:
            kind = scene_kind(event)
            if not kind or kind in found:
                continue
            start, end = max(1, event["tick"] - 14), min(engine_module.FULL_TIME_TICK, event["tick"] + 5)
            rows = [frames[tick] for tick in range(start, end + 1) if tick in frames]
            if len(rows) < 10:
                continue
            found[kind] = {
                "match": fixture.id, "tick": event["tick"], "home": engine.clubs[0], "away": engine.clubs[1],
                "n_home": len(engine.team_agents[0]), "L": engine.L, "W": engine.W,
                "frames": [{"t": r[0], "b": [r[1], r[2], r[3], r[5]], "p": r[4]} for r in rows],
                "events": [e for e in engine.events if start <= e["tick"] <= end and e["kind"] in ("SHOT", "GOAL", "SAVE", "CORNER", "FOUL")],
            }
        if len(found) == 4:
            break
    for kind, data in found.items():
        (out / f"{kind}.json").write_text(json.dumps(data, default=list))
    print(out, sorted(found))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
