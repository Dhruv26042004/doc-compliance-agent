from app.classifier import Finding
from app.fewshot import Example, ExampleIndex, render_examples
from app.llm import LLMResult
from app.pipeline import PipelineConfig, Resources, run_pipeline
from app.policy import load_policy
from app.verifier import VerifyResult, verify

import numpy as np

policy = load_policy(1)
GOV = "This Agreement is governed by the laws of Delaware."
WFH = "The Services shall not be deemed a work made for hire."
BORING = "Supplier shall deliver the Products to the address in the Order."


class ScriptedLLM:
    """Classifier batches get `classify`; verifier batches get `verify` (keyed by schema)."""

    model = "fake"

    def __init__(self, classify=None, verify=None):
        self.classify, self.verify, self.prompts = classify or {}, verify or {}, []

    def generate(self, system, prompt, schema):
        self.prompts.append(prompt)
        data = self.verify if schema is VerifyResult else self.classify
        schema.model_validate(data)
        return LLMResult(data=data, model_version="fake", input_tokens=1, output_tokens=1, latency_s=0)


def finding(rule, quote, found=True):
    return Finding(rule, quote, "e", 0.9, 0 if found else None, 5 if found else None)


def test_verifier_rejects_missing_quotes_and_unsupported_findings():
    findings = {"a": [finding("R-03", "governed by the laws of Delaware")],
                "b": [finding("R-09", "work made for hire")],
                "c": [finding("R-07", "invented text", found=False)]}
    llm = ScriptedLLM(verify={"results": [
        {"item_id": "v1", "supported": True, "reason": "Names governing law."},
        {"item_id": "v2", "supported": False, "reason": "The quote negates work-for-hire."},
    ]})
    run = verify(llm, policy, findings, {"a": GOV, "b": WFH, "c": BORING})
    assert set(run.kept) == {"a"}
    assert {(r["clause_id"], r["stage"]) for r in run.rejected} == {("b", "llm"), ("c", "quote_not_found")}
    assert len(llm.prompts) == 1 and "### Item v2" in llm.prompts[0] and "invented text" not in llm.prompts[0]


def test_verifier_fails_open_on_missing_answers():
    llm = ScriptedLLM(verify={"results": []})
    run = verify(llm, policy, {"a": [finding("R-03", "governed")]}, {"a": GOV})
    assert set(run.kept) == {"a"} and run.unanswered == 1


class StubPrefilter:
    def screen(self, texts):
        return [{"R-03"} if "governed" in t else set() for t in texts]

    def classify(self, texts):
        # Agrees with the LLM on R-03, and thinks the delivery clause is about audit rights.
        return [{"R-03"} if "governed" in t else {"R-12"} for t in texts]


def test_pipeline_skips_screened_clauses_and_adds_examples():
    examples = ExampleIndex([Example("Governed by New York law.", ["R-03"]), Example("Payment is due monthly.", [])],
                            np.eye(2, 384, dtype=np.float32))
    examples.retrieve = lambda texts, **kw: examples.examples  # no embedding model in unit tests
    llm = ScriptedLLM(classify={"results": [{"clause_id": "c1", "matches": [
        {"rule_id": "R-03", "quote": "governed by the laws of Delaware", "explanation": "e", "confidence": 0.95}]}]})
    cfg = PipelineConfig(prefilter=True, fewshot=True)
    run = run_pipeline(llm, policy, [("s1", BORING), ("s2", GOV)], cfg, Resources(StubPrefilter(), examples))

    assert run.screened_out == 1
    assert set(run.findings) == {"s2"}  # local id c1 maps to the only clause sent
    assert run.possible_misses == [("s1", "R-12")]  # small model flags it, the LLM never saw it
    (prompt,) = llm.prompts
    assert "[R-03] Governed by New York law." in prompt and "[matches no rule]" in prompt
    assert BORING not in prompt
    assert cfg.label == "v1+pf+fs"


def test_render_examples_truncates_long_text():
    line = render_examples([Example("x" * 2000, [])]).splitlines()[-1]
    assert line == "- [matches no rule] " + "x" * 500 + " ..."
