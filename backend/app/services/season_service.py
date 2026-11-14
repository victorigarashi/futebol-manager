"""Single-process season authority built on the deterministic domain engines."""

from __future__ import annotations

import time
import zlib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from app.domain.market import InitialMarket, MarketError
from app.domain.playoffs import (
    KnockoutMatch,
    PlayoffState,
    create_bracket,
    quarterfinal_pairings,
    resolve_penalties,
    semifinal_pairings,
)
from app.domain.progression import progress_player
from app.domain.season import Fixture, MatchResult, SeasonState, generate_calendar, standings
from app.domain.simulation import TeamStrength, simulate
from app.domain.squad import formation_slots, simulation_overall
from app.services.squad_service import squad_service


@dataclass
class RoomSeason:
    state: SeasonState
    mode: str
    ready_clubs: set[str] = field(default_factory=set)
    matches: dict[str, dict[str, object]] = field(default_factory=dict)
    playoffs: PlayoffState | None = None
    transfer_window_open: bool = False
    season_number: int = 1
    current_overalls: dict[str, int] = field(default_factory=dict)
    development_records: list[dict[str, object]] = field(default_factory=list)
    season_history: list[dict[str, object]] = field(default_factory=list)
    progression_applied: bool = False
    live_round: dict[str, object] | None = None


class SeasonService:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self._seasons: dict[str, RoomSeason] = {}

    def create(self, room_id: str, market: InitialMarket) -> RoomSeason:
        if room_id not in self._seasons:
            self._seasons[room_id] = RoomSeason(SeasonState(generate_calendar(tuple(market.teams))), market.mode, current_overalls={player_id: player.overall for player_id, player in market.catalog.items()})
        return self._seasons[room_id]

    def create_next_season(self, room_id: str, market: InitialMarket) -> dict[str, object]:
        previous = self._season(room_id)
        if not previous.playoffs or not previous.playoffs.champion or not previous.progression_applied:
            raise MarketError("A temporada atual precisa terminar antes de começar outra.")
        summary = {"season_number": previous.season_number, "champion": previous.playoffs.champion, "table": standings(tuple(market.teams), previous.state.fixtures, previous.state.results), "playoffs": previous.playoffs.view(), "top_scorers": self._top_scorers(previous)}
        history = [*previous.season_history, summary]
        self._seasons[room_id] = RoomSeason(SeasonState(generate_calendar(tuple(market.teams))), market.mode, season_number=previous.season_number + 1, current_overalls=dict(previous.current_overalls), development_records=list(previous.development_records), season_history=history)
        return self.view(room_id)

    def ready(self, room_id: str, club_code: str) -> dict[str, object]:
        season = self._season(room_id)
        if season.live_round:
            return self.view(room_id)
        if self.current_round(room_id) > 38:
            raise MarketError("A temporada regular já terminou.")
        season.ready_clubs.add(club_code)
        return self.view(room_id)

    def advance(self, room_id: str, market: InitialMarket, human_clubs: set[str]) -> dict[str, object]:
        season = self._season(room_id)
        if season.live_round:
            return self.view(room_id)
        round_number = self.current_round(room_id)
        if round_number > 38:
            return self._advance_playoffs(room_id, market, season)
        if round_number == 20 and season.transfer_window_open:
            raise MarketError("A janela de transferências precisa ser encerrada antes da rodada 20.")
        if not human_clubs.issubset(season.ready_clubs):
            raise MarketError("Aguardando confirmação dos técnicos para esta rodada.")
        fixtures = [fixture for fixture in season.state.fixtures if fixture.round_number == round_number]
        generated = {}
        for fixture in fixtures:
            if fixture.id in season.state.results:
                continue
            home, away = self._team_strength(room_id, market, fixture.home), self._team_strength(room_id, market, fixture.away)
            home_players = self._starting_players(room_id, market, fixture.home)
            away_players = self._starting_players(room_id, market, fixture.away)
            seed = zlib.crc32(f"{room_id}:{season.season_number}:{fixture.id}".encode())
            simulated = simulate(home, away, season.mode, seed, home_players, away_players, fixture.id)
            generated[fixture.id] = {
                "id": fixture.id,
                "home": fixture.home,
                "away": fixture.away,
                "home_formation": self._formation(room_id, market, fixture.home, home_players),
                "away_formation": self._formation(room_id, market, fixture.away, away_players),
                "home_players": list(home_players),
                "away_players": list(away_players),
                "home_goals": simulated.home_goals,
                "away_goals": simulated.away_goals,
                "home_xg": simulated.home_xg,
                "away_xg": simulated.away_xg,
                "probabilities": {"home": simulated.home_win_probability, "draw": simulated.draw_probability, "away": simulated.away_win_probability},
                "statistics": simulated.statistics,
                "events": self._event_views(simulated.events, market),
            }
        # Publish all ten prepared streams with one shared server deadline. No result
        # enters the official table until the entire round is committed.
        season.matches.update(generated)
        started_at = self.clock()
        season.live_round = {"round_number": round_number, "started_at": started_at,
                             "ends_at": started_at + 60, "duration_seconds": 60,
                             "match_ids": list(generated)}
        season.ready_clubs.clear()
        return self.view(room_id)

    def close_transfer_window(self, room_id: str) -> dict[str, object]:
        season = self._season(room_id)
        if self.current_round(room_id) != 20:
            if not season.transfer_window_open:
                return self.view(room_id)
            raise MarketError("A janela só pode ser encerrada entre as rodadas 19 e 20.")
        season.transfer_window_open = False
        season.ready_clubs.clear()
        return self.view(room_id)

    def _advance_playoffs(self, room_id: str, market: InitialMarket, season: RoomSeason) -> dict[str, object]:
        if season.playoffs is None:
            season.playoffs = create_bracket(standings(tuple(market.teams), season.state.fixtures, season.state.results))
            for club in season.playoffs.qualifiers:
                self._pay_award(market, club, f"season-{season.season_number}:quarterfinals", 1_000_000_000, "Classificação às quartas")
            pairings = quarterfinal_pairings(season.playoffs)
            season.playoffs.quarterfinals = [self._play_knockout(room_id, market, "QF", index, home, away) for index, (home, away) in enumerate(pairings, 1)]
            season.playoffs.next_stage = "SEMIFINALS"
        elif season.playoffs.next_stage == "SEMIFINALS":
            pairings = semifinal_pairings(season.playoffs)
            season.playoffs.semifinals = [self._play_knockout(room_id, market, "SF", index, home, away) for index, (home, away) in enumerate(pairings, 1)]
            for match in season.playoffs.semifinals:
                self._pay_award(market, match.winner, f"season-{season.season_number}:semifinals", 2_000_000_000, "Classificação às semifinais")
            season.playoffs.next_stage = "FINAL"
        elif season.playoffs.next_stage == "FINAL":
            first, second = (season.playoffs.semifinals[0].winner, season.playoffs.semifinals[1].winner)
            season.playoffs.final = self._play_knockout(room_id, market, "FINAL", 1, first, second)
            season.playoffs.champion = season.playoffs.final.winner
            self._pay_award(market, season.playoffs.champion, f"season-{season.season_number}:champion", 5_000_000_000, "Título brasileiro")
            self._apply_progression(room_id, market, season)
            season.playoffs.next_stage = "COMPLETE"
        return self.view(room_id)

    @staticmethod
    def _apply_progression(room_id: str, market: InitialMarket, season: RoomSeason) -> None:
        if season.progression_applied:
            return
        minutes: dict[str, int] = {}
        goals: dict[str, int] = {}
        for match in season.matches.values():
            for player_id in [*match.get("home_players", []), *match.get("away_players", [])]:
                minutes[player_id] = minutes.get(player_id, 0) + 90
            for event in match.get("events", []):
                player_id = event.get("player_id")
                if event.get("kind") == "GOAL" and player_id:
                    goals[player_id] = goals.get(player_id, 0) + 1
        updated: dict[str, int] = {}
        records: list[dict[str, object]] = []
        for player_id, player in market.catalog.items():
            record = progress_player(
                player_id=player_id, season_number=season.season_number,
                age=(player.age + season.season_number - 1) if player.age is not None else None,
                overall=season.current_overalls.get(player_id, player.overall),
                potential=player.potential,
                original_market_value_cents=player.market_value_cents,
                minutes_played=minutes.get(player_id, 0), goals=goals.get(player_id, 0),
                seed=zlib.crc32(f"{room_id}:{season.season_number}:{player_id}".encode()),
            )
            updated[player_id] = record.overall_after
            records.append(record.view())
        season.current_overalls = updated
        season.development_records.extend(records)
        season.progression_applied = True

    def _play_knockout(self, room_id: str, market: InitialMarket, stage: str, number: int, home_code: str, away_code: str) -> KnockoutMatch:
        match_id = f"{stage.lower()}-{number}"
        home = self._team_strength(room_id, market, home_code)
        away = self._team_strength(room_id, market, away_code)
        home_players = self._starting_players(room_id, market, home_code)
        away_players = self._starting_players(room_id, market, away_code)
        seed = zlib.crc32(f"{room_id}:{match_id}".encode())
        simulated = simulate(home, away, market.mode, seed, home_players, away_players, match_id)
        home_penalties = away_penalties = None
        penalty_kicks: tuple[dict[str, object], ...] = ()
        winner = home_code if simulated.home_goals > simulated.away_goals else away_code
        if simulated.home_goals == simulated.away_goals:
            home_ratings = tuple(market.catalog[player].overall for player in home_players)
            away_ratings = tuple(market.catalog[player].overall for player in away_players)
            winner, home_penalties, away_penalties, penalty_kicks = resolve_penalties(home_code, away_code, home_ratings, away_ratings, seed ^ 0x5A17)
        match = KnockoutMatch(match_id, stage, home_code, away_code, simulated.home_goals, simulated.away_goals, winner, home_penalties, away_penalties, penalty_kicks)
        events = self._event_views(simulated.events, market)
        for index, kick in enumerate(penalty_kicks, 1):
            events.append({"event_id": f"{match_id}:PK:{index:02d}", "match_id": match_id, "kind": "PENALTY", "team": kick["team"], "minute": 120, "animation_ms": 120_000 + index * 1000, "x": .5, "y": .5, "outcome": "SCORED" if kick["scored"] else "MISSED", "player_id": None, "participant_ids": [], "xg": 0.0})
        self._seasons[room_id].matches[match_id] = {
            "id": match_id, "stage": stage, "home": home_code, "away": away_code,
            "home_players": list(home_players), "away_players": list(away_players),
            "home_goals": simulated.home_goals, "away_goals": simulated.away_goals,
            "home_xg": simulated.home_xg, "away_xg": simulated.away_xg,
            "probabilities": {"home": simulated.home_win_probability, "draw": simulated.draw_probability, "away": simulated.away_win_probability},
            "statistics": simulated.statistics, "events": events,
            "home_penalties": home_penalties, "away_penalties": away_penalties, "winner": winner,
        }
        return match

    @staticmethod
    def _pay_award(market: InitialMarket, club: str, award_id: str, amount_cents: int, description: str) -> None:
        team = market.teams[club]
        operation_id = f"season-award:{award_id}:{club}"
        if operation_id in team.paid_operation_ids:
            return
        team.budget_cents += amount_cents
        team.paid_operation_ids.add(operation_id)
        team.financial_ledger.append({"operation_id": operation_id, "type": "AWARD", "amount_cents": amount_cents, "description": description})

    def view(self, room_id: str) -> dict[str, object]:
        season = self._season(room_id)
        clubs = tuple(sorted({club for fixture in season.state.fixtures for club in (fixture.home, fixture.away)}))
        current = self.current_round(room_id)
        return {"live_round": season.live_round, "server_now": self.clock(), "live_table": self.live_table(room_id), "season_number": season.season_number, "current_round": current, "regular_season_complete": current > 38, "season_complete": bool(season.playoffs and season.playoffs.champion), "progression_applied": season.progression_applied, "champion": season.playoffs.champion if season.playoffs else None, "playoffs": season.playoffs.view() if season.playoffs else None, "transfer_window_open": season.transfer_window_open, "ready_clubs": sorted(season.ready_clubs), "table": standings(clubs, season.state.fixtures, season.state.results), "fixtures": [{"id": fixture.id, "round_number": fixture.round_number, "home": fixture.home, "away": fixture.away, "result": self._result_view(season.state.results.get(fixture.id)), "match_id": fixture.id if fixture.id in season.matches else None} for fixture in season.state.fixtures if fixture.round_number == min(current, 38)], "matches": [{"id": match_id, "round_number": next((f.round_number for f in season.state.fixtures if f.id == match_id), 39), "home": match["home"], "away": match["away"], "home_goals": projected["home_goals"], "away_goals": projected["away_goals"]} for match_id, match in season.matches.items() for projected in [self.match(room_id, match_id) if season.live_round and match_id in season.live_round["match_ids"] else match]], "match_count": len(season.matches), "season_history": season.season_history, "development_records": season.development_records, "top_scorers": self._top_scorers(season)}

    @staticmethod
    def _top_scorers(season: RoomSeason) -> list[dict[str, object]]:
        goals: dict[tuple[str, str], int] = {}
        for fixture_id, match in season.matches.items():
            if season.live_round and fixture_id in season.live_round["match_ids"]:
                continue
            if fixture_id not in {fixture.id for fixture in season.state.fixtures}:
                continue
            for event in match.get("events", []):
                player_id = event.get("player_id")
                if event.get("kind") == "GOAL" and player_id:
                    key = (str(player_id), str(event.get("team", "")))
                    goals[key] = goals.get(key, 0) + 1
        names = {str(event.get("player_id")): str(event.get("player_name")) for match in season.matches.values() for event in match.get("events", []) if event.get("player_id") and event.get("player_name")}
        ordered = sorted(goals.items(), key=lambda item: (-item[1], item[0][0]))[:10]
        return [{"player_id": player_id, "player_name": names.get(player_id, player_id), "club_code": club, "goals": count} for (player_id, club), count in ordered]

    @staticmethod
    def _event_views(events: tuple[object, ...], market: InitialMarket) -> list[dict[str, object]]:
        views = [asdict(event) for event in events]
        for event in views:
            player_id = event.get("player_id")
            if player_id in market.catalog:
                event["player_name"] = market.catalog[player_id].name
        return views

    def finish_due(self, room_id: str) -> bool:
        season = self._season(room_id)
        live = season.live_round
        if not live or self.clock() < live["ends_at"]:
            return False
        # Synchronous commit under the caller's room lock, with no await points.
        results = {key: MatchResult(key, season.matches[key]["home_goals"],
                                  season.matches[key]["away_goals"])
                   for key in live["match_ids"]}
        season.state.results.update(results)
        season.transfer_window_open = live["round_number"] == 19
        season.live_round = None
        return True

    def live_table(self, room_id: str, now: float | None = None) -> list[dict[str, object]]:
        season = self._season(room_id)
        results = dict(season.state.results)
        now = self.clock() if now is None else now
        if season.live_round:
            for match_id in season.live_round["match_ids"]:
                match = self.match(room_id, match_id, now)
                results[match_id] = MatchResult(match_id, match["home_goals"], match["away_goals"])
        clubs = tuple(sorted({club for f in season.state.fixtures for club in (f.home, f.away)}))
        return standings(clubs, season.state.fixtures, results)

    def live_view(self, room_id: str, club: str) -> dict[str, object]:
        season = self._season(room_id)
        live = season.live_round
        now = self.clock()
        ids = live["match_ids"] if live else [f.id for f in season.state.fixtures
                if f.round_number == min(38, max(1, self.current_round(room_id) - 1))]
        own_id = next((key for key in ids if key in season.matches and
                       club in (season.matches[key]["home"], season.matches[key]["away"])), None)
        scores = []
        for key in ids:
            if key in season.matches:
                match = self.match(room_id, key, now)
                scores.append({k: match[k] for k in ("id", "home", "away", "home_goals", "away_goals")})
        return {"server_now": now, "live_round": live,
                "match": self.match(room_id, own_id, now) if own_id else None,
                "scores": scores, "table": self.live_table(room_id, now),
                "official_table": standings(tuple(sorted({f.home for f in season.state.fixtures})),
                                            season.state.fixtures, season.state.results),
                "current_round": self.current_round(room_id), "ready_clubs": sorted(season.ready_clubs)}

    def match(self, room_id: str, match_id: str, now: float | None = None) -> dict[str, object]:
        season = self._season(room_id)
        match = season.matches.get(match_id)
        if match is None:
            raise MarketError("Partida não encontrada ou ainda não simulada.")
        live = season.live_round
        if not live or match_id not in live["match_ids"]:
            return {**match, "pressure": project_events(match["home"], match["away"], match["events"])["pressure"], "status": "FINISHED", "minute": 90}
        elapsed = max(0, min(60, (self.clock() if now is None else now) - live["started_at"]))
        events = [e for e in match["events"] if e["animation_ms"] <= elapsed * 1500]
        projection = project_events(match["home"], match["away"], events)
        # Never return final probabilities, score, stats or future events during play.
        return {key: match[key] for key in ("id", "home", "away", "home_players",
                "away_players", "home_formation", "away_formation")} | projection | {
                "events": events, "minute": min(90, elapsed * 1.5), "status": "LIVE",
                "started_at": live["started_at"], "ends_at": live["ends_at"]}

    @staticmethod
    def _formation(room_id: str, market: InitialMarket, club: str,
                   players: tuple[str, ...]) -> dict[str, object]:
        lineup = squad_service.lineup_for(room_id, club)
        code = lineup["formation_code"] if lineup else ("2-1-1" if market.mode == "FIVE_A_SIDE" else "4-3-3")
        slots = formation_slots(market.mode, code)
        assignments = lineup["assignments"] if lineup else dict(zip((s.id for s in slots), players, strict=True))
        return {"code": code, "players": [{"id": assignments[slot.id],
                "name": market.catalog[assignments[slot.id]].name,
                "x": round((100 - slot.y) / 100, 3), "y": slot.x / 100,
                "number": index + 1} for index, slot in enumerate(slots)]}

    def export_room(self, room_id: str) -> dict[str, object]:
        season = self._season(room_id)
        return {
            "live_round": season.live_round,
            "mode": season.mode,
            "fixtures": [asdict(fixture) for fixture in season.state.fixtures],
            "results": {key: asdict(value) for key, value in season.state.results.items()},
            "matches": season.matches,
            "ready_clubs": sorted(season.ready_clubs),
            "playoffs": season.playoffs.view() if season.playoffs else None,
            "transfer_window_open": season.transfer_window_open,
            "season_number": season.season_number,
            "current_overalls": season.current_overalls,
            "development_records": season.development_records,
            "season_history": season.season_history,
            "progression_applied": season.progression_applied,
        }

    def restore_room(self, room_id: str, payload: dict[str, object]) -> RoomSeason:
        fixtures_payload = payload.get("fixtures")
        if not isinstance(fixtures_payload, list):
            raise ValueError("Snapshot da temporada sem calendário completo.")
        fixtures = [Fixture(str(row["id"]), int(row["round_number"]), str(row["home"]), str(row["away"])) for row in fixtures_payload]
        if len(fixtures) != 380 or len({fixture.id for fixture in fixtures}) != 380:
            raise ValueError("Calendário do snapshot está incompleto ou duplicado.")
        clubs = {club for fixture in fixtures for club in (fixture.home, fixture.away)}
        if (len(clubs) != 20 or {f.round_number for f in fixtures} != set(range(1, 39))
                or len({(f.home, f.away) for f in fixtures}) != 380
                or any(f.home == f.away for f in fixtures)
                or any(sum(f.round_number == number and club in (f.home, f.away) for f in fixtures) != 1
                       for number in range(1, 39) for club in clubs)):
            raise ValueError("Calendário do snapshot viola as rodadas do Brasileirão.")
        state = SeasonState(fixtures)
        results_payload = payload.get("results", {})
        matches_payload = payload.get("matches", {})
        if not isinstance(results_payload, dict) or not isinstance(matches_payload, dict):
            raise ValueError("Snapshot contém resultados inválidos.")
        for fixture_id, raw in results_payload.items():
            result = MatchResult(str(raw["fixture_id"]), int(raw["home_goals"]), int(raw["away_goals"]))
            if result.home_goals < 0 or result.away_goals < 0:
                raise ValueError("Snapshot contém placar negativo.")
            if str(fixture_id) != result.fixture_id:
                raise ValueError("Resultado associado à partida incorreta.")
            state.record(result)
        if not set(state.results).issubset(matches_payload):
            raise ValueError("Snapshot omite partidas da temporada com resultado registrado.")
        for fixture_id, result in state.results.items():
            match = matches_payload[fixture_id]
            if int(match["home_goals"]) != result.home_goals or int(match["away_goals"]) != result.away_goals:
                raise ValueError("Snapshot possui placar divergente entre calendário e replay.")
        for match_id, match in matches_payload.items():
            events = match.get("events")
            if not isinstance(events, list) or int(match["home_goals"]) < 0 or int(match["away_goals"]) < 0:
                raise ValueError("Snapshot de replay possui placar ou eventos inválidos.")
            event_ids: set[str] = set()
            goals: dict[str, int] = {str(match["home"]): 0, str(match["away"]): 0}
            for event in events:
                event_id = str(event.get("event_id", ""))
                x, y = float(event.get("x", -1)), float(event.get("y", -1))
                if not event_id or event_id in event_ids or str(event.get("match_id")) != str(match_id) or not (0 <= x <= 1 and 0 <= y <= 1):
                    raise ValueError("Snapshot de replay contém evento duplicado, órfão ou fora do campo.")
                event_ids.add(event_id)
                if event.get("kind") == "GOAL":
                    team = str(event.get("team"))
                    if team not in goals:
                        raise ValueError("Gol do snapshot referencia equipe que não disputa a partida.")
                    goals[team] += 1
            if goals[str(match["home"])] != int(match["home_goals"]) or goals[str(match["away"])] != int(match["away_goals"]):
                raise ValueError("Eventos de gol do snapshot não reconciliam com o placar.")
        live = payload.get("live_round")
        if live is not None:
            if not isinstance(live, dict):
                raise ValueError("Snapshot de transmissão inválido.")
            round_number = int(live.get("round_number", 0))
            ids = live.get("match_ids", [])
            expected = {f.id for f in fixtures if f.round_number == round_number}
            if (not isinstance(ids, list) or len(ids) != 10 or set(ids) != expected
                    or not set(ids).issubset(matches_payload) or set(ids) & set(state.results)
                    or float(live.get("ends_at", 0)) - float(live.get("started_at", 0)) != 60
                    or int(live.get("duration_seconds", 0)) != 60):
                raise ValueError("Snapshot de transmissão tem rodada ou prazo inválido.")
            if any(f.id not in state.results for f in fixtures if f.round_number < round_number):
                raise ValueError("Snapshot de transmissão omite resultados anteriores.")
            for fixture in fixtures:
                if fixture.id in expected:
                    match = matches_payload[fixture.id]
                    if (match["home"], match["away"]) != (fixture.home, fixture.away):
                        raise ValueError("Snapshot de transmissão referencia clubes incorretos.")
        playoff_payload = payload.get("playoffs")
        playoffs = self._restore_playoffs(playoff_payload) if isinstance(playoff_payload, dict) else None
        current_overalls = {str(key): int(value) for key, value in payload.get("current_overalls", {}).items()}
        if any(value < 1 or value > 99 for value in current_overalls.values()):
            raise ValueError("Snapshot contém overall de carreira inválido.")
        room_season = RoomSeason(
            live_round=payload.get("live_round"),
            state=state,
            mode=str(payload["mode"]),
            ready_clubs=set(map(str, payload.get("ready_clubs", []))),
            matches=matches_payload,
            playoffs=playoffs,
            transfer_window_open=bool(payload.get("transfer_window_open", False)),
            season_number=int(payload.get("season_number", 1)),
            current_overalls=current_overalls,
            development_records=list(payload.get("development_records", [])),
            season_history=list(payload.get("season_history", [])),
            progression_applied=bool(payload.get("progression_applied", False)),
        )
        self._seasons[room_id] = room_season
        return room_season

    @staticmethod
    def _restore_playoffs(payload: dict[str, object]) -> PlayoffState:
        state = PlayoffState(tuple(map(str, payload["qualifiers"])))
        def decode(raw: dict[str, object]) -> KnockoutMatch:
            return KnockoutMatch(str(raw["id"]), str(raw["stage"]), str(raw["home"]), str(raw["away"]), int(raw["home_goals"]), int(raw["away_goals"]), str(raw["winner"]), raw.get("home_penalties"), raw.get("away_penalties"), tuple(raw.get("penalty_kicks", [])))
        state.quarterfinals = [decode(raw) for raw in payload.get("quarterfinals", [])]
        state.semifinals = [decode(raw) for raw in payload.get("semifinals", [])]
        state.final = decode(payload["final"]) if isinstance(payload.get("final"), dict) else None
        state.champion = payload.get("champion")
        state.next_stage = str(payload.get("next_stage", "QUARTERFINALS"))
        return state

    def current_round(self, room_id: str) -> int:
        season = self._season(room_id)
        for round_number in range(1, 39):
            fixtures = [fixture for fixture in season.state.fixtures if fixture.round_number == round_number]
            if any(fixture.id not in season.state.results for fixture in fixtures):
                return round_number
        return 39

    @staticmethod
    def _result_view(result: MatchResult | None) -> dict[str, int] | None:
        return None if not result else {"home_goals": result.home_goals, "away_goals": result.away_goals}

    def _starting_players(self, room_id: str, market: InitialMarket, club_code: str) -> tuple[str, ...]:
        lineup = squad_service.lineup_for(room_id, club_code)
        if lineup:
            return tuple(str(row["player_id"]) for row in lineup["evaluation"])
        roster = market.teams[club_code].roster
        selected = tuple(player_id for position, count in market.slots.items() for player_id in [item for item in roster if market.catalog[item].position == position][:count])
        if len(selected) != sum(market.slots.values()):
            raise MarketError("Elenco sem atletas suficientes para formar o time titular.")
        return selected

    def _team_strength(self, room_id: str, market: InitialMarket, club_code: str) -> TeamStrength:
        players = [market.catalog[player_id] for player_id in self._starting_players(room_id, market, club_code)]
        lineup = squad_service.lineup_for(room_id, club_code)
        evaluation = (lineup or {}).get("evaluation", [])
        current = self._season(room_id).current_overalls
        ratings_by_position: dict[str, list[int]] = {position: [] for position in ("GK", "DF", "MF", "ST")}
        improvised = 0
        if lineup:
            for row in evaluation:
                player = market.catalog[row["player_id"]]
                target = row["target_position"]
                overall = simulation_overall(player, current.get(player.id, player.overall), target)
                if target not in {player.position, *player.secondary_positions}:
                    overall -= 12 if target == "GK" or player.position == "GK" else 6
                    improvised += 1
                ratings_by_position[target].append(max(1, overall))
        else:
            for player in players:
                ratings_by_position[player.position].append(
                    simulation_overall(player, current.get(player.id, player.overall))
                )
        by_position = ratings_by_position
        def average(values: list[int]) -> float:
            return sum(values) / len(values) if values else 1
        strategy = squad_service.strategy_for(room_id, club_code)
        positional_fit = 1 - .5 * improvised / max(1, len(evaluation))
        return TeamStrength(club_code, average(by_position["ST"]), average(by_position["MF"]), average(by_position["DF"]), average(by_position["GK"]), positional_fit=positional_fit, strategy=strategy, player_ids=tuple(player.id for player in players))

    def _season(self, room_id: str) -> RoomSeason:
        if room_id not in self._seasons:
            raise MarketError("Temporada ainda não foi criada para esta sala.")
        return self._seasons[room_id]


def project_events(home: str, away: str, events: list[dict[str, object]]) -> dict[str, object]:
    """The released event prefix is the only source of live scores and statistics."""
    stats = {club: dict.fromkeys(("shots", "shots_on_target", "possession", "passes",
             "goals", "corners", "saves", "tackles", "fouls", "cards"), 0) for club in (home, away)}
    xg = {home: 0.0, away: 0.0}
    pressure = []
    kinds = {"POSSESSION": "possession", "PASS": "passes", "GOAL": "goals",
             "CORNER": "corners", "SAVE": "saves", "TACKLE": "tackles",
             "FOUL": "fouls", "CARD": "cards"}
    for event in events:
        club, kind = event.get("team"), event["kind"]
        if club not in stats:
            continue
        if kind in kinds:
            stats[club][kinds[kind]] += 1
        if kind == "SHOT":
            stats[club]["shots"] += 1
            stats[club]["shots_on_target"] += event.get("outcome") == "ON_TARGET"
            xg[club] += event.get("xg", 0)
        if kind in {"SHOT", "CARRY", "CORNER", "GOAL"}:
            pressure.append({"minute": event["minute"], "team": club,
                             "value": 3 if kind in {"SHOT", "GOAL"} else 1})
    return {"home_goals": stats[home]["goals"], "away_goals": stats[away]["goals"],
            "home_xg": round(xg[home], 3), "away_xg": round(xg[away], 3),
            "statistics": stats, "pressure": pressure}


season_service = SeasonService()
