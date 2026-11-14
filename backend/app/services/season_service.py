"""Single-process season authority built on the deterministic domain engines."""

from __future__ import annotations

import time
import zlib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from app.core.config import get_settings
from app.domain.bot_coach import advance_with_bots, choose_lineup
from app.domain.catalog import CatalogPlayer
from app.domain.market import InitialMarket, MarketError
from app.domain.match_engine import (
    FULL_TIME_TICK,
    TICKS_PER_HALF,
    MatchEngine,
    PlayerInput,
    TeamInput,
    replay_engine,
)
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
from app.domain.squad import formation_slots
from app.domain.tactics import tactics_from_payload
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
    # Live engines are runtime objects; snapshots keep (inputs, seed, command log).
    engines: dict[str, MatchEngine] = field(default_factory=dict)
    human_clubs: set[str] = field(default_factory=set)


class SeasonService:
    def __init__(self, clock: Callable[[], float] = time.time, play_seconds: int = 180, halftime_seconds: int = 20) -> None:
        self.clock = clock
        self.play_seconds = play_seconds
        self.halftime_seconds = halftime_seconds
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

    # ------------------------------------------------------------------ live round
    def advance(self, room_id: str, market: InitialMarket, human_clubs: set[str]) -> dict[str, object]:
        season = self._season(room_id)
        if season.live_round:
            return self.view(room_id)
        season.human_clubs = set(human_clubs)
        round_number = self.current_round(room_id)
        if round_number > 38:
            return self._advance_playoffs(room_id, market, season)
        if round_number == 20 and season.transfer_window_open:
            raise MarketError("A janela de transferências precisa ser encerrada antes da rodada 20.")
        if not human_clubs.issubset(season.ready_clubs):
            raise MarketError("Aguardando confirmação dos técnicos para esta rodada.")
        fixtures = [fixture for fixture in season.state.fixtures if fixture.round_number == round_number]
        prepared: dict[str, tuple[MatchEngine, dict[str, object]]] = {}
        for fixture in fixtures:
            if fixture.id in season.state.results:
                continue
            home_input = self._team_input(room_id, market, fixture.home)
            away_input = self._team_input(room_id, market, fixture.away)
            seed = zlib.crc32(f"{room_id}:{season.season_number}:{fixture.id}".encode())
            engine = MatchEngine(fixture.id, season.mode, home_input, away_input, seed)
            meta = {"id": fixture.id, "home": fixture.home, "away": fixture.away, "status": "LIVE", "seed": seed,
                    "inputs": {"home": team_input_view(home_input), "away": team_input_view(away_input)},
                    "bot_sides": [side for side, club in enumerate((fixture.home, fixture.away)) if club not in human_clubs]}
            prepared[fixture.id] = (engine, meta)
        # Publish all ten engines with one shared server clock. No result enters the
        # official table until the whole round is committed.
        for match_id, (engine, meta) in prepared.items():
            season.engines[match_id] = engine
            season.matches[match_id] = meta
        started_at = self.clock()
        season.live_round = {"round_number": round_number, "started_at": started_at,
                             "ends_at": started_at + self.play_seconds + self.halftime_seconds,
                             "duration_seconds": self.play_seconds + self.halftime_seconds,
                             "play_seconds": self.play_seconds, "halftime_seconds": self.halftime_seconds,
                             "match_ids": list(prepared), "human_clubs": sorted(human_clubs)}
        season.ready_clubs.clear()
        return self.view(room_id)

    def target_tick(self, live: dict[str, object], now: float) -> int:
        """Server clock → game tick. The half-time break is real time with the clock stopped."""
        play, halftime = float(live["play_seconds"]), float(live["halftime_seconds"])
        elapsed = max(0.0, now - float(live["started_at"]))
        half = play / 2
        if elapsed < half:
            tick = elapsed / half * TICKS_PER_HALF
        elif elapsed < half + halftime:
            tick = TICKS_PER_HALF
        else:
            tick = TICKS_PER_HALF + (elapsed - half - halftime) / half * TICKS_PER_HALF
        return max(0, min(FULL_TIME_TICK, int(tick)))

    def clock_view(self, live: dict[str, object], now: float) -> dict[str, object]:
        tick = self.target_tick(live, now)
        half_end = float(live["started_at"]) + float(live["play_seconds"]) / 2
        phase = "FIRST_HALF" if tick < TICKS_PER_HALF else "HALF_TIME" if now < half_end + float(live["halftime_seconds"]) and tick == TICKS_PER_HALF else "SECOND_HALF"
        if tick >= FULL_TIME_TICK:
            phase = "FULL_TIME"
        return {"tick": tick, "minute": round(tick / 60, 2), "phase": phase, "server_now": now,
                "ticks_per_second": FULL_TIME_TICK / float(live["play_seconds"]),
                "halftime_ends_at": half_end + float(live["halftime_seconds"]), "ends_at": live["ends_at"]}

    def sync_live(self, room_id: str, now: float | None = None) -> None:
        """Advance every live engine (and its bot coach) to the server clock."""
        season = self._season(room_id)
        live = season.live_round
        if not live:
            return
        target = self.target_tick(live, self.clock() if now is None else now)
        for match_id in live["match_ids"]:
            engine = season.engines.get(match_id)
            if engine is None:
                continue
            meta = season.matches[match_id]
            advance_with_bots(engine, target, tuple(meta.get("bot_sides", [])), (engine.inputs[0].tactics, engine.inputs[1].tactics))

    def finish_due(self, room_id: str) -> bool:
        season = self._season(room_id)
        live = season.live_round
        if not live or self.clock() < live["ends_at"]:
            return False
        # Synchronous commit under the caller's room lock, with no await points.
        self.sync_live(room_id, float(live["ends_at"]))
        results = {}
        for match_id in live["match_ids"]:
            engine = season.engines.pop(match_id, None)
            if engine is not None:
                season.matches[match_id] = final_record(engine, season.matches[match_id])
            match = season.matches[match_id]
            results[match_id] = MatchResult(match_id, int(match["home_goals"]), int(match["away_goals"]))
        season.state.results.update(results)
        season.transfer_window_open = live["round_number"] == 19
        season.live_round = None
        return True

    def command(self, room_id: str, club: str, payload: dict[str, object]) -> dict[str, object]:
        """Coach command during a live match. Same API the bot coaches use."""
        season = self._season(room_id)
        live = season.live_round
        if not live:
            raise MarketError("Não há partida ao vivo no momento.")
        self.sync_live(room_id)
        match_id = next((key for key in live["match_ids"] if club in (season.matches[key]["home"], season.matches[key]["away"])), None)
        engine = season.engines.get(match_id) if match_id else None
        if engine is None:
            raise MarketError("Seu clube não está em uma partida ao vivo.")
        key = str(payload.get("idempotency_key") or "")
        if not 8 <= len(key) <= 80:
            raise MarketError("Comando sem chave de idempotência válida.")
        command_id = f"{club}:{key}"
        if command_id in engine.applied_commands:
            return {"command": engine.applied_commands[command_id], "match": self._personal_match(room_id, match_id, club)}
        if engine.finished:
            raise MarketError("A partida já terminou.")
        own = [c for c in engine.applied_commands if c.startswith(f"{club}:")]
        if len(own) >= 40:
            raise MarketError("Limite de comandos desta partida atingido.")
        side = 0 if season.matches[match_id]["home"] == club else 1
        kind = payload.get("kind")
        try:
            if kind == "TACTICS":
                tactics = engine.tactics[side].replace(mentality=payload.get("mentality"), pressure=payload.get("pressure"), style=payload.get("style"))
                status = engine.queue_tactics(side, tactics, command_id)
            elif kind == "SUBSTITUTION":
                status = engine.queue_substitution(side, str(payload.get("out_player_id", "")), str(payload.get("in_player_id", "")), command_id)
            else:
                raise MarketError("Tipo de comando inválido.")
        except ValueError as error:
            raise MarketError(str(error)) from error
        return {"command": status, "match": self._personal_match(room_id, match_id, club)}

    def live_view(self, room_id: str, club: str) -> dict[str, object]:
        season = self._season(room_id)
        live = season.live_round
        now = self.clock()
        if live:
            self.sync_live(room_id, now)
        ids = live["match_ids"] if live else [f.id for f in season.state.fixtures
                if f.round_number == min(38, max(1, self.current_round(room_id) - 1))]
        own_id = next((key for key in ids if key in season.matches and
                       club in (season.matches[key]["home"], season.matches[key]["away"])), None)
        scores = []
        for key in ids:
            if key in season.matches:
                match = self._score(season, key)
                scores.append(match)
        return {"server_now": now, "live_round": live, "clock": self.clock_view(live, now) if live else None,
                "match": self._personal_match(room_id, own_id, club) if own_id else None,
                "scores": scores, "table": self.live_table(room_id, now),
                "official_table": standings(tuple(sorted({f.home for f in season.state.fixtures})),
                                            season.state.fixtures, season.state.results),
                "current_round": self.current_round(room_id), "ready_clubs": sorted(season.ready_clubs)}

    def live_frames(self, room_id: str, club: str, since_tick: int) -> dict[str, object]:
        season = self._season(room_id)
        live = season.live_round
        if not live:
            return {"frames": [], "tick": None, "finished": True}
        now = self.clock()
        self.sync_live(room_id, now)
        match_id = next((key for key in live["match_ids"] if club in (season.matches[key]["home"], season.matches[key]["away"])), None)
        engine = season.engines.get(match_id) if match_id else None
        if engine is None:
            return {"frames": [], "tick": None, "finished": True}
        return {"match_id": match_id, "tick": engine.tick, "phase": engine.phase, "server_now": now,
                "score": {"home": engine.score[0], "away": engine.score[1]}, "event_count": len(engine.events),
                "frames": engine.frames_since(max(-1, since_tick))}

    @staticmethod
    def _score(season: RoomSeason, match_id: str) -> dict[str, object]:
        match = season.matches[match_id]
        engine = season.engines.get(match_id)
        home_goals, away_goals = (engine.score if engine else (match["home_goals"], match["away_goals"]))
        return {"id": match_id, "home": match["home"], "away": match["away"], "home_goals": home_goals, "away_goals": away_goals,
                "minute": round(engine.tick / 60) if engine else 90, "status": "LIVE" if engine else "FINISHED"}

    def _personal_match(self, room_id: str, match_id: str, club: str) -> dict[str, object]:
        """The coach's view of his own match: the rival's exact settings stay private."""
        match = self.match(room_id, match_id)
        you = "home" if match["home"] == club else "away" if match["away"] == club else None
        if you and "tactics" in match:
            rival = "away" if you == "home" else "home"
            match = {**match, "tactics": {**match["tactics"], rival: None}}
            match["events"] = [{**event, "tactics": None, "outcome": "CHANGED"} if event.get("kind") == "TACTICS" and event.get("team") == match[rival] else event
                               for event in match["events"]]
        season = self._season(room_id)
        engine = season.engines.get(match_id)
        if engine and you:
            match["commands"] = [status for command_id, status in engine.applied_commands.items() if command_id.startswith(f"{club}:")]
        return {**match, "you": you}

    def live_table(self, room_id: str, now: float | None = None) -> list[dict[str, object]]:
        season = self._season(room_id)
        results = dict(season.state.results)
        if season.live_round:
            for match_id in season.live_round["match_ids"]:
                score = self._score(season, match_id)
                results[match_id] = MatchResult(match_id, int(score["home_goals"]), int(score["away_goals"]))
        clubs = tuple(sorted({club for f in season.state.fixtures for club in (f.home, f.away)}))
        return standings(clubs, season.state.fixtures, results)

    def match(self, room_id: str, match_id: str, now: float | None = None) -> dict[str, object]:
        season = self._season(room_id)
        match = season.matches.get(match_id)
        if match is None:
            raise MarketError("Partida não encontrada ou ainda não simulada.")
        engine = season.engines.get(match_id)
        if engine is None:
            return {**match, "pressure": project_events(match["home"], match["away"], match["events"])["pressure"], "status": "FINISHED", "minute": 90}
        live = season.live_round
        summary = engine.summary()
        # Only the released past exists: the engine has not simulated the future yet.
        return summary | {"status": "LIVE", "pressure": project_events(match["home"], match["away"], summary["events"])["pressure"],
                          "started_at": live["started_at"], "ends_at": live["ends_at"],
                          "clock": self.clock_view(live, self.clock() if now is None else now),
                          "home_players": [p["id"] for p in summary["lineups"]["home"] if p["on_pitch"]],
                          "away_players": [p["id"] for p in summary["lineups"]["away"] if p["on_pitch"]]}

    def replay_frames(self, room_id: str, match_id: str, start: int, end: int) -> dict[str, object]:
        season = self._season(room_id)
        match = season.matches.get(match_id)
        if match is None or match_id in season.engines or "inputs" not in match:
            raise MarketError("Replay 2D indisponível para esta partida.")
        start, end = max(0, int(start)), min(FULL_TIME_TICK, int(end))
        if end <= start or end - start > 900:
            raise MarketError("Janela de replay inválida (máximo de 15 minutos de jogo).")
        engine = replay_engine(match_id, season.mode, team_input_from_view(match["inputs"]["home"]),
                               team_input_from_view(match["inputs"]["away"]), int(match["seed"]),
                               list(match.get("command_log", [])), end)
        return {"match_id": match_id, "start": start, "end": end,
                "frames": [frame for frame in engine.frames_since(start - 1, limit=1200) if frame["t"] <= end]}

    def preview(self, room_id: str, market: InitialMarket, club: str) -> dict[str, object]:
        """Pre-match comparison of the next fixture from the server's own lineup logic."""
        season = self._season(room_id)
        round_number = self.current_round(room_id)
        fixture = next((f for f in season.state.fixtures if f.round_number == round_number and club in (f.home, f.away)), None)
        if fixture is None:
            return {"fixture": None}
        sides = {}
        for side, code in (("home", fixture.home), ("away", fixture.away)):
            team = self._team_input(room_id, market, code)
            starters = [{"id": p.id, "name": p.name, "position": p.position, "slot_position": p.slot_position,
                         "overall": p.overall, "improvised": p.slot_position != p.position, "number": p.number}
                        for p in team.starters]
            sectors: dict[str, list[int]] = {}
            for player in team.starters:
                rating = player.overall - (0 if player.slot_position == player.position else 12 if "GK" in (player.slot_position, player.position) else 6)
                sectors.setdefault(player.slot_position, []).append(rating)
            sides[side] = {"club_code": code, "formation_code": team.formation_code, "starters": starters,
                           "bench_size": len(team.bench), "tactics": team.tactics.view() if code == club else None,
                           "average": round(sum(p.overall for p in team.starters) / max(1, len(team.starters)), 1),
                           "sectors": {key: round(sum(v) / len(v), 1) for key, v in sectors.items()},
                           "ready": code in season.ready_clubs, "human": code in season.human_clubs or None}
        return {"fixture": {"id": fixture.id, "round_number": round_number, "home": fixture.home, "away": fixture.away}, **sides}

    def unready(self, room_id: str, club: str) -> bool:
        season = self._seasons.get(room_id)
        if season and not season.live_round and club in season.ready_clubs:
            season.ready_clubs.discard(club)
            return True
        return False

    def _team_input(self, room_id: str, market: InitialMarket, club_code: str) -> TeamInput:
        season = self._season(room_id)
        overalls = season.current_overalls
        roster = [market.catalog[player_id] for player_id in market.teams[club_code].roster]
        lineup = squad_service.lineup_for(room_id, club_code)
        if lineup and set(lineup["assignments"].values()).issubset({p.id for p in roster}):
            code, assignments = str(lineup["formation_code"]), dict(lineup["assignments"])
        else:
            code, assignments = choose_lineup(market.mode, roster, overalls)
        slots = formation_slots(market.mode, code)

        def player_input(player: CatalogPlayer, slot_position: str, slot_x: float, slot_y: float, number: int) -> PlayerInput:
            current = overalls.get(player.id, player.overall)
            # Career progression moves every component with the overall.
            attributes = {key: max(1, min(99, value + current - player.overall)) for key, value in player.attributes.items()}
            natural = slot_position if slot_position in (player.position, *player.secondary_positions) else player.position
            return PlayerInput(player.id, player.name, natural, slot_position, slot_x, slot_y, current, attributes, number)

        starters = tuple(player_input(market.catalog[assignments[slot.id]], slot.position, slot.x, slot.y, index + 1)
                         for index, slot in enumerate(slots))
        used = {p.id for p in starters}
        order = {"GK": 0, "DF": 1, "MF": 2, "ST": 3}
        bench_players = sorted((p for p in roster if p.id not in used), key=lambda p: (order.get(p.position, 9), -overalls.get(p.id, p.overall)))
        bench = tuple(player_input(p, p.position, 50, 50, len(starters) + index + 1) for index, p in enumerate(bench_players[:7]))
        return TeamInput(club_code, code, starters, bench, squad_service.tactics_for(room_id, club_code))

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
            played = match.get("minutes")
            if isinstance(played, dict):
                for player_id, value in played.items():
                    minutes[player_id] = minutes.get(player_id, 0) + int(value)
                continue
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
        season = self._season(room_id)
        match_id = f"{stage.lower()}-{number}"
        home_input, away_input = self._team_input(room_id, market, home_code), self._team_input(room_id, market, away_code)
        seed = zlib.crc32(f"{room_id}:{season.season_number}:{match_id}".encode())
        engine = MatchEngine(match_id, market.mode, home_input, away_input, seed)
        bot_sides = tuple(side for side, club in enumerate((home_code, away_code)) if club not in season.human_clubs)
        advance_with_bots(engine, FULL_TIME_TICK, bot_sides, (home_input.tactics, away_input.tactics))
        meta = {"id": match_id, "stage": stage, "home": home_code, "away": away_code, "seed": seed,
                "inputs": {"home": team_input_view(home_input), "away": team_input_view(away_input)}, "bot_sides": list(bot_sides)}
        record = final_record(engine, meta)
        home_penalties = away_penalties = None
        penalty_kicks: tuple[dict[str, object], ...] = ()
        winner = home_code if record["home_goals"] > record["away_goals"] else away_code
        if record["home_goals"] == record["away_goals"]:
            # Takers are the players on the pitch at the final whistle.
            home_ratings = tuple(p["overall"] for p in record["lineups"]["home"] if p["on_pitch"])
            away_ratings = tuple(p["overall"] for p in record["lineups"]["away"] if p["on_pitch"])
            winner, home_penalties, away_penalties, penalty_kicks = resolve_penalties(home_code, away_code, home_ratings, away_ratings, seed ^ 0x5A17)
        events = list(record["events"])
        for index, kick in enumerate(penalty_kicks, 1):
            events.append({"event_id": f"{match_id}:PK:{index:02d}", "match_id": match_id, "kind": "PENALTY", "team": kick["team"], "tick": FULL_TIME_TICK, "minute": 120, "x": .5, "y": .5, "outcome": "SCORED" if kick["scored"] else "MISSED", "player_id": None, "player_name": None, "xg": 0.0})
        season.matches[match_id] = {**record, "events": events, "home_penalties": home_penalties, "away_penalties": away_penalties, "winner": winner}
        return KnockoutMatch(match_id, stage, home_code, away_code, int(record["home_goals"]), int(record["away_goals"]), winner, home_penalties, away_penalties, penalty_kicks)

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
        return {"live_round": season.live_round, "server_now": self.clock(), "live_table": self.live_table(room_id), "season_number": season.season_number, "current_round": current, "regular_season_complete": current > 38, "season_complete": bool(season.playoffs and season.playoffs.champion), "progression_applied": season.progression_applied, "champion": season.playoffs.champion if season.playoffs else None, "playoffs": season.playoffs.view() if season.playoffs else None, "transfer_window_open": season.transfer_window_open, "ready_clubs": sorted(season.ready_clubs), "table": standings(clubs, season.state.fixtures, season.state.results), "fixtures": [{"id": fixture.id, "round_number": fixture.round_number, "home": fixture.home, "away": fixture.away, "result": self._result_view(season.state.results.get(fixture.id)), "match_id": fixture.id if fixture.id in season.matches else None} for fixture in season.state.fixtures if fixture.round_number == min(current, 38)], "matches": [{"id": match_id, "round_number": next((f.round_number for f in season.state.fixtures if f.id == match_id), 39), "home": match["home"], "away": match["away"], "home_goals": projected["home_goals"], "away_goals": projected["away_goals"]} for match_id, match in season.matches.items() for projected in [self._score(season, match_id)]], "match_count": len(season.matches), "season_history": season.season_history, "development_records": season.development_records, "top_scorers": self._top_scorers(season)}

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

    def export_room(self, room_id: str) -> dict[str, object]:
        season = self._season(room_id)
        matches = {key: ({**match, "command_log": list(season.engines[key].command_log)} if key in season.engines else match)
                   for key, match in season.matches.items()}
        return {
            "live_round": season.live_round,
            "human_clubs": sorted(season.human_clubs),
            "mode": season.mode,
            "fixtures": [asdict(fixture) for fixture in season.state.fixtures],
            "results": {key: asdict(value) for key, value in season.state.results.items()},
            "matches": matches,
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
        live_payload = payload.get("live_round")
        live_ids = set(live_payload.get("match_ids", [])) if isinstance(live_payload, dict) else set()
        for match_id, match in matches_payload.items():
            if match_id in live_ids and match.get("status") == "LIVE":
                if not isinstance(match.get("inputs"), dict) or not isinstance(match.get("command_log", []), list):
                    raise ValueError("Snapshot de partida ao vivo sem entradas do motor.")
                continue
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
                    or abs(float(live.get("ends_at", 0)) - float(live.get("started_at", 0)) - float(live.get("duration_seconds", -1))) > 1e-6
                    or float(live.get("play_seconds", 0)) + float(live.get("halftime_seconds", -1)) != float(live.get("duration_seconds", 0))
                    or float(live.get("play_seconds", 0)) < 30):
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
            human_clubs=set(map(str, payload.get("human_clubs", []))),
        )
        if room_season.live_round:
            # Rebuild every live engine deterministically from inputs, seed and the command
            # log, then let the normal sync catch up with the original server clock.
            for match_id in room_season.live_round["match_ids"]:
                meta = matches_payload[match_id]
                log = list(meta.pop("command_log", []))
                home, away = team_input_from_view(meta["inputs"]["home"]), team_input_from_view(meta["inputs"]["away"])
                until = max((int(c["tick"]) for c in log), default=0)
                room_season.engines[match_id] = replay_engine(match_id, room_season.mode, home, away, int(meta["seed"]), log, until)
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

    def _season(self, room_id: str) -> RoomSeason:
        if room_id not in self._seasons:
            raise MarketError("Temporada ainda não foi criada para esta sala.")
        return self._seasons[room_id]


def team_input_view(team: TeamInput) -> dict[str, object]:
    return {"club_code": team.club_code, "formation_code": team.formation_code, "tactics": team.tactics.view(),
            "starters": [asdict(p) for p in team.starters], "bench": [asdict(p) for p in team.bench]}


def team_input_from_view(raw: dict[str, object]) -> TeamInput:
    def player(row: dict[str, object]) -> PlayerInput:
        return PlayerInput(str(row["id"]), str(row["name"]), str(row["position"]), str(row["slot_position"]),
                           float(row["slot_x"]), float(row["slot_y"]), int(row["overall"]),
                           {str(k): int(v) for k, v in dict(row.get("attributes", {})).items()}, int(row.get("number", 0)))
    return TeamInput(str(raw["club_code"]), str(raw["formation_code"]), tuple(player(r) for r in raw["starters"]),
                     tuple(player(r) for r in raw["bench"]), tactics_from_payload(raw["tactics"]))


def final_record(engine: MatchEngine, meta: dict[str, object]) -> dict[str, object]:
    """Official, immutable match record (with what is needed to regenerate the 2D replay)."""
    summary = engine.summary()
    statistics = summary["statistics"]
    for stats in statistics.values():
        stats["cards"] = stats["yellow_cards"] + stats["red_cards"]
    minutes: dict[str, int] = {}
    for side in ("home", "away"):
        for player in summary["lineups"][side]:
            if player["entered_tick"] is not None:
                left = player["left_tick"] if player["left_tick"] is not None else FULL_TIME_TICK
                minutes[player["id"]] = max(1, round((left - player["entered_tick"]) / 60))
    best = max((p for side in ("home", "away") for p in summary["lineups"][side] if p["entered_tick"] is not None),
               key=lambda p: p["rating"], default=None)
    return {**{k: v for k, v in meta.items() if k not in ("status",)}, **summary, "status": "FINISHED",
            "command_log": list(engine.command_log), "minutes": minutes,
            "player_of_the_match": {"id": best["id"], "name": best["name"], "rating": best["rating"]} if best else None,
            "home_players": [p["id"] for p in summary["lineups"]["home"] if p["entered_tick"] is not None],
            "away_players": [p["id"] for p in summary["lineups"]["away"] if p["entered_tick"] is not None],
            "home_formation": {"code": summary["formations"]["home"]}, "away_formation": {"code": summary["formations"]["away"]}}


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


_settings = get_settings()
season_service = SeasonService(play_seconds=_settings.live_match_seconds, halftime_seconds=_settings.live_halftime_seconds)
