"""Deterministic Brasileirão calendar and standings rules, independent from HTTP."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Fixture:
    id: str
    round_number: int
    home: str
    away: str


@dataclass(frozen=True)
class MatchResult:
    fixture_id: str
    home_goals: int
    away_goals: int


@dataclass
class Standing:
    club_code: str
    played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0
    points: int = 0

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against

    @property
    def percentage(self) -> float:
        return 0.0 if not self.played else round((self.points / (self.played * 3)) * 100, 2)

    def view(self, position: int) -> dict[str, object]:
        return {"position": position, "club_code": self.club_code, "points": self.points, "played": self.played, "wins": self.wins, "draws": self.draws, "losses": self.losses, "goals_for": self.goals_for, "goals_against": self.goals_against, "goal_difference": self.goal_difference, "percentage": self.percentage}


def generate_calendar(clubs: list[str] | tuple[str, ...]) -> list[Fixture]:
    """Circle method: 20 clubs -> 38 rounds, each pair home and away exactly once."""
    if len(clubs) != 20 or len(set(clubs)) != 20:
        raise ValueError("O Brasileirão exige exatamente 20 clubes distintos.")
    rotating = list(clubs)
    first_half: list[list[tuple[str, str]]] = []
    for round_index in range(19):
        games: list[tuple[str, str]] = []
        for index in range(10):
            left, right = rotating[index], rotating[-(index + 1)]
            games.append((left, right) if (round_index + index) % 2 == 0 else (right, left))
        first_half.append(games)
        rotating = [rotating[0], rotating[-1], *rotating[1:-1]]
    fixtures: list[Fixture] = []
    for round_index, games in enumerate(first_half, start=1):
        fixtures.extend(Fixture(f"r{round_index}-{game_index}", round_index, home, away) for game_index, (home, away) in enumerate(games, start=1))
    for round_index, games in enumerate(first_half, start=20):
        fixtures.extend(Fixture(f"r{round_index}-{game_index}", round_index, away, home) for game_index, (home, away) in enumerate(games, start=1))
    return fixtures


def standings(clubs: list[str] | tuple[str, ...], fixtures: list[Fixture], results: dict[str, MatchResult]) -> list[dict[str, object]]:
    table = {club: Standing(club) for club in clubs}
    fixture_by_id = {fixture.id: fixture for fixture in fixtures}
    for fixture_id, result in results.items():
        fixture = fixture_by_id.get(fixture_id)
        if not fixture:
            raise ValueError("Resultado referencia partida inexistente.")
        if result.home_goals < 0 or result.away_goals < 0:
            raise ValueError("Placar inválido.")
        home, away = table[fixture.home], table[fixture.away]
        home.played += 1
        away.played += 1
        home.goals_for += result.home_goals
        home.goals_against += result.away_goals
        away.goals_for += result.away_goals
        away.goals_against += result.home_goals
        if result.home_goals > result.away_goals:
            home.wins += 1
            away.losses += 1
            home.points += 3
        elif result.home_goals < result.away_goals:
            away.wins += 1
            home.losses += 1
            away.points += 3
        else:
            home.draws += 1
            away.draws += 1
            home.points += 1
            away.points += 1
    ordered = sorted(table.values(), key=lambda item: (-item.points, -item.wins, -item.goal_difference, -item.goals_for, item.club_code))
    return [item.view(position) for position, item in enumerate(ordered, start=1)]


@dataclass
class SeasonState:
    fixtures: list[Fixture]
    results: dict[str, MatchResult] = field(default_factory=dict)

    def record(self, result: MatchResult) -> None:
        if result.fixture_id in self.results:
            if self.results[result.fixture_id] != result:
                raise ValueError("Resultado de partida finalizada é imutável.")
            return
        if result.fixture_id not in {fixture.id for fixture in self.fixtures}:
            raise ValueError("Partida inexistente.")
        self.results[result.fixture_id] = result
