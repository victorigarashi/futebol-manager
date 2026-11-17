from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.rooms import BUDGETS


class RoomCreate(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    mode: Literal["FIVE_A_SIDE", "ELEVEN_A_SIDE"]
    initial_budget_cents: int = 10_000_000_000
    max_human_participants: int = Field(ge=1, le=20)
    team_count: Literal[4, 6, 8, 10, 12, 16, 20] = 20
    double_round_robin: bool = True
    market_mode: Literal["TRADITIONAL", "COINS"] = "TRADITIONAL"
    privacy: Literal["PUBLIC", "PRIVATE"] = "PUBLIC"
    initial_market_duration_seconds: int = Field(default=300)
    round_preparation_duration_seconds: int = Field(default=300, ge=120, le=604_800)
    withdrawal_penalty_percent: Literal[0, 2, 5, 10] = 5
    # Real duration of each live match: 1:00 (default), 1:30, 2:00 or 3:00.
    match_duration_seconds: Literal[60, 90, 120, 180] = 60
    game_mode: Literal["TRADITIONAL", "DRAFT"] = "TRADITIONAL"
    sim_style: Literal["REALISTIC", "EXCITING"] = "REALISTIC"
    bot_difficulty: Literal["CASUAL", "COMPETITIVE", "LEGENDARY"] = "COMPETITIVE"
    morale_enabled: bool = False
    copa_enabled: bool = False
    playoff_format: Literal["SINGLE", "TWO_LEGS"] = "SINGLE"
    coach_moves_enabled: bool = False
    draft_catalog: Literal["BRASILEIRAO", "WORLD"] = "BRASILEIRAO"
    draft_min_overall: Literal[0, 65, 70, 72, 75, 78, 80] = 0

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 3:
            raise ValueError("Nome deve conter ao menos 3 caracteres.")
        return normalized

    @field_validator("initial_budget_cents")
    @classmethod
    def validate_budget(cls, value: int) -> int:
        if value not in BUDGETS:
            raise ValueError("Orçamento inicial inválido.")
        return value

    @model_validator(mode="after")
    def validate_capacity(self) -> "RoomCreate":
        if self.max_human_participants > self.team_count:
            raise ValueError("A quantidade de técnicos humanos não pode exceder a de clubes.")
        return self

    @field_validator("initial_market_duration_seconds")
    @classmethod
    def validate_market_duration(cls, value: int) -> int:
        allowed = {120, 180, 300, 600, 900, 1_200, 1_800}
        if value not in allowed:
            raise ValueError("Escolha um tempo de preparação entre as opções disponíveis.")
        return value

    @field_validator("round_preparation_duration_seconds")
    @classmethod
    def validate_round_preparation_duration(cls, value: int) -> int:
        # Short windows suit a live session. Longer legacy values stay valid so
        # an existing lobby can still be edited without losing its settings.
        allowed = {120, 180, 300, 600, 3_600, 21_600, 43_200, 86_400, 172_800, 604_800}
        if value not in allowed:
            raise ValueError("Escolha um prazo entre as opções disponíveis.")
        return value


class JoinByCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.upper()


class ClubSelectionRequest(BaseModel):
    club_code: str = Field(min_length=3, max_length=3)

    @field_validator("club_code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.upper()


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=3, max_length=24)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 3:
            raise ValueError("Nome do técnico deve conter ao menos 3 caracteres.")
        if not all(char.isalnum() or char.isspace() for char in normalized):
            raise ValueError("Use apenas letras, números e espaços no nome do técnico.")
        return normalized


class RoomUpdate(RoomCreate):
    # Omitted by older clients: keep the room's current values.
    match_duration_seconds: Literal[60, 90, 120, 180] | None = None
    game_mode: Literal["TRADITIONAL", "DRAFT"] | None = None
    sim_style: Literal["REALISTIC", "EXCITING"] | None = None
    bot_difficulty: Literal["CASUAL", "COMPETITIVE", "LEGENDARY"] | None = None
    morale_enabled: bool | None = None
    copa_enabled: bool | None = None
    playoff_format: Literal["SINGLE", "TWO_LEGS"] | None = None
    coach_moves_enabled: bool | None = None
    draft_catalog: Literal["BRASILEIRAO", "WORLD"] | None = None
    draft_min_overall: Literal[0, 65, 70, 72, 75, 78, 80] | None = None


class MatchSettingsUpdate(BaseModel):
    match_duration_seconds: Literal[60, 90, 120, 180]


class BotChange(BaseModel):
    club_code: str | None = Field(default=None, min_length=3, max_length=3)

    @field_validator("club_code")
    @classmethod
    def normalize_optional_club(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class MarketOfferCreate(BaseModel):
    player_id: str = Field(min_length=1)
    amount_cents: int = Field(gt=0)
    idempotency_key: str = Field(min_length=8, max_length=120)


class MarketOfferUpdate(BaseModel):
    amount_cents: int = Field(gt=0)


class MarketSelectionPreview(BaseModel):
    offer_ids: list[str] = Field(max_length=48)


class MarketSelectionConfirm(MarketSelectionPreview):
    pass


class MarketReassignmentDecision(BaseModel):
    accept: bool


class LineupUpdate(BaseModel):
    formation_code: str = Field(min_length=3, max_length=12)
    assignments: dict[str, str]


class StrategyUpdate(BaseModel):
    strategy: Literal["BALANCED", "ATTACKING", "DEFENSIVE", "COUNTER", "POSSESSION", "HIGH_PRESS"]


Mentality = Literal["VERY_DEFENSIVE", "DEFENSIVE", "BALANCED", "ATTACKING", "VERY_ATTACKING"]
Pressure = Literal["LOW", "MEDIUM", "HIGH"]
Style = Literal["POSSESSION", "COUNTER", "DIRECT", "SHORT_BUILDUP", "WIDE"]


class TacticsUpdate(BaseModel):
    mentality: Mentality
    pressure: Pressure
    style: Style


class InstructionsUpdate(BaseModel):
    # player id -> instruction code; validated against the slot by the server.
    instructions: dict[str, str] = Field(max_length=11)


class LiveCommand(BaseModel):
    kind: Literal["TACTICS", "SUBSTITUTION", "FORMATION"]
    formation_code: str | None = Field(default=None, min_length=2, max_length=12)
    idempotency_key: str = Field(min_length=8, max_length=80)
    mentality: Mentality | None = None
    pressure: Pressure | None = None
    style: Style | None = None
    out_player_id: str | None = Field(default=None, min_length=1, max_length=80)
    in_player_id: str | None = Field(default=None, min_length=1, max_length=80)


class TransferBuy(BaseModel):
    incoming_player_id: str = Field(min_length=1)
    replace_player_id: str = Field(min_length=1)
    amount_cents: int = Field(gt=0)
    operation_id: str = Field(min_length=8, max_length=120)


class TransferOfferCreate(BaseModel):
    incoming_player_id: str = Field(min_length=1)
    # Empty for a cash purchase or a loan.
    offered_player_id: str = Field(default="", max_length=120)
    kind: Literal["TRADE", "PURCHASE", "LOAN"] = "TRADE"
    amount_cents: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=120)


class TransferCounter(BaseModel):
    amount_cents: int = Field(gt=0)


class TransferListingUpdate(BaseModel):
    player_id: str = Field(min_length=1, max_length=120)
    listed: bool
