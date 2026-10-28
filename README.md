# Document Compliance System

Checks contracts against a written, numbered policy. Every decision cites the exact rule and the quoted clause it relies on, and uncertain cases are routed to a human reviewer.

> **Status:** Phases 0–1 complete. See the roadmap below.

## Stack

| Layer | Tech |
|---|---|
| API | Python 3.12, FastAPI, SQLAlchemy |
| Database | PostgreSQL 16 + pgvector |
| Frontend | Next.js 15 (App Router), TypeScript, Tailwind CSS |
| LLM | Gemini / Groq / Ollama (swappable, from Phase 3) |
| Packaging | Docker Compose |

## Run it

```bash
cp .env.example .env        # add an LLM API key when Phase 3 lands
docker compose up --build
```

- Web UI: http://localhost:3000
- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

### Backend without Docker

```bash
docker compose up -d db
cd backend
uv sync
uv run uvicorn app.main:app --reload
uv run pytest
```

### Build the dataset

```bash
cd backend
uv run python -m scripts.download_cuad   # CUAD v1, CC BY 4.0
uv run python -m scripts.build_dataset   # clauses, labels, frozen splits
```

See [data/README.md](data/README.md) for the policy, label method, splits, and per-rule counts.

### Frontend without Docker

```bash
cd frontend
npm install
npm run dev
```

## Project layout

```
backend/     FastAPI app (app/) and tests
frontend/    Next.js reviewer interface and dashboard
data/        policy, datasets, and dev/test splits
eval/        evaluation scripts and results
docker/      database init scripts
```

## Roadmap

- [x] **Phase 0:** Skeleton: Docker Compose, API health check, frontend status page
- [x] **Phase 1:** Policy (numbered, testable rules) and dataset (CUAD + hand-labeled edge cases), with fixed dev/test splits
- [ ] **Phase 2:** PDF/DOCX parsing into clauses, with page and position data
- [ ] **Phase 3:** LLM classifier with structured output; per-rule precision/recall baseline
- [ ] **Phase 4:** Tiered filtering, few-shot retrieval, and a span verifier
- [ ] **Phase 5:** Confidence routing and the reviewer interface
- [ ] **Phase 6:** Audit log, policy versioning, and a metrics dashboard
- [ ] **Phase 7:** Batch mode, seed data, and the limitations page
