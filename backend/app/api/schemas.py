from typing import Literal

from pydantic import BaseModel, Field, field_validator


class RoomCreate(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    mode: Literal["FIVE_A_SIDE", "ELEVEN_A_SIDE"]
    initial_budget_cents: int
    max_human_participants: int = Field(ge=1, le=20)
    privacy: Literal["PUBLIC", "PRIVATE"] = "PUBLIC"
    initial_market_duration_seconds: int = Field(default=300)
    round_preparation_duration_seconds: int = Field(default=86_400, ge=3_600, le=604_800)
    withdrawal_penalty_percent: Literal[0, 2, 5, 10] = 5

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
        if value not in {5_000_000_000, 10_000_000_000, 15_000_000_000, 20_000_000_000}:
            raise ValueError("Orçamento inicial inválido.")
        return value

    @field_validator("initial_market_duration_seconds")
    @classmethod
    def validate_market_duration(cls, value: int) -> int:
        allowed = {120, 180, 300, 600, 900, 1_200, 1_800}
        if value not in allowed:
            raise ValueError("Escolha um tempo de preparação entre as opções disponíveis.")
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
    pass


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


class TransferBuy(BaseModel):
    incoming_player_id: str = Field(min_length=1)
    replace_player_id: str = Field(min_length=1)
    amount_cents: int = Field(gt=0)
    operation_id: str = Field(min_length=8, max_length=120)


class TransferOfferCreate(BaseModel):
    incoming_player_id: str = Field(min_length=1)
    offered_player_id: str = Field(min_length=1)
    amount_cents: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=120)


class TransferCounter(BaseModel):
    amount_cents: int = Field(gt=0)


class TransferListingUpdate(BaseModel):
    player_id: str = Field(min_length=1, max_length=120)
    listed: bool
