"""Runtime configuration.

All settings are read from environment variables prefixed with ``NIRIKSHAN_``.
The platform is designed to boot with zero configuration (sensible dev defaults)
and to degrade gracefully when optional AI credentials are absent.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_rate(value: str) -> tuple[int, int]:
    """Parse a ``"<count>/<seconds>"`` rate-limit spec into ``(count, seconds)``."""
    try:
        count, window = value.split("/", 1)
        return int(count), int(window)
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError(f"invalid rate spec {value!r}, expected 'count/seconds'") from exc


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NIRIKSHAN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Core ---
    env: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    # --- Security ---
    secret_key: str = "dev-only-insecure-secret-change-me"
    access_token_ttl_minutes: int = 60
    refresh_token_ttl_minutes: int = 60 * 24 * 30
    bootstrap_admin_email: str | None = "admin@nirikshan.dev"
    bootstrap_admin_password: str | None = "admin12345"
    # Optional shared secret for telemetry ingestion. When set, the
    # /api/telemetry/* endpoints require a matching `X-Ingest-Token` header.
    # Unset (default) => open ingestion, suitable for the local demo only.
    ingest_token: str | None = None

    # Run the event-consumer + maintenance loop as a daemon thread inside the
    # API process instead of a separate `worker` container. Intended for
    # constrained single-service hosts (e.g. Render free tier). A dedicated
    # worker process is still preferred anywhere it is available.
    run_worker_in_process: bool = False

    # --- Datastores ---
    database_url: str = "sqlite+pysqlite:///./nirikshan.sqlite3"
    redis_url: str = "redis://localhost:6379/0"
    redis_stream_maxlen: int = 50_000

    # --- Retention ---
    retention_logs_hours: int = 72
    retention_metrics_hours: int = 168
    retention_traces_hours: int = 72

    # --- Rate limits ("count/seconds") ---
    ratelimit_telemetry: str = "2000/60"
    ratelimit_investigate: str = "10/60"
    ratelimit_remediation: str = "20/60"
    ratelimit_default: str = "300/60"

    # --- AI provider abstraction ---
    llm_provider: str = "mock"
    llm_model: str = "mock-sre-1"
    llm_timeout_seconds: int = 45
    llm_max_tool_iterations: int = 8
    llm_api_key: str | None = None
    llm_base_url: str | None = None

    embedding_provider: str = "local"
    embedding_model: str = "local-hash-256"
    embedding_dim: int = 256

    # --- Remediation ---
    remediation_mode: str = "APPROVAL_REQUIRED"

    @field_validator("remediation_mode")
    @classmethod
    def _validate_mode(cls, v: str) -> str:
        allowed = {"OBSERVE", "RECOMMEND", "APPROVAL_REQUIRED", "AUTONOMOUS"}
        if v not in allowed:
            raise ValueError(f"remediation_mode must be one of {sorted(allowed)}")
        return v

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        """Accept the bare URLs that managed hosts hand out (Render/Heroku give
        ``postgres://`` / ``postgresql://``) and pin the psycopg v3 driver."""
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://") :]
        if v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://") :]
        return v

    # --- Derived helpers ---
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def llm_effective_provider(self) -> str:
        """Fall back to the mock provider when a remote provider lacks credentials."""
        if self.llm_provider in {"openai", "groq"} and not self.llm_api_key:
            return "mock"
        return self.llm_provider

    def rate(self, name: str) -> tuple[int, int]:
        return _parse_rate(getattr(self, f"ratelimit_{name}", self.ratelimit_default))


@lru_cache
def get_settings() -> Settings:
    return Settings()
