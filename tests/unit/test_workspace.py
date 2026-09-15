"""탐색 작업공간 로직 (명세 v2 §6~§8, §14) — W-T01~T11.

UI 없이 검증한다. 규칙은 전부 이 계층에 있어야 한다 (v2 §15.3).
"""
from __future__ import annotations

import pytest

from research_compass import search as svc
from research_compass import workspace as ws
from research_compass.rerank import StubReranker
from research_compass.workspace import WorkspaceError

from fake_engine import base_cfg, build_engine

IDEA = "제조공정에서 강화학습을 활용한 에너지 최적화"


def new_ws(idea: str = IDEA) -> ws.Workspace:
    return ws.new_workspace(idea)


def with_elements(w: ws.Workspace, **kw) -> ws.Workspace:
    for role, text in kw.items():
        w.add_element(ws.make_element(role, text))
    return w


def run(w, plan, engine, cfg=None, **kw):
    return ws.run_perspective_search(w, plan, engine, cfg or engine.cfg,
                                     svc.search, svc.SearchRequest, **kw)


# --- W-T01: 요소 없이 최초 검색 -----------------------------------------
def test_first_search_works_with_idea_only():
    w = new_ws()
    plan = ws.build_effective_query(w.idea_text, w.elements, "full")
    assert plan.available and plan.query_origin == "original"
    assert plan.effective_query == IDEA
    assert plan.used_element_ids == ()


def test_empty_idea_is_rejected_with_a_message():
    with pytest.raises(WorkspaceError, match="한 문장"):
        ws.new_workspace("   ")


def test_full_perspective_needs_no_elements_but_others_do():
    plans = ws.available_perspectives(IDEA, [])
    assert plans["full"].available is True
    assert plans["method"].available is False
    assert plans["target_goal"].available is False


# --- W-T02: 입력 부족이면 해당 관점만 보류 -------------------------------
def test_missing_method_element_blocks_only_that_perspective():
    w = with_elements(new_ws(), target_context="제조공정")
    plans = ws.available_perspectives(w.idea_text, w.elements)
    assert plans["full"].available is True                 # 원래 검색은 유지
    assert plans["target_goal"].available is True          # 대상 요소가 있으므로 가능
    assert plans["method"].available is False
    assert "방법·접근" in plans["method"].reason           # 사유를 안내


def test_running_an_unavailable_perspective_raises_with_reason(engine):
    w = new_ws()
    plan = ws.build_effective_query(w.idea_text, w.elements, "method")
    with pytest.raises(WorkspaceError, match="방법·접근"):
        run(w, plan, engine)


def test_target_goal_needs_only_one_of_two_roles():
    only_goal = with_elements(new_ws(), goal_question="에너지 최적화")
    assert ws.build_effective_query(IDEA, only_goal.elements, "target_goal").available


# --- §6.3 기본 검색문 구성 ----------------------------------------------
def test_perspective_queries_join_elements_in_order():
    w = with_elements(new_ws(), target_context="제조공정",
                      method_approach="강화학습", goal_question="에너지 최적화")
    p = ws.available_perspectives(w.idea_text, w.elements)
    assert p["full"].effective_query == IDEA
    assert p["method"].effective_query == "강화학습 에너지 최적화"
    assert p["target_goal"].effective_query == "제조공정 에너지 최적화"


def test_no_synonym_or_constraint_is_added_automatically():
    w = with_elements(new_ws(), method_approach="강화학습")
    q = ws.build_effective_query(w.idea_text, w.elements, "method").effective_query
    assert q == "강화학습"                                  # 용어를 늘리지 않는다


def test_unconfirmed_elements_are_not_used():
    w = new_ws()
    w.add_element(ws.make_element("method_approach", "강화학습", confirmed=False))
    assert ws.build_effective_query(w.idea_text, w.elements, "method").available is False


# --- W-T03: 실제 검색문이 엔진 입력과 같다 -------------------------------
def test_effective_query_shown_equals_engine_input(engine):
    w = with_elements(new_ws(), method_approach="제조공정 에너지")
    plan = ws.build_effective_query(w.idea_text, w.elements, "method")
    r = run(w, plan, engine)
    assert r.effective_query == plan.effective_query
    assert r.original_query == w.idea_text
    assert r.original_query != r.effective_query           # 둘을 구분해 보존


def test_user_edited_query_is_recorded_as_such(engine):
    w = with_elements(new_ws(), method_approach="강화학습")
    plan = ws.build_effective_query(w.idea_text, w.elements, "method",
                                    user_override="강화학습 제조 에너지")
    assert plan.query_origin == "user_edited"
    r = run(w, plan, engine)
    assert r.effective_query == "강화학습 제조 에너지"
    assert r.query_origin == "user_edited"
    assert r.used_element_ids                              # 근거 요소는 그대로 표시


def test_blank_user_override_is_rejected():
    w = with_elements(new_ws(), method_approach="강화학습")
    with pytest.raises(WorkspaceError):
        ws.build_effective_query(w.idea_text, w.elements, "method", user_override="   ")


# --- W-T04: 클릭한 관점만 실행 (fan-out 없음) ----------------------------
def test_only_the_chosen_perspective_runs(engine):
    w = with_elements(new_ws(), target_context="제조공정", method_approach="강화학습")
    ws.available_perspectives(w.idea_text, w.elements)     # 미리보기는 실행이 아니다
    assert w.search_runs == []
    run(w, ws.build_effective_query(w.idea_text, w.elements, "method"), engine)
    assert len(w.search_runs) == 1
    assert w.search_runs[0].perspective == "method"


def test_unknown_perspective_is_rejected():
    with pytest.raises(WorkspaceError):
        ws.build_effective_query(IDEA, [], "everything")


# --- W-T05: 관점별 점수는 실행에 종속 ------------------------------------
def test_scores_stay_within_their_run_and_are_never_averaged(engine):
    w = with_elements(new_ws(), target_context="제조공정", method_approach="강화학습")
    r1 = run(w, ws.build_effective_query(w.idea_text, w.elements, "full"), engine)
    r2 = run(w, ws.build_effective_query(w.idea_text, w.elements, "method"), engine)
    assert r1.run_id != r2.run_id
    w.select(r1.run_id, "r0")
    w.select(r2.run_id, "r0")
    sel = w.selected[0]
    assert len(sel.origin_runs) == 2                       # 두 실행의 출처를 모두 보존
    # 선택 항목에 대표 점수·평균 필드가 없다
    assert not hasattr(sel, "score")
    assert not hasattr(sel, "mean_score")
    ranks = {o["run_id"]: o["rank"] for o in sel.origin_runs}
    assert set(ranks) == {r1.run_id, r2.run_id}


# --- W-T06: 필터 -------------------------------------------------------
def test_year_filter_is_recorded_and_applied(engine):
    w = new_ws()
    plan = ws.build_effective_query(w.idea_text, w.elements, "full")
    r = run(w, plan, engine, filters={"years": [2023]})
    assert r.filters == {"years": [2023]}
    assert {x.selection_year for x in r.results} == {2023}


def test_invalid_year_filter_is_rejected(engine):
    w = new_ws()
    plan = ws.build_effective_query(w.idea_text, w.elements, "full")
    with pytest.raises(WorkspaceError, match="연도"):
        run(w, plan, engine, filters={"years": ["작년"]})


# --- W-T07: 재정렬 실패 -------------------------------------------------
def test_rerank_failure_changes_actual_engine_and_keeps_warning():
    class Broken(StubReranker):
        def score(self, pairs, deadline=None):
            raise RuntimeError("적재 실패")

    eng = build_engine(reranker=Broken())
    w = new_ws()
    r = run(w, ws.build_effective_query(w.idea_text, w.elements, "full"), eng)
    assert r.rerank_applied is False
    assert r.actual_engine == "Retrieval-A"                # E 성공으로 기록하지 않는다
    assert r.requested_engine == "Retrieval-E"
    assert "RERANK_SKIPPED" in r.warnings
    assert r.rerank_badge == "재정렬 미적용"


def test_successful_rerank_reports_engine_e(engine):
    w = new_ws()
    r = run(w, ws.build_effective_query(w.idea_text, w.elements, "full"), engine)
    assert r.rerank_applied is True and r.actual_engine == "Retrieval-E"


# --- W-T08: tau 미확정이어도 검색·비교는 된다 ----------------------------
def test_uncalibrated_tau_does_not_block_search_or_selection(engine):
    w = new_ws()
    r = run(w, ws.build_effective_query(w.idea_text, w.elements, "full"), engine)
    assert r.relevance["calibrated"] is False
    assert r.relevance["n_relevant"] is None               # 전체 집계는 하지 않는다
    assert r.results                                       # 그래도 목록은 나온다
    assert w.select(r.run_id, r.results[0].record_id)      # 비교함도 동작


# --- W-T09: 비교함 중복 ------------------------------------------------
def test_same_record_from_two_runs_is_selected_once(engine):
    w = with_elements(new_ws(), method_approach="강화학습")
    r1 = run(w, ws.build_effective_query(w.idea_text, w.elements, "full"), engine)
    r2 = run(w, ws.build_effective_query(w.idea_text, w.elements, "method"), engine)
    w.select(r1.run_id, "r0")
    w.select(r2.run_id, "r0")
    assert len(w.selected) == 1
    assert len(w.selected[0].origin_runs) == 2


def test_selecting_a_record_not_in_that_run_is_rejected(engine):
    w = new_ws()
    r = run(w, ws.build_effective_query(w.idea_text, w.elements, "full"), engine,
            filters={"years": [2023]})
    with pytest.raises(WorkspaceError, match="검색 결과에 없는"):
        w.select(r.run_id, "r5")                           # 2025년 과제


def test_selection_cap_is_enforced_and_explained(engine):
    w = new_ws()
    r = run(w, ws.build_effective_query(w.idea_text, w.elements, "full"), engine, top_k=6)
    for row in r.results[:ws.MAX_SELECTED]:
        w.select(r.run_id, row.record_id)
    with pytest.raises(WorkspaceError, match="최대 5개"):
        w.select(r.run_id, r.results[ws.MAX_SELECTED].record_id)


def test_deselect_renumbers_selection_order(engine):
    w = new_ws()
    r = run(w, ws.build_effective_query(w.idea_text, w.elements, "full"), engine, top_k=3)
    for row in r.results:
        w.select(r.run_id, row.record_id)
    first = w.selected[0].record_id
    w.deselect(first)
    assert [s.selection_order for s in w.selected] == [1, 2]
    assert first not in {s.record_id for s in w.selected}


def test_user_reason_is_preserved_and_editable(engine):
    w = new_ws()
    r = run(w, ws.build_effective_query(w.idea_text, w.elements, "full"), engine)
    rid = r.results[0].record_id
    w.select(r.run_id, rid)
    assert w.selected[0].user_reason is None               # 빈 값 유지
    w.set_reason(rid, "방법 참고용")
    assert w.selected[0].user_reason == "방법 참고용"


# --- W-T10: 필터·관점 변경 시 선택 유지 ---------------------------------
def test_selection_survives_filter_change_and_is_flagged_outside(engine):
    w = new_ws()
    r1 = run(w, ws.build_effective_query(w.idea_text, w.elements, "full"), engine)
    w.select(r1.run_id, "r5")                              # 2025년 과제
    r2 = run(w, ws.build_effective_query(w.idea_text, w.elements, "full"), engine,
             filters={"years": [2023]})
    assert len(w.selected) == 1                            # 자동 삭제하지 않는다
    assert w.selected[0].outside_current_filter is True
    assert "r5" not in {x.record_id for x in r2.results}


def test_selection_inside_current_results_is_not_flagged(engine):
    w = new_ws()
    r = run(w, ws.build_effective_query(w.idea_text, w.elements, "full"), engine)
    w.select(r.run_id, r.results[0].record_id)
    assert w.selected[0].outside_current_filter is False


# --- W-T11: 연구주제·요소 변경 ------------------------------------------
def test_changing_idea_bumps_revision_without_deleting_notes(engine):
    w = with_elements(new_ws(), method_approach="강화학습")
    r = run(w, ws.build_effective_query(w.idea_text, w.elements, "full"), engine)
    w.select(r.run_id, r.results[0].record_id, user_reason="참고")
    w.change_idea("제조공정 에너지 절감")
    assert w.idea_revision == 2
    assert len(w.selected) == 1 and w.selected[0].user_reason == "참고"   # 조용히 지우지 않는다
    assert len(w.elements) == 1


def test_explicit_reset_clears_everything(engine):
    w = with_elements(new_ws(), method_approach="강화학습")
    r = run(w, ws.build_effective_query(w.idea_text, w.elements, "full"), engine)
    w.select(r.run_id, r.results[0].record_id)
    w.reset()
    assert w.elements == [] and w.selected == [] and w.search_runs == []


def test_editing_an_element_bumps_its_revision_and_marks_stale():
    w = with_elements(new_ws(), method_approach="강화학습")
    el = w.elements[0]
    observed = {el.element_id: el.revision}
    assert w.stale_element_ids(observed) == []
    w.update_element(el.element_id, "심층 강화학습")
    assert w.element(el.element_id).revision == 2
    assert w.stale_element_ids(observed) == [el.element_id]


def test_editing_a_span_element_drops_the_span_claim():
    w = new_ws()
    el = ws.make_element("method_approach", "강화학습", origin="selected_from_idea",
                         idea_text=IDEA, span=(IDEA.index("강화학습"), IDEA.index("강화학습") + 4))
    w.add_element(el)
    assert w.elements[0].idea_span is not None
    w.update_element(el.element_id, "심층 강화학습")
    assert w.elements[0].idea_span is None                 # 원문 선택이라고 계속 주장하지 않는다
    assert w.elements[0].origin == "user_entered"


def test_previous_run_keeps_its_own_effective_query_after_edits(engine):
    w = with_elements(new_ws(), method_approach="강화학습")
    r1 = run(w, ws.build_effective_query(w.idea_text, w.elements, "method"), engine)
    w.update_element(w.elements[0].element_id, "심층 강화학습")
    assert w.search_runs[0].effective_query == r1.effective_query == "강화학습"


# --- §14.1 요소 원문 범위 계약 -------------------------------------------
def test_span_element_must_match_the_idea_text():
    with pytest.raises(WorkspaceError, match="다르다"):
        ws.make_element("method_approach", "딥러닝", origin="selected_from_idea",
                        idea_text=IDEA, span=(0, 4))


def test_span_out_of_range_is_rejected():
    with pytest.raises(WorkspaceError, match="범위"):
        ws.make_element("method_approach", "강화학습", origin="selected_from_idea",
                        idea_text=IDEA, span=(0, 999))


def test_span_element_records_exact_quote():
    s = IDEA.index("강화학습")
    el = ws.make_element("method_approach", "강화학습", origin="selected_from_idea",
                         idea_text=IDEA, span=(s, s + 4))
    assert el.idea_span.quote == "강화학습"
    assert IDEA[el.idea_span.start:el.idea_span.end] == el.idea_span.quote


def test_model_proposed_elements_are_refused_in_base_build():
    with pytest.raises(WorkspaceError, match="model_proposed"):
        ws.make_element("method_approach", "강화학습", origin="model_proposed")


def test_one_element_per_role_and_max_three():
    w = with_elements(new_ws(), target_context="제조공정",
                      method_approach="강화학습", goal_question="에너지")
    with pytest.raises(WorkspaceError, match="하나만"):
        w.add_element(ws.make_element("method_approach", "딥러닝"))
    assert len(w.elements) == ws.MAX_ELEMENTS


def test_blank_element_text_is_rejected():
    with pytest.raises(WorkspaceError):
        ws.make_element("method_approach", "   ")


def test_unknown_role_is_rejected():
    with pytest.raises(WorkspaceError):
        ws.make_element("budget", "1억원")


# --- §7.4 실행 동일성 키 -------------------------------------------------
def test_engine_config_id_changes_with_settings():
    a = ws.engine_config_id(base_cfg(), hybrid=False, rerank=True, top_n=20)
    b = ws.engine_config_id(base_cfg(), hybrid=False, rerank=True, top_n=50)
    c = ws.engine_config_id(base_cfg(), hybrid=True, rerank=True, top_n=20)
    d = ws.engine_config_id(base_cfg(retrieval={"project_relevance_threshold": 0.5}),
                            hybrid=False, rerank=True, top_n=20)
    assert len({a, b, c, d}) == 4
    assert a == ws.engine_config_id(base_cfg(), hybrid=False, rerank=True, top_n=20)


def test_run_records_model_and_snapshot_identity(engine):
    w = new_ws()
    r = run(w, ws.build_effective_query(w.idea_text, w.elements, "full"), engine)
    assert r.model_manifest_ids == ("rev-embed-test", "rev-rerank-test")
    assert r.index_manifest_id and r.source_snapshot_ids
    assert r.run_mode == "test_fixture"
    assert set(r.latency_ms) >= {"s1_semantic_s", "total_s"}


# --- §14.6 스냅샷 -------------------------------------------------------
def test_snapshot_is_serialisable_and_carries_the_contract(engine):
    import json

    w = with_elements(new_ws(), method_approach="강화학습")
    r = run(w, ws.build_effective_query(w.idea_text, w.elements, "method"), engine)
    w.select(r.run_id, r.results[0].record_id, user_reason="참고")
    snap = ws.snapshot(w, capabilities={"ranked_project_search": {"status": "available"}})
    text = json.dumps(snap, ensure_ascii=False)
    assert snap["schema_version"] == "workspace/2.0"
    for k in ("workspace_id", "revision", "idea_text", "idea_revision", "elements",
              "search_runs", "selected_projects", "observations", "next_actions",
              "user_notes", "capabilities_snapshot", "source_manifests", "run_mode"):
        assert k in snap
    assert snap["search_runs"][0]["effective_query"] == "강화학습"
    assert snap["selected_projects"][0]["user_reason"] == "참고"
    # 민감한 로컬 경로·개인식별 컬럼이 없어야 한다 (v2 §14.6)
    for bad in ("C:\\", "연구책임자", "연구자번호", "/home/"):
        assert bad not in text


def test_snapshot_has_no_score_average_field(engine):
    w = new_ws()
    r = run(w, ws.build_effective_query(w.idea_text, w.elements, "full"), engine)
    w.select(r.run_id, r.results[0].record_id)
    sel = ws.snapshot(w)["selected_projects"][0]
    assert "origin_runs" in sel
    assert not any("mean" in k or "avg" in k for k in sel)
