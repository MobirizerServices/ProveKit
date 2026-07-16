"""AgentMan configuration."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./agentman.db"
    cors_origins: str = "http://localhost:3001,http://localhost:3000"

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
