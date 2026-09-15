"""하이브리드 결합 — Reciprocal Rank Fusion (개정안 01 FR-01a, 3절).

    rrf(d) = Σ_m 1 / (k + r_m(d))          k = 60 (설정 노출)

- 한 방식에만 등장한 문서는 그 방식 항만 더한다.
- 필터는 두 방식 **모두**에 먼저 적용한다 (원본 6.3-5). 이 모듈은 이미 필터된 순위만 받는다.
- 동점은 record_id 로 안정 정렬한다 (원본 6.3-6).
- RRF 값은 화면에 표시하지 않는다. 결합 **순위**만 쓴다 (개정안 3절).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class FusedItem:
    index: int                       # projects 행 위치
    record_id: str
    fusion_rank: int                 # 1부터
    rrf_score: float                 # 감사용. 표시 금지
    ranks: dict[str, int | None] = field(default_factory=dict)   # 방식별 순위 (없으면 None)


def method_ranks(scores: np.ndarray, ids: list[str], mask: np.ndarray | None,
                 depth: int) -> list[int]:
    """한 방식의 상위 depth 개 행 위치. 필터 통과 집합에서만, 동점은 id 사전순."""
    idx = np.arange(len(scores)) if mask is None else np.flatnonzero(mask)
    if idx.size == 0:
        return []
    order = sorted(idx, key=lambda i: (-float(scores[i]), ids[i]))
    return [int(i) for i in order[:depth]]


def rrf_fuse(ranked: dict[str, list[int]], ids: list[str], k: int = 60,
             top_n: int | None = None) -> list[FusedItem]:
    """방식별 순위 목록 -> RRF 결합 순위.

    ranked: {"sem": [행위치 순서대로], "lex": [...]}  — 각 리스트는 1위부터.
    """
    if k <= 0:
        raise ValueError("rrf_k 는 양수여야 한다")
    methods = list(ranked)
    pos: dict[int, dict[str, int]] = {}
    for m in methods:
        for r, i in enumerate(ranked[m], 1):
            pos.setdefault(i, {})[m] = r

    items = []
    for i, rs in pos.items():
        score = sum(1.0 / (k + r) for r in rs.values())
        items.append(FusedItem(index=i, record_id=ids[i], fusion_rank=0, rrf_score=score,
                               ranks={m: rs.get(m) for m in methods}))
    items.sort(key=lambda it: (-it.rrf_score, it.record_id))
    for r, it in enumerate(items, 1):
        it.fusion_rank = r
    return items[:top_n] if top_n else items


def build_candidates(sem_scores: np.ndarray, lex_scores: np.ndarray, ids: list[str],
                     mask: np.ndarray | None = None, k: int = 60,
                     candidate_pool: int = 100) -> list[FusedItem]:
    """개정안 3절 후보 집합: 각 방식 상위 N_c/2 의 합집합을 RRF 로 결합한다."""
    depth = max(1, candidate_pool // 2)
    ranked = {"sem": method_ranks(sem_scores, ids, mask, depth),
              "lex": method_ranks(lex_scores, ids, mask, depth)}
    return rrf_fuse(ranked, ids, k=k)


def semantic_only(sem_scores: np.ndarray, ids: list[str], mask: np.ndarray | None = None,
                  candidate_pool: int = 100) -> list[FusedItem]:
    """`hybrid=false` 경로. S2 를 통과만 시키고 의미검색 순위를 그대로 쓴다 (개정안 2절)."""
    order = method_ranks(sem_scores, ids, mask, candidate_pool)
    return [FusedItem(index=i, record_id=ids[i], fusion_rank=r, rrf_score=float("nan"),
                      ranks={"sem": r, "lex": None}) for r, i in enumerate(order, 1)]
