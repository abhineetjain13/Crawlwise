# Centralized application settings.
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "CrawlerAI"
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    frontend_url: str = "http://127.0.0.1:3000"
    frontend_origins: str = ""
    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24
    encryption_key: str = "change-me-32-bytes-minimum-change-me"
    database_url: str = f"sqlite+aiosqlite:///{(BASE_DIR / 'crawlerai.db').as_posix()}"
    artifacts_dir: Path = Field(default=BASE_DIR / "artifacts")
    acquisition_cache_dir: Path = Field(default=BASE_DIR / "artifacts" / "acquisition_cache")
    cookie_store_dir: Path = Field(default=BASE_DIR / "cookie_store")
    playwright_headless: bool = True
    worker_poll_interval_seconds: float = 1.0
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    nvidia_api_key: str = ""


settings = Settings()


# ---------------------------------------------------------------------------
# Security guard: reject default secrets in non-dev environments
# ---------------------------------------------------------------------------
_INSECURE_DEFAULTS = {"change-me", "change-me-32-bytes-minimum-change-me"}


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
    if not issues:
        return
    msg = (
        "SECURITY WARNING — insecure default secrets detected:\n  • "
        + "\n  • ".join(issues)
        + "\nGenerate secure values: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
    )
    if env == "production":
        raise RuntimeError(msg)
    logger.warning(msg)


_check_secret_defaults()



def get_frontend_origins() -> list[str]:
    if settings.frontend_origins.strip():
        return [origin.strip() for origin in settings.frontend_origins.split(",") if origin.strip()]

    origin = settings.frontend_url.rstrip("/")
    variants = {origin}
    if "127.0.0.1" in origin:
        variants.add(origin.replace("127.0.0.1", "localhost"))
    if "localhost" in origin:
        variants.add(origin.replace("localhost", "127.0.0.1"))
    return sorted(variants)
