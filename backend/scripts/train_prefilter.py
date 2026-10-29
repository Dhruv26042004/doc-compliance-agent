"""Train the tier-1 prefilter on dev contracts outside dev_core, then report on dev_core.

No LLM calls; runs in about a minute.
Usage: uv run python -m scripts.train_prefilter [--report-split dev_core]
"""

import argparse
import json
import time

from app.config import get_settings
from app.policy import load_policy
from app.prefilter import Prefilter


def load_rows():
    data = get_settings().data_dir / "processed"
    splits = json.loads((data / "splits.json").read_text(encoding="utf-8"))
    with open(data / "segments.jsonl", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    return rows, splits


def prf(pred: list[set], gold: list[set], rule: str | None = None):
    tp = fp = fn = 0
    for p, g in zip(pred, gold):
        rules = [rule] if rule else set(p) | set(g)
        for r in rules:
            tp += r in p and r in g
            fp += r in p and r not in g
            fn += r not in p and r in g
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return prec, rec, tp, fp, fn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-split", default="dev_core", choices=["dev_core", "test_core"])
    ap.add_argument("--target", type=float, default=0.95, help="per-rule recall the screen must keep")
    args = ap.parse_args()

    rows, splits = load_rows()
    rule_ids = [r.id for r in load_policy(1).rules]
    held_out = set(splits["dev_core"]) | set(splits["test"])  # never train on what we evaluate
    train = [r for r in rows if r["split"] == "dev" and r["contract_id"] not in held_out]
    report = [r for r in rows if r["contract_id"] in set(splits[args.report_split])]
    print(f"training on {len(train)} clauses from {len({r['contract_id'] for r in train})} contracts")

    t0 = time.perf_counter()
    pf = Prefilter(rule_ids).fit([r["text"] for r in train], [set(r["rule_ids"]) for r in train],
                                 [r["contract_id"] for r in train])
    print(f"trained in {time.perf_counter() - t0:.0f}s")

    # Choose the per-rule recall target on out-of-fold scores (training data only).
    print("\nOut-of-fold trade-off (training contracts):")
    print("| Per-rule recall target | Clauses skipped | Labeled clauses kept |\n|--:|--:|--:|")
    for target in (0.99, 0.98, 0.97, 0.95, 0.93, 0.90, 0.85):
        pf.set_screen_recall(target)
        skipped, kept = pf.oof_tradeoff()
        print(f"| {target:.0%} | {skipped:.0%} | {kept:.1%} |")
    pf.set_screen_recall(args.target)
    pf.save()
    print(f"\nusing per-rule target {args.target:.0%} -> data/processed/prefilter.joblib\n")

    texts, gold = [r["text"] for r in report], [set(r["rule_ids"]) for r in report]
    t0 = time.perf_counter()
    screened = pf.screen(texts)
    ms = 1000 * (time.perf_counter() - t0) / len(texts)
    sent = sum(bool(s) for s in screened)
    kept = sum(bool(g) and bool(s) for g, s in zip(gold, screened))
    positives = sum(bool(g) for g in gold)
    # Rule-level recall of the screen: is the clause sent to the LLM at all when it has gold label r?
    print(f"{args.report_split}: screen sends {sent}/{len(texts)} clauses to the LLM "
          f"({1 - sent / len(texts):.0%} skipped), keeps {kept}/{positives} labeled clauses "
          f"({kept / positives:.1%}), {ms:.2f} ms/clause")
    print("\n| Rule | Screen recall | Small model P | Small model R |\n|---|--:|--:|--:|")
    small = pf.classify(texts)
    for r in rule_ids:
        pos = [s for s, g in zip(screened, gold) if r in g]
        sr = sum(bool(s) for s in pos) / len(pos) if pos else 0
        p, rec, *_ = prf(small, gold, r)
        print(f"| {r} | {sr:.0%} ({sum(bool(s) for s in pos)}/{len(pos)}) | {p:.0%} | {rec:.0%} |")
    p, rec, tp, fp, fn = prf(small, gold)
    print(f"| **Micro** | {kept / positives:.0%} | **{p:.0%}** | **{rec:.0%}** |")


if __name__ == "__main__":
    main()
