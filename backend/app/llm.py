"""Structured-output LLM calls with an on-disk cache and retry on rate limits.

Every response is cached under a hash of (provider, model, prompts, schema), so
re-running an evaluation never pays for the same request twice.
"""

import hashlib
import json
import logging
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from pydantic import BaseModel

from app.config import get_settings

log = logging.getLogger(__name__)

RETRYABLE = {429, 500, 502, 503, 504}


@dataclass
class LLMResult:
    data: dict  # validated against the schema
    model_version: str  # what actually served the request (aliases move over time)
    input_tokens: int
    output_tokens: int
    latency_s: float
    cached: bool = False


class LLMError(RuntimeError):
    pass


class DailyQuotaExceeded(LLMError):
    pass


def _daily_quota(exc) -> str | None:
    """The quota id if a 429 is a per-day limit, which no amount of retrying will fix today."""
    try:
        for detail in exc.details["error"]["details"]:
            for v in detail.get("violations", []):
                if "PerDay" in v.get("quotaId", ""):
                    return f"{v['quotaId']} (limit {v.get('quotaValue', '?')})"
    except (KeyError, TypeError):
        pass
    return None


def _retry_delay(exc) -> float | None:
    """The server's suggested wait from a 429 RetryInfo detail, e.g. "17s"."""
    try:
        for detail in exc.details["error"]["details"]:
            if "retryDelay" in detail:
                return min(120.0, float(detail["retryDelay"].rstrip("s")))
    except (KeyError, TypeError, ValueError):
        pass
    return None


class GeminiClient:
    provider = "gemini"

    def __init__(self, model: str | None = None, api_key: str | None = None, cache_dir: Path | None = None):
        from google import genai

        settings = get_settings()
        self.model = model or settings.llm_model
        key = api_key or settings.gemini_api_key
        if not key:
            raise LLMError("GEMINI_API_KEY is not set (see .env.example)")
        self._client = genai.Client(api_key=key)
        self.cache_dir = cache_dir or settings.llm_cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, system: str, prompt: str, schema: type[BaseModel]) -> str:
        payload = json.dumps(
            [self.provider, self.model, system, prompt, schema.model_json_schema()], sort_keys=True
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def generate(self, system: str, prompt: str, schema: type[BaseModel], max_attempts: int = 8) -> LLMResult:
        cache_file = self.cache_dir / f"{self._key(system, prompt, schema)}.json"
        if cache_file.exists():
            hit = LLMResult(**json.loads(cache_file.read_text(encoding="utf-8")))
            hit.cached = True
            return hit

        from google.genai import errors, types

        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0,
        )
        for attempt in range(1, max_attempts + 1):
            start = time.perf_counter()
            try:
                resp = self._client.models.generate_content(model=self.model, contents=prompt, config=config)
            except errors.APIError as exc:
                if exc.code == 429 and (quota := _daily_quota(exc)):
                    raise DailyQuotaExceeded(f"{self.model}: daily free-tier quota used up: {quota}") from exc
                if exc.code not in RETRYABLE or attempt == max_attempts:
                    raise LLMError(f"{self.model}: {exc.code} {exc.message}") from exc
                wait = _retry_delay(exc) or min(90, 5 * 2 ** (attempt - 1))
                wait += random.uniform(0, 3)  # jitter so parallel workers don't retry in lockstep
                log.warning("%s returned %s; retrying in %.0fs (attempt %d)", self.model, exc.code, wait, attempt)
                time.sleep(wait)
                continue

            if resp.parsed is None:  # truncated or malformed JSON: retry once more, then fail
                if attempt == max_attempts:
                    raise LLMError(f"{self.model}: response did not match the schema")
                continue
            usage = resp.usage_metadata
            result = LLMResult(
                data=resp.parsed.model_dump(),
                model_version=resp.model_version or self.model,
                input_tokens=usage.prompt_token_count or 0,
                output_tokens=(usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0),
                latency_s=round(time.perf_counter() - start, 2),
            )
            cache_file.write_text(json.dumps(asdict(result)), encoding="utf-8")
            return result
        raise LLMError(f"{self.model}: no valid response after {max_attempts} attempts")
