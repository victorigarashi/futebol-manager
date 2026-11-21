from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Brasileirão Manager API"
    app_secret: str = "development-only-secret"
    cors_origins: list[str] | str = ["http://localhost:5174"]
    session_cookie_secure: bool = False
    enable_json_snapshots: bool = False
    snapshot_path: Path = Path("data/snapshots/rooms.json")
    player_catalog_path: Path = Path("/data/catalogs/players.json")
    # International catalog used only by the Draft "Mundial" (see docs/CATALOGO_MUNDIAL.md).
    world_catalog_path: Path = Path("/data/catalogs/world_players.json")
    app_environment: str = "development"
    enable_demo_catalog: bool = False
    demo_snapshot_path: Path = Path("data/snapshots/demo-rooms.json")

    # Default real duration of a live match (each room chooses 90, 120 or 180 s; this
    # only applies to rounds started without a room setting, e.g. legacy tools).
    live_match_seconds: int = 60
    # Match presentation (line-ups on screen) between "all ready" and kick-off.
    live_intro_seconds: int = 5
    # Modo Jogável engine for competitive matches. "v6" stays the default until the owner
    # approves V7 (docs/v7); the Football Lab uses V7 and can switch for comparison.
    gameplay_engine: str = "v6"

    request_limit_per_minute: int = 600
    auth_limit_per_minute: int = 120
    max_request_body_bytes: int = 1_048_576

    @model_validator(mode="after")
    def validate_runtime(self) -> "Settings":
        if self.app_environment not in {"development", "test", "production"}:
            raise ValueError("APP_ENVIRONMENT deve ser development, test ou production.")
        if self.live_match_seconds not in {60, 90, 120, 180} or self.live_intro_seconds < 0:
            raise ValueError("LIVE_MATCH_SECONDS deve ser 60, 90, 120 ou 180 e LIVE_INTRO_SECONDS >= 0.")
        if min(self.request_limit_per_minute, self.auth_limit_per_minute, self.max_request_body_bytes) < 1:
            raise ValueError("Limites de requisição devem ser positivos.")
        if self.app_environment == "production":
            if len(self.app_secret) < 32 or self.app_secret == "development-only-secret":
                raise ValueError("Produção exige APP_SECRET exclusivo com ao menos 32 caracteres.")
            if not self.session_cookie_secure:
                raise ValueError("Produção exige SESSION_COOKIE_SECURE=true e HTTPS.")
            if not self.cors_origins or "*" in self.cors_origins:
                raise ValueError("Produção exige CORS_ORIGINS explícitos.")
            if any(not origin.startswith("https://") for origin in self.cors_origins):
                raise ValueError("Produção exige origens HTTPS.")
        return self

    @model_validator(mode="after")
    def validate_demo(self) -> "Settings":
        if self.enable_demo_catalog:
            if self.app_environment not in {"development", "test"}:
                raise ValueError("O catálogo de demonstração exige APP_ENVIRONMENT=development ou test.")
            if self.demo_snapshot_path == self.snapshot_path:
                raise ValueError("O snapshot de demonstração deve ter caminho separado.")
            self.snapshot_path = self.demo_snapshot_path
        return self

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: list[str] | str) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
