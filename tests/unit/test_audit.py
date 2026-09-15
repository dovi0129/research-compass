"""감사 로직 단위 테스트 (명세 19절 T-01~T-07 대응)."""
from __future__ import annotations

import io
import textwrap
from pathlib import Path

import pandas as pd
import pytest

from research_compass.audit import (audit_fields, audit_join, audit_projects,
                                    basic_checks, read_raw)
from research_compass.capabilities import decide
from research_compass.ingest import detect_encoding, looks_like_html, register

ACFG = {
    "encoding_candidates": ["utf-8-sig", "utf-8", "cp949", "euc-kr"],
    "pii_columns": ["연구책임자명", "연구자번호"],
    "security_flag_column": "보안과제여부",
}


def df_from(csv_text: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(textwrap.dedent(csv_text).strip()),
                       dtype=str, keep_default_na=False, na_values=[])


def find(findings, check):
    return next((f for f in findings if f.check == check), None)


# --- T-01: 정상·오류 CSV, 인코딩 ---------------------------------------
def test_html_page_is_rejected(tmp_path: Path):
    p = tmp_path / "fake.csv"
    p.write_bytes(b"<!DOCTYPE html><html><head><title>login</title></head>")
    with pytest.raises(ValueError, match="HTML"):
        register(p, "D1", "3049029", "t", "u", ACFG["encoding_candidates"])


def test_cp949_is_detected():
    raw = "과제명,선정년도\n한글제목,2023\n".encode("cp949")
    enc, conf = detect_encoding(raw, ["utf-8", "cp949"])
    assert enc == "cp949" and conf == "ok"


def test_looks_like_html():
    assert looks_like_html(b"  <html>hi</html>")
    assert not looks_like_html(b"a,b\n1,2\n")


# --- T-02: 필수 제목 결측 ----------------------------------------------
def test_blank_title_is_reported_not_filled():
    df = df_from("""
        사업년도,선정년도,과제명,주관기관명,보안과제여부
        2024,2023,실제 과제명,A,N
        2024,2023,,B,N
    """)
    f = find(audit_projects(df, ACFG), "과제명 결측/길이")
    assert f.status == "warn" and f.evidence["blank"] == 1


# --- T-03: 완전 중복 vs 제목만 같은 행 ----------------------------------
def test_duplicate_title_is_not_merged_with_full_duplicate():
    df = df_from("""
        사업년도,선정년도,과제명,주관기관명,보안과제여부
        2024,2023,같은제목,A,N
        2024,2022,같은제목,B,N
    """)
    f = find(audit_projects(df, ACFG), "중복-제목 기준")
    assert f.evidence["dup_title_only"] == 2
    assert f.evidence["dup_same_context"] == 0   # 기관·연도가 달라 같은 과제로 보지 않음


# --- T-04: 코드 선행 0 · 연도 파싱 --------------------------------------
def test_leading_zero_in_field_code_is_preserved():
    df = df_from("""
        과학기술표준명,중심분야코드,2025년 선정횟수
        인공지능,007,10
        전력전자,0071,20
    """)
    f = find(audit_fields(df, None), "분야코드 체계")
    assert f.evidence["leading_zero"] == 2
    assert f.evidence["length_distribution"] == {"3": 1, "4": 1}


def test_business_and_selection_year_are_not_conflated():
    df = df_from("""
        사업년도,선정년도,과제명,주관기관명,보안과제여부
        2025,2021,과제 하나,A,N
        2025,,과제 둘,B,N
    """)
    findings = audit_projects(df, ACFG)
    sel = find(findings, "연도-선정년도")
    biz = find(findings, "연도-사업년도")
    assert sel.evidence["valid"] == 1 and sel.evidence["invalid"] == 1
    assert biz.evidence["valid"] == 2
    assert find(findings, "연도-두 컬럼 관계").evidence["identical_rows"] == 0


# --- T-05: 빈 개수 · 미집계 · 실제 0 ------------------------------------
def test_missing_count_is_not_treated_as_zero():
    df = df_from("""
        과학기술표준명,중심분야코드,2025년 선정횟수
        가,001,0
        나,002,
        다,003,-
    """)
    f = next(x for x in audit_fields(df, None) if x.check.startswith("선정횟수 값-"))
    assert f.evidence["blank"] == 1
    assert f.evidence["parse_fail"] == 1
    assert f.evidence["valid"] == 1 and f.evidence["min"] == 0.0


# --- T-06: 통계 기간 충돌 -> 비교·후보 비활성화 -------------------------
def test_period_conflict_disables_counts_and_candidates():
    d2 = df_from("""
        과학기술표준명,중심분야코드,2025년 선정횟수
        가,001,10
        나,002,20
    """)
    d1 = df_from("""
        사업년도,선정년도,과제명,주관기관명,보안과제여부
        2025,2023,과제,A,N
    """)
    d2f = audit_fields(d2, "2023년 연구분야별 선정과제 현황")
    assert find(d2f, "기준기간 충돌").status == "blocker"
    caps = decide(basic_checks(d1, _snap(), None), audit_projects(d1, ACFG),
                  basic_checks(d2, _snap(), None), d2f, audit_join(d1, d2))
    assert caps["field_counts"]["status"] == "disabled"
    assert caps["opportunity_candidates"]["status"] == "disabled"
    assert caps["comparable_trend"]["status"] == "disabled"


def test_single_count_column_disables_trend():
    df = df_from("""
        과학기술표준명,중심분야코드,2025년 선정횟수
        가,001,10
    """)
    assert find(audit_fields(df, None), "선정횟수 컬럼 수").status == "blocker"


# --- T-07: 과제-분야 연결키 없음 ----------------------------------------
def test_no_join_key_between_d1_and_d2():
    d1 = df_from("""
        사업년도,선정년도,과제명,주관기관명,보안과제여부
        2025,2023,과제,A,N
    """)
    d2 = df_from("""
        과학기술표준명,중심분야코드,2025년 선정횟수
        가,001,10
    """)
    j = audit_join(d1, d2)
    assert find(j, "공통 컬럼명").status == "blocker"
    assert find(j, "값 수준 연결키 후보").status == "blocker"


def _snap():
    from research_compass.ingest import Snapshot
    return Snapshot("D", "0", "t", "u", "f.csv", "f.csv", 1, "a" * 64, "s", "now",
                    "utf-8", "ok", ",", [])
