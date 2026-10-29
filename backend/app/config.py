from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    database_url: str = "postgresql+psycopg://compliance:compliance@localhost:5432/compliance"
    cors_origins: list[str] = ["http://localhost:3000"]
    data_dir: Path = REPO_ROOT / "data"
    storage_dir: Path = REPO_ROOT / "storage"  # uploaded and converted files
    max_upload_mb: int = 20
    eval_results_dir: Path = REPO_ROOT / "eval" / "results"
    # New analyses use this policy version. Evaluate a new version on the test set first.
    active_policy_version: int = 1

    llm_provider: str = "gemini"
    llm_model: str = "gemini-3.5-flash-lite"  # free tier: gemini-3.5-flash allows only 20 requests/day
    llm_cache_dir: Path = REPO_ROOT / "eval" / "cache"  # responses keyed by request hash
    llm_max_workers: int = 4
    # Pipeline stages used by the API (the eval script sets these per run).
    pipeline_prefilter: bool = True
    pipeline_fewshot: bool = True
    pipeline_verify: bool = True
    # Verified findings at or above this confidence are decided automatically. Chosen on
    # dev_core as the lowest threshold whose automatic findings reach 95% precision.
    routing_auto_threshold: float = 0.99
    gemini_api_key: str = ""
    groq_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"


@lru_cache
def get_settings() -> Settings:
    return Settings()
