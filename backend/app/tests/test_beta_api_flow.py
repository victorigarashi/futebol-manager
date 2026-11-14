"""HTTP acceptance through real services, with isolated state and controlled clocks.

Only time and process-local stores are isolated. Requests use the production router,
validation, authentication, deterministic engine and financial rules.
"""

import copy
import time

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
import app.services.season_service as season_module
import app.services.squad_service as squad_module
import app.services.transfer_service as transfer_module
from app.api import routes
from app.core.config import Settings
from app.domain.rooms import RoomManager
from app.services.auth import SESSION_COOKIE
from app.services.market_service import MarketService
from app.services.realtime import RoomConnectionHub
from app.services.season_service import SeasonService
from app.services.squad_service import SquadService
from app.services.transfer_service import TransferService


@pytest.fixture
def beta_api(monkeypatch):
    now = [1_900_000_000.0]
    rooms = RoomManager()
    market = MarketService(clock=lambda: now[0])
    seasons = SeasonService(clock=lambda: now[0])
    squads = SquadService()
    transfers = TransferService()
    tasks = {}
    settings = Settings(_env_file=None, app_environment="test", enable_demo_catalog=True)
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    for module, replacements in (
        (routes, {"room_manager": rooms, "market_service": market, "season_service": seasons,
                  "squad_service": squads, "transfer_service": transfers,
                  "hub": RoomConnectionHub(), "round_tasks": tasks, "round_locks": {}}),
        (main_module, {"season_service": seasons, "round_tasks": tasks}),
        (squad_module, {"market_service": market}),
        (season_module, {"squad_service": squads}),
        (transfer_module, {"market_service": market, "season_service": seasons, "squad_service": squads}),
    ):
        for name, value in replacements.items():
            monkeypatch.setattr(module, name, value)
    with TestClient(main_module.create_app()) as client:
        identities = []
        for _ in range(3):
            response = client.post("/api/v1/auth/guest")
            assert response.status_code == 201
            identities.append(({"cookie": f"{SESSION_COOKIE}={response.cookies[SESSION_COOKIE]}"}, response.json()["data"]))
        yield client, identities, rooms, market, seasons, squads, transfers, now


def checked(client, method, path, *, headers, status=200, **kwargs):
    response = client.request(method, "/api/v1" + path, headers=headers, **kwargs)
    assert response.status_code == status, response.text
    return response.json().get("data") if response.content else None


def create_two_coach_room(client, identities, mode):
    host, guest = identities[0][0], identities[1][0]
    room = checked(client, "POST", "/rooms", headers=host, status=201, json={
        "name": "Resenha integração", "mode": mode, "initial_budget_cents": 10_000_000_000,
        "max_human_participants": 3, "privacy": "PRIVATE", "initial_market_duration_seconds": 120,
        "withdrawal_penalty_percent": 10,
    })
    base = f"/rooms/{room['id']}"
    checked(client, "POST", "/rooms/join", headers=guest, json={"code": room["code"]})
    checked(client, "PUT", base + "/participants/me/club", headers=host, json={"club_code": "FLA"})
    checked(client, "PUT", base + "/participants/me/club", headers=guest, json={"club_code": "PAL"})
    return room, base, host, guest


@pytest.mark.parametrize("duration", [120, 180, 300, 600])
def test_room_accepts_short_round_preparation_windows(beta_api, duration):
    client, identities, *_ = beta_api
    room = checked(client, "POST", "/rooms", headers=identities[0][0], status=201, json={
        "name": "Resenha rápida", "mode": "FIVE_A_SIDE", "initial_budget_cents": 5_000_000_000,
        "max_human_participants": 2, "privacy": "PRIVATE", "initial_market_duration_seconds": 120,
        "round_preparation_duration_seconds": duration,
    })
    assert room["round_preparation_duration_seconds"] == duration


@pytest.mark.parametrize(("mode", "starter_count", "roster_count"), [
    ("FIVE_A_SIDE", 5, 8), ("ELEVEN_A_SIDE", 11, 16),
])
def test_real_api_market_to_second_season_and_snapshot(beta_api, mode, starter_count, roster_count):
    client, identities, rooms, market, seasons, squads, transfers, now = beta_api
    room, base, host, guest = create_two_coach_room(client, identities, mode)
    room_id = room["id"]
    checked(client, "POST", base + "/start", headers=guest, status=403)
    checked(client, "POST", base + "/start", headers=host)
    players = checked(client, "GET", base + "/market/players?position=GK", headers=host)
    target, retained = players[:2]
    budget = checked(client, "GET", base + "/market", headers=host)["budget_cents"]

    def bid(headers, player, amount, key):
        return checked(client, "POST", base + "/market/offers", headers=headers, status=201,
                       json={"player_id": player["id"], "amount_cents": amount, "idempotency_key": key})

    # Winner voluntarily declines one commitment; the losing human receives a
    # second opportunity only after the winner confirms, never secret bid data.
    low = bid(guest, target, target["market_value_cents"], "guest-target-bid")
    high = bid(host, target, target["market_value_cents"] * 3, "host-target-bid")
    keep = bid(host, retained, retained["market_value_cents"] * 2, "host-retained-bid")
    assert bid(host, retained, retained["market_value_cents"] * 2, "host-retained-bid")["id"] == keep["id"]
    mine = checked(client, "GET", base + "/market", headers=guest)
    assert [item["id"] for item in mine["offers"]] == [low["id"]]
    assert high["id"] not in str(mine)
    checked(client, "PUT", base + f"/market/offers/{high['id']}", headers=guest,
            status=409, json={"amount_cents": target["market_value_cents"] * 4})
    checked(client, "GET", base + "/market/review", headers=host, status=409)
    checked(client, "POST", base + "/market/selection/confirm", headers=host,
            status=409, json={"offer_ids": [keep["id"]]})

    now[0] = market._session(room_id).ends_at
    checked(client, "GET", base + "/market", headers=host)
    selection = checked(client, "GET", base + "/market/selection", headers=host)
    assert {entry["offer_id"] for entry in selection["committed"]} == {high["id"], keep["id"]}
    preview = checked(client, "POST", base + "/market/selection/preview", headers=host,
                      json={"offer_ids": [keep["id"]]})
    assert preview["penalty_cents"] == high["amount_cents"] // 10
    assert checked(client, "GET", base + "/market", headers=host)["budget_cents"] == budget
    confirmed = checked(client, "POST", base + "/market/selection/confirm", headers=host,
                        json={"offer_ids": [keep["id"]]})
    repeated = checked(client, "POST", base + "/market/selection/confirm", headers=host,
                       json={"offer_ids": [keep["id"]]})
    assert confirmed == repeated
    assert market._session(room_id).market.teams["FLA"].budget_cents == budget - preview["debit_cents"]
    checked(client, "POST", base + "/market/selection/confirm", headers=guest, json={"offer_ids": []})
    opportunity = checked(client, "GET", base + "/market/reassignment", headers=guest)["opportunity"]
    assert opportunity and opportunity["offer_id"] == low["id"]
    checked(client, "POST", base + f"/market/reassignment/{low['id']}", headers=host,
            status=409, json={"accept": True})
    checked(client, "POST", base + f"/market/reassignment/{low['id']}", headers=guest,
            json={"accept": True})
    review = checked(client, "GET", base + "/market/review", headers=host)
    assert any(row["player_id"] == retained["id"] and row["buyer_club_code"] == "FLA" for row in review["entries"])
    assert any(row["player_id"] == target["id"] and row["buyer_club_code"] == "PAL" for row in review["entries"])
    assert all("idempotency_key" not in row and "offers" not in row for row in review["entries"])
    checked(client, "POST", base + "/market/review/complete", headers=guest, status=403)
    checked(client, "POST", base + "/market/review/complete", headers=host)

    for headers, club in ((host, "FLA"), (guest, "PAL")):
        squad = checked(client, "GET", base + "/squad", headers=headers)
        assert len(squad["players"]) == roster_count
        formation = squad["formations"][0]
        available = list(squad["players"])
        assignments = {}
        for slot in formation["slots"]:
            player = next((p for p in available if p["position"] == slot["position"]),
                          next((p for p in available if p["position"] != "GK"), available[0]))
            assignments[slot["id"]] = player["id"]
            available.remove(player)
        lineup = checked(client, "PUT", base + "/squad/lineup", headers=headers,
                         json={"formation_code": formation["code"], "assignments": assignments})
        assert len(lineup["evaluation"]) == starter_count
        invalid = dict(assignments)
        invalid[formation["slots"][-1]["id"]] = assignments["gk"]
        checked(client, "PUT", base + "/squad/lineup", headers=headers, status=409,
                json={"formation_code": formation["code"], "assignments": invalid})
        checked(client, "PUT", base + "/squad/strategy", headers=headers, json={"strategy": "COUNTER"})
        assert squads.strategy_for(room_id, club) == "COUNTER"
    ownership = [player for team in market._session(room_id).market.teams.values() for player in team.roster]
    assert len(ownership) == len(set(ownership)) == roster_count * 20
    checked(client, "POST", base + "/season/start", headers=host)

    for round_number in range(1, 39):
        checked(client, "POST", base + "/season/ready", headers=host)
        started = checked(client, "POST", base + "/season/ready", headers=guest)
        assert started["live_round"]["round_number"] == round_number
        assert len(started["live_round"]["match_ids"]) == 10
        live = checked(client, "GET", base + "/season/live", headers=host)
        # Nothing is simulated ahead of the server clock: only kick-off has happened.
        assert all(e["tick"] == 0 for e in live["match"]["events"])
        assert len(seasons._season(room_id).state.results) == (round_number - 1) * 10
        if round_number == 1:
            checked(client, "PUT", base + "/squad/strategy", headers=host, status=409,
                    json={"strategy": "ATTACKING"})
        now[0] = started["live_round"]["ends_at"]
        # Reaching full time makes the server play the rest of all ten matches.
        deadline = time.monotonic() + 60
        while seasons._season(room_id).live_round and time.monotonic() < deadline:
            time.sleep(.01)
        assert seasons._season(room_id).live_round is None
        official = checked(client, "GET", base + "/season", headers=host)
        assert official["current_round"] == round_number + 1
        if round_number == 19:
            assert rooms._room(room_id).phase == "TRANSFER_WINDOW"
            clubs = checked(client, "GET", base + "/transfers/clubs", headers=host)
            other = next(club for club in clubs if club["club_code"] == "PAL")
            buyer_team = market._session(room_id).market.teams["FLA"]
            offered = next(pid for pid in buyer_team.roster if market._session(room_id).market.catalog[pid].position == "DF")
            incoming = next(player["id"] for player in other["players"] if player["position"] == "DF")
            offer = checked(client, "POST", base + "/transfers/offers", headers=host,
                            json={"incoming_player_id": incoming, "offered_player_id": offered,
                                  "amount_cents": 100, "idempotency_key": "midseason-http-trade"})
            assert offer["status"] == "PENDING"
            checked(client, "POST", base + f"/transfers/offers/{offer['id']}/counter", headers=guest,
                    json={"amount_cents": 200})
            checked(client, "POST", base + f"/transfers/offers/{offer['id']}/accept", headers=host)
            assert incoming in buyer_team.roster and offered not in buyer_team.roster
            career = checked(client, "GET", base + "/career", headers=host)
            assert career["club_code"] == "FLA"
            assert any(entry["type"] == "TRANSFER" for entry in career["financial_ledger"])
            checked(client, "GET", base + "/career", headers=identities[2][0], status=403)
            checked(client, "POST", base + "/season/transfer-window/close", headers=host)

    for _ in range(3):
        completed = checked(client, "POST", base + "/season/advance", headers=host)
    assert completed["season_complete"] and completed["champion"]
    assert completed["progression_applied"]
    assert len(completed["matches"]) == 387
    snapshot = copy.deepcopy(seasons.export_room(room_id))
    restored = SeasonService(clock=lambda: now[0])
    restored.restore_room(room_id, snapshot)
    assert restored.view(room_id)["champion"] == completed["champion"]
    following = checked(client, "POST", base + "/season/next", headers=host)
    assert following["season_number"] == 2
    assert following["current_round"] == 1
    assert following["season_history"][0]["champion"] == completed["champion"]
    assert following["match_count"] == 0
    career = checked(client, "GET", base + "/career", headers=host)
    assert career["season_history"][0]["champion"] == completed["champion"]
    assert len(career["players"]) == roster_count
    assert len(career["development_records"]) >= roster_count


def test_lobby_state_survives_profile_edit_and_forbids_late_club_or_member(beta_api):
    client, identities, rooms, market, _, _, _, _ = beta_api
    room, base, host, guest = create_two_coach_room(client, identities, "FIVE_A_SIDE")
    updated_response = client.put("/api/v1/me", headers=guest, json={"display_name": "Tecnico Resenha"})
    assert updated_response.status_code == 200
    assert updated_response.json()["data"]["id"] == identities[1][1]["id"]
    state = checked(client, "GET", base + "/state", headers=host)
    assert next(p for p in state["participants"] if p["user_id"] == identities[1][1]["id"])["display_name"] == "Tecnico Resenha"
    mine = checked(client, "GET", "/rooms/mine", headers=guest)
    assert [item["id"] for item in mine] == [room["id"]]
    assert checked(client, "GET", "/rooms/mine", headers=identities[2][0]) == []
    checked(client, "POST", base + "/start", headers=host)
    rejoined = checked(client, "POST", base + "/join", headers=guest)
    assert rejoined["id"] == room["id"]
    checked(client, "POST", base + "/join", headers=identities[2][0], status=409)
    checked(client, "PUT", base + "/participants/me/club", headers=guest,
            status=409, json={"club_code": "BOT"})
    checked(client, "PUT", base + "/participants/me/club", headers=guest, json={"club_code": "PAL"})
    assert rooms._room(room["id"]).participants[identities[1][1]["id"]].selected_club_code == "PAL"
    assert room["id"] in market.sessions


def test_host_cannot_start_when_a_joined_coach_has_no_club(beta_api):
    client, identities, rooms, market, _, _, _, _ = beta_api
    host, guest = identities[0][0], identities[1][0]
    room = checked(client, "POST", "/rooms", headers=host, status=201, json={
        "name": "Aguardando técnico", "mode": "FIVE_A_SIDE", "initial_budget_cents": 10_000_000_000,
        "max_human_participants": 3, "privacy": "PRIVATE",
    })
    base = f"/rooms/{room['id']}"
    checked(client, "POST", base + "/join", headers=guest)
    checked(client, "PUT", base + "/participants/me/club", headers=host, json={"club_code": "FLA"})
    checked(client, "POST", base + "/start", headers=host, status=409)
    assert rooms._room(room["id"]).phase == "WAITING"
    assert room["id"] not in market.sessions


def test_rejected_session_tokens_fail_with_401_instead_of_server_errors():
    from fastapi import HTTPException

    from app.services.auth import _encode, _signature, identity_from_token

    tokens = [None, "invalid", "bad.signature", "á.invalid", "é.é", ".", "a." * 200]
    for body in ({}, {"id": 12, "name": []}, {"id": "", "name": ""}):
        payload = _encode(body)
        tokens.append(f"{payload}.{_signature(payload)}")
    for token in tokens:
        with pytest.raises(HTTPException) as invalid:
            identity_from_token(token)
        assert invalid.value.status_code == 401


def test_preparation_endpoints_return_conflicts_before_their_state_exists(beta_api):
    client, identities, _, _, _, _, _, _ = beta_api
    _, base, host, _ = create_two_coach_room(client, identities, "FIVE_A_SIDE")
    for path in ("/market", "/market/selection", "/market/reassignment", "/market/review",
                 "/squad", "/season", "/season/live", "/career", "/transfers/available"):
        checked(client, "GET", base + path, headers=host, status=409)
