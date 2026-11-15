"""Agent engine: determinism, replay, real tactical effects and substitution rules."""

import pytest

from app.domain.bot_coach import advance_with_bots, choose_lineup
from app.domain.match_engine import (
    FULL_TIME_TICK,
    TICKS_PER_HALF,
    MatchEngine,
    PlayerInput,
    TeamInput,
    replay_engine,
)
from app.domain.squad import formation_slots
from app.domain.tactics import Tactics


def team(code: str, mode: str = "ELEVEN_A_SIDE", tactics: Tactics = Tactics(), overall: int = 72) -> TeamInput:
    formation = "4-3-3" if mode == "ELEVEN_A_SIDE" else "2-1-1"
    starters = tuple(PlayerInput(f"{code}-{i}", f"{code} {i}", slot.position, slot.position, slot.x, slot.y, overall, {}, i + 1)
                     for i, slot in enumerate(formation_slots(mode, formation)))
    bench = tuple(PlayerInput(f"{code}-b{i}", f"{code} R{i}", pos, pos, 50, 50, overall - 3, {}, 20 + i)
                  for i, pos in enumerate(("GK", "DF", "MF", "ST", "ST")))
    return TeamInput(code, formation, starters, bench, tactics)


def test_same_seed_and_commands_reproduce_the_match_exactly():
    a = MatchEngine("m", "ELEVEN_A_SIDE", team("AAA"), team("BBB"), 7)
    a.advance_to(1200)
    a.queue_tactics(0, Tactics(mentality="ATTACKING"), "AAA:k1")
    a.advance_to(3000)
    a.queue_substitution(1, "BBB-5", "BBB-b2", "BBB:k2")
    a.run_to_end()
    b = replay_engine("m", "ELEVEN_A_SIDE", team("AAA"), team("BBB"), 7, a.command_log, FULL_TIME_TICK)
    assert (a.score, [e["event_id"] for e in a.events]) == (b.score, [e["event_id"] for e in b.events])
    assert a.frames_since(5000) == b.frames_since(5000)


def test_events_are_real_and_goals_reconcile_with_score():
    engine = MatchEngine("m", "ELEVEN_A_SIDE", team("AAA"), team("BBB"), 11)
    engine.run_to_end()
    goals = [e for e in engine.events if e["kind"] == "GOAL"]
    assert len(goals) == sum(engine.score)
    assert all(e["player_id"] for e in goals)  # every goal names its scorer
    assert engine.events[-1]["kind"] == "FULL_TIME" and any(e["kind"] == "HALF_TIME" for e in engine.events)
    stats = engine.statistics()
    assert stats["AAA"]["goals"] == engine.score[0] and stats["BBB"]["goals"] == engine.score[1]
    assert 300 < stats["AAA"]["passes"] + stats["BBB"]["passes"] < 3000
    assert abs(stats["AAA"]["possession"] + stats["BBB"]["possession"] - 100) < 0.2


def test_tactics_change_behaviour_not_a_hidden_goal_bonus():
    """High press must produce more high recoveries and more fatigue across matches."""
    press_rec, base_rec, press_stamina, base_stamina = 0, 0, 0.0, 0.0
    for seed in range(4):
        high = MatchEngine("h", "ELEVEN_A_SIDE", team("AAA", tactics=Tactics(pressure="HIGH")), team("BBB"), seed)
        low = MatchEngine("l", "ELEVEN_A_SIDE", team("AAA", tactics=Tactics(pressure="LOW")), team("BBB"), seed)
        high.advance_to(2400)
        low.advance_to(2400)
        press_rec += high.team_stats[0]["high_recoveries"]
        base_rec += low.team_stats[0]["high_recoveries"]
        press_stamina += sum(a.stamina for a in high.active(0))
        base_stamina += sum(a.stamina for a in low.active(0))
    assert press_rec > base_rec
    assert press_stamina < base_stamina


def test_substitution_rules_are_enforced_by_the_engine():
    engine = MatchEngine("m", "ELEVEN_A_SIDE", team("AAA"), team("BBB"), 3)
    engine.advance_to(600)
    assert engine.substitution_error(0, "AAA-1", "BBB-b1") == "Atleta não pertence ao seu time nesta partida."
    assert engine.substitution_error(0, "nobody", "AAA-b1")
    assert engine.substitution_error(0, "AAA-b0", "AAA-b1") == "O jogador que sai não está em campo."
    status = engine.queue_substitution(0, "AAA-4", "AAA-b1", "AAA:s1")
    assert status["status"] in {"PENDING", "APPLIED"}
    with pytest.raises(ValueError):
        engine.queue_substitution(0, "AAA-4", "AAA-b2", "AAA:s2")  # same player twice
    while engine.applied_commands["AAA:s1"]["status"] == "PENDING":
        engine.step()  # waits for a stoppage
    assert engine.dead is not None or engine.phase == "HALF_TIME" or engine.applied_commands["AAA:s1"]["applied_tick"] == engine.tick
    assert not engine.by_id["AAA-4"].active and engine.by_id["AAA-b1"].active
    with pytest.raises(ValueError):
        engine.queue_substitution(0, "AAA-5", "AAA-4", "AAA:s3")  # substituted player cannot return
    for index, (out, incoming) in enumerate((("AAA-5", "AAA-b2"), ("AAA-6", "AAA-b3"), ("AAA-7", "AAA-b4"))):
        if engine.substitution_error(0, out, incoming):
            break
        engine.queue_substitution(0, out, incoming, f"AAA:x{index}")
        while engine.pending_subs[0]:
            engine.step()
    assert engine.subs_used[0] + len(engine.pending_subs[0]) <= 5
    assert engine.windows_used[0] <= 3


def test_halftime_substitutions_do_not_spend_a_window():
    engine = MatchEngine("m", "FIVE_A_SIDE", team("AAA", "FIVE_A_SIDE"), team("BBB", "FIVE_A_SIDE"), 5)
    engine.advance_to(TICKS_PER_HALF)
    assert engine.phase == "HALF_TIME"
    # A deterministic match can still send off a particular shirt number before
    # half time.  The rule under test is the window accounting, not that a fixed
    # player remains available.
    outgoing = next(player for player in engine.active(0) if player.role != "GK")
    incoming = next(player for player in engine.team_agents[0] if not player.active and player.entered_tick is None)
    status = engine.queue_substitution(0, outgoing.id, incoming.id, "AAA:h")
    assert status["status"] == "APPLIED" and engine.windows_used[0] == 0


def test_bot_coach_uses_the_public_command_api_only():
    engine = MatchEngine("m", "ELEVEN_A_SIDE", team("AAA", overall=60), team("BBB", overall=80), 21)
    advance_with_bots(engine, FULL_TIME_TICK, (0, 1), (Tactics(), Tactics()))
    assert engine.finished
    bot_commands = [c for c in engine.command_log if str(c["command_id"]).startswith("bot:")]
    assert bot_commands, "bots should react to score, fatigue and the clock"
    assert all(c["kind"] in {"TACTICS", "SUBSTITUTION"} for c in bot_commands)
    assert engine.subs_used[0] <= 5 and engine.subs_used[1] <= 5
    replayed = replay_engine("m", "ELEVEN_A_SIDE", team("AAA", overall=60), team("BBB", overall=80), 21, engine.command_log, FULL_TIME_TICK)
    assert replayed.score == engine.score


def test_bot_lineup_is_valid_and_prefers_natural_positions():
    from app.tests.fixtures.market_catalog import synthetic_catalog
    players = synthetic_catalog("ELEVEN_A_SIDE", teams=1).players
    code, assignments = choose_lineup("ELEVEN_A_SIDE", list(players), {})
    slots = formation_slots("ELEVEN_A_SIDE", code)
    by_id = {p.id: p for p in players}
    assert set(assignments) == {s.id for s in slots} and len(set(assignments.values())) == len(slots)
    assert by_id[assignments["gk"]].position == "GK"
