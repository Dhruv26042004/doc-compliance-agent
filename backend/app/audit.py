"""Append to and verify the hash-chained audit log."""

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AuditEvent

GENESIS = "0" * 64


def _digest(prev_hash: str, at: datetime, actor: str, event: str, entity_type: str,
            entity_id: str, document_id: str | None, data: dict) -> str:
    # Normalize to UTC: the database may hand the timestamp back in another time zone.
    payload = json.dumps(
        [prev_hash, at.astimezone(timezone.utc).isoformat(), actor, event, entity_type, entity_id, document_id, data],
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def record(session: Session, event: str, entity_type: str, entity_id, *, actor: str = "system",
           document_id=None, data: dict | None = None) -> AuditEvent:
    """Append one event. Call inside the transaction that makes the change, before commit,
    so the change and its audit record are committed together or not at all."""
    # Serialize appends so two writers cannot chain onto the same previous hash.
    session.execute(text("SELECT pg_advisory_xact_lock(727274)"))
    prev = session.scalar(select(AuditEvent.hash).order_by(AuditEvent.seq.desc()).limit(1)) or GENESIS
    at = datetime.now(timezone.utc)
    data = json.loads(json.dumps(data or {}, default=str))  # store exactly what was hashed
    doc = str(document_id) if document_id is not None else None
    ev = AuditEvent(at=at, actor=actor, event=event, entity_type=entity_type, entity_id=str(entity_id),
                    document_id=doc, data=data, prev_hash=prev,
                    hash=_digest(prev, at, actor, event, entity_type, str(entity_id), doc, data))
    session.add(ev)
    session.flush()  # the next append in this transaction must see this hash
    return ev


def verify_chain(session: Session) -> dict:
    """Recompute every hash in order. Any edited, inserted, or removed row breaks the chain."""
    prev, n = GENESIS, 0
    for ev in session.scalars(select(AuditEvent).order_by(AuditEvent.seq)):
        expected = _digest(prev, ev.at, ev.actor, ev.event, ev.entity_type, ev.entity_id, ev.document_id, ev.data)
        if ev.prev_hash != prev or ev.hash != expected:
            return {"valid": False, "events_checked": n, "broken_at_seq": ev.seq}
        prev, n = ev.hash, n + 1
    return {"valid": True, "events_checked": n, "head": prev}
