"""Compare two evaluation runs on the same split with a paired bootstrap over documents.

Resampling whole contracts (not clauses) respects that clauses in one contract are
correlated. Reports the change in micro precision / recall / F1 with a 95% interval;
an interval that contains 0 means the difference is within noise.

Usage: uv run python -m scripts.compare_runs <baseline.json> <candidate.json> [--samples 2000]
"""

import argparse
import json
import random
from collections import defaultdict


def doc_counts(run: dict) -> dict[str, tuple[int, int, int]]:
    """Per-document (tp, fp, fn), pooled over rules."""
    counts = defaultdict(lambda: [0, 0, 0])
    for cid, gold in run["gold"].items():
        doc = cid.rsplit("-S", 1)[0]
        pred = {f["rule_id"] for f in run["predictions"].get(cid, [])}
        g = set(gold)
        c = counts[doc]
        c[0] += len(pred & g)
        c[1] += len(pred - g)
        c[2] += len(g - pred)
    return {d: tuple(c) for d, c in counts.items()}


def metrics(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def total(counts, docs):
    return [sum(counts[d][i] for d in docs) for i in range(3)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline")
    ap.add_argument("candidate")
    ap.add_argument("--samples", type=int, default=2000)
    args = ap.parse_args()
    a, b = (json.load(open(p, encoding="utf-8")) for p in (args.baseline, args.candidate))
    if a["gold"].keys() != b["gold"].keys():
        raise SystemExit("Runs are on different clauses; compare runs of the same split.")

    ca, cb = doc_counts(a), doc_counts(b)
    docs = sorted(ca)
    rng = random.Random(0)
    deltas = []
    for _ in range(args.samples):
        sample = [rng.choice(docs) for _ in docs]
        ma, mb = metrics(*total(ca, sample)), metrics(*total(cb, sample))
        deltas.append([y - x for x, y in zip(ma, mb)])

    base, cand = metrics(*total(ca, docs)), metrics(*total(cb, docs))
    print(f"{a['meta']['split']}, {len(docs)} documents, {args.samples} bootstrap samples")
    print(f"baseline:  {a['meta']['pipeline']['label'] if 'pipeline' in a['meta'] else 'v1'}")
    print(f"candidate: {b['meta']['pipeline']['label']}\n")
    print("| Metric | Baseline | Candidate | Change | 95% interval of change |\n|---|--:|--:|--:|--:|")
    for i, name in enumerate(("Precision", "Recall", "F1")):
        col = sorted(d[i] for d in deltas)
        lo, hi = col[int(0.025 * len(col))], col[int(0.975 * len(col)) - 1]
        verdict = "" if lo <= 0 <= hi else " (significant)"
        print(f"| {name} | {base[i]:.0%} | {cand[i]:.0%} | {cand[i] - base[i]:+.1%} | {lo:+.1%} to {hi:+.1%}{verdict} |")


if __name__ == "__main__":
    main()
