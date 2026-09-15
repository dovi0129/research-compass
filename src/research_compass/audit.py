"""데이터 감사 (명세 4.4). 실제 원본에서 확인되는 것만 기록한다.

원칙:
- 결측을 0 으로 대체하지 않는다.
- 제목만 같은 행을 같은 과제로 합치지 않는다.
- 사업년도와 선정년도를 혼용하지 않는다.
- 확인되지 않은 항목은 unknown 으로 남긴다.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .ingest import Snapshot

MOJIBAKE = re.compile(r"[��]")
YEAR = re.compile(r"^(19|20)\d{2}$")


@dataclass
class Finding:
    check: str
    status: str          # ok | warn | blocker | unknown
    detail: str
    evidence: dict = field(default_factory=dict)


def read_raw(snap: Snapshot) -> pd.DataFrame:
    """원본을 문자열 그대로 읽는다. 결측 자동 변환을 하지 않는다."""
    return pd.read_csv(
        snap.file_path,
        encoding=snap.encoding,
        sep=snap.delimiter,
        dtype=str,
        keep_default_na=False,
        na_values=[],
    )


def _blank(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip() == ""


def basic_checks(df: pd.DataFrame, snap: Snapshot, registry_rows: int | None) -> list[Finding]:
    out: list[Finding] = []
    rows, cols = df.shape
    out.append(Finding(
        "규모", "ok",
        f"원본 {rows}행 × {cols}열",
        {"rows": rows, "cols": cols, "registry_row_count": registry_rows},
    ))
    if registry_rows is not None and rows != registry_rows:
        out.append(Finding(
            "규모-등록표기 대조", "warn",
            f"등록 페이지 표기 {registry_rows}행과 실제 {rows}행이 다릅니다. "
            "등록 표기에 맞춰 행을 조정하지 않습니다.",
            {"registry": registry_rows, "actual": rows},
        ))

    mojibake_cols = {
        c: int(df[c].astype(str).str.contains(MOJIBAKE, regex=True).sum())
        for c in df.columns
    }
    bad = {c: n for c, n in mojibake_cols.items() if n}
    out.append(Finding(
        "인코딩-깨진문자", "blocker" if bad else "ok",
        f"치환문자 포함 셀: {bad}" if bad else "깨진 문자 없음",
        {"per_column": bad},
    ))

    dup_full = int(df.duplicated(keep=False).sum())
    out.append(Finding(
        "완전중복행", "warn" if dup_full else "ok",
        f"모든 컬럼이 동일한 행 {dup_full}건 (원본 행수·그룹 크기는 보존)",
        {"count": dup_full},
    ))
    return out


def audit_projects(df: pd.DataFrame, cfg: dict) -> list[Finding]:
    """D1: 과제정보."""
    out: list[Finding] = []
    cols = set(df.columns)

    title_col = "과제명"
    if title_col not in cols:
        return [Finding("과제명 컬럼", "blocker", f"'{title_col}' 컬럼이 없습니다. 검색 불가.", {"columns": sorted(cols)})]

    blank = int(_blank(df[title_col]).sum())
    lengths = df[title_col].astype(str).str.len()
    out.append(Finding(
        "과제명 결측/길이", "warn" if blank else "ok",
        f"공백 과제명 {blank}건. 길이 중앙값 {int(lengths.median())}자, 최대 {int(lengths.max())}자, "
        f"10자 미만 {int((lengths < 10).sum())}건",
        {"blank": blank, "median_len": int(lengths.median()),
         "max_len": int(lengths.max()), "short_lt10": int((lengths < 10).sum())},
    ))

    # '보안' 은 정상 연구 주제어로 자주 쓰이므로 마스킹 신호에서 제외한다.
    masked = int(df[title_col].astype(str).str.contains(r"[*]{2,}|[X]{3,}|비공개|공개제한", regex=True).sum())
    if masked:
        out.append(Finding(
            "과제명 마스킹", "warn",
            f"마스킹/비공개로 보이는 과제명 {masked}건. 검색 대상에서 격리 검토 필요.",
            {"count": masked},
        ))

    dup_title_only = int(df.duplicated(subset=[title_col], keep=False).sum())
    exact_group_cols = [c for c in [title_col, "주관기관명", "선정년도"] if c in cols]
    dup_same_ctx = int(df.duplicated(subset=exact_group_cols, keep=False).sum())
    out.append(Finding(
        "중복-제목 기준", "warn" if dup_title_only else "ok",
        f"제목만 같은 행 {dup_title_only}건 / 제목+기관+선정년도까지 같은 행 {dup_same_ctx}건. "
        "제목이 같다는 이유만으로 삭제하지 않습니다. (계속과제 반복 수록 가능성)",
        {"dup_title_only": dup_title_only, "dup_same_context": dup_same_ctx,
         "group_cols": exact_group_cols},
    ))

    for ycol in ["선정년도", "사업년도"]:
        if ycol not in cols:
            out.append(Finding(f"연도-{ycol}", "warn", f"'{ycol}' 컬럼 없음", {}))
            continue
        vals = df[ycol].astype(str).str.strip()
        valid = vals.str.match(YEAR)
        years = vals[valid].astype(int)
        out.append(Finding(
            f"연도-{ycol}", "ok" if valid.all() else "warn",
            f"{ycol}: 유효 {int(valid.sum())}건, 파싱실패/공백 {int((~valid).sum())}건, "
            f"범위 {int(years.min()) if len(years) else '-'}~{int(years.max()) if len(years) else '-'}, "
            f"고유값 {years.nunique()}개",
            {"valid": int(valid.sum()), "invalid": int((~valid).sum()),
             "min": int(years.min()) if len(years) else None,
             "max": int(years.max()) if len(years) else None,
             "distinct": int(years.nunique()),
             "top": {str(k): int(v) for k, v in Counter(years.tolist()).most_common(12)}},
        ))

    if {"선정년도", "사업년도"} <= cols:
        a = df["사업년도"].astype(str).str.strip()
        b = df["선정년도"].astype(str).str.strip()
        same = int((a == b).sum())
        identical = same == len(df)
        out.append(Finding(
            "연도-두 컬럼 관계", "warn" if identical else "ok",
            (f"사업년도와 선정년도가 전체 {len(df)}행에서 완전히 동일합니다. "
             "두 컬럼이 독립 정보를 담고 있지 않으므로 계속과제(사업년도>선정년도) 여부를 "
             "이 데이터만으로 판별할 수 없습니다. 연도 축은 한 개만 사용합니다."
             if identical else
             f"사업년도==선정년도 {same}건 / 전체 {len(df)}건. "
             "두 연도를 같은 의미로 혼용하지 않습니다. 차이나는 행은 계속과제 신호일 수 있습니다."),
            {"identical_rows": same, "total": len(df), "fully_identical": identical},
        ))

    sec = cfg.get("security_flag_column")
    if sec in cols:
        dist = Counter(df[sec].astype(str).str.strip().tolist())
        out.append(Finding(
            "보안과제 표시", "warn",
            f"{sec} 값 분포: {dict(dist.most_common(10))}. "
            "의미가 확인되기 전에는 공개 가능으로 단정하지 않고 기본 제외 후보로 둡니다.",
            {"distribution": {str(k): int(v) for k, v in dist.most_common(10)}},
        ))

    pii = [c for c in cfg.get("pii_columns", []) if c in cols]
    if pii:
        out.append(Finding(
            "개인식별 컬럼", "warn",
            f"{pii} 는 임베딩·화면·내보내기에서 제외합니다. (명세 5.3, 20.4)",
            {"columns": pii},
        ))

    prog = [c for c in ["대사업명", "중사업명", "소사업명", "세부사업명"] if c in cols]
    if prog:
        blanks = {c: int(_blank(df[c]).sum()) for c in prog}
        uniq = {c: int(df[c].nunique()) for c in prog}
        out.append(Finding(
            "사업명 계층", "ok",
            f"계층 컬럼 {prog} / 공백 {blanks} / 고유값 {uniq}. "
            "사업명은 기본 임베딩 텍스트에서 제외하고 별도 실험으로만 채택합니다. (명세 6.2)",
            {"blank": blanks, "distinct": uniq},
        ))

    if "주관기관명" in cols:
        out.append(Finding(
            "주관기관", "ok",
            f"고유 기관 {df['주관기관명'].nunique()}개, 공백 {int(_blank(df['주관기관명']).sum())}건",
            {"distinct": int(df["주관기관명"].nunique())},
        ))

    # 연도별 사업 구성 변화 — 연도 분포 해석의 함정
    if {"대사업명", "선정년도"} <= cols:
        ct = pd.crosstab(df["대사업명"].astype(str).str.strip(),
                         df["선정년도"].astype(str).str.strip())
        years = list(ct.columns)
        vanished = [p for p in ct.index
                    if ct.loc[p, years[0]] > 0 and ct.loc[p, years[-1]] == 0]
        dominant = ct.sum(axis=1).idxmax()
        dom_share = ct.sum(axis=1).max() / len(df)
        last_share = ct.loc[dominant, years[-1]] / ct[years[-1]].sum() if ct[years[-1]].sum() else 0
        out.append(Finding(
            "연도별 사업 구성 변화", "blocker" if vanished else "ok",
            (f"수록 연도 {years[0]}~{years[-1]}. 최다 사업은 '{dominant}' 로 전체의 {dom_share:.1%}, "
             f"마지막 연도에는 {last_share:.1%} 를 차지합니다. "
             f"마지막 연도에 레코드가 0이 된 사업 {len(vanished)}개: {vanished[:5]}. "
             "**연도별 레코드 수 감소는 연구지원 축소가 아니라 수록 사업 구성의 변화일 수 있습니다.** "
             "연도 분포를 국가 전체 추세로 해석하지 않습니다. (명세 8.2)"),
            {"years": years, "dominant_program": dominant,
             "dominant_share": round(float(dom_share), 4),
             "dominant_share_last_year": round(float(last_share), 4),
             "vanished_programs": vanished,
             "per_year_totals": {str(y): int(ct[y].sum()) for y in years}},
        ))

    out.append(Finding(
        "공식 과제번호", "blocker" if "과제번호" not in cols else "ok",
        "원본에 고유 과제번호가 없어 독립 과제 수를 확정할 수 없습니다. "
        "집계 명칭은 '수록 레코드 수'로 제한합니다. (명세 5.3)"
        if "과제번호" not in cols else "과제번호 컬럼 존재",
        {"columns": sorted(cols)},
    ))
    return out


def audit_fields(df: pd.DataFrame, registry_period_claim: str | None) -> list[Finding]:
    """D2: 연구분야 선정 현황."""
    out: list[Finding] = []
    cols = list(df.columns)

    name_col = next((c for c in cols if "표준명" in c or "분야명" in c), None)
    code_col = next((c for c in cols if "코드" in c), None)
    count_cols = [c for c in cols if "선정횟수" in c or "건수" in c]

    if name_col is None:
        return [Finding("분야명 컬럼", "blocker", "분야명 컬럼을 찾지 못했습니다.", {"columns": cols})]

    blank = int(_blank(df[name_col]).sum())
    out.append(Finding(
        "분야명", "warn" if blank else "ok",
        f"'{name_col}' 고유값 {df[name_col].nunique()}개 / 공백 {blank}건 / 전체 {len(df)}행",
        {"column": name_col, "distinct": int(df[name_col].nunique()), "blank": blank},
    ))

    dup_name = int(df.duplicated(subset=[name_col], keep=False).sum())
    if dup_name:
        out.append(Finding(
            "분야명 중복", "warn",
            f"동일 분야명이 여러 행에 존재: {dup_name}건. 임베딩 중복 생성 방지 키가 필요합니다.",
            {"count": dup_name},
        ))

    if code_col:
        codes = df[code_col].astype(str).str.strip()
        lens = Counter(codes.str.len().tolist())
        leading_zero = int(codes.str.startswith("0").sum())
        out.append(Finding(
            "분야코드 체계", "warn",
            f"'{code_col}' 길이 분포 {dict(sorted(lens.items()))}, 선행 0 포함 {leading_zero}건, "
            f"고유 {codes.nunique()}개. 길이가 여러 종류면 상·하위 분류가 섞여 있을 수 있어 "
            "직접 비교·합계를 금지합니다. (명세 7.2)",
            {"length_distribution": {str(k): int(v) for k, v in sorted(lens.items())},
             "leading_zero": leading_zero, "distinct": int(codes.nunique())},
        ))

    if not count_cols:
        out.append(Finding("선정횟수 컬럼", "blocker", "선정횟수 컬럼을 찾지 못했습니다.", {"columns": cols}))
        return out

    out.append(Finding(
        "선정횟수 컬럼 수", "blocker" if len(count_cols) < 2 else "ok",
        f"선정횟수 컬럼 {count_cols}. 컬럼이 1개뿐이면 이 데이터만으로 시계열을 만들 수 없으므로 "
        "comparable_trend 는 비활성입니다. (명세 8.3)"
        if len(count_cols) < 2 else f"선정횟수 컬럼 {len(count_cols)}개 — 기간별 비교 가능성 검토 대상",
        {"columns": count_cols},
    ))

    col_years = sorted({m.group(0) for c in count_cols for m in [re.search(r"(19|20)\d{2}", c)] if m})
    claim_years = sorted(set(re.findall(r"(?:19|20)\d{2}", registry_period_claim or "")))
    if col_years and claim_years and set(col_years) != set(claim_years):
        out.append(Finding(
            "기준기간 충돌", "blocker",
            f"컬럼명 연도 {col_years} 와 등록 페이지 설명문 연도 {claim_years} 가 다릅니다. "
            "확정 전에는 period_status=conflicting 으로 두고 분야 간 비교·순위화·후보 생성을 중단합니다. "
            "(명세 4.2, 7.2, 9.4)",
            {"column_years": col_years, "description_years": claim_years,
             "description_raw": registry_period_claim},
        ))
    elif not claim_years:
        out.append(Finding(
            "기준기간", "unknown", "등록 페이지 설명문에서 기준기간을 확인하지 못했습니다.", {}))
    else:
        out.append(Finding(
            "기준기간", "ok", f"컬럼명과 설명문 연도가 일치: {col_years}", {"years": col_years}))

    for c in count_cols:
        s = df[c].astype(str).str.strip()
        empty = int((s == "").sum())
        numeric = pd.to_numeric(s.replace("", None), errors="coerce")
        parse_fail = int(numeric.isna().sum() - empty)
        negative = int((numeric < 0).sum())
        valid = numeric.dropna()
        out.append(Finding(
            f"선정횟수 값-{c}", "warn" if (empty or parse_fail or negative) else "ok",
            f"공백 {empty}건 / 숫자 파싱 실패 {parse_fail}건 / 음수 {negative}건. "
            f"유효 {len(valid)}건, 최소 {valid.min() if len(valid) else '-'}, "
            f"최대 {valid.max() if len(valid) else '-'}, 중앙값 {valid.median() if len(valid) else '-'}, "
            f"고유값 {valid.nunique() if len(valid) else 0}개. 결측을 0 으로 대체하지 않습니다.",
            {"blank": empty, "parse_fail": parse_fail, "negative": negative,
             "valid": int(len(valid)),
             "min": float(valid.min()) if len(valid) else None,
             "max": float(valid.max()) if len(valid) else None,
             "median": float(valid.median()) if len(valid) else None,
             "distinct": int(valid.nunique()) if len(valid) else 0,
             "q25_linear": float(valid.quantile(0.25, interpolation="linear")) if len(valid) else None},
        ))

    out.append(Finding(
        "집계 단위", "unknown",
        "원문에 집계 단위(과제 건수/연구자 수 등)에 대한 설명이 없어 count_unit 미확정. "
        "단위 미확정 상태에서는 화면에 원문 컬럼명을 그대로 표시합니다.",
        {},
    ))
    return out


def audit_join(d1: pd.DataFrame, d2: pd.DataFrame) -> list[Finding]:
    """D1↔D2 연결 가능성 (명세 7.3)."""
    common = sorted(set(d1.columns) & set(d2.columns))
    findings = [Finding(
        "공통 컬럼명", "blocker" if not common else "warn",
        f"공통 컬럼: {common or '없음'}",
        {"common_columns": common},
    )]

    # 값 수준의 우연한 겹침도 확인한다 (컬럼명이 달라도 코드가 같을 수 있으므로).
    code_cols_d2 = [c for c in d2.columns if "코드" in c]
    overlaps = {}
    for c2 in code_cols_d2:
        vals2 = set(d2[c2].astype(str).str.strip()) - {""}
        for c1 in d1.columns:
            vals1 = set(d1[c1].astype(str).str.strip()) - {""}
            inter = vals1 & vals2
            if inter and len(inter) >= max(5, 0.05 * len(vals2)):
                overlaps[f"{c1} ~ {c2}"] = len(inter)
    findings.append(Finding(
        "값 수준 연결키 후보", "ok" if overlaps else "blocker",
        f"의미 있는 값 겹침: {overlaps}" if overlaps else
        "두 데이터 사이에 값이 겹치는 코드 컬럼이 없습니다. "
        "project_field_join = disabled 를 유지하고, 분야명 임베딩 결과를 "
        "공식 분야 코드로 저장하지 않습니다. (명세 7.3)",
        {"overlaps": overlaps},
    ))
    return findings


STATUS_RANK = {"ok": 0, "unknown": 1, "warn": 2, "blocker": 3}


def worst(findings: list[Finding]) -> str:
    return max((f.status for f in findings), key=lambda s: STATUS_RANK[s], default="unknown")


def audit_candidate_feasibility(d1: pd.DataFrame, d2: pd.DataFrame) -> list[Finding]:
    """FR-04(연구기회 후보)가 실제 자료에서 성립하는지 사전 점검한다.

    명세 9.2 의 초기 규칙(하위 25% 기준, 비교 집단 5개 이상)이 이 데이터에서
    변별력을 갖는지 확인한다. 성립하지 않으면 규칙 자체를 재설계해야 한다.
    """
    out: list[Finding] = []
    count_cols = [c for c in d2.columns if "선정횟수" in c or "건수" in c]
    if not count_cols:
        return [Finding("후보 성립성", "unknown", "선정횟수 컬럼이 없어 점검 불가", {})]
    c = pd.to_numeric(d2[count_cols[0]], errors="coerce").dropna()

    q25 = float(c.quantile(0.25, interpolation="linear"))
    at_or_below = int((c <= q25).sum())
    share = at_or_below / len(c) if len(c) else 0.0
    out.append(Finding(
        "후보 규칙 변별력", "blocker" if share > 0.35 else ("warn" if share > 0.30 else "ok"),
        f"하위 25% 기준값 q25={q25:g}. 이 값 이하인 분야가 {at_or_below}/{len(c)}개 "
        f"({share:.1%})입니다. 동률이 많아 '상대적으로 적게 선정된 분야'가 전체의 "
        f"{share:.0%}에 해당하므로, 명세 9.2 의 하위 25% 규칙만으로는 후보의 변별력이 "
        "확보되지 않습니다. 실제 비교 대상 수와 기준값을 반드시 함께 표시해야 합니다. (명세 9.2)",
        {"q25": q25, "at_or_below": at_or_below, "total": int(len(c)), "share": round(share, 4),
         "value_counts_head": {str(k): int(v) for k, v in c.value_counts().sort_index().head(6).items()}},
    ))

    cmin = float(c.min())
    out.append(Finding(
        "0건 분야의 부재", "blocker" if cmin >= 1 else "ok",
        f"선정횟수 최소값이 {cmin:g}입니다. 0건인 분야가 한 건도 수록되어 있지 않으므로, "
        "이 자료는 '전체 연구분야 목록'이 아니라 **선정 실적이 있는 분야만 모은 목록**으로 보입니다. "
        "따라서 '한 번도 선정되지 않은 분야'는 이 데이터만으로는 관측할 수 없습니다. "
        "공식 과학기술표준분류 전체 코드표와 대조하지 않는 한 미탐색 영역을 완전히 제시할 수 없습니다."
        if cmin >= 1 else f"최소값 {cmin:g} — 0건 분야가 수록되어 있음",
        {"min": cmin, "rows": int(len(c))},
    ))

    # 기준기간 판별 단서: D2 총합을 D1 의 연도별 레코드 수와 대조한다.
    ycol = "선정년도" if "선정년도" in d1.columns else None
    if ycol:
        total = int(c.sum())
        per_year = d1[ycol].astype(str).str.strip().value_counts().to_dict()
        diffs = {y: total - int(n) for y, n in per_year.items()}
        best = min(diffs, key=lambda y: abs(diffs[y]))
        out.append(Finding(
            "기준기간 대조 단서", "warn",
            f"D2 선정횟수 합계 {total:,}. D1 연도별 레코드 수 "
            + ", ".join(f"{y}년 {int(n):,}" for y, n in sorted(per_year.items()))
            + f". 가장 가까운 연도는 **{best}년** (차이 {diffs[best]:+,}). "
            "이는 정황 근거일 뿐 공식 확인이 아니므로 period_status 는 conflicting 을 유지합니다. "
            "한국연구재단 확인으로만 verified 로 바꿉니다.",
            {"d2_total": total, "d1_rows_per_year": {str(k): int(v) for k, v in per_year.items()},
             "closest_year": best, "diff": diffs[best]},
        ))
    return out
