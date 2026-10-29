"""Turn an uploaded PDF or DOCX into plain text plus a line-level layout map.

Every line keeps (page, bbox, char_start, char_end) into the extracted text, so any
character range -- a clause, or a quoted span from the model -- can be mapped back to
rectangles on the page for highlighting.
"""

import io
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import docx
import pymupdf

MARGIN = 0.08  # top/bottom fraction of a page where headers and footers live
_PAGE_NUMBER = re.compile(r"^\W*(page\s*)?\d+(\s*(of|/)\s*\d+)?\W*$", re.I)
_SENTENCE_END = tuple(".:;!?)\"'")
# A new numbered item: "2.", "2.3", "(a)", "Section 4", "ARTICLE V".
_NUMBERED = re.compile(r"^(\d+(\.\d+)*\.?|\([a-zA-Z0-9]{1,4}\)|section\s+\d|article\s+[\dIVXL]+)\s", re.I)


class ParseError(ValueError):
    pass


@dataclass
class Line:
    page: int  # 1-based
    bbox: tuple[float, float, float, float]
    start: int
    end: int


@dataclass
class Page:
    number: int
    width: float
    height: float


@dataclass
class ParsedDocument:
    text: str
    pages: list[Page]
    lines: list[Line]
    has_layout: bool
    pdf_bytes: bytes | None  # the PDF to display; None when there is no layout
    warnings: list[str] = field(default_factory=list)

    def rects(self, start: int, end: int) -> list[dict]:
        """Rectangles covering text[start:end], one per overlapping line."""
        return [
            {"page": ln.page, "bbox": [round(v, 1) for v in ln.bbox]}
            for ln in self.lines
            if ln.start < end and start < ln.end
        ]


def detect_type(data: bytes) -> str:
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:4] == b"PK\x03\x04":
        try:
            if "word/document.xml" in zipfile.ZipFile(io.BytesIO(data)).namelist():
                return "docx"
        except zipfile.BadZipFile:
            pass
    raise ParseError("Unsupported file: only PDF and DOCX are accepted.")


def parse_document(data: bytes, convert_docx: bool = True) -> ParsedDocument:
    kind = detect_type(data)
    if kind == "pdf":
        return parse_pdf(data)
    pdf = convert_docx_to_pdf(data) if convert_docx else None
    if pdf is not None:
        return parse_pdf(pdf)
    parsed = parse_docx_text(data)
    parsed.warnings.append(
        "This DOCX was read without page layout (LibreOffice is unavailable or disabled); "
        "highlights will be shown on text only."
    )
    return parsed


# ---------------------------------------------------------------- PDF


def _norm(text: str) -> str:
    return re.sub(r"\d+", "#", text.lower()).strip()


def _page_lines(page) -> list[list[tuple[str, tuple, float]]]:
    """Text blocks on a page, each a list of (line_text, bbox, font_size), in reading order."""
    blocks = []
    for b in page.get_text("dict", sort=True)["blocks"]:
        if b["type"] != 0:
            continue
        lines = []
        for ln in b["lines"]:
            text = "".join(s["text"] for s in ln["spans"]).strip()
            if text:
                lines.append((text, tuple(ln["bbox"]), max(sp["size"] for sp in ln["spans"])))
        if lines:
            blocks.append(lines)
    return blocks


def _repeated_margin_lines(pages_blocks, heights) -> set[str]:
    """Normalized lines that recur in the page margins: running headers and footers."""
    if len(pages_blocks) < 3:
        return set()
    counts: Counter[str] = Counter()
    for blocks, h in zip(pages_blocks, heights):
        seen = {
            _norm(text)
            for lines in blocks
            for text, bbox, _ in lines
            if bbox[1] < h * MARGIN or bbox[3] > h * (1 - MARGIN)
        }
        counts.update(seen)
    threshold = max(3, len(pages_blocks) // 2)
    return {k for k, n in counts.items() if n >= threshold}


def parse_pdf(data: bytes) -> ParsedDocument:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ParseError("The PDF could not be opened; it may be corrupt.") from exc
    if doc.needs_pass:
        raise ParseError("The PDF is password-protected.")

    pages = [Page(i + 1, p.rect.width, p.rect.height) for i, p in enumerate(doc)]
    pages_blocks = [_page_lines(p) for p in doc]
    repeated = _repeated_margin_lines(pages_blocks, [p.height for p in pages])

    parts: list[str] = []
    lines: list[Line] = []
    pos = 0
    warnings = []

    def emit(s: str) -> int:
        nonlocal pos
        parts.append(s)
        start = pos
        pos += len(s)
        return start

    for page, blocks in zip(pages, pages_blocks):
        if not blocks:
            warnings.append(f"Page {page.number} has no text layer (scanned image?); it was skipped.")
        first_block_on_page = True
        for block in blocks:
            kept = [
                (t, bb, size) for t, bb, size in block
                if not (
                    (bb[1] < page.height * MARGIN or bb[3] > page.height * (1 - MARGIN))
                    and (_norm(t) in repeated or _PAGE_NUMBER.match(t))
                )
            ]
            if not kept:
                continue
            if parts:
                prev = "".join(parts[-1:]).rstrip()
                # A paragraph broken by a page boundary continues in lower case.
                continues = first_block_on_page and kept[0][0][:1].islower() and not prev.endswith(_SENTENCE_END)
                emit(" " if continues else "\n\n")
            first_block_on_page = False
            for i, (t, bb, size) in enumerate(kept):
                if i > 0:
                    prev_text, _, prev_size = kept[i - 1]
                    # PyMuPDF can group a heading, or several numbered sections, into one
                    # block; split those into paragraphs so each becomes its own clause.
                    if abs(size - prev_size) >= 1 or (prev_text.endswith(_SENTENCE_END) and _NUMBERED.match(t)):
                        emit("\n\n")
                    # Keep "non-\ncompete" as "non-compete"; otherwise reflow with a space.
                    elif not (prev_text.endswith("-") and t[:1].isalpha()):
                        emit(" ")
                start = emit(t)
                lines.append(Line(page.number, bb, start, start + len(t)))

    text = "".join(parts)
    if len(text.strip()) < 50:
        raise ParseError("No extractable text: the PDF looks scanned, and OCR is not supported yet.")
    return ParsedDocument(text, pages, lines, has_layout=True, pdf_bytes=data, warnings=warnings)


# ---------------------------------------------------------------- DOCX


def convert_docx_to_pdf(data: bytes, timeout: int = 90) -> bytes | None:
    """Convert with headless LibreOffice. Returns None if LibreOffice is not installed."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "input.docx"
        src.write_bytes(data)
        profile = Path(tmp, "profile").as_uri()  # isolated profile: safe for concurrent runs
        try:
            subprocess.run(
                [soffice, f"-env:UserInstallation={profile}", "--headless",
                 "--convert-to", "pdf", "--outdir", tmp, str(src)],
                check=True, capture_output=True, timeout=timeout,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise ParseError("The DOCX could not be converted to PDF.") from exc
        out = Path(tmp) / "input.pdf"
        if not out.exists():
            raise ParseError("The DOCX could not be converted to PDF.")
        return out.read_bytes()


def parse_docx_text(data: bytes) -> ParsedDocument:
    try:
        d = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise ParseError("The DOCX could not be opened; it may be corrupt.") from exc
    paragraphs = [p.text.strip() for p in d.paragraphs]
    for table in d.tables:
        for row in table.rows:
            paragraphs.extend(c.text.strip() for c in row.cells)
    text = "\n\n".join(p for p in paragraphs if p)
    if len(text.strip()) < 50:
        raise ParseError("The DOCX contains no text.")
    return ParsedDocument(text, pages=[], lines=[], has_layout=False, pdf_bytes=None)
