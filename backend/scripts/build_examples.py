"""Build the few-shot example pool from training contracts (dev minus dev_core).

Positives: CUAD answer spans (what lawyers highlighted), labeled with the mapped rule.
Negatives: unlabeled clauses the prefilter would send to the LLM (hard negatives).
Usage: uv run python -m scripts.build_examples
"""

import hashlib
import json
import random
import re
import shutil
import time

import numpy as np

from app.config import get_settings
from app.fewshot import MAX_EXAMPLE_CHARS, embed, index_paths
from app.policy import load_policy
from app.prefilter import Prefilter

MAX_NEGATIVES = 4000
SEED = 11
CHUNK = 250  # examples embedded and saved per step


def main() -> None:
    data = get_settings().data_dir
    splits = json.loads((data / "processed/splits.json").read_text(encoding="utf-8"))
    train_ids = set(splits["dev"]) - set(splits["dev_core"])
    docs = {json.loads(l)["title"]: json.loads(l)["contract_id"] for l in open(data / "processed/documents.jsonl", encoding="utf-8")}
    cat_to_rule = load_policy(1).category_to_rule()

    # Positives: one example per distinct annotated span, merged across rules.
    spans: dict[str, set[str]] = {}
    for d in json.loads((data / "raw/cuad/CUADv1.json").read_text(encoding="utf-8"))["data"]:
        if docs[d["title"]] not in train_ids:
            continue
        for qa in d["paragraphs"][0]["qas"]:
            rule = cat_to_rule.get(qa["id"].split("__")[-1])
            for a in qa["answers"] if rule else []:
                text = re.sub(r"\s+", " ", a["text"]).strip()
                if 40 <= len(text) <= 2 * MAX_EXAMPLE_CHARS:
                    spans.setdefault(text, set()).add(rule)
    positives = [{"text": t, "rule_ids": sorted(r)} for t, r in spans.items()]

    # Hard negatives: unlabeled clauses that pass the screen.
    pf = Prefilter.load()
    with open(data / "processed/segments.jsonl", encoding="utf-8") as f:
        unlabeled = [r for r in map(json.loads, f) if r["contract_id"] in train_ids and not r["rule_ids"] and len(r["text"]) >= 60]
    passed = [r for r, s in zip(unlabeled, pf.screen([r["text"] for r in unlabeled])) if s]
    random.Random(SEED).shuffle(passed)
    negatives = [{"text": re.sub(r"\s+", " ", r["text"]).strip(), "rule_ids": []} for r in passed[:MAX_NEGATIVES]]

    examples = positives + negatives
    print(f"{len(positives)} positive spans, {len(negatives)} hard negatives (of {len(passed)} screened-in unlabeled clauses)")
    t0 = time.perf_counter()
    texts = [e["text"][:MAX_EXAMPLE_CHARS] for e in examples]  # what the prompt shows
    # Each chunk is saved as it finishes, so an interrupted build resumes where it stopped.
    # The folder name includes a hash of the inputs, so changed inputs never reuse stale chunks.
    key = hashlib.sha256("\n".join(texts).encode()).hexdigest()[:12]
    parts = data / "processed" / f"examples_parts_{key}"
    parts.mkdir(exist_ok=True)
    chunks = []
    for start in range(0, len(texts), CHUNK):
        part = parts / f"{start:06d}.npy"
        if not part.exists():
            np.save(part, embed(texts[start : start + CHUNK]))
            print(f"  embedded {min(start + CHUNK, len(texts))}/{len(texts)} ({time.perf_counter() - t0:.0f}s)", flush=True)
        chunks.append(np.load(part))
    vectors = np.vstack(chunks)
    print(f"embedded {len(examples)} examples in {time.perf_counter() - t0:.0f}s")

    rows_path, vec_path = index_paths()
    with open(rows_path, "w", encoding="utf-8", newline="\n") as f:
        for e in examples:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    np.savez_compressed(vec_path, vectors=vectors)
    shutil.rmtree(parts)
    print(f"wrote {rows_path.name} and {vec_path.name}")


if __name__ == "__main__":
    main()
