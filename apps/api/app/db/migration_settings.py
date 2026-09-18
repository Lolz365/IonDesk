from __future__ import annotations

from pydantic import PostgresDsn, TypeAdapter, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MigrationSettings(BaseSettings):
    """Configuration required exclusively for database migrations."""

    model_config = SettingsConfigDict(extra="ignore")

    database_url: str

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        database_url = TypeAdapter(PostgresDsn).validate_python(value)
        if database_url.scheme != "postgresql+asyncpg":
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg driver")
        return value
