"""하이브리드 결합·상대 점수 단위 테스트 (개정안 01 T-25~T-27)."""
from __future__ import annotations

import numpy as np
import pytest

from research_compass.fusion import build_candidates, method_ranks, rrf_fuse, semantic_only
from research_compass.relative import (PERCENTILE_TOOLTIP, annotate, format_percentile,
                                       percentile_of, query_stats)

IDS = [f"r{i}" for i in range(6)]


# --- T-25: RRF 계산 ------------------------------------------------------
def test_rrf_matches_definition():
    ranked = {"sem": [0, 1, 2], "lex": [2, 0, 3]}
    items = rrf_fuse(ranked, IDS, k=60)
    got = {it.index: it.rrf_score for it in items}
    assert got[0] == pytest.approx(1 / 61 + 1 / 62)      # 양쪽 등장
    assert got[2] == pytest.approx(1 / 63 + 1 / 61)
    assert got[1] == pytest.approx(1 / 62)               # 의미검색만
    assert got[3] == pytest.approx(1 / 63)               # 어휘검색만


def test_rrf_ranks_are_dense_and_start_at_one():
    items = rrf_fuse({"sem": [0, 1], "lex": [1, 0]}, IDS, k=60)
    assert [it.fusion_rank for it in items] == [1, 2]


def test_document_in_one_method_only_keeps_none_rank():
    items = rrf_fuse({"sem": [0], "lex": [1]}, IDS, k=60)
    by_i = {it.index: it.ranks for it in items}
    assert by_i[0] == {"sem": 1, "lex": None}
    assert by_i[1] == {"sem": None, "lex": 1}


def test_changing_k_changes_scores_and_can_change_order():
    # k 가 작으면 1위 가중이 커져, 한쪽 1위가 양쪽 중위권보다 앞선다.
    ranked = {"sem": [0, 1, 2, 3, 4], "lex": [5, 4, 3, 2, 1]}
    big = [it.index for it in rrf_fuse(ranked, IDS, k=60)]
    small = [it.index for it in rrf_fuse(ranked, IDS, k=1)]
    assert big != small
    assert rrf_fuse(ranked, IDS, k=1)[0].rrf_score != rrf_fuse(ranked, IDS, k=60)[0].rrf_score


def test_ties_break_by_record_id_stably():
    # 완전 대칭이라 RRF 값이 같다 -> record_id 사전순
    items = rrf_fuse({"sem": [3, 1], "lex": [1, 3]}, IDS, k=60)
    assert [it.record_id for it in items] == ["r1", "r3"]
    assert items[0].rrf_score == pytest.approx(items[1].rrf_score)


def test_rrf_k_must_be_positive():
    with pytest.raises(ValueError):
        rrf_fuse({"sem": [0]}, IDS, k=0)


# --- T-26: 필터 후 결합 --------------------------------------------------
def test_filter_applied_to_both_methods_before_fusion():
    sem = np.array([0.9, 0.8, 0.7, 0.6, 0.5, 0.4], dtype="float32")
    lex = np.array([0.1, 0.2, 0.3, 0.9, 0.8, 0.7], dtype="float32")
    mask = np.array([False, True, True, False, True, True])       # 0, 3 제외
    items = build_candidates(sem, lex, IDS, mask=mask, k=60, candidate_pool=100)
    got = {it.index for it in items}
    assert 0 not in got and 3 not in got                          # 필터 밖 문서 등장 없음
    assert got == {1, 2, 4, 5}


def test_candidate_pool_limits_each_method_depth():
    sem = np.linspace(1.0, 0.0, 6).astype("float32")
    lex = np.linspace(0.0, 1.0, 6).astype("float32")
    items = build_candidates(sem, lex, IDS, k=60, candidate_pool=4)   # 방식별 상위 2개
    assert {it.index for it in items} == {0, 1, 4, 5}


def test_empty_filter_set_yields_no_candidates():
    z = np.zeros(6, dtype="float32")
    assert build_candidates(z, z, IDS, mask=np.zeros(6, dtype=bool)) == []


def test_method_ranks_respects_mask_and_depth():
    s = np.array([0.5, 0.9, 0.1, 0.7, 0.3, 0.2], dtype="float32")
    assert method_ranks(s, IDS, np.array([True, False, True, True, True, True]), 2) == [3, 0]


def test_semantic_only_passthrough_keeps_semantic_order():
    s = np.array([0.1, 0.9, 0.5, 0.3, 0.2, 0.4], dtype="float32")
    items = semantic_only(s, IDS, candidate_pool=3)
    assert [it.index for it in items] == [1, 2, 5]
    assert [it.fusion_rank for it in items] == [1, 2, 3]
    assert all(it.ranks["lex"] is None for it in items)


# --- T-27: 상대 점수 ----------------------------------------------------
def test_query_stats_and_margin():
    s = np.linspace(0.0, 1.0, 101).astype("float32")
    st = query_stats(s)
    assert st.n == 101
    assert st.p50 == pytest.approx(0.5, abs=1e-3)
    assert st.p99 == pytest.approx(0.99, abs=1e-3)
    assert st.margin(1.0) == pytest.approx(0.01, abs=1e-3)
    assert st.margin(0.5) < 0                       # p99 아래는 음수 마진


def test_single_document_corpus_has_no_nan():
    s = np.array([0.42], dtype="float32")
    st = query_stats(s)
    assert not any(np.isnan(v) for v in (st.p50, st.p90, st.p99, st.p999, st.max))
    assert st.margin(float(s[0])) == pytest.approx(0.0, abs=1e-6)
    assert percentile_of(s, float(s[0])) == 0.0     # 자기보다 높은 문서 없음


def test_percentile_counts_only_strictly_higher():
    s = np.array([0.9, 0.8, 0.8, 0.1], dtype="float32")
    assert percentile_of(s, 0.8) == pytest.approx(0.25)     # 0.9 하나만 위
    assert percentile_of(s, 0.9) == 0.0


def test_percentile_respects_mask():
    s = np.array([0.9, 0.8, 0.7], dtype="float32")
    assert percentile_of(s, 0.7, mask=np.array([False, True, True])) == pytest.approx(0.5)


def test_annotate_attaches_relative_fields():
    s = np.linspace(0.0, 1.0, 100).astype("float32")
    st, out = annotate(s, [99, 50])
    assert set(out[99]) == {"semantic_score", "semantic_margin",
                            "semantic_percentile", "percentile_label"}
    assert out[99]["semantic_margin"] > out[50]["semantic_margin"]
    assert out[99]["semantic_percentile"] == 0.0
    assert st.n == 100


# --- T-34 (일부): 표시 문구에 정확도·확률 표현이 없다 --------------------
def test_percentile_label_has_no_accuracy_or_probability_wording():
    for text in [format_percentile(p) for p in (0.0, 0.0008, 0.05, 0.5, float("nan"))]:
        assert "정확도" not in text and "확률" not in text
    assert format_percentile(0.0008) == "코퍼스 상위 0.08%"
    assert format_percentile(0.0) == "코퍼스 최상위"
    # 툴팁은 반대로 "정확도·확률이 아니다" 를 **명시해야** 한다 (개정안 4절)
    assert "정확도도" in PERCENTILE_TOOLTIP and "확률도 아닙니다" in PERCENTILE_TOOLTIP


def test_empty_corpus_raises_rather_than_returning_nan_stats():
    with pytest.raises(ValueError):
        query_stats(np.array([], dtype="float32"))
