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

    # Optional Redis for paused flow-run contexts (survives workers/restarts).
    # Unset → in-memory (single-process local use).
    redis_url: str = ""

    # Quotas (protect shared infra). 0 disables a given limit.
    rate_limit_per_min: int = 120     # run requests per workspace per minute
    dataset_max_rows: int = 200       # rows per dataset run
    max_tokens_cap: int = 0           # hard cap on prompt max_tokens (0 = no cap)
    runs_retention: int = 1000        # keep last N runs per workspace

    # Optional: seed a Magari example connection set on first run.
    seed_examples: bool = True
    magari_backend_url: str = "http://127.0.0.1:8000"
    magari_mcp_url: str = "http://127.0.0.1:8765/mcp"

    # A default OpenAI key can be provided to prefill the example LLM connection.
    openai_api_key: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
