"""Gameplay Lab: reproducible Modo Jogável scenarios outside any league.

A lab session is an ordinary ``HighlightMatch`` (the same authoritative engine used by
every game mode) whose timeline holds one chosen opportunity for the human (home) side,
followed by one bot attack so the replay path can be seen too. It never touches a room,
a season, a career or a result. Sessions live in memory, are capped and expire.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from app.domain.bot_coach import choose_lineup
from app.domain.catalog import PlayerCatalog
from app.domain.highlights import KINDS, HighlightMatch
from app.domain.match_engine import PlayerInput, TeamInput
from app.domain.squad import formation_slots
from app.services.season_service import team_input_view

MAX_SESSIONS = 40
TTL_SECONDS = 30 * 60
LAB_KINDS = tuple(k for k in KINDS if k != "CORNER")


@dataclass
class LabSession:
    id: str
    owner: str
    match: HighlightMatch
    touched: float


def _team(catalog: PlayerCatalog, mode: str, club: str) -> TeamInput:
    roster = [p for p in catalog.players if p.club_code == club]
    code, assignments = choose_lineup(mode, roster, {})
    by_id = {p.id: p for p in roster}
    starters = []
    for index, slot in enumerate(formation_slots(mode, code)):
        player = by_id[assignments[slot.id]]
        starters.append(PlayerInput(player.id, player.name, player.position, slot.position, slot.x, slot.y, player.overall, dict(player.attributes), index + 1))
    return TeamInput(club, code, tuple(starters), ())


class LabService:
    def __init__(self, clock=time.time) -> None:
        self.clock = clock
        self.sessions: dict[str, LabSession] = {}

    def _prune(self) -> None:
        now = self.clock()
        for key, session in list(self.sessions.items()):
            if now - session.touched > TTL_SECONDS:
                self.sessions.pop(key)
        while len(self.sessions) >= MAX_SESSIONS:
            oldest = min(self.sessions.values(), key=lambda s: s.touched)
            self.sessions.pop(oldest.id)

    def create(self, owner: str, catalog: PlayerCatalog, mode: str, kind: str, home: str, away: str, seed: int, ruleset: str = "TRADITIONAL",
               second_half: bool = False) -> dict[str, object]:
        if kind not in LAB_KINDS:
            raise ValueError("Cenário desconhecido.")
        clubs = sorted({p.club_code for p in catalog.players})
        if home not in clubs or away not in clubs or home == away:
            home, away = clubs[0], clubs[1]
        self._prune()
        home_team, away_team = _team(catalog, mode, home), _team(catalog, mode, away)
        now = self.clock()
        match = HighlightMatch.create(f"LAB-{uuid.uuid4().hex[:8]}", mode, home_team, away_team, team_input_view(home_team), team_input_view(away_team),
                                      [home], seed, ruleset, 20, True, now - 4.0 * 0.25)
        # One chosen chance for the coach, then one bot attack (replay) and the final whistle.
        match.timeline = [{"side": 0, "kind": kind, "minute": 1.0, "index": 0}, {"side": 1, "kind": "BUILDUP", "minute": 50.0, "index": 1}]
        match.late_checked = True
        if second_half:
            # After the change of ends: the home side attacks to the LEFT.
            match.half_time_done, match.minute = True, 46.0
            match.timeline = [{"side": 0, "kind": kind, "minute": 46.5, "index": 0}, {"side": 1, "kind": "BUILDUP", "minute": 70.0, "index": 1}]
        session = LabSession(uuid.uuid4().hex, owner, match, now)
        self.sessions[session.id] = session
        return {"id": session.id, "match": match.view(home, now)}

    def _get(self, owner: str, session_id: str) -> LabSession:
        session = self.sessions.get(session_id)
        if session is None or session.owner != owner:
            raise KeyError("Sessão de laboratório não encontrada.")
        session.touched = self.clock()
        return session

    def view(self, owner: str, session_id: str, known: int | None) -> dict[str, object]:
        session = self._get(owner, session_id)
        match, now = session.match, self.clock()
        club = match.clubs[0]
        match.seen(club, now)
        match.advance(now)
        if known is not None and known == match.revision:
            return {"unchanged": True, "revision": match.revision, "minute": round(match.clock_minute(now), 2), "server_now": now,
                    "connected": {c: match.connected(c, now) for c in match.humans}}
        return match.view(club, now)

    def act(self, owner: str, session_id: str, payload: dict[str, object]) -> dict[str, object]:
        session = self._get(owner, session_id)
        match, now = session.match, self.clock()
        club = match.clubs[0]
        result = match.submit(club, payload, now)
        return {**result, "match": match.view(club, now)}


lab_service = LabService()
