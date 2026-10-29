from tests.test_documents_api import analyzed, pdf_bytes


def test_admin_token_protects_quota_and_deletes_but_not_reviews(client, monkeypatch):
    from app.config import get_settings

    doc, body = analyzed(client)  # created before the token is switched on
    monkeypatch.setattr(get_settings(), "admin_token", "s3cret")
    files = {"file": ("x.pdf", pdf_bytes())}

    assert client.post("/documents", files=files).status_code == 401
    assert client.post(f"/documents/{doc['id']}/analyze").status_code == 401
    assert client.delete(f"/documents/{doc['id']}").status_code == 401
    assert client.post("/batches", files=[("files", ("x.pdf", pdf_bytes()))]).status_code == 401
    assert client.post("/documents", files=files, headers={"X-Admin-Token": "wrong"}).status_code == 401
    assert "public demo" in client.post("/documents", files=files).json()["detail"]

    # Reading and reviewing stay open, so visitors can try the workflow.
    assert client.get("/documents").status_code == 200
    assert client.get("/reviews/queue").status_code == 200
    pending = next(d for d in body["decisions"] if d["status"] == "pending")
    assert client.post(f"/decisions/{pending['id']}/review", json={"action": "approve"}).status_code == 200

    ok = {"X-Admin-Token": "s3cret"}
    assert client.post("/documents", files=files, headers=ok).status_code == 201
    assert client.delete(f"/documents/{doc['id']}", headers=ok).status_code == 204
