import pytest
from pydantic import ValidationError

from app.core.config import DEFAULT_JWT_SECRET, Settings

DB = "postgresql+psycopg://u:p@localhost/db"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)


def make(**kwargs):
    return Settings(_env_file=None, database_url=DB, **kwargs)


def test_development_allows_default_secret():
    assert make().jwt_secret_key == DEFAULT_JWT_SECRET


@pytest.mark.parametrize("env", ["production", "PRODUCTION", "prod"])
def test_production_rejects_default_secret(env):
    with pytest.raises(ValidationError):
        make(app_env=env)


def test_production_rejects_short_secret():
    with pytest.raises(ValidationError):
        make(app_env="production", jwt_secret_key="short")


def test_production_accepts_strong_secret():
    assert make(app_env="production", jwt_secret_key="x" * 40).app_env == "production"
