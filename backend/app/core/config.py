"""Application settings, read from environment variables (prefix AGENTGUARD_) and .env."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
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
    tool_timeout_seconds: float = Field(default=5.0, gt=0)
    approval_ttl_seconds: int = Field(default=3600, gt=0)
    max_request_bytes: int = Field(default=64 * 1024, gt=0)

    # SHA-256 hex of the admin key that protects /api/v1/agents. Empty disables admin APIs.
    admin_api_key_hash: str = ""

    @field_validator("admin_api_key_hash")
    @classmethod
    def _is_sha256_or_empty(cls, v: str) -> str:
        if v and (len(v) != 64 or any(c not in "0123456789abcdef" for c in v)):
            raise ValueError("admin_api_key_hash must be a lowercase SHA-256 hex digest")
        return v

    # Folder holding the built admin dashboard, served at /dashboard. Empty: not served.
    dashboard_dir: str = ""

    # Origins allowed to call the admin APIs from a browser, e.g. a dashboard on Vercel:
    # ["https://agentguard-dashboard.vercel.app"]. Empty (default): no cross-origin access.
    cors_origins: list[str] = []

    @field_validator("cors_origins")
    @classmethod
    def _exact_origins(cls, v: list[str]) -> list[str]:
        for origin in v:
            scheme, _, rest = origin.partition("://")
            if scheme not in ("https", "http") or not rest or "/" in rest or "*" in rest:
                raise ValueError(
                    f"cors_origins needs exact origins like https://host, got {origin!r}"
                )
        return v

    # Firewall action per entity type, e.g. {"EMAIL": "allow"}. Default: secrets block, PII redacts.
    firewall_actions: dict[str, Literal["block", "redact", "allow"]] = {}

    @property
    def docs_enabled(self) -> bool:
        return self.env != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
