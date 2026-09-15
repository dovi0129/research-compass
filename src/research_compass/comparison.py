"""제목 근거 비교 — 표현 발견과 의미 판단의 분리 (명세 v2 §9, §14.4).

비교 단위는 **사용자 탐색 요소 × 선택한 과제** 다. 근거 범위는 제목 한 줄(`title_raw`)뿐이다.

지키는 경계
- `expression_found` 는 "제목에 그 표현이 있다" 이지, 그 연구가 그 방법·대상을 다뤘다는 판정이 아니다 (부정·비교 문맥 가능).
- `needs_review` 는 연구 부재·무관함·신규성이 아니다. 유의어·다른 표기·문맥을 놓칠 수 있다.
- `not_confirmed_in_title` 은 **사용자 검토로만** 생긴다. 부재의 인용문을 만들지 않는다.
- 인용은 `title_raw[start:end] == quote` 로 검증한다. offset 은 0-based Unicode 코드포인트, 끝 미포함.
- 정규화 비교는 원문 위치를 **정확히 복원**할 수 있을 때만 인용으로 만든다. 복원이 안 되면 인용을 만들지 않는다.
- 부분 단어가 있어도 복합 요소 전체가 확인됐다고 표시하지 않는다.
- 사용자의 해석("이 과제는 X를 하지 않았다")은 사용자 메모로만 남기고 시스템 확인 사실로 승격하지 않는다.
- 생성형 모델·유의어 사전을 쓰지 않는다. 문자열 일치를 의미 이해의 정확도로 평가하지 않는다.
"""
from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass, field, replace
from typing import Iterable, Literal

from . import prepare as prep

EVIDENCE_SCOPE = "title_only"
FIELD_NAME = "title_raw"

Finding = Literal["expression_found", "needs_review", "not_confirmed_in_title"]
Origin = Literal["literal_match", "normalized_match", "user_annotation", "model_proposal"]
ReviewStatus = Literal["unreviewed", "confirmed", "rejected", "stale"]
ReviewerKind = Literal["none", "user"]

FINDING_LABELS = {
    "expression_found": "제목에 표현 있음 — 의미는 검토 필요",
    "needs_review": "해당 표현 자동 미검출 — 직접 검토 필요",
    "not_confirmed_in_title": "제목에서 확인되지 않음",
}
REVIEW_LABELS = {"unreviewed": "미검토", "confirmed": "사용자 확인", "rejected": "연결 거부", "stale": "재검토 필요"}
ORIGIN_LABELS = {"literal_match": "자동 발견 (원문 그대로)", "normalized_match": "자동 발견 (표기 정규화)",
                 "user_annotation": "사용자 인용", "model_proposal": "모델 제안"}

# 시스템이 생성하는 문장에 절대 넣지 않는 표현 (v2 §9.6 금지 예시). 시험이 생성 텍스트를 이 목록으로 검사한다.
FORBIDDEN_PHRASES = ("다루지 않았다", "연구된 적이 없다", "독창적이다", "동일 연구다", "사용을 확인했다",
                     "일치하므로 동일", "연구 공백", "선정 가능성")

LIMIT_FOUND = "표현이 제목에 있다는 뜻이며, 그 연구가 해당 방법·대상을 다뤘다는 확인이 아니다 (부정·비교 문맥 가능)"
LIMIT_SCOPE = "근거 범위는 제목 한 줄이다 (초록 없음). 연구내용은 원문 확인이 필요하다"
LIMIT_NOT_FOUND = "자동 미검출은 연구 부재·무관함·신규성이 아니다. 유의어·다른 표기·문맥을 놓칠 수 있다"
LIMIT_USER = "사용자 검토는 제목 표현과 관심 요소의 관계에 대한 의견이다. 연구내용 전체를 검증했다는 뜻이 아니다"


class EvidenceError(ValueError):
    """근거 규칙 위반. UI 는 이 메시지를 그대로 보여줄 수 있다."""


def sha256_text(text: str) -> str:
    """정규화 전 원문을 UTF-8 로 인코딩한 바이트의 SHA-256 (v2 §9.5)."""
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def contains_forbidden(text: str) -> bool:
    return any(p in text for p in FORBIDDEN_PHRASES)


# ---------------------------------------------------------------------------
# §9.5 인용 계약
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TitleRef:
    """비교 대상 과제 (공개 필드만)."""
    record_id: str
    source_snapshot_id: str
    source_dataset_id: str
    title_raw: str

    @property
    def sha256(self) -> str:
        return sha256_text(self.title_raw)


@dataclass(frozen=True)
class EvidenceQuote:
    source_dataset_id: str
    source_snapshot_id: str
    record_id: str
    quote: str
    start_offset: int
    end_offset: int
    source_text_sha256: str
    field_name: str = FIELD_NAME

    def problems(self, title_raw: str) -> list[str]:
        out = []
        if not (0 <= self.start_offset < self.end_offset <= len(title_raw)):
            out.append(f"offset 범위 밖: [{self.start_offset}, {self.end_offset}) / 길이 {len(title_raw)}")
        elif title_raw[self.start_offset:self.end_offset] != self.quote:
            out.append("title_raw[start:end] != quote")
        if sha256_text(title_raw) != self.source_text_sha256:
            out.append("원문 해시 불일치 — 원문이 바뀌었다")
        if self.field_name != FIELD_NAME:
            out.append(f"근거 필드는 {FIELD_NAME} 만 허용")
        return out

    def to_dict(self) -> dict:
        return {"source_dataset_id": self.source_dataset_id, "source_snapshot_id": self.source_snapshot_id,
                "record_id": self.record_id, "field_name": self.field_name, "quote": self.quote,
                "start_offset": self.start_offset, "end_offset": self.end_offset,
                "source_text_sha256": self.source_text_sha256}


def make_quote(ref: TitleRef, start: int, end: int) -> EvidenceQuote:
    s, e = int(start), int(end)
    if not (0 <= s < e <= len(ref.title_raw)):
        raise EvidenceError(f"원문 범위가 잘못됐다: [{s}, {e}) / 길이 {len(ref.title_raw)}")
    return EvidenceQuote(source_dataset_id=ref.source_dataset_id, source_snapshot_id=ref.source_snapshot_id,
                         record_id=ref.record_id, quote=ref.title_raw[s:e], start_offset=s, end_offset=e,
                         source_text_sha256=ref.sha256)


# ---------------------------------------------------------------------------
# §9.3 표현 발견 — 원문 literal match, 그 다음 위치 복원이 가능한 정규화 match
# ---------------------------------------------------------------------------
def literal_spans(needle: str, hay: str) -> list[tuple[int, int]]:
    """겹치지 않는 모든 발견 위치 (코드포인트 인덱스)."""
    if not needle:
        return []
    out, i = [], 0
    while True:
        j = hay.find(needle, i)
        if j < 0:
            return out
        out.append((j, j + len(needle)))
        i = j + len(needle)


def _norm_map(raw: str) -> tuple[str, list[int]]:
    """`prepare.normalize_text` 와 같은 규칙(NFKC·zero-width 제거·공백 축약·양끝 공백 제거)으로 정규화하되,
    정규화 문자마다 **원문 인덱스**를 함께 돌려준다. 원문 위치 복원용."""
    chars: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(raw):
        for c in unicodedata.normalize("NFKC", ch).replace("​", "").replace("﻿", ""):
            chars.append(c)
            idx.append(i)
    out_c: list[str] = []
    out_i: list[int] = []
    for c, i in zip(chars, idx):
        if c.isspace():
            if out_c and out_c[-1] == " ":
                continue
            out_c.append(" ")
            out_i.append(i)
        else:
            out_c.append(c)
            out_i.append(i)
    while out_c and out_c[0] == " ":
        out_c.pop(0)
        out_i.pop(0)
    while out_c and out_c[-1] == " ":
        out_c.pop()
        out_i.pop()
    return "".join(out_c), out_i


def normalized_spans(element_text: str, title_raw: str) -> list[tuple[int, int]]:
    """정규화 비교. 복원한 원문 구간을 다시 정규화해 요소와 같을 때만 인용으로 인정한다 (v2 §9.3)."""
    needle = prep.normalize_text(element_text)
    if not needle:
        return []
    norm, idx = _norm_map(title_raw)
    out = []
    for a, b in literal_spans(needle, norm):
        s, e = idx[a], idx[b - 1] + 1
        if prep.normalize_text(title_raw[s:e]) == needle:
            out.append((s, e))
    return out


# ---------------------------------------------------------------------------
# §14.4 EvidenceObservation
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EvidenceObservation:
    observation_id: str
    record_id: str
    source_snapshot_id: str
    element_id: str
    element_revision: int
    finding: Finding
    origin: Origin
    quotes: tuple[EvidenceQuote, ...]
    review_status: ReviewStatus
    reviewer_kind: ReviewerKind
    user_interpretation: str | None
    limitations: tuple[str, ...]
    title_sha256: str
    element_text: str                     # 표시·메모용 사본. 판정에는 쓰지 않는다
    evidence_scope: str = EVIDENCE_SCOPE
    review_history: tuple[dict, ...] = field(default_factory=tuple)

    def spans(self) -> list[tuple[int, int]]:
        return [(q.start_offset, q.end_offset) for q in self.quotes]

    def to_dict(self) -> dict:
        return {"observation_id": self.observation_id, "record_id": self.record_id,
                "source_snapshot_id": self.source_snapshot_id, "element_id": self.element_id,
                "element_revision": self.element_revision, "evidence_scope": self.evidence_scope,
                "finding": self.finding, "origin": self.origin, "quotes": [q.to_dict() for q in self.quotes],
                "review_status": self.review_status, "reviewer_kind": self.reviewer_kind,
                "user_interpretation": self.user_interpretation, "limitations": list(self.limitations),
                "title_sha256": self.title_sha256, "element_text": self.element_text,
                "review_history": [dict(h) for h in self.review_history]}


def observation_id(element_id: str, element_revision: int, ref: TitleRef) -> str:
    """요소 revision 이 들어가므로 요소를 고치면 다른 관측이 된다 — 이전 확인을 재사용하지 않는다 (v2 §14.4)."""
    key = f"{element_id}|{element_revision}|{ref.source_snapshot_id}|{ref.record_id}"
    return "obs_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def observe(element, ref: TitleRef) -> EvidenceObservation:
    """요소 하나 × 과제 하나의 자동 관측. 결과는 항상 `unreviewed` 다."""
    text = element.text
    spans = literal_spans(text, ref.title_raw)
    origin: Origin = "literal_match"
    if not spans:
        spans = normalized_spans(text, ref.title_raw)
        origin = "normalized_match" if spans else "literal_match"
    limitations = [LIMIT_SCOPE]
    if spans:
        finding: Finding = "expression_found"
        quotes = tuple(make_quote(ref, s, e) for s, e in spans)
        limitations.insert(0, LIMIT_FOUND)
    else:
        finding = "needs_review"
        quotes = ()
        limitations.insert(0, LIMIT_NOT_FOUND)
        partial = [w for w in text.split() if len(w) >= 2 and w in ref.title_raw]
        if partial:
            limitations.append("부분 단어 " + ", ".join(f"'{w}'" for w in partial)
                               + " 는 제목에 있지만 요소 전체 표현이 아니므로 확인으로 표시하지 않는다")
    return EvidenceObservation(
        observation_id=observation_id(element.element_id, element.revision, ref),
        record_id=ref.record_id, source_snapshot_id=ref.source_snapshot_id,
        element_id=element.element_id, element_revision=element.revision,
        finding=finding, origin=origin, quotes=quotes, review_status="unreviewed", reviewer_kind="none",
        user_interpretation=None, limitations=tuple(limitations), title_sha256=ref.sha256, element_text=text)


def build_matrix(elements: Iterable, refs: Iterable[TitleRef]) -> list[EvidenceObservation]:
    """확정된 요소 × 선택 과제. 요소가 없으면 빈 목록 — 자동 분해하지 않는다 (v2 §9.1)."""
    refs = list(refs)
    return [observe(e, r) for e in elements if getattr(e, "confirmed", True) for r in refs]


def merge_reviews(current: list[EvidenceObservation], previous: Iterable[EvidenceObservation]
                  ) -> tuple[list[EvidenceObservation], list[EvidenceObservation]]:
    """자동 관측을 다시 만들 때 사용자 검토를 보존한다.

    - 같은 observation_id(요소 revision 동일) 이고 원문 해시가 같으면 이전 검토를 유지한다.
    - 원문 해시가 다르면 `stale` 로 표시한다.
    - 요소 revision 이 달라진 이전 관측은 현재 행렬에 없다. 사용자 검토가 있었다면 `stale` 목록으로 돌려준다 (v2 §8.3).
    """
    prev_by_id = {p.observation_id: p for p in previous}
    cur_keys = {(o.element_id, o.source_snapshot_id, o.record_id) for o in current}
    merged, stale = [], []
    for o in current:
        p = prev_by_id.get(o.observation_id)
        if p is None:
            merged.append(o)
        elif p.title_sha256 != o.title_sha256:
            merged.append(replace(p, review_status="stale",
                                  limitations=p.limitations + ("원문이 바뀌어 이전 검토를 재사용하지 않는다",)))
        else:
            merged.append(p)
    for p in prev_by_id.values():
        if p.reviewer_kind == "user" and p.observation_id not in {o.observation_id for o in current} \
                and (p.element_id, p.source_snapshot_id, p.record_id) in cur_keys:
            stale.append(replace(p, review_status="stale",
                                 limitations=p.limitations + ("요소가 수정되어 이전 검토는 재검토 대상이다",)))
    return merged, stale


# ---------------------------------------------------------------------------
# §9.4 사용자 검토 — 검토 주체는 항상 user 다
# ---------------------------------------------------------------------------
def _hist(obs: EvidenceObservation, action: str, note: str | None = None) -> tuple[dict, ...]:
    return obs.review_history + ({"action": action, "from": obs.review_status, "note": note},)


def review_confirm(obs: EvidenceObservation, interpretation: str | None = None) -> EvidenceObservation:
    """자동 발견 표현과 관심 요소의 관계를 사용자가 인정한다. 연구내용 검증이 아니다."""
    if obs.finding != "expression_found" or not obs.quotes:
        raise EvidenceError("확인할 인용이 없다. 원문과 정확히 일치하는 구절을 먼저 입력하거나 '제목에서 확인되지 않음' 을 선택한다")
    return replace(obs, review_status="confirmed", reviewer_kind="user",
                   user_interpretation=(interpretation or None),
                   limitations=tuple(dict.fromkeys(obs.limitations + (LIMIT_USER,))),
                   review_history=_hist(obs, "confirm", interpretation))


def review_reject(obs: EvidenceObservation, interpretation: str | None = None) -> EvidenceObservation:
    """잘못된 자동 발견의 의미 연결을 거부한다. 인용은 남기되 확정 메모에 넣지 않는다."""
    return replace(obs, review_status="rejected", reviewer_kind="user",
                   user_interpretation=(interpretation or None), review_history=_hist(obs, "reject", interpretation))


def review_not_confirmed(obs: EvidenceObservation, interpretation: str | None = None) -> EvidenceObservation:
    """제목만으로 해당 요소를 확인하지 못했다고 사용자가 표시한다. 인용을 만들지 않는다 (v2 §14.4)."""
    return replace(obs, finding="not_confirmed_in_title", origin="user_annotation", quotes=(),
                   review_status="confirmed", reviewer_kind="user", user_interpretation=(interpretation or None),
                   limitations=tuple(dict.fromkeys((LIMIT_SCOPE, LIMIT_USER,
                                                    "제목에서 확인되지 않음은 연구 부재·무관함이 아니다"))),
                   review_history=_hist(obs, "not_confirmed", interpretation))


def review_add_quote(obs: EvidenceObservation, ref: TitleRef, quote_text: str | None = None,
                     start: int | None = None, end: int | None = None,
                     interpretation: str | None = None) -> EvidenceObservation:
    """사용자가 근거 구절을 선택(offset)하거나 원문과 **정확히 일치**하는 구절을 입력한다."""
    if ref.record_id != obs.record_id or ref.source_snapshot_id != obs.source_snapshot_id:
        raise EvidenceError("다른 과제의 원문이다")
    if start is None or end is None:
        if not quote_text:
            raise EvidenceError("구절 또는 원문 위치가 필요하다")
        pos = ref.title_raw.find(quote_text)
        if pos < 0:
            raise EvidenceError("입력한 구절이 원문 제목에 그대로 있지 않다. 원문과 정확히 일치하는 구절만 인용할 수 있다")
        start, end = pos, pos + len(quote_text)
    q = make_quote(ref, start, end)
    if quote_text is not None and q.quote != quote_text:
        raise EvidenceError("선택한 범위와 입력한 구절이 다르다")
    quotes = obs.quotes if any(x.start_offset == q.start_offset and x.end_offset == q.end_offset for x in obs.quotes) \
        else obs.quotes + (q,)
    return replace(obs, finding="expression_found", origin="user_annotation", quotes=quotes,
                   review_status="confirmed", reviewer_kind="user", user_interpretation=(interpretation or None),
                   limitations=tuple(dict.fromkeys((LIMIT_FOUND, LIMIT_SCOPE, LIMIT_USER))),
                   review_history=_hist(obs, "add_quote", q.quote))


def set_interpretation(obs: EvidenceObservation, interpretation: str | None) -> EvidenceObservation:
    """사용자 해석 메모. 시스템 확인 사실로 승격하지 않는다 — finding·status 는 바꾸지 않는다."""
    return replace(obs, user_interpretation=(interpretation or None))


# ---------------------------------------------------------------------------
# §14.4 검증 규칙
# ---------------------------------------------------------------------------
def validate(obs: EvidenceObservation, title_raw: str | None) -> list[str]:
    problems = []
    if title_raw is None:
        problems.append("원문 제목을 찾을 수 없어 인용을 검증하지 못했다")
        return problems
    if sha256_text(title_raw) != obs.title_sha256:
        problems.append("원문 해시가 관측 시점과 다르다 — 재검토 필요")
    if obs.finding == "expression_found":
        valid = [q for q in obs.quotes if not q.problems(title_raw)]
        if not valid:
            problems.append("expression_found 에는 유효한 원문 인용이 최소 하나 필요하다")
        for q in obs.quotes:
            problems.extend(f"인용 '{q.quote}': {p}" for p in q.problems(title_raw))
    if obs.finding == "not_confirmed_in_title":
        if obs.reviewer_kind != "user":
            problems.append("not_confirmed_in_title 은 사용자 검토로만 생성한다")
        if obs.quotes:
            problems.append("부재의 인용문을 만들지 않는다")
    if obs.origin == "model_proposal" and obs.review_status == "confirmed" and obs.reviewer_kind != "user":
        problems.append("model_proposal 은 자동 confirmed 가 될 수 없다")
    if obs.review_status == "confirmed" and obs.reviewer_kind != "user":
        problems.append("confirmed 는 사용자 검토가 있어야 한다")
    if obs.evidence_scope != EVIDENCE_SCOPE:
        problems.append("근거 범위는 title_only 만 허용")
    return problems


def is_settled(obs: EvidenceObservation, title_raw: str | None) -> bool:
    """확정 메모 영역에 들어갈 수 있는가: 사용자 검토가 있고, 인용이 유효하고, stale 이 아닌 것."""
    return (obs.reviewer_kind == "user" and obs.review_status == "confirmed"
            and not validate(obs, title_raw))
