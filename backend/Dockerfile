# Built from the repository root: docker build -f backend/Dockerfile .
# The image is self-contained (policy, trained prefilter, example pool, eval history),
# so it runs on any container host without a separate data step.
FROM python:3.12-slim

# LibreOffice converts DOCX to PDF so Word files get page layout and highlights. It is off
# by default so the image fits small free hosts; docker-compose builds with it on.
ARG WITH_LIBREOFFICE=false
RUN apt-get update \
    && if [ "$WITH_LIBREOFFICE" = "true" ]; then \
         apt-get install -y --no-install-recommends libreoffice-writer-nogui fonts-liberation; \
       fi \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY backend/ .
COPY data/policy /data/policy
COPY data/edge_cases.yaml /data/edge_cases.yaml
COPY data/processed/splits.json data/processed/documents.jsonl data/processed/stats.json \
     data/processed/prefilter.joblib data/processed/examples.jsonl data/processed/examples.npz \
     /data/processed/
COPY eval/results /eval/results

# MALLOC_ARENA_MAX=2 stops glibc creating a memory arena per thread: ~40 MB less at peak.
ENV DATA_DIR=/data \
    EVAL_RESULTS_DIR=/eval/results \
    LLM_CACHE_DIR=/tmp/llm-cache \
    MODEL_CACHE_DIR=/tmp/models \
    PORT=8000 \
    MALLOC_ARENA_MAX=2

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
