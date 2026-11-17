"""Bot coaches: lineup choice, match plan and in-match decisions.

Bots read only what a human coach sees (score, minute, cards, the stamina shown on
the bench panel, the squad's ratings and the tactical-fit panel) and act exclusively
through the engine's public command API (`queue_tactics` / `queue_substitution` /
`queue_formation`), with the same limits.

Difficulty never grants overall, money or goals; it only changes decision quality:

* CASUAL — keeps the default plan, reacts every ten minutes, tired-legs subs only.
* COMPETITIVE (default) — picks the style its squad fits best, uses instructions,
  reacts every five minutes to score, cards and stamina.
* LEGENDARY — also reads the opponent (strength, style), changes shape late in the
  game and plans substitutions around the three windows.
"""

from __future__ import annotations

from app.domain.catalog import CatalogPlayer
from app.domain.cohesion import (
    INSTRUCTIONS,
    STYLE_WEIGHTS,
    cohesion_factor,
    compatibility,
    familiarity_of,
)
from app.domain.match_engine import FULL_TIME_TICK, Agent, MatchEngine
from app.domain.squad import FORMATION_LINES, effective_overall, formation_slots
from app.domain.tactics import Tactics

# Fixed decision checkpoints keep bot behaviour reproducible from the command log.
CHECKPOINT_TICKS = 300  # every five game minutes (half time = tick 2700 is one of them)
ORDER = ["VERY_DEFENSIVE", "DEFENSIVE", "BALANCED", "ATTACKING", "VERY_ATTACKING"]
DIFFICULTIES = ("CASUAL", "COMPETITIVE", "LEGENDARY")


def plan_match(rows: list[dict[str, object]], familiarity: dict[str, float], difficulty: str,
               own_strength: float, opponent_strength: float | None) -> tuple[Tactics, dict[str, str]]:
    """Pre-match plan of a bot: style, pressure, mentality and individual instructions.

    ``rows`` are the cohesion rows of the bot's starters (see cohesion.compatibility)."""
    if difficulty == "CASUAL" or not rows:
        return Tactics(), {}
    instructions: dict[str, str] = {}
    for row in rows:
        role = str(row["role"])
        options = INSTRUCTIONS[role]
        # The instruction whose demands best match the player's own profile.
        best = max(options, key=lambda code: _need_score(row["attributes"], options[code]["needs"]))
        instructions[str(row["player_id"])] = best
        row["instruction"] = best
    mentality = "BALANCED"
    if difficulty == "LEGENDARY" and opponent_strength is not None:
        gap = own_strength - opponent_strength
        mentality = "DEFENSIVE" if gap <= -4 else "ATTACKING" if gap >= 4 else "BALANCED"
    best: tuple[float, str, str] | None = None
    for style in STYLE_WEIGHTS:
        for pressure in ("LOW", "MEDIUM", "HIGH"):
            compat = float(compatibility(rows, style, pressure, mentality)["score"])
            value = cohesion_factor(compat, familiarity_of(familiarity, style))
            if difficulty == "LEGENDARY" and mentality == "DEFENSIVE" and style == "COUNTER":
                value += 0.03  # an underdog that can run makes the favourite pay on the break
            if best is None or value > best[0]:
                best = (value, style, pressure)
    assert best is not None
    return Tactics(mentality, best[2], best[1]), instructions


def _need_score(attrs: object, needs: object) -> float:
    if not needs:
        return 0.0
    weights = dict(needs)  # type: ignore[call-overload]
    values = dict(attrs)  # type: ignore[call-overload]
    overall_like = sum(values.get(k, 0.0) for k in ("pace", "passing", "shooting", "dribbling", "defending", "physical")) / 6
    return sum(values.get(k, 0.0) * w for k, w in weights.items()) / (sum(weights.values()) or 1.0) - overall_like


def choose_lineup(mode: str, roster: list[CatalogPlayer], overalls: dict[str, int]) -> tuple[str, dict[str, str]]:
    """Pick the formation and starters with the best total effective overall."""
    best: tuple[float, str, dict[str, str]] | None = None
    for code in FORMATION_LINES[mode]:
        slots = formation_slots(mode, code)
        available = sorted(roster, key=lambda p: -overalls.get(p.id, p.overall))
        assignments: dict[str, str] = {}
        total = 0.0
        # Fill the scarcest positions first so a natural fit is not wasted elsewhere.
        for slot in sorted(slots, key=lambda s: {"GK": 0, "ST": 1, "DF": 2, "MF": 3}[s.position]):
            natural = [p for p in available if slot.position in (p.position, *p.secondary_positions)]
            pool = natural or ([p for p in available if p.position != "GK"] if slot.position != "GK" else available)
            if not pool:
                break
            pick = max(pool, key=lambda p: effective_overall(p.model_copy(update={"overall": overalls.get(p.id, p.overall)}), slot.position)[0])
            assignments[slot.id] = pick.id
            total += effective_overall(pick.model_copy(update={"overall": overalls.get(pick.id, pick.overall)}), slot.position)[0]
            available.remove(pick)
        if len(assignments) != len(slots):
            continue
        if slots and slots[0].position == "GK" and next(p for p in roster if p.id == assignments["gk"]).position != "GK":
            total -= 40  # only as a last resort
        if best is None or total > best[0]:
            best = (total, code, assignments)
    if best is None:
        raise ValueError("Elenco sem atletas suficientes para formar o time titular.")
    return best[1], best[2]


def _shift(mentality: str, steps: int) -> str:
    return ORDER[max(0, min(len(ORDER) - 1, ORDER.index(mentality) + steps))]


def decide(engine: MatchEngine, side: int, baseline: Tactics, command_prefix: str,
           difficulty: str = "COMPETITIVE") -> list[dict[str, object]]:
    """Run at a checkpoint tick; returns the commands issued (already queued)."""
    issued: list[dict[str, object]] = []
    if engine.finished:
        return issued
    if difficulty == "CASUAL" and engine.tick % (CHECKPOINT_TICKS * 2):
        return issued  # a casual coach looks at the game half as often
    minute = engine.tick / 60
    diff = engine.score[side] - engine.score[1 - side]
    mine = engine.active(side)
    theirs = engine.active(1 - side)
    stamina = sum(a.stamina for a in mine) / max(1, len(mine))
    numbers = len(mine) - len(theirs)
    stronger = sum(a.overall for a in mine) / max(1, len(mine)) >= sum(a.overall for a in theirs) / max(1, len(theirs))

    mentality, pressure, style = baseline.mentality, baseline.pressure, baseline.style
    if diff < 0:
        if minute >= 75:
            mentality, style = _shift(baseline.mentality, 2), "DIRECT"
            pressure = "HIGH"
        elif minute >= 55 or diff <= -2:
            mentality = _shift(baseline.mentality, 1)
            pressure = "HIGH" if stamina > 0.7 else "MEDIUM"
    elif diff > 0:
        if minute >= 70 or diff >= 2:
            mentality, style = _shift(baseline.mentality, -1), "COUNTER"
            pressure = "LOW" if minute >= 80 else "MEDIUM"
    elif minute >= 70 and stronger:
        mentality = _shift(baseline.mentality, 1)
    if numbers < 0:  # a man down: compact and save legs
        mentality, pressure = _shift(mentality, -1), "LOW"
    elif numbers > 0:
        mentality, pressure = _shift(mentality, 1), "HIGH" if stamina > 0.65 else pressure
    if stamina < 0.62 and pressure == "HIGH":
        pressure = "MEDIUM"
    if difficulty == "CASUAL":
        pressure, style = baseline.pressure, baseline.style  # only the mentality moves
    wanted = Tactics(mentality, pressure, style)
    if wanted != engine.tactics[side]:
        command_id = f"{command_prefix}:t{engine.tick}"
        issued.append(engine.queue_tactics(side, wanted, command_id))

    if difficulty == "LEGENDARY":
        issued.extend(_shape(engine, side, minute, diff, command_prefix))
    issued.extend(_substitutions(engine, side, minute, diff, command_prefix, difficulty))
    return issued


def _shape(engine: MatchEngine, side: int, minute: float, diff: int, prefix: str) -> list[dict[str, object]]:
    """Late change of formation: more strikers when chasing, a back five when protecting."""
    if engine.mode != "ELEVEN_A_SIDE" or minute < 65 or len(engine.active(side)) < 10:
        return []
    current = engine.formation_codes[side]
    wanted = current
    if diff < 0:
        wanted = "4-2-3-1" if minute < 78 else "3-4-3"
    elif diff > 0 and minute >= 75:
        wanted = "5-4-1" if diff == 1 else "5-3-2"
    if wanted == current:
        return []
    return [engine.queue_formation(side, wanted, f"{prefix}:f{engine.tick}")]


def _substitutions(engine: MatchEngine, side: int, minute: float, diff: int, prefix: str,
                   difficulty: str = "COMPETITIVE") -> list[dict[str, object]]:
    issued: list[dict[str, object]] = []
    halftime = engine.phase == "HALF_TIME"
    if minute < 45 and not halftime:
        return issued
    if difficulty == "LEGENDARY" and engine.windows_used[side] >= 2 and minute < 75:
        return issued  # keep the last window for the final quarter of an hour
    bench = [a for a in engine.team_agents[side] if not a.active and a.entered_tick is None and not a.sent_off]
    if not bench:
        return issued
    candidates: list[tuple[float, Agent, Agent]] = []
    for player in engine.active(side):
        if player.role == "GK" and player.position == "GK":
            continue
        reason = 0.0
        if player.stamina < 0.66 and minute >= 55:
            reason += (0.66 - player.stamina) * 10
        if player.yellow and player.role in ("DF", "MF") and minute >= 60:
            reason += 0.8
        if diff < 0 and minute >= 60 and player.role == "DF" and difficulty != "CASUAL":
            reason += 0.4  # chasing: trade a defender for an attacker
        if difficulty == "LEGENDARY" and player.stamina < 0.72 and minute >= 50:
            reason += (0.72 - player.stamina) * 6  # fresh legs before the drop-off shows
        if reason <= 0:
            continue
        wanted_role = "ST" if diff < 0 and minute >= 60 and player.role == "DF" else player.role
        options = [b for b in bench if b.position == wanted_role] or [b for b in bench if b.position == player.role]
        if not options:
            continue
        replacement = max(options, key=lambda b: b.overall)
        if replacement.overall + 6 * (1 - player.stamina) < player.overall - 8:
            continue  # the bench option is much worse; keep the starter
        candidates.append((reason, player, replacement))
    candidates.sort(key=lambda item: -item[0])
    used: set[str] = set()
    # One window at a time: up to two changes together, like a real coach.
    for _, player, replacement in candidates[:2]:
        if replacement.id in used:
            continue
        command_id = f"{prefix}:s{engine.tick}:{player.id}"
        if engine.substitution_error(side, player.id, replacement.id):
            continue
        status = engine.queue_substitution(side, player.id, replacement.id, command_id)
        used.add(replacement.id)
        issued.append(status)
    return issued


def next_checkpoint(tick: int) -> int:
    return min(FULL_TIME_TICK, (tick // CHECKPOINT_TICKS + 1) * CHECKPOINT_TICKS)


def advance_with_bots(engine: MatchEngine, target_tick: int, bot_sides: tuple[int, ...], baselines: tuple[Tactics, Tactics]) -> None:
    """Advance to target, stopping at fixed checkpoints so bots can react.

    The bot difficulty travels on the engine (`engine.bot_difficulty`); bot commands
    land in the command log, so replays never need it."""
    target_tick = min(FULL_TIME_TICK, target_tick)
    difficulty = getattr(engine, "bot_difficulty", "COMPETITIVE")
    while engine.tick < target_tick and not engine.finished:
        checkpoint = next_checkpoint(engine.tick)
        engine.advance_to(min(target_tick, checkpoint))
        if engine.tick == checkpoint and engine.tick < FULL_TIME_TICK:
            for side in bot_sides:
                decide(engine, side, baselines[side], f"bot:{engine.match_id}:{side}", difficulty)
