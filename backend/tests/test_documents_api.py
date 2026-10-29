import io

import docx
import pymupdf

from app.config import get_settings

CLAUSES = [
    "1. Term. This Agreement begins on the Effective Date and continues for three years.",
    "2. Governing Law. This Agreement is governed by the laws of the State of Delaware.",
    "3. Assignment. Neither party may assign this Agreement without prior written consent.",
]


def pdf_bytes() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    for i, clause in enumerate(CLAUSES):
        page.insert_text((72, 100 + 40 * i), clause, fontsize=9)
    return doc.tobytes()


def docx_bytes() -> bytes:
    d = docx.Document()
    for clause in CLAUSES:
        d.add_paragraph(clause)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def upload(client, name, data):
    return client.post("/documents", files={"file": (name, data)})


def test_upload_pdf_returns_clauses_with_positions(client, tmp_path):
    resp = upload(client, "msa.pdf", pdf_bytes())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["file_type"] == "pdf" and body["has_layout"] and body["n_pages"] == 1
    assert [c["text"] for c in body["clauses"]] == CLAUSES
    for c in body["clauses"]:
        assert body["text"][c["char_start"] : c["char_end"]] == c["text"]
        assert c["page_start"] == c["page_end"] == 1
        assert c["rects"] and len(c["rects"][0]["bbox"]) == 4

    doc_id = body["id"]
    assert client.get(f"/documents/{doc_id}").json()["clauses"] == body["clauses"]
    pdf = client.get(f"/documents/{doc_id}/file")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    listed = client.get("/documents").json()
    assert [(d["id"], d["n_clauses"]) for d in listed] == [(doc_id, 3)]


def test_reupload_is_idempotent(client):
    data = pdf_bytes()  # generate once: each PDF build embeds a fresh timestamp
    first = upload(client, "a.pdf", data).json()
    again = upload(client, "renamed.pdf", data)
    assert again.status_code == 200
    assert again.json()["id"] == first["id"]
    assert len(client.get("/documents").json()) == 1


def test_docx_upload(client):
    resp = upload(client, "nda.docx", docx_bytes())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["file_type"] == "docx"
    assert [c["text"] for c in body["clauses"]] == CLAUSES
    pdf = client.get(f"/documents/{body['id']}/file")
    if body["has_layout"]:  # LibreOffice available (e.g. in Docker)
        assert pdf.status_code == 200 and body["clauses"][0]["rects"]
    else:
        assert pdf.status_code == 404 and body["warnings"]


def test_rejects_bad_uploads(client, monkeypatch):
    assert upload(client, "notes.txt", b"just some text").status_code == 415
    assert upload(client, "empty.pdf", b"").status_code == 422
    assert upload(client, "broken.pdf", b"%PDF-1.7 garbage").status_code == 422
    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    assert upload(client, "big.pdf", pdf_bytes()).status_code == 413


def test_delete_removes_rows_and_files(client, tmp_path):
    doc_id = upload(client, "msa.pdf", pdf_bytes()).json()["id"]
    assert list(tmp_path.glob(f"{doc_id}.*"))
    assert client.delete(f"/documents/{doc_id}").status_code == 204
    assert client.get(f"/documents/{doc_id}").status_code == 404
    assert not list(tmp_path.glob(f"{doc_id}.*"))


class FakeLLM:
    model = "fake-model"

    def generate(self, system, prompt, schema):
        from app.llm import LLMResult

        data = {"results": [
            {"clause_id": "c2", "matches": [{"rule_id": "R-03", "quote": "governed by the laws of the State of Delaware",
                                             "explanation": "Names Delaware law.", "confidence": 1.0}]},
            {"clause_id": "c3", "matches": [{"rule_id": "R-08", "quote": "may only be transferred with permission",
                                             "explanation": "Restricts assignment.", "confidence": 0.6}]},
        ]}
        schema.model_validate(data)
        return LLMResult(data=data, model_version="fake-model-001", input_tokens=1, output_tokens=1, latency_s=0)


def analyzed(client):
    from app.analysis import default_config
    from app.main import app
    from app.pipeline import PipelineConfig
    from app.routers.documents import get_llm_client

    app.dependency_overrides[get_llm_client] = lambda: FakeLLM()
    app.dependency_overrides[default_config] = lambda: PipelineConfig()  # classifier stage only
    doc = upload(client, "msa.pdf", pdf_bytes()).json()
    resp = client.post(f"/documents/{doc['id']}/analyze")
    assert resp.status_code == 200, resp.text
    return doc, resp.json()


def test_analyze_stores_and_routes_decisions(client):
    doc, body = analyzed(client)
    assert body["model_version"] == "fake-model-001" and body["pipeline"] == "v1" and body["auto_threshold"] == 0.99
    by_rule = {d["rule_id"]: d for d in body["decisions"]}

    gov = by_rule["R-03"]  # verified quote at confidence 1.0: decided automatically
    assert (gov["kind"], gov["route"], gov["status"], gov["final_applies"]) == ("finding", "auto", "auto", True)
    assert doc["text"][gov["quote_start"] : gov["quote_end"]] == "governed by the laws of the State of Delaware"
    assert gov["clause_idx"] == 1 and gov["rule_title"] == "Governing law required"

    assign = by_rule["R-08"]  # low confidence, and the quote is not in the clause: review
    assert (assign["route"], assign["status"], assign["quote_start"]) == ("review", "pending", None)
    assert assign["rects"] == doc["clauses"][2]["rects"]

    cap = by_rule["R-01"]  # nothing satisfies the required rule: a human confirms
    assert (cap["kind"], cap["verdict"], cap["route"], cap["clause_id"]) == ("missing_required", "violated", "review", None)

    assert body["status"] == "needs_review" and (body["n_auto"], body["n_pending"]) == (1, 2)
    assert body["rule_status"]["R-03"] == "satisfied" and body["rule_status"]["R-01"] == "pending"
    assert client.get(f"/documents/{doc['id']}/analysis").json()["id"] == body["id"]


def test_review_flow_records_labels(client):
    doc, body = analyzed(client)
    queue = client.get("/reviews/queue").json()
    assert {q["rule_id"] for q in queue} == {"R-01", "R-08"}
    assert all(q["filename"] == "msa.pdf" for q in queue)
    assert next(q for q in queue if q["rule_id"] == "R-08")["clause_text"].startswith("3. Assignment.")
    assert [q["rule_id"] for q in client.get("/reviews/queue", params={"rule_id": "R-08"}).json()] == ["R-08"]

    ids = {q["rule_id"]: q["id"] for q in queue}
    review = lambda rule, **body: client.post(f"/decisions/{ids[rule]}/review", json=body)  # noqa: E731

    assert review("R-08", action="override").status_code == 422  # an override needs a reason
    assert review("R-08", action="delete").status_code == 422

    ok = review("R-01", action="approve", reviewer="dana")
    assert ok.status_code == 200 and ok.json()["status"] == "approved" and ok.json()["final_applies"] is False
    assert review("R-01", action="approve").status_code == 409  # already reviewed

    # The finding says R-08 applies; the reviewer disagrees.
    over = review("R-08", action="override", reviewer="dana", reason="Clause 3 restricts assignment; quote was wrong.")
    assert over.json()["status"] == "overridden" and over.json()["final_applies"] is False

    final = client.get(f"/analyses/{body['id']}").json()
    assert final["status"] == "complete" and final["n_pending"] == 0
    assert final["rule_status"]["R-01"] == "violated" and final["rule_status"]["R-08"] == "clear"
    assert client.get("/reviews/queue").json() == []

    labels = {l["rule_id"]: l for l in client.get("/labels").json()}
    assert labels["R-08"]["applies"] is False and labels["R-08"]["source"] == "overridden"
    assert labels["R-08"]["clause_text"].startswith("3. Assignment.")
    assert labels["R-01"]["clause_text"] is None and labels["R-01"]["source"] == "approved"
