import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import ReviewError, effective_status, review_decision
from app.db import get_session
from app.models import Analysis, Clause, Decision, Document, Label
from app.policy import Policy, load_policy
from app.schemas import AnalysisOut, DecisionOut, QueueItem, ReviewIn

router = APIRouter(tags=["review"])


def decision_out(d: Decision, policy: Policy, clause_idx: dict[uuid.UUID, int]) -> DecisionOut:
    rule = policy.rule(d.rule_id)
    return DecisionOut.model_validate(d).model_copy(update={
        "clause_idx": clause_idx.get(d.clause_id), "rule_title": rule.title, "severity": rule.severity.value,
    })


def analysis_out(session: Session, analysis: Analysis) -> AnalysisOut:
    policy = load_policy(analysis.policy_version)
    clause_idx = dict(session.execute(
        select(Clause.id, Clause.idx).where(Clause.document_id == analysis.document_id)
    ).all())
    decisions = [decision_out(d, policy, clause_idx) for d in analysis.decisions]
    return AnalysisOut.model_validate({
        **{k: getattr(analysis, k) for k in AnalysisOut.model_fields if hasattr(analysis, k) and k != "decisions"},
        "rule_status": effective_status(analysis, policy),
        "n_auto": sum(d.route == "auto" for d in decisions),
        "n_pending": sum(d.status == "pending" for d in decisions),
        "decisions": decisions,
    })


@router.get("/analyses/{analysis_id}", response_model=AnalysisOut)
def get_analysis(analysis_id: uuid.UUID, session: Session = Depends(get_session)) -> AnalysisOut:
    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found")
    return analysis_out(session, analysis)


@router.get("/reviews/queue", response_model=list[QueueItem])
def review_queue(rule_id: str | None = None, limit: int = 100, session: Session = Depends(get_session)) -> list[QueueItem]:
    """Pending decisions, oldest analysis first, so the queue drains in order."""
    q = (
        select(Decision, Analysis, Document, Clause)
        .join(Analysis, Decision.analysis_id == Analysis.id)
        .join(Document, Analysis.document_id == Document.id)
        .outerjoin(Clause, Decision.clause_id == Clause.id)
        .where(Decision.status == "pending")
        .order_by(Analysis.created_at, Decision.position)
        .limit(min(limit, 500))
    )
    if rule_id:
        q = q.where(Decision.rule_id == rule_id)
    items = []
    for d, a, doc, clause in session.execute(q).all():
        base = decision_out(d, load_policy(a.policy_version), {clause.id: clause.idx} if clause else {})
        items.append(QueueItem(**base.model_dump(), analysis_id=a.id, document_id=doc.id,
                               filename=doc.filename, clause_text=clause.text if clause else None))
    return items


@router.post("/decisions/{decision_id}/review", response_model=DecisionOut)
def review(decision_id: uuid.UUID, body: ReviewIn, session: Session = Depends(get_session)) -> DecisionOut:
    decision = session.get(Decision, decision_id)
    if decision is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Decision not found")
    try:
        review_decision(session, decision, body.action, body.reviewer, body.reason)
    except ReviewError as exc:
        code = status.HTTP_409_CONFLICT if "already" in str(exc) else status.HTTP_422_UNPROCESSABLE_CONTENT
        raise HTTPException(code, str(exc)) from exc
    policy = load_policy(decision.analysis.policy_version)
    idx = {decision.clause_id: session.get(Clause, decision.clause_id).idx} if decision.clause_id else {}
    return decision_out(decision, policy, idx)


@router.get("/labels")
def export_labels(session: Session = Depends(get_session)) -> list[dict]:
    """Every human-confirmed label, for retraining the prefilter and growing the example pool."""
    rows = session.scalars(select(Label).order_by(Label.created_at)).all()
    return [{"id": str(l.id), "decision_id": str(l.decision_id), "rule_id": l.rule_id, "applies": l.applies,
             "source": l.source, "policy_version": l.policy_version, "clause_text": l.clause_text,
             "created_at": l.created_at.isoformat()} for l in rows]


@router.get("/policy")
def get_policy(version: int = 1) -> dict:
    """The policy rules, so the interface can show each rule's definition next to a decision."""
    return load_policy(version).model_dump(mode="json")
