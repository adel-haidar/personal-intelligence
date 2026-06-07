from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",  # silently ignores vars not defined as fields
    )

    db_host: str = "localhost"
    db_name: str = "postgres"
    db_user: str = "postgres"
    db_password: str = ""

    secret_key: str = ""

    aws_region: str = "eu-central-1"

    upload_dir: str = "/uploads"


@lru_cache
def get_settings() -> Settings:
    return Settings()
