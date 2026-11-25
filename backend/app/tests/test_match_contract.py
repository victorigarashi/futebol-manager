"""MatchPayload v1 and engine adapters (Phase 1 of the external-engine study).

No external engine is involved: these tests prove the neutral contract built from the
season's frozen snapshots, its validation rules, its stability, and that the experimental
PES 2013 adapter refuses everything (and is unreachable with the flag off).
"""

from __future__ import annotations

import copy

import pytest

from app.core.config import get_settings
from app.domain.engine_adapters import (
    CurrentEngineAdapter,
    EngineCapabilityError,
    Pes2013Adapter,
    engine_adapter,
    engines_view,
)
from app.domain.market import InitialMarket, MarketError
from app.domain.match_contract import (
    MatchContractError,
    build_match_payload,
    payload_checksum,
    verify_checksum,
)
from app.services.match_payload_service import MatchPayloadService
from app.services.season_service import SeasonService
from app.tests.fixtures.clock import finish_round
from app.tests.fixtures.market_catalog import complete_test_market, synthetic_catalog

CLUBS = tuple(f"C{number:02}" for number in range(20))


def _season(mode: str = "ELEVEN_A_SIDE", room: str = "pes", move: tuple[str, str] | None = None):
    market = InitialMarket(synthetic_catalog(mode, teams=20), mode, dict.fromkeys(CLUBS, 10_000_000_000))
    complete_test_market(market, room)
    if move:
        # A player bought by another club before the round: he must play for the buyer.
        seller, buyer = move
        player = next(p for p in market.teams[seller].roster if market.catalog[p].position == "MF")
        market.teams[seller].roster.remove(player)
        market.teams[buyer].roster.append(player)
    service = SeasonService()
    service.create(room, market)
    service.ready(room, "C00")
    service.advance(room, market, {"C00"})
    return service, market


def _first_match(service: SeasonService, room: str) -> str:
    return service._season(room).live_round["match_ids"][0]


@pytest.mark.parametrize("mode,size", [("FIVE_A_SIDE", 5), ("ELEVEN_A_SIDE", 11)])
def test_payload_from_the_frozen_round_respects_the_mode(mode, size):
    service, _ = _season(mode, room=f"pes-{mode}")
    payloads = MatchPayloadService(service)
    match_id = _first_match(service, f"pes-{mode}")
    payload = payloads.payload_for(f"pes-{mode}", match_id)
    frozen = service.frozen_match(f"pes-{mode}", match_id)
    assert payload.schema_version == 1 and payload.mode == mode and payload.match_id == match_id
    assert payload.home.club_code == frozen["home"]["club_code"] and payload.away.club_code == frozen["away"]["club_code"]
    assert payload.home.side == "HOME" and payload.away.side == "AWAY"
    for team in (payload.home, payload.away):
        assert len(team.starters) == size
        assert sum(p.slot_position == "GK" for p in team.starters) == 1
        assert all(p.origin == "CATALOG" for p in (*team.starters, *team.bench))
    assert verify_checksum(payload)


def test_bought_player_plays_for_his_current_club_and_attributes_are_never_invented():
    service, market = _season(room="pes-move", move=("C03", "C00"))
    season = service._season("pes-move")
    moved = next(p for p in market.teams["C00"].roster if p.startswith("C03") or market.catalog[p].club_code == "C03")
    match_id = next(m for m in season.live_round["match_ids"] if "C00" in (season.matches[m]["home"], season.matches[m]["away"]))
    payload = MatchPayloadService(service).payload_for("pes-move", match_id)
    team = payload.home if payload.home.club_code == "C00" else payload.away
    ids = {p.player_id for p in (*team.starters, *team.bench)}
    other = payload.away if team is payload.home else payload.home
    assert moved not in {p.player_id for p in (*other.starters, *other.bench)}
    assert moved in ids or len(market.teams["C00"].roster) > len(ids)      # in the squad (lineup or beyond the 7-man bench)
    for player in (*team.starters, *team.bench):
        catalog = market.catalog[player.player_id]
        assert player.name == catalog.name
        if not catalog.attributes:
            assert player.stats.attributes == {} and player.stats.provenance == "OVERALL_ONLY"
        else:
            assert set(player.stats.attributes) == set(catalog.attributes) and player.stats.provenance == "CATALOG"


def test_snapshot_is_stable_after_the_market_changes():
    service, market = _season(room="pes-stable")
    payloads = MatchPayloadService(service)
    match_id = _first_match(service, "pes-stable")
    before = payloads.payload_for("pes-stable", match_id)
    club = before.home.club_code
    sold = before.home.starters[3].player_id
    market.teams[club].roster.remove(sold)            # the market moves on after kick-off
    after = payloads.payload_for("pes-stable", match_id)
    assert after == before and after.checksum == before.checksum


def test_contract_rejects_invalid_fixtures():
    service, _ = _season(room="pes-reject")
    frozen = service.frozen_match("pes-reject", _first_match(service, "pes-reject"))
    home, away = frozen["home"], frozen["away"]

    def build(h, a, mode="ELEVEN_A_SIDE"):
        return build_match_payload("m", mode, h, a, seed=1)

    build(home, away)                                                     # the real one is valid
    incomplete = copy.deepcopy(home)
    incomplete["starters"] = incomplete["starters"][:-1]
    with pytest.raises(MatchContractError, match="incompleta"):
        build(incomplete, away)
    duplicated = copy.deepcopy(away)
    duplicated["bench"] = duplicated["bench"] + [copy.deepcopy(home["starters"][2])]
    with pytest.raises(MatchContractError, match="mais de uma vez"):
        build(home, duplicated)
    bad_formation = copy.deepcopy(home)
    bad_formation["formation_code"] = "9-0-1"
    with pytest.raises(MatchContractError, match="Formação"):
        build(bad_formation, away)
    two_keepers = copy.deepcopy(home)
    two_keepers["starters"][1]["slot_position"] = "GK"
    with pytest.raises(MatchContractError):
        build(two_keepers, away)
    with pytest.raises(MatchContractError, match="si mesmo"):
        build(home, home)
    with pytest.raises(MatchContractError, match="Modo"):
        build(home, away, mode="SEVEN_A_SIDE")
    invented = copy.deepcopy(home)
    invented["starters"][4]["attributes"] = {"overall_magic": 99}
    with pytest.raises(MatchContractError, match="desconhecidos"):
        build(invented, away)
    with pytest.raises(MarketError, match="inexistente"):
        service.frozen_match("pes-reject", "no-such-match")


def test_tampered_payload_is_refused_by_the_adapter():
    service, _ = _season(room="pes-tamper")
    payload = MatchPayloadService(service).payload_for("pes-tamper", _first_match(service, "pes-tamper"))
    tampered = payload.model_copy(update={"seed": payload.seed + 1})
    assert not verify_checksum(tampered) and payload_checksum(tampered) != payload.checksum
    with pytest.raises(EngineCapabilityError, match="adulterado"):
        CurrentEngineAdapter().prepare(tampered)
    assert CurrentEngineAdapter().prepare(payload).payload_checksum == payload.checksum


def test_finished_match_cannot_be_prepared_again():
    service, _ = _season(room="pes-done")
    payloads = MatchPayloadService(service)
    match_id = _first_match(service, "pes-done")
    assert payloads.prepare("pes-done", match_id, "RESENHA").match_id == match_id
    finish_round(service, "pes-done")
    assert service.frozen_match("pes-done", match_id)["status"] == "FINISHED"
    with pytest.raises(MarketError, match="encerrada"):
        payloads.prepare("pes-done", match_id, "RESENHA")
    assert payloads.payload_for("pes-done", match_id).match_id == match_id     # still readable (reproducibility)


def test_pes2013_is_unreachable_with_the_flag_off_and_refuses_everything_with_it_on(monkeypatch):
    assert get_settings().pes2013_adapter_enabled is False
    with pytest.raises(EngineCapabilityError, match="desativado"):
        engine_adapter("PES2013_WEB", pes2013_enabled=False)
    listed = {e["name"]: e for e in engines_view(pes2013_enabled=False)}
    assert listed["PES2013_WEB"]["status"] == "DISABLED" and listed["RESENHA"]["status"] == "AVAILABLE"
    caps = Pes2013Adapter().capabilities()
    assert not any((caps.can_load_custom_roster, caps.can_select_teams, caps.can_auto_start_match, caps.can_read_result,
                    caps.can_netplay, caps.supports_5v5, caps.supports_11v11))
    assert {e["name"]: e for e in engines_view(pes2013_enabled=True)}["PES2013_WEB"]["status"] == "EXPERIMENTAL_UNAVAILABLE"
    service, _ = _season(room="pes-flag")
    match_id = _first_match(service, "pes-flag")
    monkeypatch.setattr(get_settings(), "pes2013_adapter_enabled", True)
    with pytest.raises(EngineCapabilityError, match="não validada"):
        MatchPayloadService(service).prepare("pes-flag", match_id, "PES2013_WEB")
    with pytest.raises(EngineCapabilityError, match="desconhecida"):
        engine_adapter("FIFA", pes2013_enabled=True)


def test_flag_off_changes_nothing_in_how_a_round_is_played():
    """The adapter layer is read-only: two identical seasons, one of them read through the
    payload service mid-round, produce identical official results (same room id: the seeds
    derive from it)."""
    results = []
    for read in (False, True):
        service, _ = _season(room="pes-same")
        if read:
            for match_id in service._season("pes-same").live_round["match_ids"]:
                MatchPayloadService(service).payload_for("pes-same", match_id)
        view = finish_round(service, "pes-same")
        results.append([(m["home"], m["away"], m.get("home_goals"), m.get("away_goals")) for m in view["matches"]])
    assert results[0] == results[1]


def test_engines_endpoint_lists_pes2013_as_disabled():
    from fastapi.testclient import TestClient

    from app import main as main_module

    with TestClient(main_module.create_app()) as client:
        body = client.get("/api/v1/match-engines").json()
    engines = {e["name"]: e for e in body["data"]["engines"]}
    assert engines["RESENHA"]["status"] == "AVAILABLE" and engines["RESENHA"]["capabilities"]["can_netplay"] is True
    assert engines["PES2013_WEB"]["status"] == "DISABLED"
    assert engines["PES2013_WEB"]["capabilities"]["can_load_custom_roster"] is False
