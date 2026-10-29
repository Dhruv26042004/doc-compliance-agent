"""Upload every PDF/DOCX in a folder as one batch, then wait for the analysis to finish.

Usage: uv run python -m scripts.batch_upload <folder> [--api http://localhost:8000] [--no-analyze]
"""

import argparse
import os
import time
from pathlib import Path

import httpx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--token", default=os.environ.get("ADMIN_TOKEN"), help="X-Admin-Token for a protected deployment")
    ap.add_argument("--no-analyze", action="store_true")
    args = ap.parse_args()

    paths = sorted(p for p in args.folder.iterdir() if p.suffix.lower() in (".pdf", ".docx"))
    if not paths:
        raise SystemExit(f"No PDF or DOCX files in {args.folder}")
    files = [("files", (p.name, p.read_bytes())) for p in paths]
    with httpx.Client(base_url=args.api, headers={"X-Admin-Token": args.token} if args.token else {}, timeout=300) as api:
        resp = api.post("/batches", params={"analyze": str(not args.no_analyze).lower()}, files=files)
        resp.raise_for_status()
        batch = resp.json()
        print(f"batch {batch['id']}: {len(paths)} files, {batch['counts']}")
        while batch["status"] != "done":
            time.sleep(5)
            batch = api.get(f"/batches/{batch['id']}").json()
            print(f"  {batch['status']}: {batch['counts']}", flush=True)
    for item in batch["items"]:
        print(f"  {item['status']:16s} {item['filename']}" + (f"  ({item['error']})" if item["error"] else ""))


if __name__ == "__main__":
    main()
