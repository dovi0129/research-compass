"""S1~S5 파이프라인 통합 단위 테스트 (개정안 01 T-26·T-31·T-34, 원본 T-14).

실모델 없이 결정적 가짜 엔진으로 **경로와 계약**을 검증한다. 품질 수치는 실측으로만 기록한다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research_compass import search as svc
from research_compass.rerank import RERANK_SKIPPED, RERANK_TIMEOUT, RerankTimeout, StubReranker

TITLES = ["강화학습 기반 제조공정 에너지 최적화",
          "산업 전력 데이터 이상탐지",
          "조선후기 향촌사회 신분 변동",
          "짧은제목",
          "고체전해질 계면 안정화 연구",
          "제조공정 에너지 절감 알고리즘 개발"]
YEARS = [2023, 2024, 2023, 2025, 2024, 2025]


def _cfg(**over) -> dict:
    cfg = {
        "paths": {"processed": "data/processed", "artifacts": "artifacts"},
        "baseline": {"ngram_min": 2, "ngram_max": 5},
        "retrieval": {"hybrid": True, "rrf_k": 60, "candidate_pool": 100,
                      "project_relevance_threshold": None, "threshold_space": None,
                      "threshold_evidence_path": None},
        "rerank": {"enabled": True, "top_n": 20, "timeout_s": 10, "max_tokens": 256},
        "runtime": {"mode": "test_fixture"},
    }
    for k, v in over.items():
        cfg[k] = {**cfg.get(k, {}), **v}
    return cfg


class _Scores:
    """미리 정해둔 점수를 돌려주는 가짜 점수기."""

    def __init__(self, vals):
        self.vals = np.asarray(vals, dtype="float32")

    def scores(self, _q):
        return self.vals


class _Embedder:
    def encode(self, texts, **_):
        return np.zeros((len(texts), 4), dtype="float32")


def make_engine(sem, lex, cfg=None, reranker="stub") -> svc.SearchEngine:
    e = object.__new__(svc.SearchEngine)
    e.cfg = cfg or _cfg()
    e.root = e.art = None
    e.projects = pd.DataFrame({
        "record_id": [f"r{i}" for i in range(len(TITLES))],
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
    e.baseline = _Scores(lex)
    e.semantic = {"embedder": _Embedder(), "index": _Scores(sem)}
    e.run_mode = "test_fixture"
    e._reranker = None if reranker == "stub" else reranker
    e._reranker_failed = False
    e._offline_reranker = True
    if reranker == "stub":
        e._reranker = StubReranker()
    return e


SEM = [0.90, 0.70, 0.20, 0.65, 0.30, 0.85]
LEX = [0.10, 0.80, 0.05, 0.70, 0.02, 0.20]


# --- T-31: tau 미확정이면 게이트 보류, 전체 집계 없음 --------------------
def test_null_tau_marks_every_result_uncalibrated_and_skips_aggregate():
    r = svc.search(svc.SearchRequest("제조공정 에너지", top_k=3), make_engine(SEM, LEX))
    assert r.relevance.calibrated is False
    assert r.relevance.tau is None
    assert r.relevance.n_relevant is None            # 전체 집계 안 함
    assert svc.GATE_UNCALIBRATED in r.warnings
    assert {x.relevance_gate for x in r.results} == {svc.GATE_UNCAL}


def test_calibrated_tau_produces_corpus_aggregate():
    cfg = _cfg(retrieval={"project_relevance_threshold": 0.6, "threshold_space": "s_sem"})
    r = svc.search(svc.SearchRequest("제조공정", top_k=6), make_engine(SEM, LEX, cfg))
    assert r.relevance.calibrated and r.relevance.scope == "corpus"
    assert r.relevance.n_relevant == 4               # 0.90 0.70 0.65 0.85
    gates = {x.record_id: x.relevance_gate for x in r.results}
    assert gates["r0"] == svc.GATE_PASS and gates["r2"] == svc.GATE_FAIL


def test_margin_space_gate_uses_p99_offset():
    cfg = _cfg(retrieval={"project_relevance_threshold": 0.0, "threshold_space": "margin"})
    r = svc.search(svc.SearchRequest("제조공정", top_k=6), make_engine(SEM, LEX, cfg))
    assert r.relevance.space == "margin" and r.relevance.scope == "corpus"
    assert r.relevance.n_relevant >= 1

def test_srr_space_does_not_claim_corpus_aggregate():
    cfg = _cfg(retrieval={"project_relevance_threshold": 0.0, "threshold_space": "s_rr"})
    r = svc.search(svc.SearchRequest("제조공정 에너지", top_k=3), make_engine(SEM, LEX, cfg))
    assert r.relevance.scope == "candidate_pool"     # 코퍼스 전체로 확장하지 않는다
    assert "코퍼스 전체 집계는 하지 않는다" in r.relevance.reason


def test_unknown_threshold_space_is_rejected():
    cfg = _cfg(retrieval={"project_relevance_threshold": 0.5, "threshold_space": "made_up"})
    with pytest.raises(ValueError):
        svc.search(svc.SearchRequest("제조공정"), make_engine(SEM, LEX, cfg))


# --- T-14: 표시 Top-K 를 바꿔도 전체 집계가 변하지 않는다 ----------------
def test_changing_top_k_does_not_change_aggregate():
    cfg = _cfg(retrieval={"project_relevance_threshold": 0.6, "threshold_space": "s_sem"})
    eng = make_engine(SEM, LEX, cfg)
    counts = {svc.search(svc.SearchRequest("제조공정", top_k=k), eng).relevance.n_relevant
              for k in (1, 3, 6)}
    assert counts == {4}


# --- T-26: 필터가 두 방식 모두에 먼저 적용된다 ---------------------------
def test_year_filter_excludes_documents_from_both_methods():
    eng = make_engine(SEM, LEX)
    r = svc.search(svc.SearchRequest("제조공정", top_k=10, years=[2023]), eng)
    assert {x.record_id for x in r.results} == {"r0", "r2"}
    assert r.stats["n_after_filter"] == 2


def test_exclude_short_masks_short_titles():
    eng = make_engine(SEM, LEX)
    with_short = svc.search(svc.SearchRequest("제조공정", top_k=10), eng)
    without = svc.search(svc.SearchRequest("제조공정", top_k=10, exclude_short=True), eng)
    assert "r3" in {x.record_id for x in with_short.results}
    assert "r3" not in {x.record_id for x in without.results}
    assert any(x.short_title for x in with_short.results)


def test_filter_that_removes_everything_returns_empty_not_crash():
    r = svc.search(svc.SearchRequest("제조공정", years=[1999]), make_engine(SEM, LEX))
    assert r.results == [] and r.relevance.calibrated is False


# --- 하이브리드 on/off ---------------------------------------------------
def test_hybrid_off_keeps_pure_semantic_order():
    eng = make_engine(SEM, LEX)
    r = svc.search(svc.SearchRequest("제조공정", top_k=3, hybrid=False, rerank=False), eng)
    assert [x.record_id for x in r.results] == ["r0", "r5", "r1"]     # 0.90 0.85 0.70
    assert all(x.lexical_rank is None for x in r.results)
    assert r.stats["hybrid"] is False


def test_hybrid_on_brings_up_lexically_strong_document():
    eng = make_engine(SEM, LEX)
    r = svc.search(svc.SearchRequest("제조공정", top_k=6, hybrid=True, rerank=False), eng)
    # r1 은 의미 3위지만 어휘 1위 -> 결합에서 순위가 올라간다
    fused = {x.record_id: x.fusion_rank for x in r.results}
    assert fused["r1"] < fused["r5"]
    assert any(x.lexical_rank is not None for x in r.results)


def test_explicit_request_overrides_eval_disabled_default_but_is_flagged():
    """평가로 꺼둔 단계도 다시 측정할 수 있어야 한다 (조건 C 재채점). 대신 경고를 남긴다."""
    cfg = _cfg(retrieval={"hybrid": False})
    r = svc.search(svc.SearchRequest("제조공정", hybrid=True), make_engine(SEM, LEX, cfg))
    assert r.stats["hybrid"] is True                      # 요청이 설정을 이긴다
    assert svc.HYBRID_DISABLED_BY_EVAL in r.warnings


def test_none_follows_config_for_hybrid_and_rerank():
    off = _cfg(retrieval={"hybrid": False}, rerank={"enabled": False})
    r = svc.search(svc.SearchRequest("제조공정"), make_engine(SEM, LEX, off))
    assert r.stats["hybrid"] is False and r.rerank_applied is False
    assert svc.HYBRID_DISABLED_BY_EVAL not in r.warnings  # 설정을 따랐을 뿐이므로 경고 없음

    on = _cfg(retrieval={"hybrid": True}, rerank={"enabled": True})
    r2 = svc.search(svc.SearchRequest("제조공정 에너지"), make_engine(SEM, LEX, on))
    assert r2.stats["hybrid"] is True and r2.rerank_applied is True


def test_request_can_disable_a_config_enabled_stage():
    on = _cfg(retrieval={"hybrid": True}, rerank={"enabled": True})
    r = svc.search(svc.SearchRequest("제조공정", hybrid=False, rerank=False),
                   make_engine(SEM, LEX, on))
    assert r.stats["hybrid"] is False and r.rerank_applied is False


# --- T-30 (경로 수준): 재정렬 실패는 조용히 넘어가지 않는다 --------------
def test_rerank_failure_falls_back_to_fusion_order_with_badge():
    class Broken(StubReranker):
        def score(self, pairs, deadline=None):
            raise RuntimeError("적재 실패")

    eng = make_engine(SEM, LEX, reranker=Broken())
    r = svc.search(svc.SearchRequest("제조공정", top_k=3, rerank=True), eng)
    assert r.rerank_applied is False
    assert RERANK_SKIPPED in r.warnings
    assert r.rerank_badge == "재정렬 미적용"
    assert all(x.rerank_score is None for x in r.results)
    base = svc.search(svc.SearchRequest("제조공정", top_k=3, rerank=False), eng)
    assert [x.record_id for x in r.results] == [x.record_id for x in base.results]


def test_rerank_timeout_reports_timeout_code():
    class Slow(StubReranker):
        def score(self, pairs, deadline=None):
            raise RerankTimeout("예산 초과")

    r = svc.search(svc.SearchRequest("제조공정", rerank=True), make_engine(SEM, LEX, reranker=Slow()))
    assert RERANK_TIMEOUT in r.warnings and r.rerank_applied is False


def test_reranker_load_failure_is_not_retried():
    eng = make_engine(SEM, LEX)
    eng._reranker, eng._reranker_failed = None, True
    r = svc.search(svc.SearchRequest("제조공정", rerank=True), eng)
    assert RERANK_SKIPPED in r.warnings and eng.reranker() is None


def test_rerank_applied_sets_scores_and_reorders():
    eng = make_engine(SEM, LEX)
    r = svc.search(svc.SearchRequest("제조공정에서 강화학습 에너지 최적화", top_k=6, rerank=True), eng)
    assert r.rerank_applied is True
    scored = [x for x in r.results if x.rerank_score is not None]
    assert scored and all(0.0 <= x.rerank_score <= 1.0 for x in scored)
    logits = [x.rerank_logit for x in scored]
    assert logits == sorted(logits, reverse=True)          # s_rr 내림차순


def test_rerank_disabled_by_request_keeps_fusion_order():
    eng = make_engine(SEM, LEX)
    r = svc.search(svc.SearchRequest("제조공정", top_k=3, rerank=False), eng)
    assert r.rerank_applied is False and not r.warnings[:0]
    assert all(x.rerank_score is None for x in r.results)
    assert any("재정렬 꺼짐" in n for n in r.notes)


# --- 계약·표시 규칙 (T-34) ----------------------------------------------
def test_result_carries_full_contract_fields():
    r = svc.search(svc.SearchRequest("제조공정", top_k=1, rerank=False), make_engine(SEM, LEX))
    x = r.results[0]
    for f in ("semantic_score", "semantic_percentile", "semantic_margin", "lexical_rank",
              "fusion_rank", "rerank_score", "relevance_gate", "percentile_label"):
        assert hasattr(x, f)
    assert x.rank == 1 and x.fusion_rank == 1
    # 결합 1위는 의미 1위와 다를 수 있다 (r1 은 의미 3위·어휘 1위). 계약 필드만 확인한다.
    assert x.semantic_score == pytest.approx(SEM[int(x.record_id[1:])], abs=1e-6)
    assert x.lexical_rank == 1


def test_percentile_label_carries_no_accuracy_or_probability_claim():
    r = svc.search(svc.SearchRequest("제조공정", top_k=6), make_engine(SEM, LEX))
    for x in r.results:
        assert "정확도" not in x.percentile_label and "확률" not in x.percentile_label
        assert x.percentile_label.startswith("코퍼스")


def test_normalized_query_is_used_and_reported():
    r = svc.search(svc.SearchRequest("  제조공정   에너지  "), make_engine(SEM, LEX))
    assert r.normalized_query == "제조공정 에너지"


def test_timings_are_recorded_per_stage():
    r = svc.search(svc.SearchRequest("제조공정", rerank=True), make_engine(SEM, LEX))
    for k in ("s1_semantic_s", "s1_lexical_s", "s2_fusion_s", "s3_relative_s", "total_s"):
        assert k in r.timings
