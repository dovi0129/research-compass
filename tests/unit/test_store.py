"""CSV 저장·복원 왕복 테스트 (parquet 미사용 확인 포함)."""
from __future__ import annotations

import pandas as pd
import pytest

from research_compass.store import path_for, read_table, write_table


def test_roundtrip_preserves_types_and_lists(tmp_path):
    df = pd.DataFrame({
        "record_id": ["a", "b", "c"],
        "source_row": pd.array([1, 2, 3], dtype="Int64"),
        "selection_year": pd.array([2023, None, 2025], dtype="Int64"),
        "business_year": pd.array([2023, 2024, None], dtype="Int64"),
        "title_raw": ["가, 나", '따옴표 "포함"', "줄바꿈 없음"],
        "quality_flags": [["short_title"], [], ["short_title", "masked"]],
    })
    write_table(df, tmp_path, "projects")
    back = read_table(tmp_path, "projects")

    assert back["record_id"].tolist() == ["a", "b", "c"]
    assert back["source_row"].tolist() == [1, 2, 3]
    assert back["selection_year"].isna().tolist() == [False, True, False]
    assert back["selection_year"].dropna().tolist() == [2023, 2025]
    assert back["title_raw"].tolist() == df["title_raw"].tolist()   # 쉼표·따옴표 보존
    assert back["quality_flags"].tolist() == [["short_title"], [], ["short_title", "masked"]]


def test_written_file_is_csv_not_parquet(tmp_path):
    write_table(pd.DataFrame({"record_id": ["a"]}), tmp_path, "projects")
    p = path_for(tmp_path, "projects")
    assert p.suffix == ".csv"
    assert p.read_bytes()[:4] != b"PAR1"          # parquet 매직 바이트가 아님
    assert p.read_text(encoding="utf-8-sig").startswith("record_id")


def test_missing_file_gives_actionable_error(tmp_path):
    with pytest.raises(SystemExit, match="prepare"):
        read_table(tmp_path, "projects")


def test_field_counts_survive_roundtrip(tmp_path):
    df = pd.DataFrame({
        "field_code": ["HB0902", "HD0206"],
        "source_row": pd.array([1, 2], dtype="Int64"),
        "selection_count": pd.array([56, None], dtype="Int64"),
    })
    write_table(df, tmp_path, "fields")
    back = read_table(tmp_path, "fields")
    assert back["field_code"].tolist() == ["HB0902", "HD0206"]      # 선행문자 보존
    assert back["selection_count"].isna().tolist() == [False, True]  # 결측이 0 으로 변하지 않음
