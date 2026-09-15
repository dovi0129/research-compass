"""검색 평가 (명세 18절).

- make_pool: 질의별 의미검색 Top-5 ∪ 어휘검색 Top-5 를 합쳐 중복 제거 후 섞고,
  검색 방식·순위를 가린 라벨 시트를 만든다. (18.2)
- score: 라벨(2/1/0/U)로 엄격·완화 P@5 를 계산한다. U 는 상·하한으로 보고한다. (18.3)
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

LABELS = {"2", "1", "0", "U"}


def load_queries(path: Path) -> list[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _blind_id(split: str, qid: str, record_id: str) -> str:
    return "i" + hashlib.sha1(f"{split}|{qid}|{record_id}".encode()).hexdigest()[:8]


def make_pool(queries: list[dict], projects: pd.DataFrame,
              semantic_scores_fn, lexical_scores_fn,
              split: str, k: int = 5, seed: int = 20260909
              ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """반환: (label_sheet, key). key 는 라벨러에게 보여주지 않는다."""
    rng = random.Random(seed)
    ids = projects["record_id"].tolist()
    sheet_rows, key_rows = [], []

    for q in queries:
        qid, text = q["query_id"], q["query"]
        s_sem = semantic_scores_fn(text)
        s_lex = lexical_scores_fn(text)
        top_sem = [int(i) for i in np.argsort(-s_sem, kind="stable")[:k]]
        top_lex = [int(i) for i in np.argsort(-s_lex, kind="stable")[:k]]

        pool: dict[int, dict] = {}
        for r, i in enumerate(top_sem, 1):
            pool.setdefault(i, {"sem_rank": None, "lex_rank": None})["sem_rank"] = r
        for r, i in enumerate(top_lex, 1):
            pool.setdefault(i, {"sem_rank": None, "lex_rank": None})["lex_rank"] = r

        items = list(pool.items())
        rng.shuffle(items)                                   # 방식·순위 은닉 (18.2)
        for i, meta in items:
            p = projects.iloc[i]
            bid = _blind_id(split, qid, p["record_id"])
            sheet_rows.append({
                "query_id": qid, "query": text, "item_id": bid,
                "title": p["title_raw"],
                "institution": p.get("institution", ""),
                "selection_year": p.get("selection_year", ""),
                "program": p.get("program_대사업명", ""),
                "label": "", "note": "",
            })
            key_rows.append({
                "query_id": qid, "item_id": bid, "record_id": p["record_id"],
                "source_row": p["source_row"],
                "sem_rank": meta["sem_rank"], "sem_score": round(float(s_sem[i]), 4),
                "lex_rank": meta["lex_rank"], "lex_score": round(float(s_lex[i]), 4),
                "short_title": "short_title" in (p.get("quality_flags") or []),
                "title_len": len(str(p["title_raw"])),
            })
    return pd.DataFrame(sheet_rows), pd.DataFrame(key_rows)


def write_sheet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 엑셀에서 열어 라벨을 채우는 용도. 수식으로 해석될 수 있는 선행문자 무력화 (명세 13.2)
    d = df.copy()
    for c in ("title", "query", "institution", "program"):
        if c in d.columns:
            d[c] = d[c].astype(str).map(lambda s: "'" + s if s[:1] in "=+-@" else s)
    d.to_csv(path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_ALL, lineterminator="\n")


def _p_at_k(labels: list[str], k: int, relevant: set[str]) -> tuple[float, float]:
    """(하한, 상한). U 는 하한에서 0, 상한에서 관련으로 본다."""
    top = labels[:k]
    denom = min(k, len(top)) or 1
    lo = sum(1 for l in top if l in relevant) / denom
    hi = sum(1 for l in top if l in relevant or l == "U") / denom
    return lo, hi


def score(sheet: pd.DataFrame, key: pd.DataFrame, k: int = 5) -> dict:
    """라벨 시트 + key -> 질의별·전체 P@5 (엄격/완화, 상·하한)."""
    m = sheet.merge(key, on=["query_id", "item_id"], how="inner")
    m["label"] = m["label"].astype(str).str.strip().str.upper()
    unlabeled = int((m["label"] == "").sum())
    bad = m[(~m["label"].isin(LABELS)) & (m["label"] != "")]     # 빈칸은 미라벨, 그 외는 오입력

    per_q = []
    for qid, g in m.groupby("query_id", sort=True):
        row = {"query_id": qid, "query": g["query"].iloc[0],
               "n_items": len(g), "n_unlabeled": int((g["label"] == "").sum()),
               "n_U": int((g["label"] == "U").sum())}
        for method, rank_col in (("semantic", "sem_rank"), ("lexical", "lex_rank")):
            gg = g[g[rank_col].notna()].sort_values(rank_col)
            labels = gg["label"].tolist()
            s_lo, s_hi = _p_at_k(labels, k, {"2"})
            l_lo, l_hi = _p_at_k(labels, k, {"2", "1"})
            row[f"{method}_strict_p@{k}"] = (s_lo, s_hi)
            row[f"{method}_lenient_p@{k}"] = (l_lo, l_hi)
            row[f"{method}_short_in_top{k}"] = int(gg["short_title"].head(k).sum())
        per_q.append(row)

    def agg(name):
        vals = [r[name] for r in per_q]
        return (round(float(np.mean([v[0] for v in vals])), 4),
                round(float(np.mean([v[1] for v in vals])), 4)) if vals else (None, None)

    summary = {
        "n_queries": len(per_q), "k": k,
        "n_unlabeled": unlabeled, "n_invalid_labels": int(len(bad)),
        "semantic_strict": agg(f"semantic_strict_p@{k}"),
        "semantic_lenient": agg(f"semantic_lenient_p@{k}"),
        "lexical_strict": agg(f"lexical_strict_p@{k}"),
        "lexical_lenient": agg(f"lexical_lenient_p@{k}"),
        "note": "값은 (하한, 상한). U 라벨을 하한에서는 비관련, 상한에서는 관련으로 계산. "
                "전체 코퍼스 라벨링이 아니므로 recall 은 계산하지 않는다. (명세 18.3)",
    }
    return {"summary": summary, "per_query": per_q}


def score_distribution(scores: np.ndarray) -> dict:
    """한 질의에 대한 전체 코퍼스 점수 분포 — 관련도 기준값(tau) 검토용."""
    q = np.quantile(scores, [0.5, 0.9, 0.99, 0.999])
    return {
        "n": int(scores.size), "max": round(float(scores.max()), 4),
        "p50": round(float(q[0]), 4), "p90": round(float(q[1]), 4),
        "p99": round(float(q[2]), 4), "p99.9": round(float(q[3]), 4),
        "mean": round(float(scores.mean()), 4), "std": round(float(scores.std()), 4),
        "top1_minus_p99": round(float(scores.max() - q[2]), 4),
    }


# ---------------------------------------------------------------------------
# tau 보정용 심층 표본 (Top-5 풀만으로는 기준값을 정할 수 없을 때)
# ---------------------------------------------------------------------------
PROBE_RANKS = (6, 7, 8, 9, 10, 15, 20, 30, 50, 100, 200, 500)


def make_tau_probe(queries: list[dict], projects: pd.DataFrame, semantic_scores_fn,
                   split: str, ranks: tuple[int, ...] = PROBE_RANKS, n_random: int = 3,
                   seed: int = 20260909) -> tuple[pd.DataFrame, pd.DataFrame]:
    """질의별로 의미검색 순위 6~500위 지점과 무작위 항목을 뽑아 라벨 시트를 만든다.

    목적: 점수가 낮아질수록 관련 비율이 어떻게 떨어지는지 보고 tau 를 정한다.
    Top-5 만 라벨하면 모두 높은 점수라 기준선을 그을 수 없다.
    """
    rng = random.Random(seed)
    n = len(projects)
    sheet_rows, key_rows = [], []
    for q in queries:
        qid, text = q["query_id"], q["query"]
        s = semantic_scores_fn(text)
        order = np.argsort(-s, kind="stable")
        picks = [(int(order[r - 1]), r, "probe") for r in ranks if r <= n]
        pool_idx = {i for i, _, _ in picks}
        lo = min(1000, max(len(ranks) + 1, n // 2))           # 코퍼스가 작아도 동작하도록
        while n > lo and len([p for p in picks if p[2] == "random"]) < n_random:
            r = rng.randint(lo, n)                            # 상위권 밖 무작위
            i = int(order[r - 1])
            if i not in pool_idx:
                picks.append((i, r, "random")); pool_idx.add(i)
        rng.shuffle(picks)
        for i, r, kind in picks:
            p = projects.iloc[i]
            bid = _blind_id(split + "-tau", qid, p["record_id"])
            sheet_rows.append({
                "query_id": qid, "query": text, "item_id": bid,
                "title": p["title_raw"], "institution": p.get("institution", ""),
                "selection_year": p.get("selection_year", ""),
                "program": p.get("program_대사업명", ""), "label": "", "note": "",
            })
            key_rows.append({
                "query_id": qid, "item_id": bid, "record_id": p["record_id"],
                "source_row": p["source_row"], "sem_rank": r,
                "sem_score": round(float(s[i]), 4), "kind": kind,
                "short_title": "short_title" in (p.get("quality_flags") or []),
            })
    return pd.DataFrame(sheet_rows), pd.DataFrame(key_rows)


# 점수 공간별 (key 컬럼, 방향). desc = "점수 ≥ t 가 관련", asc = "순위 ≤ t 가 관련".
# 라벨은 점수기와 독립이므로 같은 시트를 어느 공간에서도 다시 채점할 수 있다 (개정안 6.1, T-33).
SCORE_SPACES: dict[str, tuple[str, str]] = {
    "s_sem": ("sem_score", "desc"),
    "margin": ("sem_margin", "desc"),
    "rank": ("sem_rank", "asc"),
    "s_rr": ("rerank_logit", "desc"),
}
RANK_CUTOFFS = (5, 6, 7, 8, 9, 10, 15, 20, 30, 50, 100, 200, 500, 1000, 2000, 5000)


def _default_bins(values: pd.Series, direction: str) -> tuple[float, ...]:
    if direction == "asc":                        # 순위 공간: 고정 절단점 중 표본 범위 안쪽
        hi = float(values.max())
        return tuple(float(c) for c in RANK_CUTOFFS if c <= hi) or (hi,)
    lo = float(np.floor(values.min() * 20) / 20)
    hi = float(np.ceil(values.max() * 20) / 20)
    return tuple(np.round(np.arange(lo, hi + 1e-9, 0.02), 2))


def tau_curve(labeled: pd.DataFrame, bins: tuple[float, ...] | None = None,
              space: str = "s_sem") -> dict:
    """라벨된 표본 -> tau 후보별 정밀도 곡선.

    P(tau) = 게이트 통과 항목 중 관련(2 또는 2∪1) 비율. U 는 분모에서 제외하고 개수만 보고.
    `space` 로 점수 공간을 고른다 (개정안 6.2). 순위 공간은 '작을수록 관련' 이므로 방향이 반대다.
    """
    if space not in SCORE_SPACES:
        raise ValueError(f"알 수 없는 점수 공간 {space!r} — {tuple(SCORE_SPACES)} 중 하나")
    col, direction = SCORE_SPACES[space]
    d = labeled.copy()
    d["label"] = d["label"].astype(str).str.strip().str.upper()
    if col not in d.columns:
        raise KeyError(f"{space} 곡선에는 '{col}' 컬럼이 필요하다. rescore-pool 을 먼저 실행한다.")
    d[col] = pd.to_numeric(d[col], errors="coerce")
    scored = d[d[col].notna()]
    n_missing = int(len(d) - len(scored))
    known = scored[scored["label"].isin(["2", "1", "0"])]
    n_u = int((scored["label"] == "U").sum())
    if known.empty:
        raise ValueError(f"{space}: 점수와 라벨이 모두 있는 항목이 없다")
    if bins is None:
        bins = _default_bins(scored[col], direction)

    def gate(t: float) -> pd.DataFrame:
        return known[known[col] >= t] if direction == "desc" else known[known[col] <= t]

    rows = []
    for t in bins:
        sel = gate(float(t))
        if len(sel) == 0:
            continue
        rows.append({
            "tau": float(t), "n_at_or_above": int(len(sel)),
            "precision_2": round(float((sel["label"] == "2").mean()), 3),
            "precision_2or1": round(float(sel["label"].isin(["2", "1"]).mean()), 3),
        })
    # 구간별(비누적) 관련 비율 — 곡선이 어디서 무너지는지 보기 위함
    band_rows = []
    edges = list(bins)
    for a, b in zip(edges[:-1], edges[1:]):
        sel = known[(known[col] >= float(a)) & (known[col] < float(b))]
        if len(sel):
            band_rows.append({"from": float(a), "to": float(b), "n": int(len(sel)),
                              "rel_2or1": round(float(sel["label"].isin(["2", "1"]).mean()), 3),
                              "rel_2": round(float((sel["label"] == "2").mean()), 3)})

    def suggest(target: float, pcol: str):
        """조건을 만족하는 **가장 포용적인** 절단점 (개정안 6.3-2)."""
        ok = [r for r in rows if r[pcol] >= target]
        if not ok:
            return None
        pick = min(ok, key=lambda r: r["tau"]) if direction == "desc" else max(ok, key=lambda r: r["tau"])
        return pick["tau"]

    return {
        "space": space, "score_column": col, "direction": direction,
        "n_labeled": int(len(known)), "n_U": n_u, "n_missing_score": n_missing,
        "cumulative": rows, "bands": band_rows,
        "suggest": {
            "tau_for_precision_2or1_ge_0.7": suggest(0.7, "precision_2or1"),
            "tau_for_precision_2or1_ge_0.5": suggest(0.5, "precision_2or1"),
            "tau_for_precision_2_ge_0.5": suggest(0.5, "precision_2"),
        },
        "note": "표본은 개발 질의 5개에서 뽑은 것이며 통계적으로 충분한 검정이 아니다. (명세 18.1)",
    }


# ---------------------------------------------------------------------------
# 조건 매트릭스 채점 (개정안 9.1) — A 의미 / B 어휘 / C RRF / D RRF+재정렬
# ---------------------------------------------------------------------------
# E·E' 는 개정안 9.1 에 없던 조건이다. 조건 C(RRF)가 dev·test 모두에서 미달해 기본값이 꺼졌으므로
# (D-020), 실제 기본 경로는 "RRF + 재정렬"(D)이 아니라 **"의미 + 재정렬"** 이다. 그것을 측정해야 한다.
CONDITIONS = {
    "A": {"label": "의미 단독", "hybrid": False, "rerank": False, "top_n": None},
    "B": {"label": "어휘 단독", "hybrid": None, "rerank": False, "top_n": None},
    "C": {"label": "RRF", "hybrid": True, "rerank": False, "top_n": None},
    "D": {"label": "RRF + 재정렬 N_r=20", "hybrid": True, "rerank": True, "top_n": 20},
    "D'": {"label": "RRF + 재정렬 N_r=50", "hybrid": True, "rerank": True, "top_n": 50},
    "E": {"label": "의미 + 재정렬 N_r=20", "hybrid": False, "rerank": True, "top_n": 20},
    "E'": {"label": "의미 + 재정렬 N_r=50", "hybrid": False, "rerank": True, "top_n": 50},
}


# 라벨 출처 (v2 §17.3). 같은 모델의 병렬 에이전트 여러 개를 사람 평가자 여러 명으로 쓰지 않는다.
LABEL_SOURCES = ("llm", "human", "adjudicated", "unknown")
DEFAULT_PERSPECTIVE = "full"        # v2 §6.3 의 관점. 기존 시트는 전부 원래 주제 검색이다.


def infer_label_source(labeler: str) -> str:
    """시트의 `labeler` 문자열에서 출처를 판별한다. `label_source` 컬럼이 있으면 그것을 쓴다."""
    s = str(labeler).strip().lower()
    if not s:
        return "unknown"
    if "adjudicat" in s or "조정" in s:
        return "adjudicated"
    if any(t in s for t in ("claude", "sonnet", "gpt", "llm", "model")):
        return "llm"
    if any(t in s for t in ("human", "사람", "person")):
        return "human"
    return "unknown"


@dataclass(frozen=True)
class LabelRecord:
    label: str
    source: str                      # llm | human | adjudicated | unknown
    labeler: str
    sheet: str
    item_id: str


def collect_labels(sheets: list[tuple[str, pd.DataFrame, pd.DataFrame]],
                   perspective: str = DEFAULT_PERSPECTIVE
                   ) -> tuple[dict[tuple[str, str, str], LabelRecord], list[dict]]:
    """여러 라벨 시트를 `(query_id, perspective, record_id) -> LabelRecord` 로 모은다.

    `item_id` 는 시트마다 다른 소금(split, split+'-tau', split+'-incr')으로 만든 해시라
    시트 간 비교에 쓸 수 없다. key 를 거쳐 `record_id` 로 맞춘다.

    무결성 규칙 (v2 §17.5) — 문제를 **감추지 않고 목록으로 돌려준다.** 호출자가 실패 처리한다.

    | kind | 뜻 |
    |---|---|
    | `id_collision` | 같은 `(query_id, item_id)` 가 서로 다른 `record_id` 를 가리킨다 |
    | `key_missing` | 라벨은 있는데 key 에 그 항목이 없다 — **증분 key 덮어쓰기 회귀** |
    | `label_disagreement` | 같은 항목에 서로 다른 라벨이 있다 |
    | `invalid_label` | 2/1/0/U 가 아닌 값 |

    `keep=first` 로 조용히 넘기지 않는다. 라벨이 어긋나면 그 항목을 **채택하지 않는다.**
    관점(v2 §17.3)이 키에 들어가므로 원래 주제 라벨이 방법 중심 질의에 재사용되지 않는다.
    """
    out: dict[tuple[str, str, str], LabelRecord] = {}
    problems: list[dict] = []
    id_map: dict[tuple[str, str], str] = {}      # (query_id, item_id) -> record_id
    rejected: set[tuple[str, str, str]] = set()

    for name, sheet, key in sheets:
        kk = key[["query_id", "item_id", "record_id"]].astype(str)
        # key 파일 자체의 (query_id, item_id) 중복이 다른 레코드를 가리키는지 먼저 본다
        for (q, i), g in kk[kk.duplicated(subset=["query_id", "item_id"], keep=False)] \
                .groupby(["query_id", "item_id"]):
            if g["record_id"].nunique() > 1:
                problems.append({"kind": "id_collision", "sheet": name, "query_id": q,
                                 "item_id": i, "record_ids": sorted(set(g["record_id"]))})
        kk = kk.drop_duplicates(subset=["query_id", "item_id", "record_id"])

        s = sheet.astype(str)
        m = s.merge(kk, on=["query_id", "item_id"], how="left", indicator=True)
        for _, r in m.iterrows():
            lab = str(r["label"]).strip().upper()
            if lab == "":
                continue                                  # 아직 라벨하지 않은 행
            qid, iid = str(r["query_id"]), str(r["item_id"])
            if lab not in LABELS:
                problems.append({"kind": "invalid_label", "sheet": name, "query_id": qid,
                                 "item_id": iid, "label": lab})
                continue
            if r["_merge"] != "both":
                problems.append({"kind": "key_missing", "sheet": name,
                                 "query_id": qid, "item_id": iid})
                continue
            rid = str(r["record_id"])
            prev_rid = id_map.get((qid, iid))
            if prev_rid is not None and prev_rid != rid:
                problems.append({"kind": "id_collision", "sheet": name, "query_id": qid,
                                 "item_id": iid, "record_ids": sorted({prev_rid, rid})})
                continue
            id_map[(qid, iid)] = rid

            src = str(r["label_source"]).strip().lower() if "label_source" in m.columns else ""
            labeler = str(r.get("labeler", ""))
            if src not in LABEL_SOURCES:
                src = infer_label_source(labeler)
            k = (qid, perspective, rid)
            if k in out and out[k].label != lab:
                problems.append({"kind": "label_disagreement", "query_id": qid, "record_id": rid,
                                 "labels": sorted({out[k].label, lab}),
                                 "sheets": sorted({out[k].sheet, name})})
                rejected.add(k)                           # 어긋난 항목은 채택하지 않는다
                continue
            if k not in rejected:
                out[k] = LabelRecord(label=lab, source=src, labeler=labeler,
                                     sheet=name, item_id=iid)
    for k in rejected:
        out.pop(k, None)
    return out, problems


def label_source_counts(labels: dict[tuple[str, str, str], LabelRecord]) -> dict[str, int]:
    """출처별 라벨 수. 사람 라벨과 LLM 라벨을 하나의 정확도로 섞지 않기 위해 함께 보고한다."""
    counts: dict[str, int] = {}
    for rec in labels.values():
        counts[rec.source] = counts.get(rec.source, 0) + 1
    return dict(sorted(counts.items()))


def score_condition(rankings: dict[str, list[str]],
                    labels: dict[tuple[str, str, str], LabelRecord],
                    k: int = 5, perspective: str = DEFAULT_PERSPECTIVE) -> dict:
    """조건 하나의 P@k. rankings: {query_id: [record_id, ...]} (이미 조건별 순위).

    라벨이 없는 항목은 `missing` 으로 세고 **관련으로 치지 않는다.** 미라벨이 있으면
    그 질의의 값은 부분 라벨 기준임을 표시한다 (조용히 0 으로 바꾸지 않는다).
    라벨은 `(query_id, perspective, record_id)` 로 찾으므로 다른 관점의 라벨을 끌어오지 않는다.
    """
    per_q, missing = [], []
    for qid in sorted(rankings):
        top = rankings[qid][:k]
        labs = []
        for rid in top:
            rec = labels.get((qid, perspective, rid))
            if rec is None:
                missing.append({"query_id": qid, "record_id": rid})
            labs.append(rec.label if rec is not None else "")
        denom = min(k, len(top)) or 1
        s_lo = sum(1 for l in labs if l == "2") / denom
        s_hi = sum(1 for l in labs if l in ("2", "U", "")) / denom
        l_lo = sum(1 for l in labs if l in ("2", "1")) / denom
        l_hi = sum(1 for l in labs if l in ("2", "1", "U", "")) / denom
        per_q.append({"query_id": qid, "n_top": len(top),
                      "n_missing_label": sum(1 for l in labs if l == ""),
                      "n_U": sum(1 for l in labs if l == "U"),
                      f"strict_p@{k}": (round(s_lo, 4), round(s_hi, 4)),
                      f"lenient_p@{k}": (round(l_lo, 4), round(l_hi, 4))})

    def agg(name):
        v = [r[name] for r in per_q]
        return (round(float(np.mean([x[0] for x in v])), 4),
                round(float(np.mean([x[1] for x in v])), 4)) if v else (None, None)

    return {"n_queries": len(per_q), "k": k,
            "strict": agg(f"strict_p@{k}"), "lenient": agg(f"lenient_p@{k}"),
            "n_missing_labels": len(missing), "missing": missing,
            "per_query": per_q,
            "note": "값은 (하한, 상한). U 와 미라벨을 하한에서는 비관련, 상한에서는 관련으로 계산. "
                    "미라벨이 0 이 아니면 확정값이 아니다."}


def rescore_pool(key: pd.DataFrame, queries: list[dict], projects: pd.DataFrame,
                 semantic_scores_fn, reranker=None, timeout_s: float = 60.0
                 ) -> tuple[pd.DataFrame, dict]:
    """라벨 시트는 건드리지 않고 key 에 점수 컬럼만 추가한다 (개정안 6.1, T-33).

    추가 컬럼: `sem_margin`(= s_sem − p99(q)), `sem_percentile`, 그리고
    재정렬기를 주면 `rerank_logit`. 질의별 p99 는 **전체 코퍼스** 분포에서 계산한다.
    """
    from . import prepare as _prep
    from . import relative as _rel
    from . import rerank as _rr

    row_of = {rid: i for i, rid in enumerate(projects["record_id"].tolist())}
    texts = projects["search_text"].astype(str).tolist()
    out = key.copy()
    for c in ("sem_margin", "sem_percentile", "rerank_logit"):
        if c not in out.columns:
            out[c] = np.nan
    meta = {"queries": [], "reranker": None}

    for q in queries:
        qid, text = q["query_id"], q["query"]
        sel = out.index[out["query_id"] == qid]
        if len(sel) == 0:
            continue
        s = semantic_scores_fn(text)
        st = _rel.query_stats(s)
        idxs = [row_of[r] for r in out.loc[sel, "record_id"]]
        out.loc[sel, "sem_margin"] = [round(st.margin(float(s[i])), 4) for i in idxs]
        out.loc[sel, "sem_percentile"] = [round(_rel.percentile_of(s, float(s[i])), 6) for i in idxs]
        qmeta = {"query_id": qid, "p99": round(st.p99, 4), "p999": round(st.p999, 4),
                 "max": round(st.max, 4), "n_corpus": st.n}
        if reranker is not None:
            nq = _prep.normalize_text(text)
            res = _rr.apply_rerank(reranker, nq, [texts[i] for i in idxs],
                                   top_n=len(idxs), timeout_s=timeout_s,
                                   enforce_range=False)   # 표본 전수 재점수 (10~50 제한 밖)
            if res.applied:
                out.loc[sel, "rerank_logit"] = [round(v, 4) for v in res.scores]
                qmeta["rerank_seconds"] = round(res.elapsed_s, 2)
            else:
                qmeta["rerank_warnings"] = res.warnings
        meta["queries"].append(qmeta)

    if reranker is not None:
        meta["reranker"] = {"model_id": getattr(reranker, "model_id", None),
                            "revision": getattr(reranker, "revision", None),
                            "device": getattr(reranker, "device", None)}
    return out, meta
