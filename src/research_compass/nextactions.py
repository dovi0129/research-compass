"""다음 탐색·확인 — 규칙 템플릿 (명세 v2 §10, §14.5).

연구기회·저빈도 분야 판정과 구분한다. 기회점수·성공 가능성 순위가 아니다.

지키는 경계
- 사용자가 입력·확인한 요소, 선택한 과제, 비교표 상태**만** 근거로 쓴다. 입력에 없는 주제를 추천하지 않는다.
- 최대 3개, 정해진 규칙 순서. 근거가 부족하면 억지로 채우지 않는다.
- 새 검색은 사용자가 확인한 뒤에만 실행한다 — 여기서는 검색문을 **제안**만 한다.
- 상세 원문 연결이 없으므로 '상세 자료 확인 필요' 작업만 만든다. 자료를 가져온 것처럼 쓰지 않는다.
- 사용자가 제안을 수정하면 `user_edited` 와 이력을 남긴다.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from typing import Iterable, Literal

from . import workspace as wsm
from .comparison import EvidenceObservation, contains_forbidden

Kind = Literal["change_perspective", "edit_query", "inspect_project_detail", "explore_field"]
KIND_LABELS = {"change_perspective": "다른 관점으로 탐색", "edit_query": "검색문 수정",
               "inspect_project_detail": "상세 자료에서 확인", "explore_field": "분야명으로 탐색"}
MAX_ITEMS = 3


class NextActionError(ValueError):
    pass


@dataclass(frozen=True)
class NextAction:
    action_id: str
    kind: Kind
    text: str
    proposed_query: str | None
    basis_element_ids: tuple[str, ...] = ()
    basis_record_ids: tuple[str, ...] = ()
    basis_field_record_ids: tuple[str, ...] = ()
    basis_observation_ids: tuple[str, ...] = ()
    origin: Literal["rule_template", "user_edited"] = "rule_template"
    confirmed: bool = False
    history: tuple[dict, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"action_id": self.action_id, "kind": self.kind, "text": self.text,
                "proposed_query": self.proposed_query,
                "basis_element_ids": list(self.basis_element_ids), "basis_record_ids": list(self.basis_record_ids),
                "basis_field_record_ids": list(self.basis_field_record_ids),
                "basis_observation_ids": list(self.basis_observation_ids),
                "origin": self.origin, "confirmed": self.confirmed, "history": [dict(h) for h in self.history]}


def _aid(kind: str, *parts: str) -> str:
    return "act_" + hashlib.sha256("|".join((kind,) + tuple(parts)).encode("utf-8")).hexdigest()[:12]


def _unresolved(obs: EvidenceObservation) -> bool:
    """제목에서 요소를 확인하지 못한 상태 — 사용자 확인이 없는 모든 경우."""
    if obs.review_status == "stale":
        return True
    if obs.finding == "not_confirmed_in_title":
        return True
    if obs.finding == "needs_review":
        return True
    return obs.review_status == "rejected"        # 자동 발견을 사용자가 거부 → 여전히 미확인


def propose(ws: wsm.Workspace, observations: Iterable[EvidenceObservation],
            plans: dict[str, wsm.QueryPlan] | None = None, *, insufficient: bool = False,
            field_selections: Iterable[dict] = (), max_items: int = MAX_ITEMS) -> list[NextAction]:
    """§10.2 규칙 순서대로 제안한다. 근거가 없으면 빈 목록."""
    out: list[NextAction] = []
    obs = list(observations)
    plans = plans or wsm.available_perspectives(ws.idea_text, ws.elements)
    el_by_id = {e.element_id: e for e in ws.elements}

    # 규칙 1 — 제목에서 확인하지 못한 요소 → 선택 과제의 연구목표·요약에서 확인 (요소별로 묶는다)
    for role in wsm.ROLES:
        for e in [x for x in ws.elements if x.role == role]:
            hit = [o for o in obs if o.element_id == e.element_id and _unresolved(o)]
            if not hit:
                continue
            recs = tuple(dict.fromkeys(o.record_id for o in hit))
            out.append(NextAction(
                action_id=_aid("inspect_project_detail", e.element_id, str(e.revision), *recs),
                kind="inspect_project_detail",
                text=f"선택한 과제 {len(recs)}건의 연구목표·요약에서 '{e.text}' 관련 내용을 확인한다 — 제목만으로는 확인되지 않았다 (상세 자료 확인 필요)",
                proposed_query=None, basis_element_ids=(e.element_id,), basis_record_ids=recs,
                basis_observation_ids=tuple(o.observation_id for o in hit)))

    # 규칙 2·3 — 요소 기반 관점 중 한쪽만 탐색했고 다른 쪽 요소가 있음
    ran = {r.perspective for r in ws.search_runs if r.idea_revision == ws.idea_revision} - {"full"}
    if ran == {"method"} and plans.get("target_goal") is not None and plans["target_goal"].available:
        p = plans["target_goal"]
        out.append(NextAction(action_id=_aid("change_perspective", "target_goal", p.effective_query),
                              kind="change_perspective",
                              text="대상·문제 중심 검색문을 미리 보고 확인 후 탐색한다",
                              proposed_query=p.effective_query, basis_element_ids=tuple(p.used_element_ids)))
    elif ran == {"target_goal"} and plans.get("method") is not None and plans["method"].available:
        p = plans["method"]
        out.append(NextAction(action_id=_aid("change_perspective", "method", p.effective_query),
                              kind="change_perspective",
                              text="방법·접근 중심 검색문을 미리 보고 확인 후 탐색한다",
                              proposed_query=p.effective_query, basis_element_ids=tuple(p.used_element_ids)))

    # 규칙 4 — 사용자가 현재 결과가 충분하지 않다고 표시
    latest = ws.latest_run()
    if insufficient and latest is not None:
        out.append(NextAction(action_id=_aid("edit_query", latest.run_id),
                              kind="edit_query",
                              text="현재 검색문을 더 넓게 또는 다르게 고쳐 다시 탐색한다 (사용자가 결과가 충분하지 않다고 표시)",
                              proposed_query=latest.effective_query, basis_element_ids=tuple(latest.used_element_ids)))

    # 규칙 5 — 사용자가 D2 분야명을 선택함
    for fs in field_selections:
        name = str(fs.get("field_name", "")).strip()
        if not name:
            continue
        out.append(NextAction(action_id=_aid("explore_field", str(fs.get("field_record_id", "")), name),
                              kind="explore_field",
                              text=f"선택한 분야명 '{name}' 으로 별도 검색문을 작성해 확인 후 탐색한다 (분야 배정이 아니다)",
                              proposed_query=name,
                              basis_field_record_ids=(str(fs.get("field_record_id", "")),)))

    # 규칙 6 — 억지로 채우지 않는다
    out = out[:max_items]
    for a in out:
        assert not contains_forbidden(a.text), a.text
    return out


def user_edit(action: NextAction, text: str | None = None, proposed_query: str | None = None) -> NextAction:
    """사용자 수정. 이력과 user_edited 를 남긴다 (v2 §10.3)."""
    t = (text or action.text).strip()
    if not t:
        raise NextActionError("작업 설명이 비어 있다")
    q = action.proposed_query if proposed_query is None else (proposed_query.strip() or None)
    return replace(action, text=t, proposed_query=q, origin="user_edited", confirmed=False,
                   history=action.history + ({"action": "edit", "text": action.text, "proposed_query": action.proposed_query},))


def confirm(action: NextAction) -> NextAction:
    """사용자 확인. 확인된 작업만 메모의 '다음 탐색·확인' 확정 영역에 들어간다."""
    return replace(action, confirmed=True, history=action.history + ({"action": "confirm"},))
