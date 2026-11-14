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
    app_environment: str = "development"
    enable_demo_catalog: bool = False
    demo_snapshot_path: Path = Path("data/snapshots/demo-rooms.json")

    request_limit_per_minute: int = 600
    auth_limit_per_minute: int = 120
    max_request_body_bytes: int = 1_048_576

    @model_validator(mode="after")
    def validate_runtime(self) -> "Settings":
        if self.app_environment not in {"development", "test", "production"}:
            raise ValueError("APP_ENVIRONMENT deve ser development, test ou production.")
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
