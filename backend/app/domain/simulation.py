"""Deterministic event-based football simulation using only supplied player data."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace

STRATEGIES = {
    "BALANCED": "Equilibrada",
    "ATTACKING": "Ofensiva",
    "DEFENSIVE": "Defensiva",
    "COUNTER": "Contra-ataque",
    "POSSESSION": "Posse de bola",
    "HIGH_PRESS": "Pressão alta",
}


@dataclass(frozen=True)
class TeamStrength:
    club_code: str
    attack: float
    midfield: float
    defense: float
    goalkeeper: float
    positional_fit: float = 1.0
    tactic: float = 0.0
    form: float = 0.0
    strategy: str = "BALANCED"
    player_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MatchEvent:
    event_id: str
    match_id: str
    kind: str
    team: str | None
    minute: int
    animation_ms: int
    x: float
    y: float
    outcome: str = ""
    player_id: str | None = None
    participant_ids: tuple[str, ...] = ()
    xg: float = 0.0


@dataclass(frozen=True)
class SimulationResult:
    home_goals: int
    away_goals: int
    home_xg: float
    away_xg: float
    events: tuple[MatchEvent, ...]
    home_win_probability: float = 0.0
    draw_probability: float = 0.0
    away_win_probability: float = 0.0
    statistics: dict[str, dict[str, int]] = field(default_factory=dict)


def _tactical_edges(home: TeamStrength, away: TeamStrength) -> tuple[float, float]:
    """Bounded matchup effects: every plan pays a cost and has a counter-plan."""
    attack_bonus = {"BALANCED": .0, "ATTACKING": .11, "DEFENSIVE": -.15, "COUNTER": -.01, "POSSESSION": .02, "HIGH_PRESS": .05}
    defense_bonus = {"BALANCED": .0, "ATTACKING": -.12, "DEFENSIVE": .13, "COUNTER": .02, "POSSESSION": -.02, "HIGH_PRESS": -.09}
    home_attack = attack_bonus.get(home.strategy, 0.0)
    away_attack = attack_bonus.get(away.strategy, 0.0)
    home_defense = defense_bonus.get(home.strategy, 0.0)
    away_defense = defense_bonus.get(away.strategy, 0.0)
    # Counter attacks gain space against an attacking/high-press opponent.
    if home.strategy == "COUNTER" and away.strategy in {"ATTACKING", "HIGH_PRESS"}:
        home_attack += .10
    if away.strategy == "COUNTER" and home.strategy in {"ATTACKING", "HIGH_PRESS"}:
        away_attack += .10
    return home_attack - away_defense, away_attack - home_defense


def expected_goals(home: TeamStrength, away: TeamStrength, mode: str) -> tuple[float, float]:
    individual_weight = 0.70 if mode == "FIVE_A_SIDE" else 0.65
    home_delta = individual_weight * ((home.attack + home.midfield / 2) - (away.defense + away.goalkeeper / 2)) / 100
    away_delta = individual_weight * ((away.attack + away.midfield / 2) - (home.defense + home.goalkeeper / 2)) / 100
    home_tactic, away_tactic = _tactical_edges(home, away)
    home_factor = home_delta + .15 * (home.positional_fit - away.positional_fit) + .10 * (home.tactic - away.tactic) + .05 * (home.form - away.form) + home_tactic + (.05 if mode == "ELEVEN_A_SIDE" else 0)
    away_factor = away_delta + .15 * (away.positional_fit - home.positional_fit) + .10 * (away.tactic - home.tactic) + .05 * (away.form - home.form) + away_tactic
    base = 1.45 if mode == "ELEVEN_A_SIDE" else 2.75
    return tuple(round(max(.15, min(4.5, base * math.exp(factor))), 3) for factor in (home_factor, away_factor))


def outcome_probabilities(home_xg: float, away_xg: float) -> tuple[float, float, float]:
    """Compute 1-X-2 from independent Poisson score distributions."""
    def distribution(lam: float) -> list[float]:
        probs = [math.exp(-lam)]
        for goals in range(1, 13):
            probs.append(probs[-1] * lam / goals)
        return probs
    home, away = distribution(home_xg), distribution(away_xg)
    home_win = draw = away_win = 0.0
    for h, hp in enumerate(home):
        for a, ap in enumerate(away):
            if h > a:
                home_win += hp * ap
            elif h == a:
                draw += hp * ap
            else:
                away_win += hp * ap
    total = home_win + draw + away_win
    return home_win / total, draw / total, away_win / total


def _poisson(lam: float, rng: random.Random) -> int:
    threshold, product, count = math.exp(-lam), 1.0, 0
    while product > threshold:
        count += 1
        product *= rng.random()
    return count - 1


def simulate(
    home: TeamStrength,
    away: TeamStrength,
    mode: str,
    seed: int,
    home_scorers: tuple[str, ...] = (),
    away_scorers: tuple[str, ...] = (),
    match_id: str = "match",
) -> SimulationResult:
    """Generate possessions first; score and statistics are projections of those events."""
    home_xg, away_xg = expected_goals(home, away, mode)
    p_home, p_draw, p_away = outcome_probabilities(home_xg, away_xg)
    rng = random.Random(seed)
    events: list[MatchEvent] = []
    stats = {home.club_code: {key: 0 for key in ("shots", "shots_on_target", "possession", "passes", "goals", "corners", "saves", "tackles", "fouls", "cards")}, away.club_code: {key: 0 for key in ("shots", "shots_on_target", "possession", "passes", "goals", "corners", "saves", "tackles", "fouls", "cards")}}
    home_goals = away_goals = 0
    sequence = 0
    simulated_xg = {home.club_code: 0.0, away.club_code: 0.0}

    def emit(kind: str, team: str | None, minute: int, x: float, y: float, outcome: str = "", player: str | None = None, participants: tuple[str, ...] = (), xg: float = 0.0) -> None:
        nonlocal sequence
        sequence += 1
        if kind in {"FOUL", "CARD"} and team in stats:
            stats[team]["fouls" if kind == "FOUL" else "cards"] += 1
        events.append(MatchEvent(f"{match_id}:{sequence:05d}", match_id, kind, team, minute, minute * 1000, round(min(1, max(0, x)), 4), round(min(1, max(0, y)), 4), outcome, player, participants, round(xg, 4)))

    emit("MATCH_START", None, 0, .5, .5)
    # The shot volume is tied to expected goals; each generated shot has a calibrated
    # conversion probability, so no score is pre-drawn or added after the event stream.
    for minute in range(1, 91):
        attacking_home = rng.random() < .5
        attack, defend = (home, away) if attacking_home else (away, home)
        team_code = attack.club_code
        player_pool = home_scorers if attacking_home else away_scorers
        if not player_pool:
            player_pool = attack.player_ids
        opponent_pool = away.player_ids if attacking_home else home.player_ids
        stats[team_code]["possession"] += 1
        direction = 1 if attacking_home else -1
        x, y = (.08 if attacking_home else .92), rng.uniform(.18, .82)
        emit("POSSESSION", team_code, minute, x, y, "START")
        passes = 1 + rng.randrange(4)
        failed = False
        for _ in range(passes):
            passer = rng.choice(player_pool) if player_pool else None
            receiver = rng.choice(player_pool) if player_pool else None
            success = rng.random() < min(.92, max(.45, .70 + (attack.midfield - 70) / 180 + (.05 if attack.strategy == "POSSESSION" else 0)))
            x = min(.92, max(.08, x + direction * rng.uniform(.03, .13)))
            y = min(.9, max(.1, y + rng.uniform(-.12, .12)))
            if success:
                stats[team_code]["passes"] += 1
                emit("PASS", team_code, minute, x, y, "COMPLETE", passer, tuple(filter(None, (passer, receiver))))
                emit("RECEPTION", team_code, minute, x, y, "CONTROLLED", receiver)
            else:
                failed = True
                stats[defend.club_code]["tackles"] += 1
                defender = rng.choice(opponent_pool) if opponent_pool else None
                emit("INTERCEPTION", defend.club_code, minute, x, y, "POSSESSION_WON", defender, tuple(filter(None, (passer, defender))))
                emit("TACKLE", defend.club_code, minute, x, y, "CLEAN", defender)
                break
        if failed:
            continue
        # Attack plan and relative quality determine the chance to shoot; xG per shot
        # derives from that team's expected goals, so the event flow remains reconcilable.
        lam = home_xg if attacking_home else away_xg
        shot_chance = min(.58, max(.12, lam / 31 + .18 + (.08 if attack.strategy == "ATTACKING" else 0) + (.04 if attack.strategy == "HIGH_PRESS" else 0)))
        if rng.random() < shot_chance:
            shot_player = rng.choice(player_pool) if player_pool else None
            stats[team_code]["shots"] += 1
            shot_x = .96 if attacking_home else .04
            shot_xg = min(.6, max(.025, lam / max(1.0, 45 * shot_chance)))
            simulated_xg[team_code] += round(shot_xg, 4)
            on_target_probability = min(.78, max(.42, .58 + (attack.attack - 70) / 250))
            if rng.random() < on_target_probability:
                stats[team_code]["shots_on_target"] += 1
                emit("SHOT", team_code, minute, shot_x, y, "ON_TARGET", shot_player, xg=shot_xg)
                if rng.random() < min(.9, shot_xg / on_target_probability):
                    if attacking_home:
                        home_goals += 1
                    else:
                        away_goals += 1
                    stats[team_code]["goals"] += 1
                    emit("GOAL", team_code, minute, shot_x, y, "SCORED", shot_player)
                else:
                    stats[defend.club_code]["saves"] += 1
                    keeper = next(iter(opponent_pool), None)
                    emit("SAVE", defend.club_code, minute, shot_x, y, "SAVED", keeper, tuple(filter(None, (shot_player, keeper))))
                    if rng.random() < .12:
                        stats[team_code]["corners"] += 1
                        emit("CORNER", team_code, minute, .94 if attacking_home else .06, y, "AWARDED")
            else:
                emit("SHOT", team_code, minute, shot_x, y, "OFF_TARGET", shot_player, xg=shot_xg)
                if rng.random() < .08:
                    stats[team_code]["corners"] += 1
                    emit("CORNER", team_code, minute, .94 if attacking_home else .06, y, "AWARDED")
        elif rng.random() < .025:
            emit("FOUL", defend.club_code, minute, x, y, "FREE_KICK")
            if rng.random() < .08:
                emit("CARD", defend.club_code, minute, x, y, "YELLOW")
        elif rng.random() < .04:
            emit("RESTART", team_code, minute, x, y, "THROW_IN")
        else:
            emit("CARRY", team_code, minute, x, y, "ADVANCE", rng.choice(player_pool) if player_pool else None)
    emit("MATCH_END", None, 90, .5, .5)
    # Preserve causal order within a minute rather than releasing an entire
    # possession in a single frame. A 90,000 ms replay maps to 60 real seconds.
    minute_indices: dict[int, list[int]] = {}
    for index, event in enumerate(events):
        if event.kind not in {"MATCH_START", "MATCH_END"}:
            minute_indices.setdefault(event.minute, []).append(index)
    for minute, indices in minute_indices.items():
        for offset, index in enumerate(indices):
            events[index] = replace(events[index], animation_ms=(minute - 1) * 1000 +
                                    round((offset + 1) * 1000 / (len(indices) + 1)))
    # Derive xG and all outcomes from the actual shots in the event stream.
    return SimulationResult(home_goals, away_goals, round(simulated_xg[home.club_code], 3), round(simulated_xg[away.club_code], 3), tuple(events), p_home, p_draw, p_away, stats)
