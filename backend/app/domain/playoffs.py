"""Deterministic single-leg knockout bracket and penalty shootouts."""

from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass(frozen=True)
class KnockoutMatch:
    id: str
    stage: str
    home: str
    away: str
    home_goals: int
    away_goals: int
    winner: str
    home_penalties: int | None = None
    away_penalties: int | None = None
    penalty_kicks: tuple[dict[str, object], ...] = ()


@dataclass
class PlayoffState:
    qualifiers: tuple[str, ...]
    quarterfinals: list[KnockoutMatch] = field(default_factory=list)
    semifinals: list[KnockoutMatch] = field(default_factory=list)
    final: KnockoutMatch | None = None
    champion: str | None = None
    next_stage: str = "QUARTERFINALS"

    def view(self) -> dict[str, object]:
        return {
            "qualifiers": list(self.qualifiers),
            "quarterfinals": [_match_view(match) for match in self.quarterfinals],
            "semifinals": [_match_view(match) for match in self.semifinals],
            "final": _match_view(self.final) if self.final else None,
            "champion": self.champion,
            "next_stage": self.next_stage,
        }


def create_bracket(table: list[dict[str, object]]) -> PlayoffState:
    if len(table) < 8:
        raise ValueError("Os playoffs exigem ao menos oito clubes classificados.")
    qualifiers = tuple(str(row["club_code"]) for row in table[:8])
    if len(set(qualifiers)) != 8:
        raise ValueError("Classificação contém clubes duplicados.")
    return PlayoffState(qualifiers)


def quarterfinal_pairings(state: PlayoffState) -> tuple[tuple[str, str], ...]:
    first, second, third, fourth, fifth, sixth, seventh, eighth = state.qualifiers
    return ((first, eighth), (fourth, fifth), (second, seventh), (third, sixth))


def semifinal_pairings(state: PlayoffState) -> tuple[tuple[str, str], tuple[str, str]]:
    if len(state.quarterfinals) != 4:
        raise ValueError("As quartas precisam terminar antes das semifinais.")
    return ((state.quarterfinals[0].winner, state.quarterfinals[1].winner), (state.quarterfinals[2].winner, state.quarterfinals[3].winner))


def resolve_penalties(home: str, away: str, home_ratings: tuple[int, ...], away_ratings: tuple[int, ...], seed: int) -> tuple[str, int, int, tuple[dict[str, object], ...]]:
    rng = random.Random(seed)
    kicks: list[dict[str, object]] = []
    scores = {home: 0, away: 0}
    teams = ((home, home_ratings), (away, away_ratings))
    for round_number in range(1, 6):
        for team, ratings in teams:
            rating = ratings[(round_number - 1) % len(ratings)] if ratings else 70
            scored = rng.random() < min(.88, max(.42, .68 + (rating - 70) * .006))
            if scored:
                scores[team] += 1
            kicks.append({"round": round_number, "team": team, "scored": scored, "shooter_rating": rating})
        remaining = 5 - round_number
        if abs(scores[home] - scores[away]) > remaining:
            break
    sudden_round = 6
    while scores[home] == scores[away] and sudden_round <= 20:
        for team, ratings in teams:
            rating = ratings[(sudden_round - 1) % len(ratings)] if ratings else 70
            scored = rng.random() < min(.88, max(.42, .68 + (rating - 70) * .006))
            if scored:
                scores[team] += 1
            kicks.append({"round": sudden_round, "team": team, "scored": scored, "shooter_rating": rating})
        sudden_round += 1
    winner = home if scores[home] > scores[away] else away
    return winner, scores[home], scores[away], tuple(kicks)


def _match_view(match: KnockoutMatch) -> dict[str, object]:
    return {"id": match.id, "stage": match.stage, "home": match.home, "away": match.away, "home_goals": match.home_goals, "away_goals": match.away_goals, "winner": match.winner, "home_penalties": match.home_penalties, "away_penalties": match.away_penalties, "penalty_kicks": list(match.penalty_kicks)}
