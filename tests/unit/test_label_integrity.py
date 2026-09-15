"""라벨 출처·증분 키 무결성 (v2 §17.3·§17.5, W-T23).

핵심 요구: `keep=first` 로 충돌을 숨기지 않는다. 어긋난 항목은 채택하지 않고 문제로 보고한다.
"""
from __future__ import annotations

import pandas as pd
import pytest

from research_compass import evaluation as ev


def sheet(rows: list[dict]) -> pd.DataFrame:
    base = {"query_id": "", "query": "질의", "item_id": "", "title": "제목",
            "institution": "", "selection_year": "", "program": "",
            "label": "", "note": "", "labeler": "claude-sonnet(1차)"}
    return pd.DataFrame([{**base, **r} for r in rows])


def key(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{"query_id": r["query_id"], "item_id": r["item_id"],
                          "record_id": r["record_id"]} for r in rows])


def kinds(problems: list[dict]) -> set[str]:
    return {p["kind"] for p in problems}


# --- 정상 경로 ----------------------------------------------------------
def test_labels_are_keyed_by_query_perspective_and_record():
    s = sheet([{"query_id": "q1", "item_id": "iaaa", "label": "2"}])
    k = key([{"query_id": "q1", "item_id": "iaaa", "record_id": "r1"}])
    labels, problems = ev.collect_labels([("s1", s, k)])
    assert problems == []
    assert labels[("q1", "full", "r1")].label == "2"
    assert labels[("q1", "full", "r1")].source == "llm"


def test_unlabeled_rows_are_skipped_not_reported():
    s = sheet([{"query_id": "q1", "item_id": "iaaa", "label": ""}])
    k = key([{"query_id": "q1", "item_id": "iaaa", "record_id": "r1"}])
    labels, problems = ev.collect_labels([("s1", s, k)])
    assert labels == {} and problems == []


def test_same_label_from_two_sheets_is_not_a_conflict():
    s1 = sheet([{"query_id": "q1", "item_id": "iaaa", "label": "1"}])
    s2 = sheet([{"query_id": "q1", "item_id": "ibbb", "label": "1"}])
    k1 = key([{"query_id": "q1", "item_id": "iaaa", "record_id": "r1"}])
    k2 = key([{"query_id": "q1", "item_id": "ibbb", "record_id": "r1"}])
    labels, problems = ev.collect_labels([("s1", s1, k1), ("s2", s2, k2)])
    assert problems == [] and labels[("q1", "full", "r1")].label == "1"


# --- §17.5 무결성 위반 --------------------------------------------------
def test_label_disagreement_is_reported_and_item_is_not_adopted():
    """keep=first 금지: 두 시트가 다른 라벨을 주면 그 항목을 아예 쓰지 않는다."""
    s1 = sheet([{"query_id": "q1", "item_id": "iaaa", "label": "2"}])
    s2 = sheet([{"query_id": "q1", "item_id": "ibbb", "label": "0"}])
    k1 = key([{"query_id": "q1", "item_id": "iaaa", "record_id": "r1"}])
    k2 = key([{"query_id": "q1", "item_id": "ibbb", "record_id": "r1"}])
    labels, problems = ev.collect_labels([("s1", s1, k1), ("s2", s2, k2)])
    assert kinds(problems) == {"label_disagreement"}
    assert problems[0]["labels"] == ["0", "2"]
    assert ("q1", "full", "r1") not in labels          # 첫 라벨을 조용히 채택하지 않는다


def test_disagreement_is_not_resurrected_by_a_later_matching_sheet():
    s1 = sheet([{"query_id": "q1", "item_id": "iaaa", "label": "2"}])
    s2 = sheet([{"query_id": "q1", "item_id": "ibbb", "label": "0"}])
    s3 = sheet([{"query_id": "q1", "item_id": "iccc", "label": "2"}])
    ks = [key([{"query_id": "q1", "item_id": i, "record_id": "r1"}])
          for i in ("iaaa", "ibbb", "iccc")]
    labels, problems = ev.collect_labels(list(zip(("s1", "s2", "s3"), (s1, s2, s3), ks)))
    assert ("q1", "full", "r1") not in labels
    assert "label_disagreement" in kinds(problems)


def test_same_item_id_pointing_to_two_records_fails():
    s = sheet([{"query_id": "q1", "item_id": "iaaa", "label": "2"}])
    s2 = sheet([{"query_id": "q1", "item_id": "iaaa", "label": "2"}])
    k1 = key([{"query_id": "q1", "item_id": "iaaa", "record_id": "r1"}])
    k2 = key([{"query_id": "q1", "item_id": "iaaa", "record_id": "r9"}])
    labels, problems = ev.collect_labels([("s1", s, k1), ("s2", s2, k2)])
    assert "id_collision" in kinds(problems)
    assert len(labels) == 1                             # 충돌한 두 번째 항목은 채택되지 않는다


def test_key_file_with_internal_id_collision_is_reported():
    s = sheet([{"query_id": "q1", "item_id": "iaaa", "label": "2"}])
    k = key([{"query_id": "q1", "item_id": "iaaa", "record_id": "r1"},
             {"query_id": "q1", "item_id": "iaaa", "record_id": "r2"}])
    _labels, problems = ev.collect_labels([("s1", s, k)])
    assert "id_collision" in kinds(problems)


def test_label_without_key_row_is_reported_as_key_missing():
    """증분 key 덮어쓰기 회귀 탐지 — 라벨은 있는데 key 가 사라진 상태."""
    s = sheet([{"query_id": "q1", "item_id": "iaaa", "label": "2"},
               {"query_id": "q1", "item_id": "ilost", "label": "1"}])
    k = key([{"query_id": "q1", "item_id": "iaaa", "record_id": "r1"}])
    labels, problems = ev.collect_labels([("s1", s, k)])
    assert kinds(problems) == {"key_missing"}
    assert problems[0]["item_id"] == "ilost"
    assert len(labels) == 1                             # 조용히 버리지 않고 보고한다


def test_invalid_label_value_is_reported():
    s = sheet([{"query_id": "q1", "item_id": "iaaa", "label": "3"}])
    k = key([{"query_id": "q1", "item_id": "iaaa", "record_id": "r1"}])
    labels, problems = ev.collect_labels([("s1", s, k)])
    assert kinds(problems) == {"invalid_label"} and labels == {}


# --- §17.3 관점 분리 ----------------------------------------------------
def test_labels_from_one_perspective_are_not_reused_by_another():
    s = sheet([{"query_id": "q1", "item_id": "iaaa", "label": "2"}])
    k = key([{"query_id": "q1", "item_id": "iaaa", "record_id": "r1"}])
    labels, _ = ev.collect_labels([("s1", s, k)], perspective="full")
    scored_full = ev.score_condition({"q1": ["r1"]}, labels, k=1, perspective="full")
    scored_method = ev.score_condition({"q1": ["r1"]}, labels, k=1, perspective="method")
    assert scored_full["strict"] == (1.0, 1.0)
    assert scored_method["n_missing_labels"] == 1        # 방법 관점에는 라벨이 없다
    assert scored_method["strict"] == (0.0, 1.0)         # 미라벨은 구간으로 보고


# --- §17.3 라벨 출처 ----------------------------------------------------
def test_explicit_label_source_column_wins_over_inference():
    s = sheet([{"query_id": "q1", "item_id": "iaaa", "label": "2"}])
    s["label_source"] = "human"
    s["labeler"] = "익명 평가자 P1"
    k = key([{"query_id": "q1", "item_id": "iaaa", "record_id": "r1"}])
    labels, problems = ev.collect_labels([("s1", s, k)])
    assert problems == []
    assert labels[("q1", "full", "r1")].source == "human"


def test_source_counts_keep_llm_and_human_separate():
    s = sheet([{"query_id": "q1", "item_id": "iaaa", "label": "2"},
               {"query_id": "q1", "item_id": "ibbb", "label": "1"}])
    s["label_source"] = ["llm", "human"]
    k = key([{"query_id": "q1", "item_id": "iaaa", "record_id": "r1"},
             {"query_id": "q1", "item_id": "ibbb", "record_id": "r2"}])
    labels, _ = ev.collect_labels([("s1", s, k)])
    assert ev.label_source_counts(labels) == {"human": 1, "llm": 1}


@pytest.mark.parametrize("labeler,expected", [
    ("claude-sonnet(1차, 사람 검토 전)", "llm"),
    ("gpt-4o batch", "llm"),
    ("사람 검토자 A", "human"),
    ("human reviewer 2", "human"),
    ("adjudicated by 2 reviewers", "adjudicated"),
    ("", "unknown"),
    ("알 수 없음", "unknown"),
])
def test_label_source_inference(labeler, expected):
    assert ev.infer_label_source(labeler) == expected
