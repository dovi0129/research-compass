"""테스트 공용 가짜 검색 엔진. 실모델 없이 파이프라인·작업공간 경로를 검증한다.

품질 수치는 여기서 만들지 않는다 — 실측은 실모델 실행으로만 기록한다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research_compass import search as svc

TITLES = ["강화학습 기반 제조공정 에너지 최적화",
          "산업 전력 데이터 이상탐지",
          "조선후기 향촌사회 신분 변동",
          "짧은제목",
          "고체전해질 계면 안정화 연구",
          "제조공정 에너지 절감 알고리즘 개발"]
YEARS = [2023, 2024, 2023, 2025, 2024, 2025]
SEM = [0.90, 0.70, 0.20, 0.65, 0.30, 0.85]
LEX = [0.10, 0.80, 0.05, 0.70, 0.02, 0.20]
SNAPSHOT = "3049029-testsnap"


def base_cfg(**over) -> dict:
    cfg = {
        "paths": {"processed": "data/processed", "artifacts": "artifacts"},
        "baseline": {"ngram_min": 2, "ngram_max": 5},
        "embedding": {"revision": "rev-embed-test"},
        "retrieval": {"hybrid": False, "rrf_k": 60, "candidate_pool": 100,
                      "project_relevance_threshold": None, "threshold_space": None,
                      "threshold_evidence_path": None},
        "rerank": {"enabled": True, "top_n": 20, "timeout_s": 10, "max_tokens": 256,
                   "revision": "rev-rerank-test", "device": "cpu"},
        "runtime": {"mode": "test_fixture"},
    }
    for k, v in over.items():
        cfg[k] = {**cfg.get(k, {}), **v}
    return cfg


class _Scores:
    def __init__(self, vals):
        self.vals = np.asarray(vals, dtype="float32")

    def scores(self, _q):
        return self.vals


class _Embedder:
    def encode(self, texts, **_):
        return np.zeros((len(texts), 4), dtype="float32")


def build_engine(sem=None, lex=None, cfg=None, reranker="stub") -> svc.SearchEngine:
    from research_compass.rerank import StubReranker

    e = object.__new__(svc.SearchEngine)
    e.cfg = cfg or base_cfg()
    e.root = e.art = None
    e.projects = pd.DataFrame({
        "record_id": [f"r{i}" for i in range(len(TITLES))],
        "source_snapshot_id": [SNAPSHOT] * len(TITLES),
        "source_row": range(1, len(TITLES) + 1),
        "title_raw": TITLES,
        "search_text": TITLES,
        "institution": ["A대", "B대", "C대", "D대", "E대", "F대"],
        "selection_year": YEARS,
        "program_대사업명": ["학술·인문사회사업"] * len(TITLES),
        "quality_flags": [[] if len(t) >= 10 else ["short_title"] for t in TITLES],
    })
    e.ids = e.projects["record_id"].tolist()
    e.search_texts = TITLES
    e._short = np.array([len(t) < 10 for t in TITLES])
    e.baseline = _Scores(LEX if lex is None else lex)
    e.semantic = {"embedder": _Embedder(), "index": _Scores(SEM if sem is None else sem)}
    e.run_mode = "test_fixture"
    e._reranker_failed = False
    e._offline_reranker = True
    e._reranker = StubReranker() if reranker == "stub" else reranker
    return e
