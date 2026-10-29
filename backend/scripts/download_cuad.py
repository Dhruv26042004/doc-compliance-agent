"""Download CUAD v1 (CC BY 4.0, The Atticus Project) into data/raw/cuad/.

Usage: uv run python -m scripts.download_cuad [--pdfs]
"""

import io
import shutil
import sys
import urllib.request
import zipfile

from app.config import get_settings

URL = "https://github.com/TheAtticusProject/cuad/raw/main/data.zip"
EXPECTED = {"CUADv1.json", "test.json", "train_separate_questions.json"}
# The original contract PDFs (~106 MB), used by the demo seed. Read in place from the zip.
PDF_URL = "https://zenodo.org/records/4595826/files/CUAD_v1.zip?download=1"


def main() -> None:
    out = get_settings().data_dir / "raw" / "cuad"
    out.mkdir(parents=True, exist_ok=True)
    if all((out / name).exists() for name in EXPECTED):
        print(f"CUAD already present in {out}")
        return

    print(f"Downloading {URL} ...")
    with urllib.request.urlopen(URL) as resp:
        archive = zipfile.ZipFile(io.BytesIO(resp.read()))
    for name in EXPECTED:  # extract only the known files, never arbitrary archive paths
        (out / name).write_bytes(archive.read(name))
    print(f"Wrote {sorted(EXPECTED)} to {out}")


def download_pdfs() -> None:
    out = get_settings().data_dir / "raw" / "cuad_pdfs" / "CUAD_v1.zip"
    if out.exists():
        print(f"CUAD PDFs already present at {out}")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_suffix(".part")
    print(f"Downloading CUAD PDFs (~106 MB) from {PDF_URL} ...")
    with urllib.request.urlopen(PDF_URL) as resp, open(partial, "wb") as f:
        shutil.copyfileobj(resp, f, length=1 << 20)
    partial.rename(out)  # only a complete download gets the final name
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
    if "--pdfs" in sys.argv:
        download_pdfs()
