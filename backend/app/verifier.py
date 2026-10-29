"""Second pass: check that each finding's quote really supports its rule.

Two stages. First, free: a quote that cannot be found in the clause is rejected
(on the dev baseline those findings were right only 27% of the time). Second, an LLM
re-reads each remaining finding with the rule definition and answers supported / not.
The verifier fails open: a finding the model does not answer for is kept.
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from app.classifier import Finding
from app.llm import LLMResult
from app.policy import Policy

PROMPT_PATH = Path(__file__).parent / "prompts" / "verify_v1.md"
BATCH_SIZE = 15
MAX_CLAUSE_CHARS = 1500


class Verdict(BaseModel):
    item_id: str
    supported: bool
    reason: str


class VerifyResult(BaseModel):
    results: list[Verdict]


@dataclass
class VerifyRun:
    kept: dict[str, list[Finding]] = field(default_factory=dict)
    rejected: list[dict] = field(default_factory=list)  # {clause_id, rule_id, quote, stage, reason}
    calls: list[LLMResult] = field(default_factory=list)
    unanswered: int = 0


def prompt_hash() -> str:
    return hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest()[:12]


def _item(i: int, policy: Policy, clause: str, f: Finding) -> str:
    rule = policy.rule(f.rule_id)
    clause = clause if len(clause) <= MAX_CLAUSE_CHARS else clause[:MAX_CLAUSE_CHARS] + " ..."
    not_match = "\n".join(f"  - {m}" for m in rule.does_not_match)
    return (
        f"### Item v{i}\n"
        f"RULE {rule.id} [{rule.kind.value}] {rule.title}: {rule.definition.strip()}\n"
        f"Does not match, e.g.:\n{not_match}\n"
        f"CLAUSE: {clause}\n"
        f"QUOTE: {f.quote}"
    )


def verify(client, policy: Policy, findings: dict[str, list[Finding]], clause_text: dict[str, str]) -> VerifyRun:
    run = VerifyRun()
    pending: list[tuple[str, Finding]] = []
    for cid, fs in findings.items():
        for f in fs:
            if f.quote_found:
                pending.append((cid, f))
            else:
                run.rejected.append({"clause_id": cid, "rule_id": f.rule_id, "quote": f.quote,
                                     "stage": "quote_not_found", "reason": "Quote does not appear in the clause."})

    system = PROMPT_PATH.read_text(encoding="utf-8")
    for start in range(0, len(pending), BATCH_SIZE):
        batch = pending[start : start + BATCH_SIZE]
        prompt = "\n\n".join(_item(i, policy, clause_text[cid], f) for i, (cid, f) in enumerate(batch, start=1))
        result = client.generate(system, prompt, VerifyResult)
        run.calls.append(result)
        answers = {r["item_id"]: r for r in result.data["results"]}
        for i, (cid, f) in enumerate(batch, start=1):
            ans = answers.get(f"v{i}")
            if ans is None:
                run.unanswered += 1
            if ans is None or ans["supported"]:
                run.kept.setdefault(cid, []).append(f)
            else:
                run.rejected.append({"clause_id": cid, "rule_id": f.rule_id, "quote": f.quote,
                                     "stage": "llm", "reason": ans["reason"]})
    return run
