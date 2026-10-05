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
    email_backend: str = "console"  # smtp | console | memory
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "HoReCa Platform <no-reply@localhost>"
    smtp_starttls: bool = True
    app_base_url: str = "http://localhost:5173"
    password_reset_minutes: int = 60
    invite_hours: int = 72
    audit_retention_days: int | None = None  # None keeps the audit log forever
    webhook_event_retention_days: int | None = 90
    http_connector_allow_private: bool = False  # allow loopback/private hosts (development and tests only)
    http_connector_timeout_seconds: int = 20
    trial_days: int | None = None  # new companies' subscription expires after this many days (None = never)
    invoice_reader: str = "local"  # local | ollama | claude  (used where the reading actually happens)
    invoice_reader_url: str | None = None  # send PDFs/photos to a separate reader service, e.g. http://invoice-reader:8100
    invoice_reader_token: str | None = None  # shared secret between the API/worker and the reader service
    invoice_reader_timeout_seconds: int = 180
    invoice_read_async: bool = False  # True: uploads return at once and the worker reads them in the background
    invoice_read_max_attempts: int = 5
    ollama_url: str | None = None  # e.g. http://localhost:11434
    ollama_model: str = "qwen2.5:7b-instruct"
    ollama_timeout_seconds: int = 180
    anthropic_api_key: str | None = None  # enables AI reading of PDF/photo invoices
    invoice_ai_model: str = "claude-opus-5-5"
    imap_host: str | None = None
    imap_port: int = 993
    imap_user: str | None = None
    imap_password: str | None = None
    imap_folder: str = "INBOX"
    invoice_inbox_address: str | None = None  # e.g. invoices@example.com; companies use invoices+TOKEN@example.com
    invoice_poll_seconds: int = 120
    default_plan: str = "business"
    admin_api_key: str | None = None
    metrics_token: str | None = None
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
        if self.app_env.lower() in {"production", "prod"} and self.email_backend == "console":
            # Safe default for production: use SMTP when configured, otherwise do not log secrets.
            self.email_backend = "smtp"
        return self

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,  # a blank value in .env/compose means "use the default"
    )


settings = Settings()
