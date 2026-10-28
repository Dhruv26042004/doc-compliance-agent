"""Ingest an uploaded file: parse it, split it into clauses, store rows and files."""

import hashlib
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Clause, Document
from app.parsing import detect_type, parse_document
from app.segmenter import split_text


def pdf_path(storage_dir: Path, doc_id: uuid.UUID) -> Path:
    return storage_dir / f"{doc_id}.pdf"


def span_rects(doc: Document, start: int, end: int) -> list[dict]:
    """Line rectangles covering doc.text[start:end]."""
    return [
        {"page": ln[0], "bbox": ln[1:5]}
        for ln in doc.lines
        if ln[5] < end and start < ln[6]
    ]


def ingest(session: Session, storage_dir: Path, filename: str, data: bytes) -> tuple[Document, bool]:
    """Returns (document, created). Re-uploading identical bytes returns the existing document."""
    digest = hashlib.sha256(data).hexdigest()
    existing = session.scalar(select(Document).where(Document.sha256 == digest))
    if existing is not None:
        return existing, False

    file_type = detect_type(data)
    parsed = parse_document(data)

    doc = Document(
        id=uuid.uuid4(),
        filename=Path(filename).name[:255] or f"upload.{file_type}",
        file_type=file_type,
        sha256=digest,
        size_bytes=len(data),
        n_pages=len(parsed.pages),
        has_layout=parsed.has_layout,
        text=parsed.text,
        pages=[{"number": p.number, "width": p.width, "height": p.height} for p in parsed.pages],
        lines=[[ln.page, *(round(v, 1) for v in ln.bbox), ln.start, ln.end] for ln in parsed.lines],
        warnings=parsed.warnings,
    )
    for i, seg in enumerate(split_text(parsed.text)):
        rects = parsed.rects(seg.start, seg.end)
        pages = [r["page"] for r in rects]
        doc.clauses.append(Clause(
            idx=i,
            char_start=seg.start,
            char_end=seg.end,
            text=parsed.text[seg.start : seg.end],
            page_start=min(pages) if pages else None,
            page_end=max(pages) if pages else None,
            rects=rects,
        ))

    storage_dir.mkdir(parents=True, exist_ok=True)
    (storage_dir / f"{doc.id}.original.{file_type}").write_bytes(data)
    if parsed.pdf_bytes is not None:
        pdf_path(storage_dir, doc.id).write_bytes(parsed.pdf_bytes)

    session.add(doc)
    session.commit()
    return doc, True


def delete(session: Session, storage_dir: Path, doc: Document) -> None:
    for f in storage_dir.glob(f"{doc.id}.*"):
        f.unlink(missing_ok=True)
    session.delete(doc)
    session.commit()
