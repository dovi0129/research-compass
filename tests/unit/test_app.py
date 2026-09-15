"""app.py 화면 배선 시험 — Streamlit AppTest + 가짜 엔진 (test_fixture).

규칙 자체는 test_workspace / test_search_pipeline 이 검증한다. 여기서는 **화면이 그 함수를 올바르게
호출하고 결과를 숨기지 않는지**만 본다 (W-T01·T03·T04·T09·T24·T26·T27 의 UI 측).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fake_engine import build_engine

APP = Path(__file__).resolve().parents[2] / "app.py"
st_testing = pytest.importorskip("streamlit.testing.v1")
AppTest = st_testing.AppTest


def boot(engine=None, ux: str | None = None):
    at = AppTest.from_file(str(APP), default_timeout=60)
    if ux is not None:
        at.session_state["_ux_override"] = ux            # 화면 조건 주입 (v2 §17.6)
    at.session_state["_engine_override"] = engine or build_engine()
    at.session_state["_caps_override"] = {"project_search": {"status": "verified", "reason": "t"},
                                          "field_search": {"status": "verified", "reason": "t"}}
    at.run()
    return at


def all_markdown(at) -> str:
    return "\n".join(m.value for m in at.markdown)


def search(at, idea: str):
    at.text_input(key="idea_input").input(idea).run()
    at.button(key="btn_search").click().run()
    return at


def test_boots_without_workspace_and_shows_mode():
    at = boot()
    assert not at.exception
    assert at.session_state["ws"] is None
    md = all_markdown(at)
    assert "테스트 임베더" in md                     # W-T26: fixture 모드를 실제 모델처럼 보이지 않음
    assert "rc-landing" in md                       # 첫 화면


def test_first_search_needs_only_idea(monkeypatch):
    at = search(boot(), "제조공정 에너지 최적화")
    assert not at.exception
    ws = at.session_state["ws"]
    assert len(ws.search_runs) == 1                # W-T01: 요소 없이 원래 질의로 1회 실행
    run = ws.search_runs[0]
    assert run.perspective == "full" and run.effective_query == "제조공정 에너지 최적화"
    md = all_markdown(at)
    assert "강화학습 기반 제조공정 에너지 최적화" in md   # 원문 제목 그대로
    assert run.effective_query in md                # W-T03: 화면의 실제 검색문 = 엔진 입력
    assert "Retrieval-E" in md                      # StubReranker 적용 → E
    assert "테스트 임베더" in md


def test_select_into_basket_is_deduplicated():
    at = search(boot(), "제조공정 에너지 최적화")
    run = at.session_state["ws"].search_runs[0]
    top = run.results[0]
    at.button(key=f"sel_{run.run_id}_{top.record_id}").click().run()
    ws = at.session_state["ws"]
    assert [s.record_id for s in ws.selected] == [top.record_id]
    # 같은 항목은 '담김' 으로 비활성. 눌러도 늘지 않는다 (W-T09)
    btn = at.button(key=f"sel_{run.run_id}_{top.record_id}")
    assert btn.disabled
    assert "비교함" in all_markdown(at)
    at.button(key=f"desel_{top.source_snapshot_id}_{top.record_id}").click().run()
    assert at.session_state["ws"].selected == []


def test_more_reveals_without_rerunning():
    at = search(boot(), "제조공정 에너지 최적화")
    ws = at.session_state["ws"]
    assert len(ws.search_runs) == 1 and len(ws.search_runs[0].results) == 6   # 가짜 코퍼스 6건
    assert at.session_state["shown"] == 5
    at.button(key="btn_more").click().run()
    assert at.session_state["shown"] == 6
    assert len(at.session_state["ws"].search_runs) == 1                        # 재검색 없음


def test_perspective_runs_only_clicked_one():
    at = search(boot(), "제조공정 에너지 최적화")
    ws = at.session_state["ws"]
    at.text_input(key=f"el_method_approach_{ws.idea_revision}").input("강화학습").run()
    at.button(key="btn_elements").click().run()
    assert [e.role for e in at.session_state["ws"].elements] == ["method_approach"]
    at.segmented_control(key="persp").set_value("method").run()
    at.button(key="btn_run_persp").click().run()
    ws = at.session_state["ws"]
    assert len(ws.search_runs) == 2                                            # W-T04: 관점 1개만 추가
    last = ws.search_runs[-1]
    assert last.perspective == "method" and last.effective_query == "강화학습"
    assert last.query_origin == "elements_joined"
    md = all_markdown(at)
    assert "방법·접근 중심으로 탐색" in md and "강화학습" in md


def test_target_goal_without_elements_is_held_not_executed():
    at = search(boot(), "제조공정 에너지 최적화")
    at.segmented_control(key="persp").set_value("target_goal").run()
    assert any("요소가 하나 이상 필요" in i.value for i in at.info)
    assert not [b for b in at.button if b.key == "btn_run_persp"]               # 실행 버튼 자체가 없다
    assert len(at.session_state["ws"].search_runs) == 1


def test_snapshot_download_has_no_local_paths_or_pii():
    at = search(boot(), "제조공정 에너지 최적화")
    dl = at.download_button(key="dl_memo_json")
    assert dl is not None
    from research_compass import workspace as wsm
    import json
    snap = json.dumps(wsm.snapshot(at.session_state["ws"]), ensure_ascii=False)
    for bad in ("C:\\", "연구책임자", "연구자번호", "/home/"):
        assert bad not in snap                                                 # W-T24 · §21.3


def test_raw_title_is_escaped_not_rendered():
    e = build_engine()
    evil = "<script>alert(1)</script> 제조공정 에너지 <b>강조</b>"
    e.projects.loc[0, "title_raw"] = evil
    at = search(boot(e), "제조공정 에너지 최적화")
    md = all_markdown(at)
    assert "<script>" not in md and "&lt;script&gt;" in md                     # W-T27
    assert "<b>강조</b>" not in md and "&lt;b&gt;강조&lt;/b&gt;" in md


def test_idea_change_marks_old_results_stale_without_deleting():
    at = search(boot(), "제조공정 에너지 최적화")
    run1 = at.session_state["ws"].search_runs[0]
    top = run1.results[0]
    at.button(key=f"sel_{run1.run_id}_{top.record_id}").click().run()
    # 한 페이지(D-038)에서 새 연구주제는 `요소별 탐색` 탭의 연구주제 칸으로 낸다 (첫 화면으로 돌아가는 단추는 없다)
    at.segmented_control(key="search_mode").set_value("elements").run()
    at.text_input(key="idea_input_el").input("산업 전력 이상탐지").run()
    at.radio(key="persp_land").set_value("full").run()
    at.button(key="btn_search_el").click().run()
    ws = at.session_state["ws"]
    assert ws.idea_revision == 2 and len(ws.search_runs) == 2
    assert len(ws.selected) == 1                                               # W-T11: 조용히 지우지 않음
    assert ws.search_runs[0].idea_revision == 1 and ws.search_runs[1].idea_revision == 2


def test_basket_item_outside_displayed_results_is_flagged_not_removed():
    """필터를 바꿔 다시 탐색하면 이전 선택은 남고 '지금 보는 결과에 없음' 으로만 표시된다 (W-T10 UI)."""
    at = search(boot(), "제조공정 에너지 최적화")
    run1 = at.session_state["ws"].search_runs[0]
    r2023 = next(r for r in run1.results if r.selection_year == 2023)
    at.button(key=f"sel_{run1.run_id}_{r2023.record_id}").click().run()
    assert "지금 보는 결과에 없음" not in all_markdown(at)
    at.multiselect(key="f_years").select(2025).run()
    at.button(key="btn_refilter").click().run()
    ws = at.session_state["ws"]
    assert len(ws.search_runs) == 2 and ws.search_runs[-1].filters == {"years": [2025]}
    assert all(r.selection_year == 2025 for r in ws.search_runs[-1].results)
    assert len(ws.selected) == 1                                               # 자동 삭제 없음
    assert "지금 보는 결과에 없음" in all_markdown(at)


def test_field_card_seed_fills_query_preview_without_running():
    """분야 카드 '검색문으로 미리보기' 는 검색문 칸만 채운다. 실행은 사용자 확인 후 (v2 §12.3·§6.5)."""
    at = search(boot(), "제조공정 에너지 최적화")
    n_runs = len(at.session_state["ws"].search_runs)
    at.session_state["query_seed"] = "최적화"
    at.run()
    ws = at.session_state["ws"]
    key = f"query_edit_full_{ws.revision}_{at.session_state['query_seq']}"
    assert at.text_input(key=key).value == "최적화"
    assert len(at.session_state["ws"].search_runs) == n_runs                # 자동 실행 없음
    at.button(key="btn_run_persp").click().run()
    last = at.session_state["ws"].search_runs[-1]
    assert last.effective_query == "최적화" and last.query_origin == "user_edited"


def _with_elements_and_basket(at):
    """검색 → 요소 2개 반영 → 상위 2건 담기. W3 영역 시험의 공통 준비."""
    at = search(at, "제조공정 에너지 최적화")
    ws = at.session_state["ws"]
    at.text_input(key=f"el_method_approach_{ws.idea_revision}").input("강화학습").run()
    at.text_input(key=f"el_goal_question_{ws.idea_revision}").input("에너지 최적화").run()
    at.button(key="btn_elements").click().run()
    run = at.session_state["ws"].search_runs[0]
    for r in run.results[:2]:
        at.button(key=f"sel_{run.run_id}_{r.record_id}").click().run()
    return at


def test_evidence_section_auto_findings_are_unreviewed_and_highlighted():
    at = _with_elements_and_basket(boot())
    assert not at.exception
    obs = list(at.session_state["observations"].values())
    assert len(obs) == 4                                                       # 요소 2 × 과제 2
    assert all(o.review_status == "unreviewed" for o in obs)
    md = all_markdown(at)
    assert 'rc-cell found">제목에 있음<' in md                                 # '강화학습 기반 제조공정 에너지 최적화' 에서 발견
    assert 'rc-cell none">제목에 없음<' in md                                  # '산업 전력 데이터 이상탐지' 에는 없음
    assert "사용을 확인했다" not in md and "다루지 않았다" not in md                  # 금지 표현 없음 (W-T14)
    md_memo = "\n".join(m.value for m in at.markdown if m.value.startswith("# Research Compass 탐색 메모"))
    assert "## 선택한 과제" in md_memo and "### E1." in md_memo and "### E2." in md_memo   # 압축 메모 (D-033)
    assert "## 근거 부록" not in md_memo and "제목에서 확인한 표현" not in md_memo        # 전체 기록은 JSON 에만
    assert at.download_button(key="dl_memo_json") is not None


def test_memo_without_selection_is_honest():
    at = search(boot(), "제조공정 에너지 최적화")
    md_memo = "\n".join(m.value for m in at.markdown if m.value.startswith("# Research Compass 탐색 메모"))
    assert "참고 후보를 선택하지 않았습니다" in md_memo and "### E1." not in md_memo   # W-T19
    assert at.download_button(key="dl_memo_json") is not None


def test_not_ready_shows_guidance_not_fake_results(tmp_path, monkeypatch):
    at = AppTest.from_file(str(APP), default_timeout=60)
    # 준비 안 된 환경을 흉내: 엔진 주입 없이 readiness 가 실패하도록 설정 경로를 비운 사본으로
    import yaml
    cfg = yaml.safe_load((APP.parent / "config" / "default.yaml").read_text(encoding="utf-8"))
    cfg["paths"]["processed"] = str(tmp_path / "nope")
    cfg["paths"]["artifacts"] = str(tmp_path / "nope_art")
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("RESEARCH_COMPASS_CONFIG", str(p))
    at.run()
    assert not at.exception
    assert any("준비되지 않아" in e.value for e in at.error)
    assert at.session_state["ws"] is None


# ---------------------------------------------------------------------------
# W5 — 사용자 작업 비교 조건 (UX-L 목록 전용 / UX-W 작업공간, v2 §17.6)
# ---------------------------------------------------------------------------
def wkeys(widgets) -> list[str]:
    return [w.key for w in widgets]


def test_ux_l_is_list_only_but_keeps_query_edit_and_free_memo():
    """UX-L 은 관점·비교함·근거 비교표·탐색 메모를 두지 않는다. 대신 검색문 수정과 자유 메모는 준다."""
    at = search(boot(ux="l"), "제조공정 에너지 최적화")
    assert not at.exception
    run = at.session_state["ws"].search_runs[0]
    b = wkeys(at.button)
    assert "btn_run_query" in b                                    # 검색문 직접 수정 가능
    assert "free_memo" in wkeys(at.text_area)                      # 자유 메모 있음
    assert not any(k.startswith("sel_") for k in b)                # 비교함 담기 없음
    assert "btn_elements" not in b and "persp" not in wkeys(at.segmented_control)
    md = all_markdown(at)
    assert "제목이 유사한 과제" in md and run.results[0].title_raw in md   # 목록·원문은 그대로
    for gone in ("비교함", "제목 근거 비교", "탐색 메모", "다음 탐색"):
        assert gone not in md, gone
    assert "자유 메모" in md


def test_ux_w_is_the_default_and_has_workspace_sections():
    at = search(boot(), "제조공정 에너지 최적화")
    md = all_markdown(at)
    assert "비교함" in md and "제목 근거 비교" in md and "탐색 메모" in md
    assert "free_memo" in wkeys(at.text_area)                      # 자유 메모는 두 조건 공통 (기록 수단 동등)


def test_both_conditions_search_the_same_way():
    """같은 엔진·같은 원자료·같은 표시 건수. UX-W 에 더 좋은 결과를 주지 않는다 (v2 §17.6)."""
    idea = "제조공정 에너지 최적화"
    a = search(boot(ux="l"), idea).session_state["ws"].search_runs[0]
    b = search(boot(ux="w"), idea).session_state["ws"].search_runs[0]
    assert a.effective_query == b.effective_query and a.perspective == b.perspective
    assert a.actual_engine == b.actual_engine and a.rerank_applied == b.rerank_applied
    assert [r.record_id for r in a.results] == [r.record_id for r in b.results]
    assert [r.rank for r in a.results] == [r.rank for r in b.results]


def test_ux_l_query_edit_runs_user_query_and_keeps_idea():
    at = search(boot(ux="l"), "제조공정 에너지 최적화")
    ws = at.session_state["ws"]
    key = f"query_edit_l_{ws.revision}_0"
    at.text_input(key=key).input("전력 데이터 이상탐지").run()
    assert len(at.session_state["ws"].search_runs) == 1            # 입력만으로 실행되지 않는다
    at.button(key="btn_run_query").click().run()
    ws = at.session_state["ws"]
    assert len(ws.search_runs) == 2
    last = ws.search_runs[-1]
    assert last.effective_query == "전력 데이터 이상탐지" and last.query_origin == "user_edited"
    assert ws.idea_text == "제조공정 에너지 최적화"                    # 연구주제는 그대로
    assert last.perspective == "full"


def test_ux_l_feature_table_omits_sections_not_on_that_screen():
    at = boot(ux="l")
    dev = all_markdown(at)
    assert "관점별 탐색" not in dev and "제목 근거 비교" not in dev
    at2 = boot()
    assert "관점별 탐색" in all_markdown(at2)


def test_second_search_shows_history_immediately():
    """실행 직후 탐색 이력이 나와야 한다. execute() 가 st.rerun 하지 않으면 한 박자 늦게 나타났다."""
    at = search(boot(ux="l"), "제조공정 에너지 최적화")
    ws = at.session_state["ws"]
    assert not at.pills.values                                     # 실행 1건이면 이력 위젯 없음
    at.text_input(key=f"query_edit_l_{ws.revision}_0").input("전력 데이터 이상탐지").run()
    at.button(key="btn_run_query").click().run()
    ws = at.session_state["ws"]
    assert len(ws.search_runs) == 2
    pills = at.pills(key=f"hist_{len(ws.search_runs)}")            # 같은 응답에서 이력이 보인다
    assert pills.value == ws.search_runs[-1].run_id                # 새 실행이 선택된 상태
    assert len(pills.options) == 2


# ---------------------------------------------------------------------------
# D-029 — 화면 재설계 계약: 흐름 순서·핵심 기능 노출·비교표 문구·자유 메모 반출
# ---------------------------------------------------------------------------
def test_landing_shows_only_search_box():
    """검색 전에는 검색칸(과 기능 상태 접힘)만 있다 — 결과·관점·비교·메모 절이 없다 (D-031)."""
    at = boot()
    md = all_markdown(at)
    assert "rc-landing" in md and "idea_input" in wkeys(at.text_input)
    for gone in ('rc-sec">제목이 유사한 과제', 'rc-sec">선택한 과제 비교', 'rc-sec">탐색 메모', 'rc-h">비교함'):
        assert gone not in md, gone                                    # 절 제목이 없다 (기능표의 낱말은 무관)
    assert "persp" not in wkeys(at.segmented_control)


def test_main_flow_order_and_perspective_always_visible():
    """검색 뒤에는 관점 선택이 접힘 없이 보이고, 절 순서가 결과→비교→메모→데이터·기능 정보다."""
    at = search(boot(), "제조공정 에너지 최적화")
    assert at.segmented_control(key="persp").value == "full"           # 관점 선택이 항상 보인다
    md = all_markdown(at)
    order = ["제목이 유사한 과제", "선택한 과제 비교", "탐색 메모", "데이터 및 검색 정보"]
    pos = [md.find(x) for x in order]
    assert all(p >= 0 for p in pos), dict(zip(order, pos))
    assert pos == sorted(pos)
    ws = at.session_state["ws"]
    key = f"query_edit_full_{ws.revision}_0"
    assert at.text_input(key=key).value == "제조공정 에너지 최적화"     # 실제 검색문이 항상 보인다


def test_comparison_table_labels_do_not_claim_absence():
    at = _with_elements_and_basket(boot())
    md = all_markdown(at)
    assert 'rc-cell found">제목에 있음<' in md and 'rc-cell none">제목에 없음<' in md   # 표는 두 값이 기본
    assert "확인이 필요한 요소:" in md and "<b>에너지 최적화</b>" in md     # 없음으로 남은 요소를 한 줄로 (D-032: 뒷문장 없음)
    assert "— 제목에 없을 뿐" not in md and 'title="제목에 이 낱말이 없을 뿐' in md   # 설명은 마우스 올림에만
    assert "<b>기관</b>" in md and "<b>사업</b>" in md and "<b>탐색 관점</b>" in md and "<b>검색문</b>" in md   # 발견 맥락 우선 (D-035)
    assert "<b>당시 순위</b>" in md and "<b>원본 위치</b>" in md
    assert md.index("<b>탐색 관점</b>") < md.index("<b>선정연도</b>") < md.index("<b>기관</b>")
    assert 'rc-sec">다음 탐색·확인' not in md and "nx_method" not in wkeys(at.button)   # 화면 절·바로가기 없음 (D-030). 메모 절 제목은 남는다
    from research_compass import comparison as cmp
    for bad in cmp.FORBIDDEN_PHRASES:
        assert bad not in md, bad


def test_comparison_without_elements_shows_record_facts_table():
    """요소를 넣지 않고 담아도 제목 한 줄이 아니라 기관·선정연도·사업을 나란히 놓는 표가 나온다 (D-032)."""
    at = search(boot(), "제조공정 에너지 최적화")
    run = at.session_state["ws"].search_runs[0]
    for r in run.results[:2]:
        at.button(key=f"sel_{run.run_id}_{r.record_id}").click().run()
    md = all_markdown(at)
    assert "<b>기관</b>" in md and "<b>선정연도</b>" in md and "<b>사업</b>" in md
    assert 'class="ref">E1<' in md and 'class="ref">E2<' in md
    assert 'rc-cell found">' not in md and 'rc-cell none">' not in md   # 요소가 없으니 있음/없음 칸도 없다
    assert "같은 사업의 수록 레코드" in md and "원본 행" in md and "제목 표현 비교" not in md   # 요소 없으면 표현 비교 접힘도 없다
    assert "확인이 필요한 요소:" not in md


def test_free_memo_survives_search_and_element_reruns():
    """메모를 쓴 뒤 다시 탐색하거나 요소를 반영해도(내부 st.rerun) 메모가 내보내기에서 사라지지 않는다 (D-033 발견 버그)."""
    at = search(boot(), "제조공정 에너지 최적화")
    at.text_area(key="free_memo").input("E1이 가장 가깝다").run()
    ws = at.session_state["ws"]
    at.text_input(key=f"query_edit_full_{ws.revision}_0").input("전력 데이터 이상탐지").run()
    at.button(key="btn_run_persp").click().run()                      # execute() → st.rerun()
    assert len(at.session_state["ws"].search_runs) == 2
    md_memo = "\n".join(m.value for m in at.markdown if m.value.startswith("# Research Compass 탐색 메모"))
    assert "E1이 가장 가깝다" in md_memo and at.session_state["ws"].user_notes == "E1이 가장 가깝다"
    ws = at.session_state["ws"]
    at.text_input(key=f"el_method_approach_{ws.idea_revision}").input("강화학습").run()
    at.button(key="btn_elements").click().run()                      # apply_elements() → st.rerun()
    md_memo = "\n".join(m.value for m in at.markdown if m.value.startswith("# Research Compass 탐색 메모"))
    assert "E1이 가장 가깝다" in md_memo


def test_free_memo_goes_into_final_markdown_as_user_section():
    at = search(boot(), "제조공정 에너지 최적화")
    at.text_area(key="free_memo").input("후보 2건 중 첫 번째가 더 가깝다고 느낌 — 확인 필요").run()
    ws = at.session_state["ws"]
    assert ws.user_notes == "후보 2건 중 첫 번째가 더 가깝다고 느낌 — 확인 필요"
    md_memo = "\n".join(m.value for m in at.markdown if m.value.startswith("# Research Compass 탐색 메모"))
    assert "## 메모" in md_memo and "첫 번째가 더 가깝다고 느낌" in md_memo
    assert md_memo.index("## 선택한 과제") < md_memo.index("## 탐색 기록") < md_memo.index("## 메모")


def test_result_card_hides_rerank_number_but_keeps_similarity():
    at = search(boot(), "제조공정 에너지 최적화")
    run = at.session_state["ws"].search_runs[0]
    assert run.rerank_applied
    cards = [m.value for m in at.markdown if 'class="rc-card' in m.value]
    assert cards
    assert all("의미 유사도" in c and "재정렬 점수 0." not in c for c in cards)   # 숫자는 근거 보기에만
    assert all('class="rc-bar"' not in c and "상위" not in c for c in cards)        # 정렬 막대·백분위는 카드에 없다 (D-035)
    md = all_markdown(at)
    assert "최종 표시 순위" in md and "1차 의미검색 위치" in md                     # 두 순위는 근거 보기에서 다른 값으로


def test_theme_toggle_defaults_to_system_and_switches_palette():
    at = boot()
    assert at.session_state["theme_choice"] == "system"
    css = next(m.value for m in at.markdown if m.value.startswith("<style>"))
    assert css.startswith("<style>:root{--bg:#F3F5F7") and "--accent:#1F4E8C" in css   # 시스템 = 라이트 기본 — 행정 네이비 (D-036)
    assert "@media (prefers-color-scheme: dark){:root{--bg:#1E242C" in css     # 시스템 모드는 CSS 가 직접 운영체제 설정을 본다 (반쪽 화면 버그 수정)
    at.segmented_control(key="theme_pick").set_value("dark").run()
    assert at.session_state["theme_choice"] == "dark"
    css = next(m.value for m in at.markdown if m.value.startswith("<style>"))
    assert css.startswith("<style>:root{--bg:#1E242C") and "--ink:#E4E8ED" in css   # 슬레이트 다크, 보라 기운 없음 (D-036)
    assert "prefers-color-scheme" not in css                                  # 고정 선택이면 미디어 쿼리 없음
    at.segmented_control(key="theme_pick").set_value("light").run()
    css = next(m.value for m in at.markdown if m.value.startswith("<style>"))
    assert css.startswith("<style>:root{--bg:#F3F5F7") and "prefers-color-scheme" not in css


# ---------------------------------------------------------------------------
# D-036 — 첫 화면 복합화: 검색 방식 4개 · 검색 전 범위 · 수치 띠 · 바닥글. 설명문 없음
# ---------------------------------------------------------------------------
def test_landing_has_modes_stats_and_footer_but_no_prose():
    at = boot()
    assert at.segmented_control(key="search_mode").value == "topic"
    md = all_markdown(at)
    assert 'class="rc-stats"' in md and "수록 레코드" in md and "주관기관명" in md
    assert 'class="rc-foot"' in md and "data.go.kr 3049029" in md and "기관의 공식 서비스가 아닙니다" in md
    assert "수록 데이터 구성" in md                                          # 오른쪽 30%: 전체 수록 데이터의 연도·사업 구성 (실데이터)
    assert 'class="rc-band"' in md and "공모전 출품작" in md                # 상단 식별 띠
    assert md.index('class="rc-band"') < md.index('class="rc-landing"')       # 띠가 머리말보다 위
    assert "theme_pick" in wkeys(at.segmented_control)                         # 화면 모드는 페이지 맨 아래 작은 글자로 남아 있다
    assert "찾아 나란히 비교합니다" not in md and 'class="tag"' not in md      # 한 줄 설명(태그라인) 없음
    assert "f_years" in wkeys(at.multiselect) and "f_short" in wkeys(at.checkbox)  # 검색 전 범위


def test_landing_filters_apply_to_first_search():
    at = boot()
    at.multiselect(key="f_years").select(2025).run()
    at = search(at, "제조공정 에너지 최적화")
    run = at.session_state["ws"].search_runs[0]
    assert run.filters == {"years": [2025]}
    assert all(r.selection_year == 2025 for r in run.results)
    assert at.multiselect(key="f_years").value == [2025]                   # 결과 화면의 검색 범위에도 그대로


def test_landing_elements_mode_runs_only_chosen_perspective():
    at = boot()
    at.segmented_control(key="search_mode").set_value("elements").run()
    assert "idea_input" not in wkeys(at.text_input) and "idea_input_el" in wkeys(at.text_input)
    at.text_input(key="idea_input_el").input("제조공정 에너지 최적화").run()
    at.text_input(key="el_land_method_approach").input("강화학습").run()
    at.radio(key="persp_land").set_value("method").run()
    at.button(key="btn_search_el").click().run()
    ws = at.session_state["ws"]
    assert ws.idea_text == "제조공정 에너지 최적화" and [e.role for e in ws.elements] == ["method_approach"]
    assert len(ws.search_runs) == 1                                          # 관점 1개만 실행, 자동 통합 없음
    run = ws.search_runs[0]
    assert run.perspective == "method" and run.effective_query == "강화학습"
    assert at.segmented_control(key="persp").value == "method"             # 결과 화면의 관점 선택도 같은 관점


def test_landing_elements_mode_without_required_element_is_held():
    at = boot()
    at.segmented_control(key="search_mode").set_value("elements").run()
    at.text_input(key="idea_input_el").input("제조공정 에너지 최적화").run()
    at.radio(key="persp_land").set_value("target_goal").run()
    at.button(key="btn_search_el").click().run()
    assert at.session_state["ws"] is not None and at.session_state["ws"].search_runs == []
    assert any("요소가 하나 이상 필요" in i.value for i in at.info)


def test_landing_summary_mode_uses_whole_text_as_query():
    at = boot()
    at.segmented_control(key="search_mode").set_value("summary").run()
    text = "본 연구는 제조공정의 에너지 최적화를 위해\n강화학습 기반 제어 기법을 제안한다.  두 번째 문단."
    at.text_area(key="summary_input").input(text).run()
    at.button(key="btn_search_summary").click().run()
    ws = at.session_state["ws"]
    run = ws.search_runs[0]
    assert ws.idea_text == "본 연구는 제조공정의 에너지 최적화를 위해 강화학습 기반 제어 기법을 제안한다. 두 번째 문단."
    assert run.perspective == "full" and run.effective_query == ws.idea_text and run.query_origin == "original"
    assert '<b title="' in all_markdown(at)                                   # 긴 검색문은 상태 줄에서 줄이고 전체는 툴팁


def test_landing_field_mode_is_gated_by_capability_in_test_mode():
    at = boot()
    at.segmented_control(key="search_mode").set_value("field").run()
    assert not at.exception
    assert "f_years" not in wkeys(at.multiselect)                            # 분야명 찾기에는 검색 범위가 없다
    msgs = [i.value for i in at.info]
    assert any("분야명 찾기를 제공하지 않습니다" in m or "시험 모드에서는 분야 인덱스" in m for m in msgs), msgs
    assert "fq_land" not in wkeys(at.text_input)                              # 인덱스 없이는 입력칸도 없다


def test_ux_l_landing_has_no_elements_mode():
    at = boot(ux="l")
    opts = at.segmented_control(key="search_mode").options                  # AppTest 는 표시 라벨을 준다
    assert "요소별 탐색" not in opts and "연구 요약 붙여넣기" in opts and "연구분야로 찾기" in opts


def test_one_page_keeps_search_box_and_appends_results():
    """D-038: 검색 뒤에도 띠·머리말·검색 상자가 같은 자리에 남고, 결과는 그 아래에 붙는다. 첫 화면/결과 화면 전환이 없다."""
    at = search(boot(), "제조공정 에너지 최적화")
    md = all_markdown(at)
    assert 'class="rc-band"' in md and "rc-landing" in md                    # 띠·머리말 유지
    assert at.segmented_control(key="search_mode").value == "topic"           # 결과를 만든 관점·검색문이 보이는 탭으로
    assert "persp" in wkeys(at.segmented_control) and "f_years" in wkeys(at.multiselect)   # 검색 상자 안: 관점 행 + 범위 한 줄
    assert "btn_back" not in wkeys(at.button)                                             # 결과가 보이는 동안은 되돌아가기 단추 없음
    assert 'rc-sec">제목이 유사한 과제' in md and 'class="rc-stats"' in md and 'class="rc-foot"' in md
    assert md.index('rc-sec">제목이 유사한 과제') < md.index('class="rc-stats"') < md.index('class="rc-foot"')  # 결과 위, 수치 띠·바닥글 아래
    assert 'rc-h">수록 데이터 구성' not in md and 'rc-h">비교함' in md          # 오른쪽 30% 는 비교함으로 바뀐다 (UX-W) — CSS 주석의 낱말은 무관
    assert len(at.session_state["ws"].search_runs) == 1


def test_logo_returns_to_home_view_without_deleting_and_back_restores():
    """로고(Research Compass) = 기본 화면. 결과·비교함은 숨기기만 하고 지우지 않는다. `이전 결과로 돌아가기` 로 복귀."""
    at = search(boot(), "제조공정 에너지 최적화")
    run = at.session_state["ws"].search_runs[0]
    at.button(key=f"sel_{run.run_id}_{run.results[0].record_id}").click().run()
    at.button(key="btn_home").click().run()
    md = all_markdown(at)
    assert 'rc-sec">제목이 유사한 과제' not in md and 'rc-h">비교함' not in md and 'rc-h">수록 데이터 구성' in md   # 기본 화면 모습
    assert "idea_input" in wkeys(at.text_input) and "persp" not in wkeys(at.segmented_control)                 # 연구주제 칸으로 돌아감
    assert "btn_back" in wkeys(at.button)
    assert len(at.session_state["ws"].search_runs) == 1 and len(at.session_state["ws"].selected) == 1        # 아무것도 지우지 않았다
    at.button(key="btn_back").click().run()
    md = all_markdown(at)
    assert 'rc-sec">제목이 유사한 과제' in md and 'rc-h">비교함' in md and "btn_back" not in wkeys(at.button)
    assert len(at.session_state["ws"].search_runs) == 1                                                       # 재검색 없음


# ---------------------------------------------------------------------------
# D-035 — 연구 작업공간 톤: 비교 절 상태별 표시 · 라벨 · 메모 저장이 마지막 글을 담는지
# ---------------------------------------------------------------------------
def test_comparison_section_is_compact_until_two_selected():
    at = search(boot(), "제조공정 에너지 최적화")
    md = all_markdown(at)
    assert 'rc-compact"><b>선택한 과제 비교</b>' in md and 'rc-sec">선택한 과제 비교' not in md   # 0건: 한 줄만
    assert "비교할 과제를 담아 주세요." in md                                                  # 비교함 빈 상태 문구
    run = at.session_state["ws"].search_runs[0]
    at.button(key=f"sel_{run.run_id}_{run.results[0].record_id}").click().run()
    md = all_markdown(at)
    assert "한 개 더 담으면" in md and 'rc-sec">선택한 과제 비교' not in md                     # 1건: 표 없음
    assert at.session_state["_program_paths"]                                                # 메모용 사업 계층은 1건에도 계산
    at.button(key=f"sel_{run.run_id}_{run.results[1].record_id}").click().run()
    md = all_markdown(at)
    assert 'rc-sec">선택한 과제 비교' in md and "<b>탐색 관점</b>" in md                      # 2건: 표


def test_perspective_and_query_labels_are_visible():
    at = search(boot(), "제조공정 에너지 최적화")
    assert at.segmented_control(key="persp").label == "탐색 관점"
    ws = at.session_state["ws"]
    ti = at.text_input(key=f"query_edit_full_{ws.revision}_0")
    assert ti.label == "현재 검색문"
    assert "직접 수정됨" not in all_markdown(at)
    ti.input("전력 데이터 이상탐지").run()
    assert "직접 수정됨" in all_markdown(at)                                                  # 관점 제안과 다르면 표시
    assert len(at.session_state["ws"].search_runs) == 1                                        # 표시만, 실행 없음


def test_same_project_found_in_two_searches_lists_both_origins():
    """같은 과제가 두 검색에서 발견되면 발견 관점·검색문·당시 순위 행에 ①② 로 둘 다 적힌다."""
    at = search(boot(), "제조공정 에너지 최적화")
    run1 = at.session_state["ws"].search_runs[0]
    for r in run1.results[:2]:
        at.button(key=f"sel_{run1.run_id}_{r.record_id}").click().run()
    ws = at.session_state["ws"]
    at.text_input(key=f"query_edit_full_{ws.revision}_0").input("제조공정 에너지 절감").run()
    at.button(key="btn_run_persp").click().run()
    ws = at.session_state["ws"]
    run2 = ws.search_runs[-1]
    top = run1.results[0]
    again = next(r for r in run2.results if r.record_id == top.record_id)
    assert at.button(key=f"sel_{run2.run_id}_{again.record_id}").disabled                     # 화면은 중복 담기를 막는다 (담김)
    at.session_state["ws"].select(run2.run_id, again.record_id)                                # 출처 추가는 작업공간 규칙 (두 번째 origin)
    at.run()
    ws = at.session_state["ws"]
    assert len(ws.selected) == 2
    assert len(next(s for s in ws.selected if s.record_id == top.record_id).origin_runs) == 2
    md = all_markdown(at)
    assert 'class="rc-ln"><span class="n">1</span>' in md and 'class="rc-ln"><span class="n">2</span>' in md
    assert "“제조공정 에너지 절감”" in md and "(사용자 수정)" not in md.split("# Research Compass 탐색 메모")[0]


def test_memo_download_has_no_blur_instruction_and_uses_deferred_data():
    at = search(boot(), "제조공정 에너지 최적화")
    md = all_markdown(at) + "\n".join(c.value for c in at.caption)
    assert "칸 밖을" not in md and "메모는 현재 브라우저 세션에만 유지" in md
    labels = {b.key: b.label for b in at.download_button}
    assert labels["dl_memo_md"] == "탐색 메모 저장" and labels["dl_memo_json"] == "전체 작업기록 백업"
    at.text_area(key="free_memo").input("마지막에 쓴 글").run()
    assert at.session_state["ws"].user_notes == "마지막에 쓴 글"
