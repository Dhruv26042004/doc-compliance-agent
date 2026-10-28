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
