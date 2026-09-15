"""D2 중심분야코드 ↔ 국가과학기술표준분류(KISTEP) 대조 (P1).

정책 (사용자 지시):
- KISTEP 은 NRF 데이터를 대체하는 핵심 데이터가 아니라 **코드·계층 복원용 보조 공공데이터**다.
- KISTEP 에 있으나 D2 에 없는 코드는 `0건` 이 아니라 **`unobserved`** 로 취급한다.
- 근거 없는 매칭을 만들지 않는다. 접두가 다른 체계는 억지로 잇지 않는다.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict, field

import pandas as pd


def normalize_name(s: str) -> str:
    """명칭 비교용 정규화. 의미를 바꾸지 않는 표기 차이만 제거한다."""
    s = unicodedata.normalize("NFKC", str(s))
    return re.sub(r"[\s/·,()\[\]{}\-–—~‧]+", "", s).lower()


@dataclass
class CrosswalkResult:
    d2_rows: int
    d2_codes: int
    kistep_rows: int
    kistep_major: int
    kistep_mid: int
    kistep_minor: int

    code_match: int
    code_match_rate: float
    name_exact: int
    name_exact_rate: float
    name_normalized: int
    name_normalized_rate: float

    in_scheme_prefixes: list[str] = field(default_factory=list)
    out_scheme_prefixes: list[str] = field(default_factory=list)
    in_scheme_rows: int = 0
    out_scheme_rows: int = 0
    in_scheme_match_rate: float = 0.0

    unobserved_in_scope: int = 0
    scope_minor_total: int = 0
    unresolved_rows: int = 0

    name_diff_samples: list[dict] = field(default_factory=list)
    unmatched_in_scheme: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def build(d2: pd.DataFrame, kistep: pd.DataFrame,
          code_col: str = "중심분야코드", name_col: str = "과학기술표준명") -> CrosswalkResult:
    d2 = d2.copy(); kistep = kistep.copy()
    for df in (d2, kistep):
        for c in df.columns:
            df[c] = df[c].astype(str).str.strip()

    k_minor = kistep.drop_duplicates("소분류코드")
    minor_name = dict(zip(k_minor["소분류코드"], k_minor["소분류코드명"]))
    major_codes = set(kistep["대분류코드"])

    code = d2[code_col]
    prefix = code.str[:2]
    in_scheme = prefix.isin(major_codes)          # KISTEP 체계에 속하는 접두
    hit = code.isin(minor_name)                   # 소분류코드 정확 일치

    matched = d2[hit].copy()
    matched["_k"] = matched[code_col].map(minor_name)
    exact = matched[name_col] == matched["_k"]
    normed = matched[name_col].map(normalize_name) == matched["_k"].map(normalize_name)

    # unobserved 는 D2 가 실제로 사용하는 KISTEP 대분류의 하위 소분류로 범위를 한정한다.
    used_majors = sorted(set(prefix[in_scheme]))
    scope = k_minor[k_minor["대분류코드"].isin(used_majors)]
    observed = set(code[hit])
    unobserved = sorted(set(scope["소분류코드"]) - observed)

    diff = matched[~normed][[code_col, name_col, "_k"]].rename(
        columns={code_col: "code", name_col: "d2_name", "_k": "kistep_name"})
    unmatched_in = d2[in_scheme & ~hit][[code_col, name_col]].rename(
        columns={code_col: "code", name_col: "d2_name"})

    n_in = int(in_scheme.sum())
    return CrosswalkResult(
        d2_rows=len(d2), d2_codes=int(code.nunique()),
        kistep_rows=len(kistep), kistep_major=int(kistep["대분류코드"].nunique()),
        kistep_mid=int(kistep["중분류코드"].nunique()), kistep_minor=int(k_minor["소분류코드"].nunique()),
        code_match=int(hit.sum()), code_match_rate=round(float(hit.mean()), 6),
        name_exact=int(exact.sum()), name_exact_rate=round(float(exact.mean()) if len(matched) else 0.0, 6),
        name_normalized=int(normed.sum()),
        name_normalized_rate=round(float(normed.mean()) if len(matched) else 0.0, 6),
        in_scheme_prefixes=used_majors,
        out_scheme_prefixes=sorted(set(prefix[~in_scheme])),
        in_scheme_rows=n_in, out_scheme_rows=int((~in_scheme).sum()),
        in_scheme_match_rate=round(float(hit[in_scheme].mean()) if n_in else 0.0, 6),
        unobserved_in_scope=len(unobserved), scope_minor_total=int(len(scope)),
        unresolved_rows=int((~in_scheme).sum()),
        name_diff_samples=diff.to_dict("records"),
        unmatched_in_scheme=unmatched_in.to_dict("records"),
    )


def gate(res: CrosswalkResult, min_rate: float) -> dict:
    """P1 통과 조건 판정. 전체 기준과 체계 내 기준을 분리한다."""
    return {
        "overall": {
            "rate": res.code_match_rate, "threshold": min_rate,
            "pass": res.code_match_rate >= min_rate,
        },
        "in_scheme_only": {
            "rate": res.in_scheme_match_rate, "threshold": min_rate,
            "pass": res.in_scheme_match_rate >= min_rate,
            "coverage_of_d2": round(res.in_scheme_rows / res.d2_rows, 6) if res.d2_rows else 0.0,
        },
    }
