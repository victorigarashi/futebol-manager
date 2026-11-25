"""Engine-neutral match contract (MatchPayload v1).

What a match engine needs to play one official fixture, derived from the snapshot the season
already freezes when a round starts (`season.matches[id]["inputs"]`, built by
`SeasonService._team_input` from the club's current roster and saved lineup). Nothing here
re-reads the market: once a round has started the payload is stable even if the market
changes later, and its checksum proves it.

This is NOT the format of any external engine. Engine adapters (app.domain.engine_adapters)
translate it; an adapter that cannot do something says so explicitly.

Rules (all from the project, none invented):
- Formation slots per mode come from `app.domain.squad.formation_slots` (5x5 or 11x11): the
  number of starters and the position of each slot must match exactly.
- Exactly one goalkeeper among the starters; no player twice in a team or in both teams.
- Bench: at most 7 (the size `_team_input` builds).
- Attributes: only the keys the catalog actually has (FUT six + four goalkeeper keys), 1..99.
  Players the catalog has no attributes for carry none (provenance OVERALL_ONLY); the payload
  never derives or invents them. The values are the catalog's, shifted by the player's career
  progression and condition exactly as the current engine receives them.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.domain.market import MarketError
from app.domain.squad import formation_slots

MATCH_PAYLOAD_SCHEMA_VERSION = 1
MODES = ("FIVE_A_SIDE", "ELEVEN_A_SIDE")
NATURAL_POSITIONS = ("GK", "DF", "MF", "ST")
OUTFIELD_ATTRIBUTES = ("pace", "shooting", "passing", "dribbling", "defending", "physical")
GOALKEEPER_ATTRIBUTES = ("gk_diving", "gk_handling", "gk_reflexes", "gk_positioning")
KNOWN_ATTRIBUTES = frozenset(OUTFIELD_ATTRIBUTES + GOALKEEPER_ATTRIBUTES)
MAX_BENCH = 7


class MatchContractError(ValueError):
    """The fixture cannot be expressed as a valid MatchPayload (the message says why, in Portuguese)."""


class PlayerStats(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    overall: int = Field(ge=1, le=99)
    attributes: dict[str, int] = Field(default_factory=dict)
    provenance: Literal["CATALOG", "OVERALL_ONLY"]

    @model_validator(mode="after")
    def _known(self) -> PlayerStats:
        unknown = set(self.attributes) - KNOWN_ATTRIBUTES
        if unknown:
            raise ValueError(f"Atributos desconhecidos: {sorted(unknown)}")
        if any(not 1 <= v <= 99 for v in self.attributes.values()):
            raise ValueError("Atributos devem estar entre 1 e 99.")
        if (self.provenance == "CATALOG") != bool(self.attributes):
            raise ValueError("Proveniência inconsistente com os atributos.")
        return self


class MatchPlayer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    player_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    # Only catalogue players exist in the project today (no user-created players).
    origin: Literal["CATALOG"] = "CATALOG"
    natural_position: Literal["GK", "DF", "MF", "ST"]
    slot_position: Literal["GK", "DF", "MF", "ST"]
    slot_x: float = Field(ge=0, le=100)
    slot_y: float = Field(ge=0, le=100)
    shirt_number: int = Field(ge=0, le=99)
    is_starter: bool
    stats: PlayerStats


class MatchTeam(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    side: Literal["HOME", "AWAY"]
    club_code: str = Field(min_length=3, max_length=3)
    formation_code: str = Field(min_length=1)
    starters: tuple[MatchPlayer, ...]
    bench: tuple[MatchPlayer, ...] = ()
    tactics: dict[str, str] = Field(default_factory=dict)
    instructions: dict[str, str] = Field(default_factory=dict)


class MatchPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = MATCH_PAYLOAD_SCHEMA_VERSION
    match_id: str = Field(min_length=1)
    mode: Literal["FIVE_A_SIDE", "ELEVEN_A_SIDE"]
    competition: str = "LEAGUE"
    seed: int
    home: MatchTeam
    away: MatchTeam
    provenance: dict[str, str] = Field(default_factory=dict)
    checksum: str = ""

    @model_validator(mode="after")
    def _valid_fixture(self) -> MatchPayload:
        validate_payload(self)
        return self


def _canonical(payload: MatchPayload) -> bytes:
    data = payload.model_dump(mode="json", exclude={"checksum"})
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def payload_checksum(payload: MatchPayload) -> str:
    return "sha256:" + hashlib.sha256(_canonical(payload)).hexdigest()


def verify_checksum(payload: MatchPayload) -> bool:
    return bool(payload.checksum) and payload.checksum == payload_checksum(payload)


def validate_payload(payload: MatchPayload) -> None:
    if payload.home.side != "HOME" or payload.away.side != "AWAY":
        raise MatchContractError("Mandante e visitante trocados no contrato.")
    if payload.home.club_code == payload.away.club_code:
        raise MatchContractError("Um clube não pode enfrentar a si mesmo.")
    seen: set[str] = set()
    for team in (payload.home, payload.away):
        _validate_team(team, payload.mode)
        for player in (*team.starters, *team.bench):
            if player.player_id in seen:
                raise MatchContractError(f"Jogador {player.player_id} aparece mais de uma vez na partida.")
            seen.add(player.player_id)


def _validate_team(team: MatchTeam, mode: str) -> None:
    try:
        slots = formation_slots(mode, team.formation_code)
    except MarketError as error:
        raise MatchContractError(f"Formação {team.formation_code} inválida para {mode}.") from error
    if not slots:
        raise MatchContractError(f"Formação {team.formation_code} inválida para {mode}.")
    if len(team.starters) != len(slots):
        raise MatchContractError(f"{team.club_code}: escalação incompleta ({len(team.starters)} de {len(slots)} titulares).")
    if [p.slot_position for p in team.starters] != [s.position for s in slots]:
        raise MatchContractError(f"{team.club_code}: posições dos titulares não correspondem à formação {team.formation_code}.")
    if sum(1 for p in team.starters if p.slot_position == "GK") != 1:
        raise MatchContractError(f"{team.club_code}: é preciso exatamente um goleiro titular.")
    if not all(p.is_starter for p in team.starters) or any(p.is_starter for p in team.bench):
        raise MatchContractError(f"{team.club_code}: titulares e reservas marcados de forma inconsistente.")
    if len(team.bench) > MAX_BENCH:
        raise MatchContractError(f"{team.club_code}: no máximo {MAX_BENCH} reservas.")
    for player in team.starters:
        if player.player_id not in team.instructions and team.instructions:
            raise MatchContractError(f"{team.club_code}: titular {player.player_id} sem instrução individual.")


def _player(row: dict[str, object], starter: bool) -> MatchPlayer:
    attributes = {str(k): int(v) for k, v in dict(row.get("attributes") or {}).items()}
    return MatchPlayer(
        player_id=str(row["id"]), name=str(row["name"]), natural_position=str(row["position"]),
        slot_position=str(row["slot_position"]), slot_x=float(row["slot_x"]), slot_y=float(row["slot_y"]),
        shirt_number=int(row.get("number", 0)), is_starter=starter,
        stats=PlayerStats(overall=int(row["overall"]), attributes=attributes, provenance="CATALOG" if attributes else "OVERALL_ONLY"))


def _team(side: str, view: dict[str, object]) -> MatchTeam:
    tactics = {str(k): str(v) for k, v in dict(view.get("tactics") or {}).items()}
    return MatchTeam(
        side=side, club_code=str(view["club_code"]), formation_code=str(view["formation_code"]),
        starters=tuple(_player(r, True) for r in view["starters"]), bench=tuple(_player(r, False) for r in view.get("bench", ())),
        tactics=tactics, instructions={str(k): str(v) for k, v in dict(view.get("instructions") or {}).items()})


def build_match_payload(match_id: str, mode: str, home_view: dict[str, object], away_view: dict[str, object], *,
                        seed: int, competition: str = "LEAGUE") -> MatchPayload:
    """MatchPayload from the season's frozen team snapshots (`team_input_view` rows)."""
    if mode not in MODES:
        raise MatchContractError(f"Modo de partida desconhecido: {mode}.")
    try:
        draft = MatchPayload(match_id=match_id, mode=mode, competition=competition, seed=int(seed),
                             home=_team("HOME", home_view), away=_team("AWAY", away_view),
                             provenance={"source": "season.matches.inputs", "frozen_at": "round start",
                                         "attributes": "catalog values shifted by career progression and condition; none derived"})
    except ValidationError as error:
        first = error.errors()[0]
        raise MatchContractError(str(first.get("msg", "")).removeprefix("Value error, ")) from error
    return draft.model_copy(update={"checksum": payload_checksum(draft)})
