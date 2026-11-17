"""Player development: realistic, bounded, reproducible, applied once per season."""

from __future__ import annotations

import statistics

from app.domain.progression import progress_player


def develop(**overrides):
    base = {"player_id": "p", "season_number": 1, "age": 25, "overall": 70, "potential": 80,
            "original_market_value_cents": 1_000_000_000, "minutes_played": 2_000, "goals": 2, "seed": 1,
            "assists": 1, "matches": 25, "average_rating": 6.8, "catalog_overall": 70}
    base.update(overrides)
    return progress_player(**base)


def mean_delta(seeds=range(200), **overrides) -> float:
    return statistics.mean(develop(seed=seed, **overrides).delta for seed in seeds)


def test_young_players_grow_veterans_decline_prime_players_hold():
    young = mean_delta(age=19, overall=68, potential=82)
    prime = mean_delta(age=28, overall=75, potential=78)
    veteran = mean_delta(age=35, overall=78, potential=78)
    assert young > 1.0
    assert -0.6 < prime < 0.9
    assert veteran < -1.5


def test_minutes_matter_for_growth():
    regular = mean_delta(age=20, overall=68, potential=85, minutes_played=2_400, matches=28)
    unused = mean_delta(age=20, overall=68, potential=85, minutes_played=90, matches=1, average_rating=None)
    assert regular > unused + 0.5


def test_performance_moves_development():
    good = mean_delta(age=27, average_rating=7.6, goals=12, assists=6)
    poor = mean_delta(age=27, average_rating=5.8, goals=0, assists=0)
    assert good > poor + 1.0


def test_growth_never_passes_the_potential_and_changes_are_bounded():
    for seed in range(300):
        record = develop(seed=seed, age=18, overall=79, potential=80, average_rating=8.5, goals=20)
        assert record.overall_after <= 80
        record = develop(seed=seed, age=37, overall=80, potential=80, average_rating=5.0, minutes_played=0, matches=0)
        assert record.overall_after >= 76


def test_unknown_age_uses_only_a_conservative_performance_rule():
    for seed in range(200):
        record = develop(seed=seed, age=None, average_rating=8.5, goals=15)
        assert abs(record.delta) <= 1
    assert any("idade não confirmada" in reason for reason in develop(age=None).reasons)


def test_development_is_reproducible():
    assert develop(seed=42, age=21) == develop(seed=42, age=21)


def test_market_value_follows_the_level_and_accumulates_across_seasons():
    first = develop(seed=3, age=20, overall=70, potential=85, catalog_overall=70)
    # Season 2 starts from season 1's level; the value is measured from the catalog level.
    second = develop(seed=4, age=21, overall=first.overall_after, potential=85, catalog_overall=70, season_number=2)
    assert first.overall_after > 70
    assert first.internal_market_value_cents > 1_000_000_000
    if second.overall_after > first.overall_after:
        assert second.internal_market_value_cents > first.internal_market_value_cents
    declined = develop(seed=5, age=36, overall=80, potential=80, catalog_overall=80)
    assert declined.internal_market_value_cents < 1_000_000_000
