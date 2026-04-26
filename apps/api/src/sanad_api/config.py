from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SANAD API"
    database_url: str = "sqlite:///./sanad.db"
    storage_root: Path = Path("./storage")
    active_provider: str = "tmt_api"
    enable_demo_reset: bool = True

    # TMT API (Google TMT Hackathon 2026 /lang-translate endpoint)
    tmt_official_endpoint: str = "https://tmt.ilprl.ku.edu.np/lang-translate"
    tmt_api_key: str | None = None

    # Legacy public TMT endpoint (/translate workaround, used as fallback)
    tmt_api_endpoint: str | None = "https://tmt.ilprl.ku.edu.np"
    tmt_auth_method: str | None = None

    # Shared TMT settings
    tmt_timeout_seconds: float = Field(default=20.0, gt=0)
    tmt_provider_batch_size: int = Field(default=25, ge=1)
    tmt_enable_fallback: bool = True
    tmt_health_check_interval: int = Field(default=60, ge=5)
    tmt_rate_limit_delay: float = Field(default=0.25, ge=0)

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    model_config = SettingsConfigDict(env_prefix="SANAD_", env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
