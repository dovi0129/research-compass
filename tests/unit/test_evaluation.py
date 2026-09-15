"""평가 풀 생성·채점 테스트 (명세 18.2, 18.3)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from research_compass import evaluation as ev


def _projects(n=8):
    return pd.DataFrame({
        "record_id": [f"r{i}" for i in range(n)],
        "source_row": list(range(1, n + 1)),
        "title_raw": [f"제목 {i}" if i != 7 else "질적탐구" for i in range(n)],
        "institution": ["A"] * n, "selection_year": [2024] * n,
        "program_대사업명": ["학술·인문사회사업"] * n,
        "quality_flags": [[] if i != 7 else ["short_title"] for i in range(n)],
    })


def test_pool_is_union_deduped_and_blinded():
    P = _projects()
    q = [{"query_id": "q1", "query": "테스트"}]
    sem = lambda _: np.array([0.9, 0.8, 0.7, 0.6, 0.5, 0.1, 0.1, 0.1])   # top5: 0..4
    lex = lambda _: np.array([0.0, 0.0, 0.9, 0.8, 0.0, 0.7, 0.6, 0.5])   # top5: 2,3,5,6,7
    sheet, key = ev.make_pool(q, P, sem, lex, split="dev", k=5)
    assert len(sheet) == 8 and len(key) == 8                 # 0..7 합집합, 중복(2,3) 제거
    assert set(sheet.columns) >= {"item_id", "title", "label"}
    assert "sem_rank" not in sheet.columns and "lex_rank" not in sheet.columns   # 방식 은닉
    assert sheet["label"].eq("").all()
    assert key["short_title"].sum() == 1                      # 질적탐구 표시


def test_pool_shuffle_is_deterministic():
    P = _projects(); q = [{"query_id": "q1", "query": "t"}]
    s = lambda _: np.arange(8, dtype=float); l = lambda _: np.arange(8, dtype=float)[::-1]
    a, _ = ev.make_pool(q, P, s, l, split="dev", seed=1)
    b, _ = ev.make_pool(q, P, s, l, split="dev", seed=1)
    c, _ = ev.make_pool(q, P, s, l, split="dev", seed=2)
    assert a["item_id"].tolist() == b["item_id"].tolist()
    assert a["item_id"].tolist() != c["item_id"].tolist()


def test_score_reports_bounds_with_U():
    key = pd.DataFrame({
        "query_id": ["q"] * 5, "item_id": list("abcde"), "record_id": list("abcde"),
        "source_row": range(5), "sem_rank": [1, 2, 3, 4, 5], "sem_score": [.9, .8, .7, .6, .5],
        "lex_rank": [None] * 5, "lex_score": [0] * 5, "short_title": [False] * 5, "title_len": [10] * 5,
    })
    sheet = pd.DataFrame({"query_id": ["q"] * 5, "query": ["t"] * 5, "item_id": list("abcde"),
                          "label": ["2", "1", "0", "U", "2"]})
    res = ev.score(sheet, key, k=5)
    s = res["summary"]
    assert s["semantic_strict"] == (0.4, 0.6)      # 2 두 개 / U 를 관련으로 보면 3
    assert s["semantic_lenient"] == (0.6, 0.8)     # 2,1 세 개 / +U
    assert s["n_unlabeled"] == 0


def test_score_counts_unlabeled_and_invalid():
    key = pd.DataFrame({"query_id": ["q"] * 2, "item_id": ["a", "b"], "record_id": ["a", "b"],
                        "source_row": [1, 2], "sem_rank": [1, 2], "sem_score": [.9, .8],
                        "lex_rank": [None, None], "lex_score": [0, 0],
                        "short_title": [False, False], "title_len": [10, 10]})
    sheet = pd.DataFrame({"query_id": ["q"] * 2, "query": ["t"] * 2, "item_id": ["a", "b"],
                          "label": ["", "3"]})
    s = ev.score(sheet, key)["summary"]
    assert s["n_unlabeled"] == 1 and s["n_invalid_labels"] == 1


def test_sheet_neutralizes_formula_prefix(tmp_path):
    df = pd.DataFrame({"query_id": ["q"], "query": ["t"], "item_id": ["i"],
                       "title": ["=HYPERLINK(...)"], "institution": ["-A"], "selection_year": [2024],
                       "program": ["p"], "label": [""], "note": [""]})
    p = tmp_path / "s.csv"; ev.write_sheet(df, p)
    txt = p.read_text(encoding="utf-8-sig")
    assert "\"'=HYPERLINK" in txt and "\"'-A\"" in txt


def test_score_distribution_fields():
    d = ev.score_distribution(np.linspace(0, 1, 1000))
    assert d["n"] == 1000 and d["max"] == 1.0 and 0 < d["p99"] < 1


def test_tau_probe_picks_requested_ranks_and_randoms():
    P = _projects(600)
    q = [{"query_id": "q1", "query": "t"}]
    s = lambda _: np.linspace(1, 0, 600)                     # 순위 = 인덱스+1
    sheet, key = ev.make_tau_probe(q, P, s, split="dev", ranks=(6, 10, 50, 500), n_random=2)
    assert len(sheet) == 6 and len(key) == 6
    assert sorted(key[key["kind"] == "probe"]["sem_rank"]) == [6, 10, 50, 500]
    assert (key[key["kind"] == "random"]["sem_rank"] >= 300).all()          # 상위권 밖에서 뽑힘
    assert "sem_score" not in sheet.columns                  # 블라인드


def test_tau_curve_suggests_threshold():
    d = pd.DataFrame({
        "sem_score": [0.80, 0.75, 0.70, 0.65, 0.60, 0.55, 0.50, 0.45, 0.40, 0.35],
        "label":     ["2",  "2",  "1",  "1",  "0",  "1",  "0",  "0",  "U",  "0"],
    })
    r = ev.tau_curve(d, bins=(0.35, 0.45, 0.55, 0.65, 0.75))
    assert r["n_labeled"] == 9 and r["n_U"] == 1
    cum = {row["tau"]: row for row in r["cumulative"]}
    assert cum[0.75]["precision_2"] == 1.0
    assert cum[0.35]["precision_2or1"] == round(5 / 9, 3)
    assert r["suggest"]["tau_for_precision_2or1_ge_0.7"] == 0.55
