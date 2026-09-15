"""검색 (명세 6.3~6.5).

- 정규화 벡터의 내적 = 코사인 유사도.
- 필터를 먼저 적용한 집합에서 순위를 계산한다. 전역 Top-K 를 잘라내지 않는다.
- 동점은 record_id 로 안정 정렬한다.
"""
from __future__ import annotations

import numpy as np


class FlatIPIndex:
    """FAISS IndexFlatIP. 설치 실패 시 NumPy 참조 구현으로 대체한다."""

    def __init__(self, vectors: np.ndarray, backend: str = "auto"):
        self.vectors = np.ascontiguousarray(vectors, dtype="float32")
        self.backend = "numpy"
        self._index = None
        if backend in ("auto", "faiss"):
            try:
                import faiss
                idx = faiss.IndexFlatIP(self.vectors.shape[1])
                idx.add(self.vectors)
                self._index = idx
                self.backend = "faiss"
            except Exception:
                if backend == "faiss":
                    raise

    def scores(self, q: np.ndarray) -> np.ndarray:
        """전체 문서에 대한 점수. 필터는 호출자가 적용한다."""
        q = np.ascontiguousarray(q.reshape(1, -1), dtype="float32")
        if self._index is not None:
            import faiss  # noqa: F401
            s, _ = self._index.search(q, self.vectors.shape[0])
            out = np.empty(self.vectors.shape[0], dtype="float32")
            s2, i2 = s[0], _[0]
            out[i2] = s2
            return out
        return (self.vectors @ q[0]).astype("float32")

    def scores_numpy(self, q: np.ndarray) -> np.ndarray:
        """참조 구현. FAISS 결과 검증용 (명세 T-09)."""
        q = np.asarray(q, dtype="float32").reshape(-1)
        return (self.vectors @ q).astype("float32")


def rank(scores: np.ndarray, ids: list[str], mask: np.ndarray | None = None,
         top_k: int = 10) -> list[tuple[int, float]]:
    """필터 통과 집합에서 상위 top_k. 동점은 id 사전순으로 안정 정렬."""
    idx = np.arange(len(scores)) if mask is None else np.flatnonzero(mask)
    if idx.size == 0:
        return []
    order = sorted(idx, key=lambda i: (-float(scores[i]), ids[i]))
    return [(int(i), float(scores[i])) for i in order[:top_k]]


def above_threshold(scores: np.ndarray, mask: np.ndarray | None, tau: float | None) -> np.ndarray:
    """관련도 기준 통과 마스크. tau 가 None 이면 판단 보류(전부 False)."""
    base = np.ones(len(scores), dtype=bool) if mask is None else mask
    if tau is None:
        return np.zeros(len(scores), dtype=bool)
    return base & (scores >= tau)
