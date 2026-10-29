# Limitations and fairness

This system triages contracts for a human reviewer. It does not give legal advice, and it is not accurate enough to run without people. This page lists where it fails, with numbers from the held-out test set (`test_core`: 30 contracts, 2,331 clauses), and how the human loop is designed to catch each failure.

## Where it fails

### It misses about a third of relevant clauses on its own

Model-only recall is **64%** on the test set (precision 80%). Missed clauses are the bigger risk in compliance work, because nobody looks at what the system reports as clear.

*How it is caught:* clauses where a small TF-IDF model flags a rule but the LLM did not are sent to review as possible misses. With the queue resolved correctly, recall rises to **78%** (an estimate that assumes reviewers decide every queued item correctly). That still leaves about one relevant clause in five unflagged; see "What humans cannot catch" below.

### Short clauses and short contracts do worse

| Slice (test set) | Precision | Recall |
|---|--:|--:|
| Clauses under 300 characters | 76% | **54%** |
| Clauses of 300–1,000 characters | 76% | 69% |
| Clauses over 1,000 characters | 91% | 64% |
| Shortest third of contracts | 83% | **57%** |
| Longest third of contracts | 78% | 69% |

Short clauses are often fragments of a provision that the PDF layout or the paragraph splitter separated from the rest, so the model sees half a sentence. Results by contract type (license, services, distribution, …) are not reported as findings: the test set has only 1–4 contracts of each type, too few to tell a pattern from chance.

### Some rules are weak, and the rarest ones cannot be measured well

| Rule (test set) | F1 | Note |
|---|--:|---|
| R-09 Transfer of IP ownership | 40% | Ownership language is spread across definitions, licenses, and assignment clauses. |
| R-02 Uncapped liability | 44% | Carve-outs hide inside long liability clauses; CUAD labels some statutory boilerplate. |
| R-11 Liquidated damages | 44% | Only 6 positive clauses in the test set. |
| R-10 Most favored nation | 50% | Only 3 positive clauses in the whole test set; the number is close to meaningless. |
| R-03 Governing law | 93% | Formulaic language; the easiest rule. |

### The ground truth itself is imperfect

Labels come from CUAD (law students, reviewed by lawyers) mapped to this policy's rules. CUAD marks clause *types*, not which party bears the risk, and its definitions do not always match the policy's (see `data/edge_cases.yaml`). A small TF-IDF model is about as accurate as the LLM here (72% precision / 64% recall on dev), which suggests label noise and clause-level scoring set part of the ceiling.

### Decisions change when the prompt changes

The whole policy is in every prompt. Changing two rules for policy v2 flipped decisions on **37 clauses of rules nobody changed**, and rewording a definition without changing its meaning created new false positives (`eval/results/policy_diff_v1_v2_test_core.md`). Some of that is ordinary run-to-run variation, even at temperature 0.

*How it is caught:* every analysis records its policy version, prompt hash, and model version in the audit log, and `scripts/policy_diff.py` shows how decisions shift before a new policy version is activated. Treat every policy edit as a release that needs a regression run.

### Accuracy gains on dev did not all carry over

The Phase 4 improvements raised dev F1 from 70% to 76% (statistically significant) but left test F1 unchanged (72% → 71%, within noise). Thirty contracts per split is small: differences of a few points are not detectable, and numbers in this repository should be read with the bootstrap intervals in `scripts/compare_runs.py` in mind.

### Inputs it does not handle

- **Scanned PDFs** (no text layer) are rejected; there is no OCR.
- **English only.** CUAD is US SEC filings; non-US drafting styles and other languages are untested.
- **Tables, schedules, and cross-references** ("as defined in Section 4.2") are read as plain text; a clause that only makes sense with its definitions may be judged wrong.
- **Hyphenated line breaks** keep the hyphen ("agree-ment"), since compounds such as "non-compete" cannot be told apart without a dictionary.
- **The model can change underneath the system.** `gemini-3.5-flash` currently resolves to a newer model, and the free tier allows only 20 requests a day on it. Every result records the version that actually answered.

## Fairness

"Fairness" here means: does the system serve some contracts, counterparties, or reviewers worse than others?

- **Counterparty and jurisdiction.** The data is US public-company contracts. Contracts drafted under other legal systems, by small businesses, or in plainer language are under-represented, and the system has not been tested on them. Any deployment outside US commercial contracts needs its own labeled test set first.
- **One-sided risk.** The policy flags clause *types* without asking who benefits. A non-compete that binds the counterparty is flagged exactly like one that binds the client. That is consistent, but it can over-flag contracts written in the client's favor; reviewers should expect it.
- **Automation bias.** Reviewers see the model's proposal, explanation, and confidence before deciding, which invites agreement. The interface makes the reviewer approve or override every routed decision explicitly, requires a written reason for each override, and records reviewer identity, so override rates can be audited per reviewer and per rule.
- **Feedback loops.** Reviewed decisions become new labels (`GET /labels`). If those labels retrain the prefilter or grow the example pool, reviewer mistakes and biases flow into the model. Labels record their source (approved or overridden) and policy version so they can be filtered, and they should be spot-checked before retraining.
- **The demo's reviewer is simulated.** Seeded reviews follow CUAD labels and are marked as simulated. Real override rates will differ.

## What humans cannot catch

The review queue only contains what the system routed there. A relevant clause that neither the LLM nor the small model flagged is decided "no match" automatically, and no reviewer sees it: about **22% of relevant clauses** on the test set under the assumptions above. For high-stakes contracts, the right use of this tool is to prioritize a lawyer's reading, not to replace it.
