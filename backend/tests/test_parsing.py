import io
import zipfile

import docx
import pymupdf
import pytest

from app.parsing import ParseError, detect_type, parse_docx_text, parse_pdf


def make_pdf(pages: list[list[tuple[float, str]]], header: str | None = None) -> bytes:
    """Each page is a list of (y, text) lines; a blank gap between lines makes a new block."""
    doc = pymupdf.open()
    for n, lines in enumerate(pages, start=1):
        page = doc.new_page()
        if header:
            page.insert_text((72, 30), header)
            page.insert_text((280, 820), f"Page {n} of {len(pages)}")
        for y, text in lines:
            page.insert_text((72, y), text)
    return doc.tobytes()


GOVERNING = "12. Governing Law. This Agreement is governed by the laws of Delaware."
LIABILITY = "13. Limitation of Liability. Neither party shall be liable for indirect damages."


def test_line_offsets_index_extracted_text():
    parsed = parse_pdf(make_pdf([[(100, GOVERNING), (140, LIABILITY)]]))
    assert parsed.text == f"{GOVERNING}\n\n{LIABILITY}"
    for ln in parsed.lines:
        assert parsed.text[ln.start : ln.end].strip()
    assert parsed.has_layout and parsed.pdf_bytes


def test_rects_locate_a_span_on_the_right_page():
    parsed = parse_pdf(make_pdf([[(100, GOVERNING)], [(100, LIABILITY)]]))
    start = parsed.text.index("indirect damages")
    rects = parsed.rects(start, start + len("indirect damages"))
    assert [r["page"] for r in rects] == [2]
    x0, y0, x1, y1 = rects[0]["bbox"]
    assert x0 < x1 and y0 < y1 and 80 < y1 < 120


def test_running_headers_and_page_numbers_are_removed():
    parsed = parse_pdf(make_pdf([[(100, GOVERNING)]] * 3, header="ACME CORP - CONFIDENTIAL"))
    assert "CONFIDENTIAL" not in parsed.text
    assert "Page" not in parsed.text
    assert parsed.text.count("Governing Law") == 3


def test_paragraph_broken_across_pages_is_rejoined():
    pdf = make_pdf([
        [(100, GOVERNING), (780, "Either party may terminate this Agreement for any reason upon")],
        [(100, "ninety days written notice to the other party."), (140, LIABILITY)],
    ])
    parsed = parse_pdf(pdf)
    assert "for any reason upon ninety days written notice" in parsed.text
    start = parsed.text.index("upon ninety")
    assert {r["page"] for r in parsed.rects(start, start + len("upon ninety"))} == {1, 2}


def test_lines_of_one_paragraph_are_reflowed():
    parsed = parse_pdf(make_pdf([[(100, "This Agreement shall be governed by the"), (114, "laws of the State of New York.")]]))
    assert parsed.text == "This Agreement shall be governed by the laws of the State of New York."


def test_heading_and_numbered_items_in_one_block_are_split():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "MUTUAL NON-DISCLOSURE AGREEMENT", fontsize=14)
    page.insert_text((72, 116), "1. Term. This Agreement continues for two years.", fontsize=11)
    page.insert_text((72, 129), "2. Governing Law. California law applies to this Agreement.", fontsize=11)
    page.insert_text((72, 142), "3. Payment. Fees are due within thirty days of the invoice", fontsize=11)
    page.insert_text((72, 155), "4.2 of the Statement of Work, as amended.", fontsize=11)
    parsed = parse_pdf(doc.tobytes())
    assert parsed.text.split("\n\n") == [
        "MUTUAL NON-DISCLOSURE AGREEMENT",
        "1. Term. This Agreement continues for two years.",
        "2. Governing Law. California law applies to this Agreement.",
        # "4.2" follows a line without a full stop, so it is a cross-reference, not a new item.
        "3. Payment. Fees are due within thirty days of the invoice 4.2 of the Statement of Work, as amended.",
    ]


def test_scanned_pdf_without_text_is_rejected():
    doc = pymupdf.open()
    doc.new_page()
    with pytest.raises(ParseError, match="scanned"):
        parse_pdf(doc.tobytes())


def test_docx_fallback_reads_paragraphs_and_tables():
    d = docx.Document()
    d.add_paragraph(GOVERNING)
    d.add_paragraph("")
    table = d.add_table(rows=1, cols=1)
    table.cell(0, 0).text = LIABILITY
    buf = io.BytesIO()
    d.save(buf)
    parsed = parse_docx_text(buf.getvalue())
    assert parsed.text == f"{GOVERNING}\n\n{LIABILITY}"
    assert not parsed.has_layout and parsed.rects(0, 10) == []


def test_detect_type():
    assert detect_type(make_pdf([[(100, GOVERNING)]])) == "pdf"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "not a docx")
    for bad in (b"plain text file", buf.getvalue()):
        with pytest.raises(ParseError, match="Unsupported"):
            detect_type(bad)
