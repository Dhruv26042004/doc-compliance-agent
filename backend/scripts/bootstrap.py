"""Prepare everything a fresh clone needs, skipping steps that are already done.

  1. download CUAD (annotations, and the original PDFs for the demo)
  2. build the clause dataset and frozen splits
  3. train the tier-1 prefilter
  4. build the few-shot example pool (embeddings, ~6 minutes on CPU)

Usage: uv run python -m scripts.bootstrap
   or: docker compose run --rm api python -m scripts.bootstrap
"""

import subprocess
import sys
import time

from app.config import get_settings


def step(name: str, done: bool, *args: str) -> None:
    if done:
        print(f"[skip] {name}: already done")
        return
    print(f"[run]  {name} ...", flush=True)
    t0 = time.perf_counter()
    subprocess.run([sys.executable, "-m", *args], check=True)
    print(f"[done] {name} in {time.perf_counter() - t0:.0f}s", flush=True)


def main() -> None:
    d = get_settings().data_dir
    p = d / "processed"
    step("download CUAD", (d / "raw/cuad/CUADv1.json").exists() and (d / "raw/cuad_pdfs/CUAD_v1.zip").exists(),
         "scripts.download_cuad", "--pdfs")
    step("build dataset", (p / "segments.jsonl").exists(), "scripts.build_dataset")
    step("train prefilter", (p / "prefilter.joblib").exists(), "scripts.train_prefilter", "--target", "0.93")
    step("build example pool", (p / "examples.npz").exists(), "scripts.build_examples")
    print("Ready.")


if __name__ == "__main__":
    main()
