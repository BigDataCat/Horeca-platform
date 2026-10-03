from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]

DEFAULT_JWT_SECRET = "change-this-in-production"
MIN_PRODUCTION_SECRET_LENGTH = 32


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str
    jwt_secret_key: str = DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    cors_origins: str = "http://localhost:5173"
    worker_poll_seconds: int = 30
    login_max_attempts: int = 10
    login_window_seconds: int = 300

    @model_validator(mode="after")
    def reject_insecure_production_secret(self) -> "Settings":
        if self.app_env.lower() in {"production", "prod"} and (
            self.jwt_secret_key == DEFAULT_JWT_SECRET
            or len(self.jwt_secret_key) < MIN_PRODUCTION_SECRET_LENGTH
        ):
            raise ValueError(
                "JWT_SECRET_KEY must be set to a unique value of at least "
                f"{MIN_PRODUCTION_SECRET_LENGTH} characters when APP_ENV=production"
            )
        return self

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
