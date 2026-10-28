"""Build the labeled clause dataset and the fixed dev/test splits from CUAD.

Deterministic: same CUAD file + same policy + same seed -> byte-identical output.

Outputs in data/processed/:
  segments.jsonl   every clause with offsets and rule labels (large, git-ignored, rebuildable)
  documents.jsonl  one row per contract with document-level verdicts for "required" rules
  splits.json      contract ids per split, plus the source file hash  (committed, frozen)
  stats.json       label counts per rule and split                    (committed)

Usage: uv run python -m scripts.build_dataset [--refreeze]
"""

import hashlib
import json
import random
import sys
from collections import Counter, defaultdict

from app.config import get_settings
from app.policy import RuleKind, load_policy
from app.segmenter import split_text

SEED = 42
CORE_SIZE = 30  # contracts per core subset; keeps LLM eval runs inside free-tier limits
CORE_MAX_CHARS = 100_000  # very long contracts would dominate a core subset's cost
CORE_MIN_PER_RULE = 5  # every rule should appear in at least this many core contracts
MIN_OVERLAP = 0.5  # fraction of min(span, segment) that must overlap to count as labeled


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def label_segments(text, segments, spans_by_rule):
    """Assign rule ids to segments by span overlap. Returns labels and count of unplaced spans."""
    labels = [set() for _ in segments]
    unplaced = 0
    for rule_id, spans in spans_by_rule.items():
        for s, e in spans:
            placed = False
            for i, seg in enumerate(segments):
                overlap = min(e, seg.end) - max(s, seg.start)
                if overlap > 0 and overlap >= MIN_OVERLAP * min(e - s, seg.end - seg.start):
                    labels[i].add(rule_id)
                    placed = True
            unplaced += not placed
    return labels, unplaced


def pick_core(contract_ids, docs, rule_ids, rng):
    """Choose a fixed subset that still covers every rule, rarest rules first."""
    eligible = [c for c in contract_ids if docs[c]["n_chars"] <= CORE_MAX_CHARS]
    rng.shuffle(eligible)
    has = {r: [c for c in eligible if r in docs[c]["rules_present"]] for r in rule_ids}
    chosen: list[str] = []
    for r in sorted(rule_ids, key=lambda r: len(has[r])):
        for c in has[r]:
            if sum(r in docs[x]["rules_present"] for x in chosen) >= CORE_MIN_PER_RULE:
                break
            if c not in chosen:
                chosen.append(c)
    chosen += [c for c in eligible if c not in chosen][: max(0, CORE_SIZE - len(chosen))]
    return sorted(chosen)


def main(refreeze: bool = False) -> None:
    data_dir = get_settings().data_dir
    raw = data_dir / "raw" / "cuad"
    out = data_dir / "processed"
    out.mkdir(parents=True, exist_ok=True)

    policy = load_policy(1)
    cat_to_rule = policy.category_to_rule()
    rule_ids = [r.id for r in policy.rules]
    required = [r.id for r in policy.rules if r.kind == RuleKind.REQUIRED]

    cuad = json.loads((raw / "CUADv1.json").read_text(encoding="utf-8"))["data"]
    test_titles = {
        d["title"] for d in json.loads((raw / "test.json").read_text(encoding="utf-8"))["data"]
    }

    # Stable short ids, ordered by title.
    cuad.sort(key=lambda d: d["title"])
    docs, segment_rows, unplaced_total, span_total = {}, [], 0, 0
    for n, d in enumerate(cuad, start=1):
        cid = f"C{n:04d}"
        text = d["paragraphs"][0]["context"]
        split = "test" if d["title"] in test_titles else "dev"

        spans_by_rule = defaultdict(list)
        for qa in d["paragraphs"][0]["qas"]:
            rule = cat_to_rule.get(qa["id"].split("__")[-1])
            if rule:
                for a in qa["answers"]:
                    spans_by_rule[rule].append((a["answer_start"], a["answer_start"] + len(a["text"])))
        span_total += sum(len(v) for v in spans_by_rule.values())

        segments = split_text(text)
        labels, unplaced = label_segments(text, segments, spans_by_rule)
        unplaced_total += unplaced

        for i, (seg, labs) in enumerate(zip(segments, labels)):
            segment_rows.append({
                "segment_id": f"{cid}-S{i:04d}",
                "contract_id": cid,
                "split": split,
                "start": seg.start,
                "end": seg.end,
                "text": text[seg.start : seg.end],
                "rule_ids": sorted(labs),
            })

        present = set(spans_by_rule)
        docs[cid] = {
            "contract_id": cid,
            "title": d["title"],
            "split": split,
            "n_chars": len(text),
            "n_segments": len(segments),
            "rules_present": sorted(present),
            # Required rules are judged on the whole document: no matching clause = violation.
            "required_verdicts": {r: ("satisfied" if r in present else "violated") for r in required},
        }

    splits_path = out / "splits.json"
    source_hash = sha256(raw / "CUADv1.json")
    if splits_path.exists() and not refreeze:
        # Splits are frozen once created: policy edits must never reshuffle the test set.
        splits = json.loads(splits_path.read_text(encoding="utf-8"))
        if splits["source"]["sha256"] != source_hash:
            raise SystemExit("CUADv1.json differs from the file the splits were frozen on.")
        print(f"Using frozen splits from {splits_path.name} (pass --refreeze to rebuild)")
    else:
        rng = random.Random(SEED)
        dev_ids = sorted(c for c in docs if docs[c]["split"] == "dev")
        test_ids = sorted(c for c in docs if docs[c]["split"] == "test")
        splits = {
            "seed": SEED,
            "source": {"file": "CUADv1.json", "sha256": source_hash},
            "frozen_with_policy_version": policy.version,
            "dev": dev_ids,
            "test": test_ids,
            "dev_core": pick_core(dev_ids, docs, rule_ids, rng),
            "test_core": pick_core(test_ids, docs, rule_ids, rng),
        }
        splits_path.write_text(json.dumps(splits, indent=2) + "\n", encoding="utf-8")
    core_of = {c: s for s in ("dev_core", "test_core") for c in splits[s]}

    with open(out / "segments.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for row in segment_rows:
            row["core"] = row["contract_id"] in core_of
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(out / "documents.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for cid in sorted(docs):
            f.write(json.dumps(docs[cid], ensure_ascii=False) + "\n")

    # Stats: positive clauses per rule (clause level) and documents violating required rules.
    stats = {"unplaced_spans": unplaced_total, "total_spans": span_total, "splits": {}}
    for name in ("dev", "test", "dev_core", "test_core"):
        ids = set(splits[name])
        rows = [r for r in segment_rows if r["contract_id"] in ids]
        pos = Counter(rid for r in rows for rid in r["rule_ids"])
        stats["splits"][name] = {
            "contracts": len(ids),
            "segments": len(rows),
            "unlabeled_segments": sum(not r["rule_ids"] for r in rows),
            "positive_segments": {r: pos[r] for r in rule_ids},
            "contracts_with_rule": {
                r: sum(r in docs[c]["rules_present"] for c in ids) for r in rule_ids
            },
            "required_violations": {
                r: sum(docs[c]["required_verdicts"][r] == "violated" for c in ids) for r in required
            },
        }
    (out / "stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")

    print(f"{len(docs)} contracts, {len(segment_rows)} segments, "
          f"{unplaced_total}/{span_total} spans could not be placed on a segment")
    for name, s in stats["splits"].items():
        print(f"{name:10s} contracts={s['contracts']:3d} segments={s['segments']:6d} "
              f"labeled={s['segments'] - s['unlabeled_segments']}")


if __name__ == "__main__":
    main(refreeze="--refreeze" in sys.argv)
