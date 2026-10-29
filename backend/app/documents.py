"""Ingest an uploaded file: parse it, split it into clauses, store rows and files."""

import hashlib
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.config import get_settings
from app.models import Clause, Document, StoredFile
from app.parsing import detect_type, parse_document
from app.segmenter import split_text


CONTENT_TYPES = {"pdf": "application/pdf",
                 "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def _use_db() -> bool:
    return get_settings().file_storage == "database"


def save_file(session: Session, storage_dir: Path, doc_id: uuid.UUID, kind: str, ext: str, data: bytes) -> None:
    """kind is "original" (the upload) or "pdf" (what the viewer shows)."""
    if _use_db():
        session.add(StoredFile(document_id=doc_id, kind=kind, content_type=CONTENT_TYPES[ext], content=data))
    else:
        storage_dir.mkdir(parents=True, exist_ok=True)
        name = f"{doc_id}.pdf" if kind == "pdf" else f"{doc_id}.original.{ext}"
        (storage_dir / name).write_bytes(data)


def load_pdf(session: Session, storage_dir: Path, doc_id: uuid.UUID) -> bytes | None:
    if _use_db():
        f = session.get(StoredFile, (doc_id, "pdf"))
        return f.content if f else None
    path = storage_dir / f"{doc_id}.pdf"
    return path.read_bytes() if path.exists() else None


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
    parsed = parse_document(data, convert_docx=get_settings().docx_convert)

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

    session.add(doc)
    session.flush()
    save_file(session, storage_dir, doc.id, "original", file_type, data)
    if parsed.pdf_bytes is not None:
        save_file(session, storage_dir, doc.id, "pdf", "pdf", parsed.pdf_bytes)
    audit.record(session, "document.uploaded", "document", doc.id, document_id=doc.id, data={
        "filename": doc.filename, "file_type": file_type, "sha256": digest, "size_bytes": len(data),
        "pages": doc.n_pages, "clauses": len(doc.clauses), "has_layout": doc.has_layout, "warnings": doc.warnings,
    })
    session.commit()
    return doc, True


def delete(session: Session, storage_dir: Path, doc: Document) -> None:
    # Database-stored files go with the row (ON DELETE CASCADE); disk files are removed here.
    for f in storage_dir.glob(f"{doc.id}.*"):
        f.unlink(missing_ok=True)
    audit.record(session, "document.deleted", "document", doc.id, document_id=doc.id,
                 data={"filename": doc.filename, "sha256": doc.sha256})
    session.delete(doc)
    session.commit()
