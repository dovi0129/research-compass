"""W-T21 — 범위를 명시한 기술통계 (v2 §12.1~12.2)."""
from __future__ import annotations

import pytest

from research_compass import analytics as an

SNAP = "3049029-testsnap"


def rec(rid, year, program="학술·인문사회사업", snap=SNAP):
    return {"source_snapshot_id": snap, "record_id": rid, "selection_year": year,
            "program": program, "institution": "A대"}


def test_year_distribution_counts_and_unknown_separately():
    rows = [rec("r1", 2023), rec("r2", 2024), rec("r3", 2023), rec("r4", None), rec("r5", float("nan"))]
    d = an.distribution(rows, "selection_year", "displayed_results", run_ids=["run_x"])
    assert d.n == 5
    assert d.counts == {"2023": 2, "2024": 1}
    assert d.n_unknown == 2                      # 결측은 따로 센다. 0 으로 바꾸지 않는다
    assert "2025" not in d.counts                # 관측되지 않은 연도는 키 자체가 없다 (0 건 아님)
    assert an.check_invariants(d) == []
    assert d.run_ids == ("run_x",)


def test_duplicate_record_across_perspectives_counted_once():
    rows = [rec("r1", 2023), rec("r1", 2023), rec("r2", 2024)]
    d = an.distribution(rows, "selection_year", "selected_records")
    assert d.n == 2 and d.counts == {"2023": 1, "2024": 1}
    assert len(d.record_ids) == 2
    assert an.check_invariants(d) == []


def test_same_record_id_different_snapshot_is_distinct():
    rows = [rec("r1", 2023), rec("r1", 2023, snap="other-snap")]
    d = an.distribution(rows, "selection_year", "selected_records")
    assert d.n == 2


def test_calibrated_scope_is_refused():
    with pytest.raises(an.ScopeError):
        an.distribution([rec("r1", 2023)], "selection_year", "calibrated_relevant_corpus")


def test_unknown_scope_is_refused():
    with pytest.raises(an.ScopeError):
        an.distribution([], "selection_year", "everything")


def test_empty_input_is_a_valid_zero_scope():
    d = an.distribution([], "program", "selected_records")
    assert d.n == 0 and d.counts == {} and d.n_unknown == 0
    assert an.check_invariants(d) == []


def test_program_distribution_sorted_by_count_then_name():
    rows = [rec("r1", 2023, "B사업"), rec("r2", 2023, "A사업"), rec("r3", 2023, "B사업"),
            rec("r4", 2023, "")]
    d = an.distribution(rows, "program", "displayed_results")
    assert list(d.counts) == ["B사업", "A사업"]
    assert d.n_unknown == 1


def test_describe_has_scope_and_no_trend_language():
    rows = [rec("r1", 2023), rec("r2", 2024), rec("r3", None)]
    for scope in an.SCOPE_KINDS:
        d = an.distribution(rows, "selection_year", scope)
        text = an.describe(d) + " " + " ".join(d.caveats)
        assert an.SCOPE_LABELS[scope] in text
        assert "3건" in an.describe(d) and "미상 1건" in an.describe(d)
        assert not an.contains_trend_language(text)


def test_dataset_scope_carries_d012_caveat():
    d = an.distribution([rec("r1", 2023)], "selection_year", "dataset_snapshot")
    assert any("증감으로 읽지 않" in c for c in d.caveats)                # 문구 어투는 바뀔 수 있어도 D-012 경고는 남아야 한다
    assert any("신규 선정 건수가 아닙" in c for c in d.caveats)


def test_to_dict_records_scope_fields():
    d = an.distribution([rec("r1", 2023)], "selection_year", "displayed_results",
                        run_ids=["run_1"], filters={"years": [2023]})
    out = d.to_dict()
    for k in ("scope_kind", "by", "n", "n_unknown", "counts", "record_ids", "run_ids",
              "filters", "caveats", "label"):
        assert k in out
    assert out["scope_kind"] == "displayed_results" and out["filters"] == {"years": [2023]}


def test_invariant_checker_detects_zero_fill_and_mismatch():
    d = an.distribution([rec("r1", 2023)], "selection_year", "displayed_results")
    zero_fill = an.ScopedDistribution(scope_kind=d.scope_kind, by=d.by, n=d.n, n_unknown=d.n_unknown,
                                      counts={"2023": 1, "2025": 0}, record_ids=d.record_ids)
    assert any("0 건" in p for p in an.check_invariants(zero_fill))
    mismatch = an.ScopedDistribution(scope_kind=d.scope_kind, by=d.by, n=d.n, n_unknown=d.n_unknown,
                                     counts={"2023": 2}, record_ids=d.record_ids)
    assert any("합계" in p for p in an.check_invariants(mismatch))
    dup = an.ScopedDistribution(scope_kind=d.scope_kind, by=d.by, n=2, n_unknown=0,
                                counts={"2023": 2}, record_ids=("a",))
    assert any("중복" in p for p in an.check_invariants(dup))


def test_trend_words_detected():
    assert an.contains_trend_language("2024년 대비 증가율 12%")
    assert not an.contains_trend_language("현재 표시된 검색 후보 5건 기준")
