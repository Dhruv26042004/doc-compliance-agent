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


class FindingOut(BaseModel):
    clause_id: uuid.UUID
    clause_idx: int
    rule_id: str
    rule_title: str
    rule_kind: str  # required | prohibited | review
    severity: str
    verdict: str  # satisfies | violation | flag
    quote: str
    quote_found: bool  # False: the model's quote is not in the clause (possible hallucination)
    quote_start: int | None  # offsets into the document text
    quote_end: int | None
    explanation: str
    confidence: float
    rects: list[Rect]


class RejectedOut(BaseModel):
    """A finding the verifier removed; kept for review and audit rather than discarded."""

    clause_id: uuid.UUID
    clause_idx: int
    rule_id: str
    quote: str
    stage: str  # quote_not_found | llm
    reason: str


class AnalysisOut(BaseModel):
    document_id: uuid.UUID
    policy_id: str
    policy_version: int
    prompt_version: str
    prompt_hash: str
    pipeline: str  # e.g. "v1+pf+ver"
    model_version: str
    llm_calls: int
    clauses_screened_out: int
    required_rules: dict[str, str]  # rule id -> satisfied | violated
    n_violations: int
    n_flags: int
    findings: list[FindingOut]
    rejected: list[RejectedOut]
