"""Read-only, versioned player catalog validation for the in-memory game server."""

import csv
import json
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.domain.clubs import CLUBS

POSITION_ALIASES = {
    "GK": "GK", "GOL": "GK", "GOLEIRO": "GK",
    "CB": "DF", "ZAG": "DF", "ZAGUEIRO": "DF", "LB": "DF", "RB": "DF", "DF": "DF", "DEFENSOR": "DF",
    "CM": "MF", "CDM": "MF", "CAM": "MF", "MEIA": "MF", "VOL": "MF", "MF": "MF",
    "ST": "ST", "CF": "ST", "AT": "ST", "ATA": "ST", "ATACANTE": "ST", "LW": "ST", "RW": "ST",
}


def normalize_position(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in POSITION_ALIASES:
        raise ValueError(f"Posição não suportada: {value}")
    return POSITION_ALIASES[normalized]


class CatalogPlayer(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    club_code: str = Field(min_length=3, max_length=3)
    # Real club name for international records (club_code "WLD"); absent for national ones.
    club_name: str | None = Field(default=None, max_length=80)
    age: int | None = Field(default=None, ge=14, le=50)
    nationality: str | None = Field(default=None, min_length=1)
    verification_status: str | None = Field(default=None, min_length=1)
    position: str = Field(min_length=1)
    secondary_positions: list[str] = Field(default_factory=list)
    # Optional editorial component ratings; legacy and synthetic entries remain valid without them.
    attributes: dict[str, int] = Field(default_factory=dict)
    overall: int = Field(ge=1, le=99)
    potential: int = Field(ge=1, le=99)
    market_value_cents: int = Field(ge=0)
    source: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    # Optional presentation metadata from the supplied squad list (absent on legacy entries).
    source_ids: dict[str, str] = Field(default_factory=dict)
    shirt_number: int | None = Field(default=None, ge=0, le=99)
    squad_role: str | None = None
    # Production bundles use a local static path for individually licensed assets;
    # legacy catalogs may still reference a HTTPS image. Arbitrary schemes are not
    # accepted so card rendering cannot be used as a URL-scheme escape hatch.
    photo_url: str | None = Field(default=None, pattern=r"^(?:https://|/player-photos/)")

    @field_validator("id", "name", "source", "source_version", "nationality", "verification_status")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return " ".join(value.split())

    @field_validator("club_code")
    @classmethod
    def normalize_club(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("position", mode="before")
    @classmethod
    def normalize_primary_position(cls, value: str) -> str:
        return normalize_position(value)

    @field_validator("secondary_positions", mode="before")
    @classmethod
    def normalize_secondary_positions(cls, value: list[str] | None) -> list[str]:
        return [] if not value else list(dict.fromkeys(normalize_position(item) for item in value))

    @field_validator("attributes")
    @classmethod
    def validate_attributes(cls, value: dict[str, int]) -> dict[str, int]:
        if any(not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 99 for rating in value.values()):
            raise ValueError("Atributos devem ser inteiros entre 1 e 99.")
        return value


class PlayerCatalog(BaseModel):
    catalog_version: str = Field(min_length=1)
    source: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    players: list[CatalogPlayer]


class CatalogStatus(BaseModel):
    loaded: bool
    player_count: int
    catalog_version: str | None = None
    reason: str | None = None
    missing_clubs: list[str] = Field(default_factory=list)


class CatalogImportReport(BaseModel):
    accepted: bool
    player_count: int = 0
    duplicate_ids: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    catalog: PlayerCatalog | None = None


def load_catalog(path: Path) -> PlayerCatalog | None:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        return PlayerCatalog.model_validate(json.load(handle))


def catalog_status(path: Path) -> CatalogStatus:
    try:
        catalog = load_catalog(path)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        return CatalogStatus(loaded=False, player_count=0, reason=f"Catálogo inválido: {error}")
    if not catalog:
        return CatalogStatus(loaded=False, player_count=0, reason="Aguardando arquivo autorizado data/catalogs/players.json.")
    known = {club.code for club in CLUBS}
    covered = {player.club_code for player in catalog.players if player.club_code in known}
    missing = sorted(known - covered)
    return CatalogStatus(loaded=not missing, player_count=len(catalog.players), catalog_version=catalog.catalog_version, missing_clubs=missing, reason=None if not missing else "Há clubes sem atletas no catálogo.")


def validate_catalog_payload(payload: dict[str, object]) -> CatalogImportReport:
    try:
        catalog = PlayerCatalog.model_validate(payload)
    except ValidationError as error:
        return CatalogImportReport(accepted=False, issues=[item["msg"] for item in error.errors()])
    ids = [player.id for player in catalog.players]
    duplicates = sorted({player_id for player_id in ids if ids.count(player_id) > 1})
    if duplicates:
        return CatalogImportReport(accepted=False, player_count=len(catalog.players), duplicate_ids=duplicates, issues=["Identificadores de atleta duplicados."])
    return CatalogImportReport(accepted=True, player_count=len(catalog.players), catalog=catalog)


def import_catalog(path: Path) -> CatalogImportReport:
    """Imports authorized local JSON/CSV only; deliberately performs no network collection."""
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
        elif path.suffix.lower() == ".csv":
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            if not rows:
                return CatalogImportReport(accepted=False, issues=["CSV sem jogadores."])
            first = rows[0]
            payload = {"catalog_version": first.pop("catalog_version", ""), "source": first.pop("catalog_source", ""), "source_version": first.pop("catalog_source_version", ""), "players": rows}
        else:
            return CatalogImportReport(accepted=False, issues=["Formato aceito: JSON ou CSV."])
    except (OSError, json.JSONDecodeError, csv.Error) as error:
        return CatalogImportReport(accepted=False, issues=[str(error)])
    return validate_catalog_payload(payload)
