"""Knockout competitions played live: Brasileirão playoffs and the optional Copa do Brasil.

Every knockout match is an ordinary live match (same engine, broadcast and tactical
control). This module only holds the competition rules:

* **Ties** — one match, or two legs with an aggregate score (no away-goals rule);
  a level tie goes to the existing automatic penalty shoot-out.
* **Draws** — done once on the server from a seed derived from (room, season,
  stage); the result is stored and replayed to every client for the ceremony. The
  client never chooses a pairing.
* **Playoffs** — the top eight. Pot 1 = 1st–4th, Pot 2 = 5th–8th; each Pot 1 club is
  drawn against a Pot 2 club. The semi-final path follows the draw order (QF1 winner
  v QF2 winner, QF3 v QF4). The better league position hosts the single match / the
  second leg.
* **Copa do Brasil** (20 clubs) — a preliminary round between the eight lowest seeds
  (4 ties, single match), then an open round of 16 with pots (seeds 1–8 v the other
  eight), quarter-finals, semi-finals and final, single matches. Seeds: the previous
  season's final table; in the first season, squad strength (mean of the best
  starting ratings) — documented in docs/COMPETICOES.md. Higher seed hosts.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field

PLAYOFF_STAGES = ("QF", "SF", "FINAL")
CUP_STAGES = ("PRELIM", "R16", "QF", "SF", "FINAL")
STAGE_NAMES = {"PRELIM": "Fase preliminar", "R16": "Oitavas de final", "QF": "Quartas de final",
               "SF": "Semifinal", "FINAL": "Final"}
COMPETITION_NAMES = {"PLAYOFF": "Playoffs do Brasileirão", "CUP": "Copa do Brasil"}
# When each Copa stage is played, as a share of the league rounds already completed.
CUP_SCHEDULE = {"PRELIM": 0.08, "R16": 0.18, "QF": 0.32, "SF": 0.47, "FINAL": 0.66}

# Cumulative playoff prizes (cents): reach QF 50 mi; SF +100 mi; runner-up +150 mi;
# champion +200 mi  →  runner-up total 300 mi, champion total 350 mi.
PLAYOFF_PRIZES = {"QF": 5_000_000_000, "SF": 10_000_000_000, "RUNNER_UP": 15_000_000_000, "CHAMPION": 20_000_000_000}


@dataclass
class Tie:
    id: str
    competition: str
    stage: str
    high: str            # better seed: hosts the single match or the second leg
    low: str
    legs: int
    order: int           # position in the draw (drives the bracket path)
    leg_scores: list[list[int]] = field(default_factory=list)   # per leg: [high goals, low goals]
    penalties: list[int] | None = None                          # [high, low]
    penalty_kicks: list[dict[str, object]] = field(default_factory=list)
    winner: str | None = None

    def match_id(self, leg: int) -> str:
        return f"{self.id}-l{leg}" if self.legs == 2 else self.id

    def fixture(self, leg: int) -> tuple[str, str]:
        """(home, away) of a leg: the lower seed hosts the first of two legs."""
        if self.legs == 2 and leg == 1:
            return self.low, self.high
        return self.high, self.low

    def aggregate(self) -> tuple[int, int]:
        return sum(s[0] for s in self.leg_scores), sum(s[1] for s in self.leg_scores)

    @property
    def complete(self) -> bool:
        return self.winner is not None

    def record_leg(self, leg: int, home_goals: int, away_goals: int) -> None:
        if len(self.leg_scores) >= leg:
            return  # idempotent: a leg is recorded once
        if len(self.leg_scores) != leg - 1:
            raise ValueError("As partidas do confronto precisam ser registradas em ordem.")
        home, _ = self.fixture(leg)
        self.leg_scores.append([home_goals, away_goals] if home == self.high else [away_goals, home_goals])

    def view(self) -> dict[str, object]:
        high, low = self.aggregate()
        return {**asdict(self), "aggregate": [high, low], "stage_name": STAGE_NAMES[self.stage],
                "match_ids": [self.match_id(leg) for leg in range(1, self.legs + 1)],
                "fixtures": [list(self.fixture(leg)) for leg in range(1, self.legs + 1)]}


@dataclass
class KnockoutRound:
    """One live round of a knockout competition (all ties of a stage, one leg)."""
    id: str
    competition: str
    stage: str
    leg: int
    after_round: int         # played once this many league rounds are complete
    tie_ids: list[str]
    status: str = "PENDING"  # PENDING -> DONE

    def view(self) -> dict[str, object]:
        return {**asdict(self), "stage_name": STAGE_NAMES[self.stage], "competition_name": COMPETITION_NAMES[self.competition]}


@dataclass
class KnockoutState:
    ties: dict[str, Tie] = field(default_factory=dict)
    rounds: list[KnockoutRound] = field(default_factory=list)
    draws: list[dict[str, object]] = field(default_factory=list)
    cup_enabled: bool = False
    cup_seeds: list[str] = field(default_factory=list)
    cup_champion: str | None = None
    cup_runner_up: str | None = None
    playoff_runner_up: str | None = None

    def view(self) -> dict[str, object]:
        return {"ties": {key: tie.view() for key, tie in self.ties.items()},
                "rounds": [r.view() for r in self.rounds], "draws": self.draws,
                "cup_enabled": self.cup_enabled, "cup_seeds": self.cup_seeds,
                "cup_champion": self.cup_champion, "cup_runner_up": self.cup_runner_up,
                "playoff_runner_up": self.playoff_runner_up}

    def to_dict(self) -> dict[str, object]:
        return {"ties": {key: asdict(tie) for key, tie in self.ties.items()}, "rounds": [asdict(r) for r in self.rounds],
                "draws": self.draws, "cup_enabled": self.cup_enabled, "cup_seeds": self.cup_seeds,
                "cup_champion": self.cup_champion, "cup_runner_up": self.cup_runner_up,
                "playoff_runner_up": self.playoff_runner_up}

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> KnockoutState:
        state = cls(cup_enabled=bool(raw.get("cup_enabled", False)), cup_seeds=list(map(str, raw.get("cup_seeds", []))),
                    cup_champion=raw.get("cup_champion"), cup_runner_up=raw.get("cup_runner_up"),
                    playoff_runner_up=raw.get("playoff_runner_up"), draws=list(raw.get("draws", [])))
        for key, value in dict(raw.get("ties", {})).items():
            tie = Tie(**{k: v for k, v in dict(value).items()})
            if tie.legs not in (1, 2) or tie.competition not in COMPETITION_NAMES or tie.stage not in STAGE_NAMES:
                raise ValueError("Snapshot contém confronto de mata-mata inválido.")
            state.ties[str(key)] = tie
        for value in raw.get("rounds", []):
            knockout_round = KnockoutRound(**dict(value))
            if not set(knockout_round.tie_ids).issubset(state.ties):
                raise ValueError("Snapshot contém rodada de mata-mata sem confronto.")
            state.rounds.append(knockout_round)
        return state

    # ------------------------------------------------------------------ queries
    def stage_ties(self, competition: str, stage: str) -> list[Tie]:
        return sorted((t for t in self.ties.values() if t.competition == competition and t.stage == stage), key=lambda t: t.order)

    def due_round(self, completed_league_rounds: int, league_finished: bool) -> KnockoutRound | None:
        for knockout_round in self.rounds:
            if knockout_round.status != "PENDING":
                continue
            if knockout_round.competition == "PLAYOFF" and not league_finished:
                continue
            if knockout_round.after_round <= completed_league_rounds:
                return knockout_round
        return None

    def pending(self, competition: str) -> bool:
        return any(r.status == "PENDING" and r.competition == competition for r in self.rounds)


# ---------------------------------------------------------------------- draws
def _rng(seed_text: str) -> random.Random:
    import zlib
    return random.Random(zlib.crc32(seed_text.encode()))


def pot_draw(seed_text: str, pot1: list[str], pot2: list[str]) -> list[tuple[str, str]]:
    """Each club of pot 1 (in order) gets a random club of pot 2."""
    rng = _rng(seed_text)
    remaining = list(pot2)
    rng.shuffle(remaining)
    return list(zip(pot1, remaining, strict=True))


def open_draw(seed_text: str, clubs: list[str], seeds: list[str]) -> list[tuple[str, str]]:
    """Random pairs; inside a pair the better seed is listed first."""
    rng = _rng(seed_text)
    pool = list(clubs)
    rng.shuffle(pool)
    rank = {club: index for index, club in enumerate(seeds)}
    pairs = []
    for index in range(0, len(pool), 2):
        a, b = pool[index], pool[index + 1]
        pairs.append((a, b) if rank.get(a, 99) <= rank.get(b, 99) else (b, a))
    return pairs


def schedule_cup(state: KnockoutState, seeds: list[str], league_rounds: int) -> None:
    """Copa do Brasil for 20 clubs: preliminary round now, later stages drawn on the way."""
    if len(seeds) != 20:
        raise ValueError("A Copa do Brasil simplificada exige os 20 clubes.")
    state.cup_enabled = True
    state.cup_seeds = list(seeds)
    prelim = seeds[12:]  # the eight lowest seeds
    pairs = [(prelim[i], prelim[7 - i]) for i in range(4)]  # 13 v 20, 14 v 19, 15 v 18, 16 v 17
    add_stage(state, "CUP", "PRELIM", pairs, legs=1, after_round=cup_after_round("PRELIM", league_rounds),
              draw={"kind": "SEEDED", "rule": "13º x 20º, 14º x 19º, 15º x 18º, 16º x 17º (cabeças de chave)"})


def cup_after_round(stage: str, league_rounds: int) -> int:
    return max(1, round(CUP_SCHEDULE[stage] * league_rounds))


def add_stage(state: KnockoutState, competition: str, stage: str, pairs: list[tuple[str, str]], legs: int,
              after_round: int, draw: dict[str, object]) -> list[Tie]:
    prefix = "po" if competition == "PLAYOFF" else "cup"
    ties = []
    for order, (high, low) in enumerate(pairs, 1):
        tie = Tie(f"{prefix}-{stage.lower()}-{order}", competition, stage, high, low, legs, order)
        state.ties[tie.id] = tie
        ties.append(tie)
    for leg in range(1, legs + 1):
        state.rounds.append(KnockoutRound(f"{prefix}-{stage.lower()}-leg{leg}", competition, stage, leg, after_round,
                                          [t.id for t in ties]))
    state.draws.append({"competition": competition, "stage": stage, "stage_name": STAGE_NAMES[stage],
                        "pairs": [[t.high, t.low] for t in ties], **draw})
    return ties


def next_stage(stage: str, competition: str) -> str | None:
    stages = PLAYOFF_STAGES if competition == "PLAYOFF" else CUP_STAGES
    index = stages.index(stage)
    return stages[index + 1] if index + 1 < len(stages) else None
