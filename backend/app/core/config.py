"""Application configuration.

Reads settings from environment variables (and an optional `.env` file at the
repository root). Never hard-code credentials anywhere else in the codebase.

Why a settings object instead of reading os.environ directly?
    * One place to see every setting the app understands.
    * Values are typed and validated at startup, so a typo fails loudly and early.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# Repository root = backend/app/core/config.py -> three levels up.
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Typed application settings, loaded from the environment / `.env`."""

    model_config = SettingsConfigDict(
        # Look for `.env` in the repository root (two levels above this file).
        env_file=(str(_REPO_ROOT / ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- General ----
    app_name: str = "ElderLife AI"
    environment: str = "development"  # "development" | "test" | "production"

    # ---- Database ----
    # Default targets the Docker Compose service defined in docker-compose.yml.
    # Override with the DATABASE_URL variable in your local `.env`.
    database_url: str = (
        "postgresql+psycopg://elderlife_dev:change_me_local_only@localhost:5432/elderlife"
    )

    # ---- Backend ----
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    allowed_origins: str = "http://localhost:5173"

    # ---- Security (Phase 3) ----
    # The development default is intentionally obvious and unsafe. Production
    # MUST override SECRET_KEY via the environment; see `validate_secret_key`.
    secret_key: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    @property
    def cors_origins(self) -> list[str]:
        """Allowed browser origins as a list (the frontend dev server)."""
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    def validate_secret_key(self) -> None:
        """Refuse to run in production with the placeholder secret key.

        Failing loudly at startup is far better than silently signing real
        tokens with a publicly-known key.
        """
        insecure = "dev-only-insecure-secret-change-me"
        if self.is_production and self.secret_key == insecure:
            raise RuntimeError(
                "SECRET_KEY is still the development placeholder. "
                "Set a strong, random SECRET_KEY in the environment before "
                "running in production."
            )
        if self.is_production and len(self.secret_key) < 32:
            raise RuntimeError(
                "SECRET_KEY must be at least 32 characters in production."
            )

    @property
    def is_production(self) -> bool:
        """True when running in production — used to block destructive scripts."""
        return self.environment.strip().lower() == "production"

    @property
    def is_test(self) -> bool:
        """True when running the automated test suite."""
        return self.environment.strip().lower() == "test"


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings object (created once per process)."""
    return Settings()
