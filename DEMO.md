# Demo script (about 3 minutes)

A shot list for the portfolio screen recording. Record at 1080p with the browser zoomed to 110%, and use Windows' built-in recorder (Win + Alt + R) or OBS.

## Before recording

```bash
docker compose up -d
cd backend && uv run python -m scripts.seed_demo --reset   # skip if already seeded
```

Open http://localhost:3000 and http://localhost:8000/docs in two tabs (or the live site, https://doc-compliance-agent.vercel.app and https://compliance-api-hk1j.onrender.com/docs; load both a minute early so they are awake). Close other tabs and notifications.

## Shots

**1. The problem (15 s).** Documents page.
> "Legal teams check every vendor contract against a checklist: liability caps, non-competes, IP assignment. This system does the first pass, explains every decision with the exact clause, and sends only uncertain cases to a person."

**2. The document list (15 s).** Point at the status column ("4 to review", "Complete").
> "Seven contracts: six real ones from the CUAD dataset, which the model never saw during tuning, and one Word NDA."

**3. A contract under review (60 s).** Open the contract with the most pending items.
- Point at the highlights: red is a violation, amber a flag, green satisfied, blue waiting for a human.
- Click a pending decision in the side panel; the PDF scrolls to the highlighted quote.
- Read the proposal, the quote, and the explanation. Open the rule definition.
- Point at "Why: Below the confidence threshold" or "Small model flags a possible miss".
> "Every decision cites a rule and quotes the contract word for word. High-confidence, verified findings are decided automatically. Low-confidence ones, and clauses where two models disagree, come here."
- Click **Approve** on one. Type a reason and click **Override** on another. Point at the per-rule status updating.

**4. The queue (15 s).** Review queue page; filter by one rule.
> "Reviewers work through one queue across all documents. Every review becomes a new labeled example."

**5. The dashboard (30 s).** Dashboard page.
- Point at the tiles: share of clauses decided with no human, automatic decisions, override rate.
- Point at precision/recall across evaluation runs (switch the split to `test_core`).
> "On held-out contracts, 43% of the decisions that matter are made automatically at 97% precision, and review lifts recall from 64% to 78%."

**6. Audit (15 s).** API docs tab: run `GET /audit/verify`, then `GET /audit` with a document id.
> "Every upload, decision, and review is in an append-only, hash-chained audit log, with the model version, prompt hash, and policy version that produced it."

**7. Close (10 s).** README results table, or `LIMITATIONS.md`.
> "It is not perfect: it misses some clauses, and this page says where and how humans catch it."

## Numbers to have on screen or in the description

- Parser: 99.7% of lawyer-annotated spans recovered from 40 real contract PDFs.
- Routing on held-out test set: 90% of clauses need no human; 43% of candidate decisions automatic at 97.3% precision; recall 64% → 78% with review.
- Audit: append-only, hash-chained, tamper detection tested.
- Cost: free tier (Gemini 3.5 Flash-Lite), about 36 seconds and 2 LLM calls for a 9-page contract.
