"""재정렬 — cross-encoder (개정안 01 FR-01c, 5절).

의미검색이 뽑은 후보를 (질의, 과제명) 쌍으로 다시 채점한다. 생성형 모델이 아니며
원본에 없는 텍스트를 만들지 않는다 (개정안 1절 비목표).

규칙
- 입력 쌍은 (정규화 질의, search_text) 뿐이다. 기관·연구자·사업명은 넣지 않는다 (T-28).
- 실패·시간초과 시 **조용히 대체하지 않는다.** S2 순위를 그대로 쓰고 경고 코드를 남긴다 (T-30).
- 출력 로짓은 확률·정확도가 아니다. 화면 표기는 시그모이드값이며 그 사실을 함께 적는다.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# SearchResponse.warnings 코드 (개정안 7절)
RERANK_SKIPPED = "RERANK_SKIPPED"
RERANK_TIMEOUT = "RERANK_TIMEOUT"
NOT_APPLIED_BADGE = "재정렬 미적용"
SCORE_CAPTION = "재정렬 점수 (확률·정확도가 아닙니다)"

TOP_N_MIN, TOP_N_MAX = 10, 50


class RerankTimeout(RuntimeError):
    """설정된 시간 예산을 넘겼다. 배치 경계에서 판정한다."""


def clamp_top_n(n: int) -> int:
    """허용 범위 10~50 (개정안 5.2). 범위를 벗어난 설정은 잘라서 쓴다."""
    return max(TOP_N_MIN, min(TOP_N_MAX, int(n)))


def sigmoid(logit: float) -> float:
    """표시용 변환. **확률이 아니다** (개정안 5.2)."""
    x = float(logit)
    if x >= 0:
        return float(1.0 / (1.0 + np.exp(-x)))
    e = float(np.exp(x))
    return e / (1.0 + e)


def make_pairs(query_normalized: str, search_texts: list[str]) -> list[list[str]]:
    """(정규화 질의, 정규화 과제명) 쌍만 만든다. 다른 필드를 섞지 않는다 (T-28)."""
    return [[query_normalized, str(t)] for t in search_texts]


@dataclass
class RerankResult:
    applied: bool
    scores: list[float] = field(default_factory=list)      # 로짓. applied=False 면 빈 목록
    order: list[int] = field(default_factory=list)         # 입력 목록에 대한 재정렬 순서
    warnings: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    n_scored: int = 0
    badge: str | None = None


class Reranker:
    """`BAAI/bge-reranker-v2-m3` 기본. revision 을 고정해 재현성을 확보한다."""

    def __init__(self, model_id: str, revision: str | None = None, device: str = "cpu",
                 max_tokens: int = 256, batch_size: int = 8):
        from sentence_transformers import CrossEncoder

        kw = {"device": device, "max_length": max_tokens}
        if revision:
            kw["revision"] = revision
        t0 = time.monotonic()
        self.model = CrossEncoder(model_id, **kw)
        self.load_s = time.monotonic() - t0
        self.model_id, self.device = model_id, device
        self.max_tokens, self.batch_size = max_tokens, batch_size
        self.revision = revision or self._resolved_revision()

    def _resolved_revision(self) -> str | None:
        try:
            return getattr(self.model.model.config, "_commit_hash", None)
        except Exception:
            return None

    def dtype(self) -> str:
        try:
            return str(next(self.model.model.parameters()).dtype)
        except Exception:
            return "unknown"

    def score(self, pairs: list[list[str]], deadline: float | None = None) -> np.ndarray:
        """로짓 배열. deadline(monotonic) 을 넘기면 배치 경계에서 RerankTimeout.

        배치 경계에서만 판정하는 이유: 진행 중인 forward 를 중간에 끊을 수단이 없다.
        따라서 실제 소요는 예산 + 마지막 배치 시간까지 늘어날 수 있다.
        """
        out = []
        for i in range(0, len(pairs), self.batch_size):
            if deadline is not None and time.monotonic() > deadline:
                raise RerankTimeout(f"{len(out)}개 배치 후 시간 예산 초과")
            v = self.model.predict(pairs[i:i + self.batch_size],
                                   batch_size=self.batch_size,
                                   activation_fn=None,           # 로짓 그대로 (시그모이드 금지)
                                   convert_to_numpy=True,
                                   show_progress_bar=False)
            out.append(np.asarray(v, dtype="float64").reshape(-1))
        return np.concatenate(out) if out else np.zeros(0, dtype="float64")


class StubReranker:
    """오프라인 파이프라인 검증용 결정적 재정렬기. **실제 모델이 아니다.**

    산출물에는 run_mode=test_fixture 로 표시한다. 평가 수치에 쓰지 않는다.
    """

    model_id = "stub-reranker-v1"
    revision = None
    load_s = 0.0

    def __init__(self, device: str = "cpu", max_tokens: int = 256, batch_size: int = 8, **_):
        self.device, self.max_tokens, self.batch_size = device, max_tokens, batch_size

    def dtype(self) -> str:
        return "stub"

    def score(self, pairs: list[list[str]], deadline: float | None = None) -> np.ndarray:
        # 질의·문서의 문자 3-gram 자카드 유사도를 로짓처럼 스케일. 순서 검증 전용.
        def grams(s: str) -> set[str]:
            s = str(s)
            return {s[i:i + 3] for i in range(max(1, len(s) - 2))}

        out = []
        for q, d in pairs:
            a, b = grams(q), grams(d)
            j = len(a & b) / max(1, len(a | b))
            out.append(8.0 * j - 4.0)
        return np.asarray(out, dtype="float64")


def apply_rerank(reranker, query_normalized: str, search_texts: list[str],
                 top_n: int = 20, timeout_s: float = 10.0,
                 enforce_range: bool = True) -> RerankResult:
    """상위 top_n 후보를 재정렬한다. 실패하면 applied=False 로 알리고 순위를 바꾸지 않는다.

    반환 `order` 는 입력 목록 위치의 재정렬 결과다. 동점은 입력 순서(= S2 결합 순위)를 유지한다.
    `enforce_range=False` 는 표본 재점수(`rescore-pool`) 전용 — 검색 경로에서는 쓰지 않는다.
    """
    n = min(clamp_top_n(top_n) if enforce_range else int(top_n), len(search_texts))
    if n == 0:
        return RerankResult(applied=False, warnings=[RERANK_SKIPPED],
                            badge=NOT_APPLIED_BADGE, n_scored=0)
    pairs = make_pairs(query_normalized, search_texts[:n])
    t0 = time.monotonic()
    try:
        logits = reranker.score(pairs, deadline=t0 + float(timeout_s))
    except RerankTimeout:
        return RerankResult(applied=False, warnings=[RERANK_TIMEOUT],
                            badge=NOT_APPLIED_BADGE, elapsed_s=time.monotonic() - t0)
    except Exception:
        return RerankResult(applied=False, warnings=[RERANK_SKIPPED],
                            badge=NOT_APPLIED_BADGE, elapsed_s=time.monotonic() - t0)
    if len(logits) != n:
        return RerankResult(applied=False, warnings=[RERANK_SKIPPED],
                            badge=NOT_APPLIED_BADGE, elapsed_s=time.monotonic() - t0)
    # 내림차순, 동점은 입력 순서 유지 (개정안 5.2)
    order = sorted(range(n), key=lambda i: (-float(logits[i]), i))
    return RerankResult(applied=True, scores=[float(x) for x in logits], order=order,
                        elapsed_s=time.monotonic() - t0, n_scored=n)


def make_reranker(cfg: dict, offline: bool = False):
    """설정에서 재정렬기를 만든다. 로딩 실패는 호출자가 폴백으로 처리한다."""
    r = cfg.get("rerank", {}) or {}
    if offline:
        return StubReranker(device="cpu", max_tokens=r.get("max_tokens", 256))
    return Reranker(model_id=r.get("model_id", "BAAI/bge-reranker-v2-m3"),
                    revision=r.get("revision"), device=r.get("device", "cpu"),
                    max_tokens=r.get("max_tokens", 256),
                    batch_size=r.get("batch_size", 8))


def write_manifest(path: Path, reranker, top_n: int, run_mode: str,
                   extra: dict | None = None) -> dict:
    """`artifacts/rerank_manifest.json` (개정안 7절)."""
    from datetime import datetime, timezone

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_mode": run_mode,
        "model_id": getattr(reranker, "model_id", None),
        "model_revision": getattr(reranker, "revision", None),
        "dtype": reranker.dtype(),
        "device": getattr(reranker, "device", None),
        "max_tokens": getattr(reranker, "max_tokens", None),
        "top_n": clamp_top_n(top_n),
        "load_seconds": round(float(getattr(reranker, "load_s", 0.0)), 2),
        "score_note": "출력은 로짓이며 확률·정확도가 아니다. 표시값은 시그모이드 변환.",
    }
    payload.update(extra or {})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
