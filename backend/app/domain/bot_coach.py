"""Bot coaches: lineup choice and in-match decisions.

Bots read only what a human coach sees (score, minute, cards, the stamina shown on
the bench panel and the squad's ratings) and act exclusively through the engine's
public command API (`queue_tactics` / `queue_substitution`), with the same limits.
"""

from __future__ import annotations

from app.domain.catalog import CatalogPlayer
from app.domain.match_engine import FULL_TIME_TICK, Agent, MatchEngine
from app.domain.squad import FORMATION_LINES, effective_overall, formation_slots
from app.domain.tactics import Tactics

# Fixed decision checkpoints keep bot behaviour reproducible from the command log.
CHECKPOINT_TICKS = 300  # every five game minutes (half time = tick 2700 is one of them)
ORDER = ["VERY_DEFENSIVE", "DEFENSIVE", "BALANCED", "ATTACKING", "VERY_ATTACKING"]


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


def decide(engine: MatchEngine, side: int, baseline: Tactics, command_prefix: str) -> list[dict[str, object]]:
    """Run at a checkpoint tick; returns the commands issued (already queued)."""
    issued: list[dict[str, object]] = []
    if engine.finished:
        return issued
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
    wanted = Tactics(mentality, pressure, style)
    if wanted != engine.tactics[side]:
        command_id = f"{command_prefix}:t{engine.tick}"
        issued.append(engine.queue_tactics(side, wanted, command_id))

    issued.extend(_substitutions(engine, side, minute, diff, command_prefix))
    return issued


def _substitutions(engine: MatchEngine, side: int, minute: float, diff: int, prefix: str) -> list[dict[str, object]]:
    issued: list[dict[str, object]] = []
    halftime = engine.phase == "HALF_TIME"
    if minute < 45 and not halftime:
        return issued
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
        if diff < 0 and minute >= 60 and player.role == "DF":
            reason += 0.4  # chasing: trade a defender for an attacker
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
    """Advance to target, stopping at fixed checkpoints so bots can react."""
    target_tick = min(FULL_TIME_TICK, target_tick)
    while engine.tick < target_tick and not engine.finished:
        checkpoint = next_checkpoint(engine.tick)
        engine.advance_to(min(target_tick, checkpoint))
        if engine.tick == checkpoint and engine.tick < FULL_TIME_TICK:
            for side in bot_sides:
                decide(engine, side, baselines[side], f"bot:{engine.match_id}:{side}")
