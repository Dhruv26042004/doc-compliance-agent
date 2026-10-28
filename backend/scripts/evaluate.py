"""Evaluate the LLM classifier: per-rule precision / recall at clause level, plus
document-level violation detection for the "required" rules.

Usage:
  uv run python -m scripts.evaluate edge_dev
  uv run python -m scripts.evaluate dev_core [--contracts 5] [--model gemini-3.5-flash]
  uv run python -m scripts.evaluate test_core --allow-test     # final numbers only

Results go to eval/results/<split>/ as JSON (full predictions) and Markdown (tables).
LLM responses are cached, so an interrupted run resumes for free.
"""

import argparse
import json
import logging
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone

import yaml

from app.classifier import MAX_BATCH_CHARS, MAX_BATCH_CLAUSES, classify, load_prompt
from app.config import REPO_ROOT, get_settings
from app.llm import DailyQuotaExceeded, GeminiClient, LLMError
from app.policy import RuleKind, load_policy

SPLITS = ("edge_dev", "edge_test", "dev_core", "test_core", "dev", "test")


def load_split(name: str, n_contracts: int | None):
    """Returns ({doc_id: [(clause_id, text)]}, {clause_id: gold rule set}, {doc_id: required verdicts})."""
    data = get_settings().data_dir
    docs, gold, required = defaultdict(list), {}, {}
    if name.startswith("edge_"):
        cases = yaml.safe_load((data / "edge_cases.yaml").read_text(encoding="utf-8"))["cases"]
        for c in cases:
            if c["split"] == name.removeprefix("edge_"):
                docs["edge"].append((c["id"], c["text"]))
                gold[c["id"]] = set(c["rule_ids"])
        return dict(docs), gold, required

    ids = json.loads((data / "processed/splits.json").read_text(encoding="utf-8"))[name]
    ids = set(ids[:n_contracts] if n_contracts else ids)
    with open(data / "processed/segments.jsonl", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row["contract_id"] in ids:
                docs[row["contract_id"]].append((row["segment_id"], row["text"]))
                gold[row["segment_id"]] = set(row["rule_ids"])
    with open(data / "processed/documents.jsonl", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row["contract_id"] in ids:
                required[row["contract_id"]] = row["required_verdicts"]
    return dict(docs), gold, required


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f1 = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f1}


def score(policy, docs, gold, required, predicted):
    rule_ids = [r.id for r in policy.rules]
    per_rule = {}
    for rid in rule_ids:
        tp = fp = fn = 0
        for cid, g in gold.items():
            p = rid in predicted.get(cid, set())
            tp += p and rid in g
            fp += p and rid not in g
            fn += (not p) and rid in g
        per_rule[rid] = prf(tp, fp, fn)
    micro = prf(*(sum(m[k] for m in per_rule.values()) for k in ("tp", "fp", "fn")))

    # Document level: a required rule is violated when no clause in the document matches it.
    doc_level = {}
    for rid in [r.id for r in policy.rules if r.kind == RuleKind.REQUIRED] if required else []:
        tp = fp = fn = tn = 0
        for doc_id, verdicts in required.items():
            pred_violated = not any(rid in predicted.get(cid, set()) for cid, _ in docs[doc_id])
            gold_violated = verdicts[rid] == "violated"
            tp += pred_violated and gold_violated
            fp += pred_violated and not gold_violated
            fn += (not pred_violated) and gold_violated
            tn += (not pred_violated) and not gold_violated
        doc_level[rid] = {**prf(tp, fp, fn), "tn": tn}
    return per_rule, micro, doc_level


def fmt(x):
    return "–" if x is None else f"{x:.0%}"


def markdown(meta, per_rule, micro, doc_level, policy) -> str:
    titles = {r.id: r.title for r in policy.rules}
    out = [
        f"# {meta['split']}: {meta['model_version']} / prompt {meta['prompt_version']} ({meta['prompt_hash']})",
        "",
        f"{meta['n_documents']} documents, {meta['n_clauses']} clauses, run {meta['run_at']}.",
        "",
        "| Rule | Precision | Recall | F1 | TP | FP | FN |",
        "|---|--:|--:|--:|--:|--:|--:|",
    ]
    for rid, m in per_rule.items():
        out.append(f"| {rid} {titles[rid]} | {fmt(m['precision'])} | {fmt(m['recall'])} | {fmt(m['f1'])} | {m['tp']} | {m['fp']} | {m['fn']} |")
    out.append(f"| **Micro average** | **{fmt(micro['precision'])}** | **{fmt(micro['recall'])}** | **{fmt(micro['f1'])}** | {micro['tp']} | {micro['fp']} | {micro['fn']} |")
    if doc_level:
        out += ["", "Document-level detection of missing required clauses:", "",
                "| Rule | Precision | Recall | TP | FP | FN | TN |", "|---|--:|--:|--:|--:|--:|--:|"]
        for rid, m in doc_level.items():
            out.append(f"| {rid} {titles[rid]} missing | {fmt(m['precision'])} | {fmt(m['recall'])} | {m['tp']} | {m['fp']} | {m['fn']} | {m['tn']} |")
    c = meta["cost"]
    out += ["", f"Quotes found verbatim in the clause: {fmt(meta['quote_found_rate'])} of {meta['n_findings']} findings.",
            f"LLM calls: {c['calls']} ({c['cached']} cached), tokens in/out: {c['input_tokens']:,} / {c['output_tokens']:,}, "
            f"wall time {c['wall_s']:.0f}s."]
    if meta["failed_documents"]:
        out.append(f"\n**{len(meta['failed_documents'])} documents failed** and are excluded: {meta['failed_documents']}")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("split", choices=SPLITS)
    ap.add_argument("--contracts", type=int, help="only the first N contracts of the split")
    ap.add_argument("--model")
    ap.add_argument("--prompt", default="v1")
    ap.add_argument("--workers", type=int, default=get_settings().llm_max_workers)
    ap.add_argument("--allow-test", action="store_true", help="required for test splits")
    args = ap.parse_args()
    if "test" in args.split and not args.allow_test:
        raise SystemExit("Refusing to run on a test split without --allow-test. Tune on dev splits only.")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    policy = load_policy(1)
    client = GeminiClient(model=args.model)
    _, prompt_hash = load_prompt(args.prompt)
    docs, gold, required = load_split(args.split, args.contracts)
    print(f"{args.split}: {len(docs)} documents, {len(gold)} clauses -> {client.model}, prompt {args.prompt} ({prompt_hash})")

    predicted, findings_out, calls, failed = {}, {}, [], []
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(classify, client, policy, clauses, args.prompt): doc_id for doc_id, clauses in docs.items()}
        for n, fut in enumerate(as_completed(futures), start=1):
            doc_id = futures[fut]
            try:
                run = fut.result()
            except DailyQuotaExceeded as exc:
                pool.shutdown(wait=False, cancel_futures=True)
                raise SystemExit(
                    f"\nStopped: {exc}\n{n - 1} documents finished and are cached; "
                    "re-run the same command after the quota resets to resume for free."
                ) from None
            except LLMError as exc:
                failed.append(doc_id)
                print(f"  [{n}/{len(docs)}] {doc_id} FAILED: {exc}")
                continue
            calls += run.calls
            for cid, fs in run.findings.items():
                predicted[cid] = {f.rule_id for f in fs}
                findings_out[cid] = [asdict(f) | {"quote_found": f.quote_found} for f in fs]
            print(f"  [{n}/{len(docs)}] {doc_id}: {len(run.calls)} calls, {sum(c.cached for c in run.calls)} cached")

    for doc_id in failed:  # score only what was actually classified
        for cid, _ in docs.pop(doc_id):
            gold.pop(cid, None)
        required.pop(doc_id, None)

    per_rule, micro, doc_level = score(policy, docs, gold, required, predicted)
    all_findings = [f for fs in findings_out.values() for f in fs]
    meta = {
        "split": args.split,
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": client.model,
        "model_version": sorted({c.model_version for c in calls})[-1] if calls else client.model,
        "prompt_version": args.prompt,
        "prompt_hash": prompt_hash,
        "policy_version": policy.version,
        "batch": {"max_clauses": MAX_BATCH_CLAUSES, "max_chars": MAX_BATCH_CHARS},
        "n_documents": len(docs),
        "n_clauses": len(gold),
        "n_findings": len(all_findings),
        "quote_found_rate": sum(f["quote_found"] for f in all_findings) / len(all_findings) if all_findings else None,
        "failed_documents": failed,
        "cost": {
            "calls": len(calls),
            "cached": sum(c.cached for c in calls),
            "input_tokens": sum(c.input_tokens for c in calls),
            "output_tokens": sum(c.output_tokens for c in calls),
            "llm_latency_s": round(sum(c.latency_s for c in calls if not c.cached), 1),
            "wall_s": round(time.perf_counter() - t0, 1),
        },
    }
    md = markdown(meta, per_rule, micro, doc_level, policy)

    out_dir = REPO_ROOT / "eval" / "results" / args.split
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{meta['run_at'].replace(':', '')}_{client.model}_{args.prompt}" + (f"_n{args.contracts}" if args.contracts else "")
    (out_dir / f"{stem}.json").write_text(json.dumps({
        "meta": meta, "per_rule": per_rule, "micro": micro, "doc_level": doc_level,
        "predictions": {cid: findings_out.get(cid, []) for cid in gold},
        "gold": {cid: sorted(g) for cid, g in gold.items()},
    }, indent=1), encoding="utf-8")
    (out_dir / f"{stem}.md").write_text(md, encoding="utf-8")
    print("\n" + md)
    print(f"Saved eval/results/{args.split}/{stem}.(json|md)")


if __name__ == "__main__":
    main()
