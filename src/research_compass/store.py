"""정제 데이터 저장·로드.

parquet 을 쓰지 않는다. pyarrow 의 Parquet DLL 이 조직 보안정책(WDAC/AppLocker)에
차단되는 환경이 있어, 추가 바이너리 의존성 없는 CSV 로 고정한다.
CSV 는 사람이 직접 열어 확인할 수 있어 근거 추적에도 유리하다.

타입 손실을 막기 위해 컬럼별 스키마를 명시적으로 적용한다.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

LIST_SEP = "|"

# 읽을 때 복원할 타입. 여기에 없는 컬럼은 문자열로 둔다.
SCHEMAS: dict[str, dict[str, str]] = {
    "projects": {
        "source_row": "Int64",
        "selection_year": "Int64",
        "business_year": "Int64",
    },
    "fields": {
        "source_row": "Int64",
        "selection_count": "Int64",
    },
}
LIST_COLUMNS = {"projects": ["quality_flags"], "fields": []}


def path_for(processed_dir: Path, name: str) -> Path:
    return Path(processed_dir) / f"{name}.csv"


def write_table(df: pd.DataFrame, processed_dir: Path, name: str) -> Path:
    d = df.copy()
    for c in LIST_COLUMNS.get(name, []):
        if c in d.columns:
            d[c] = d[c].map(lambda v: LIST_SEP.join(v) if isinstance(v, (list, tuple)) else ("" if v is None else str(v)))
    p = path_for(processed_dir, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(p, index=False, encoding="utf-8-sig", lineterminator="\n")
    return p


def read_table(processed_dir: Path, name: str) -> pd.DataFrame:
    p = path_for(processed_dir, name)
    if not p.exists():
        raise SystemExit(
            f"[중단] {p} 가 없습니다. 먼저 정제를 실행하세요:\n"
            f"    python -m research_compass.cli prepare"
        )
    d = pd.read_csv(p, encoding="utf-8-sig", dtype=str, keep_default_na=False, na_values=[])
    for c, t in SCHEMAS.get(name, {}).items():
        if c in d.columns:
            d[c] = pd.to_numeric(d[c].replace("", None), errors="coerce").astype(t)
    for c in LIST_COLUMNS.get(name, []):
        if c in d.columns:
            d[c] = d[c].map(lambda s: [x for x in str(s).split(LIST_SEP) if x])
    return d
