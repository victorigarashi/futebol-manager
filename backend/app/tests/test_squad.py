import json

import pytest

from app.domain.catalog import CatalogPlayer
from app.domain.market import MarketError
from app.domain.squad import effective_overall, formation_slots, simulation_overall, validate_lineup
from app.services.snapshots import load_snapshot, write_snapshot
from app.tests.fixtures.market_catalog import synthetic_catalog


def test_formation_coordinates_and_effective_rating_are_server_defined() -> None:
    slots = formation_slots("FIVE_A_SIDE", "1-2-1")
    assert len(slots) == 5
    assert slots[0].position == "GK"
    player = synthetic_catalog("FIVE_A_SIDE").players[0]
    rating, improvised = effective_overall(player, "ST")
    assert improvised is (player.position != "ST")
    assert rating <= player.overall


def test_editorial_components_adjust_match_rating_but_synthetic_falls_back_to_overall() -> None:
    striker = CatalogPlayer(id="real", name="Real", club_code="FLA", age=None, position="ST", overall=70, potential=80, market_value_cents=0, source="EDITORIAL_ESTIMATE", source_version="v1", attributes={"shooting": 90, "pace": 80, "dribbling": 80, "physical": 80})
    generic = CatalogPlayer(id="generic", name="Genérico", club_code="FLA", age=20, position="ST", overall=70, potential=80, market_value_cents=0, source="synthetic-career", source_version="v1")
    assert simulation_overall(striker, 70) > 70
    assert simulation_overall(generic, 70) == 70


def test_lineup_uses_starters_from_roster_with_reserves_and_goalkeeper() -> None:
    catalog = synthetic_catalog("FIVE_A_SIDE")
    players = {player.id: player for player in catalog.players[:8]}
    roster = list(players)
    slots = formation_slots("FIVE_A_SIDE", "1-2-1")
    assignments = {slot.id: player_id for slot, player_id in zip(slots, roster[:5], strict=True)}
    assert len(validate_lineup(mode="FIVE_A_SIDE", formation_code="1-2-1", assignments=assignments, roster=roster, players=players)) == 5
    outfield_id = next(player_id for player_id in roster[:5] if players[player_id].position != "GK")
    outfield_slot = next(slot_id for slot_id, player_id in assignments.items() if player_id == outfield_id)
    assignments[outfield_slot], assignments["gk"] = assignments["gk"], outfield_id
    with pytest.raises(MarketError, match="goleiro"):
        validate_lineup(mode="FIVE_A_SIDE", formation_code="1-2-1", assignments=assignments, roster=roster, players=players)


def test_snapshot_write_is_atomic_and_valid_json(tmp_path) -> None:
    path = tmp_path / "snapshots" / "rooms.json"
    write_snapshot(path, {"rooms": {"room-a": {"phase": "SQUAD_MANAGEMENT"}}})
    assert json.loads(path.read_text(encoding="utf-8"))["rooms"]["room-a"]["phase"] == "SQUAD_MANAGEMENT"
    assert load_snapshot(path)["schema_version"] == 2


def test_corrupt_snapshot_is_rejected_and_preserved(tmp_path) -> None:
    path = tmp_path / "rooms.json"
    path.write_text('{"schema_version": 2, "rooms": {"room": {}}, "checksum_sha256": "bad"}', encoding="utf-8")
    original = path.read_bytes()
    with pytest.raises(ValueError, match="corrompido"):
        load_snapshot(path)
    assert path.read_bytes() == original
