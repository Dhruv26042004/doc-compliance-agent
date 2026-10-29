from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    database_url: str = "postgresql+psycopg://compliance:compliance@localhost:5432/compliance"
    cors_origins: list[str] = ["http://localhost:3000"]  # env: CORS_ORIGINS='["https://you.vercel.app"]'
    cors_origin_regex: str | None = None  # e.g. https://.*[.]vercel[.]app for preview deployments
    data_dir: Path = REPO_ROOT / "data"
    storage_dir: Path = REPO_ROOT / "storage"  # uploaded and converted files (file_storage=disk)
    # "disk" or "database". Use database on hosts whose disk is wiped on restart (Render free).
    file_storage: str = "disk"
    # Convert DOCX to PDF with LibreOffice when installed. Off on small hosts: it needs ~200 MB extra RAM.
    docx_convert: bool = True
    max_upload_mb: int = 20
    eval_results_dir: Path = REPO_ROOT / "eval" / "results"
    # New analyses use this policy version. Evaluate a new version on the test set first.
    active_policy_version: int = 1

    llm_model: str = "gemini-3.5-flash-lite"  # free tier: gemini-3.5-flash allows only 20 requests/day
    llm_cache_dir: Path = REPO_ROOT / "eval" / "cache"  # responses keyed by request hash
    model_cache_dir: Path = REPO_ROOT / ".cache" / "models"  # downloaded embedding model
    llm_max_workers: int = 4
    # Pipeline stages used by the API (the eval script sets these per run).
    pipeline_prefilter: bool = True
    pipeline_fewshot: bool = True
    pipeline_verify: bool = True
    # Verified findings at or above this confidence are decided automatically. Chosen on
    # dev_core as the lowest threshold whose automatic findings reach 95% precision.
    routing_auto_threshold: float = 0.99
    # Set on public deployments: then upload/analyze/batch/delete need the X-Admin-Token header.
    admin_token: str | None = None
    gemini_api_key: str = ""


    @field_validator("database_url")
    @classmethod
    def _use_psycopg_driver(cls, url: str) -> str:
        # Hosted Postgres (Neon, Render, Supabase) hands out postgres:// or postgresql:// URLs.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
