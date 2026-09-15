"""국가과학기술표준분류체계 버전 판별 및 D2 코드 검증.

배경:
- D2(`한국연구재단_선정과제 연구분야`)의 `중심분야코드` 는 6자리 `AA9999` 형식이다.
- 2023년 개정판(KISTEP 20251231)과는 6자리 정확 일치율이 12.81% 에 그친다.
- 2018년 체계(KISTEP 20210923 `과학기술표준분류정보`)에는 `HA`~`HE`, `SA`~`SI` 대분류가 존재한다.
  2023년 개정에서 인문사회가 `HF`/`HG`/`HH` 로 재편되었기 때문이다.

따라서 D2 의 기준 분류체계를 먼저 판별하고, 그 결과에 따라 모집단을 정한다.

정책:
- 2023 표는 **모집단 산정용이 아니라 2018→2023 신구 crosswalk 용도**로만 쓴다.
- 부재 코드는 `unobserved` 다. `선정 0건` 이 아니다.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict, field

import pandas as pd

# 2018 체계의 연구분야(RCSARE) 대분류 33종
CORE_2018 = tuple("EA EB EC ED EE EF EG EH EI HA HB HC HD HE LA LB LC "
                  "NA NB NC ND OA OB OC SA SB SC SD SE SF SG SH SI".split())

_EN_TAIL = re.compile(r"\([^()]*[A-Za-z][^()]*\)\s*$")
_MID_HEADER = re.compile(r"^[A-Z]{2}\d{2}\.")
_PUNCT = re.compile(r"[\s/·,()\[\]{}\-–—~‧]+")


def strip_english_tail(s: str) -> str:
    """'대수학(Algebra)' -> '대수학'. 한글 괄호 주석은 보존한다."""
    return _EN_TAIL.sub("", str(s)).strip()


def normalize_name(s: str) -> str:
    return _PUNCT.sub("", unicodedata.normalize("NFKC", str(s))).lower()


def load_2018_reference(df: pd.DataFrame) -> pd.DataFrame:
    """KISTEP `과학기술표준분류정보` 원본에서 연구분야(RCSARE) 소분류 목록을 복원한다.

    이 원본에는 소분류 6자리 코드 컬럼이 없다. 중분류코드(4자리) + 소분류명(제목)만 있다.
    따라서 6자리 수준의 모집단은 이 자료만으로 확정할 수 없다.
    """
    d = df.copy()
    for c in d.columns:
        d[c] = d[c].astype(str).str.strip()
    d = d[(d["분류코드"] == "RCSARE")
          & (d["대분류코드"].isin(CORE_2018))
          & (d["중분류코드"].str.len() == 4)]
    d = d[~d["제목"].str.match(_MID_HEADER)]          # 중분류 헤더 행 제거
    out = pd.DataFrame({
        "major_code": d["중분류코드"].str[:2],
        "mid_code": d["중분류코드"],
        "mid_name": d["중분류코드한글명"],
        "minor_name": d["제목"].map(strip_english_tail),
    }).drop_duplicates()
    out["minor_name_norm"] = out["minor_name"].map(normalize_name)
    return out.reset_index(drop=True)


@dataclass
class VersionCheck:
    version_label: str
    d2_rows: int
    major_match: int
    major_rate: float
    mid_match: int
    mid_rate: float
    name_strict_match: int
    name_strict_rate: float
    name_contained_match: int
    name_contained_rate: float
    code_name_consistent: int
    code_name_conflict: int
    unmatched_majors: list[str] = field(default_factory=list)
    unmatched_mids: list[str] = field(default_factory=list)
    unexplained_names: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def verify_against_2018(d2: pd.DataFrame, ref: pd.DataFrame,
                        code_col: str = "중심분야코드",
                        name_col: str = "과학기술표준명") -> VersionCheck:
    d2 = d2.copy()
    for c in d2.columns:
        d2[c] = d2[c].astype(str).str.strip()
    code, name = d2[code_col], d2[name_col]

    majors = set(ref["major_code"])
    mids = set(ref["mid_code"])
    names = set(ref["minor_name_norm"])
    by_mid: dict[str, list[tuple[str, str]]] = {}
    mids_by_name: dict[str, set[str]] = {}
    for r in ref.itertuples(index=False):
        by_mid.setdefault(r.mid_code, []).append((r.minor_name, r.minor_name_norm))
        mids_by_name.setdefault(r.minor_name_norm, set()).add(r.mid_code)

    m2 = code.str[:2].isin(majors)
    m4 = code.str[:4].isin(mids)
    nstrict = name.map(normalize_name).isin(names)

    contained, unexplained, consistent, conflict = 0, [], 0, 0
    for c, n in zip(code, name):
        nn = normalize_name(n)
        owners = mids_by_name.get(nn)
        if owners:
            consistent += 1 if c[:4] in owners else 0
            conflict += 0 if c[:4] in owners else 1
            contained += 1
            continue
        # 같은 중분류 안에서 포함 관계로 설명되는가 (예: '현대소설(국문학)' vs '현대소설')
        cands = by_mid.get(c[:4], [])
        if any(nn in cn or cn in nn for _, cn in cands):
            contained += 1
            consistent += 1
        else:
            unexplained.append({"code": c, "d2_name": n,
                                "mid_candidates": [x for x, _ in cands][:4]})

    n = len(d2)
    return VersionCheck(
        version_label="KISTEP 2018 국가과학기술표준분류체계 (연구분야 RCSARE)",
        d2_rows=n,
        major_match=int(m2.sum()), major_rate=round(float(m2.mean()), 6),
        mid_match=int(m4.sum()), mid_rate=round(float(m4.mean()), 6),
        name_strict_match=int(nstrict.sum()), name_strict_rate=round(float(nstrict.mean()), 6),
        name_contained_match=contained, name_contained_rate=round(contained / n, 6),
        code_name_consistent=consistent, code_name_conflict=conflict,
        unmatched_majors=sorted(set(code[~m2].str[:2])),
        unmatched_mids=sorted(set(code[~m4].str[:4])),
        unexplained_names=unexplained[:50],
    )


def population_status(ref: pd.DataFrame, d2: pd.DataFrame,
                      code_col: str = "중심분야코드") -> dict:
    """모집단(unobserved) 산정 가능 여부.

    2018 원본에 소분류 6자리 코드가 없으므로 코드 수준 차집합을 확정할 수 없다.
    명칭 수준의 추정치는 참고로만 제시하고 확정 결과로 쓰지 않는다.
    """
    obs_codes = set(d2[code_col].astype(str).str.strip())
    obs_mids = {c[:4] for c in obs_codes}
    scope = ref[ref["mid_code"].isin(obs_mids)]
    return {
        "status": "blocked",
        "reason": "2018 체계 참조자료(KISTEP 20210923)에 소분류 6자리 코드 컬럼이 없어 "
                  "코드 수준 차집합을 확정할 수 없음",
        "absent_code_semantics": "unobserved",
        "forbid_zero_label": True,
        "observed_codes": len(obs_codes),
        "observed_mid_codes": len(obs_mids),
        "reference_minor_names_in_scope": int(scope["minor_name_norm"].nunique()),
        "name_level_estimate_only": int(scope["minor_name_norm"].nunique()) - len(obs_codes),
        "note": "위 추정치는 명칭 기준이며 확정 결과가 아니다. "
                "소분류 코드가 포함된 2018 체계 코드표를 확보해야 확정할 수 있다.",
    }
