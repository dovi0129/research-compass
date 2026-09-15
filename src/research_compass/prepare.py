"""정제 — ProjectRecord / FieldRecord 생성 (명세 5절).

원칙:
- 원본은 수정하지 않는다. 정제 결과와 제외 사유를 따로 남긴다.
- 개인식별 컬럼은 산출물에 넣지 않는다. (명세 5.3, 20.4)
- 제목만 같은 행을 같은 과제로 합치지 않는다.
- 공식 과제번호가 없으므로 집계 명칭은 '수록 레코드 수' 다.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

import pandas as pd

from .ingest import Snapshot

_WS = re.compile(r"\s+")


def normalize_text(s: str) -> str:
    """검색용 정규화. 기술 용어·숫자·기호를 무차별 삭제하지 않는다. (명세 6.3-1)"""
    s = unicodedata.normalize("NFKC", str(s))
    s = s.replace("​", "").replace("﻿", "")
    return _WS.sub(" ", s).strip()


def _rid(snapshot_id: str, row: int) -> str:
    h = hashlib.sha256(f"{snapshot_id}:{row}".encode()).hexdigest()[:12]
    return f"{snapshot_id}#{row}#{h}"


def build_projects(df: pd.DataFrame, snap: Snapshot, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """D1 -> ProjectRecord. 반환: (정제 결과, 제외 행)"""
    d = df.copy()
    d.insert(0, "_row", range(1, len(d) + 1))          # 헤더 제외 1부터
    for c in d.columns:
        if c != "_row":
            d[c] = d[c].astype(str).str.strip()

    sec = cfg["audit"].get("security_flag_column")
    excl_vals = set(cfg["audit"].get("security_exclude_values", []))
    flags: dict[int, list[str]] = {}

    drop = pd.Series(False, index=d.index)
    reasons = pd.Series("", index=d.index)

    blank_title = d["과제명"].eq("")
    drop |= blank_title
    reasons[blank_title] = "과제명 공백"

    if sec in d.columns:
        is_sec = d[sec].isin(excl_vals)
        drop |= is_sec
        reasons[is_sec & (reasons == "")] = f"{sec}={d.loc[is_sec, sec].iloc[0] if is_sec.any() else ''} (보안과제 기본 제외)"

    kept = d[~drop].copy()
    excluded = d[drop].copy()
    excluded["_exclude_reason"] = reasons[drop]

    prog_cols = [c for c in ["대사업명", "중사업명", "소사업명", "세부사업명"] if c in kept.columns]

    def year(v):
        v = str(v).strip()
        return int(v) if re.fullmatch(r"(19|20)\d{2}", v) else None

    out = pd.DataFrame({
        "record_id": [_rid(snap.snapshot_id, r) for r in kept["_row"]],
        "source_dataset_id": snap.dataset_id,
        "source_snapshot_id": snap.snapshot_id,
        "source_row": kept["_row"].values,
        "official_project_id": None,                    # 원본에 없음
        "title_raw": kept["과제명"].values,
        "title_normalized": [normalize_text(t) for t in kept["과제명"]],
        "selection_year": [year(v) for v in kept.get("선정년도", pd.Series([""] * len(kept)))],
        "business_year": [year(v) for v in kept.get("사업년도", pd.Series([""] * len(kept)))],
        "institution": kept.get("주관기관명", pd.Series([""] * len(kept))).values,
        "field_code": None,                             # 공식 연결키 없음
        "source_url": snap.source_url,
    })
    for c in prog_cols:
        out[f"program_{c}"] = kept[c].values
    out["search_text"] = out["title_normalized"]        # title_only_v1

    # 품질 플래그 (제거가 아니라 표시)
    short = out["search_text"].str.len() < 10
    out["quality_flags"] = [["short_title"] if s else [] for s in short]

    # 개인식별 컬럼은 산출물에 포함하지 않는다
    for pii in cfg["audit"].get("pii_columns", []):
        assert pii not in out.columns, f"{pii} 가 산출물에 포함됨"

    return out.reset_index(drop=True), excluded.reset_index(drop=True)


def build_fields(df: pd.DataFrame, snap: Snapshot, cfg: dict) -> pd.DataFrame:
    """D2 -> FieldRecord."""
    d = df.copy()
    d.insert(0, "_row", range(1, len(d) + 1))
    for c in d.columns:
        if c != "_row":
            d[c] = d[c].astype(str).str.strip()

    count_col = next(c for c in d.columns if "선정횟수" in c)
    src = next(s for s in cfg["sources"] if s["key"] == "D2")

    counts = pd.to_numeric(d[count_col], errors="coerce")
    out = pd.DataFrame({
        "field_record_id": [_rid(snap.snapshot_id, r) for r in d["_row"]],
        "source_dataset_id": snap.dataset_id,
        "source_snapshot_id": snap.snapshot_id,
        "source_row": d["_row"].values,
        "field_code": d["중심분야코드"].values,
        "field_name": d["과학기술표준명"].values,
        "field_name_normalized": [normalize_text(x) for x in d["과학기술표준명"]],
        "selection_count": counts.values,
        "count_column_raw": count_col,
        "period_label": src.get("period_basis_value"),
        "period_status": src.get("period_status", "unknown"),
        "count_unit": None,                              # 원문에 설명 없음
        "classification_scheme": cfg["classification"]["d2_scheme_version"],
        "major_code": d["중심분야코드"].str[:2].values,
        "mid_code": d["중심분야코드"].str[:4].values,
        "source_url": snap.source_url,
    })
    out["search_text"] = out["field_name_normalized"]
    return out
