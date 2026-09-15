"""W-T12~T17 — 제목 근거 비교 (v2 §9, §14.4). 합성 제목만 쓴다 (§9.7)."""
from __future__ import annotations

import pytest

from research_compass import comparison as cmp
from research_compass import workspace as wsm

SNAP, DS = "3049029-testsnap", "3049029"


def ref(title: str, rid: str = "r1") -> cmp.TitleRef:
    return cmp.TitleRef(record_id=rid, source_snapshot_id=SNAP, source_dataset_id=DS, title_raw=title)


def el(role: str, text: str) -> wsm.ExplorationElement:
    return wsm.make_element(role, text)


# --- W-T12 원문 표현 발견: 정확한 구절·offset·해시 ------------------------------
def test_literal_match_has_exact_quote_offsets_and_hash():
    r = ref("강화학습을 이용한 추천시스템 분석")
    o = cmp.observe(el("method_approach", "강화학습"), r)
    assert o.finding == "expression_found" and o.origin == "literal_match"
    assert o.review_status == "unreviewed" and o.reviewer_kind == "none"
    q = o.quotes[0]
    assert (q.start_offset, q.end_offset, q.quote) == (0, 4, "강화학습")
    assert r.title_raw[q.start_offset:q.end_offset] == q.quote                  # 검증식
    assert q.source_text_sha256 == cmp.sha256_text(r.title_raw)
    assert q.field_name == "title_raw" and q.source_dataset_id == DS
    assert q.problems(r.title_raw) == []
    assert cmp.validate(o, r.title_raw) == []


def test_offsets_are_codepoints_not_bytes_or_display_width():
    r = ref("𝒜 강화학습 연구")                      # 앞 글자는 서로게이트 쌍 없이 1 코드포인트(비-BMP)
    o = cmp.observe(el("method_approach", "강화학습"), r)
    q = o.quotes[0]
    assert (q.start_offset, q.end_offset) == (2, 6)
    assert r.title_raw[2:6] == "강화학습"


def test_multiple_occurrences_all_quoted():
    r = ref("강화학습, 그리고 강화학습")
    o = cmp.observe(el("method_approach", "강화학습"), r)
    assert [(q.start_offset, q.end_offset) for q in o.quotes] == [(0, 4), (10, 14)]


def test_normalized_match_recovers_raw_span():
    r = ref("ＡＩ 기반  제조공정 최적화")             # 전각 + 이중 공백
    o = cmp.observe(el("target_context", "AI 기반 제조공정"), r)
    assert o.finding == "expression_found" and o.origin == "normalized_match"
    q = o.quotes[0]
    assert r.title_raw[q.start_offset:q.end_offset] == q.quote                  # 원문 구간을 그대로 인용
    assert q.quote == "ＡＩ 기반  제조공정"


def test_normalized_match_that_cannot_be_restored_is_not_quoted():
    # ㈜ → NFKC "(주)" 세 글자. 요소 "(주" 는 정규화 문자열에는 있지만 원문 구간 복원이 안 된다
    r = ref("㈜테스트 기업의 공정")
    spans = cmp.normalized_spans("(주", r.title_raw)
    assert spans == []


# --- W-T13 복합 요소 부분 일치 -------------------------------------------------
def test_partial_word_does_not_confirm_whole_element():
    r = ref("강화학습을 이용한 추천시스템 분석")
    o = cmp.observe(el("goal_question", "에너지 최적화"), r)
    assert o.finding == "needs_review" and o.quotes == ()
    o2 = cmp.observe(el("goal_question", "추천시스템 최적화"), r)           # '추천시스템' 만 있음
    assert o2.finding == "needs_review"
    assert any("부분 단어" in x and "'추천시스템'" in x for x in o2.limitations)
    assert cmp.validate(o2, r.title_raw) == []


def test_spec_example_9_7():
    r = ref("강화학습을 이용한 추천시스템 분석")
    els = [el("method_approach", "강화학습"), el("target_context", "제조공정"), el("goal_question", "에너지 최적화")]
    m = cmp.build_matrix(els, [r])
    assert [o.finding for o in m] == ["expression_found", "needs_review", "needs_review"]
    assert all(o.review_status == "unreviewed" for o in m)


# --- W-T14 부정·비교 문맥 ----------------------------------------------------
def test_negated_title_still_only_expression_found_and_no_usage_claim():
    r = ref("강화학습을 사용하지 않는 추천시스템 분석")
    o = cmp.observe(el("method_approach", "강화학습"), r)
    assert o.finding == "expression_found"
    text = " ".join(o.limitations) + " " + cmp.FINDING_LABELS[o.finding]
    assert "다뤘다는 확인이 아니다" in text
    assert not cmp.contains_forbidden(text)
    assert "사용을 확인했다" not in text


# --- W-T15 표현 미검출 = needs_review, 부재 판정 없음 -----------------------------
def test_not_found_is_needs_review_not_absence():
    r = ref("조선후기 향촌사회 신분 변동")
    o = cmp.observe(el("method_approach", "강화학습"), r)
    assert o.finding == "needs_review" and o.quotes == ()
    assert any("연구 부재·무관함·신규성이 아니다" in x for x in o.limitations)
    with pytest.raises(cmp.EvidenceError):
        cmp.review_confirm(o)                                                    # 인용 없이 확인 불가


# --- W-T16 사용자 확인: 판단 주체 분리, 원문 사실로 승격 없음 -----------------------
def test_user_confirm_records_user_and_keeps_limits():
    r = ref("강화학습을 이용한 추천시스템 분석")
    o = cmp.observe(el("method_approach", "강화학습"), r)
    c = cmp.review_confirm(o, "우리 방법과 같은 계열로 보임")
    assert c.review_status == "confirmed" and c.reviewer_kind == "user"
    assert c.user_interpretation == "우리 방법과 같은 계열로 보임"
    assert c.finding == "expression_found" and c.origin == "literal_match"       # 자동 발견 사실은 그대로
    assert any("연구내용 전체를 검증했다는 뜻이 아니다" in x for x in c.limitations)
    assert c.review_history[-1]["action"] == "confirm"
    assert cmp.is_settled(c, r.title_raw)


def test_user_interpretation_is_not_promoted():
    r = ref("강화학습을 사용하지 않는 추천시스템 분석")
    o = cmp.observe(el("method_approach", "강화학습"), r)
    o2 = cmp.set_interpretation(o, "이 과제는 강화학습을 쓰지 않았다")
    assert o2.finding == o.finding and o2.review_status == "unreviewed"           # 의견만 저장
    assert o2.user_interpretation.startswith("이 과제는")


def test_reject_and_not_confirmed_are_user_only():
    r = ref("강화학습을 이용한 추천시스템 분석")
    o = cmp.observe(el("method_approach", "강화학습"), r)
    rj = cmp.review_reject(o, "여기서 강화학습은 비교 대상일 뿐")
    assert rj.review_status == "rejected" and rj.reviewer_kind == "user" and rj.quotes == o.quotes
    assert not cmp.is_settled(rj, r.title_raw)
    nc = cmp.review_not_confirmed(cmp.observe(el("target_context", "제조공정"), r))
    assert nc.finding == "not_confirmed_in_title" and nc.quotes == () and nc.reviewer_kind == "user"
    assert cmp.validate(nc, r.title_raw) == [] and cmp.is_settled(nc, r.title_raw)
    fake = cmp.EvidenceObservation(**{**nc.__dict__, "reviewer_kind": "none"})
    assert any("사용자 검토로만" in p for p in cmp.validate(fake, r.title_raw))


def test_user_quote_must_match_raw_title_exactly():
    r = ref("강화학습을 이용한 추천시스템 분석")
    o = cmp.observe(el("goal_question", "추천 성능"), r)                          # needs_review
    with pytest.raises(cmp.EvidenceError):
        cmp.review_add_quote(o, r, quote_text="추천 시스템")                      # 공백 다름 → 원문에 없음
    u = cmp.review_add_quote(o, r, quote_text="추천시스템 분석", interpretation="목표와 관련")
    assert u.finding == "expression_found" and u.origin == "user_annotation" and u.reviewer_kind == "user"
    assert u.quotes[0].quote == "추천시스템 분석" and r.title_raw[u.quotes[0].start_offset:u.quotes[0].end_offset] == "추천시스템 분석"
    assert cmp.is_settled(u, r.title_raw)
    with pytest.raises(cmp.EvidenceError):
        cmp.review_add_quote(o, ref("다른 제목", "r9"), quote_text="다른")          # 다른 과제 원문


# --- W-T17 가짜·변경된 인용 → 검증 실패·재검토 ---------------------------------------
def test_tampered_quote_or_changed_title_fails_validation():
    r = ref("강화학습을 이용한 추천시스템 분석")
    o = cmp.review_confirm(cmp.observe(el("method_approach", "강화학습"), r))
    bad_q = cmp.EvidenceQuote(**{**o.quotes[0].__dict__, "quote": "심층강화학습"})
    tampered = cmp.EvidenceObservation(**{**o.__dict__, "quotes": (bad_q,)})
    probs = cmp.validate(tampered, r.title_raw)
    assert any("title_raw[start:end] != quote" in p for p in probs)
    assert not cmp.is_settled(tampered, r.title_raw)
    changed = "강화 학습을 이용한 추천시스템 분석"                                     # 원문 변경
    probs2 = cmp.validate(o, changed)
    assert any("원문 해시" in p for p in probs2)
    assert not cmp.is_settled(o, changed)


def test_merge_keeps_user_review_and_marks_stale_when_element_changes():
    ws = wsm.new_workspace("주제")
    e = ws.add_element(el("method_approach", "강화학습"))
    r = ref("강화학습을 이용한 추천시스템 분석")
    first = cmp.build_matrix(ws.elements, [r])
    reviewed = [cmp.review_confirm(first[0], "관련")]
    again = cmp.build_matrix(ws.elements, [r])
    merged, stale = cmp.merge_reviews(again, reviewed)
    assert merged[0].review_status == "confirmed" and stale == []                 # 같은 revision → 유지
    ws.update_element(e.element_id, "심층강화학습")                                  # revision 2
    third = cmp.build_matrix(ws.elements, [r])
    merged2, stale2 = cmp.merge_reviews(third, reviewed)
    assert merged2[0].review_status == "unreviewed" and merged2[0].observation_id != reviewed[0].observation_id
    assert len(stale2) == 1 and stale2[0].review_status == "stale"               # 이전 확인은 재검토 대상


def test_changed_title_hash_makes_review_stale():
    r = ref("강화학습을 이용한 추천시스템 분석")
    o = cmp.review_confirm(cmp.observe(el("method_approach", "강화학습"), r))
    r2 = ref("강화학습을 이용한 추천시스템 분석 (수정)")                                 # 같은 record_id, 다른 원문
    merged, _ = cmp.merge_reviews(cmp.build_matrix([el("method_approach", "강화학습")], [r2]), [o])
    # observation_id 는 요소 id 가 달라(새 요소) 다르지만, 같은 요소 객체로 재현하면 stale 이 된다
    e = el("method_approach", "강화학습")
    o1 = cmp.review_confirm(cmp.observe(e, r))
    m2, _ = cmp.merge_reviews([cmp.observe(e, r2)], [o1])
    assert m2[0].review_status == "stale"


def test_no_elements_means_no_matrix():
    assert cmp.build_matrix([], [ref("아무 제목")]) == []


def test_model_proposal_cannot_be_auto_confirmed():
    r = ref("강화학습을 이용한 추천시스템 분석")
    o = cmp.observe(el("method_approach", "강화학습"), r)
    mp = cmp.EvidenceObservation(**{**o.__dict__, "origin": "model_proposal", "review_status": "confirmed"})
    assert any("사용자 검토" in p or "model_proposal" in p for p in cmp.validate(mp, r.title_raw))
