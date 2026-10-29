"""Retrieve labeled reference examples similar to the clauses being classified.

Positives are the exact spans lawyers highlighted in CUAD (so an example shows precisely
what a match looks like); negatives are "hard negatives", clauses the prefilter found
suspicious but that match no rule. Both come only from training contracts.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.config import get_settings

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
MAX_EXAMPLE_CHARS = 500


@lru_cache
def _embedder():
    from fastembed import TextEmbedding

    # Two threads and small batches keep peak memory low on an ordinary laptop.
    return TextEmbedding(EMBED_MODEL, threads=2, cache_dir=str(get_settings().model_cache_dir))


def embed(texts: list[str], batch_size: int = 32) -> np.ndarray:
    v = np.array(list(_embedder().embed(texts, batch_size=batch_size)), dtype=np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


@dataclass
class Example:
    text: str
    rule_ids: list[str]  # empty = matches no rule


def index_paths() -> tuple[Path, Path]:
    d = get_settings().data_dir / "processed"
    return d / "examples.jsonl", d / "examples.npz"


class ExampleIndex:
    def __init__(self, examples: list[Example], vectors: np.ndarray):
        self.examples = examples
        self.vectors = vectors
        self.is_positive = np.array([bool(e.rule_ids) for e in examples])

    @classmethod
    def load(cls) -> "ExampleIndex":
        rows_path, vec_path = index_paths()
        with open(rows_path, encoding="utf-8") as f:
            examples = [Example(**json.loads(line)) for line in f]
        return cls(examples, np.load(vec_path)["vectors"])

    def retrieve(self, texts: list[str], k_pos: int = 2, k_neg: int = 1, limit: int = 24) -> list[Example]:
        """Nearest positives and hard negatives for a batch, most similar first, deduplicated."""
        sims = embed([t[:MAX_EXAMPLE_CHARS] for t in texts]) @ self.vectors.T  # (batch, pool)
        best: dict[int, float] = {}
        for row in sims:
            for mask, k in ((self.is_positive, k_pos), (~self.is_positive, k_neg)):
                scores = np.where(mask, row, -np.inf)
                for i in np.argpartition(-scores, k)[:k]:
                    best[int(i)] = max(best.get(int(i), -1.0), float(row[i]))
        ranked = sorted(best, key=best.get, reverse=True)[:limit]
        return [self.examples[i] for i in ranked]


def render_examples(examples: list[Example]) -> str:
    lines = ["Reference examples labeled by lawyers (similar to the clauses below; for calibration only):", ""]
    for e in examples:
        label = ", ".join(e.rule_ids) if e.rule_ids else "matches no rule"
        text = e.text if len(e.text) <= MAX_EXAMPLE_CHARS else e.text[:MAX_EXAMPLE_CHARS] + " ..."
        lines.append(f"- [{label}] {text}")
    return "\n".join(lines)
