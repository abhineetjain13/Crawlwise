# Centralized application settings.
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BASE_DIR.parent


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
    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24
    encryption_key: str = "change-me-32-bytes-minimum-change-me"
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
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    nvidia_api_key: str = ""
    request_id_header: str = "X-Request-ID"
    crawl_log_db_min_level: str = "info"
    crawl_log_db_url_progress_sample_rate: int = 4
    crawl_log_db_max_rows_per_run: int = 1000
    crawl_log_file_enabled: bool = True
    crawl_log_file_dir: Path = Field(default=BASE_DIR / "artifacts" / "run_logs")
    default_admin_email: str = "admin@admin.com"
    default_admin_password: str | None = None
    bootstrap_admin_once: bool = False
    # When false, POST /api/auth/register returns 403 (POC single-admin dev). Enable for production multi-tenant.
    registration_enabled: bool = False


settings = Settings()


def _resolve_project_path(value: str | Path, *, anchor: Path = PROJECT_ROOT) -> Path:
    raw_path = Path(value)
    return raw_path if raw_path.is_absolute() else (anchor / raw_path).resolve()

settings.artifacts_dir = _resolve_project_path(
    settings.artifacts_dir, anchor=PROJECT_ROOT
)
settings.acquisition_cache_dir = _resolve_project_path(
    settings.acquisition_cache_dir, anchor=PROJECT_ROOT
)
settings.cookie_store_dir = _resolve_project_path(
    settings.cookie_store_dir, anchor=PROJECT_ROOT
)
settings.crawl_log_file_dir = _resolve_project_path(
    settings.crawl_log_file_dir, anchor=PROJECT_ROOT
)


# ---------------------------------------------------------------------------
# Security guard: reject default secrets in non-dev environments
# ---------------------------------------------------------------------------
_INSECURE_DEFAULTS = {"change-me", "change-me-32-bytes-minimum-change-me"}
_INSECURE_ADMIN_PASSWORD_DEFAULTS = {"YourSecurePassword123!"}
_INSECURE_ADMIN_EMAIL_DEFAULTS = {"admin@admin.com"}


def _check_secret_defaults() -> None:
    """Warn loudly (or crash in production) if default secrets are still set."""
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
        issues.append("bootstrap_admin_once requires a non-empty default_admin_password")
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
    if env == "production":
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
