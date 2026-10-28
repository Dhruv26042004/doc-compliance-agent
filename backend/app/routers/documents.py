import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import documents
from app.analysis import analyze_document
from app.config import get_settings
from app.db import get_session
from app.llm import GeminiClient, LLMError
from app.models import Clause, Document
from app.parsing import ParseError
from app.policy import load_policy
from app.schemas import AnalysisOut, DocumentDetail, DocumentSummary

router = APIRouter(prefix="/documents", tags=["documents"])


def get_storage_dir() -> Path:
    return get_settings().storage_dir


def get_llm_client():
    try:
        return GeminiClient()
    except LLMError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


def _summary(doc: Document, n_clauses: int) -> DocumentSummary:
    return DocumentSummary.model_validate({**doc.__dict__, "n_clauses": n_clauses})


def _detail(doc: Document) -> DocumentDetail:
    return DocumentDetail.model_validate(
        {**doc.__dict__, "n_clauses": len(doc.clauses), "clauses": doc.clauses}
    )


def _get(session: Session, doc_id: uuid.UUID) -> Document:
    doc = session.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


@router.post("", status_code=status.HTTP_201_CREATED, response_model=DocumentDetail)
def upload_document(
    file: UploadFile,
    response: Response,
    session: Session = Depends(get_session),
    storage_dir: Path = Depends(get_storage_dir),
) -> DocumentDetail:
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"File exceeds {limit // 2**20} MB")
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "File is empty")
    try:
        doc, created = documents.ingest(session, storage_dir, file.filename or "", data)
    except ParseError as exc:
        code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE if "Unsupported" in str(exc) else status.HTTP_422_UNPROCESSABLE_CONTENT
        raise HTTPException(code, str(exc)) from exc
    if not created:
        response.status_code = status.HTTP_200_OK
    return _detail(doc)


@router.get("", response_model=list[DocumentSummary])
def list_documents(limit: int = 50, offset: int = 0, session: Session = Depends(get_session)) -> list[DocumentSummary]:
    n_clauses = select(func.count(Clause.id)).where(Clause.document_id == Document.id).scalar_subquery()
    rows = session.execute(
        select(Document, n_clauses).order_by(Document.created_at.desc()).limit(min(limit, 200)).offset(offset)
    ).all()
    return [_summary(doc, n) for doc, n in rows]


@router.get("/{doc_id}", response_model=DocumentDetail)
def get_document(doc_id: uuid.UUID, session: Session = Depends(get_session)) -> DocumentDetail:
    return _detail(_get(session, doc_id))


@router.get("/{doc_id}/file")
def get_document_file(
    doc_id: uuid.UUID,
    session: Session = Depends(get_session),
    storage_dir: Path = Depends(get_storage_dir),
) -> FileResponse:
    doc = _get(session, doc_id)
    path = documents.pdf_path(storage_dir, doc.id)
    if not doc.has_layout or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No PDF rendition for this document")
    return FileResponse(path, media_type="application/pdf", filename=f"{Path(doc.filename).stem}.pdf")


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    doc_id: uuid.UUID,
    session: Session = Depends(get_session),
    storage_dir: Path = Depends(get_storage_dir),
) -> None:
    documents.delete(session, storage_dir, _get(session, doc_id))


@router.post("/{doc_id}/analyze", response_model=AnalysisOut)
def analyze(
    doc_id: uuid.UUID,
    session: Session = Depends(get_session),
    client=Depends(get_llm_client),
) -> AnalysisOut:
    """Check every clause against the current policy. Slow on the free tier: about 30s per 20 clauses."""
    doc = _get(session, doc_id)
    try:
        return analyze_document(client, load_policy(1), doc)
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"LLM request failed: {exc}") from exc
