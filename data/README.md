# Data card

## Contents

| Path | What it is | In git |
|---|---|---|
| `policy/policy_v1.yaml` | The policy: 12 numbered, testable rules, each with examples that match and examples that don't | yes |
| `edge_cases.yaml` | 48 hand-labeled tricky clauses (2 dev + 2 test per rule) | yes |
| `processed/splits.json` | **Frozen** contract ids for dev / test / dev_core / test_core, plus the source file's hash | yes |
| `processed/documents.jsonl` | One row per contract, with document-level verdicts for the "required" rules | yes |
| `processed/stats.json` | Label counts per rule and split | yes |
| `processed/segments.jsonl` | 65,502 clauses with character offsets and rule labels (35 MB) | no, rebuilt |
| `raw/cuad/` | CUAD v1 source files | no, downloaded |

Rebuild from scratch:

```bash
cd backend
uv run python -m scripts.download_cuad
uv run python -m scripts.build_dataset
```

## Source

[CUAD v1](https://www.atticusprojectai.org/cuad) by The Atticus Project: 510 commercial contracts from SEC filings, with 41 clause types annotated by law students and reviewed by lawyers. Licensed **CC BY 4.0**.

## How labels are made

1. **Splitting.** Each contract is split on blank lines. Paragraphs over 3,000 characters are split again at sentence boundaries, and fragments under 20 characters (page numbers, stray headers) are dropped. Offsets index into the original text exactly.
2. **Clause labels.** Each rule maps to one or two CUAD clause types (`cuad_categories` in the policy). A clause gets a rule's label when a CUAD span for that rule overlaps at least 50% of the shorter of the span and the clause. Only 2 of 4,750 spans failed to land on any clause.
3. **Document verdicts.** For the `required` rules (R-01, R-03), a contract with no matching clause is a document-level violation.

## Splits

- **dev / test** follow CUAD's official 408 / 102 contract split, so results can be compared with published CUAD work. Splitting is by contract, so no contract's clauses appear in both.
- **dev_core / test_core** are fixed subsets of 30 contracts each, used for LLM evaluation within free-tier limits. They are chosen with seed 42, rarest rule first, so each rule appears in at least 5 contracts where the data allows it. Contracts over 100k characters are excluded to keep costs predictable.
- **Splits are frozen.** The build script reuses `splits.json` and only rebuilds it with `--refreeze`. Policy edits change the labels but never which contracts are in the test set.
- **Never tune against test or test_core.** Prompt iteration, few-shot pools, and threshold tuning use dev only.

## Label counts

Cells show clauses (contracts).

| Rule | Kind | Dev | Test | Dev core | Test core |
|---|---|--:|--:|--:|--:|
| R-01 Limitation of liability required | required | 490 (231) | 102 (44) | 36 (16) | 36 (15) |
| R-02 Uncapped liability prohibited | prohibited | 152 (98) | 14 (13) | 10 (7) | 5 (5) |
| R-03 Governing law required | required | 371 (354) | 89 (83) | 28 (27) | 29 (24) |
| R-04 Termination for convenience | review | 194 (154) | 40 (29) | 16 (14) | 8 (7) |
| R-05 Renewal terms | review | 193 (151) | 32 (27) | 11 (9) | 7 (7) |
| R-06 Non-compete / customer non-solicit | prohibited | 220 (104) | 63 (27) | 16 (11) | 15 (5) |
| R-07 Exclusivity | review | 314 (147) | 72 (33) | 12 (8) | 20 (11) |
| R-08 Assignment / change of control | review | 570 (303) | 146 (73) | 36 (24) | 41 (23) |
| R-09 Transfer of IP ownership | prohibited | 283 (114) | 62 (26) | 13 (5) | 18 (9) |
| R-10 Most favored nation | review | 30 (25) | 3 (3) | 8 (6) | 3 (3) |
| R-11 Liquidated damages | review | 86 (47) | 24 (14) | 14 (5) | 6 (5) |
| R-12 Audit rights | review | 417 (176) | 75 (38) | 29 (14) | 18 (13) |
| **All clauses** | | 54,874 | 10,628 | 2,198 | 2,331 |

Document-level violations of the required rules: R-01 is missing in 58 of 102 test contracts, and R-03 in 19 of 102.

## Known limitations

- **Labels mark clause type, not risk.** CUAD tells us a clause *is* an uncapped-liability clause, not whether it favors our side. The policy is written so that clause type alone decides the verdict; the direction of risk is out of scope.
- **Rare rules.** R-10 has only 3 positive clauses in the whole test set, so its precision and recall will have very wide error bars. Results tables will report raw counts next to the percentages.
- **CUAD and the policy sometimes disagree.** CUAD labels some statutory boilerplate as uncapped liability, and some free-assignment clauses as anti-assignment. Ground truth follows CUAD; `edge_cases.yaml` records where the policy's reading differs.
- **Long multi-topic paragraphs** can carry several labels at once (one has R-04, R-05 and R-07). That is realistic, but it makes clause-level scoring stricter than span-level scoring.
- **Most clauses match no rule:** 94% of test clauses are unlabeled. This is the imbalance the Phase 4 cheap filter is meant to exploit.
- **Edge cases were drafted by the developer** and are reviewed by hand. They test policy interpretation and are not a substitute for a lawyer's labels.
