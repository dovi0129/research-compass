"""탐색 검토 메모 — Markdown / JSON (명세 v2 §11).

지키는 경계
- 자동 발견 표현과 사용자 검토 내용을 섞지 않는다. 검토하지 않은 자동 제안은 확정 영역에 넣지 않는다.
- stale·인용 검증 실패 항목은 확정 영역에서 제외하고 사유를 남긴다.
- 선택 과제가 없어도 메모를 만든다. 가짜 과제·근거·연구방향을 채우지 않는다.
- `[E1]` 은 이 메모의 근거 번호다. 공식 과제번호가 아니다.
- 같은 작업공간 snapshot 이면 `generated_at` 을 제외하고 결정적으로 생성한다.
- 원문·사용자 텍스트는 Markdown 특수문자를 escape 한다. URL 은 https 만 허용한다 (v2 §21.4).
- 키·토큰·개인식별 컬럼·로컬 절대 경로를 넣지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Iterable

from . import analytics as an
from . import comparison as cmp
from . import workspace as wsm
from .nextactions import KIND_LABELS, NextAction

SCHEMA_VERSION = "memo/1.0"
MEMO_TITLE = "# Research Compass 탐색 검토 메모"
NO_SELECTION_NOTE = "현재 탐색에서는 참고 후보를 선택하지 않았습니다. 이 결과는 해당 연구가 없다는 의미가 아닙니다."
USER_NOTES_SCOPE = "> 아래는 사용자가 직접 쓴 글입니다. 자동으로 만든 문장·해석·판정이 아니며 검증하지 않았습니다."
ENGINE_DESC = {"Retrieval-A": "의미검색", "Retrieval-E": "의미검색 + 재정렬",
               "Retrieval-C": "의미·어휘 결합", "Retrieval-C+rerank": "의미·어휘 결합 + 재정렬"}

_MD = re.compile(r"([\\`*_\[\]<>|#~])")          # 서식·HTML·표 구분에 쓰이는 문자만. 식별자는 code() 로 감싼다
_LOCAL_PATH = re.compile(r"[A-Za-z]:\\|/home/|/Users/")


class MemoError(ValueError):
    pass


def md_escape(s) -> str:
    """Markdown 서식·HTML 로 해석될 문자를 무력화한다. 표 칸에서는 줄바꿈도 없앤다."""
    t = _MD.sub(r"\\\1", str(s if s is not None else ""))
    return t.replace("\r", " ").replace("\n", " ")


def code(s) -> str:
    """식별자(run_id·해시·revision)는 escape 대신 코드 스팬으로. 백틱만 제거한다."""
    return "`" + str(s if s is not None else "").replace("`", "") + "`"


def safe_url(u: str | None) -> str | None:
    return u if isinstance(u, str) and u.startswith("https://") else None


@dataclass
class MemoResult:
    markdown: str
    data: dict
    problems: list[str] = field(default_factory=list)          # 확정 영역에서 제외된 항목과 사유


def _refs_from_snapshot(snapshot: dict) -> dict[tuple[str, str], cmp.TitleRef]:
    out = {}
    for s in snapshot.get("selected_projects", []):
        r = s["project_record"]
        ds = r.get("source_dataset_id") or str(r.get("source_snapshot_id", "")).split("-")[0]
        out[(r["source_snapshot_id"], r["record_id"])] = cmp.TitleRef(
            record_id=r["record_id"], source_snapshot_id=r["source_snapshot_id"],
            source_dataset_id=str(ds), title_raw=str(r["title_raw"]))
    return out


def _fmt_filters(f: dict) -> str:
    parts = []
    if f.get("years"):
        parts.append("선정년도 " + "·".join(str(y) for y in f["years"]))
    if f.get("programs"):
        parts.append("사업 " + "·".join(f["programs"]))
    if f.get("institutions"):
        parts.append("기관 " + "·".join(f["institutions"]))
    if f.get("exclude_short"):
        parts.append("짧은 제목 제외")
    return ", ".join(parts) or "없음"


def build(snapshot: dict, observations: Iterable[cmp.EvidenceObservation] = (),
          next_actions: Iterable[NextAction] = (), *, generated_at: str | None = None,
          source_url: str | None = None, dataset_label: str = "한국연구재단 이알앤디 과제정보 (D1)") -> MemoResult:
    """WorkspaceSnapshot + 관측 + 다음 작업 → 메모. 내보내기 전에 인용·출처·검토 상태를 검증한다 (v2 §11.5)."""
    obs = list(observations)
    acts = list(next_actions)
    refs = _refs_from_snapshot(snapshot)
    problems: list[str] = []
    elements = {e["element_id"]: e for e in snapshot.get("elements", [])}
    runs = snapshot.get("search_runs", [])
    selected = snapshot.get("selected_projects", [])
    run_by_id = {r["run_id"]: r for r in runs}

    # 근거 번호 (선택 순서대로 E1…) — 이 메모 내부 번호
    evidence_no = {(s["project_record"]["source_snapshot_id"], s["record_id"]): f"E{i}"
                   for i, s in enumerate(selected, 1)}

    def ename(eid: str) -> str:
        e = elements.get(eid)
        return f"{wsm.ROLE_LABELS.get(e['role'], e['role'])} = {e['text']}" if e else eid

    L: list[str] = [MEMO_TITLE, ""]
    L += ["## 연구주제", md_escape(snapshot.get("idea_text", "")), ""]

    # --- 탐색한 관점 -------------------------------------------------------
    L += ["## 탐색한 관점"]
    if not runs:
        L.append("실행한 검색이 없습니다.")
    else:
        L.append("| # | 관점 | 실제 검색문 | 필터 | 검색 엔진 | 결과 |")
        L.append("|---|---|---|---|---|---|")
        for i, r in enumerate(runs, 1):
            eng = r["actual_engine"]
            eng_txt = f"{ENGINE_DESC.get(eng, eng)} ({eng})"
            if r.get("requested_engine") and r["requested_engine"] != eng:
                eng_txt += f" — 요청 {r['requested_engine']} 대체"
            old = " · 이전 연구주제" if r.get("idea_revision") != snapshot.get("idea_revision") else ""
            q = md_escape(r["effective_query"])
            if r.get("query_origin") == "user_edited":
                q += " (사용자 수정)"
            L.append(f"| {i} | {md_escape(wsm.PERSPECTIVE_LABELS.get(r['perspective'], r['perspective']))}{old} | {q} | "
                     f"{md_escape(_fmt_filters(r.get('filters', {})))} | {md_escape(eng_txt)} | {len(r.get('results', []))}건 |")
    L.append("")

    # --- 선택한 과제 -------------------------------------------------------
    L += ["## 참고 후보로 선택한 과제"]
    if not selected:
        L.append(f"> {NO_SELECTION_NOTE}")
    else:
        L.append("| 근거 | 원문 제목 | 공개 메타데이터 | 담은 검색 | 사용자 선택 이유 |")
        L.append("|---|---|---|---|---|")
        for s in selected:
            r = s["project_record"]
            no = evidence_no[(r["source_snapshot_id"], s["record_id"])]
            year = f"{r['selection_year']}년 선정" if r.get("selection_year") is not None else "선정연도 미상"
            meta = " · ".join(x for x in (r.get("institution", ""), year, r.get("program", "")) if x)
            origins = "; ".join(f"{wsm.PERSPECTIVE_LABELS.get(o['perspective'], o['perspective'])} {o['rank']}위"
                                for o in s.get("origin_runs", []))
            flag = " (지금 보는 결과에 없음)" if s.get("outside_current_filter") else ""
            L.append(f"| [{no}] | {md_escape(r['title_raw'])} | {md_escape(meta)} | {md_escape(origins)}{flag} | "
                     f"{md_escape(s.get('user_reason') or '—')} |")
    L.append("")

    # --- 근거 검토: 확정 / 미확인 분리 -------------------------------------------
    settled, pending = [], []
    for o in obs:
        ref = refs.get((o.source_snapshot_id, o.record_id))
        title = ref.title_raw if ref else None
        probs = cmp.validate(o, title)
        if o.review_status == "stale":
            pending.append((o, "재검토 필요 (요소 또는 원문이 바뀜)"))
        elif probs:
            pending.append((o, "인용 검증 실패: " + "; ".join(probs)))
            problems.append(f"{o.observation_id}: " + "; ".join(probs))
        elif cmp.is_settled(o, title):
            settled.append(o)
        elif o.review_status == "rejected":
            pending.append((o, "사용자가 자동 발견의 의미 연결을 거부함"))
        elif o.finding == "expression_found":
            pending.append((o, "자동 발견 표현 — 사용자 검토 전"))
        else:
            pending.append((o, "해당 표현 자동 미검출 — 직접 검토 필요"))

    L += ["## 제목에서 확인한 표현과 검토 내용"]
    if not elements:
        L.append("탐색 요소를 입력하지 않아 제목 표현 비교는 하지 않았습니다. 선택 이유와 미확인 사항은 위·아래 절에 있습니다.")
    elif not settled:
        L.append("사용자가 검토를 마친 항목이 없습니다. 자동 발견 표현은 아래 '아직 확인하지 못한 사항' 에 있습니다.")
    else:
        L.append("| 요소 | 과제 | 구분 | 원문 인용 (위치) | 사용자 검토 의견 |")
        L.append("|---|---|---|---|---|")
        for o in settled:
            no = evidence_no.get((o.source_snapshot_id, o.record_id), "?")
            if o.finding == "not_confirmed_in_title":
                kind, quote = "제목에서 확인되지 않음 (사용자 검토)", "—"
            else:
                kind = ("사용자 인용" if o.origin == "user_annotation"
                        else f"{cmp.ORIGIN_LABELS.get(o.origin, o.origin)} → 사용자 확인")
                quote = "; ".join(f"“{md_escape(q.quote)}” ({q.start_offset}–{q.end_offset})" for q in o.quotes)
            L.append(f"| {md_escape(ename(o.element_id))} | [{no}] | {kind} | {quote} | "
                     f"{md_escape(o.user_interpretation or '—')} |")
    L.append("")

    # --- 아직 확인하지 못한 사항 ------------------------------------------------
    L += ["## 아직 확인하지 못한 사항"]
    if not pending and not any(a.kind == "inspect_project_detail" for a in acts):
        L.append("추가로 기록된 미확인 항목이 없습니다. 이는 모든 것이 확인됐다는 뜻이 아니라, 제목 기반 비교의 범위 안에서 남은 항목이 없다는 뜻입니다.")
    else:
        for o, why in pending:
            no = evidence_no.get((o.source_snapshot_id, o.record_id), "?")
            extra = ""
            if o.finding == "expression_found" and o.quotes:
                extra = " — 자동 발견 구절: " + "; ".join(f"“{md_escape(q.quote)}”" for q in o.quotes)
            L.append(f"- [{no}] {md_escape(ename(o.element_id))}: {md_escape(why)}{extra}")
        for a in acts:
            if a.kind == "inspect_project_detail":
                L.append(f"- 확인 질문: {md_escape(a.text)}")
    L.append("")

    # --- 다음 탐색·확인 ---------------------------------------------------------
    L += ["## 다음 탐색·확인"]
    confirmed = [a for a in acts if a.confirmed]
    proposed = [a for a in acts if not a.confirmed]
    if not acts:
        L.append("제안된 다음 작업이 없습니다 (근거 부족 시 억지로 채우지 않습니다).")
    for a in confirmed:
        q = f" — 검색문: {md_escape(a.proposed_query)}" if a.proposed_query else ""
        tag = " (사용자 수정)" if a.origin == "user_edited" else ""
        L.append(f"- **확인함** [{KIND_LABELS.get(a.kind, a.kind)}] {md_escape(a.text)}{q}{tag}")
    for a in proposed:
        q = f" — 검색문: {md_escape(a.proposed_query)}" if a.proposed_query else ""
        L.append(f"- 제안 (미확인) [{KIND_LABELS.get(a.kind, a.kind)}] {md_escape(a.text)}{q}")
    L.append("")

    # --- 사용자 자유 메모 (D-029) — 사용자가 쓴 글을 그대로 담는다. 자동 요약·해석 없음. 템플릿 검사 대상이 아니다
    notes = str(snapshot.get("user_notes") or "").replace("\r\n", "\n").strip()
    user_lines = notes.split("\n") if notes else []
    L += ["## 사용자 자유 메모"]
    if notes:
        L.append(USER_NOTES_SCOPE)
        L.append("")
        L += user_lines
    else:
        L.append("작성한 자유 메모가 없습니다.")
    L.append("")

    # --- 범위와 제한 ------------------------------------------------------------
    caps = snapshot.get("capabilities_snapshot", {}) or {}
    limited = [k for k, v in caps.items() if isinstance(v, dict) and v.get("status") in ("unavailable", "unverified")]
    snaps = sorted({r["source_snapshot_id"] for s in selected for r in [s["project_record"]]}
                   | {sid for r in runs for sid in r.get("source_snapshot_ids", [])})
    L += ["## 범위와 제한",
          f"- 사용 데이터: {md_escape(dataset_label)}, 스냅샷 {', '.join(code(x) for x in snaps) or '—'}. 제목과 공개 메타데이터만 사용(초록 없음).",
          "- 검색 결과는 '가까운 검색 결과' 이며 관련 과제 판정이 아닙니다. 점수는 상대 점수이고 정확도·확률이 아닙니다.",
          "- 제목 기반 비교: 표현 발견은 연구내용 확인이 아니며, 자동 미검출은 연구 부재·무관함·신규성이 아닙니다.",
          "- 분야명 탐색(D2)은 독립 보조 기능이며 과제에 분야를 배정하지 않습니다. 선정횟수는 기준연도 미확인으로 비교하지 않습니다.",
          f"- 제한된 기능: {', '.join(md_escape(k) for k in limited) if limited else '기능 상태 스냅샷 없음'}.",
          f"- 실행 모드: {code(snapshot.get('run_mode', 'unknown'))}.", ""]

    # --- 근거 부록 --------------------------------------------------------------
    L += ["## 근거 부록"]
    url = safe_url(source_url)
    if selected:
        L.append("| 근거 | 데이터셋 | 스냅샷 | 레코드 ID | 원본 행 | 원문 SHA-256 (앞 12자) |")
        L.append("|---|---|---|---|---|---|")
        for s in selected:
            r = s["project_record"]
            no = evidence_no[(r["source_snapshot_id"], s["record_id"])]
            ds = r.get("source_dataset_id") or str(r["source_snapshot_id"]).split("-")[0]
            L.append(f"| [{no}] | {code(ds)} | {code(r['source_snapshot_id'])} | {code(r['record_id'])} | "
                     f"{r.get('source_row', '—')} | `{cmp.sha256_text(str(r['title_raw']))[:12]}` |")
    if url:
        L.append(f"- 원본 데이터 페이지: {url}")
    model_ids = sorted({m for r in runs for m in r.get("model_manifest_ids", [])})
    cfg_ids = sorted({r.get("engine_config_id", "") for r in runs} - {""})
    L.append(f"- 모델 revision: {', '.join(code(m) for m in model_ids) or '—'}")
    L.append(f"- 엔진 설정 ID: {', '.join(code(c) for c in cfg_ids) or '—'}")
    L.append(f"- 검색 실행 ID: {', '.join(code(r['run_id']) for r in runs) or '—'}")
    L.append(f"- 작업공간: {code(snapshot.get('workspace_id', ''))} (revision {snapshot.get('revision', '?')})")
    if generated_at:
        L.append(f"- 생성 시각: {code(generated_at)}")
    L.append("")
    L.append("_[E#] 은 이 메모의 근거 번호이며 공식 과제번호가 아닙니다._")

    markdown = "\n".join(L).rstrip() + "\n"

    # 안전 검사 — 생성 문장(템플릿)에 금지 표현·추세 문구·로컬 경로가 없어야 한다
    user_set = set(user_lines)
    template_only = "\n".join(x for x in L if not x.startswith("|") and x not in user_set)
    if cmp.contains_forbidden(template_only):
        raise MemoError("메모 템플릿에 금지 표현이 있다")
    if _LOCAL_PATH.search(markdown):
        raise MemoError("메모에 로컬 절대 경로가 들어갔다")

    data = {"schema_version": SCHEMA_VERSION, "generated_at": generated_at,
            "workspace": snapshot,
            "observations": [o.to_dict() for o in obs],
            "next_actions": [a.to_dict() for a in acts],
            "evidence_index": {no: {"source_snapshot_id": k[0], "record_id": k[1]} for k, no in evidence_no.items()},
            "settled_observation_ids": [o.observation_id for o in settled],
            "excluded": problems,
            "markdown_sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest()}
    return MemoResult(markdown=markdown, data=data, problems=problems)


BRIEF_TITLE = "# Research Compass 탐색 메모"
BRIEF_FOOT_NOTE = "_[E#] 은 이 메모의 번호이며 공식 과제번호가 아닙니다. 검색 결과는 제목 기준으로 가까운 결과이며 관련 과제 판정이 아닙니다._"


def build_brief(snapshot: dict, *, generated_at: str | None = None, source_url: str | None = None,
                program_paths: dict | None = None,
                dataset_label: str = "한국연구재단 이알앤디 과제정보 (D1)", top_n: int = 5) -> str:
    """압축 메모 (D-033) — 선택한 과제(원본 링크) · 탐색 기록 · 사용자 메모만. 전체 기록(관측·검토·다음 작업·부록)은 build() 의 JSON 에 있다.

    같은 snapshot 이면 generated_at 을 제외하고 결정적이다. 자동 판정·해석 문장을 만들지 않는다.
    program_paths: {(source_snapshot_id, record_id): "대사업 › … › 세부사업"} — 화면이 정제 데이터에서 만든 사업 계층 (없으면 대사업명).
    """
    runs = snapshot.get("search_runs", [])
    selected = snapshot.get("selected_projects", [])
    run_by_id = {r["run_id"]: r for r in runs}
    url = safe_url(source_url)
    paths = program_paths or {}
    data_lines: set[str] = set()          # 원문 제목이 든 줄 — 템플릿 금지어 검사에서 제외

    L: list[str] = [BRIEF_TITLE, "", f"**연구주제:** {md_escape(snapshot.get('idea_text', ''))}", ""]

    L += ["## 선택한 과제"]
    if not selected:
        L.append(f"> {NO_SELECTION_NOTE}")
        L.append("")
    for i, s in enumerate(selected, 1):
        r = s["project_record"]
        head = f"### E{i}. {md_escape(r['title_raw'])}"
        data_lines.add(head)
        L.append(head)
        year = f"{r['selection_year']}년 선정" if r.get("selection_year") is not None else "선정연도 미상"
        prog = paths.get((r["source_snapshot_id"], s["record_id"])) or r.get("program") or ""
        L.append("- " + " · ".join(md_escape(x) for x in (r.get("institution", ""), year, prog) if x))
        for o in s.get("origin_runs", []):
            run = run_by_id.get(o["run_id"])
            q = f" “{md_escape(run['effective_query'])}”" if run else ""
            L.append(f"- 찾은 검색: {md_escape(wsm.PERSPECTIVE_LABELS.get(o['perspective'], o['perspective']))}{q} · {o['rank']}위")
        src_txt = f"[원본 데이터 페이지]({url})" if url else "원본 데이터 페이지 —"
        L.append(f"- 원본: {src_txt} · 원본 행 {r.get('source_row', '—')}")
        L.append("")

    L += ["## 탐색 기록"]
    if not runs:
        L.append("실행한 검색이 없습니다.")
    for i, r in enumerate(runs, 1):
        q = md_escape(r["effective_query"])
        if r.get("query_origin") == "user_edited":
            q += " (사용자 수정)"
        L.append(f"{i}. **{md_escape(wsm.PERSPECTIVE_LABELS.get(r['perspective'], r['perspective']))}** — {q} · 결과 {len(r.get('results', []))}건")
        for x in r.get("results", [])[:top_n]:
            line = f"   - {x['rank']}위 {md_escape(x['title_raw'])}"
            data_lines.add(line)
            L.append(line)
    L.append("")

    notes = str(snapshot.get("user_notes") or "").replace("\r\n", "\n").strip()
    user_lines = notes.split("\n") if notes else []
    L += ["## 메모"]
    L += user_lines if notes else ["작성한 메모가 없습니다."]
    L.append("")

    foot = [f"데이터: {md_escape(dataset_label)}"]
    if url:
        foot.append(url)
    if generated_at:
        foot.append(f"생성 {code(generated_at)}")
    foot.append(f"작업공간 {code(snapshot.get('workspace_id', ''))}")
    L += ["---", " · ".join(foot), "", BRIEF_FOOT_NOTE]
    markdown = "\n".join(L).rstrip() + "\n"

    skip = set(user_lines) | data_lines
    template_only = "\n".join(x for x in L if x not in skip)
    if cmp.contains_forbidden(template_only):
        raise MemoError("메모 템플릿에 금지 표현이 있다")
    if _LOCAL_PATH.search(markdown):
        raise MemoError("메모에 로컬 절대 경로가 들어갔다")
    return markdown


FREE_MEMO_TITLE = "# 연구탐색 자유 메모"
FREE_MEMO_SCOPE = ("- 제목과 공개 메타데이터만 보고 쓴 기록입니다. 아래 본문은 사용자가 직접 쓴 글이며 "
                   "자동으로 만든 문장·해석·판정은 없습니다.")


def free_memo(user_text: str, *, idea_text: str = "", generated_at: str | None = None) -> str:
    """자유 메모 파일 본문 (v2 §17.6 — UX-L·UX-W 공통 기록 수단).

    사용자가 쓴 글을 **그대로** 담는다. 자동 요약·해석·다음 행동을 만들지 않는다.
    머리말은 사실만 적는다: 작성 시각·연구주제·자료 범위. 본문은 사용자 파일이므로 escape 하지 않는다.
    """
    head = [FREE_MEMO_TITLE, ""]
    if generated_at:
        head.append(f"- 작성 시각: {md_escape(generated_at)}")
    if str(idea_text or "").strip():
        head.append(f"- 내 연구주제: {md_escape(idea_text)}")
    head += [FREE_MEMO_SCOPE, "", "---", "", ""]
    body = str(user_text or "").replace("\r\n", "\n")
    return "\n".join(head) + (body if body.endswith("\n") else body + "\n")


def to_json(result: MemoResult) -> str:
    return json.dumps(result.data, ensure_ascii=False, indent=2)


def has_trend_language(result: MemoResult) -> bool:
    return an.contains_trend_language(result.markdown)
