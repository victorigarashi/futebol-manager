"""Deterministic internal game price calculation in integer cents."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def game_starting_value_cents(
    *,
    overall: int,
    potential: int,
    age: int,
    position: str,
    external_market_value_eur: int | None = None,
    eur_to_brl: Decimal = Decimal("5.50"),
) -> int:
    """Calculate a game price; never label it as an external market valuation."""
    quality = Decimal(overall) * Decimal("0.65") + Decimal(potential) * Decimal("0.35")
    age_factor = max(
        Decimal("0.70"),
        min(Decimal("1.20"), Decimal("1.0") + Decimal(24 - age) / Decimal(100)),
    )
    position_factor = {
        "GK": Decimal("0.95"),
        "DF": Decimal("1.0"),
        "MF": Decimal("1.05"),
        "ST": Decimal("1.10"),
    }.get(position.upper(), Decimal("1.0"))
    if external_market_value_eur is not None and external_market_value_eur >= 0:
        base = Decimal(external_market_value_eur) * eur_to_brl
        value = base * Decimal("0.70") + (quality / Decimal(99)) * base * Decimal(
            "0.30"
        )
    else:
        value = (quality / Decimal(99)) ** 3 * Decimal(50000000)
    cents = (value * age_factor * position_factor * Decimal(100)).quantize(
        Decimal(1), rounding=ROUND_HALF_UP
    )
    return max(0, int(cents))
