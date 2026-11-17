"""Short competitions without a league: Draft Eliminatório, Pack & Play and Último Sobrevivente.

Pure rules (no I/O); the season service plays every match live with the same engine,
broadcast and tactical control as the career, and calls these functions under the
room lock. Everything is deterministic from the room seed and stored, so a refresh or
a reconnection never re-draws anything.

**Knockout tournament** (Draft Eliminatório, Pack & Play) — 4, 8 or 16 clubs, single
matches, penalties if level. The server draws the bracket once: pot 1 = the stronger
half by squad strength, pot 2 = the weaker half; each pot-1 club meets a pot-2 club.
The path follows the draw (winners of ties 1 and 2 meet, then 3 and 4, …).

**Último Sobrevivente** — 8, 12, 16 or 20 clubs. Every round the active clubs are
drawn into pairs and play one match. They are ranked by the round's
1. points (3 win, 1 draw), 2. goal difference, 3. goals scored, then by the whole run
4. points, 5. goal difference, 6. goals, and finally 7. a deterministic draw fixed
before the start (hash of room seed and club). The lowest-ranked are eliminated.
The number eliminated per round is always even, so the active field stays even and
nobody is ever left without an opponent. When two clubs remain they play a final
(penalties if level): the winner is the last survivor.
"""

from __future__ import annotations

import random
import zlib
from dataclasses import asdict, dataclass, field

TOURNAMENT_SIZES = (4, 8, 16)
SURVIVOR_SIZES = (8, 12, 16, 20)
SURVIVOR_ELIMINATIONS = (0, 2, 4)   # 0 = automatic (about a quarter of the field)
TOURNAMENT_STAGES = {4: ("SF", "FINAL"), 8: ("QF", "SF", "FINAL"), 16: ("R16", "QF", "SF", "FINAL")}


def _rng(text: str) -> random.Random:
    return random.Random(zlib.crc32(text.encode()))


def tournament_stages(size: int) -> tuple[str, ...]:
    if size not in TOURNAMENT_STAGES:
        raise ValueError("O torneio eliminatório aceita 4, 8 ou 16 clubes.")
    return TOURNAMENT_STAGES[size]


def first_round_pairs(seed_text: str, clubs_by_strength: list[str]) -> tuple[list[tuple[str, str]], dict[str, object]]:
    """Pot draw of the opening stage: stronger half against weaker half."""
    half = len(clubs_by_strength) // 2
    pot1, pot2 = list(clubs_by_strength[:half]), list(clubs_by_strength[half:])
    order = pot2[:]
    _rng(seed_text).shuffle(order)
    pairs = list(zip(pot1, order, strict=True))
    return pairs, {"kind": "POTS", "pot1": pot1, "pot2": pot2, "seed": seed_text}


def next_round_pairs(winners: list[str]) -> list[tuple[str, str]]:
    """The path follows the draw: winners of ties 1 & 2, 3 & 4… (better seed listed first)."""
    return [(winners[i], winners[i + 1]) for i in range(0, len(winners), 2)]


# ---------------------------------------------------------------------- survivor
def survivor_eliminations(active: int, configured: int) -> int:
    """How many clubs leave after this round (even, leaves at least two)."""
    if active <= 2:
        return 0
    wanted = configured or max(2, 2 * round(active * 0.25 / 2))
    wanted = max(2, wanted - wanted % 2)
    return min(wanted, active - 2)


def survivor_schedule(size: int, configured: int) -> list[int]:
    """Active clubs at the start of each round, down to the final (for the UI path)."""
    path, active = [size], size
    while active > 2:
        active -= survivor_eliminations(active, configured)
        path.append(active)
    return path


def tie_break(seed: str, club: str) -> int:
    return zlib.crc32(f"{seed}:{club}".encode())


@dataclass
class SurvivorRound:
    number: int
    pairs: list[list[str]]
    results: dict[str, list[int]] = field(default_factory=dict)   # "home|away" -> [hg, ag]
    table: list[dict[str, object]] = field(default_factory=list)
    eliminated: list[str] = field(default_factory=list)
    final: bool = False


@dataclass
class SurvivorState:
    seed: str
    clubs: list[str]
    configured: int = 0
    active: list[str] = field(default_factory=list)
    eliminated: list[dict[str, object]] = field(default_factory=list)   # {club, round, position}
    rounds: list[SurvivorRound] = field(default_factory=list)
    totals: dict[str, list[int]] = field(default_factory=dict)          # club -> [points, gf, ga]
    champion: str | None = None
    runner_up: str | None = None

    def __post_init__(self) -> None:
        if len(self.clubs) not in SURVIVOR_SIZES:
            raise ValueError("Último Sobrevivente começa com 8, 12, 16 ou 20 clubes.")
        if self.configured not in SURVIVOR_ELIMINATIONS:
            raise ValueError("Eliminações por rodada: automático, 2 ou 4.")
        if not self.active and not self.champion:
            self.active = list(self.clubs)
        for club in self.clubs:
            self.totals.setdefault(club, [0, 0, 0])

    @property
    def current(self) -> SurvivorRound | None:
        return self.rounds[-1] if self.rounds else None

    def draw_round(self) -> SurvivorRound:
        """Pairs for the next round (stored: drawing again returns the same round)."""
        if self.champion:
            raise ValueError("A competição já terminou.")
        if self.current and not self.current.table:
            return self.current
        number = len(self.rounds) + 1
        pool = sorted(self.active)
        _rng(f"{self.seed}:round:{number}").shuffle(pool)
        pairs = [[pool[i], pool[i + 1]] for i in range(0, len(pool), 2)]
        round_ = SurvivorRound(number, pairs, final=len(pool) == 2)
        self.rounds.append(round_)
        return round_

    def record(self, home: str, away: str, home_goals: int, away_goals: int) -> None:
        round_ = self.current
        if round_ is None or [home, away] not in round_.pairs:
            raise ValueError("Confronto fora da rodada atual.")
        key = f"{home}|{away}"
        if key in round_.results:
            return  # idempotent
        round_.results[key] = [int(home_goals), int(away_goals)]

    def complete_round(self, final_winner: str | None = None) -> list[str]:
        """Rank the round and eliminate (or crown the champion). Idempotent."""
        round_ = self.current
        if round_ is None or round_.table:
            return round_.eliminated if round_ else []
        if len(round_.results) != len(round_.pairs):
            raise ValueError("A rodada ainda tem partidas em andamento.")
        rows: dict[str, dict[str, int]] = {}
        for key, (hg, ag) in round_.results.items():
            home, away = key.split("|")
            for club, own, other in ((home, hg, ag), (away, ag, hg)):
                points = 3 if own > other else 1 if own == other else 0
                rows[club] = {"points": points, "gf": own, "ga": other}
                total = self.totals[club]
                total[0] += points
                total[1] += own
                total[2] += other
        def key(club: str) -> tuple:
            r, t = rows[club], self.totals[club]
            return (-r["points"], -(r["gf"] - r["ga"]), -r["gf"], -t[0], -(t[1] - t[2]), -t[1], tie_break(self.seed, club))
        ranked = sorted(rows, key=key)
        round_.table = [{"club_code": club, "position": i + 1, **rows[club], "gd": rows[club]["gf"] - rows[club]["ga"],
                         "total_points": self.totals[club][0], "total_gd": self.totals[club][1] - self.totals[club][2]}
                        for i, club in enumerate(ranked)]
        if round_.final:
            if final_winner not in ranked:
                raise ValueError("A final precisa de um vencedor (pênaltis em caso de empate).")
            self.champion = final_winner
            self.runner_up = next(c for c in ranked if c != final_winner)
            round_.eliminated = [self.runner_up]
            self.eliminated.append({"club": self.runner_up, "round": round_.number, "position": 2})
            self.active = [final_winner]
            return round_.eliminated
        count = survivor_eliminations(len(self.active), self.configured)
        out = ranked[len(ranked) - count:]
        round_.eliminated = out
        remaining = len(ranked) - count
        for offset, club in enumerate(reversed(out)):
            self.eliminated.append({"club": club, "round": round_.number, "position": len(ranked) - offset})
        self.active = [c for c in self.active if c not in out]
        return out if remaining else out

    def to_dict(self) -> dict[str, object]:
        return {**{k: v for k, v in asdict(self).items() if k != "rounds"}, "rounds": [asdict(r) for r in self.rounds]}

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> SurvivorState:
        state = cls(str(raw["seed"]), list(raw["clubs"]), int(raw.get("configured", 0)), list(raw.get("active", [])),  # type: ignore[arg-type]
                    list(raw.get("eliminated", [])), [], {str(k): list(v) for k, v in dict(raw.get("totals", {})).items()},  # type: ignore[arg-type]
                    raw.get("champion"), raw.get("runner_up"))  # type: ignore[arg-type]
        state.rounds = [SurvivorRound(**dict(r)) for r in raw.get("rounds", [])]  # type: ignore[arg-type]
        if not set(state.active) <= set(state.clubs) or len(state.active) % 2 and not state.champion:
            raise ValueError("Snapshot do Último Sobrevivente inválido.")
        return state

    def view(self) -> dict[str, object]:
        return {**self.to_dict(), "path": survivor_schedule(len(self.clubs), self.configured), "remaining": len(self.active)}
