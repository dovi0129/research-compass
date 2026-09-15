"""범위를 명시한 기술통계 (명세 v2 §12.1~12.2).

허용 범위는 세 가지다 — `dataset_snapshot`, `displayed_results`, `selected_records`.
`calibrated_relevant_corpus` 는 검증된 tau 가 있어야 하며 **이 모듈이 만들지 않는다**
(기존 Top-K 독립성 시험 T-14 가 그 범위에 계속 적용된다).

지키는 경계
- 집계마다 `scope_kind`·대상 레코드 ID·대상 수·미상 값 수를 함께 기록한다.
- 미상(결측) 값은 `unknown` 으로 따로 세고 0 으로 바꾸지 않는다.
- 관측하지 않은 값(연도 등)을 0 건으로 채우지 않는다 — 관측된 값만 나열한다.
- 증가율·감소율·성장성 문구를 만들지 않는다. 구성(counts)만 돌려준다.
- 같은 (source_snapshot_id, record_id) 는 한 번만 센다 — 관점이 달라도 중복 집계하지 않는다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Iterable

SCOPE_KINDS = ("dataset_snapshot", "displayed_results", "selected_records")
SCOPE_LABELS = {"dataset_snapshot": "수록 데이터 전체",
                "displayed_results": "표시 중인 결과",
                "selected_records": "비교함에 담은 레코드"}
UNKNOWN = "unknown"

# 화면·메모가 절대 붙이지 않는 문구 (v2 §12.2). 시험이 이 목록으로 출력 문자열을 검사한다.
FORBIDDEN_TREND_WORDS = ("증가율", "감소율", "성장성", "성장률", "급증", "급감", "추세")


class ScopeError(ValueError):
    """허용되지 않은 집계 범위."""


@dataclass(frozen=True)
class ScopedDistribution:
    scope_kind: str
    by: str                                   # 집계 기준 필드 (selection_year, program, institution)
    n: int                                    # 대상 레코드 수 (중복 제거 후)
    n_unknown: int                            # 기준 필드가 비어 있는 레코드 수 (0 으로 채우지 않음)
    counts: dict[str, int]                    # 관측된 값 → 레코드 수. 관측되지 않은 값은 키가 없다
    record_ids: tuple[str, ...]               # 대상 레코드 식별자 (source_snapshot_id#record_id)
    run_ids: tuple[str, ...] = ()             # displayed_results 일 때 근거 검색 실행
    filters: dict = field(default_factory=dict)
    caveats: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return SCOPE_LABELS[self.scope_kind]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["record_ids"] = list(self.record_ids)
        d["run_ids"] = list(self.run_ids)
        d["caveats"] = list(self.caveats)
        d["label"] = self.label
        return d


def _key(rec: dict) -> str:
    return f"{rec.get('source_snapshot_id', '')}#{rec.get('record_id', '')}"


def _value(rec: dict, by: str) -> str | None:
    v = rec.get(by)
    if v is None:
        return None
    if isinstance(v, float) and v != v:           # NaN
        return None
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    if by == "selection_year":
        try:
            return str(int(float(s)))
        except ValueError:
            return s
    return s


def distribution(records: Iterable[dict], by: str, scope_kind: str, *,
                 run_ids: Iterable[str] = (), filters: dict | None = None,
                 caveats: Iterable[str] = ()) -> ScopedDistribution:
    """레코드 목록의 `by` 기준 구성을 센다. 레코드는 공개 필드 dict 다.

    `scope_kind` 는 세 허용 범위 중 하나여야 한다. `calibrated_relevant_corpus` 는 거절한다 —
    그 범위는 검증된 tau 없이 만들 수 없다 (v2 §12.1, 개정안 6절).
    """
    if scope_kind not in SCOPE_KINDS:
        raise ScopeError(f"허용되지 않은 집계 범위: {scope_kind!r} — {SCOPE_KINDS} 중 하나. "
                         f"calibrated_relevant_corpus 는 검증된 tau 없이 만들지 않는다")
    seen: dict[str, dict] = {}
    for r in records:
        k = _key(r)
        if k not in seen:                          # 관점이 달라도 같은 레코드는 한 번만
            seen[k] = r
    counts: dict[str, int] = {}
    unknown = 0
    for r in seen.values():
        v = _value(r, by)
        if v is None:
            unknown += 1
            continue
        counts[v] = counts.get(v, 0) + 1
    ordered = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    base_caveats = list(caveats)
    if scope_kind == "displayed_results":
        base_caveats.append("표시 수가 바뀌면 이 구성도 바뀝니다")
    elif scope_kind == "selected_records":
        base_caveats.append("비교함이 바뀌면 이 구성도 바뀝니다")
    else:
        base_caveats.append("수록 레코드 구성이며 지원 규모의 증감으로 읽지 않습니다")
    if by == "selection_year":
        base_caveats.append("계속과제가 반복 수록될 수 있어 해당 연도 신규 선정 건수가 아닙니다")
    return ScopedDistribution(scope_kind=scope_kind, by=by, n=len(seen), n_unknown=unknown,
                              counts=ordered, record_ids=tuple(seen.keys()),
                              run_ids=tuple(run_ids), filters=dict(filters or {}),
                              caveats=tuple(base_caveats))


def check_invariants(d: ScopedDistribution) -> list[str]:
    """범위별 불변성 (W-T21). 위반 목록을 돌려준다 — 비어 있으면 정상."""
    problems = []
    if sum(d.counts.values()) + d.n_unknown != d.n:
        problems.append("구성 합계 + 미상 ≠ 대상 수")
    if len(d.record_ids) != d.n:
        problems.append("레코드 ID 수 ≠ 대상 수 (중복 집계)")
    if any(v <= 0 for v in d.counts.values()):
        problems.append("관측되지 않은 값이 0 건으로 채워짐")
    if d.scope_kind not in SCOPE_KINDS:
        problems.append(f"허용되지 않은 범위: {d.scope_kind}")
    return problems


def contains_trend_language(text: str) -> bool:
    """출력 문자열에 금지 문구가 있는지 (v2 §12.2)."""
    return any(w in text for w in FORBIDDEN_TREND_WORDS)


def describe(d: ScopedDistribution) -> str:
    """한 줄 설명. 범위·대상 수·미상 수를 항상 붙인다. 추세 문구는 만들지 않는다."""
    unk = f", 미상 {d.n_unknown}건" if d.n_unknown else ""
    return f"{d.label} {d.n}건 기준{unk}"
