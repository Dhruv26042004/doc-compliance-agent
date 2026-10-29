"""Tier 1: a cheap TF-IDF + logistic regression screen in front of the LLM.

One binary classifier per rule. A clause goes to the LLM only if at least one rule
scores above that rule's screening threshold; everything else is decided "matches
nothing" for free. Thresholds are set for high recall, because a clause screened out
here can never be recovered later.
"""

from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold

from app.config import get_settings


def default_path() -> Path:
    return get_settings().data_dir / "processed" / "prefilter.joblib"


def _vectorizer() -> TfidfVectorizer:
    return TfidfVectorizer(
        ngram_range=(1, 2), min_df=2, max_features=300_000, sublinear_tf=True, strip_accents="unicode"
    )


def _model() -> LogisticRegression:
    return LogisticRegression(C=4.0, class_weight="balanced", max_iter=2000, solver="liblinear")


def _threshold_for_recall(scores: np.ndarray, target: float) -> float:
    """Highest threshold that still keeps `target` of the positive scores."""
    s = np.sort(scores)
    k = int(np.floor((1 - target) * len(s)))
    return float(s[k]) if len(s) else 0.5


@dataclass
class Prefilter:
    rule_ids: list[str]
    target_recall: float = 0.98
    vectorizer: TfidfVectorizer = field(default_factory=_vectorizer)
    models: dict[str, LogisticRegression] = field(default_factory=dict)
    screen_threshold: dict[str, float] = field(default_factory=dict)  # high recall, for routing
    classify_threshold: dict[str, float] = field(default_factory=dict)  # best F1, standalone use
    oof_scores: dict[str, np.ndarray] = field(default_factory=dict, repr=False)  # for re-thresholding
    oof_labels: dict[str, np.ndarray] = field(default_factory=dict, repr=False)

    def fit(self, texts: list[str], labels: list[set[str]], groups: list[str], folds: int = 5) -> "Prefilter":
        y = {r: np.array([r in l for l in labels]) for r in self.rule_ids}
        # Thresholds come from out-of-fold scores, grouped by contract, so they are not
        # set on clauses the models were trained on.
        oof = {r: np.zeros(len(texts)) for r in self.rule_ids}
        for train, held in GroupKFold(n_splits=folds).split(texts, groups=groups):
            vec = _vectorizer().fit([texts[i] for i in train])
            x_train, x_held = vec.transform([texts[i] for i in train]), vec.transform([texts[i] for i in held])
            for r in self.rule_ids:
                oof[r][held] = _model().fit(x_train, y[r][train]).predict_proba(x_held)[:, 1]
        self.oof_scores, self.oof_labels = oof, y
        self.set_screen_recall(self.target_recall)
        for r in self.rule_ids:
            self.classify_threshold[r] = _best_f1_threshold(oof[r], y[r])

        x = self.vectorizer.fit_transform(texts)
        self.models = {r: _model().fit(x, y[r]) for r in self.rule_ids}
        return self

    def set_screen_recall(self, target: float) -> None:
        """Per-rule screening thresholds that keep `target` of each rule's out-of-fold positives."""
        self.target_recall = target
        for r in self.rule_ids:
            self.screen_threshold[r] = _threshold_for_recall(self.oof_scores[r][self.oof_labels[r]], target)

    def oof_tradeoff(self) -> tuple[float, float]:
        """(share of clauses skipped, share of labeled clauses kept) on out-of-fold scores."""
        sent = np.zeros(len(next(iter(self.oof_scores.values()))), dtype=bool)
        for r in self.rule_ids:
            sent |= self.oof_scores[r] >= self.screen_threshold[r]
        labeled = np.any([self.oof_labels[r] for r in self.rule_ids], axis=0)
        return 1 - sent.mean(), (sent & labeled).sum() / labeled.sum()

    def scores(self, texts: list[str]) -> dict[str, np.ndarray]:
        x = self.vectorizer.transform(texts)
        return {r: m.predict_proba(x)[:, 1] for r, m in self.models.items()}

    def screen(self, texts: list[str]) -> list[set[str]]:
        """Candidate rules per clause; an empty set means skip the LLM."""
        s = self.scores(texts)
        return [{r for r in self.rule_ids if s[r][i] >= self.screen_threshold[r]} for i in range(len(texts))]

    def classify(self, texts: list[str]) -> list[set[str]]:
        """Use the small model on its own (no LLM), at its best-F1 thresholds."""
        s = self.scores(texts)
        return [{r for r in self.rule_ids if s[r][i] >= self.classify_threshold[r]} for i in range(len(texts))]

    def save(self, path: Path | None = None) -> None:
        joblib.dump(self, path or default_path())

    @staticmethod
    def load(path: Path | None = None) -> "Prefilter":
        return joblib.load(path or default_path())


def _best_f1_threshold(scores: np.ndarray, y: np.ndarray) -> float:
    best, best_t = -1.0, 0.5
    for t in np.unique(np.round(scores, 3)):
        p = scores >= t
        tp = int((p & y).sum())
        if tp == 0:
            continue
        f1 = 2 * tp / (p.sum() + y.sum())
        if f1 > best:
            best, best_t = f1, float(t)
    return best_t
