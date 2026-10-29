import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(10))  # pdf | docx
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    n_pages: Mapped[int] = mapped_column(Integer)
    has_layout: Mapped[bool]
    text: Mapped[str] = mapped_column(Text)
    pages: Mapped[list] = mapped_column(JSON)  # [{number, width, height}]
    # Line layout as [page, x0, y0, x1, y1, char_start, char_end], for highlighting any span.
    lines: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    clauses: Mapped[list["Clause"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="Clause.idx"
    )


class Clause(Base):
    __tablename__ = "clauses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)  # position within the document
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    rects: Mapped[list] = mapped_column(JSON, default=list)  # [{page, bbox: [x0, y0, x1, y1]}]

    document: Mapped[Document] = relationship(back_populates="clauses")


class Analysis(Base):
    """One run of the decision pipeline over a document, with everything needed to reproduce it."""

    __tablename__ = "analyses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    policy_id: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[int] = mapped_column(Integer)
    pipeline: Mapped[str] = mapped_column(String(64))  # e.g. v1+pf+fs+ver
    prompt_hash: Mapped[str] = mapped_column(String(32))
    model_version: Mapped[str] = mapped_column(String(128))
    auto_threshold: Mapped[float]
    llm_calls: Mapped[int] = mapped_column(Integer)
    clauses_screened_out: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))  # needs_review | complete

    decisions: Mapped[list["Decision"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", order_by="Decision.position"
    )


class Decision(Base):
    """One proposed statement ("clause X matches rule R"), how it was routed, and its review."""

    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    clause_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clauses.id", ondelete="CASCADE"))
    rule_id: Mapped[str] = mapped_column(String(16))
    # finding | rejected_finding | possible_miss | missing_required
    kind: Mapped[str] = mapped_column(String(24))
    proposed_applies: Mapped[bool]  # the model's proposal: does the rule apply here?
    verdict: Mapped[str] = mapped_column(String(16))  # violation | flag | satisfies | violated | none
    route: Mapped[str] = mapped_column(String(8))  # auto | review
    route_reason: Mapped[str] = mapped_column(String(32))
    quote: Mapped[str | None] = mapped_column(Text)
    quote_start: Mapped[int | None] = mapped_column(Integer)
    quote_end: Mapped[int | None] = mapped_column(Integer)
    explanation: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None]
    rects: Mapped[list] = mapped_column(JSON, default=list)
    # auto | pending | approved | overridden
    status: Mapped[str] = mapped_column(String(12), index=True)
    final_applies: Mapped[bool | None]
    reviewer: Mapped[str | None] = mapped_column(String(128))
    review_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    analysis: Mapped[Analysis] = relationship(back_populates="decisions")


class Label(Base):
    """A human-confirmed label created by a review: new training and evaluation data."""

    __tablename__ = "labels"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    decision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decisions.id", ondelete="CASCADE"), index=True)
    clause_text: Mapped[str | None] = mapped_column(Text)  # None for document-level decisions
    rule_id: Mapped[str] = mapped_column(String(16))
    applies: Mapped[bool]
    source: Mapped[str] = mapped_column(String(16))  # approved | overridden
    policy_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(Base):
    """Append-only, hash-chained record of everything the system and its reviewers did.

    No foreign keys: events must outlive the documents they describe. A database
    trigger rejects UPDATE and DELETE, and each row's hash covers the previous row's
    hash, so a rewritten history is detectable (see app.audit.verify_chain).
    """

    __tablename__ = "audit_events"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor: Mapped[str] = mapped_column(String(128))  # "system" or a reviewer name
    event: Mapped[str] = mapped_column(String(48), index=True)  # e.g. decision.reviewed
    entity_type: Mapped[str] = mapped_column(String(24))
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    document_id: Mapped[str | None] = mapped_column(String(64), index=True)
    data: Mapped[dict] = mapped_column(JSON)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)
