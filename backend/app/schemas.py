import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Rect(BaseModel):
    page: int
    bbox: list[float]  # [x0, y0, x1, y1] in PDF points, origin top-left


class ClauseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    idx: int
    char_start: int
    char_end: int
    text: str
    page_start: int | None
    page_end: int | None
    rects: list[Rect]


class PageOut(BaseModel):
    number: int
    width: float
    height: float


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    file_type: str
    size_bytes: int
    n_pages: int
    n_clauses: int
    has_layout: bool
    warnings: list[str]
    created_at: datetime


class DocumentDetail(DocumentSummary):
    text: str
    pages: list[PageOut]
    clauses: list[ClauseOut]


class DecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    clause_id: uuid.UUID | None
    clause_idx: int | None = None
    rule_id: str
    rule_title: str = ""
    severity: str = ""
    kind: str  # finding | rejected_finding | possible_miss | missing_required
    proposed_applies: bool
    verdict: str  # violation | flag | satisfies | violated | none
    route: str  # auto | review
    route_reason: str
    quote: str | None
    quote_start: int | None
    quote_end: int | None
    explanation: str
    confidence: float | None
    rects: list[Rect]
    status: str  # auto | pending | approved | overridden
    final_applies: bool | None
    reviewer: str | None
    review_reason: str | None
    reviewed_at: datetime | None


class AnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    created_at: datetime
    policy_id: str
    policy_version: int
    pipeline: str
    prompt_hash: str
    model_version: str
    auto_threshold: float
    llm_calls: int
    clauses_screened_out: int
    status: str  # needs_review | complete
    rule_status: dict[str, str]  # rule id -> violated | flagged | satisfied | clear | pending
    n_auto: int
    n_pending: int
    decisions: list[DecisionOut]


class QueueItem(DecisionOut):
    analysis_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    clause_text: str | None


class ReviewIn(BaseModel):
    action: str  # approve | override
    reviewer: str = "reviewer"
    reason: str | None = None
