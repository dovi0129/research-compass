"""검색 서비스 — S1~S5 파이프라인 (개정안 01 2절).

    질의 q
     ├─ S1  의미 검색   BGE-M3 → s_sem(d)            (전체 코퍼스)
     ├─ S1' 어휘 검색   char n-gram TF-IDF → s_lex(d)
     ├─ S2  결합       RRF(rank_sem, rank_lex) → 후보 N_c
     ├─ S3  상대 점수  margin(d) = s_sem(d) − p99(q)
     ├─ S4  재정렬     cross-encoder(q, title) → s_rr(d), 상위 N_r
     └─ S5  게이트     relevant(d) := score_X(d) ≥ tau   (tau 미확정 시 보류)

CLI 와 UI 가 **이 모듈의 같은 함수**를 쓴다 (계획 P4 통과 조건).
각 단계는 끌 수 있고, 끈 사실·실패한 사실은 경고 코드로 남는다.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import embedding as emb
from . import fusion as fus
from . import prepare as prep
from . import relative as rel
from . import rerank as rr
from .baseline import CharTfidfBaseline
from .retrieval import FlatIPIndex
from .store import read_table

# SearchResponse.warnings 코드 (개정안 7절)
HYBRID_DISABLED_BY_EVAL = "HYBRID_DISABLED_BY_EVAL"
SEMANTIC_UNAVAILABLE = "SEMANTIC_UNAVAILABLE"
GATE_UNCALIBRATED = "GATE_UNCALIBRATED"

GATE_PASS, GATE_FAIL, GATE_UNCAL = "pass", "fail", "uncalibrated"
THRESHOLD_SPACES = ("s_sem", "margin", "rank", "s_rr")


@dataclass
class SearchRequest:
    """개정안 7절 계약. 필터는 원본 6.3-5 에 따라 두 방식 모두에 먼저 적용된다.

    `hybrid`·`rerank` 는 3상태다. `None` 이면 설정값을 따르고, `True`/`False` 는 **명시적 재정의**로
    설정값을 이긴다. 평가로 꺼둔 단계를 다시 측정하려면 재정의가 가능해야 하기 때문이다
    (설정과 AND 로 묶으면 조건 C 를 영원히 측정할 수 없다).
    """
    query: str
    top_k: int = 10
    hybrid: bool | None = None
    rerank: bool | None = None
    rerank_top_n: int = 20
    exclude_short: bool = False
    years: list[int] | None = None
    programs: list[str] | None = None
    institutions: list[str] | None = None


@dataclass
class ProjectResult:
    rank: int
    record_id: str
    source_row: int
    title: str
    institution: str
    selection_year: int | None
    program: str
    short_title: bool
    semantic_score: float
    semantic_percentile: float
    semantic_margin: float
    percentile_label: str
    lexical_rank: int | None
    fusion_rank: int                     # 감사용. 화면에 표시하지 않는다 (개정안 3절)
    rerank_score: float | None           # 시그모이드. 확률이 아니다
    rerank_logit: float | None
    relevance_gate: str                  # pass | fail | uncalibrated


@dataclass
class RelevanceSummary:
    """S5 게이트 상태. tau 가 없으면 전체 집계를 하지 않는다 (T-31)."""
    tau: float | None
    space: str | None
    calibrated: bool
    reason: str
    n_relevant: int | None = None
    scope: str | None = None             # corpus | candidate_pool
    evidence_path: str | None = None


@dataclass
class SearchResponse:
    query: str
    normalized_query: str
    results: list[ProjectResult]
    relevance: RelevanceSummary
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)
    run_mode: str = "unknown"
    rerank_applied: bool = False
    rerank_badge: str | None = None


class SearchEngine:
    """정제 데이터·인덱스·baseline·재정렬기를 한 번만 적재해 재사용한다."""

    def __init__(self, root: Path, cfg: dict, need_semantic: bool = True,
                 offline_reranker: bool = False):
        self.root, self.cfg = Path(root), cfg
        proc = self.root / cfg["paths"]["processed"]
        self.art = self.root / cfg["paths"]["artifacts"]
        self.projects = read_table(proc, "projects")
        self.ids = self.projects["record_id"].tolist()
        self.search_texts = self.projects["search_text"].astype(str).tolist()
        self._short = self.projects["quality_flags"].map(
            lambda f: "short_title" in (f or [])).to_numpy()

        t0 = time.monotonic()
        self.baseline = CharTfidfBaseline(self.search_texts,
                                          cfg["baseline"]["ngram_min"], cfg["baseline"]["ngram_max"])
        self.lexical_load_s = time.monotonic() - t0

        self.semantic = None
        self.run_mode = "unknown"
        if need_semantic and (self.art / "project_embeddings.npy").exists():
            man = json.loads((self.art / "index_manifest.json").read_text(encoding="utf-8"))
            self.run_mode = man["run_mode"]
            t0 = time.monotonic()
            e = emb.make_embedder(cfg, offline=(self.run_mode == "test_fixture"))
            idx = FlatIPIndex(emb.load(self.art / "project_embeddings.npy"))
            self.semantic = {"embedder": e, "index": idx}
            self.semantic_load_s = time.monotonic() - t0

        self._reranker = None
        self._reranker_failed = False
        self._offline_reranker = offline_reranker

    # --- 필터 (두 방식 모두에 적용) ------------------------------------
    def filter_mask(self, req: SearchRequest) -> np.ndarray | None:
        m = np.ones(len(self.projects), dtype=bool)
        used = False
        if req.exclude_short:
            m &= ~self._short
            used = True
        if req.years:
            m &= self.projects["selection_year"].isin(req.years).to_numpy()
            used = True
        if req.programs and "program_대사업명" in self.projects.columns:
            m &= self.projects["program_대사업명"].isin(req.programs).to_numpy()
            used = True
        if req.institutions:
            m &= self.projects["institution"].isin(req.institutions).to_numpy()
            used = True
        return m if used else None

    def reranker(self):
        """최초 호출에서만 적재한다. 한 번 실패하면 다시 시도하지 않는다."""
        if self._reranker is None and not self._reranker_failed:
            try:
                self._reranker = rr.make_reranker(self.cfg, offline=self._offline_reranker)
            except Exception:
                self._reranker_failed = True
        return self._reranker


def _tau_config(cfg: dict) -> tuple[float | None, str | None, str | None]:
    r = cfg.get("retrieval", {})
    tau, space = r.get("project_relevance_threshold"), r.get("threshold_space")
    if tau is not None and space not in THRESHOLD_SPACES:
        raise ValueError(f"threshold_space 가 {THRESHOLD_SPACES} 중 하나여야 한다: {space!r}")
    return tau, space, r.get("threshold_evidence_path")


def _gate_scores(space: str, sem_scores: np.ndarray, stats: rel.RelativeStats,
                 mask: np.ndarray | None) -> tuple[np.ndarray, str]:
    """게이트를 적용할 점수 공간. s_rr 은 후보만 채점되므로 전체 코퍼스 집계가 불가능하다."""
    if space == "s_sem":
        return sem_scores, "corpus"
    if space == "margin":
        return sem_scores - stats.p99, "corpus"
    if space == "rank":
        # 순위 공간: 낮을수록 관련. 부호를 뒤집어 '≥ tau' 규칙을 유지한다.
        idx = np.arange(len(sem_scores)) if mask is None else np.flatnonzero(mask)
        ranks = np.full(len(sem_scores), np.inf)
        order = idx[np.argsort(-sem_scores[idx], kind="stable")]
        ranks[order] = np.arange(1, len(order) + 1)
        return -ranks, "corpus"
    raise ValueError(f"전체 코퍼스에서 계산할 수 없는 공간: {space}")


def search(req: SearchRequest, engine: SearchEngine) -> SearchResponse:
    """S1~S5 를 순서대로 실행하고 개정안 7절 계약대로 반환한다."""
    warnings: list[str] = []
    notes: list[str] = []
    timings: dict[str, float] = {}
    q = prep.normalize_text(req.query)
    mask = engine.filter_mask(req)

    if engine.semantic is None:
        raise RuntimeError("의미검색 인덱스가 없다. build-index 를 먼저 실행한다.")

    # --- S1 / S1' -----------------------------------------------------
    t0 = time.monotonic()
    qv = engine.semantic["embedder"].encode([q])[0]
    s_sem = engine.semantic["index"].scores(qv)
    timings["s1_semantic_s"] = time.monotonic() - t0

    t0 = time.monotonic()
    s_lex = engine.baseline.scores(q)
    timings["s1_lexical_s"] = time.monotonic() - t0

    # --- S2 결합 ------------------------------------------------------
    pool = int(engine.cfg["retrieval"].get("candidate_pool", 100))
    k_rrf = int(engine.cfg["retrieval"].get("rrf_k", 60))
    cfg_hybrid = bool(engine.cfg["retrieval"].get("hybrid", True))
    hybrid = cfg_hybrid if req.hybrid is None else bool(req.hybrid)
    if hybrid and not cfg_hybrid:
        # 평가 미달로 기본값이 꺼진 단계를 호출자가 명시적으로 켰다 (D-020)
        warnings.append(HYBRID_DISABLED_BY_EVAL)
    t0 = time.monotonic()
    fused = (fus.build_candidates(s_sem, s_lex, engine.ids, mask, k=k_rrf, candidate_pool=pool)
             if hybrid else
             fus.semantic_only(s_sem, engine.ids, mask, candidate_pool=pool))
    timings["s2_fusion_s"] = time.monotonic() - t0
    if not fused:
        empty = RelevanceSummary(tau=None, space=None, calibrated=False,
                                 reason="필터 통과 문서가 없다")
        return SearchResponse(query=req.query, normalized_query=q, results=[], relevance=empty,
                              warnings=warnings, run_mode=engine.run_mode)

    # --- S3 상대 점수 --------------------------------------------------
    t0 = time.monotonic()
    stats = rel.query_stats(s_sem, mask)
    _, annot = rel.annotate(s_sem, [it.index for it in fused], mask)
    timings["s3_relative_s"] = time.monotonic() - t0

    # 어휘 순위는 결합 단계에서 이미 계산됐다 (한쪽만 등장하면 None)
    lex_rank = {it.index: it.ranks.get("lex") for it in fused}

    # --- S4 재정렬 -----------------------------------------------------
    ordered = list(fused)                             # S2 순위
    rr_logit: dict[int, float] = {}
    applied, badge = False, None
    cfg_rerank = bool(engine.cfg.get("rerank", {}).get("enabled", True))
    if cfg_rerank if req.rerank is None else bool(req.rerank):
        reranker = engine.reranker()
        if reranker is None:
            warnings.append(rr.RERANK_SKIPPED)
            badge = rr.NOT_APPLIED_BADGE
            notes.append("재정렬기 적재 실패 — S2 결합 순위로 표시한다")
        else:
            n_r = rr.clamp_top_n(req.rerank_top_n)
            head = ordered[:n_r]
            t0 = time.monotonic()
            out = rr.apply_rerank(reranker, q, [engine.search_texts[it.index] for it in head],
                                  top_n=n_r,
                                  timeout_s=float(engine.cfg["rerank"].get("timeout_s", 10)))
            timings["s4_rerank_s"] = time.monotonic() - t0
            if out.applied:
                applied = True
                for local, it in enumerate(head):
                    rr_logit[it.index] = out.scores[local]
                ordered = [head[i] for i in out.order] + ordered[n_r:]
            else:
                warnings.extend(out.warnings)
                badge = out.badge
                notes.append("재정렬 실패·시간초과 — S2 결합 순위로 표시한다 (조용한 대체 없음)")
    else:
        notes.append("재정렬 꺼짐 — S2 결합 순위로 표시한다")

    # --- S5 게이트 -----------------------------------------------------
    tau, space, evidence = _tau_config(engine.cfg)
    if tau is None:
        relevance = RelevanceSummary(
            tau=None, space=space, calibrated=False,
            reason="관련도 기준값(tau) 미확정 — 라벨 표본의 정밀도 곡선으로만 정한다 (개정안 6절)",
            evidence_path=evidence)
        warnings.append(GATE_UNCALIBRATED)
        gate_of = {}
    elif space == "s_rr":
        # 재정렬 점수는 후보 N_r 만 있다. 코퍼스 전체 집계로 확장하지 않는다.
        gate_of = {i: (GATE_PASS if v >= tau else GATE_FAIL) for i, v in rr_logit.items()}
        n_rel = sum(1 for v in gate_of.values() if v == GATE_PASS) if applied else None
        relevance = RelevanceSummary(
            tau=tau, space=space, calibrated=applied,
            reason=("재정렬 점수 공간이므로 후보 풀 안에서만 판정한다. 코퍼스 전체 집계는 하지 않는다"
                    if applied else "재정렬이 적용되지 않아 s_rr 게이트를 쓸 수 없다"),
            n_relevant=n_rel, scope="candidate_pool", evidence_path=evidence)
    else:
        gscores, scope = _gate_scores(space, s_sem, stats, mask)
        base = np.ones(len(gscores), dtype=bool) if mask is None else mask
        n_rel = int((base & (gscores >= tau)).sum())
        gate_of = {it.index: (GATE_PASS if gscores[it.index] >= tau else GATE_FAIL)
                   for it in ordered}
        relevance = RelevanceSummary(tau=tau, space=space, calibrated=True,
                                     reason="라벨 표본 정밀도 곡선으로 확정된 기준값",
                                     n_relevant=n_rel, scope=scope, evidence_path=evidence)

    # --- 표시 Top-K ----------------------------------------------------
    results = []
    for r, it in enumerate(ordered[:max(1, req.top_k)], 1):
        p = engine.projects.iloc[it.index]
        a = annot[it.index]
        logit = rr_logit.get(it.index)
        year = p["selection_year"]
        results.append(ProjectResult(
            rank=r, record_id=p["record_id"], source_row=int(p["source_row"]),
            title=str(p["title_raw"]), institution=str(p.get("institution", "")),
            selection_year=(int(year) if year == year and str(year) != "" else None),
            program=str(p.get("program_대사업명", "")),
            short_title=bool(engine._short[it.index]),
            semantic_score=a["semantic_score"], semantic_percentile=a["semantic_percentile"],
            semantic_margin=a["semantic_margin"], percentile_label=a["percentile_label"],
            lexical_rank=lex_rank.get(it.index), fusion_rank=it.fusion_rank,
            rerank_score=(rr.sigmoid(logit) if logit is not None else None),
            rerank_logit=logit,
            relevance_gate=gate_of.get(it.index, GATE_UNCAL)))

    timings["total_s"] = sum(v for k, v in timings.items() if k != "total_s")
    return SearchResponse(
        query=req.query, normalized_query=q, results=results, relevance=relevance,
        warnings=warnings, notes=notes, run_mode=engine.run_mode,
        rerank_applied=applied, rerank_badge=badge, timings=timings,
        stats={"n_corpus": int(len(engine.projects)),
               "n_after_filter": int(len(engine.projects) if mask is None else mask.sum()),
               "n_candidates": len(fused), "hybrid": hybrid,
               "p99": stats.p99, "p999": stats.p999, "max": stats.max, "p50": stats.p50,
               "histogram": score_histogram(s_sem, mask)})


def score_histogram(scores: np.ndarray, mask: np.ndarray | None = None, bins: int = 40) -> dict:
    """질의 하나에 대한 **필터 대상 전체**의 의미 유사도 분포 (화면 표시용 요약).

    표시된 상위 결과가 배경 분포에서 어디에 있는지 보여주는 용도다. 관련성·정확도 축이 아니다.
    범위는 `dataset_snapshot`(필터 적용 후)이며 `n` 에 대상 수를 함께 기록한다 (v2 §12.1).
    """
    s = np.asarray(scores, dtype="float64")
    if mask is not None:
        s = s[np.asarray(mask, dtype=bool)]
    if s.size == 0:
        return {"scope_kind": "dataset_snapshot", "n": 0, "edges": [], "counts": []}
    lo, hi = float(s.min()), float(s.max())
    if hi <= lo:
        hi = lo + 1e-6
    counts, edges = np.histogram(s, bins=int(bins), range=(lo, hi))
    return {"scope_kind": "dataset_snapshot", "n": int(s.size),
            "edges": [round(float(e), 5) for e in edges],
            "counts": [int(c) for c in counts]}
