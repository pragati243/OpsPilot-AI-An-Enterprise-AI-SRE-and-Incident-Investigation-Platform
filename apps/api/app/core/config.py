from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, sourced from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"

    app_secret_key: str = "dev-only-change-me"
    jwt_secret_key: str = "dev-only-change-me-too"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_minutes: int = 60 * 24 * 7

    database_url: str = "postgresql+asyncpg://opspilot:opspilot@localhost:5544/opspilot"
    database_echo: bool = False

    redis_url: str = "redis://localhost:6399/0"

    groq_api_key: str = Field(default="")
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "llama-3.3-70b-versatile"

    langfuse_public_key: str = Field(default="")
    langfuse_secret_key: str = Field(default="")
    langfuse_host: str = "https://cloud.langfuse.com"

    cors_allow_origins: list[str] = ["http://localhost:5173"]

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
