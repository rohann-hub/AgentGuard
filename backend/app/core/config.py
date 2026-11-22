"""Application settings, read from environment variables (prefix AGENTGUARD_) and .env."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTGUARD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AgentGuard"
    version: str = "0.1.0"
    env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+psycopg://agentguard:agentguard@localhost:5432/agentguard"
    opa_url: str = "http://localhost:8181"

    # How long readiness checks wait on each dependency before calling it down.
    dependency_timeout_seconds: float = Field(default=2.0, gt=0)

    @property
    def docs_enabled(self) -> bool:
        return self.env != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
