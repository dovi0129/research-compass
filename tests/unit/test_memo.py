"""W-T19·T20·T27 — 탐색 메모 무결성 (v2 §11)."""
from __future__ import annotations

import json

import pytest

from fake_engine import build_engine
from research_compass import comparison as cmp
from research_compass import memo
from research_compass import nextactions as na
from research_compass import search as svc
from research_compass import workspace as wsm


def scenario(select=True, elements=True):
    eng = build_engine()
    ws = wsm.new_workspace("강화학습 기반 제조공정 에너지 최적화", run_mode="test_fixture")
    if elements:
        ws.add_element(wsm.make_element("method_approach", "강화학습"))
        ws.add_element(wsm.make_element("goal_question", "에너지 최적화"))
    plan = wsm.build_effective_query(ws.idea_text, ws.elements, "full")
    run = wsm.run_perspective_search(ws, plan, eng, eng.cfg, svc.search, svc.SearchRequest, top_k=5)
    if select:
        ws.select(run.run_id, run.results[0].record_id, "가장 가까운 제목")
        ws.select(run.run_id, run.results[1].record_id)
    refs = [cmp.TitleRef(record_id=s.record_id, source_snapshot_id=s.source_snapshot_id, source_dataset_id="3049029",
                         title_raw=s.project_record.title_raw) for s in ws.selected]
    obs = cmp.build_matrix(ws.elements, refs)
    return ws, refs, obs


def test_no_selection_memo_is_allowed_and_honest():
    ws, _, obs = scenario(select=False)
    res = memo.build(wsm.snapshot(ws), obs, [])
    assert memo.NO_SELECTION_NOTE in res.markdown
    assert "## 참고 후보로 선택한 과제" in res.markdown and "## 근거 부록" in res.markdown
    assert "[E1]" not in res.markdown                                            # 가짜 근거 없음
    assert res.problems == []
    assert not memo.has_trend_language(res)


def test_unreviewed_auto_matches_stay_out_of_settled_section():
    ws, refs, obs = scenario()
    res = memo.build(wsm.snapshot(ws), obs, [])
    md = res.markdown
    settled = md.split("## 제목에서 확인한 표현과 검토 내용")[1].split("## 아직 확인하지 못한 사항")[0]
    pending = md.split("## 아직 확인하지 못한 사항")[1].split("## 다음 탐색·확인")[0]
    assert "검토를 마친 항목이 없습니다" in settled
    assert "자동 발견 표현 — 사용자 검토 전" in pending and "직접 검토 필요" in pending
    assert "“강화학습”" in pending                                                 # 자동 발견 구절은 미검토 영역에만


def test_confirmed_review_appears_with_quote_and_user_opinion_separately():
    ws, refs, obs = scenario()
    found = next(o for o in obs if o.finding == "expression_found")
    reviewed = [cmp.review_confirm(found, "우리 방법과 같은 계열") if o is found else o for o in obs]
    res = memo.build(wsm.snapshot(ws), reviewed, [])
    settled = res.markdown.split("## 제목에서 확인한 표현과 검토 내용")[1].split("## 아직 확인하지 못한 사항")[0]
    assert "→ 사용자 확인" in settled and "“강화학습” (0–4)" in settled
    assert "우리 방법과 같은 계열" in settled                                          # 사용자 의견은 별도 열
    assert "[E1]" in settled


def test_rejected_and_not_confirmed_are_separated():
    ws, refs, obs = scenario()
    found = next(o for o in obs if o.finding == "expression_found")
    missing = next(o for o in obs if o.finding == "needs_review")
    reviewed = []
    for o in obs:
        if o is found:
            reviewed.append(cmp.review_reject(o, "비교 대상으로 언급"))
        elif o is missing:
            reviewed.append(cmp.review_not_confirmed(o))
        else:
            reviewed.append(o)
    res = memo.build(wsm.snapshot(ws), reviewed, [])
    md = res.markdown
    settled = md.split("## 제목에서 확인한 표현과 검토 내용")[1].split("## 아직 확인하지 못한 사항")[0]
    pending = md.split("## 아직 확인하지 못한 사항")[1].split("## 다음 탐색·확인")[0]
    assert "제목에서 확인되지 않음 (사용자 검토)" in settled
    assert "의미 연결을 거부함" in pending


def test_tampered_quote_is_excluded_with_reason():
    ws, refs, obs = scenario()
    found = next(o for o in obs if o.finding == "expression_found")
    c = cmp.review_confirm(found)
    bad = cmp.EvidenceObservation(**{**c.__dict__, "quotes": (cmp.EvidenceQuote(**{**c.quotes[0].__dict__, "quote": "심층강화학습"}),)})
    res = memo.build(wsm.snapshot(ws), [bad], [])
    assert res.problems and "title_raw[start:end] != quote" in res.problems[0]
    assert "인용 검증 실패" in res.markdown
    assert "심층강화학습" not in res.markdown.split("## 제목에서 확인한 표현과 검토 내용")[1].split("## 아직")[0]
    assert res.data["settled_observation_ids"] == []


def test_stale_observation_excluded_with_reason():
    ws, refs, obs = scenario()
    found = next(o for o in obs if o.finding == "expression_found")
    stale = cmp.EvidenceObservation(**{**cmp.review_confirm(found).__dict__, "review_status": "stale"})
    res = memo.build(wsm.snapshot(ws), [stale], [])
    assert "재검토 필요" in res.markdown
    assert res.data["settled_observation_ids"] == []


def test_memo_matches_snapshot_facts_and_is_deterministic():
    ws, refs, obs = scenario()
    acts = na.propose(ws, obs)
    snap = wsm.snapshot(ws)
    r1 = memo.build(snap, obs, acts, generated_at="2026-09-09T00:00:00Z")
    r2 = memo.build(snap, obs, acts, generated_at="2026-09-09T00:00:00Z")
    assert r1.markdown == r2.markdown and r1.data["markdown_sha256"] == r2.data["markdown_sha256"]
    run = ws.search_runs[0]
    assert run.effective_query in r1.markdown                                      # 실제 검색문
    assert run.actual_engine in r1.markdown and run.run_id in r1.markdown           # 엔진·실행 ID
    for s in ws.selected:
        assert s.project_record.title_raw in r1.markdown or memo.md_escape(s.project_record.title_raw) in r1.markdown
        assert s.record_id in r1.markdown
    assert "가장 가까운 제목" in r1.markdown                                           # 사용자 선택 이유 열
    assert "test_fixture" in r1.markdown                                            # 모드 구분 (W-T26)
    assert "공식 과제번호가 아닙니다" in r1.markdown
    data = json.loads(memo.to_json(r1))
    assert data["schema_version"] == "memo/1.0" and data["workspace"]["workspace_id"] == ws.workspace_id
    assert len(data["observations"]) == len(obs) and len(data["next_actions"]) == len(acts)


def test_next_actions_confirmed_vs_proposed():
    ws, refs, obs = scenario()
    acts = na.propose(ws, obs)
    assert acts
    acts2 = [na.confirm(acts[0])] + acts[1:]
    md = memo.build(wsm.snapshot(ws), obs, acts2).markdown.split("## 다음 탐색·확인")[1].split("## 범위와 제한")[0]
    assert "**확인함**" in md
    if len(acts2) > 1:
        assert "제안 (미확인)" in md


def test_markdown_escaping_blocks_html_and_table_breaks():
    ws, refs, obs = scenario(select=False)
    ws.idea_text = "<script>alert(1)</script> | 제조공정 *에너지*"
    res = memo.build(wsm.snapshot(ws), [], [])
    assert "<script>" not in res.markdown and "\\<script\\>" in res.markdown
    assert "\\|" in res.markdown and "\\*에너지\\*" in res.markdown


def test_no_forbidden_or_trend_language_and_no_local_paths():
    ws, refs, obs = scenario()
    res = memo.build(wsm.snapshot(ws), obs, na.propose(ws, obs), source_url="https://www.data.go.kr/data/3049029/fileData.do")
    assert not cmp.contains_forbidden("\n".join(x for x in res.markdown.splitlines() if not x.startswith("|")))
    assert not memo.has_trend_language(res)
    assert "https://www.data.go.kr" in res.markdown
    assert memo.safe_url("javascript:alert(1)") is None and memo.safe_url("http://x") is None
    for bad in ("C:\\", "/home/", "연구책임자", "연구자번호"):
        assert bad not in res.markdown and bad not in memo.to_json(res)


def test_no_elements_memo_explains_no_comparison():
    ws, refs, obs = scenario(elements=False)
    assert obs == []
    res = memo.build(wsm.snapshot(ws), obs, [])
    assert "탐색 요소를 입력하지 않아 제목 표현 비교는 하지 않았습니다" in res.markdown


def test_free_memo_keeps_user_text_verbatim_and_adds_no_claims():
    """자유 메모는 사용자가 쓴 글만 담는다 (v2 §17.6 — UX-L·UX-W 공통 기록 수단)."""
    body = "1) 노인 우울 관련 3건 담음\n- 확인 못 한 것: 대상 연령대\n"
    out = memo.free_memo(body, idea_text="노인 우울증 예방 디지털 치료제",
                         generated_at="2026-09-09T00:00:00+00:00")
    assert out.startswith(memo.FREE_MEMO_TITLE)
    assert body in out                                   # 요약·해석·escape 없이 그대로
    assert "2026-09-09T00:00:00+00:00" in out and "노인 우울증 예방 디지털 치료제" in out
    head = out.split("---", 1)[0]
    for bad in cmp.FORBIDDEN_PHRASES:
        assert bad not in head                           # 머리말이 판정 문구를 만들지 않는다
    assert out == memo.free_memo(body, idea_text="노인 우울증 예방 디지털 치료제",
                                 generated_at="2026-09-09T00:00:00+00:00")


def test_free_memo_without_input_has_no_fabricated_body():
    out = memo.free_memo("", generated_at="2026-09-09T00:00:00+00:00")
    assert out.split("---", 1)[1].strip() == ""           # 본문을 지어내지 않는다
    assert "연구주제" not in out                            # 없는 값은 줄 자체를 넣지 않는다


def test_free_memo_escapes_idea_line_only():
    out = memo.free_memo("*본문 강조*", idea_text="a|b *c*", generated_at="t")
    assert "a\\|b \\*c\\*" in out                          # 머리말은 표·서식 깨짐 방지로 escape
    assert "*본문 강조*" in out                              # 본문은 사용자 파일이므로 그대로


def test_user_notes_section_is_verbatim_and_not_template_checked():
    """자유 메모는 '사용자 자유 메모' 절에 그대로 들어가고, 사용자 글의 표현은 템플릿 금지어 검사 대상이 아니다 (D-029)."""
    ws = wsm.new_workspace("제조공정 에너지 최적화", run_mode="test_fixture")
    ws.user_notes = "첫 후보는 우리 방법을 다루지 않았다 고 생각함 — 원문 확인 필요\n둘째 줄"
    res = memo.build(wsm.snapshot(ws), [], [])
    assert "## 사용자 자유 메모" in res.markdown and "둘째 줄" in res.markdown
    assert memo.USER_NOTES_SCOPE in res.markdown
    assert res.markdown.index("## 다음 탐색·확인") < res.markdown.index("## 사용자 자유 메모") < res.markdown.index("## 범위와 제한")
    ws.user_notes = None
    assert "작성한 자유 메모가 없습니다." in memo.build(wsm.snapshot(ws), [], []).markdown


URL = "https://www.data.go.kr/data/3049029/fileData.do"


def test_brief_memo_has_only_selected_runs_and_notes():
    """D-033 압축 메모: 선택한 과제(원본 링크·행) · 탐색 기록 · 사용자 메모만. 결정적이고 금지 표현이 없다."""
    ws, refs, obs = scenario()
    ws.user_notes = "첫 후보를 먼저 원문에서 확인"
    snap = wsm.snapshot(ws, capabilities={}, observations=[], next_actions=[])
    md = memo.build_brief(snap, generated_at="2026-09-10T00:00:00+00:00", source_url=URL)
    assert md.startswith(memo.BRIEF_TITLE)
    assert "## 선택한 과제" in md and "### E1." in md and "### E2." in md
    assert f"[원본 데이터 페이지]({URL})" in md and "원본 행" in md
    assert "## 탐색 기록" in md and "결과 5건" in md and "1위 " in md
    assert "## 메모" in md and "첫 후보를 먼저 원문에서 확인" in md
    for gone in ("## 근거 부록", "## 범위와 제한", "## 다음 탐색·확인", "## 탐색한 관점", "## 제목에서 확인한 표현", "## 아직 확인하지 못한 사항"):
        assert gone not in md, gone
    assert md == memo.build_brief(snap, generated_at="2026-09-10T00:00:00+00:00", source_url=URL)   # 결정적
    for bad in cmp.FORBIDDEN_PHRASES:
        assert bad not in md, bad
    assert not memo.has_trend_language(memo.MemoResult(markdown=md, data={}))


def test_brief_memo_without_selection_or_notes_is_honest():
    ws, refs, obs = scenario(select=False)
    snap = wsm.snapshot(ws, capabilities={}, observations=[], next_actions=[])
    md = memo.build_brief(snap, source_url="http://insecure.example")      # https 아니면 링크를 만들지 않는다
    assert memo.NO_SELECTION_NOTE in md and "### E1." not in md
    assert "작성한 메모가 없습니다." in md and "insecure.example" not in md

