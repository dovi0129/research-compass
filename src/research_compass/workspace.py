"""탐색 작업공간 — 요소·관점·검색 실행·선택 (명세 v2 §6~§8, §14).

UI 는 상태 입력·표시만 하고, 규칙은 여기의 테스트 가능한 함수에서 수행한다 (v2 §15.3).

지키는 경계
- 입력하지 않은 탐색 요소를 규칙·LLM 이 임의로 보완하지 않는다 (v2 §6.2).
- 관점 선택만으로 모든 관점을 자동 실행하지 않는다. 한 번에 한 관점만 (v2 §6.5).
- 관점별 결과를 RRF·점수 평균으로 자동 통합하지 않는다 (v2 §6.5).
- 서로 다른 질의의 원시 점수를 같은 축에서 비교해 우열을 매기지 않는다 (v2 §6.5).
- 작업공간은 메모리에만 있다. 자동 파일·DB 저장을 하지 않는다 (v2 §8.4).
"""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field, replace
from typing import Literal

from . import prepare as prep

SCHEMA_VERSION = "workspace/2.0"

Role = Literal["target_context", "method_approach", "goal_question"]
ROLES: tuple[Role, ...] = ("target_context", "method_approach", "goal_question")
ROLE_LABELS = {"target_context": "대상·맥락",
               "method_approach": "방법·접근",
               "goal_question": "목표·질문"}

Perspective = Literal["full", "method", "target_goal"]
PERSPECTIVES: tuple[Perspective, ...] = ("full", "method", "target_goal")
PERSPECTIVE_LABELS = {"full": "전체 주제로 탐색",
                      "method": "방법·접근 중심으로 탐색",
                      "target_goal": "대상·문제 중심으로 탐색"}

Origin = Literal["user_entered", "selected_from_idea", "model_proposed"]
QueryOrigin = Literal["original", "elements_joined", "user_edited"]
RunMode = Literal["local_live", "saved_replay", "test_fixture"]

MAX_ELEMENTS = 3
MAX_SELECTED = 5


class WorkspaceError(ValueError):
    """작업공간 규칙 위반. UI 는 이 메시지를 사용자에게 그대로 보여줄 수 있다."""


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# §14.1 ExplorationElement
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class IdeaSpan:
    start: int
    end: int
    quote: str


@dataclass(frozen=True)
class ExplorationElement:
    element_id: str
    role: Role
    text: str
    origin: Origin
    confirmed: bool = False
    idea_span: IdeaSpan | None = None
    revision: int = 1


def make_element(role: str, text: str, origin: str = "user_entered",
                 idea_text: str | None = None, span: tuple[int, int] | None = None,
                 confirmed: bool = True) -> ExplorationElement:
    """탐색 요소 하나를 만든다.

    `origin=selected_from_idea` 면 원문 범위를 함께 저장하고 **원문과 일치하는지 검증**한다.
    원래 아이디어에 없던 입력을 `selected_from_idea` 로 위장할 수 없다 (v2 §14.1).
    `model_proposed` 는 기본 구현에서 만들지 않는다 (v2 §6.2).
    """
    if role not in ROLES:
        raise WorkspaceError(f"알 수 없는 요소 종류: {role!r} — {ROLES} 중 하나")
    t = prep.normalize_text(text)
    if not t:
        raise WorkspaceError(f"{ROLE_LABELS[role]} 이 비어 있습니다")
    if origin == "model_proposed":
        raise WorkspaceError("model_proposed 요소는 기본 구현에서 생성하지 않는다 (v2 §6.2·§18.1)")
    if origin not in ("user_entered", "selected_from_idea"):
        raise WorkspaceError(f"알 수 없는 origin: {origin!r}")

    ispan = None
    if origin == "selected_from_idea":
        if idea_text is None or span is None:
            raise WorkspaceError("원문 선택 요소는 idea_text 와 span 이 필요하다")
        s, e = int(span[0]), int(span[1])
        if not (0 <= s < e <= len(idea_text)):
            raise WorkspaceError(f"원문 범위가 잘못됐다: [{s}, {e}) / 길이 {len(idea_text)}")
        quote = idea_text[s:e]
        if prep.normalize_text(quote) != t:
            raise WorkspaceError(
                f"선택한 원문 범위와 요소 텍스트가 다르다: 원문 {quote!r} vs 요소 {text!r}")
        ispan = IdeaSpan(start=s, end=e, quote=quote)
    return ExplorationElement(element_id=_new_id("el"), role=role, text=t,   # type: ignore[arg-type]
                              origin=origin, confirmed=bool(confirmed), idea_span=ispan)


# ---------------------------------------------------------------------------
# §6.3 관점과 기본 검색문
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class QueryPlan:
    perspective: Perspective
    effective_query: str
    query_origin: QueryOrigin
    used_element_ids: tuple[str, ...]
    available: bool
    reason: str = ""


def _by_role(elements: list[ExplorationElement]) -> dict[str, list[ExplorationElement]]:
    out: dict[str, list[ExplorationElement]] = {r: [] for r in ROLES}
    for e in elements:
        if e.confirmed:
            out[e.role].append(e)
    return out


def build_effective_query(idea_text: str, elements: list[ExplorationElement],
                          perspective: str, user_override: str | None = None) -> QueryPlan:
    """관점별 실제 검색문. 요소를 **순서대로 연결**하는 수준이다.

    새 기술 용어·유의어·제약을 자동 추가하지 않는다 (v2 §6.3).
    입력이 부족하면 `available=False` 와 사유를 돌려준다 — 원래 주제 검색은 계속 가능하다 (v2 §6.5).
    """
    if perspective not in PERSPECTIVES:
        raise WorkspaceError(f"알 수 없는 관점: {perspective!r} — {PERSPECTIVES} 중 하나")
    by = _by_role(elements)

    def joined(roles: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
        parts, ids = [], []
        for r in roles:
            for e in by[r]:
                parts.append(e.text)
                ids.append(e.element_id)
        return prep.normalize_text(" ".join(parts)), tuple(ids)

    if perspective == "full":
        q, ids, origin = prep.normalize_text(idea_text), (), "original"
        if not q:
            return QueryPlan("full", "", "original", (), False, "연구주제가 비어 있습니다")
    elif perspective == "method":
        if not by["method_approach"]:
            return QueryPlan("method", "", "elements_joined", (), False,
                             f"{ROLE_LABELS['method_approach']} 요소를 입력하면 이 관점으로 탐색할 수 있습니다")
        q, ids = joined(("method_approach", "goal_question"))
        origin = "elements_joined"
    else:  # target_goal
        if not (by["target_context"] or by["goal_question"]):
            return QueryPlan("target_goal", "", "elements_joined", (), False,
                             f"{ROLE_LABELS['target_context']} 또는 "
                             f"{ROLE_LABELS['goal_question']} 요소가 하나 이상 필요합니다")
        q, ids = joined(("target_context", "goal_question"))
        origin = "elements_joined"

    if user_override is not None:
        edited = prep.normalize_text(user_override)
        if not edited:
            raise WorkspaceError("수정한 검색문이 비어 있습니다")
        # 사용자가 손대면 요소 연결이 아니라 사용자 검색문이다. 근거 요소 표시는 유지한다.
        return QueryPlan(perspective, edited, "user_edited", ids, True)   # type: ignore[arg-type]
    return QueryPlan(perspective, q, origin, ids, True)                   # type: ignore[arg-type]


def available_perspectives(idea_text: str, elements: list[ExplorationElement]
                           ) -> dict[str, QueryPlan]:
    """관점별 실행 가능 여부와 기본 검색문. **실행하지 않는다** — 미리보기용 (v2 §6.5)."""
    return {p: build_effective_query(idea_text, elements, p) for p in PERSPECTIVES}


# ---------------------------------------------------------------------------
# §14.2 SearchRun / §14.3 SelectedProject
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ResultRow:
    """화면·메모가 쓰는 안전한 공개 필드만. 개인식별 컬럼은 담지 않는다 (v2 §4.1)."""
    rank: int
    record_id: str
    source_snapshot_id: str
    source_row: int
    title_raw: str
    institution: str
    selection_year: int | None
    program: str
    short_title: bool
    semantic_score: float
    percentile_label: str
    rerank_score: float | None
    relevance_gate: str
    semantic_percentile: float | None = None   # 0~1. 화면 위치 표시용. 관련성·확률 아님
    source_dataset_id: str = ""                # 인용 계약(v2 §9.5)용. 스냅샷 ID 앞부분과 같다


@dataclass(frozen=True)
class SearchRun:
    run_id: str
    workspace_id: str
    idea_revision: int
    perspective: Perspective
    original_query: str
    effective_query: str
    query_origin: QueryOrigin
    used_element_ids: tuple[str, ...]
    filters: dict
    requested_engine: str
    actual_engine: str
    engine_config_id: str
    model_manifest_ids: tuple[str, ...]
    index_manifest_id: str
    source_snapshot_ids: tuple[str, ...]
    results: tuple[ResultRow, ...]
    warnings: tuple[str, ...]
    latency_ms: dict
    run_mode: RunMode
    rerank_applied: bool
    rerank_badge: str | None
    relevance: dict


@dataclass(frozen=True)
class SelectedProject:
    record_id: str
    source_snapshot_id: str
    project_record: ResultRow
    origin_runs: tuple[dict, ...]          # {run_id, perspective, rank}
    selection_order: int
    user_reason: str | None = None
    outside_current_filter: bool = False


# ---------------------------------------------------------------------------
# §14.6 WorkspaceSnapshot
# ---------------------------------------------------------------------------
@dataclass
class Workspace:
    workspace_id: str
    idea_text: str
    idea_revision: int = 1
    revision: int = 1
    elements: list[ExplorationElement] = field(default_factory=list)
    search_runs: list[SearchRun] = field(default_factory=list)
    selected: list[SelectedProject] = field(default_factory=list)
    user_notes: str | None = None
    run_mode: RunMode = "local_live"

    # --- 요소 -----------------------------------------------------------
    def add_element(self, element: ExplorationElement) -> ExplorationElement:
        if len([e for e in self.elements if e.role == element.role]) >= 1:
            raise WorkspaceError(
                f"{ROLE_LABELS[element.role]} 요소는 하나만 둡니다. 기존 요소를 수정하세요")
        if len(self.elements) >= MAX_ELEMENTS:
            raise WorkspaceError(f"탐색 요소는 최대 {MAX_ELEMENTS}개입니다")
        self.elements.append(element)
        self.revision += 1
        return element

    def update_element(self, element_id: str, text: str) -> ExplorationElement:
        """요소를 고치면 revision 이 올라간다. 이전 근거 판단은 `stale` 이 된다 (v2 §8.3)."""
        for i, e in enumerate(self.elements):
            if e.element_id == element_id:
                t = prep.normalize_text(text)
                if not t:
                    raise WorkspaceError("요소 텍스트가 비어 있습니다")
                # 원문 선택이었더라도 손으로 고치면 더 이상 원문 선택이 아니다
                new = replace(e, text=t, revision=e.revision + 1,
                              origin="user_entered", idea_span=None)
                self.elements[i] = new
                self.revision += 1
                return new
        raise WorkspaceError(f"요소를 찾을 수 없습니다: {element_id}")

    def remove_element(self, element_id: str) -> None:
        n = len(self.elements)
        self.elements = [e for e in self.elements if e.element_id != element_id]
        if len(self.elements) == n:
            raise WorkspaceError(f"요소를 찾을 수 없습니다: {element_id}")
        self.revision += 1

    def element(self, element_id: str) -> ExplorationElement | None:
        return next((e for e in self.elements if e.element_id == element_id), None)

    # --- 연구주제 -------------------------------------------------------
    def change_idea(self, idea_text: str) -> None:
        """원래 연구주제를 바꾼다. 호출 전에 UI 가 초기화 여부를 확인해야 한다 (v2 §8.3).

        이전 메모를 조용히 삭제하지 않는다 — 이 함수는 요소·선택을 지우지 않고
        `idea_revision` 만 올린다. 초기화는 `reset()` 로 명시적으로 한다.
        """
        t = prep.normalize_text(idea_text)
        if not t:
            raise WorkspaceError("연구주제가 비어 있습니다")
        if t == self.idea_text:
            return
        self.idea_text = t
        self.idea_revision += 1
        self.revision += 1

    def reset(self) -> None:
        """`작업공간 지우기` (v2 §8.4). 명시적 호출만."""
        self.elements.clear()
        self.search_runs.clear()
        self.selected.clear()
        self.user_notes = None
        self.revision += 1

    # --- 검색 실행 ------------------------------------------------------
    def add_run(self, run: SearchRun) -> SearchRun:
        self.search_runs.append(run)
        self.revision += 1
        self._refresh_outside_filter()
        return run

    def run(self, run_id: str) -> SearchRun | None:
        return next((r for r in self.search_runs if r.run_id == run_id), None)

    def latest_run(self) -> SearchRun | None:
        return self.search_runs[-1] if self.search_runs else None

    # --- 선택 (비교함) --------------------------------------------------
    def select(self, run_id: str, record_id: str, user_reason: str | None = None
               ) -> SelectedProject:
        """비교함에 담는다. 중복 키는 `(source_snapshot_id, record_id)` (v2 §8.1).

        다른 관점에서 같은 과제가 나오면 **출처 이력만 추가**하고 독립 항목으로 세지 않는다.
        """
        r = self.run(run_id)
        if r is None:
            raise WorkspaceError(f"검색 실행을 찾을 수 없습니다: {run_id}")
        row = next((x for x in r.results if x.record_id == record_id), None)
        if row is None:
            raise WorkspaceError(f"이 검색 결과에 없는 과제입니다: {record_id}")
        origin = {"run_id": r.run_id, "perspective": r.perspective, "rank": row.rank}

        for i, s in enumerate(self.selected):
            if (s.source_snapshot_id, s.record_id) == (row.source_snapshot_id, record_id):
                if origin not in s.origin_runs:
                    self.selected[i] = replace(s, origin_runs=s.origin_runs + (origin,))
                    self.revision += 1
                if user_reason:
                    self.selected[i] = replace(self.selected[i], user_reason=user_reason)
                    self.revision += 1
                return self.selected[i]

        if len(self.selected) >= MAX_SELECTED:
            raise WorkspaceError(
                f"비교함은 최대 {MAX_SELECTED}개입니다. 화면 복잡도를 줄이기 위한 값이며 "
                f"항목을 빼면 더 담을 수 있습니다")
        sel = SelectedProject(record_id=record_id, source_snapshot_id=row.source_snapshot_id,
                              project_record=row, origin_runs=(origin,),
                              selection_order=len(self.selected) + 1, user_reason=user_reason)
        self.selected.append(sel)
        self.revision += 1
        self._refresh_outside_filter()
        return sel

    def deselect(self, record_id: str, source_snapshot_id: str | None = None) -> None:
        n = len(self.selected)
        self.selected = [s for s in self.selected
                         if not (s.record_id == record_id and
                                 (source_snapshot_id is None or
                                  s.source_snapshot_id == source_snapshot_id))]
        if len(self.selected) == n:
            raise WorkspaceError(f"비교함에 없는 과제입니다: {record_id}")
        # 선택 순서를 다시 매긴다 (사용자 선택 순서가 기본 순서다)
        self.selected = [replace(s, selection_order=i)
                         for i, s in enumerate(self.selected, 1)]
        self.revision += 1

    def set_reason(self, record_id: str, reason: str) -> SelectedProject:
        for i, s in enumerate(self.selected):
            if s.record_id == record_id:
                self.selected[i] = replace(s, user_reason=reason or None)
                self.revision += 1
                return self.selected[i]
        raise WorkspaceError(f"비교함에 없는 과제입니다: {record_id}")

    def _refresh_outside_filter(self) -> None:
        """가장 최근 실행 결과에 없는 선택 항목을 `현재 필터 밖` 으로 표시한다 (v2 §8.2).

        **자동 삭제하지 않는다.** 이전 검색에서 선택했다는 사실을 유지한다.
        """
        latest = self.latest_run()
        if latest is None:
            return
        present = {(x.source_snapshot_id, x.record_id) for x in latest.results}
        self.selected = [
            replace(s, outside_current_filter=((s.source_snapshot_id, s.record_id) not in present))
            for s in self.selected]

    # --- 스냅샷 ---------------------------------------------------------
    def stale_element_ids(self, observed_revisions: dict[str, int]) -> list[str]:
        """근거 판단이 참조한 요소 revision 이 현재와 다르면 그 요소는 재검토 대상이다."""
        return [eid for eid, rev in observed_revisions.items()
                if (e := self.element(eid)) is not None and e.revision != rev]


def new_workspace(idea_text: str, run_mode: RunMode = "local_live") -> Workspace:
    t = prep.normalize_text(idea_text)
    if not t:
        raise WorkspaceError("연구주제를 한 문장 입력하세요")
    return Workspace(workspace_id=_new_id("ws"), idea_text=t, run_mode=run_mode)


# ---------------------------------------------------------------------------
# 기존 검색 서비스 연결 (v2 §7.1)
# ---------------------------------------------------------------------------
def engine_config_id(cfg: dict, hybrid: bool, rerank: bool, top_n: int) -> str:
    """설정 동일성 키. 실제 검색문·필터와 함께 캐시 키를 이룬다 (v2 §7.4)."""
    r, k = cfg.get("retrieval", {}), cfg.get("rerank", {})
    parts = [f"hybrid={hybrid}", f"rrf_k={r.get('rrf_k')}",
             f"pool={r.get('candidate_pool')}", f"rerank={rerank}",
             f"top_n={top_n}", f"max_tokens={k.get('max_tokens')}",
             f"device={k.get('device')}", f"tau={r.get('project_relevance_threshold')}",
             f"space={r.get('threshold_space')}"]
    s = "|".join(parts)
    return "cfg_" + hashlib.sha256(s.encode()).hexdigest()[:12]


def actual_engine_name(hybrid: bool, rerank_applied: bool) -> str:
    """v2 §2.2 의 명명. 재정렬 실패를 E 성공으로 기록하지 않는다 (v2 §7.2)."""
    if hybrid:
        return "Retrieval-C+rerank" if rerank_applied else "Retrieval-C"
    return "Retrieval-E" if rerank_applied else "Retrieval-A"


_YEAR = re.compile(r"^(19|20)\d{2}$")


def run_perspective_search(ws: Workspace, plan: QueryPlan, engine, cfg: dict,
                           search_fn, request_cls, top_k: int = 5,
                           filters: dict | None = None,
                           requested_engine: str | None = None) -> SearchRun:
    """확정된 검색문 하나로 기존 검색 서비스를 **1회** 호출한다.

    `search_fn`/`request_cls` 를 받는 이유는 UI·CLI·테스트가 같은 경로를 쓰되
    검색 구현에 강결합되지 않게 하기 위함이다. 자동 fan-out 은 하지 않는다 (v2 §6.5).
    """
    if not plan.available:
        raise WorkspaceError(plan.reason or "이 관점은 아직 실행할 수 없습니다")
    f = dict(filters or {})
    years = f.get("years")
    if years:
        bad = [y for y in years if not _YEAR.match(str(y))]
        if bad:
            raise WorkspaceError(f"연도 필터가 잘못됐습니다: {bad}")

    rerank_on = bool(cfg.get("rerank", {}).get("enabled", True))
    hybrid_on = bool(cfg.get("retrieval", {}).get("hybrid", False))
    top_n = int(cfg.get("rerank", {}).get("top_n", 20))

    req = request_cls(query=plan.effective_query, top_k=top_k,
                      years=[int(y) for y in years] if years else None,
                      programs=f.get("programs") or None,
                      institutions=f.get("institutions") or None,
                      exclude_short=bool(f.get("exclude_short", False)))
    resp = search_fn(req, engine)

    snap = str(engine.projects["source_snapshot_id"].iloc[0]) if len(engine.projects) else ""
    rows = tuple(
        ResultRow(rank=r.rank, record_id=r.record_id, source_snapshot_id=snap,
                  source_row=r.source_row, title_raw=r.title, institution=r.institution,
                  selection_year=r.selection_year, program=r.program,
                  short_title=r.short_title, semantic_score=r.semantic_score,
                  percentile_label=r.percentile_label, rerank_score=r.rerank_score,
                  relevance_gate=r.relevance_gate,
                  semantic_percentile=getattr(r, "semantic_percentile", None),
                  source_dataset_id=snap.split("-")[0] if snap else "")
        for r in resp.results)

    run = SearchRun(
        run_id=_new_id("run"), workspace_id=ws.workspace_id, idea_revision=ws.idea_revision,
        perspective=plan.perspective, original_query=ws.idea_text,
        effective_query=resp.normalized_query, query_origin=plan.query_origin,
        used_element_ids=plan.used_element_ids, filters=f,
        requested_engine=requested_engine or actual_engine_name(hybrid_on, rerank_on),
        actual_engine=actual_engine_name(resp.stats.get("hybrid", hybrid_on),
                                         resp.rerank_applied),
        engine_config_id=engine_config_id(cfg, resp.stats.get("hybrid", hybrid_on),
                                          resp.rerank_applied, top_n),
        model_manifest_ids=(str(cfg.get("embedding", {}).get("revision") or "unpinned"),
                            str(cfg.get("rerank", {}).get("revision") or "unpinned")),
        index_manifest_id=snap, source_snapshot_ids=(snap,),
        results=rows, warnings=tuple(resp.warnings),
        latency_ms={k: round(v * 1000, 1) for k, v in resp.timings.items()},
        run_mode=resp.run_mode, rerank_applied=resp.rerank_applied,   # type: ignore[arg-type]
        rerank_badge=resp.rerank_badge,
        relevance={"tau": resp.relevance.tau, "space": resp.relevance.space,
                   "calibrated": resp.relevance.calibrated,
                   "reason": resp.relevance.reason,
                   "n_relevant": resp.relevance.n_relevant,
                   "scope": resp.relevance.scope})
    return ws.add_run(run)


def snapshot(ws: Workspace, capabilities: dict | None = None,
             observations: list | None = None, next_actions: list | None = None,
             source_manifests: list | None = None) -> dict:
    """§14.6 WorkspaceSnapshot. 키·토큰·개인식별 컬럼·민감한 로컬 경로는 넣지 않는다."""
    def el(e: ExplorationElement) -> dict:
        return {"element_id": e.element_id, "role": e.role, "text": e.text,
                "origin": e.origin, "confirmed": e.confirmed, "revision": e.revision,
                "idea_span": (None if e.idea_span is None else
                              {"start": e.idea_span.start, "end": e.idea_span.end,
                               "quote": e.idea_span.quote})}

    def row(r: ResultRow) -> dict:
        return {"rank": r.rank, "record_id": r.record_id,
                "source_snapshot_id": r.source_snapshot_id, "source_row": r.source_row,
                "title_raw": r.title_raw, "institution": r.institution,
                "selection_year": r.selection_year, "program": r.program,
                "short_title": r.short_title, "semantic_score": r.semantic_score,
                "percentile_label": r.percentile_label, "rerank_score": r.rerank_score,
                "relevance_gate": r.relevance_gate,
                "semantic_percentile": r.semantic_percentile,
                "source_dataset_id": r.source_dataset_id}

    def run(r: SearchRun) -> dict:
        return {"run_id": r.run_id, "idea_revision": r.idea_revision,
                "perspective": r.perspective, "original_query": r.original_query,
                "effective_query": r.effective_query, "query_origin": r.query_origin,
                "used_element_ids": list(r.used_element_ids), "filters": r.filters,
                "requested_engine": r.requested_engine, "actual_engine": r.actual_engine,
                "engine_config_id": r.engine_config_id,
                "model_manifest_ids": list(r.model_manifest_ids),
                "index_manifest_id": r.index_manifest_id,
                "source_snapshot_ids": list(r.source_snapshot_ids),
                "results": [row(x) for x in r.results], "warnings": list(r.warnings),
                "latency_ms": r.latency_ms, "run_mode": r.run_mode,
                "rerank_applied": r.rerank_applied, "rerank_badge": r.rerank_badge,
                "relevance": r.relevance}

    def sel(s: SelectedProject) -> dict:
        return {"record_id": s.record_id, "source_snapshot_id": s.source_snapshot_id,
                "project_record": row(s.project_record),
                "origin_runs": [dict(o) for o in s.origin_runs],
                "selection_order": s.selection_order, "user_reason": s.user_reason,
                "outside_current_filter": s.outside_current_filter}

    return {"schema_version": SCHEMA_VERSION, "workspace_id": ws.workspace_id,
            "revision": ws.revision, "idea_text": ws.idea_text,
            "idea_revision": ws.idea_revision,
            "elements": [el(e) for e in ws.elements],
            "search_runs": [run(r) for r in ws.search_runs],
            "selected_projects": [sel(s) for s in ws.selected],
            "observations": list(observations or []),
            "next_actions": list(next_actions or []),
            "user_notes": ws.user_notes,
            "capabilities_snapshot": dict(capabilities or {}),
            "source_manifests": list(source_manifests or []),
            "run_mode": ws.run_mode}
