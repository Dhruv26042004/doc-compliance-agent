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
                                             "explanation": "Names Delaware law.", "confidence": 0.97}]},
            {"clause_id": "c3", "matches": [{"rule_id": "R-08", "quote": "may only be transferred with permission",
                                             "explanation": "Restricts assignment.", "confidence": 0.6}]},
        ]}
        schema.model_validate(data)
        return LLMResult(data=data, model_version="fake-model-001", input_tokens=1, output_tokens=1, latency_s=0)


def test_analyze_maps_findings_to_verdicts_and_highlights(client):
    from app.main import app
    from app.routers.documents import get_llm_client

    app.dependency_overrides[get_llm_client] = lambda: FakeLLM()
    doc = upload(client, "msa.pdf", pdf_bytes()).json()
    resp = client.post(f"/documents/{doc['id']}/analyze")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["model_version"] == "fake-model-001" and body["policy_version"] == 1
    assert body["required_rules"] == {"R-01": "violated", "R-03": "satisfied"}
    gov, assign = body["findings"]
    assert (gov["rule_id"], gov["verdict"], gov["quote_found"]) == ("R-03", "satisfies", True)
    assert doc["text"][gov["quote_start"] : gov["quote_end"]] == "governed by the laws of the State of Delaware"
    assert gov["rects"] == doc["clauses"][1]["rects"]  # single-line clause: quote is on that line
    # A quote that is not in the clause is flagged, and the whole clause is highlighted instead.
    assert (assign["verdict"], assign["quote_found"], assign["quote_start"]) == ("flag", False, None)
    assert assign["rects"] == doc["clauses"][2]["rects"]
    assert body["n_violations"] == 1 and body["n_flags"] == 1  # R-01 missing; R-08 flagged
