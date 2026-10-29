"""Show how decisions shift between two policy versions on the same split.

Takes two evaluation runs (same split, different --policy) and reports what changed in
the policy text, which clauses gained or lost a rule, and how document outcomes moved.
Rules the policy did NOT change are reported separately: their flips are run-to-run
noise, the floor against which real shifts should be judged.

Usage: uv run python -m scripts.policy_diff <run_old.json> <run_new.json>
"""

import argparse
import json
from collections import Counter, defaultdict

from app.config import REPO_ROOT, get_settings
from app.policy import Policy, RuleKind, load_policy

FIELDS = ("title", "kind", "severity", "definition", "matches", "does_not_match", "edge_notes", "cuad_categories")


def rule_changes(old: Policy, new: Policy) -> dict[str, list[str]]:
    out = {}
    for r in new.rules:
        prev = old.rule(r.id)
        changed = [f for f in FIELDS if getattr(prev, f) != getattr(r, f)]
        if changed:
            out[r.id] = changed
    return out


def matched(run: dict) -> dict[str, set[str]]:
    return {cid: {f["rule_id"] for f in run["predictions"].get(cid, [])} for cid in run["gold"]}


def doc_outcome(policy: Policy, rule_id: str, clauses_matching: int) -> str:
    """What a document's result is for one rule, given how many clauses match it."""
    kind = policy.rule(rule_id).kind
    if kind == RuleKind.REQUIRED:
        return "satisfied" if clauses_matching else "violated"
    if not clauses_matching:
        return "clear"
    return "violation" if kind == RuleKind.PROHIBITED else "flag"


def prf(m: dict[str, set[str]], gold: dict[str, list[str]], rule: str) -> tuple[float, float]:
    tp = sum(rule in m[c] and rule in gold[c] for c in gold)
    fp = sum(rule in m[c] and rule not in gold[c] for c in gold)
    fn = sum(rule not in m[c] and rule in gold[c] for c in gold)
    return (tp / (tp + fp) if tp + fp else 0.0), (tp / (tp + fn) if tp + fn else 0.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("old")
    ap.add_argument("new")
    args = ap.parse_args()
    a, b = (json.load(open(p, encoding="utf-8")) for p in (args.old, args.new))
    if a["gold"].keys() != b["gold"].keys():
        raise SystemExit("The runs cover different clauses; compare runs of the same split.")
    pa, pb = load_policy(a["meta"]["policy_version"]), load_policy(b["meta"]["policy_version"])
    split = a["meta"]["split"]
    changes = rule_changes(pa, pb)
    ma, mb = matched(a), matched(b)

    text = {}
    with open(get_settings().data_dir / "processed/segments.jsonl", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row["segment_id"] in ma:
                text[row["segment_id"]] = row["text"]

    out = [f"# Policy v{pa.version} → v{pb.version} on `{split}`", "",
           f"{len(ma)} clauses in {len({c.rsplit('-S', 1)[0] for c in ma})} documents. "
           f"Same pipeline (`{b['meta']['pipeline']['label']}`) and model (`{b['meta']['model_version']}`).", "",
           "## What changed in the policy", ""]
    out += [f"- {c}" for c in pb.changelog] + [""]
    out += ["| Rule | Fields changed |", "|---|---|"]
    out += [f"| {rid} {pb.rule(rid).title} | {', '.join(fs)} |" for rid, fs in changes.items()] + [""]

    out += ["## Clause-level shift", "",
            "| Rule | Changed in policy? | Matched v1 | Matched v2 | Gained | Lost |", "|---|---|--:|--:|--:|--:|"]
    flips_unchanged = 0
    for r in pb.rules:
        in_a = {c for c in ma if r.id in ma[c]}
        in_b = {c for c in mb if r.id in mb[c]}
        gained, lost = len(in_b - in_a), len(in_a - in_b)
        if r.id not in changes:
            flips_unchanged += gained + lost
        out.append(f"| {r.id} {r.title} | {'**yes**' if r.id in changes else 'no'} | {len(in_a)} | {len(in_b)} | {gained} | {lost} |")
    unchanged_matches = sum(len(ma[c] - set(changes)) for c in ma)
    out += ["", f"**Noise floor:** rules the policy did not change still flipped on {flips_unchanged} clauses "
            f"(against {unchanged_matches} matches in v1). Shifts in changed rules should be read against that.", ""]

    out += ["## Document outcomes", "", "| Rule | Outcome change | Documents |", "|---|---|--:|"]
    docs = defaultdict(list)
    for c in ma:
        docs[c.rsplit("-S", 1)[0]].append(c)
    for r in pb.rules:
        moves = Counter()
        for d, cs in docs.items():
            before = doc_outcome(pa, r.id, sum(r.id in ma[c] for c in cs))
            after = doc_outcome(pb, r.id, sum(r.id in mb[c] for c in cs))
            if before != after:
                moves[f"{before} → {after}"] += 1
        for move, n in moves.most_common():
            out.append(f"| {r.id} {r.title} | {move} | {n} |")
    out.append("")

    out += ["## Examples of changed decisions", ""]
    for rid in changes:
        flipped = [c for c in ma if (rid in ma[c]) != (rid in mb[c])][:3]
        if not flipped:
            continue
        out.append(f"**{rid} {pb.rule(rid).title}**")
        out.append("")
        for c in flipped:
            verb = "no longer matches" if rid in ma[c] else "now matches"
            snippet = " ".join(text[c].split())[:280]
            out.append(f"- `{c}` {verb}: “{snippet}{'…' if len(text[c]) > 280 else ''}”")
        out.append("")

    out += ["## Against the CUAD reference labels", "",
            "CUAD labels follow the v1 definitions, so a narrowed rule is expected to lose recall against them.", "",
            "| Rule | v1 precision / recall | v2 precision / recall |", "|---|--:|--:|"]
    for rid in changes:
        (p1, r1), (p2, r2) = prf(ma, a["gold"], rid), prf(mb, b["gold"], rid)
        out.append(f"| {rid} | {p1:.0%} / {r1:.0%} | {p2:.0%} / {r2:.0%} |")

    report = "\n".join(out) + "\n"
    path = REPO_ROOT / "eval" / "results" / f"policy_diff_v{pa.version}_v{pb.version}_{split}.md"
    path.write_text(report, encoding="utf-8")
    print(report)
    print(f"Saved {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
