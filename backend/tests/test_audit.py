import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.test_documents_api import analyzed


def test_lifecycle_is_audited_in_order(client):
    doc, body = analyzed(client)
    pending = [d for d in body["decisions"] if d["status"] == "pending"]
    client.post(f"/decisions/{pending[0]['id']}/review", json={"action": "approve", "reviewer": "dana"})

    events = list(reversed(client.get("/audit", params={"document_id": doc["id"]}).json()))
    kinds = [e["event"] for e in events]
    assert kinds[0] == "document.uploaded" and kinds[1] == "analysis.created"
    assert kinds.count("decision.created") == len(body["decisions"])
    assert kinds[-1] == "decision.reviewed"

    created = events[1]["data"]
    assert created["model_version"] == "fake-model-001" and created["policy_version"] == 1
    assert created["prompt_hash"] == body["prompt_hash"] and created["auto_threshold"] == 0.99
    reviewed = events[-1]
    assert reviewed["actor"] == "dana" and reviewed["data"]["action"] == "approve"

    client.delete(f"/documents/{doc['id']}")
    # Events outlive the document they describe.
    assert client.get("/audit", params={"document_id": doc["id"]}).json()[0]["event"] == "document.deleted"
    assert client.get("/audit/verify").json()["valid"] is True


def test_database_rejects_edits_and_deletes(client):
    from app.db import engine

    analyzed(client)
    for stmt in ("UPDATE audit_events SET actor = 'mallory'", "DELETE FROM audit_events"):
        with pytest.raises(DBAPIError, match="append-only"):
            with engine.begin() as conn:
                conn.execute(text(stmt))


def test_verify_detects_tampering(client):
    from app.db import engine

    analyzed(client)
    assert client.get("/audit/verify").json()["valid"] is True
    # Someone with admin rights switches off the trigger and rewrites history...
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_change"))
        seq = conn.scalar(text("SELECT seq FROM audit_events WHERE event = 'analysis.created'"))
        conn.execute(text("UPDATE audit_events SET data = jsonb_set(data::jsonb, '{model_version}', '\"gpt-x\"')::json WHERE seq = :s"), {"s": seq})
        conn.execute(text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_no_change"))
    # ...and the chain shows exactly where.
    result = client.get("/audit/verify").json()
    assert result["valid"] is False and result["broken_at_seq"] == seq
