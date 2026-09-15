"""검색 계층 단위 테스트 (명세 19절 T-08~T-14)."""
from __future__ import annotations

import numpy as np
import pytest

from research_compass.embedding import HashEmbedder, check_vectors
from research_compass.prepare import normalize_text
from research_compass.retrieval import FlatIPIndex, above_threshold, rank

TEXTS = ["강화학습 기반 제조공정 에너지 최적화", "산업 전력 데이터 이상탐지",
         "양자배터리 충전 제어", "조선후기 사회사 연구", "고체전해질 계면 안정화"]
IDS = [f"r{i}" for i in range(len(TEXTS))]


@pytest.fixture(scope="module")
def vecs():
    return HashEmbedder(dim=64).encode(TEXTS)


# --- T-08: 벡터 정규화·NaN·영벡터 ---------------------------------------
def test_vectors_are_normalized(vecs):
    c = check_vectors(vecs)
    assert c["normalized"] and c["nan_rows"] == 0 and c["zero_rows"] == 0


def test_empty_text_does_not_produce_nan():
    v = HashEmbedder(dim=64).encode([""])
    assert not np.isnan(v).any()


# --- T-09: FAISS 와 NumPy 참조 구현 일치 --------------------------------
def test_faiss_matches_numpy_reference(vecs):
    idx = FlatIPIndex(vecs)
    q = vecs[0]
    assert np.abs(idx.scores(q) - idx.scores_numpy(q)).max() < 1e-5


def test_self_similarity_is_one(vecs):
    idx = FlatIPIndex(vecs)
    assert idx.scores_numpy(vecs[2])[2] == pytest.approx(1.0, abs=1e-5)


# --- T-10: 필터 적용 집합에서의 Top-K -----------------------------------
def test_filter_applied_before_ranking(vecs):
    idx = FlatIPIndex(vecs)
    s = idx.scores(vecs[0])
    mask = np.array([False, True, True, False, True])
    got = [i for i, _ in rank(s, IDS, mask, top_k=5)]
    assert set(got) <= {1, 2, 4}
    assert len(got) == 3          # 전역 Top-K 를 잘라낸 게 아니라 필터 집합 전체에서 뽑는다


def test_ties_break_stably():
    s = np.array([0.5, 0.5, 0.5], dtype="float32")
    ids = ["c", "a", "b"]
    assert [ids[i] for i, _ in rank(s, ids, None, 3)] == ["a", "b", "c"]


# --- T-13: 기준 미검증이면 판단 보류 ------------------------------------
def test_uncalibrated_threshold_yields_no_positives(vecs):
    idx = FlatIPIndex(vecs)
    s = idx.scores(vecs[0])
    assert above_threshold(s, None, None).sum() == 0      # tau 미검증 -> 전부 보류
    assert above_threshold(s, None, 0.99).sum() >= 1


# --- T-14: 화면 Top-K 변경이 전체 집계에 영향을 주지 않는다 --------------
def test_topk_does_not_change_aggregate(vecs):
    idx = FlatIPIndex(vecs)
    s = idx.scores(vecs[0])
    tau = 0.3
    agg5 = int(above_threshold(s, None, tau).sum())
    _ = rank(s, IDS, None, 2)
    _ = rank(s, IDS, None, 5)
    assert int(above_threshold(s, None, tau).sum()) == agg5


# --- 정규화 ---------------------------------------------------------------
def test_normalize_keeps_technical_tokens():
    assert normalize_text("  CO2  저감   기술 3D-프린팅 ") == "CO2 저감 기술 3D-프린팅"


def test_normalize_is_idempotent():
    s = "딥러닝 기반　수질 예측"
    assert normalize_text(normalize_text(s)) == normalize_text(s)
