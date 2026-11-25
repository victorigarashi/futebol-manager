"""Custom (coach-created) players: rules, squad integration, persistence, contract and engine."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

import app.services.match_payload_service as payload_module
import app.services.transfer_service as transfer_module
from app.domain.custom_players import MAX_OVERALL, CustomPlayerSpec, custom_overall
from app.domain.football.world import Athlete
from app.domain.highlights import _bodies, team_strength
from app.domain.market import InitialMarket, MarketError
from app.services.market_service import MarketService, MarketSession
from app.services.match_payload_service import MatchPayloadService
from app.services.season_service import SeasonService, team_input_from_view
from app.services.squad_service import SquadService
from app.services.transfer_service import TransferService
from app.tests.fixtures.clock import finish_round
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog

CLUBS = tuple(f"C{i:02}" for i in range(20))
STRIKER = {"pace": 88, "shooting": 82, "passing": 60, "dribbling": 80, "defending": 35, "physical": 70}


@pytest.fixture
def game(monkeypatch):
    market = InitialMarket(synthetic_catalog("ELEVEN_A_SIDE", teams=20), "ELEVEN_A_SIDE", dict.fromkeys(CLUBS, 10_000_000_000))
    complete_test_market(market, "custom")
    markets = MarketService()
    markets.sessions["custom"] = MarketSession("custom", 0, market, finalized=True)
    seasons = SeasonService()
    seasons.create("custom", market)                     # pre-season: no match played, window closed
    squads = SquadService()
    monkeypatch.setattr(transfer_module, "market_service", markets)
    monkeypatch.setattr(transfer_module, "season_service", seasons)
    monkeypatch.setattr(transfer_module, "squad_service", squads)
    monkeypatch.setattr("app.services.season_service.squad_service", squads)
    return TransferService(), market, markets, seasons


def _striker_of(market, club="C00"):
    return next(p for p in market.teams[club].roster if market.catalog[p].position == "ST")


def test_spec_rules_overall_is_computed_never_typed():
    spec = CustomPlayerSpec(name="  Zé   da Resenha ", position="ST", attributes=STRIKER)
    assert spec.name == "Zé da Resenha"
    assert custom_overall("ST", STRIKER) == round(82 * .4 + 88 * .2 + 80 * .2 + 70 * .1 + 60 * .1)
    with pytest.raises(ValidationError, match="acima de"):
        CustomPlayerSpec(name="Craque", position="ST", attributes={k: 90 for k in STRIKER})
    with pytest.raises(ValidationError, match="entre 30 e 90"):
        CustomPlayerSpec(name="Craque", position="ST", attributes={**STRIKER, "pace": 99})
    with pytest.raises(ValidationError, match="faltando: gk_diving"):
        CustomPlayerSpec(name="Goleiro", position="GK", attributes=STRIKER)
    with pytest.raises(ValidationError, match="não aceitos"):
        CustomPlayerSpec(name="Meia", position="MF", attributes={**STRIKER, "gk_diving": 50})
    with pytest.raises(ValidationError, match="Posição"):
        CustomPlayerSpec(name="Ala", position="LW", attributes=STRIKER)
    with pytest.raises(ValidationError, match="caracteres"):
        CustomPlayerSpec(name="<script>", position="ST", attributes=STRIKER)
    assert custom_overall("ST", {**STRIKER}) <= MAX_OVERALL


def test_created_player_joins_the_club_in_place_of_one_of_the_same_position(game):
    service, market, _, _ = game
    out = _striker_of(market)
    size = len(market.teams["C00"].roster)
    spec = CustomPlayerSpec(name="Zé da Resenha", position="ST", attributes=STRIKER, shirt_number=99)
    result = asyncio.run(service.create_custom_player("custom", "C00", spec, out, "op-custom-001"))
    pid = result["player"]["id"]
    assert pid == "CUS-custom-C00-01" and pid in market.teams["C00"].roster and out not in market.teams["C00"].roster
    assert len(market.teams["C00"].roster) == size
    assert not any(out in t.roster for t in market.teams.values())                 # released: free agent
    player = market.catalog[pid]
    assert player.source == "CUSTOM" and player.attributes == STRIKER and player.overall == custom_overall("ST", STRIKER)
    again = asyncio.run(service.create_custom_player("custom", "C00", spec, out, "op-custom-001"))   # retry
    assert again["player"]["id"] == pid and sum(p.startswith("CUS-") for p in market.teams["C00"].roster) == 1
    with pytest.raises(MarketError, match="mesma posição"):
        defender = next(p for p in market.teams["C00"].roster if market.catalog[p].position == "DF")
        asyncio.run(service.create_custom_player("custom", "C00", spec, defender, "op-custom-002"))
    with pytest.raises(MarketError, match="não pertence"):
        asyncio.run(service.create_custom_player("custom", "C00", spec, _striker_of(market, "C01"), "op-custom-003"))


def test_at_most_three_per_club(game):
    service, market, _, _ = game
    for n in range(3):
        mid = next(p for p in market.teams["C00"].roster if market.catalog[p].position == "DF" and not p.startswith("CUS-"))
        asyncio.run(service.create_custom_player("custom", "C00", CustomPlayerSpec(name=f"Zagueiro {n}", position="DF",
                    attributes={"pace": 60, "shooting": 40, "passing": 55, "dribbling": 50, "defending": 75, "physical": 72}), mid, f"op-df-000{n}"))
    mid = next(p for p in market.teams["C00"].roster if market.catalog[p].position == "DF" and not p.startswith("CUS-"))
    with pytest.raises(MarketError, match="no máximo 3"):
        asyncio.run(service.create_custom_player("custom", "C00", CustomPlayerSpec(name="Quarto", position="DF",
                    attributes={"pace": 60, "shooting": 40, "passing": 55, "dribbling": 50, "defending": 75, "physical": 72}), mid, "op-df-0004"))


def test_custom_player_survives_a_server_restart(game):
    service, market, markets, _ = game
    asyncio.run(service.create_custom_player("custom", "C00", CustomPlayerSpec(name="Zé da Resenha", position="ST", attributes=STRIKER),
                                             _striker_of(market), "op-restart-01"))
    payload = markets.export_room("custom")
    restored = MarketService().restore_room(payload, lambda *_: None, schedule_tasks=False).market
    assert restored.catalog["CUS-custom-C00-01"].attributes == STRIKER
    assert "CUS-custom-C00-01" in restored.teams["C00"].roster


def test_not_allowed_during_the_season_with_the_window_closed(game):
    service, market, _, seasons = game
    seasons.ready("custom", "C00")
    seasons.advance("custom", market, {"C00"})
    with pytest.raises(MarketError, match="pré-temporada"):
        asyncio.run(service.create_custom_player("custom", "C00", CustomPlayerSpec(name="Tarde Demais", position="ST", attributes=STRIKER),
                                                 _striker_of(market), "op-late-0001"))


def test_custom_player_reaches_the_frozen_round_the_contract_and_the_engine(game, monkeypatch):
    service, market, _, seasons = game
    result = asyncio.run(service.create_custom_player("custom", "C00", CustomPlayerSpec(name="Zé da Resenha", position="ST", attributes=STRIKER),
                                                      _striker_of(market), "op-engine-01"))
    pid = result["player"]["id"]
    seasons.ready("custom", "C00")
    seasons.advance("custom", market, {"C00"})
    season = seasons._season("custom")
    match_id = next(m for m in season.live_round["match_ids"] if "C00" in (season.matches[m]["home"], season.matches[m]["away"]))
    monkeypatch.setattr(payload_module, "season_service", seasons)
    payload = MatchPayloadService(seasons).payload_for("custom", match_id)
    team = payload.home if payload.home.club_code == "C00" else payload.away
    zé = next(p for p in (*team.starters, *team.bench) if p.player_id == pid)
    assert zé.origin == "CUSTOM" and zé.name == "Zé da Resenha" and zé.stats.provenance == "CATALOG"
    assert {k: zé.stats.attributes[k] for k in STRIKER} == STRIKER and zé.stats.estimated_keys == ()
    # The engine plays him with these attributes (physics: top speed comes from pace).
    frozen = seasons.frozen_match("custom", match_id)
    view = frozen["home"] if frozen["home"]["club_code"] == "C00" else frozen["away"]
    body = next((b for b in _bodies(team_input_from_view(view), "A") if b.id == pid), None)
    if body is not None:                                  # a starter: on the pitch from kick-off
        assert body.pace == STRIKER["pace"] and body.shooting == STRIKER["shooting"]
    finish_round(seasons, "custom")
    assert seasons.frozen_match("custom", match_id)["status"] == "FINISHED"


def test_attributes_change_how_the_team_plays(game):
    """Same line-up, only the attributes differ: the engine's team strength and the athletes'
    physics (top speed) change — attributes are not decoration."""
    _, market, _, seasons = game
    seasons.ready("custom", "C00")
    seasons.advance("custom", market, {"C00"})
    season = seasons._season("custom")
    match_id = season.live_round["match_ids"][0]
    view = season.matches[match_id]["inputs"]["home"]
    slow = {**view, "starters": [{**r, "attributes": {k: 45 for k in STRIKER}} if r["slot_position"] != "GK" else r for r in view["starters"]]}
    fast = {**view, "starters": [{**r, "attributes": {k: 85 for k in STRIKER}} if r["slot_position"] != "GK" else r for r in view["starters"]]}
    s_slow, s_fast = team_strength(team_input_from_view(slow)), team_strength(team_input_from_view(fast))
    assert s_fast[0] > s_slow[0] + 20 and s_fast[1] > s_slow[1] + 20          # attack and defence
    b_slow = next(b for b in _bodies(team_input_from_view(slow), "A") if b.role == "ST")
    b_fast = next(b for b in _bodies(team_input_from_view(fast), "A") if b.role == "ST")
    a = Athlete(b_fast.id, b_fast.name, 9, "A", "ST", 0, 0, b_fast.pace, 60, 60, 60, 60, 60, 60)
    b = Athlete(b_slow.id, b_slow.name, 9, "A", "ST", 0, 0, b_slow.pace, 60, 60, 60, 60, 60, 60)
    assert a.top_speed > b.top_speed + 1.0                                      # m/s
