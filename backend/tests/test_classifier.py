import pytest
from pydantic import ValidationError

from app.classifier import MAX_BATCH_CHARS, MAX_BATCH_CLAUSES, batches, classify, locate_quote, response_schema, system_prompt
from app.llm import LLMResult
from app.policy import load_policy

policy = load_policy(1)


class FakeClient:
    """Returns canned responses keyed by which clause text appears in the prompt."""

    def __init__(self, responses):
        self.responses = responses
        self.prompts = []

    def generate(self, system, prompt, schema):
        self.prompts.append(prompt)
        data = {"results": [r for r in self.responses if r.pop("_needle") in prompt]} if self.responses else {"results": []}
        schema.model_validate(data)  # the fake must honour the same schema as the real model
        return LLMResult(data=data, model_version="fake", input_tokens=10, output_tokens=5, latency_s=0)


def test_locate_quote_ignores_case_spacing_and_hyphens():
    text = "12.  Governing   Law. This Agreement is governed by the laws of the State of New-York."
    start, end = locate_quote(text, "governed by the laws of the state of new york")
    assert text[start:end] == "governed by the laws of the State of New-York"
    assert locate_quote(text, "governed by English law") is None
    assert locate_quote(text, "...") is None


def test_batches_respect_count_and_size_limits():
    clauses = [(f"s{i}", "x" * 100) for i in range(2 * MAX_BATCH_CLAUSES + 5)]
    out = batches(clauses)
    assert [len(b) for b in out] == [MAX_BATCH_CLAUSES, MAX_BATCH_CLAUSES, 5]
    big = [("a", "x" * (MAX_BATCH_CHARS - 10)), ("b", "x" * 20)]
    assert [len(b) for b in batches(big)] == [1, 1]


def test_schema_only_allows_policy_rule_ids():
    schema = response_schema(policy)
    ok = {"results": [{"clause_id": "c1", "matches": [{"rule_id": "R-03", "quote": "q", "explanation": "e", "confidence": 0.9}]}]}
    schema.model_validate(ok)
    bad = {"results": [{"clause_id": "c1", "matches": [{"rule_id": "R-99", "quote": "q", "explanation": "e", "confidence": 0.9}]}]}
    with pytest.raises(ValidationError):
        schema.model_validate(bad)


def test_system_prompt_contains_every_rule():
    text = system_prompt(policy)
    for r in policy.rules:
        assert f"## {r.id} [{r.kind.value}]" in text
    assert "{" not in text.split("# Policy")[1].split("\n")[0]  # placeholders all filled


def test_classify_maps_local_ids_and_flags_bad_quotes():
    clauses = [
        ("doc-S0", "This Agreement is governed by the laws of Delaware."),
        ("doc-S1", "Supplier shall deliver the Products."),
        ("doc-S2", "Neither party may assign this Agreement without consent."),
    ]
    fake = FakeClient([
        {"_needle": "Delaware", "clause_id": "c1", "matches": [
            {"rule_id": "R-03", "quote": "governed by the laws of Delaware", "explanation": "e", "confidence": 0.95},
            {"rule_id": "R-03", "quote": "laws of Delaware", "explanation": "e", "confidence": 0.5},  # duplicate rule
        ]},
        {"_needle": "assign", "clause_id": "c3", "matches": [
            {"rule_id": "R-08", "quote": "may not transfer the contract", "explanation": "e", "confidence": 0.8},
        ]},
        {"_needle": "Products", "clause_id": "c9", "matches": [
            {"rule_id": "R-07", "quote": "x", "explanation": "e", "confidence": 0.8},
        ]},
    ])
    run = classify(fake, policy, clauses)
    assert set(run.findings) == {"doc-S0", "doc-S2"}
    (gov,) = run.findings["doc-S0"]
    assert gov.confidence == 0.95 and gov.quote_found
    (assign,) = run.findings["doc-S2"]
    assert assign.rule_id == "R-08" and not assign.quote_found  # paraphrased quote is flagged
    assert run.dropped == 1  # c9 does not exist in the batch
    assert len(fake.prompts) == 1 and "[c3]" in fake.prompts[0]
