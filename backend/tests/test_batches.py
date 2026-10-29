from tests.test_documents_api import FakeLLM, docx_bytes, pdf_bytes


def test_batch_uploads_then_analyzes_in_background(client):
    from app.analysis import default_config
    from app.main import app
    from app.pipeline import PipelineConfig
    from app.routers.documents import get_llm_client

    app.dependency_overrides[get_llm_client] = lambda: FakeLLM()
    app.dependency_overrides[default_config] = lambda: PipelineConfig()
    files = [("files", ("a.pdf", pdf_bytes())), ("files", ("b.docx", docx_bytes())), ("files", ("notes.txt", b"plain text"))]
    resp = client.post("/batches", files=files)
    assert resp.status_code == 202, resp.text
    batch_id = resp.json()["id"]

    # TestClient runs background tasks before returning, so the batch is already finished.
    batch = client.get(f"/batches/{batch_id}").json()
    assert batch["status"] == "done"
    assert batch["counts"] == {"analyzed": 2, "failed": 1}
    bad = next(i for i in batch["items"] if i["filename"] == "notes.txt")
    assert "Unsupported" in bad["error"] and bad["document_id"] is None
    for item in batch["items"][:2]:
        assert client.get(f"/analyses/{item['analysis_id']}").json()["document_id"] == item["document_id"]
    assert client.get("/audit", params={"event": "batch.created"}).json()[0]["data"]["files"] == 3


def test_batch_without_analysis_and_limits(client):
    resp = client.post("/batches", params={"analyze": "false"}, files=[("files", ("a.pdf", pdf_bytes()))])
    assert resp.status_code == 202 and resp.json()["status"] == "done"
    assert resp.json()["counts"] == {"uploaded": 1}
    assert client.post("/batches", files=[]).status_code == 422
    assert client.get("/batches/00000000-0000-0000-0000-000000000000").status_code == 404
