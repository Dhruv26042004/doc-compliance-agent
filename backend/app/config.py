from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    database_url: str = "postgresql+psycopg://compliance:compliance@localhost:5432/compliance"
    cors_origins: list[str] = ["http://localhost:3000"]
    data_dir: Path = REPO_ROOT / "data"

    # LLM provider settings are read now but only used from Phase 3 onward.
    llm_provider: str = "gemini"
    gemini_api_key: str = ""
    groq_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"


@lru_cache
def get_settings() -> Settings:
    return Settings()
