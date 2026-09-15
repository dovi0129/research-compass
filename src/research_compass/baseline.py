"""비교용 어휘 기반 검색 — 문자 n-gram TF-IDF (명세 3.2)."""
from __future__ import annotations

import numpy as np


class CharTfidfBaseline:
    def __init__(self, texts: list[str], ngram_min: int = 2, ngram_max: int = 5):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.vec = TfidfVectorizer(analyzer="char_wb",
                                   ngram_range=(ngram_min, ngram_max),
                                   sublinear_tf=True, min_df=2)
        self.matrix = self.vec.fit_transform(texts)

    def scores(self, query: str) -> np.ndarray:
        from sklearn.preprocessing import normalize
        q = normalize(self.vec.transform([query]))
        m = normalize(self.matrix)
        return np.asarray((m @ q.T).todense()).ravel().astype("float32")
