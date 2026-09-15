"""재정렬 단위 테스트 (개정안 01 T-28~T-30, T-34 일부)."""
from __future__ import annotations

import json
import time

import numpy as np
import pytest

from research_compass.rerank import (NOT_APPLIED_BADGE, RERANK_SKIPPED, RERANK_TIMEOUT,
                                     SCORE_CAPTION, RerankTimeout, StubReranker, apply_rerank,
                                     clamp_top_n, make_pairs, make_reranker, sigmoid,
                                     write_manifest)

QUERY = "제조공정 강화학습 에너지 최적화"
TEXTS = ["강화학습 기반 제조공정 에너지 최적화 연구",
         "조선후기 향촌사회 신분 변동",
         "산업 전력 데이터 이상탐지",
         "제조공정 에너지 절감 알고리즘"]


# --- T-28: 재정렬 입력에 기관·연구자·사업명이 없다 ----------------------
def test_pairs_contain_only_query_and_title():
    pairs = make_pairs(QUERY, TEXTS)
    assert all(len(p) == 2 for p in pairs)
    assert [p[0] for p in pairs] == [QUERY] * len(TEXTS)
    assert [p[1] for p in pairs] == TEXTS


def test_pairs_do_not_leak_other_record_fields():
    forbidden = ["부산대학교", "홍길동", "학술·인문사회사업", "2024"]
    flat = " ".join(x for p in make_pairs(QUERY, TEXTS) for x in p)
    assert not any(f in flat for f in forbidden)


def test_apply_rerank_scores_only_top_n_titles():
    seen = []

    class Spy(StubReranker):
        def score(self, pairs, deadline=None):
            seen.extend(p[1] for p in pairs)
            return super().score(pairs, deadline)

    apply_rerank(Spy(), QUERY, TEXTS, top_n=10, timeout_s=10)
    assert seen == TEXTS                       # 후보 4건뿐이므로 전부, 그리고 제목만


# --- T-29: 재현성 ------------------------------------------------------
def test_repeated_runs_give_identical_order_and_scores():
    a = apply_rerank(StubReranker(), QUERY, TEXTS, top_n=20, timeout_s=10)
    b = apply_rerank(StubReranker(), QUERY, TEXTS, top_n=20, timeout_s=10)
    assert a.applied and b.applied
    assert a.order == b.order
    assert np.abs(np.array(a.scores) - np.array(b.scores)).max() <= 1e-3


def test_batch_size_does_not_change_scores():
    a = apply_rerank(StubReranker(batch_size=1), QUERY, TEXTS, top_n=20, timeout_s=10)
    b = apply_rerank(StubReranker(batch_size=8), QUERY, TEXTS, top_n=20, timeout_s=10)
    assert np.abs(np.array(a.scores) - np.array(b.scores)).max() <= 1e-3
    assert a.order == b.order


def test_order_is_descending_by_logit_ties_keep_input_order():
    class Flat(StubReranker):
        def score(self, pairs, deadline=None):
            return np.array([1.0, 1.0, 2.0, 1.0])       # 동점 다수

    r = apply_rerank(Flat(), QUERY, TEXTS, top_n=20, timeout_s=10)
    assert r.order == [2, 0, 1, 3]                      # 2위 먼저, 나머지는 입력 순서


def test_relevant_title_outranks_unrelated_one():
    r = apply_rerank(StubReranker(), QUERY, TEXTS, top_n=20, timeout_s=10)
    assert r.order.index(0) < r.order.index(1)          # 제조공정 강화학습 > 조선후기


# --- T-30: 폴백 (조용한 대체 없음) --------------------------------------
def test_load_failure_falls_back_with_warning():
    class Broken(StubReranker):
        def score(self, pairs, deadline=None):
            raise RuntimeError("모델 적재 실패")

    r = apply_rerank(Broken(), QUERY, TEXTS, top_n=20, timeout_s=10)
    assert r.applied is False
    assert r.warnings == [RERANK_SKIPPED]
    assert r.badge == NOT_APPLIED_BADGE
    assert r.scores == [] and r.order == []             # 순위를 바꾸지 않는다


def test_timeout_reports_its_own_warning_code():
    class Slow(StubReranker):
        def score(self, pairs, deadline=None):
            raise RerankTimeout("예산 초과")

    r = apply_rerank(Slow(), QUERY, TEXTS, top_n=20, timeout_s=0.01)
    assert r.applied is False and r.warnings == [RERANK_TIMEOUT]
    assert r.badge == NOT_APPLIED_BADGE


def test_real_deadline_trips_at_batch_boundary():
    class Sleepy(StubReranker):
        def score(self, pairs, deadline=None):
            out = []
            for i in range(0, len(pairs), 1):
                if deadline is not None and time.monotonic() > deadline:
                    raise RerankTimeout("배치 경계 초과")
                time.sleep(0.02)
                out.append(0.0)
            return np.asarray(out)

    r = apply_rerank(Sleepy(), QUERY, TEXTS, top_n=20, timeout_s=0.03)
    assert r.applied is False and r.warnings == [RERANK_TIMEOUT]


def test_score_count_mismatch_is_treated_as_failure():
    class Short(StubReranker):
        def score(self, pairs, deadline=None):
            return np.array([1.0])                      # 4건 요청, 1건 반환

    r = apply_rerank(Short(), QUERY, TEXTS, top_n=20, timeout_s=10)
    assert r.applied is False and r.warnings == [RERANK_SKIPPED]


def test_empty_candidate_list_skips_without_crashing():
    r = apply_rerank(StubReranker(), QUERY, [], top_n=20, timeout_s=10)
    assert r.applied is False and r.n_scored == 0 and r.warnings == [RERANK_SKIPPED]


# --- top_n 범위·표시 규칙 ----------------------------------------------
def test_top_n_is_clamped_to_allowed_range():
    assert clamp_top_n(20) == 20
    assert clamp_top_n(5) == 10        # 하한
    assert clamp_top_n(500) == 50      # 상한


def test_only_top_n_candidates_are_rescored():
    many = [f"과제 {i}" for i in range(60)]
    r = apply_rerank(StubReranker(), QUERY, many, top_n=20, timeout_s=10)
    assert r.n_scored == 20 and len(r.scores) == 20
    assert max(r.order) < 20           # 재정렬 범위를 넘어서지 않는다


def test_sigmoid_is_labelled_as_not_a_probability():
    assert sigmoid(0.0) == pytest.approx(0.5)
    assert 0.0 < sigmoid(-40.0) < 1e-10          # 큰 음수에서 오버플로 없음
    assert sigmoid(40.0) == pytest.approx(1.0)
    assert "확률" in SCORE_CAPTION and "아닙니다" in SCORE_CAPTION


def test_manifest_records_model_identity_and_top_n(tmp_path):
    p = tmp_path / "rerank_manifest.json"
    payload = write_manifest(p, StubReranker(), top_n=20, run_mode="test_fixture")
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved == payload
    for field in ("model_id", "model_revision", "dtype", "device", "top_n",
                  "load_seconds", "run_mode", "score_note"):
        assert field in saved
    assert saved["top_n"] == 20 and saved["run_mode"] == "test_fixture"
    assert "확률" in saved["score_note"]


def test_offline_factory_returns_stub_not_real_model():
    r = make_reranker({"rerank": {"model_id": "BAAI/bge-reranker-v2-m3"}}, offline=True)
    assert isinstance(r, StubReranker) and r.model_id == "stub-reranker-v1"
