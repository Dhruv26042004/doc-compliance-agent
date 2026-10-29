"""The full decision pipeline, shared by the evaluation script and the API:

  tier-1 prefilter -> (retrieved examples) -> LLM classifier -> (verifier)

Each stage is switchable so its effect on accuracy and cost can be measured alone.
"""

from dataclasses import dataclass, field

from app.classifier import Finding, classify, load_prompt
from app.fewshot import ExampleIndex, render_examples
from app.llm import LLMResult
from app.policy import Policy
from app.prefilter import Prefilter
from app.verifier import prompt_hash as verify_prompt_hash
from app.verifier import verify


@dataclass(frozen=True)
class PipelineConfig:
    prompt_version: str = "v1"
    prefilter: bool = False
    fewshot: bool = False
    verify: bool = False

    @property
    def label(self) -> str:
        parts = [self.prompt_version] + [n for n, on in (("pf", self.prefilter), ("fs", self.fewshot), ("ver", self.verify)) if on]
        return "+".join(parts)

    def describe(self) -> dict:
        _, classify_hash = load_prompt(self.prompt_version)
        return {
            "label": self.label,
            "prompt_version": self.prompt_version,
            "prompt_hash": classify_hash,
            "prefilter": self.prefilter,
            "fewshot": self.fewshot,
            "verify": self.verify,
            "verify_prompt_hash": verify_prompt_hash() if self.verify else None,
        }


@dataclass
class PipelineRun:
    findings: dict[str, list[Finding]] = field(default_factory=dict)
    calls: list[LLMResult] = field(default_factory=list)
    screened_out: int = 0  # clauses decided "no match" by the prefilter, never sent to the LLM
    rejected: list[dict] = field(default_factory=list)  # findings removed by the verifier
    # (clause id, rule id) pairs the small model flags but the LLM did not: possible misses.
    possible_misses: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Resources:
    """Loaded once and shared across documents."""

    prefilter: Prefilter | None = None
    examples: ExampleIndex | None = None

    @classmethod
    def for_config(cls, cfg: PipelineConfig) -> "Resources":
        res = cls(
            prefilter=Prefilter.load() if cfg.prefilter else None,
            examples=ExampleIndex.load() if cfg.fewshot else None,
        )
        if res.examples:
            res.examples.retrieve(["warm up the embedding model"])  # load it before threads start
        return res


def run_pipeline(client, policy: Policy, clauses: list[tuple[str, str]], cfg: PipelineConfig,
                 res: Resources, pool=None) -> PipelineRun:
    run = PipelineRun()
    text = dict(clauses)

    all_clauses = clauses
    if cfg.prefilter:
        candidates = res.prefilter.screen([t for _, t in clauses])
        sent = [c for c, cand in zip(clauses, candidates) if cand]
        run.screened_out = len(clauses) - len(sent)
        clauses = sent

    context = (lambda batch: render_examples(res.examples.retrieve([t for _, t in batch]))) if cfg.fewshot else None
    if clauses:
        c = classify(client, policy, clauses, cfg.prompt_version, pool, context)
        run.findings, run.calls = c.findings, c.calls

    if cfg.verify and run.findings:
        v = verify(client, policy, run.findings, text)
        run.findings, run.rejected = v.kept, v.rejected
        run.calls += v.calls

    if cfg.prefilter:
        # Safety net for recall: confidence can only route findings that exist, so a
        # clause the small model is confident about but the LLM left empty goes to review.
        small = res.prefilter.classify([t for _, t in all_clauses])
        rejected = {(r["clause_id"], r["rule_id"]) for r in run.rejected}
        for (cid, _), rules in zip(all_clauses, small):
            found = {f.rule_id for f in run.findings.get(cid, [])}
            run.possible_misses += [(cid, r) for r in sorted(rules - found) if (cid, r) not in rejected]
    return run
