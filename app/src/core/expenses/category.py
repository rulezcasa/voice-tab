"""Category = nearest fixed category by bge-m3 similarity."""
from functools import cache

import numpy as np

from src.core.expenses.categories import MODEL_CATEGORIES
from src.model.embeddings import embed

MIN_SCORE = 0.38
_CATS = [c for c in MODEL_CATEGORIES if c != "other"]


@cache
def _prototypes() -> np.ndarray:
    vecs = np.array(embed([f"{c}: {MODEL_CATEGORIES[c]}" for c in _CATS]), dtype=np.float32)
    return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)


def classify(text: str) -> tuple[str, float, list[tuple[str, float]]]:
    """'Costco run' -> ('groceries', 0.49, [top 3 (category, score)])."""
    v = np.array(embed([text], is_query=True)[0], dtype=np.float32)
    sims = _prototypes() @ (v / np.linalg.norm(v))
    order = np.argsort(-sims)
    top = [(_CATS[i], round(float(sims[i]), 3)) for i in order[:3]]
    best, score = top[0]
    return (best if score >= MIN_SCORE else "other"), score, top
