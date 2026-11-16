"""Single-process season authority built on the deterministic domain engines."""

from __future__ import annotations

import json
import time
import zlib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from app.core.config import get_settings
from app.domain.bot_coach import advance_with_bots, choose_lineup
from app.domain.broadcast import DEFAULT_DURATION, DURATIONS, Director, LinearClock, clock_from_dict
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

# Cooperative simulation budget. One slice simulates at most this many ticks of one
# match (~5-8 ms of CPU on a desktop core, ~10x more on a 0.1 CPU host), so the event
# loop always gets back control quickly (health check, other requests, sockets).
LEAGUE_SIZES = (4, 6, 8, 10, 12, 16, 20)
FRAME_MEMO_HITS = [0]
# Engine ticks simulated by the cooperative slices (observability).
TICKS_SIMULATED = [0]


def _advance_counted(engine: MatchEngine, target: int, bots: tuple[int, ...], baselines: tuple) -> None:
    before = engine.tick
    advance_with_bots(engine, target, bots, baselines)
    TICKS_SIMULATED[0] += engine.tick - before
SLICE_TICKS = 40
# Watched matches are simulated this far beyond the broadcast cursor in slices, so
# the planner rarely has to simulate inline.
PRESIM_LEAD = 150
# Unwatched matches stay at least this far ahead of their score-ticker clock.
LINEAR_LEAD = 120


@dataclass
class PrebuiltMatch:
    fingerprint: str
    engine: MatchEngine


class ReplayJob:
    """Deterministic rebuild of a live engine from its command log, done in slices.

    Same order of operations as `replay_engine` (advance to each command tick, apply
    it, then advance to the frontier), so the rebuilt engine is identical."""

    def __init__(self, engine: MatchEngine, command_log: list[dict[str, object]], until_tick: int) -> None:
        self.engine = engine
        self.commands = [c for c in sorted(command_log, key=lambda c: int(c["tick"])) if int(c["tick"]) <= until_tick]
        self.index = 0
        self.until = until_tick

    @property
    def done(self) -> bool:
        return self.index >= len(self.commands) and (self.engine.tick >= self.until or self.engine.finished)

    def step(self, budget: int) -> None:
        engine = self.engine
        target = min(self.until, engine.tick + budget)
        while self.index < len(self.commands) and int(self.commands[self.index]["tick"]) <= target:
            command = self.commands[self.index]
            engine.advance_to(int(command["tick"]))
            side = int(command["side"])
            if command["kind"] == "TACTICS":
                engine.queue_tactics(side, tactics_from_payload(command["tactics"]), str(command["command_id"]))
            elif command["kind"] == "SUBSTITUTION":
                try:
                    engine.queue_substitution(side, str(command["out"]), str(command["in"]), str(command["command_id"]))
                except ValueError:
                    pass
            self.index += 1
        engine.advance_to(target)


def _fingerprint(home: TeamInput, away: TeamInput, seed: int, bot_sides: list[int]) -> str:
    return json.dumps([team_input_view(home), team_input_view(away), seed, bot_sides], sort_keys=True, default=str)


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
    # Broadcast timeline of each live match (what is shown when; see app.domain.broadcast).
    directors: dict[str, Director] = field(default_factory=dict)
    human_clubs: set[str] = field(default_factory=set)
    # When the current round became available for preparation (server clock).
    preparation_opened_at: float | None = None
    double_round_robin: bool = True
    # Bot-against-bot matches of the next round simulated ahead, during preparation.
    prebuilt: dict[str, PrebuiltMatch] = field(default_factory=dict)
    # Live engines being rebuilt after a restart (replayed in slices, never in one go).
    recovering: dict[str, ReplayJob] = field(default_factory=dict)


class SeasonService:
    def __init__(self, clock: Callable[[], float] = time.time, intro_seconds: int = 0, match_seconds: int = DEFAULT_DURATION) -> None:
        self.clock = clock
        if match_seconds not in DURATIONS:
            raise ValueError("Duração de partida inválida.")
        # Real duration of a live match when the caller does not say (room setting wins).
        self.match_seconds = match_seconds
        # Match presentation before kick-off: line-ups shown, tactics still editable.
        self.intro_seconds = intro_seconds
        self._seasons: dict[str, RoomSeason] = {}
        # Short-lived memo of visible frame windows (room, match, since, shown) -> rows.
        self._frames_memo: dict[tuple[str, str, int, int], list[dict[str, object]]] = {}

    def create(self, room_id: str, market: InitialMarket, *, double_round_robin: bool = True) -> RoomSeason:
        if room_id not in self._seasons:
            self._seasons[room_id] = RoomSeason(SeasonState(generate_calendar(tuple(market.teams), double_round_robin=double_round_robin)), market.mode, current_overalls={player_id: player.overall for player_id, player in market.catalog.items()},
                                                preparation_opened_at=self.clock(), double_round_robin=double_round_robin)
        return self._seasons[room_id]

    def create_next_season(self, room_id: str, market: InitialMarket) -> dict[str, object]:
        previous = self._season(room_id)
        if not previous.playoffs or not previous.playoffs.champion or not previous.progression_applied:
            raise MarketError("A temporada atual precisa terminar antes de começar outra.")
        summary = {"season_number": previous.season_number, "champion": previous.playoffs.champion, "table": standings(tuple(market.teams), previous.state.fixtures, previous.state.results), "playoffs": previous.playoffs.view(), "top_scorers": self._top_scorers(previous)}
        history = [*previous.season_history, summary]
        self._seasons[room_id] = RoomSeason(SeasonState(generate_calendar(tuple(market.teams), double_round_robin=previous.double_round_robin)), market.mode, season_number=previous.season_number + 1, current_overalls=dict(previous.current_overalls), development_records=list(previous.development_records), season_history=history, double_round_robin=previous.double_round_robin)
        return self.view(room_id)

    def ready(self, room_id: str, club_code: str) -> dict[str, object]:
        season = self._season(room_id)
        if season.live_round:
            return self.view(room_id)
        if self.current_round(room_id) > self._regular_round_count(season):
            raise MarketError("A temporada regular já terminou.")
        season.ready_clubs.add(club_code)
        return self.view(room_id)

    def preparation_deadline(self, room_id: str, duration_seconds: int) -> float | None:
        season = self._season(room_id)
        if season.live_round or season.transfer_window_open or self.current_round(room_id) > self._regular_round_count(season) or season.preparation_opened_at is None:
            return None
        return season.preparation_opened_at + duration_seconds

    def start_if_preparation_expired(self, room_id: str, market: InitialMarket, human_clubs: set[str], duration_seconds: int,
                                     match_seconds: int | None = None) -> bool:
        """Preparation timeout: coaches who did not confirm play with their saved plan."""
        deadline = self.preparation_deadline(room_id, duration_seconds)
        if deadline is None or self.clock() < deadline:
            return False
        season = self._season(room_id)
        season.ready_clubs |= human_clubs
        self.advance(room_id, market, human_clubs, match_seconds)
        return season.live_round is not None

    # ------------------------------------------------------------------ live round
    def advance(self, room_id: str, market: InitialMarket, human_clubs: set[str], match_seconds: int | None = None) -> dict[str, object]:
        season = self._season(room_id)
        match_seconds = self.match_seconds if match_seconds is None else int(match_seconds)
        if match_seconds not in DURATIONS:
            raise MarketError("Duração de partida inválida: escolha 1:30, 2:00 ou 3:00.")
        if season.live_round:
            return self.view(room_id)
        season.human_clubs = set(human_clubs)
        round_number = self.current_round(room_id)
        if round_number > self._regular_round_count(season):
            return self._advance_playoffs(room_id, market, season)
        if round_number == self._transfer_resume_round(season) and season.transfer_window_open:
            raise MarketError("A janela de transferências precisa ser encerrada antes da rodada 20.")
        if not human_clubs.issubset(season.ready_clubs):
            raise MarketError("Aguardando confirmação dos técnicos para esta rodada.")
        fixtures = [fixture for fixture in season.state.fixtures if fixture.round_number == round_number]
        prepared: dict[str, tuple[MatchEngine, dict[str, object]]] = {}
        for fixture in fixtures:
            if fixture.id in season.state.results:
                continue
            home_input, away_input, seed, bot_sides = self._fixture_inputs(room_id, market, fixture, human_clubs)
            prebuilt = season.prebuilt.pop(fixture.id, None)
            if prebuilt is not None and prebuilt.fingerprint == _fingerprint(home_input, away_input, seed, bot_sides):
                # Simulated during preparation from exactly these inputs: identical result.
                engine = prebuilt.engine
            else:
                engine = MatchEngine(fixture.id, season.mode, home_input, away_input, seed)
            meta = {"id": fixture.id, "home": fixture.home, "away": fixture.away, "status": "LIVE", "seed": seed,
                    "inputs": {"home": team_input_view(home_input), "away": team_input_view(away_input)},
                    "bot_sides": bot_sides}
            prepared[fixture.id] = (engine, meta)
        season.prebuilt.clear()
        # Publish all ten engines with one shared server clock. No result enters the
        # official table until the whole round is committed.
        announced_at = self.clock()
        started_at = announced_at + self.intro_seconds
        for match_id, (engine, meta) in prepared.items():
            if self._watched(meta):
                engine.enable_snapshots()
                season.directors[match_id] = Director(started_at, match_seconds)
            else:
                # Nobody watches bot against bot: no broadcast, frames or snapshots.
                engine.record_frames = False
                season.directors[match_id] = LinearClock(started_at, match_seconds)
            season.engines[match_id] = engine
            season.matches[match_id] = meta
        season.live_round = {"round_number": round_number, "announced_at": announced_at, "started_at": started_at,
                             "ends_at": started_at + match_seconds, "duration_seconds": match_seconds,
                             "match_seconds": match_seconds, "match_ids": list(prepared), "human_clubs": sorted(human_clubs)}
        season.ready_clubs.clear()
        return self.view(room_id)

    @staticmethod
    def _watched(meta: dict[str, object]) -> bool:
        return len(meta.get("bot_sides", [])) < 2

    def _fixture_inputs(self, room_id: str, market: InitialMarket, fixture: Fixture,
                        human_clubs: set[str]) -> tuple[TeamInput, TeamInput, int, list[int]]:
        season = self._season(room_id)
        home_input = self._team_input(room_id, market, fixture.home)
        away_input = self._team_input(room_id, market, fixture.away)
        seed = zlib.crc32(f"{room_id}:{season.season_number}:{fixture.id}".encode())
        bot_sides = [side for side, club in enumerate((fixture.home, fixture.away)) if club not in human_clubs]
        return home_input, away_input, seed, bot_sides

    # ------------------------------------------------------------------ cooperative simulation
    def prepare_slice(self, room_id: str, market: InitialMarket, human_clubs: set[str], budget: int = SLICE_TICKS) -> bool:
        """During preparation, simulate the next round's bot-against-bot matches ahead.

        They depend on nothing a coach can still change (only their own inputs, which
        are fingerprinted and re-checked when the round starts), so their CPU cost is
        spread over the preparation instead of competing with the live broadcast.
        Returns True while there is still work to do."""
        season = self._season(room_id)
        if season.live_round or season.transfer_window_open or season.recovering:
            return False
        round_number = self.current_round(room_id)
        if round_number > self._regular_round_count(season):
            return False
        for fixture in season.state.fixtures:
            if fixture.round_number != round_number or fixture.id in season.state.results:
                continue
            if fixture.home in human_clubs or fixture.away in human_clubs:
                season.prebuilt.pop(fixture.id, None)
                continue
            prebuilt = season.prebuilt.get(fixture.id)
            if prebuilt is None:
                home_input, away_input, seed, bot_sides = self._fixture_inputs(room_id, market, fixture, human_clubs)
                engine = MatchEngine(fixture.id, season.mode, home_input, away_input, seed)
                engine.record_frames = False
                season.prebuilt[fixture.id] = PrebuiltMatch(_fingerprint(home_input, away_input, seed, bot_sides), engine)
                return True
            engine = prebuilt.engine
            if not engine.finished:
                _advance_counted(engine, engine.tick + budget, (0, 1), (engine.inputs[0].tactics, engine.inputs[1].tactics))
                return True
        return False

    def simulate_slice(self, room_id: str, now: float | None = None, budget: int = SLICE_TICKS) -> tuple[bool, bool]:
        """One bounded unit of live simulation work (the caller yields between slices).

        Returns (urgent, more): `urgent` while something the screen will need soon is
        still missing; `more` while any useful work remains (e.g. finishing unwatched
        matches early with spare CPU)."""
        season = self._season(room_id)
        live = season.live_round
        if not live:
            return False, False
        now = self.clock() if now is None else now
        # 1. Engines being rebuilt after a restart.
        for match_id, job in list(season.recovering.items()):
            job.step(budget)
            if job.done:
                season.recovering.pop(match_id)
            return True, True
        started = now >= float(live["started_at"])
        pending_more = False
        # 2. Watched matches: keep the engine ahead of the planner, then plan.
        for match_id in live["match_ids"]:
            engine, director = season.engines.get(match_id), season.directors.get(match_id)
            if engine is None or not isinstance(director, Director) or director.complete:
                continue
            meta = season.matches[match_id]
            bots = tuple(meta.get("bot_sides", []))
            baselines = (engine.inputs[0].tactics, engine.inputs[1].tactics)
            # During the presentation the frontier stays at kick-off, so tactics changed
            # before the whistle count from the first minute.
            if started:
                cursor = director.cursor_tick
                half_limit = TICKS_PER_HALF if cursor <= TICKS_PER_HALF else FULL_TIME_TICK
                target = min(half_limit, cursor + PRESIM_LEAD)
                if engine.tick < target and not engine.finished:
                    _advance_counted(engine, min(target, engine.tick + budget), bots, baselines)
                    return True, True
            if director.cursor_real < now + 1.5:
                before = (director.cursor_real, len(director.segments))
                director.plan(engine, lambda tick, e=engine, b=bots, base=baselines: _advance_counted(e, tick, b, base), now)
                engine.prune_snapshots(director.shown_tick(now) - 30)
                if (director.cursor_real, len(director.segments)) != before:
                    return True, True
        # 3. Unwatched matches: stay ahead of their score-ticker clock.
        for match_id in live["match_ids"]:
            engine, clock = season.engines.get(match_id), season.directors.get(match_id)
            if engine is None or not isinstance(clock, LinearClock) or engine.finished:
                continue
            need = FULL_TIME_TICK if now >= clock.deadline - 2 else min(FULL_TIME_TICK, clock.shown_tick(now + 3) + LINEAR_LEAD)
            if engine.tick < need:
                _advance_counted(engine, min(need, engine.tick + budget), (0, 1), (engine.inputs[0].tactics, engine.inputs[1].tactics))
                return True, True
            pending_more = True
        # 4. Spare CPU: finish unwatched matches early (their result is fixed anyway).
        if pending_more:
            for match_id in live["match_ids"]:
                engine, clock = season.engines.get(match_id), season.directors.get(match_id)
                if engine is not None and isinstance(clock, LinearClock) and not engine.finished:
                    _advance_counted(engine, engine.tick + budget, (0, 1), (engine.inputs[0].tactics, engine.inputs[1].tactics))
                    return False, True
        return False, False

    def ready_to_finish(self, room_id: str, now: float | None = None) -> bool:
        """The round can be committed without simulating anything inline."""
        season = self._season(room_id)
        live = season.live_round
        if not live or season.recovering:
            return False
        now = self.clock() if now is None else now
        if now < float(live["ends_at"]):
            return False
        for match_id in live["match_ids"]:
            engine, clock = season.engines.get(match_id), season.directors.get(match_id)
            if engine is None:
                continue
            if isinstance(clock, Director):
                # The planner reaches the final whistle cheaply once the engine is there.
                if engine.tick < FULL_TIME_TICK - 1 and not engine.finished:
                    return False
            elif not engine.finished:
                return False
        return True

    def round_state(self, room_id: str, now: float | None = None) -> str:
        """PREPARING -> READY -> STARTING -> LIVE -> FINISHED (then PREPARING again)."""
        season = self._season(room_id)
        now = self.clock() if now is None else now
        live = season.live_round
        if live:
            if season.recovering:
                return "RECOVERING"
            if now < float(live["started_at"]):
                return "STARTING"
            return "LIVE" if now < float(live["ends_at"]) else "FINISHED"
        humans = season.human_clubs
        if humans and humans.issubset(season.ready_clubs):
            return "READY"
        return "PREPARING"

    def shown_tick(self, season: RoomSeason, match_id: str, now: float) -> int:
        """Tick currently on screen for a live match (the broadcast trails the engine)."""
        director = season.directors.get(match_id)
        engine = season.engines.get(match_id)
        if director is None or engine is None:
            return FULL_TIME_TICK
        return min(engine.tick, director.shown_tick(now))

    def clock_view(self, live: dict[str, object], now: float, director: Director | None = None) -> dict[str, object]:
        started = float(live["started_at"])
        tick = director.tick_at(now) if director else 0.0
        segment = None
        if director:
            current = [s for s in director.window(now, past=0)]
            segment = current[-1] if current else None
        phase = "FIRST_HALF" if tick < TICKS_PER_HALF else "SECOND_HALF"
        if segment and segment["k"] == "BREAK" and segment["label"] == "HALF_TIME":
            phase = "HALF_TIME"
        if tick >= FULL_TIME_TICK:
            phase = "FULL_TIME"
        if now < started:
            phase = "PRESENTATION"
        halftime = next((s for s in (director.segments if director else []) if s["label"] == "HALF_TIME" and s["k"] == "BREAK"), None)
        return {"tick": int(tick), "kickoff_at": started, "minute": round(tick / 60, 2), "phase": phase, "server_now": now,
                "match_seconds": live.get("match_seconds", live.get("duration_seconds")),
                "segment": segment["k"] if segment else None,
                "halftime_ends_at": float(halftime["r1"]) if halftime else None, "ends_at": live["ends_at"]}

    def sync_live(self, room_id: str, now: float | None = None) -> None:
        """Synchronous catch-up of every live match to the server clock.

        The server never calls this on a request path: the round task does the same
        work in small slices (`simulate_slice`). It remains for the commit at the
        final whistle (where it is a no-op once the slices have caught up) and tests."""
        season = self._season(room_id)
        live = season.live_round
        if not live:
            return
        now = self.clock() if now is None else now
        for match_id, job in list(season.recovering.items()):
            while not job.done:
                job.step(FULL_TIME_TICK)
            season.recovering.pop(match_id)
        for match_id in live["match_ids"]:
            engine = season.engines.get(match_id)
            director = season.directors.get(match_id)
            if engine is None or director is None:
                continue
            meta = season.matches[match_id]
            bots = tuple(meta.get("bot_sides", []))
            baselines = (engine.inputs[0].tactics, engine.inputs[1].tactics)
            if isinstance(director, LinearClock):
                target = FULL_TIME_TICK if now >= director.deadline - 2 else director.shown_tick(now + 3) + LINEAR_LEAD
                advance_with_bots(engine, target, bots, baselines)
                continue
            director.plan(engine, lambda tick, e=engine, b=bots, base=baselines: advance_with_bots(e, tick, b, base), now)
            engine.prune_snapshots(director.shown_tick(now) - 30)

    def finish_due(self, room_id: str) -> bool:
        season = self._season(room_id)
        live = season.live_round
        if not live or self.clock() < live["ends_at"]:
            return False
        # Synchronous commit under the caller's room lock, with no await points.
        ends_at = float(live["ends_at"])
        self.sync_live(room_id, ends_at)
        results = {}
        for match_id in live["match_ids"]:
            engine = season.engines.pop(match_id, None)
            season.directors.pop(match_id, None)
            if engine is not None:
                meta = season.matches[match_id]
                # The broadcast has reached the final whistle; finishing is a no-op guard.
                advance_with_bots(engine, FULL_TIME_TICK, tuple(meta.get("bot_sides", [])), (engine.inputs[0].tactics, engine.inputs[1].tactics))
                season.matches[match_id] = final_record(engine, meta)
            match = season.matches[match_id]
            results[match_id] = MatchResult(match_id, int(match["home_goals"]), int(match["away_goals"]))
        season.state.results.update(results)
        season.transfer_window_open = live["round_number"] == self._transfer_open_after_round(season)
        season.live_round = None
        season.preparation_opened_at = self.clock()
        return True

    def command(self, room_id: str, club: str, payload: dict[str, object]) -> dict[str, object]:
        """Coach command during a live match. Same API the bot coaches use."""
        season = self._season(room_id)
        live = season.live_round
        if not live:
            raise MarketError("Não há partida ao vivo no momento.")
        if season.recovering:
            raise MarketError("A partida está sendo recuperada após uma reinicialização do servidor. Tente de novo em alguns segundos.")
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
        director = season.directors.get(match_id)
        if director is not None and director.complete:
            raise MarketError("A partida já terminou.")
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
        if live and season.recovering:
            return {"server_now": now, "live_round": live, "recovering": True, "round_state": "RECOVERING", "clock": None,
                    "broadcast": None, "match": None, "scores": [], "table": [], "official_table": [],
                    "current_round": self.current_round(room_id), "ready_clubs": sorted(season.ready_clubs)}
        ids = live["match_ids"] if live else [f.id for f in season.state.fixtures
                if f.round_number == min(self._regular_round_count(season), max(1, self.current_round(room_id) - 1))]
        own_id = next((key for key in ids if key in season.matches and
                       club in (season.matches[key]["home"], season.matches[key]["away"])), None)
        scores = [self._score(season, key, now) for key in ids if key in season.matches]
        director = season.directors.get(own_id) if own_id else None
        if live and director is None and live["match_ids"]:
            director = season.directors.get(live["match_ids"][0])
        return {"server_now": now, "live_round": live, "clock": self.clock_view(live, now, director) if live else None,
                "broadcast": director.window(now) if director else None,
                "match": self._personal_match(room_id, own_id, club, now) if own_id else None,
                "scores": scores, "table": self.live_table(room_id, now),
                "official_table": standings(tuple(sorted({f.home for f in season.state.fixtures})),
                                            season.state.fixtures, season.state.results),
                "current_round": self.current_round(room_id), "ready_clubs": sorted(season.ready_clubs),
                "round_state": self.round_state(room_id, now), "recovering": False}

    def live_frames(self, room_id: str, club: str, since_tick: int, sync: bool = False,
                    known_timeline: list[int] | tuple[int, int] | None = None) -> dict[str, object]:
        """Authoritative frames of the coach's match up to the tick on screen.

        Only frames the broadcast shows are sent: every tick of a highlight, and the
        edges of a cut (the client cross-fades between them instead of sliding).
        A socket push passes the timeline key it already sent: the broadcast window is
        then only rebuilt and included when it changed (the push runs several times a
        second per coach, so this is the hot path on a small server)."""
        season = self._season(room_id)
        live = season.live_round
        if not live:
            return {"frames": [], "tick": None, "finished": True}
        now = self.clock()
        if season.recovering:
            return {"frames": [], "tick": None, "finished": False, "recovering": True, "server_now": now}
        if sync:
            self.sync_live(room_id, now)
        match_id = next((key for key in live["match_ids"] if club in (season.matches[key]["home"], season.matches[key]["away"])), None)
        engine = season.engines.get(match_id) if match_id else None
        director = season.directors.get(match_id) if match_id else None
        if engine is None or director is None:
            return {"frames": [], "tick": None, "finished": True}
        shown = self.shown_tick(season, match_id, now)
        since = max(int(since_tick), shown - 240)
        # Both coaches of a match (and every tab) ask for the same window: compute once.
        memo_key = (room_id, match_id, since, shown)
        rows = self._frames_memo.get(memo_key)
        if rows is None:
            rows = [row for row in engine.frames_between(since, shown) if director.visible(int(row["t"]))] if shown > since else []
            if len(self._frames_memo) >= 256:
                self._frames_memo.clear()
            self._frames_memo[memo_key] = rows
        else:
            FRAME_MEMO_HITS[0] += 1
        timeline = list(director.timeline_key(now))
        view: dict[str, object] = {"match_id": match_id, "tick": shown, "server_now": now, "frames": rows, "timeline": timeline}
        if known_timeline is None or list(known_timeline) != timeline:
            view["broadcast"] = director.window(now)
        if known_timeline is None:
            goals = [e for e in engine.events if e["kind"] == "GOAL" and int(e["tick"]) <= shown]
            view["score"] = {"home": sum(1 for g in goals if g["team"] == engine.clubs[0]),
                             "away": sum(1 for g in goals if g["team"] == engine.clubs[1])}
        return view

    # ------------------------------------------------------------------ light live messages
    def _own_live_match(self, season: RoomSeason, club: str) -> str | None:
        live = season.live_round
        if not live:
            return None
        return next((key for key in live["match_ids"] if club in (season.matches[key]["home"], season.matches[key]["away"])), None)

    @staticmethod
    def _shown_event_count(engine: MatchEngine, shown: int, start: int = 0) -> int:
        """Events are append-only and in tick order: count those already on screen."""
        events = engine.events
        index = min(max(0, start), len(events))
        while index > 0 and int(events[index - 1]["tick"]) > shown:
            index -= 1
        while index < len(events) and int(events[index]["tick"]) <= shown:
            index += 1
        return index

    def live_state(self, room_id: str, club: str, known: dict[str, object] | None = None,
                   heartbeat: bool = False) -> dict[str, object] | None:
        """Reliable, incremental state of the coach's live match (WebSocket `live.state`).

        `seq` is the number of match events already on screen. A message carries the
        events in (`seq_from`, `seq`], the score, the round's scores and - only when a
        score changed - the live table. Nothing beyond the tick on screen is revealed;
        the rival's tactical choices stay masked exactly as in the HTTP view.
        Returns None when nothing changed (unless a heartbeat is due)."""
        season = self._season(room_id)
        live = season.live_round
        if not live or season.recovering:
            return None
        match_id = self._own_live_match(season, club)
        engine = season.engines.get(match_id) if match_id else None
        if engine is None:
            return None
        now = self.clock()
        known = known or {}
        if known.get("match_id") != match_id:
            known = {}
        shown = self.shown_tick(season, match_id, now)
        seq_from = int(known.get("seq", 0))
        seq = self._shown_event_count(engine, shown, seq_from)
        scores = [self._score(season, key, now) for key in live["match_ids"] if key in season.matches]
        scores_key = [(s["home_goals"], s["away_goals"]) for s in scores]
        changed_scores = scores_key != known.get("scores_key")
        if seq == seq_from and not changed_scores and not heartbeat:
            return None
        meta = season.matches[match_id]
        rival = meta["away"] if meta["home"] == club else meta["home"]
        events = [{**event, "tactics": None, "outcome": "CHANGED"} if event.get("kind") == "TACTICS" and event.get("team") == rival else event
                  for event in engine.events[min(seq_from, seq):seq]]
        own = scores[live["match_ids"].index(match_id)]
        message: dict[str, object] = {
            "type": "live.state", "match_id": match_id, "seq_from": min(seq_from, seq), "seq": seq, "tick": shown,
            "server_now": now, "ends_at": live["ends_at"], "score": {"home": own["home_goals"], "away": own["away_goals"]},
            "events": events, "scores": scores,
        }
        if changed_scores:
            message["table"] = self.live_table(room_id, now)
        known.update(match_id=match_id, seq=seq, scores_key=scores_key)
        message["_known"] = known
        return message

    def live_stats(self, room_id: str, club: str) -> dict[str, object] | None:
        """Compact match detail for the side panels (WebSocket `live.stats`, every few s):
        statistics, xG, line-ups (stamina, cards, ratings) and the coach's own orders,
        at the tick on screen - without the event list and the player attributes."""
        season = self._season(room_id)
        if not season.live_round or season.recovering:
            return None
        match_id = self._own_live_match(season, club)
        if not match_id or match_id not in season.engines:
            return None
        match = self._personal_match(room_id, match_id, club, self.clock())
        # Only what changes during a match travels again; names, numbers, roles and
        # attributes are already in the client's live view (merged by player id).
        keep = ("statistics", "home_xg", "away_xg", "substitutions", "commands", "ordered_tactics", "tactics", "player_of_the_match")
        slim = {key: match[key] for key in keep if key in match}
        dynamic = ("id", "on_pitch", "sent_off", "yellow_cards", "stamina", "available", "entered_tick", "left_tick", "rating", "stats")
        slim["lineups"] = {side: [{k: player[k] for k in dynamic if k in player} for player in players]
                           for side, players in match["lineups"].items()}
        card_stats = ("goals", "assists", "passes", "passes_completed", "shots", "tackles", "interceptions", "distance")
        for side in slim["lineups"].values():
            for player in side:
                if isinstance(player.get("stats"), dict):
                    player["stats"] = {k: round(player["stats"][k], 1) if isinstance(player["stats"][k], float) else player["stats"][k]
                                       for k in card_stats if k in player["stats"]}
                if isinstance(player.get("stamina"), float):
                    player["stamina"] = round(player["stamina"], 3)
                if isinstance(player.get("rating"), float):
                    player["rating"] = round(player["rating"], 1)
        return {"type": "live.stats", "match_id": match_id, "match": slim}

    def _score(self, season: RoomSeason, match_id: str, now: float | None = None) -> dict[str, object]:
        match = season.matches[match_id]
        engine = season.engines.get(match_id)
        if engine is None:
            return {"id": match_id, "home": match["home"], "away": match["away"], "home_goals": match["home_goals"],
                    "away_goals": match["away_goals"], "minute": 90, "status": "FINISHED"}
        shown = self.shown_tick(season, match_id, self.clock() if now is None else now)
        goals = [e for e in engine.events if e["kind"] == "GOAL" and int(e["tick"]) <= shown]
        return {"id": match_id, "home": match["home"], "away": match["away"],
                "home_goals": sum(1 for g in goals if g["team"] == engine.clubs[0]),
                "away_goals": sum(1 for g in goals if g["team"] == engine.clubs[1]),
                "minute": min(90, round(shown / 60)), "status": "LIVE"}

    def _personal_match(self, room_id: str, match_id: str, club: str, now: float | None = None) -> dict[str, object]:
        """The coach's view of his own match: the rival's exact settings stay private."""
        match = self.match(room_id, match_id, now)
        you = "home" if match["home"] == club else "away" if match["away"] == club else None
        if you and "tactics" in match:
            rival = "away" if you == "home" else "home"
            match = {**match, "tactics": {**match["tactics"], rival: None}}
            match["events"] = [{**event, "tactics": None, "outcome": "CHANGED"} if event.get("kind") == "TACTICS" and event.get("team") == match[rival] else event
                               for event in match["events"]]
        season = self._season(room_id)
        engine = season.engines.get(match_id)
        side = 0 if you == "home" else 1
        if engine and you:
            match["commands"] = [status for command_id, status in engine.applied_commands.items() if command_id.startswith(f"{club}:")]
            # The coach's own orders are his to know even before they reach the screen.
            match["ordered_tactics"] = engine.tactics[side].view()
        # Engine inputs and the command log stay server-side: they would reveal the
        # rival's plan. Each coach gets only his own decisions.
        log = match.get("command_log") or []
        match = {key: value for key, value in match.items() if key not in ("inputs", "seed", "command_log", "bot_sides", "frontier")}
        if you and not engine:
            match["commands"] = [{"command_id": c["command_id"], "kind": c["kind"], "status": "APPLIED", "applied_tick": c["tick"],
                                  "tactics": c.get("tactics"), "out_player_id": c.get("out"), "in_player_id": c.get("in")}
                                 for c in log if int(c["side"]) == side and str(c["command_id"]).startswith(f"{club}:")]
        return {**match, "you": you}

    def live_table(self, room_id: str, now: float | None = None) -> list[dict[str, object]]:
        season = self._season(room_id)
        results = dict(season.state.results)
        if season.live_round:
            for match_id in season.live_round["match_ids"]:
                score = self._score(season, match_id, now)
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
        now = self.clock() if now is None else now
        shown = self.shown_tick(season, match_id, now)
        # Only what the broadcast has shown so far: the engine may already have simulated
        # a little further (lookahead), but that future is never sent to a client.
        summary = engine.summary(at_tick=shown)
        return summary | {"status": "LIVE", "pressure": project_events(match["home"], match["away"], summary["events"])["pressure"],
                          "started_at": live["started_at"], "ends_at": live["ends_at"],
                          "clock": self.clock_view(live, now, season.directors.get(match_id)),
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
        if self.current_round(room_id) != self._transfer_resume_round(season):
            if not season.transfer_window_open:
                return self.view(room_id)
            raise MarketError("A janela só pode ser encerrada entre as metades do campeonato.")
        season.transfer_window_open = False
        season.ready_clubs.clear()
        season.preparation_opened_at = self.clock()
        return self.view(room_id)

    def _advance_playoffs(self, room_id: str, market: InitialMarket, season: RoomSeason) -> dict[str, object]:
        # A four- or six-club league ends on the table: eight qualifiers do not
        # exist, so silently fabricating a knockout would be incorrect.
        if len(market.teams) < 8:
            if not season.playoffs:
                champion = standings(tuple(market.teams), season.state.fixtures, season.state.results)[0]["club_code"]
                season.playoffs = PlayoffState((), champion=str(champion), next_stage="COMPLETE")
                self._apply_progression(room_id, market, season)
            return self.view(room_id)
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
        # Coin rooms are closed virtual economies: neither a new 100-coin grant
        # nor legacy cash prizes may alter the balance between transfer windows.
        if market.market_mode == "COINS":
            return
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
        total_rounds = self._regular_round_count(season)
        return {"live_round": season.live_round, "server_now": self.clock(), "preparation_opened_at": season.preparation_opened_at, "live_table": self.live_table(room_id), "season_number": season.season_number, "current_round": current, "total_rounds": total_rounds, "double_round_robin": season.double_round_robin, "regular_season_complete": current > total_rounds, "season_complete": bool(season.playoffs and season.playoffs.champion), "progression_applied": season.progression_applied, "champion": season.playoffs.champion if season.playoffs else None, "playoffs": season.playoffs.view() if season.playoffs else None, "transfer_window_open": season.transfer_window_open, "ready_clubs": sorted(season.ready_clubs), "human_clubs": sorted(season.human_clubs), "round_state": self.round_state(room_id), "recovering": bool(season.recovering), "table": standings(clubs, season.state.fixtures, season.state.results), "fixtures": [{"id": fixture.id, "round_number": fixture.round_number, "home": fixture.home, "away": fixture.away, "result": self._result_view(season.state.results.get(fixture.id)), "match_id": fixture.id if fixture.id in season.matches else None} for fixture in season.state.fixtures if fixture.round_number == min(current, total_rounds)], "matches": [{"id": match_id, "round_number": next((f.round_number for f in season.state.fixtures if f.id == match_id), total_rounds + 1), "home": match["home"], "away": match["away"], "home_goals": projected["home_goals"], "away_goals": projected["away_goals"]} for match_id, match in season.matches.items() for projected in [self._score(season, match_id)]], "match_count": len(season.matches), "schedule": [{"id": f.id, "round_number": f.round_number, "home": f.home, "away": f.away, "result": self._result_view(season.state.results.get(f.id))} for f in season.state.fixtures], "season_history": season.season_history, "development_records": season.development_records, "top_scorers": self._top_scorers(season)}

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
        def live_entry(key: str, match: dict[str, object]) -> dict[str, object]:
            job = season.recovering.get(key)
            # Mid-rebuild the engine only holds part of the log: persist the full one.
            log, frontier = (list(job.commands), job.until) if job else (list(season.engines[key].command_log), season.engines[key].tick)
            return {**match, "command_log": log, "frontier": frontier,
                    "broadcast": season.directors[key].to_dict() if key in season.directors else None}
        matches = {key: (live_entry(key, match) if key in season.engines else match) for key, match in season.matches.items()}
        return {
            "live_round": season.live_round,
            "human_clubs": sorted(season.human_clubs),
            "preparation_opened_at": season.preparation_opened_at,
            "double_round_robin": season.double_round_robin,
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
        clubs = {club for fixture in fixtures for club in (fixture.home, fixture.away)}
        team_count = len(clubs)
        if team_count not in LEAGUE_SIZES:
            raise ValueError("Calendário do snapshot tem uma quantidade de clubes não suportada.")
        # Custom leagues (4 to 20 clubs, single or double round robin): the format is
        # stored; older snapshots (always 20 clubs, ida e volta) infer it.
        rounds_single = team_count - 1
        double_round_robin = bool(payload.get("double_round_robin", len(fixtures) == team_count * rounds_single))
        rounds = rounds_single * (2 if double_round_robin else 1)
        expected = team_count * rounds // 2
        if len(fixtures) != expected or len({fixture.id for fixture in fixtures}) != expected:
            raise ValueError("Calendário do snapshot está incompleto ou duplicado.")
        pairs = [(f.home, f.away) for f in fixtures]
        unique_pairs = len(set(pairs)) == expected if double_round_robin else len({frozenset(p) for p in pairs}) == expected
        per_round: dict[tuple[int, str], int] = {}
        for f in fixtures:
            for club in (f.home, f.away):
                per_round[(f.round_number, club)] = per_round.get((f.round_number, club), 0) + 1
        if ({f.round_number for f in fixtures} != set(range(1, rounds + 1)) or not unique_pairs
                or any(f.home == f.away for f in fixtures)
                or len(per_round) != rounds * team_count or any(count != 1 for count in per_round.values())):
            raise ValueError("Calendário do snapshot viola as rodadas do campeonato.")
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
            if match.get("status") == "LIVE" and match_id not in live_ids:
                raise ValueError("Snapshot de transmissão contém partida ao vivo fora da rodada.")
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
            if "match_seconds" not in live and "play_seconds" in live:
                # Snapshot from the previous clock model: keep its kick-off, adopt 3:00.
                live["match_seconds"] = live["duration_seconds"] = 180
                live["ends_at"] = float(live.get("started_at", 0)) + 180
            if (not isinstance(ids, list) or len(ids) != team_count // 2 or set(ids) != expected
                    or not set(ids).issubset(matches_payload) or set(ids) & set(state.results)
                    or int(live.get("match_seconds", 0)) not in DURATIONS
                    or abs(float(live.get("ends_at", 0)) - float(live.get("started_at", 0)) - float(live.get("match_seconds", -1))) > 1e-6):
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
            preparation_opened_at=float(payload["preparation_opened_at"]) if payload.get("preparation_opened_at") is not None else None,
            double_round_robin=double_round_robin,
        )
        if room_season.live_round:
            # Every live engine is rebuilt deterministically from inputs, seed and the
            # command log - in slices, by the round task (`simulate_slice`), never here:
            # replaying ten matches inline used to keep a 0.1 CPU host busy for over a
            # minute before it could even answer its health check.
            for match_id in room_season.live_round["match_ids"]:
                meta = matches_payload[match_id]
                log = list(meta.pop("command_log", []))
                home, away = team_input_from_view(meta["inputs"]["home"]), team_input_from_view(meta["inputs"]["away"])
                until = max([int(meta.pop("frontier", 0) or 0), *(int(c["tick"]) for c in log)])
                engine = MatchEngine(match_id, room_season.mode, home, away, int(meta["seed"]))
                broadcast = meta.pop("broadcast", None)
                live_round = room_season.live_round
                clock = (clock_from_dict(broadcast) if isinstance(broadcast, dict)
                         else Director(float(live_round["started_at"]), int(live_round["match_seconds"])))
                if isinstance(clock, Director):
                    engine.enable_snapshots()
                else:
                    engine.record_frames = False
                room_season.engines[match_id] = engine
                room_season.directors[match_id] = clock
                room_season.recovering[match_id] = ReplayJob(engine, log, until)
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
        for round_number in range(1, self._regular_round_count(season) + 1):
            fixtures = [fixture for fixture in season.state.fixtures if fixture.round_number == round_number]
            if any(fixture.id not in season.state.results for fixture in fixtures):
                return round_number
        return self._regular_round_count(season) + 1

    @staticmethod
    def _regular_round_count(season: RoomSeason) -> int:
        return max((fixture.round_number for fixture in season.state.fixtures), default=0)

    @classmethod
    def _transfer_open_after_round(cls, season: RoomSeason) -> int:
        return max(1, cls._regular_round_count(season) // 2)

    @classmethod
    def _transfer_resume_round(cls, season: RoomSeason) -> int:
        return cls._transfer_open_after_round(season) + 1

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
season_service = SeasonService(intro_seconds=_settings.live_intro_seconds, match_seconds=_settings.live_match_seconds)
