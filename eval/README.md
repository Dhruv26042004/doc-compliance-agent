# Evaluation

```bash
cd backend
uv run python -m scripts.evaluate edge_dev                    # 24 hand-labeled dev edge cases
uv run python -m scripts.evaluate dev_core                    # 30 dev contracts, ~2,200 clauses
uv run python -m scripts.evaluate test_core --allow-test      # final numbers only
```

Each run writes `results/<split>/<timestamp>_<model>_<prompt>.json` (every prediction, gold label, quote, and confidence) and a `.md` table. LLM responses are cached in `cache/` (git-ignored) under a hash of the full request, so re-running costs nothing and an interrupted run resumes where it stopped.

## Comparing runs

```bash
uv run python -m scripts.compare_runs <baseline.json> <candidate.json>   # paired bootstrap, 95% intervals
uv run python -m scripts.policy_diff <policy_v1_run.json> <policy_v2_run.json>   # decision shift between policy versions
```

## What is measured

**Clause level, per rule.** For every clause and every rule: did the model say the clause matches the rule, and does the gold label agree?

- **Precision**: of the clauses the model tagged with the rule, the share that were right. Low precision means false alarms for reviewers.
- **Recall**: of the clauses that truly match, the share the model found. Low recall means missed risks, which is worse in compliance.
- **Micro average** pools TP/FP/FN across all rules, so common rules weigh more.

**Document level, for `required` rules (R-01, R-03).** A contract violates a required rule when no clause matches it. We score how well the system detects these missing clauses.

**Quote validity.** The share of findings whose quoted evidence is found in the clause (ignoring case, spacing, punctuation). A quote that is not there is a likely hallucination; the Phase 4 verifier targets these.

**Cost.** LLM calls, input/output tokens (including the model's thinking tokens), and wall time.

## Rules of the game

- Prompts, few-shot pools, and thresholds are tuned on **dev only** (`edge_dev`, `dev_core`, `dev`). The script refuses test splits without `--allow-test`.
- `test_core` and `edge_test` are run once per milestone to report numbers, never to choose between options.
- Every result records the exact model version that served it, the prompt version and hash, and the policy version, so any number in this repo can be traced to what produced it.
- Small counts are reported next to percentages. With 3 positives, 67% recall means 2 out of 3; read it that way.

## Known measurement caveats

- Ground truth comes from CUAD's clause-type labels mapped to policy rules (see `data/README.md`). Where CUAD and the policy's definition disagree, a correct model can be scored as wrong. The edge cases record the known disagreements.
- Clause-level scoring is strict: a long paragraph that CUAD labels for one rule because of one sentence counts as a miss if the model does not tag it, even if the model tagged the neighboring clause that holds the rest of the provision.
