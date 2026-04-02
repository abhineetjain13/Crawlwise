# Centralized application settings.
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "CrawlerAI"
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    frontend_url: str = "http://127.0.0.1:3000"
    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24
    encryption_key: str = "change-me-32-bytes-minimum-change-me"
    database_url: str = "sqlite+aiosqlite:///./crawlerai.db"
    artifacts_dir: Path = Field(default=Path("./backend/artifacts"))
    acquisition_cache_dir: Path = Field(default=Path("./backend/artifacts/acquisition_cache"))
    playwright_headless: bool = True
    worker_poll_interval_seconds: float = 1.0
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    groq_api_key: str = ""


settings = Settings()
