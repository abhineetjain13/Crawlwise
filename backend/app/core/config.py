# Centralized application settings.
from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BASE_DIR.parent


def _resolve_project_path(value: str | Path, *, anchor: Path = PROJECT_ROOT) -> Path:
    raw_path = Path(value)
    return raw_path if raw_path.is_absolute() else (anchor / raw_path).resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Support both repo-root and backend-local .env files.
        env_file=(str(PROJECT_ROOT / ".env"), str(BASE_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "CrawlerAI"
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    frontend_url: str = "http://127.0.0.1:3000"
    frontend_origins: str = ""
    jwt_secret_key: str = Field(
        validation_alias=AliasChoices("JWT_SECRET_KEY", "jwt_secret_key"),
    )
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24
    encryption_key: str = Field(
        validation_alias=AliasChoices("ENCRYPTION_KEY", "encryption_key"),
    )
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/crawl_db"
    redis_url: str = "redis://localhost:6379/0"
    redis_state_enabled: bool = False
    celery_dispatch_enabled: bool = False
    legacy_inprocess_runner_enabled: bool = True
    artifacts_dir: Path = Field(default=BASE_DIR / "artifacts")
    acquisition_cache_dir: Path = Field(
        default=BASE_DIR / "artifacts" / "acquisition_cache"
    )
    cookie_store_dir: Path = Field(default=BASE_DIR / "cookie_store")
    playwright_headless: bool = True
    browser_pool_size: int = 2
    browser_context_timeout_seconds: float = 30.0
    http_timeout_seconds: float = 20.0
    http_max_connections: int = 50
    http_max_keepalive_connections: int = 20
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    nvidia_api_key: str = ""
    request_id_header: str = "X-Request-ID"
    crawl_log_db_min_level: str = "info"
    crawl_log_db_url_progress_sample_rate: int = 4
    crawl_log_db_max_rows_per_run: int = 1000
    crawl_log_file_enabled: bool = True
    crawl_log_file_dir: Path = Field(default=BASE_DIR / "artifacts" / "run_logs")
    system_max_concurrent_urls: int = 8
    llm_cache_ttl_seconds: int = 86400
    default_admin_email: str = Field(
        default="",
        validation_alias=AliasChoices("DEFAULT_ADMIN_EMAIL", "default_admin_email"),
    )
    default_admin_password: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "DEFAULT_ADMIN_PASSWORD",
            "default_admin_password",
        ),
    )
    bootstrap_admin_once: bool = Field(
        default=False,
        validation_alias=AliasChoices("BOOTSTRAP_ADMIN_ONCE", "bootstrap_admin_once"),
    )
    # When false, POST /api/auth/register returns 403 (POC single-admin dev). Enable for production multi-tenant.
    registration_enabled: bool = False

    # Database pool tuning (ignored for SQLite).
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle_seconds: int = 600
    db_pool_timeout_seconds: int = 10
    db_pool_pre_ping: bool = True

    @field_validator(
        "artifacts_dir",
        "acquisition_cache_dir",
        "cookie_store_dir",
        "crawl_log_file_dir",
        mode="before",
    )
    @classmethod
    def _resolve_repo_relative_paths(cls, value: str | Path) -> Path:
        return _resolve_project_path(value, anchor=PROJECT_ROOT)


settings = Settings()


# ---------------------------------------------------------------------------
# Security guard: reject default secrets in non-dev environments
# ---------------------------------------------------------------------------
_INSECURE_DEFAULTS = {
    "change-me",
    "change-me-32-bytes-minimum-change-me",
    "replace-with-64-byte-random-secret",
    "replace-with-32-byte-minimum-secret",
}
_INSECURE_ADMIN_PASSWORD_DEFAULTS = {"YourSecurePassword123!"}
_INSECURE_ADMIN_EMAIL_DEFAULTS = {"admin@admin.com", "admin@example.invalid"}


def _is_non_dev_environment(env_name: str) -> bool:
    normalized = str(env_name or "").strip().lower()
    return normalized not in {"", "development", "dev", "local", "test", "testing"}


def _check_secret_defaults() -> None:
    """Warn loudly (or crash outside dev/test) if default secrets are still set."""
    import logging
    import os

    logger = logging.getLogger("app.core.config")
    env = os.getenv("APP_ENV", "development").lower()
    issues: list[str] = []
    if settings.jwt_secret_key in _INSECURE_DEFAULTS:
        issues.append("jwt_secret_key is set to a default value")
    if settings.encryption_key in _INSECURE_DEFAULTS:
        issues.append("encryption_key is set to a default value")
    default_admin_password = str(settings.default_admin_password or "").strip()
    default_admin_email = str(settings.default_admin_email or "").strip().lower()
    if default_admin_password in _INSECURE_ADMIN_PASSWORD_DEFAULTS:
        issues.append("default_admin_password is set to an insecure placeholder value")
    if settings.bootstrap_admin_once and not default_admin_password:
        issues.append(
            "bootstrap_admin_once requires a non-empty default_admin_password"
        )
    if (
        settings.bootstrap_admin_once
        and default_admin_email in _INSECURE_ADMIN_EMAIL_DEFAULTS
    ):
        issues.append("bootstrap_admin_once requires a non-default default_admin_email")
    if not issues:
        return
    msg = (
        "SECURITY WARNING — insecure default secrets detected:\n  • "
        + "\n  • ".join(issues)
        + '\nGenerate secure values: python -c "import secrets; print(secrets.token_urlsafe(64))"'
    )
    if _is_non_dev_environment(env):
        raise RuntimeError(msg)
    logger.warning(msg)


_check_secret_defaults()


def get_frontend_origins() -> list[str]:
    if settings.frontend_origins.strip():
        return [
            origin.strip()
            for origin in settings.frontend_origins.split(",")
            if origin.strip()
        ]

    origin = settings.frontend_url.rstrip("/")
    variants = {origin}
    if "127.0.0.1" in origin:
        variants.add(origin.replace("127.0.0.1", "localhost"))
    if "localhost" in origin:
        variants.add(origin.replace("localhost", "127.0.0.1"))
    return sorted(variants)


def load_admin_bootstrap_settings() -> Settings:
    import os

    fresh = Settings()
    resolved = settings.model_copy()
    if (
        os.getenv("DEFAULT_ADMIN_EMAIL") is not None
        or os.getenv("default_admin_email") is not None
    ):
        resolved = resolved.model_copy(
            update={"default_admin_email": fresh.default_admin_email}
        )
    if (
        os.getenv("DEFAULT_ADMIN_PASSWORD") is not None
        or os.getenv("default_admin_password") is not None
    ):
        resolved = resolved.model_copy(
            update={"default_admin_password": fresh.default_admin_password}
        )
    if (
        os.getenv("BOOTSTRAP_ADMIN_ONCE") is not None
        or os.getenv("bootstrap_admin_once") is not None
    ):
        resolved = resolved.model_copy(
            update={"bootstrap_admin_once": fresh.bootstrap_admin_once}
        )
    return resolved
