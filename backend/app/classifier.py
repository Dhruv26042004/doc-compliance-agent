"""Classify contract clauses against the policy with an LLM.

Clauses are sent in batches (one contract at a time) to keep request counts inside
free-tier limits. Every returned quote is checked against the clause text: a quote that
cannot be found is kept but flagged, and the Phase 4 verifier builds on that flag.
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, create_model

from app.llm import LLMResult
from app.policy import Policy

PROMPT_DIR = Path(__file__).parent / "prompts"
MAX_BATCH_CLAUSES = 40  # larger batches = fewer requests against daily free-tier caps
MAX_BATCH_CHARS = 30_000


@dataclass
class Finding:
    rule_id: str
    quote: str
    explanation: str
    confidence: float
    quote_start: int | None  # offsets within the clause text; None if the quote was not found
    quote_end: int | None

    @property
    def quote_found(self) -> bool:
        return self.quote_start is not None


@dataclass
class ClassifierRun:
    findings: dict[str, list[Finding]] = field(default_factory=dict)  # clause id -> findings
    calls: list[LLMResult] = field(default_factory=list)
    dropped: int = 0  # findings for unknown clause ids (schema already restricts rule ids)


# ---------------------------------------------------------------- prompt


def load_prompt(version: str = "v1") -> tuple[str, str]:
    """Returns (template, short hash). The hash is stored with every run for auditability."""
    template = (PROMPT_DIR / f"classify_{version}.md").read_text(encoding="utf-8")
    return template, hashlib.sha256(template.encode()).hexdigest()[:12]


def render_rules(policy: Policy) -> str:
    blocks = []
    for r in policy.rules:
        lines = [f"## {r.id} [{r.kind.value}] {r.title}", f"Definition: {r.definition.strip()}"]
        lines += [f"- Matches: {m}" for m in r.matches]
        lines += [f"- Does not match: {m}" for m in r.does_not_match]
        if r.edge_notes:
            lines.append(f"Notes: {r.edge_notes.strip()}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def system_prompt(policy: Policy, version: str = "v1") -> str:
    template, _ = load_prompt(version)
    return template.format(policy_id=policy.policy_id, policy_version=policy.version, rules=render_rules(policy))


def response_schema(policy: Policy) -> type[BaseModel]:
    """Schema whose rule_id is an enum of this policy's rule ids."""
    rule_id_type = Literal[tuple(r.id for r in policy.rules)]
    match = create_model(
        "RuleMatch",
        rule_id=(rule_id_type, ...),
        quote=(str, ...),
        explanation=(str, ...),
        confidence=(float, Field(ge=0, le=1)),
    )
    clause = create_model("ClauseMatches", clause_id=(str, ...), matches=(list[match], ...))
    return create_model("BatchResult", results=(list[clause], ...))


def batches(clauses: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    out, cur, size = [], [], 0
    for cid, text in clauses:
        if cur and (len(cur) >= MAX_BATCH_CLAUSES or size + len(text) > MAX_BATCH_CHARS):
            out.append(cur)
            cur, size = [], 0
        cur.append((cid, text))
        size += len(text)
    if cur:
        out.append(cur)
    return out


def user_prompt(batch: list[tuple[str, str]]) -> str:
    return "Clauses:\n\n" + "\n\n".join(f"[c{i}]\n{text}" for i, (_, text) in enumerate(batch, start=1))


# ---------------------------------------------------------------- quotes


def locate_quote(text: str, quote: str) -> tuple[int, int] | None:
    """Find quote in text ignoring case, whitespace, punctuation and hyphenation."""
    kept = [(i, ch.lower()) for i, ch in enumerate(text) if ch.isalnum()]
    hay = "".join(ch for _, ch in kept)
    needle = re.sub(r"[^0-9a-z]", "", quote.lower())
    if not needle:
        return None
    pos = hay.find(needle)
    if pos < 0:
        return None
    return kept[pos][0], kept[pos + len(needle) - 1][0] + 1


# ---------------------------------------------------------------- run


def classify(client, policy: Policy, clauses: list[tuple[str, str]], prompt_version: str = "v1", pool=None) -> ClassifierRun:
    """clauses: (clause_id, text) pairs from ONE document, in reading order."""
    system = system_prompt(policy, prompt_version)
    schema = response_schema(policy)
    run = ClassifierRun()
    todo = batches(clauses)
    call = lambda b: (b, client.generate(system, user_prompt(b), schema))  # noqa: E731
    results = pool.map(call, todo) if pool else map(call, todo)

    for batch, result in results:
        run.calls.append(result)
        by_local_id = {f"c{i}": (cid, text) for i, (cid, text) in enumerate(batch, start=1)}
        for item in result.data["results"]:
            if item["clause_id"] not in by_local_id:
                run.dropped += len(item["matches"])
                continue
            cid, text = by_local_id[item["clause_id"]]
            best: dict[str, Finding] = {f.rule_id: f for f in run.findings.get(cid, [])}
            for m in item["matches"]:
                span = locate_quote(text, m["quote"])
                f = Finding(m["rule_id"], m["quote"], m["explanation"], m["confidence"],
                            span[0] if span else None, span[1] if span else None)
                if m["rule_id"] not in best or f.confidence > best[m["rule_id"]].confidence:
                    best[m["rule_id"]] = f
            run.findings[cid] = list(best.values())
    return run
