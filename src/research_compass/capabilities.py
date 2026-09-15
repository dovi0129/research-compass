"""감사 결과 -> 기능 가용성 판정 (명세 4.5, 작업공간 명세 v2 §12.4).

v2 §12.4 는 12개 기능이 **독립 상태**를 갖도록 요구한다. 기존 키는 이름을 바꾸지 않고
`WORKSPACE_ALIASES` 로 매핑하고, 새 작업공간 기능만 추가한다.
이름만 바꾸어 미검증 기능이 활성화되지 않게 한다.
"""
from __future__ import annotations

from .audit import Finding

# v2 §12.4 가 요구하는 기능 키. 기존 키는 그대로 두고 별칭으로 연결한다.
WORKSPACE_ALIASES = {
    "ranked_project_search": "project_search",       # 순위 기반 검색 = 기존 project_search
    "field_name_search": "field_search",
    "field_count_display": "field_counts",
}

# v2 §12.4 의 상태 체계. 기존 판정값을 여기에 대응시킨다.
#   available   = 실제 자료·실행으로 동작 확인
#   limited     = 동작하지만 범위·해석에 제한
#   unavailable = 자료가 지원하지 않음 (영구 제한 포함)
#   unverified  = 검증 전
STATUS_MAP = {"verified": "available", "disabled": "unavailable",
              "unverified": "unverified", "limited": "limited"}


def _find(findings: list[Finding], check: str) -> Finding | None:
    return next((f for f in findings if f.check == check), None)


def decide(
    d1_basic: list[Finding],
    d1: list[Finding],
    d2_basic: list[Finding],
    d2: list[Finding],
    join: list[Finding],
) -> dict:
    caps: dict[str, dict] = {}

    def put(key: str, status: str, reason: str, **extra):
        caps[key] = {"status": status, "reason": reason, **extra}

    # --- project_search ---
    title = _find(d1, "과제명 결측/길이")
    title_missing = _find(d1, "과제명 컬럼")
    if title_missing and title_missing.status == "blocker":
        put("project_search", "disabled", "과제명 컬럼이 없어 검색 텍스트를 만들 수 없음")
    else:
        put("project_search", "verified",
            f"과제명 확보. {title.detail if title else ''}",
            scope="검색 텍스트 = 정규화 과제명 (초록·분야코드 없음)",
            limitations=["제목 한 줄만으로 임베딩하므로 짧은 과제명의 변별력이 낮을 수 있음",
                         "공식 과제번호가 없어 '과제 수'가 아니라 '수록 레코드 수'로만 집계"])

    # --- year_distribution ---
    sel = _find(d1, "연도-선정년도")
    if sel is None or sel.status == "warn" and sel.evidence.get("valid", 0) == 0:
        put("year_distribution", "disabled", "선정년도를 사용할 수 없음")
    else:
        ev = sel.evidence
        put("year_distribution", "verified",
            f"선정년도 유효 {ev.get('valid')}건, 범위 {ev.get('min')}~{ev.get('max')}, "
            f"파싱실패 {ev.get('invalid')}건",
            scope="다운로드한 스냅샷 내 선정연도별 수록 레코드 분포",
            limitations=["국가 전체 연구지원 현황이 아님",
                         "계속과제 반복 수록 가능성이 있어 해당 연도의 신규 선정 건수로 해석 금지",
                         "미상 연도는 별도 표기하며 0 으로 채우지 않음"])

    # --- field_search ---
    fname = _find(d2, "분야명")
    if fname is None or fname.status == "blocker":
        put("field_search", "disabled", "분야명 컬럼을 확인하지 못함")
    else:
        put("field_search", "verified", fname.detail,
            scope="입력 주제와 공개 분야명 간 의미 유사도",
            limitations=["개별 과제의 공식 분류를 뜻하지 않음"])

    # --- field_counts ---
    conflict = _find(d2, "기준기간 충돌")
    if conflict is not None:
        put("field_counts", "disabled",
            "기준기간 충돌 미해결 — " + conflict.detail,
            evidence_refs=[conflict.evidence],
            limitations=["원문 확인 영역에서 원본 컬럼명과 '기간 확인 필요' 표시만 허용",
                         "비교 차트·순위화 금지"])
    else:
        cnt = next((f for f in d2 if f.check.startswith("선정횟수 값-")), None)
        put("field_counts", "verified" if cnt else "unverified",
            cnt.detail if cnt else "선정횟수 값 검증 결과 없음")

    # --- comparable_trend ---
    ncol = _find(d2, "선정횟수 컬럼 수")
    if ncol is not None and ncol.status == "blocker":
        put("comparable_trend", "disabled",
            "D2 의 선정횟수 컬럼이 1개뿐이라 이 데이터만으로 시계열을 구성할 수 없음. "
            "연도별 변화는 D1 의 선정년도 분포(year_distribution)로만 제시",
            evidence_refs=[ncol.evidence])
    else:
        put("comparable_trend", "unverified",
            "기간별 집계 기준·포함 범위의 비교 가능성 검증 필요 (명세 8.3)")

    # --- project_field_join ---
    jk = _find(join, "값 수준 연결키 후보")
    if jk is None or jk.status == "blocker":
        put("project_field_join", "disabled",
            "D1 과 D2 사이에 공식 연결키가 없음. 분야명 임베딩의 최근접 코드를 "
            "과제의 공식 분야 코드로 저장하는 것을 금지 (명세 7.3)")
    else:
        put("project_field_join", "unverified", f"연결키 후보 발견: {jk.detail}. 공식 매핑 근거 확인 필요")

    # --- opportunity_candidates ---
    if caps["field_counts"]["status"] != "verified":
        put("opportunity_candidates", "disabled",
            "비교 가능한 검증된 선정 통계가 없어 후보를 생성하지 않음. "
            "UI 는 후보 대신 판단 보류 사유를 표시 (명세 9.4)")
    else:
        put("opportunity_candidates", "unverified",
            "관련도 기준값(tau_field) 사람 평가 및 비교 집단 정의 필요")

    caps.update(_workspace_caps(caps))
    return caps


# 기능별로 그 기능을 **실제로 구현하는 모듈**을 본다. 한 모듈이 생겼다고 다른 기능까지
# 승격되면 다시 과대주장이 된다 (v2 §1.2).
FEATURE_MODULES = {
    "perspective_search": "workspace",
    "comparison_workspace": "workspace",
    "title_evidence_review": "comparison",
    "exploration_memo": "memo",
    "scoped_distribution": "analytics",
}


def _module_exists(name: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(f"{__package__}.{name}") is not None


def workspace_implemented(feature: str | None = None) -> bool:
    """해당 기능의 구현 모듈이 실제로 있는지. 명세 문장이 아니라 코드 존재로 판정한다 (v2 §1.2)."""
    if feature is None:
        return _module_exists("workspace")
    mod = FEATURE_MODULES.get(feature)
    return _module_exists(mod) if mod else False


def _workspace_caps(caps: dict) -> dict:
    """v2 §12.4 의 작업공간 기능 상태.

    작업공간 기능은 **순위 기반 후보**로 동작하므로 tau 검증을 기다리지 않는다(v2 §7.3).
    반면 `calibrated_relevant_corpus` 는 검증된 tau 가 있어야 하며 기존 게이트를 그대로 따른다.

    상태는 **자료 지원 여부와 구현 여부를 함께** 본다. 자료가 지원해도 구현·실행이 확인되지
    않았으면 `unverified` 다. 명세에 적혀 있다는 이유로 `available` 로 올리지 않는다 (v2 §1.2).
    `data_supports` 로 두 사유를 구분해 남긴다.
    """
    out: dict[str, dict] = {}
    searchable = caps.get("project_search", {}).get("status") == "verified"

    def put(key, ready_status, reason, **extra):
        """자료가 지원하고 **그 기능의 모듈이 있을 때만** ready_status 를 쓴다."""
        built = workspace_implemented(key)
        mod = FEATURE_MODULES.get(key, "?")
        if not searchable:
            out[key] = {"status": "unavailable", "reason": "과제 검색이 불가하여 이 기능도 불가",
                        "data_supports": False, "implemented": built, **extra}
        elif not built:
            out[key] = {"status": "unverified",
                        "reason": f"자료는 지원하지만 `{mod}` 모듈이 아직 없음 (v2 W1~W3 미구현). "
                                  + reason,
                        "data_supports": True, "implemented": False, **extra}
        else:
            out[key] = {"status": ready_status, "reason": reason,
                        "data_supports": True, "implemented": True, **extra}

    # 검색·비교·메모 — tau 와 무관 (v2 §7.3)
    put("perspective_search", "available",
        "사용자가 확정한 탐색 요소로 검색문을 구성해 관점당 1회 실행. "
        "관점 이름은 탐색 의도의 표식이며 반환 과제가 그 의도를 충족한다는 판정이 아님",
        limitations=["관점별 결과를 자동 통합(RRF·점수 평균)하지 않음",
                     "서로 다른 질의의 원시 점수를 같은 축에서 비교하지 않음"])
    put("comparison_workspace", "available",
        "선택 과제를 (source_snapshot_id, record_id) 로 중복 없이 보관하고 검색 출처 이력을 남김",
        limitations=["여러 검색의 점수를 하나의 대표 관련도로 합치지 않음",
                     "기본 순서는 사용자 선택 순서"])
    put("title_evidence_review", "limited",
        "근거 범위가 제목 한 줄뿐(evidence_scope=title_only). 원문 literal match 로 표현 발견만 자동화",
        limitations=["표현 발견은 그 연구가 해당 방법을 썼다는 뜻이 아님 (부정·비교 문맥 가능)",
                     "자동 미검출은 연구 부재·무관함·신규성이 아니라 needs_review",
                     "초록이 없어 연구내용 사실은 제목으로 확정 불가"])
    put("exploration_memo", "available",
        "자동 발견 표현과 사용자 검토를 분리해 Markdown/JSON 으로 내보냄",
        limitations=["근거 번호는 이 메모 내부 번호이며 공식 과제번호가 아님",
                     "선택 0건도 정상 결과로 내보냄"])

    # 범위를 명시한 기술통계 — 전역 tau 를 요구하지 않는다 (v2 §12.1)
    put("scoped_distribution", "limited",
        "dataset_snapshot / displayed_results / selected_records 세 범위의 기술통계만 허용",
        limitations=["displayed_results 는 표시 수가 바뀌면 바뀜",
                     "selected_records 는 비교함이 바뀌면 바뀜",
                     "증가율·감소율·성장성 문구 금지 (v2 §12.2)",
                     "관측하지 않은 기간을 0건으로 채우지 않음"])

    # 검증된 tau 가 필요한 전체 집계 — 기존 게이트 유지. 구현 여부와 무관하게 unverified 다.
    out["calibrated_relevant_corpus"] = {
        "status": "unverified",
        "reason": "관련도 기준값(tau) 미확정 — 라벨 표본의 정밀도 곡선으로만 정한다 (D-019). "
                  "확정 전에는 '관련 과제 총 N건' 을 만들지 않는다",
        "data_supports": False, "implemented": workspace_implemented("scoped_distribution"),
        "limitations": ["Top-K 독립성 시험은 이 범위에 계속 적용 (T-14)",
                        "표본이 순위 층화 표본이므로 정밀도 곡선은 무편향 추정치가 아님"],
    }
    return out


def refresh_workspace_states(caps: dict) -> dict:
    """저장된 capabilities.json 위에 **현재 코드 기준** 작업공간 상태를 덧씌운다.

    모듈 존재 여부는 실행 시점에 판정하므로, 파일이 오래됐어도 없는 기능을 available 로 보이지 않는다.
    """
    out = dict(caps)
    out.update(_workspace_caps(out))
    return out


def workspace_status(caps: dict, key: str) -> dict | None:
    """v2 §12.4 키로 상태를 조회한다. 기존 키 이름과의 별칭을 흡수한다."""
    if key in caps:
        return caps[key]
    alias = WORKSPACE_ALIASES.get(key)
    if alias and alias in caps:
        c = dict(caps[alias])
        c["aliased_from"] = alias
        return c
    return None


def v2_feature_states(caps: dict) -> dict:
    """v2 §12.4 의 12개 키를 상태 체계로 정규화해 돌려준다. 없는 키는 unverified."""
    keys = ("ranked_project_search", "perspective_search", "comparison_workspace",
            "title_evidence_review", "exploration_memo", "field_name_search",
            "field_count_display", "scoped_distribution", "calibrated_relevant_corpus",
            "comparable_trend", "project_field_join", "opportunity_candidates")
    out = {}
    for k in keys:
        c = workspace_status(caps, k)
        if c is None:
            out[k] = {"status": "unverified", "reason": "판정 근거 없음"}
            continue
        out[k] = {**c, "status": STATUS_MAP.get(c["status"], c["status"])}
    return out
