"""분류체계 버전 검증 단위 테스트 (P1-B)."""
from __future__ import annotations

import pandas as pd

from research_compass.classification import (CORE_2018, load_2018_reference,
                                             normalize_name, strip_english_tail,
                                             verify_against_2018)


def _ref_raw():
    return pd.DataFrame({
        "분류코드": ["RCSARE"] * 4,
        "대분류코드": ["HD", "HD", "NA", "TA"],
        "중분류코드": ["HD02", "HD02", "NA01", "TA01"],
        "중분류코드한글명": ["국문학", "국문학", "대수학", "대수학"],
        "제목": ["현대소설", "HD02. 국문학(Korean literature)",
                 "선형대수(Linear algebra)", "선형대수"],
    })


def test_strip_english_tail_keeps_korean_parens():
    assert strip_english_tail("대수학(Algebra)") == "대수학"
    assert strip_english_tail("현대소설(국문학)") == "현대소설(국문학)"


def test_core_2018_has_33_majors():
    assert len(CORE_2018) == 33
    assert {"HA", "HE", "SA", "SI"} <= set(CORE_2018)      # 2018 에만 있는 인문사회
    assert "HF" not in CORE_2018                            # 2023 개정 코드


def test_reference_drops_mid_header_rows_and_non_core():
    ref = load_2018_reference(_ref_raw())
    assert "TA" not in set(ref["major_code"])               # 한글전용 변형 제외
    assert not ref["minor_name"].str.startswith("HD02.").any()
    assert set(ref["minor_name"]) == {"현대소설", "선형대수"}


def test_containment_match_explains_korean_qualifier():
    ref = load_2018_reference(_ref_raw())
    d2 = pd.DataFrame({"중심분야코드": ["HD0206"], "과학기술표준명": ["현대소설(국문학)"]})
    v = verify_against_2018(d2, ref)
    assert v.major_rate == 1.0 and v.mid_rate == 1.0
    assert v.name_strict_rate == 0.0                        # 엄격 비교로는 불일치
    assert v.name_contained_rate == 1.0                     # 같은 중분류 안에서 설명됨
    assert v.unexplained_names == []


def test_unrelated_name_stays_unexplained():
    ref = load_2018_reference(_ref_raw())
    d2 = pd.DataFrame({"중심분야코드": ["HD0299"], "과학기술표준명": ["원자력공학"]})
    v = verify_against_2018(d2, ref)
    assert len(v.unexplained_names) == 1


def test_normalize_name():
    assert normalize_name("하/폐수 고도처리 및 핵심요소기술") == normalize_name("하폐수고도처리및핵심요소기술")
