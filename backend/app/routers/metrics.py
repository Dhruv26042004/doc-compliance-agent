import json
from collections import Counter, defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import Analysis, AuditEvent, Clause, Decision, Document, Label
from app.policy import load_policy

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("")
def operational_metrics(session: Session = Depends(get_session)) -> dict:
    """Live numbers from production use: volume, automation, and what reviewers changed."""
    decisions = session.execute(select(Decision.rule_id, Decision.kind, Decision.route, Decision.status)).all()
    n = len(decisions)
    auto = sum(d.route == "auto" for d in decisions)
    reviewed = [d for d in decisions if d.status in ("approved", "overridden")]

    # Clauses that needed no human: analyzed clauses minus those with a review decision.
    analyzed_clauses = session.scalar(
        select(func.count(Clause.id)).where(Clause.document_id.in_(select(Analysis.document_id)))
    ) or 0
    review_clauses = session.scalar(
        select(func.count(func.distinct(Decision.clause_id))).where(Decision.route == "review", Decision.clause_id.is_not(None))
    ) or 0

    per_rule = defaultdict(Counter)
    for d in decisions:
        c = per_rule[d.rule_id]
        c["decisions"] += 1
        c["auto"] += d.route == "auto"
        c["pending"] += d.status == "pending"
        c["approved"] += d.status == "approved"
        c["overridden"] += d.status == "overridden"
        # Reviewer-measured precision: of the model's "this clause matches" proposals that a
        # human checked, how many did they approve?
        if d.kind == "finding" and d.status in ("approved", "overridden"):
            c["findings_reviewed"] += 1
            c["findings_approved"] += d.status == "approved"
    rules = []
    for r in load_policy().rules:
        c = per_rule.get(r.id, Counter())
        done = c["approved"] + c["overridden"]
        rules.append({
            "rule_id": r.id, "title": r.title, "decisions": c["decisions"], "auto": c["auto"], "pending": c["pending"],
            "reviewed": done, "overridden": c["overridden"],
            "override_rate": c["overridden"] / done if done else None,
            "reviewer_precision": c["findings_approved"] / c["findings_reviewed"] if c["findings_reviewed"] else None,
        })

    # Daily volume comes from the audit log, which records every event with a timestamp.
    day = func.date_trunc("day", AuditEvent.at)
    volume = defaultdict(Counter)
    for d, event, count in session.execute(
        select(day, AuditEvent.event, func.count())
        .where(AuditEvent.event.in_(["document.uploaded", "analysis.created", "decision.reviewed"]))
        .group_by(day, AuditEvent.event)
    ):
        volume[d.date().isoformat()][event] += count

    return {
        "documents": session.scalar(select(func.count(Document.id))) or 0,
        "analyses": session.scalar(select(func.count(Analysis.id))) or 0,
        "decisions": n,
        "auto_decisions": auto,
        "automation_rate": auto / n if n else None,
        "clauses_analyzed": analyzed_clauses,
        "clauses_without_human": (analyzed_clauses - review_clauses) / analyzed_clauses if analyzed_clauses else None,
        "pending_reviews": sum(d.status == "pending" for d in decisions),
        "reviewed": len(reviewed),
        "override_rate": sum(d.status == "overridden" for d in reviewed) / len(reviewed) if reviewed else None,
        "labels": session.scalar(select(func.count(Label.id))) or 0,
        "rules": rules,
        "volume": [
            {"day": d, "uploaded": v["document.uploaded"], "analyzed": v["analysis.created"], "reviewed": v["decision.reviewed"]}
            for d, v in sorted(volume.items())
        ],
    }


@router.get("/evals")
def evaluation_history() -> list[dict]:
    """Every saved evaluation run, oldest first: the offline precision/recall history."""
    root = get_settings().eval_results_dir
    runs = []
    for path in sorted(root.glob("*/*.json")):
        r = json.loads(path.read_text(encoding="utf-8"))
        meta = r["meta"]
        runs.append({
            "file": f"{path.parent.name}/{path.name}",
            "split": meta["split"],
            "run_at": meta["run_at"],
            "model_version": meta["model_version"],
            "pipeline": meta.get("pipeline", {}).get("label", meta["prompt_version"]),
            "policy_version": meta.get("policy_version", 1),
            "n_clauses": meta["n_clauses"],
            "precision": r["micro"]["precision"],
            "recall": r["micro"]["recall"],
            "f1": r["micro"]["f1"],
            "llm_calls": meta["cost"]["calls"],
            "per_rule": {rid: {"precision": m["precision"], "recall": m["recall"]} for rid, m in r["per_rule"].items()},
        })
    return sorted(runs, key=lambda x: x["run_at"])
