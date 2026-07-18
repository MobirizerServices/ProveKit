"""AgentMan configuration."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./agentman.db"
    cors_origins: str = "http://localhost:3001,http://localhost:3000"

    # Hosted mode: stricter outbound-URL guarding (block private/internal ranges).
    # Leave false for local single-user use.
    hosted: bool = False

    # Encryption key for secrets at rest (any string; derived to a Fernet key).
    # Optional for local SQLite (a key file is auto-generated next to the db);
    # required for any other database.
    secret_key: str = ""

    # Optional OTLP/HTTP collector to mirror AgentMan's own runs as gen_ai spans.
    otel_export_url: str = ""

    # Public base URL shown in deployment endpoints (where /v1/d/{slug} is reachable).
    public_base_url: str = "http://localhost:8100"

    # Wall-clock cap for a single deployment invocation (seconds); 0 disables.
    deployment_timeout_s: float = 120.0

    # Optional Sentry DSN for error reporting (off when unset).
    sentry_dsn: str = ""

    # Web app base URL (for links in emails). Same-origin in prod.
    web_base_url: str = "http://localhost:3001"

    # Email (account recovery/verification). No SMTP host → links are logged, not sent.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    require_email_verification: bool = False

    # Optional Redis for paused flow-run contexts (survives workers/restarts).
    # Unset → in-memory (single-process local use).
    redis_url: str = ""

    # Max concurrent sync workers (streams run in this threadpool). Lifts Starlette's
    # ~40-token default so many more streams run at once without an async rewrite.
    thread_pool_size: int = 200

    # Quotas (protect shared infra). 0 disables a given limit.
    rate_limit_per_min: int = 120     # run requests per workspace per minute
    login_attempts_per_min: int = 10  # login attempts per email+IP per minute
    dataset_max_rows: int = 200       # rows per dataset run
    max_tokens_cap: int = 0           # hard cap on prompt max_tokens (0 = no cap)
    runs_retention: int = 1000        # keep last N runs per workspace
    max_body_bytes: int = 2_000_000   # reject request bodies larger than this
    max_flow_nodes: int = 200         # cap nodes per flow

    # Seed empty OpenAI + Anthropic example connections on first run. The keyless
    # "Demo Assistant (mock)" connection is seeded regardless of this setting.
    seed_examples: bool = True

    # A default OpenAI key can be provided to prefill the example LLM connection.
    openai_api_key: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
