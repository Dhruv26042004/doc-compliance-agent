"""Split contract text into clause-sized segments with exact character offsets.

Offsets always index into the original text, so text[start:end] == segment text.
That is what lets us map labels onto segments and, later, highlight them in the UI.
"""

import re
from dataclasses import dataclass

MIN_CHARS = 20  # shorter fragments are page numbers, stray headers, signature lines
MAX_CHARS = 3000  # longer paragraphs get split at sentence boundaries
TARGET_CHARS = 1500

_PARAGRAPH = re.compile(r"\S(?:.*?\S)?(?=\n\s*\n|\s*$)", re.S)
_SENTENCE_END = re.compile(r"(?<=[.;:])\s+(?=[A-Z(\"\d])")


@dataclass(frozen=True)
class Segment:
    start: int
    end: int


def _split_long(text: str, start: int, end: int) -> list[Segment]:
    cuts = [m.end() for m in _SENTENCE_END.finditer(text, start, end)]
    pieces, piece_start = [], start
    for i, cut in enumerate(cuts):
        next_cut = cuts[i + 1] if i + 1 < len(cuts) else end
        if next_cut - piece_start > TARGET_CHARS and cut > piece_start:
            pieces.append((piece_start, cut))
            piece_start = cut
    pieces.append((piece_start, end))

    # A piece with no usable sentence boundary is still too long: cut at whitespace.
    out: list[Segment] = []
    for s, e in pieces:
        while e - s > MAX_CHARS:
            cut = text.rfind(" ", s, s + TARGET_CHARS)
            cut = cut if cut > s else s + TARGET_CHARS
            out.append(Segment(s, cut))
            s = cut
            while s < e and text[s].isspace():
                s += 1
        out.append(Segment(s, e))
    return [_trim(text, seg) for seg in out]


def _trim(text: str, seg: Segment) -> Segment:
    s, e = seg.start, seg.end
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return Segment(s, e)


def split_text(text: str) -> list[Segment]:
    segments: list[Segment] = []
    for m in _PARAGRAPH.finditer(text):
        s, e = m.start(), m.end()
        parts = _split_long(text, s, e) if e - s > MAX_CHARS else [Segment(s, e)]
        segments.extend(p for p in parts if p.end - p.start >= MIN_CHARS)
    return segments
