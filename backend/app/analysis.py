"""Run the decision pipeline over a document, route each decision, and store the result.

Every proposed statement becomes a Decision:
  finding           "clause matches rule"      auto if verified and confidence >= threshold
  rejected_finding  "clause does NOT match"    review: the verifier overruled the classifier
  possible_miss     "clause does NOT match"    review: the small model thinks it might
  missing_required  "document lacks the rule"  review: high-severity, a human confirms
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy.orm import Session

from app.config import get_settings
from app.documents import span_rects
from app.models import Analysis, Decision, Document, Label
from app.pipeline import PipelineConfig, Resources, run_pipeline
from app.policy import Policy, RuleKind

# What a matching clause means for each kind of rule.
VERDICT = {RuleKind.REQUIRED: "satisfies", RuleKind.PROHIBITED: "violation", RuleKind.REVIEW: "flag"}


class ReviewError(ValueError):
    pass


def default_config() -> PipelineConfig:
    s = get_settings()
    return PipelineConfig("v1", s.pipeline_prefilter, s.pipeline_fewshot, s.pipeline_verify)


@lru_cache
def _resources(cfg: PipelineConfig) -> Resources:
    return Resources.for_config(cfg)  # loaded once per process


def analyze_document(session: Session, client, policy: Policy, doc: Document,
                     cfg: PipelineConfig | None = None, res: Resources | None = None) -> Analysis:
    cfg = cfg or default_config()
    res = res or _resources(cfg)
    threshold = get_settings().routing_auto_threshold
    clauses = {str(c.id): c for c in doc.clauses}
    with ThreadPoolExecutor(max_workers=get_settings().llm_max_workers) as pool:
        run = run_pipeline(client, policy, [(cid, c.text) for cid, c in clauses.items()], cfg, res, pool)

    decisions: list[Decision] = []

    def add(**kw) -> None:
        review = kw["route"] == "review"
        decisions.append(Decision(position=len(decisions), status="pending" if review else "auto",
                                  final_applies=None if review else kw["proposed_applies"], **kw))

    for cid, clause in clauses.items():
        for f in run.findings.get(cid, []):
            rule = policy.rule(f.rule_id)
            auto = f.quote_found and f.confidence >= threshold
            start = clause.char_start + f.quote_start if f.quote_found else None
            end = clause.char_start + f.quote_end if f.quote_found else None
            add(clause_id=clause.id, rule_id=rule.id, kind="finding", proposed_applies=True,
                verdict=VERDICT[rule.kind], route="auto" if auto else "review",
                route_reason="high_confidence" if auto else "low_confidence",
                quote=f.quote, quote_start=start, quote_end=end, explanation=f.explanation,
                confidence=f.confidence,
                rects=(span_rects(doc, start, end) if start is not None else None) or clause.rects)

    for r in run.rejected:
        clause = clauses[r["clause_id"]]
        add(clause_id=clause.id, rule_id=r["rule_id"], kind="rejected_finding", proposed_applies=False,
            verdict="none", route="review", route_reason=f"verifier_{r['stage']}", quote=r["quote"],
            explanation=f"The classifier proposed this; the verifier rejected it: {r['reason']}",
            confidence=None, rects=clause.rects)

    for cid, rule_id in run.possible_misses:
        clause = clauses[cid]
        add(clause_id=clause.id, rule_id=rule_id, kind="possible_miss", proposed_applies=False,
            verdict="none", route="review", route_reason="small_model_disagrees", quote=None,
            explanation="The LLM found no match, but the small model flags this clause for this rule.",
            confidence=None, rects=clause.rects)

    matched = {d.rule_id for d in decisions if d.kind == "finding"}
    for rule in policy.rules:
        if rule.kind == RuleKind.REQUIRED and rule.id not in matched:
            add(clause_id=None, rule_id=rule.id, kind="missing_required", proposed_applies=False,
                verdict="violated", route="review", route_reason="required_rule_missing", quote=None,
                explanation=f"No clause in the document was found to satisfy {rule.id} ({rule.title}).",
                confidence=None, rects=[])

    described = cfg.describe()
    analysis = Analysis(
        document_id=doc.id,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        pipeline=described["label"],
        prompt_hash=described["prompt_hash"],
        model_version=sorted({c.model_version for c in run.calls})[-1] if run.calls else client.model,
        auto_threshold=threshold,
        llm_calls=len(run.calls),
        clauses_screened_out=run.screened_out,
        status="needs_review" if any(d.route == "review" for d in decisions) else "complete",
        decisions=decisions,
    )
    session.add(analysis)
    session.commit()
    return analysis


def review_decision(session: Session, decision: Decision, action: str, reviewer: str, reason: str | None) -> Decision:
    """Approve or override a pending decision, and record the outcome as a new label."""
    if decision.status != "pending":
        raise ReviewError(f"Decision is already {decision.status}.")
    if action not in ("approve", "override"):
        raise ReviewError("Action must be 'approve' or 'override'.")
    if action == "override" and not (reason and reason.strip()):
        raise ReviewError("An override needs a reason.")

    decision.final_applies = decision.proposed_applies if action == "approve" else not decision.proposed_applies
    decision.status = "approved" if action == "approve" else "overridden"
    decision.reviewer = reviewer
    decision.review_reason = reason.strip() if reason else None
    decision.reviewed_at = datetime.now(timezone.utc)

    clause_text = None
    if decision.clause_id is not None:
        doc = session.get(Document, decision.analysis.document_id)
        clause_text = next(c.text for c in doc.clauses if c.id == decision.clause_id)
    session.add(Label(decision_id=decision.id, clause_text=clause_text, rule_id=decision.rule_id,
                      applies=decision.final_applies, source=decision.status,
                      policy_version=decision.analysis.policy_version))

    analysis = decision.analysis
    if all(d.status != "pending" for d in analysis.decisions):
        analysis.status = "complete"
    session.commit()
    return decision


def effective_status(analysis: Analysis, policy: Policy) -> dict[str, str]:
    """Per-rule outcome for the document, using reviewed answers where they exist.

    A rule is "violated", "flagged" or "satisfied" when a decision confirms it applies,
    "pending" while any decision about it awaits review, and otherwise "clear" (or
    "violated" for a required rule nothing satisfies).
    """
    out = {}
    for rule in policy.rules:
        ds = [d for d in analysis.decisions if d.rule_id == rule.id]
        if any(d.status == "pending" for d in ds):
            out[rule.id] = "pending"
            continue
        applies = [d for d in ds if d.clause_id is not None and d.final_applies]
        if rule.kind == RuleKind.REQUIRED:
            missing = [d for d in ds if d.kind == "missing_required"]
            confirmed_missing = any(d.final_applies is False for d in missing) and not applies
            out[rule.id] = "satisfied" if applies or (missing and not confirmed_missing) else "violated"
        elif applies:
            out[rule.id] = "violated" if rule.kind == RuleKind.PROHIBITED else "flagged"
        else:
            out[rule.id] = "clear"
    return out
