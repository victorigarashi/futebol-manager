"""Custom (user-created) players.

A coach creates an athlete for HIS club: name, position, attributes. The overall is never typed
by the coach: it is computed from the attributes with explicit per-position weights, so a custom
player plays exactly at the level his attributes describe and the same attributes always give
the same overall. Fair-play limits keep every coach on the same terms.

The player becomes an ordinary catalogue entry of the room (`source = "CUSTOM"`), so the market,
transfers, line-ups, frozen round snapshots, MatchPayload and every engine treat him like any
other athlete. Persistence reuses the market's generated-player store (saved in snapshots).
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.catalog import CatalogPlayer

OUTFIELD_KEYS = ("pace", "shooting", "passing", "dribbling", "defending", "physical")
KEEPER_KEYS = ("gk_diving", "gk_handling", "gk_reflexes", "gk_positioning")
ATTRIBUTE_MIN, ATTRIBUTE_MAX = 30, 90
MAX_OVERALL = 80               # a created player never outclasses the league's stars
MAX_PER_CLUB = 3
SOURCE = "CUSTOM"

# Overall = weighted mean of the attributes that matter for the position (weights sum to 1).
WEIGHTS: dict[str, dict[str, float]] = {
    "GK": {"gk_diving": 0.25, "gk_handling": 0.2, "gk_reflexes": 0.25, "gk_positioning": 0.2, "physical": 0.05, "passing": 0.05},
    "DF": {"defending": 0.4, "physical": 0.25, "pace": 0.15, "passing": 0.12, "dribbling": 0.05, "shooting": 0.03},
    "MF": {"passing": 0.35, "dribbling": 0.2, "defending": 0.12, "shooting": 0.13, "pace": 0.1, "physical": 0.1},
    "ST": {"shooting": 0.4, "pace": 0.2, "dribbling": 0.2, "physical": 0.1, "passing": 0.1},
}


class CustomPlayerSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=40)
    position: str
    attributes: dict[str, int]
    shirt_number: int | None = Field(default=None, ge=1, le=99)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not re.fullmatch(r"[\wÀ-ÿ' .-]{2,40}", value):
            raise ValueError("Nome com caracteres inválidos.")
        return value

    @model_validator(mode="after")
    def _attributes(self) -> CustomPlayerSpec:
        if self.position not in WEIGHTS:
            raise ValueError("Posição inválida: use GK, DF, MF ou ST.")
        required = OUTFIELD_KEYS + (KEEPER_KEYS if self.position == "GK" else ())
        missing = [k for k in required if k not in self.attributes]
        extra = [k for k in self.attributes if k not in required]
        if missing:
            raise ValueError(f"Atributos faltando: {', '.join(missing)}.")
        if extra:
            raise ValueError(f"Atributos não aceitos para {self.position}: {', '.join(extra)}.")
        if any(not ATTRIBUTE_MIN <= v <= ATTRIBUTE_MAX for v in self.attributes.values()):
            raise ValueError(f"Cada atributo deve ficar entre {ATTRIBUTE_MIN} e {ATTRIBUTE_MAX}.")
        if custom_overall(self.position, self.attributes) > MAX_OVERALL:
            raise ValueError(f"Overall resultante acima de {MAX_OVERALL}: reduza os atributos principais da posição.")
        return self


def custom_overall(position: str, attributes: dict[str, int]) -> int:
    weights = WEIGHTS[position]
    return int(round(sum(attributes[key] * weight for key, weight in weights.items())))


def custom_player_id(room_id: str, club_code: str, sequence: int) -> str:
    return f"CUS-{room_id[:8]}-{club_code}-{sequence:02d}"


def build_custom_player(spec: CustomPlayerSpec, club_code: str, player_id: str) -> CatalogPlayer:
    overall = custom_overall(spec.position, spec.attributes)
    return CatalogPlayer(
        id=player_id, name=spec.name, club_code=club_code, position=spec.position, attributes=dict(spec.attributes),
        overall=overall, potential=overall, market_value_cents=0, source=SOURCE, source_version="custom-v1",
        shirt_number=spec.shirt_number, attribute_source=SOURCE, rating_source=SOURCE)
