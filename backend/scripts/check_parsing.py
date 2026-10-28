"""Measure parser quality on the original CUAD PDFs.

For a seeded sample of dev contracts, parse the PDF and check what fraction of the
lawyer-annotated CUAD spans can be found in our extracted text (ignoring case,
whitespace and punctuation). A low score means highlights on real documents would fail.

Needs data/raw/cuad_pdfs/CUAD_v1.zip (https://zenodo.org/records/4595826).
Usage: uv run python -m scripts.check_parsing [n_contracts]
"""

import json
import random
import re
import sys
import time
import zipfile
from pathlib import PurePosixPath

from app.config import get_settings
from app.parsing import ParseError, parse_pdf
from app.segmenter import split_text

SEED = 7


def squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def main(n: int = 40) -> None:
    data_dir = get_settings().data_dir
    cuad = {
        d["title"]: d["paragraphs"][0]
        for d in json.loads((data_dir / "raw/cuad/CUADv1.json").read_text(encoding="utf-8"))["data"]
    }
    splits = json.loads((data_dir / "processed/splits.json").read_text(encoding="utf-8"))
    docs = [json.loads(l) for l in (data_dir / "processed/documents.jsonl").open(encoding="utf-8")]
    dev_titles = {d["title"] for d in docs if d["contract_id"] in set(splits["dev"])}

    archive = zipfile.ZipFile(data_dir / "raw/cuad_pdfs/CUAD_v1.zip")
    pdfs = {
        PurePosixPath(name).stem.strip(): name
        for name in archive.namelist()
        if name.lower().endswith(".pdf")
    }
    matched = sorted(t for t in dev_titles if t in pdfs)
    print(f"{len(matched)}/{len(dev_titles)} dev contracts matched to a PDF by file name")
    sample = random.Random(SEED).sample(matched, min(n, len(matched)))

    found = total = pages = failures = clauses = 0
    worst = []
    t0 = time.perf_counter()
    for title in sample:
        try:
            parsed = parse_pdf(archive.read(pdfs[title]))
        except ParseError as exc:
            failures += 1
            print(f"  FAILED {title[:60]}: {exc}")
            continue
        pages += len(parsed.pages)
        clauses += len(split_text(parsed.text))
        hay = squash(parsed.text)
        spans = [a["text"] for qa in cuad[title]["qas"] for a in qa["answers"] if len(squash(a["text"])) >= 10]
        hit = sum(squash(s) in hay for s in spans)
        found += hit
        total += len(spans)
        if spans:
            worst.append((hit / len(spans), title))
    elapsed = time.perf_counter() - t0

    print(f"parsed {len(sample) - failures}/{len(sample)} PDFs, {pages} pages, {clauses} clauses "
          f"in {elapsed:.1f}s ({1000 * elapsed / max(pages, 1):.0f} ms/page)")
    print(f"CUAD spans recovered verbatim: {found}/{total} = {found / max(total, 1):.1%}")
    print("lowest recovery:")
    for score, title in sorted(worst)[:5]:
        print(f"  {score:6.1%}  {title[:70]}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 40)
