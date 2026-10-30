"""Runtime configuration (environment variables, `.env`), validated with pydantic-settings.

Every variable is documented in the repository's `.env.example`.
"""

from __future__ import annotations

import base64
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- runtime ---
    env: Literal["dev", "test", "prod"] = Field("dev", alias="STRATA_ENV")
    log_level: str = Field("INFO", alias="STRATA_LOG_LEVEL")
    data_dir: Path = Field(REPO_ROOT / "data", alias="STRATA_DATA_DIR")
    storage_dir: Path = Field(REPO_ROOT / ".strata-storage", alias="STRATA_STORAGE_DIR")

    # --- database ---
    # SQLite for dev/test; Postgres (postgresql+psycopg://...) in production.
    database_url: str = Field("sqlite:///./strata-dev.db", alias="DATABASE_URL")
    db_echo: bool = Field(False, alias="STRATA_DB_ECHO")

    # --- secrets ---
    # Key-encryption key for envelope encryption: base64 of 32 random bytes.
    data_key: str | None = Field(None, alias="STRATA_DATA_KEY")
    # Previous KEKs (comma separated, base64) still accepted for unwrapping during rotation.
    data_key_previous: str = Field("", alias="STRATA_DATA_KEY_PREVIOUS")
    # HMAC secret for guest tokens. Defaults to a key derived from STRATA_DATA_KEY.
    guest_token_secret: str | None = Field(None, alias="STRATA_GUEST_TOKEN_SECRET")

    # --- Supabase auth/storage ---
    supabase_url: str | None = Field(None, alias="SUPABASE_URL")
    supabase_jwt_secret: str | None = Field(None, alias="SUPABASE_JWT_SECRET")
    supabase_jwks_url: str | None = Field(None, alias="SUPABASE_JWKS_URL")
    supabase_jwt_audience: str = Field("authenticated", alias="SUPABASE_JWT_AUDIENCE")
    supabase_service_role_key: str | None = Field(None, alias="SUPABASE_SERVICE_ROLE_KEY")
    storage_backend: Literal["db", "local", "supabase"] = Field(
        "db", alias="STRATA_STORAGE_BACKEND"
    )
    storage_bucket: str = Field("encrypted-datasets", alias="STRATA_STORAGE_BUCKET")

    # --- LLM providers ---
    anthropic_api_key: str | None = Field(None, alias="ANTHROPIC_API_KEY")
    openai_api_key: str | None = Field(None, alias="OPENAI_API_KEY")
    llm_provider: Literal["anthropic", "openai", "none"] = Field(
        "anthropic", alias="STRATA_LLM_PROVIDER"
    )

    # --- jobs ---
    job_mode: Literal["inline", "queue"] = Field("inline", alias="STRATA_JOB_MODE")
    job_max_attempts: int = Field(3, alias="STRATA_JOB_MAX_ATTEMPTS")
    job_backoff_base_s: float = Field(5.0, alias="STRATA_JOB_BACKOFF_BASE_S")
    job_heartbeat_s: float = Field(10.0, alias="STRATA_JOB_HEARTBEAT_S")
    job_stale_after_s: float = Field(120.0, alias="STRATA_JOB_STALE_AFTER_S")
    job_timeout_s: float = Field(1800.0, alias="STRATA_JOB_TIMEOUT_S")
    worker_poll_s: float = Field(1.0, alias="STRATA_WORKER_POLL_S")

    # --- HTTP ---
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"], alias="STRATA_CORS_ORIGINS"
    )
    guest_ttl_hours: float = Field(24.0, alias="STRATA_GUEST_TTL_HOURS")
    max_upload_mb: float = Field(64.0, alias="STRATA_MAX_UPLOAD_MB")
    rate_limit_per_minute: int = Field(120, alias="STRATA_RATE_LIMIT_PER_MINUTE")
    rate_limit_burst: int = Field(60, alias="STRATA_RATE_LIMIT_BURST")
    rate_limit_expensive_per_minute: int = Field(
        10, alias="STRATA_RATE_LIMIT_EXPENSIVE_PER_MINUTE"
    )
    trust_proxy_headers: bool = Field(False, alias="STRATA_TRUST_PROXY_HEADERS")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                import json

                return json.loads(s)
            return [o.strip() for o in s.split(",") if o.strip()]
        return v

    @model_validator(mode="after")
    def _check(self) -> Settings:
        if self.env == "prod":
            if not self.data_key:
                raise ValueError("STRATA_DATA_KEY is required when STRATA_ENV=prod")
            if self.database_url.startswith("sqlite"):
                raise ValueError("SQLite is not supported when STRATA_ENV=prod; use Postgres")
        if self.data_key:
            raw = base64.b64decode(self.data_key, validate=True)
            if len(raw) != 32:
                raise ValueError("STRATA_DATA_KEY must be base64 of exactly 32 bytes")
        return self

    # --- derived ---
    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgres")

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @property
    def examples_dir(self) -> Path:
        return self.data_dir / "examples"

    def kek_bytes(self) -> bytes:
        """Primary key-encryption key. In dev/test without a key, a per-process ephemeral key."""
        if self.data_key:
            return base64.b64decode(self.data_key)
        return _ephemeral_dev_key()

    def previous_keks(self) -> list[bytes]:
        return [base64.b64decode(k) for k in self.data_key_previous.split(",") if k.strip()]

    def guest_secret_bytes(self) -> bytes:
        if self.guest_token_secret:
            return self.guest_token_secret.encode()
        import hashlib
        import hmac

        return hmac.new(self.kek_bytes(), b"strata-guest-token-v1", hashlib.sha256).digest()

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        if self.llm_provider == "openai":
            return bool(self.openai_api_key)
        return False


@lru_cache(maxsize=1)
def _ephemeral_dev_key() -> bytes:
    # Data encrypted with this key is unreadable after restart: acceptable only for dev/test.
    return secrets.token_bytes(32)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def reset_settings_cache() -> None:
    get_settings.cache_clear()
