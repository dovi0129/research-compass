"""W-T18 — 다음 탐색·확인은 실제 요소·선택 근거만 쓰고, 실행 전 확인을 거친다 (v2 §10)."""
from __future__ import annotations

import pytest

from fake_engine import build_engine
from research_compass import comparison as cmp
from research_compass import nextactions as na
from research_compass import search as svc
from research_compass import workspace as wsm


def make_ws(perspectives=("full",), elements=None):
    eng = build_engine()
    ws = wsm.new_workspace("강화학습 기반 제조공정 에너지 최적화", run_mode="test_fixture")
    for role, text in (elements or []):
        ws.add_element(wsm.make_element(role, text))
    for p in perspectives:
        plan = wsm.build_effective_query(ws.idea_text, ws.elements, p)
        wsm.run_perspective_search(ws, plan, eng, eng.cfg, svc.search, svc.SearchRequest, top_k=5)
    return ws


def refs_of(ws):
    return [cmp.TitleRef(record_id=s.record_id, source_snapshot_id=s.source_snapshot_id,
                         source_dataset_id="3049029", title_raw=s.project_record.title_raw) for s in ws.selected]


def test_no_basis_no_actions():
    ws = make_ws()
    assert na.propose(ws, []) == []                                              # 억지로 채우지 않는다


def test_unconfirmed_element_yields_inspect_detail_grouped_by_element():
    ws = make_ws(elements=[("method_approach", "강화학습"), ("goal_question", "에너지 최적화")])
    run = ws.latest_run()
    ws.select(run.run_id, run.results[0].record_id)        # '강화학습 기반 제조공정 에너지 최적화'
    ws.select(run.run_id, run.results[1].record_id)        # 다른 제목
    obs = cmp.build_matrix(ws.elements, refs_of(ws))
    acts = na.propose(ws, obs)
    inspect = [a for a in acts if a.kind == "inspect_project_detail"]
    assert inspect and all("상세 자료 확인 필요" in a.text for a in inspect)
    for a in inspect:
        assert a.basis_element_ids and a.basis_record_ids and a.basis_observation_ids
        assert a.proposed_query is None and a.origin == "rule_template" and a.confirmed is False
        assert not cmp.contains_forbidden(a.text)
    # 요소별 1개로 묶인다 (과제 수만큼 늘지 않음)
    assert len(inspect) <= len(ws.elements)


def test_method_only_run_suggests_target_goal_preview_without_executing():
    ws = make_ws(perspectives=("method",), elements=[("method_approach", "강화학습"), ("target_context", "제조공정")])
    n_runs = len(ws.search_runs)
    acts = na.propose(ws, [])
    cp = [a for a in acts if a.kind == "change_perspective"]
    assert len(cp) == 1 and cp[0].proposed_query == "제조공정" and cp[0].confirmed is False
    assert len(ws.search_runs) == n_runs                                         # 실행하지 않는다


def test_target_goal_only_run_suggests_method_preview():
    ws = make_ws(perspectives=("target_goal",), elements=[("method_approach", "강화학습"), ("target_context", "제조공정")])
    acts = na.propose(ws, [])
    assert [a.proposed_query for a in acts if a.kind == "change_perspective"] == ["강화학습"]


def test_both_perspectives_run_gives_no_perspective_suggestion():
    ws = make_ws(perspectives=("method", "target_goal"), elements=[("method_approach", "강화학습"), ("target_context", "제조공정")])
    assert [a for a in na.propose(ws, []) if a.kind == "change_perspective"] == []


def test_insufficient_and_field_selection_rules_and_cap():
    ws = make_ws(elements=[("method_approach", "강화학습"), ("target_context", "제조공정"), ("goal_question", "에너지 최적화")])
    run = ws.latest_run()
    ws.select(run.run_id, run.results[2].record_id)
    obs = cmp.build_matrix(ws.elements, refs_of(ws))
    acts = na.propose(ws, obs, insufficient=True, field_selections=[{"field_record_id": "f1", "field_name": "최적화"}])
    assert len(acts) <= na.MAX_ITEMS                                            # 최대 3개
    kinds = [a.kind for a in acts]
    assert kinds == sorted(kinds, key=lambda k: ["inspect_project_detail", "change_perspective", "edit_query", "explore_field"].index(k))
    acts2 = na.propose(ws, [], insufficient=True, field_selections=[{"field_record_id": "f1", "field_name": "최적화"}])
    assert [a.kind for a in acts2] == ["edit_query", "explore_field"]
    assert acts2[0].proposed_query == run.effective_query
    assert acts2[1].proposed_query == "최적화" and acts2[1].basis_field_record_ids == ("f1",)
    assert "분야 배정이 아니다" in acts2[1].text


def test_no_invented_topics():
    ws = make_ws(elements=[("method_approach", "강화학습")])
    run = ws.latest_run()
    ws.select(run.run_id, run.results[1].record_id)
    acts = na.propose(ws, cmp.build_matrix(ws.elements, refs_of(ws)), insufficient=True)
    blob = " ".join(a.text + " " + (a.proposed_query or "") for a in acts)
    for bad in ("안전제약", "오프라인 RL", "전이학습", "유망", "창의적"):
        assert bad not in blob


def test_user_edit_and_confirm_keep_history():
    ws = make_ws(perspectives=("method",), elements=[("method_approach", "강화학습"), ("target_context", "제조공정")])
    a = na.propose(ws, [])[0]
    e = na.user_edit(a, text="대상 관점 검색문을 '제조공정 에너지' 로 넓혀 본다", proposed_query="제조공정 에너지")
    assert e.origin == "user_edited" and e.confirmed is False and e.history[-1]["action"] == "edit"
    c = na.confirm(e)
    assert c.confirmed and c.history[-1]["action"] == "confirm"
    with pytest.raises(na.NextActionError):
        na.user_edit(a, text="   ")


def test_ids_are_deterministic():
    ws = make_ws(perspectives=("method",), elements=[("method_approach", "강화학습"), ("target_context", "제조공정")])
    a1 = na.propose(ws, [])
    a2 = na.propose(ws, [])
    assert [x.action_id for x in a1] == [x.action_id for x in a2]
