import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from app import audit, documents
from app.analysis import analyze_document, default_config
from app.config import get_settings
from app.db import SessionLocal, get_session
from app.llm import LLMError
from app.models import Batch, Document
from app.parsing import ParseError
from app.pipeline import PipelineConfig
from app.policy import load_policy
from app.routers.documents import get_llm_client, get_storage_dir

router = APIRouter(prefix="/batches", tags=["batches"])
MAX_FILES = 50


def _out(batch: Batch) -> dict:
    counts = {}
    for item in batch.items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {"id": str(batch.id), "created_at": batch.created_at.isoformat() if batch.created_at else None,
            "status": batch.status, "analyze": batch.analyze, "counts": counts, "items": batch.items}


def run_batch(batch_id: uuid.UUID, client, cfg: PipelineConfig) -> None:
    """Analyze each uploaded document in turn. Runs after the response, in its own session."""
    with SessionLocal() as session:
        batch = session.get(Batch, batch_id)
        batch.status = "running"
        session.commit()
        items = [dict(i) for i in batch.items]
        for item in items:
            if item["status"] != "uploaded":
                continue
            try:
                doc = session.get(Document, uuid.UUID(item["document_id"]))
                analysis = analyze_document(session, client, load_policy(), doc, cfg)
                item.update(status="analyzed", analysis_id=str(analysis.id))
            except LLMError as exc:
                session.rollback()
                item.update(status="analysis_failed", error=str(exc))
            batch.items = [dict(i) for i in items]  # reassign so the JSON column is saved
            session.commit()
        batch.status = "done"
        session.commit()


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_batch(
    request: Request,
    files: list[UploadFile],
    background: BackgroundTasks,
    analyze: bool = True,
    session: Session = Depends(get_session),
    storage_dir: Path = Depends(get_storage_dir),
    cfg: PipelineConfig = Depends(default_config),
) -> dict:
    """Upload up to 50 PDF/DOCX files. Each is parsed now; with analyze=true, all are then
    checked against the policy in the background. Poll GET /batches/{id} for progress."""
    if not files or len(files) > MAX_FILES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Send between 1 and {MAX_FILES} files.")
    # Resolve the LLM client only when analysis is requested (honoring test overrides), so
    # upload-only batches work without an API key, and a missing key fails before uploading.
    client = request.app.dependency_overrides.get(get_llm_client, get_llm_client)() if analyze else None
    limit = get_settings().max_upload_mb * 1024 * 1024
    items = []
    for f in files:
        item = {"filename": f.filename, "document_id": None, "analysis_id": None, "status": "uploaded", "error": None}
        data = f.file.read(limit + 1)
        try:
            if len(data) > limit:
                raise ParseError(f"File exceeds {limit // 2**20} MB")
            doc, _ = documents.ingest(session, storage_dir, f.filename or "", data)
            item["document_id"] = str(doc.id)
        except ParseError as exc:
            session.rollback()
            item.update(status="failed", error=str(exc))
        items.append(item)

    batch = Batch(status="queued" if analyze else "done", analyze=analyze, items=items)
    session.add(batch)
    session.flush()
    audit.record(session, "batch.created", "batch", batch.id, data={
        "files": len(items), "parsed": sum(i["status"] == "uploaded" for i in items), "analyze": analyze,
    })
    session.commit()
    if analyze:
        background.add_task(run_batch, batch.id, client, cfg)
    return _out(batch)


@router.get("/{batch_id}")
def get_batch(batch_id: uuid.UUID, session: Session = Depends(get_session)) -> dict:
    batch = session.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Batch not found")
    return _out(batch)
