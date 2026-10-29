# Document Compliance System

Checks contracts against a written, numbered policy. Every decision cites the exact rule and the quoted clause it relies on, and uncertain cases are routed to a human reviewer.

> **Status:** Phases 0–5 complete. See the roadmap below.

## Stack

| Layer | Tech |
|---|---|
| API | Python 3.12, FastAPI, SQLAlchemy |
| Database | PostgreSQL 16 + pgvector |
| Frontend | Next.js 15 (App Router), TypeScript, Tailwind CSS |
| LLM | Gemini 3.5 Flash-Lite (free tier), structured JSON output |
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

## Document parsing

Upload a PDF or DOCX with `POST /documents`. The file is split into clauses, and each clause keeps its character offsets and its line rectangles on the page, so any clause (or any quoted span inside one) can be highlighted.

- **PDF:** PyMuPDF reads the text layer. Running headers, footers and page numbers are removed; paragraphs broken across pages are rejoined; headings and numbered sections that share a layout block are split apart.
- **DOCX:** converted to PDF with headless LibreOffice (installed in the Docker image), then parsed like any PDF. Without LibreOffice it falls back to text-only parsing with python-docx.
- **Not supported:** scanned PDFs with no text layer (rejected with a clear error) and password-protected PDFs.

**Quality on real contracts** (`uv run python -m scripts.check_parsing`, 40 CUAD dev PDFs, 875 pages): all 40 parsed, **99.7%** of lawyer-annotated CUAD spans recovered from our text, about 3 ms per page.

| Endpoint | Purpose |
|---|---|
| `POST /documents` | Upload and parse (201; returns 200 with the existing record for identical bytes) |
| `GET /documents` | List documents with clause counts |
| `GET /documents/{id}` | Text, pages and clauses with rectangles |
| `GET /documents/{id}/file` | The PDF rendition, for the viewer |
| `DELETE /documents/{id}` | Remove the record and its files |

> PyMuPDF is AGPL-licensed. That is fine for an open-source portfolio project; a commercial deployment would need its commercial license or a swap to `pdfplumber`.

## Baseline results (Phase 3)

One LLM pass per contract: clauses are sent in batches of up to 40 with the full policy, and the model returns, for each matching clause, the rule ID, a verbatim quote, an explanation, and a confidence score. The prompt lives in [`backend/app/prompts/classify_v1.md`](backend/app/prompts/classify_v1.md); every result records the model version, prompt hash, and policy version.

**Held-out test set** (`test_core`: 30 contracts, 2,331 clauses, `gemini-3.5-flash-lite`, prompt v1):

| Rule | Precision | Recall | F1 | TP / FP / FN |
|---|--:|--:|--:|--:|
| R-01 Limitation of liability required | 77% | 56% | 65% | 20 / 6 / 16 |
| R-02 Uncapped liability prohibited | 50% | 80% | 62% | 4 / 4 / 1 |
| R-03 Governing law required | 87% | 93% | 90% | 27 / 4 / 2 |
| R-04 Termination for convenience | 50% | 62% | 56% | 5 / 5 / 3 |
| R-05 Renewal terms | 64% | 100% | 78% | 7 / 4 / 0 |
| R-06 Non-compete / customer non-solicit | 75% | 60% | 67% | 9 / 3 / 6 |
| R-07 Exclusivity | 59% | 65% | 62% | 13 / 9 / 7 |
| R-08 Assignment / change of control | 100% | 73% | 85% | 30 / 0 / 11 |
| R-09 Transfer of IP ownership | 60% | 33% | 43% | 6 / 4 / 12 |
| R-10 Most favored nation | 100% | 67% | 80% | 2 / 0 / 1 |
| R-11 Liquidated damages | 100% | 33% | 50% | 2 / 0 / 4 |
| R-12 Audit rights | 93% | 78% | 85% | 14 / 1 / 4 |
| **Micro average** | **78%** | **67%** | **72%** | 139 / 40 / 67 |

- **Missing required clauses (document level):** missing liability cap detected with 100% precision / 87% recall; missing governing law 100% / 100%.
- **Quote validity:** 92% of quotes were found verbatim in their clause; the other 8% are candidate hallucinations for the Phase 4 verifier.
- **Cost:** 77 requests, 406k input / 23k output tokens, 12 minutes on the free tier.
- **Dev set** (`dev_core`, used for analysis): 72% precision / 69% recall. Hand-labeled edge cases: 100% / 100% (dev), 100% / 93% (test).

Full tables: [`eval/results/`](eval/results/). Method and caveats: [`eval/README.md`](eval/README.md).

## Accuracy work (Phase 4)

The decision pipeline is now four stages, each switchable for measurement (`scripts/evaluate.py --prefilter --fewshot --verify`):

1. **Tier-1 prefilter.** A TF-IDF + logistic regression model per rule, trained on dev contracts outside `dev_core`. Clauses that score low for every rule are decided "no match" without an LLM call. The threshold was chosen on out-of-fold training data: it skips about half the clauses and keeps 97% of labeled ones.
2. **Retrieved examples.** For each batch, the nearest lawyer-highlighted CUAD spans and "hard negatives" (suspicious-looking clauses that match nothing) are added to the prompt. Embeddings: `bge-small-en` via ONNX on CPU, 7,205 examples from training contracts only.
3. **LLM classifier.** Unchanged from Phase 3.
4. **Verifier.** Findings whose quote is not in the clause are rejected (on dev those were right only 27% of the time). A second LLM call re-reads each remaining finding against the rule definition. Rejected findings are kept with the reason, for human review.

**Ablation on the dev set** (`dev_core`, where choices were made):

| Pipeline | Precision | Recall | F1 | LLM calls |
|---|--:|--:|--:|--:|
| Baseline | 72% | 69% | 70% | 75 |
| + prefilter | 74% | 67% | 70% | 50 |
| + prefilter + verifier | 82% | 62% | 71% | 81 |
| + prefilter + examples | 73% | 70% | 72% | 50 |
| **+ prefilter + examples + verifier** | **85%** | 68% | **76%** | 82 |
| Small model alone (no LLM) | 72% | 64% | – | 0 |

**Held-out test set** (`test_core`, run once with the configuration chosen on dev), with 95% intervals from a paired bootstrap over contracts (`scripts/compare_runs.py`):

| | Baseline | Final pipeline | Change (95% interval) |
|---|--:|--:|--:|
| Precision | 78% | 80% | +2.8% (−3.9% to +9.3%) |
| Recall | 67% | 64% | −3.4% (−10.1% to +3.0%) |
| F1 | 72% | 71% | −0.9% (−5.1% to +3.6%) |
| Quotes found verbatim | 92% | **100%** | |
| Wall time | 714s | **303s** | 2.4× faster |

**What this shows.** On dev, the precision gain (+13 points) and F1 gain (+5 points) are statistically significant. On the held-out test set, accuracy did not change significantly. The dev improvement did not replicate, and this README reports that instead of a best-case number. What did carry over: every finding now cites text that exists in the contract, runs are 2.4× faster, and half the clauses never reach the LLM. A small TF-IDF model is roughly as accurate as the LLM on this task, which suggests the ceiling is set partly by CUAD label noise and clause-level scoring rather than by the model.

## Human in the loop (Phase 5)

Every analysis is stored as a set of **decisions**, each routed either to an automatic outcome or to a reviewer:

| Decision | Proposed outcome | Route |
|---|---|---|
| Finding with a verified quote, confidence ≥ 0.99 | Clause matches the rule | **Automatic** |
| Finding below the threshold | Clause matches the rule | Review |
| Finding the verifier rejected | Clause does not match | Review |
| Possible miss: the small model flags a rule the LLM did not | Clause does not match | Review |
| Required rule with no matching clause | Document violates the rule | Review (high severity) |

Confidence can only route findings that exist, so the possible-miss check is the safety net for recall. The threshold (0.99) is the lowest value whose automatic findings reach 95% precision on `dev_core`.

**Routing results** (thresholds fixed on dev; reviewers assumed to decide correctly):

| | Dev | Held-out test |
|---|--:|--:|
| Clauses decided with no human | 89% | **90%** |
| Candidate decisions made automatically | 41% | **43%** |
| Precision of automatic decisions | 98.3% | **97.3%** |
| Recall: model alone → with review | 68% → 79% | **64% → 78%** |

**Reviewer workflow** (Next.js at http://localhost:3000):

- **Documents:** upload a PDF or DOCX, run the check, and see how many decisions await review.
- **Review queue:** every pending decision across documents, filterable by rule.
- **Document review:** the contract with color-coded highlights on the exact quoted text (red violation, amber flag, green satisfied, blue awaiting review), next to each decision's proposal, quote, explanation, confidence, routing reason, and the rule's definition. **Approve** or **Override**; an override requires a reason.
- **Per-rule status** for the document updates as decisions are reviewed: violated, flagged, satisfied, clear, or pending.

Every review is stored on the decision (reviewer, reason, timestamp) and as a new **label** (`GET /labels`), ready to retrain the prefilter and grow the example pool.

| Endpoint | Purpose |
|---|---|
| `POST /documents/{id}/analyze` | Run the pipeline, route and store every decision |
| `GET /documents/{id}/analysis` | Latest analysis with decisions and per-rule status |
| `GET /reviews/queue?rule_id=` | Pending decisions across documents |
| `POST /decisions/{id}/review` | `{"action": "approve" \| "override", "reviewer", "reason"}` |
| `GET /labels` | Every human-confirmed label |
| `GET /policy` | Rule definitions for display |

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
- [x] **Phase 2:** PDF/DOCX parsing into clauses, with page and position data
- [x] **Phase 3:** LLM classifier with structured output; per-rule precision/recall baseline
- [x] **Phase 4:** Tiered filtering, few-shot retrieval, and a span verifier
- [x] **Phase 5:** Confidence routing and the reviewer interface
- [ ] **Phase 6:** Audit log, policy versioning, and a metrics dashboard
- [ ] **Phase 7:** Batch mode, seed data, and the limitations page
