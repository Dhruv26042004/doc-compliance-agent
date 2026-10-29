import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import documents
from app.analysis import analyze_document, default_config
from app.config import get_settings
from app.db import get_session
from app.llm import GeminiClient, LLMError
from app.models import Analysis, Clause, Document
from app.parsing import ParseError
from app.pipeline import PipelineConfig
from app.policy import load_policy
from app.routers.reviews import analysis_out
from app.schemas import AnalysisOut, DocumentDetail, DocumentSummary
from app.security import require_admin

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


@router.post("", status_code=status.HTTP_201_CREATED, response_model=DocumentDetail, dependencies=[Depends(require_admin)])
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
) -> Response:
    doc = _get(session, doc_id)
    pdf = documents.load_pdf(session, storage_dir, doc.id) if doc.has_layout else None
    if pdf is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No PDF rendition for this document")
    name = f"{Path(doc.filename).stem}.pdf".encode("ascii", "ignore").decode() or "document.pdf"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'})


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
def delete_document(
    doc_id: uuid.UUID,
    session: Session = Depends(get_session),
    storage_dir: Path = Depends(get_storage_dir),
) -> None:
    documents.delete(session, storage_dir, _get(session, doc_id))


@router.post("/{doc_id}/analyze", response_model=AnalysisOut, dependencies=[Depends(require_admin)])
def analyze(
    doc_id: uuid.UUID,
    session: Session = Depends(get_session),
    client=Depends(get_llm_client),
    cfg: PipelineConfig = Depends(default_config),
) -> AnalysisOut:
    """Check every clause against the current policy, route each decision, and store the result.

    Slow on the free tier: about a minute for a typical contract.
    """
    doc = _get(session, doc_id)
    try:
        analysis = analyze_document(session, client, load_policy(), doc, cfg)
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"LLM request failed: {exc}") from exc
    return analysis_out(session, analysis)


@router.get("/{doc_id}/analysis", response_model=AnalysisOut)
def latest_analysis(doc_id: uuid.UUID, session: Session = Depends(get_session)) -> AnalysisOut:
    _get(session, doc_id)
    analysis = session.scalar(
        select(Analysis).where(Analysis.document_id == doc_id).order_by(Analysis.created_at.desc()).limit(1)
    )
    if analysis is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This document has not been analyzed yet")
    return analysis_out(session, analysis)
