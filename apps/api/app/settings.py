from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "production"
    database_url: str = Field(min_length=1, repr=False)
    redis_url: str = Field(min_length=1, repr=False)
    object_storage_endpoint: str = Field(min_length=1)
    object_storage_region: str = "us-east-1"
    object_storage_access_key: str = Field(min_length=1, repr=False)
    object_storage_secret_key: str = Field(min_length=1, repr=False)
    object_storage_bucket: str = Field(min_length=1)
    readiness_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
