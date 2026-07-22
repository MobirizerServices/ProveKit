"""ProveKit configuration."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./provekit.db"
    cors_origins: str = "http://localhost:3001,http://localhost:3000"

    # Hosted mode: a login wall, secure cookies, and stricter outbound-URL guarding.
    hosted: bool = False

    # Signs session/reset/verify tokens (any string → a Fernet key). Optional for local
    # SQLite (a key file is auto-generated); required for any other database.
    secret_key: str = ""

    # Optional OTLP/HTTP collector to mirror captured runs to another backend.
    otel_export_url: str = ""

    # Optional Sentry DSN for error reporting (off when unset).
    sentry_dsn: str = ""

    # Web app base URL (for links in emails).
    web_base_url: str = "http://localhost:3001"

    # Email (account recovery / verification). No SMTP host → links are logged, not sent.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    require_email_verification: bool = False

    # Optional Redis (shared rate-limit windows across workers). Unset → in-memory.
    redis_url: str = ""

    thread_pool_size: int = 200

    # Durable accept (services/spool.py). Every ingest batch is staged to disk before it is
    # acknowledged, so a database outage can't destroy data the exporter believes was taken.
    # Empty dir → a temp-dir default; on by default because losing spans is the one failure
    # an observability tool cannot have.
    spool_enabled: bool = True
    spool_dir: str = ""
    spool_drain_seconds: float = 5.0   # how often the background drainer retries staged batches
    # Backpressure: refuse new batches once this many are already waiting to land. A spike
    # then gets a retriable 503 instead of becoming unbounded disk and DB pressure. 0 = off.
    spool_max_depth: int = 5000

    # Mask PII (emails, cards, SSNs, phones, common secret keys) in captured span
    # input/output/error before it's stored. Off by default; a safety net for hosted use.
    redact_pii: bool = False

    # Bootstrap platform operators: any account whose email is in this comma-list is treated
    # as a superuser (admin console), even before the DB flag is set. e.g. "you@co.com".
    superuser_emails: str = ""

    @property
    def superuser_email_list(self) -> list[str]:
        return [e.strip().lower() for e in self.superuser_emails.split(",") if e.strip()]

    # Quotas (protect shared infra). 0 disables a given limit.
    ingest_rate_per_min: int = 600     # trace-ingest requests per project per minute
    login_attempts_per_min: int = 10   # login attempts per email+IP per minute
    playground_monthly_usd_cap: float = 25.0   # per-project cap on playground/replay spend; 0 = off
    runs_retention: int = 10000        # keep last N spans per project (older ones pruned)
    # Per-account ceilings for a hosted tier. 0 = unlimited, which is the default so that a
    # self-hosted instance never starts refusing its owner's own data after an upgrade.
    monthly_span_quota: int = 0        # spans an account may ingest per calendar month
    max_projects_per_account: int = 0  # projects one account may own
    max_body_bytes: int = 2_000_000    # reject request bodies larger than this

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
