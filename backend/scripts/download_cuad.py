"""Download CUAD v1 (CC BY 4.0, The Atticus Project) into data/raw/cuad/.

Usage: uv run python -m scripts.download_cuad
"""

import io
import urllib.request
import zipfile

from app.config import get_settings

URL = "https://github.com/TheAtticusProject/cuad/raw/main/data.zip"
EXPECTED = {"CUADv1.json", "test.json", "train_separate_questions.json"}


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


if __name__ == "__main__":
    main()
