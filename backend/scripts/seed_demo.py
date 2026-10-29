"""Load a realistic demo: held-out CUAD contracts plus a Word NDA, analyzed, partly reviewed.

The reviewer is SIMULATED: each pending decision is approved or overridden according to
CUAD's lawyer annotations for that contract, and is labeled as simulated everywhere it
appears. About a quarter of the queue is left pending for a live demo. LLM responses are
cached, so re-seeding the same contracts costs nothing after the first run.

Usage: uv run python -m scripts.seed_demo [--api http://localhost:8000] [--reset]
"""

import argparse
import io
import json
import random
import re
import time
import zipfile
from pathlib import PurePosixPath

import docx
import httpx

from app.config import get_settings
from app.policy import load_policy

N_CONTRACTS = 6
REVIEW_SHARE = 0.75
REVIEWER = "demo reviewer (simulated from CUAD labels)"
SEED = 5


def squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def pick_contracts(data) -> list[dict]:
    """Held-out test contracts of moderate length, covering as many rules as possible."""
    splits = json.loads((data / "processed/splits.json").read_text(encoding="utf-8"))
    docs = [json.loads(line) for line in (data / "processed/documents.jsonl").open(encoding="utf-8")]
    pool = [d for d in docs if d["contract_id"] in set(splits["test_core"]) and 40 <= d["n_segments"] <= 130]
    random.Random(SEED).shuffle(pool)
    chosen, covered = [], set()
    for d in sorted(pool, key=lambda d: -len(set(d["rules_present"]))):
        if len(chosen) < N_CONTRACTS and (set(d["rules_present"]) - covered or len(chosen) < 3):
            chosen.append(d)
            covered |= set(d["rules_present"])
    chosen += [d for d in pool if d not in chosen][: N_CONTRACTS - len(chosen)]  # fill up once coverage is reached
    return chosen


def demo_nda() -> bytes:
    d = docx.Document()
    d.add_heading("MUTUAL NON-DISCLOSURE AGREEMENT", 1)
    for text in [
        "1. Purpose. The parties wish to evaluate a potential business relationship and may disclose confidential information to each other for that purpose.",
        "2. Term. This Agreement continues for two (2) years and shall automatically renew for successive one-year periods unless either party gives written notice of non-renewal at least thirty (30) days before the end of the then-current term.",
        "3. Non-Solicitation. For twelve months after termination, neither party shall solicit any customer of the other party introduced through the evaluation.",
        "4. Remedies. Each party shall be liable for all damages arising from its breach of this Agreement, without limitation.",
        "5. Governing Law. This Agreement is governed by the laws of the State of California.",
        "6. Assignment. Neither party may assign this Agreement without the prior written consent of the other party.",
    ]:
        d.add_paragraph(text)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--reset", action="store_true", help="delete all existing documents first")
    args = ap.parse_args()
    data = get_settings().data_dir
    policy = load_policy(1)
    cat_to_rule = policy.category_to_rule()

    contracts = pick_contracts(data)
    archive = zipfile.ZipFile(data / "raw/cuad_pdfs/CUAD_v1.zip")
    pdfs = {PurePosixPath(n).stem.strip(): n for n in archive.namelist() if n.lower().endswith(".pdf")}
    cuad = {d["title"]: d["paragraphs"][0] for d in json.loads((data / "raw/cuad/CUADv1.json").read_text(encoding="utf-8"))["data"]}

    with httpx.Client(base_url=args.api, timeout=600) as api:
        if args.reset:
            for d in api.get("/documents", params={"limit": 200}).json():
                api.delete(f"/documents/{d['id']}")
            print("removed existing documents")

        files, truth = [], {}
        for c in contracts:
            name = re.sub(r"[^A-Za-z0-9]+", "_", c["title"].split("-EX-")[0]).strip("_").lower()[:40] + ".pdf"
            files.append(("files", (name, archive.read(pdfs[c["title"]]))))
            spans = {}
            for qa in cuad[c["title"]]["qas"]:
                rule = cat_to_rule.get(qa["id"].split("__")[-1])
                if rule:
                    spans.setdefault(rule, []).extend(squash(a["text"]) for a in qa["answers"])
            truth[name] = {"spans": spans, "required": c["required_verdicts"]}
        files.append(("files", ("mutual_nda.docx", demo_nda())))

        print(f"uploading {len(files)} documents and analyzing (about a minute each on the free tier)...")
        batch = api.post("/batches", files=files).json()
        while batch["status"] != "done":
            time.sleep(5)
            batch = api.get(f"/batches/{batch['id']}").json()
            print(f"  {batch['status']}: {batch['counts']}", flush=True)

        rng = random.Random(SEED)
        reviewed = overridden = 0
        for item in batch["items"]:
            t = truth.get(item["filename"])
            if item["status"] != "analyzed" or t is None:
                continue  # the NDA has no lawyer labels: leave it all for a live review
            analysis = api.get(f"/analyses/{item['analysis_id']}").json()
            clauses = {c["id"]: c["text"] for c in api.get(f"/documents/{item['document_id']}").json()["clauses"]}
            for d in analysis["decisions"]:
                if d["status"] != "pending" or rng.random() > REVIEW_SHARE:
                    continue
                if d["kind"] == "missing_required":
                    # Here "applies" means the document satisfies the rule; the proposal is that it does not.
                    applies = t["required"][d["rule_id"]] == "satisfied"
                else:
                    text = squash(clauses[d["clause_id"]])
                    applies = any(s and (s in text or (len(text) >= 40 and text in s)) for s in t["spans"].get(d["rule_id"], []))
                agree = applies == d["proposed_applies"]
                body = {"action": "approve" if agree else "override", "reviewer": REVIEWER,
                        "reason": None if agree else f"CUAD annotation says {d['rule_id']} {'applies' if applies else 'does not apply'} here."}
                api.post(f"/decisions/{d['id']}/review", json=body).raise_for_status()
                reviewed += 1
                overridden += not agree

        m = api.get("/metrics").json()
        print(f"simulated reviews: {reviewed} ({overridden} overrides); still pending: {m['pending_reviews']}")
        print(f"automation rate {m['automation_rate']:.0%}, clauses without a human {m['clauses_without_human']:.0%}, "
              f"audit chain valid: {api.get('/audit/verify').json()['valid']}")


if __name__ == "__main__":
    main()
