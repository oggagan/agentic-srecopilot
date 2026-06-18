"""Central configuration, loaded from the repo root .env (gitignored)."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# repo root = backend/app/config.py -> app -> backend -> root
_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # model provider: deepseek | anthropic | bedrock
    llm_provider: str = "deepseek"

    # deepseek (openai compatible)
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_reasoner_model: str = "deepseek-reasoner"

    # cost guardrail
    daily_max_spend_usd: float = 2.0

    # fleet access (read only for the POC)
    fleet_ssh_helper: str = ""
    fleet_target_host: str = ""
    fleet_environment: str = "prod"

    # observability
    otel_enabled: bool = True
    phoenix_enabled: bool = True
    phoenix_otlp_endpoint: str = "http://localhost:4317"

    # database + RAG
    database_url: str = "postgresql://postgres:postgres@localhost:5432/srecopilot"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    rag_top_k: int = 5


settings = Settings()
