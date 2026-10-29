"""Run the decision pipeline over a stored document and turn findings into policy decisions."""

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from app.config import get_settings
from app.documents import span_rects
from app.models import Document
from app.pipeline import PipelineConfig, Resources, run_pipeline
from app.policy import Policy, RuleKind
from app.schemas import AnalysisOut, FindingOut, RejectedOut

# What a matching clause means for each kind of rule.
VERDICT = {RuleKind.REQUIRED: "satisfies", RuleKind.PROHIBITED: "violation", RuleKind.REVIEW: "flag"}


def default_config() -> PipelineConfig:
    s = get_settings()
    return PipelineConfig("v1", s.pipeline_prefilter, s.pipeline_fewshot, s.pipeline_verify)


@lru_cache
def _resources(cfg: PipelineConfig) -> Resources:
    return Resources.for_config(cfg)  # loaded once per process


def analyze_document(client, policy: Policy, doc: Document, cfg: PipelineConfig | None = None,
                     res: Resources | None = None) -> AnalysisOut:
    cfg = cfg or default_config()
    res = res or _resources(cfg)
    clauses = {str(c.id): c for c in doc.clauses}
    with ThreadPoolExecutor(max_workers=get_settings().llm_max_workers) as pool:
        run = run_pipeline(client, policy, [(cid, c.text) for cid, c in clauses.items()], cfg, res, pool)

    findings = []
    for cid, clause in clauses.items():
        for f in run.findings.get(cid, []):
            rule = policy.rule(f.rule_id)
            if f.quote_found:
                start, end = clause.char_start + f.quote_start, clause.char_start + f.quote_end
                rects = span_rects(doc, start, end) or clause.rects
            else:
                start = end = None
                rects = clause.rects  # fall back to highlighting the whole clause
            findings.append(FindingOut(
                clause_id=clause.id,
                clause_idx=clause.idx,
                rule_id=rule.id,
                rule_title=rule.title,
                rule_kind=rule.kind.value,
                severity=rule.severity.value,
                verdict=VERDICT[rule.kind],
                quote=f.quote,
                quote_found=f.quote_found,
                quote_start=start,
                quote_end=end,
                explanation=f.explanation,
                confidence=f.confidence,
                rects=rects,
            ))

    matched = {f.rule_id for f in findings}
    required = {
        r.id: ("satisfied" if r.id in matched else "violated")
        for r in policy.rules if r.kind == RuleKind.REQUIRED
    }
    described = cfg.describe()
    return AnalysisOut(
        document_id=doc.id,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        prompt_version=cfg.prompt_version,
        prompt_hash=described["prompt_hash"],
        pipeline=described["label"],
        model_version=sorted({c.model_version for c in run.calls})[-1] if run.calls else client.model,
        llm_calls=len(run.calls),
        clauses_screened_out=run.screened_out,
        required_rules=required,
        n_violations=sum(f.verdict == "violation" for f in findings) + sum(v == "violated" for v in required.values()),
        n_flags=sum(f.verdict == "flag" for f in findings),
        findings=findings,
        rejected=[RejectedOut(clause_id=r["clause_id"], clause_idx=clauses[r["clause_id"]].idx,
                              rule_id=r["rule_id"], quote=r["quote"], stage=r["stage"], reason=r["reason"])
                  for r in run.rejected],
    )
