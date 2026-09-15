"""질의 상대 점수 (개정안 01 FR-01b, 4절).

절대 코사인 값은 질의마다 분포가 달라 그대로 읽으면 오독한다(D-016: Top-5 가 0.02 폭).
질의별 전체 코퍼스 분포 안에서의 **상대 위치**를 함께 계산한다.

    p99(q)   = s_sem 의 99 백분위
    margin(d) = s_sem(d) − p99(q)
    pct(d)    = d 보다 점수가 높은 문서 비율

금지: pct 를 "정확도"나 "관련 확률"로 표기하지 않는다 (개정안 4절).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# 화면·내보내기에 붙는 고정 문구. 분포 위치이며 관련성 판정이 아님을 명시한다 (T-34).
PERCENTILE_TOOLTIP = ("질의에 대한 전체 코퍼스 점수 분포에서의 위치입니다. "
                      "관련성 판정도, 정확도도, 확률도 아닙니다.")


@dataclass
class RelativeStats:
    """한 질의에 대한 분포 요약. 문서별 상대 점수의 기준이 된다."""
    n: int
    p99: float
    p999: float
    p90: float
    p50: float
    max: float

    def margin(self, score: float) -> float:
        return float(score) - self.p99


def query_stats(scores: np.ndarray, mask: np.ndarray | None = None) -> RelativeStats:
    """필터 통과 집합의 점수 분포. 단일 문서 코퍼스에서도 NaN 을 만들지 않는다 (T-27)."""
    s = np.asarray(scores, dtype="float64")
    if mask is not None:
        s = s[mask]
    if s.size == 0:
        raise ValueError("점수 분포를 계산할 문서가 없다 (필터가 전부 제외했다)")
    q = np.quantile(s, [0.5, 0.9, 0.99, 0.999])   # size==1 이면 모든 분위가 그 값이다
    return RelativeStats(n=int(s.size), p50=float(q[0]), p90=float(q[1]),
                         p99=float(q[2]), p999=float(q[3]), max=float(s.max()))


def percentile_of(scores: np.ndarray, value: float, mask: np.ndarray | None = None) -> float:
    """value 보다 **높은** 점수를 가진 문서의 비율. 0.0008 -> 상위 0.08%.

    비교는 코퍼스 배열의 dtype 으로 맞춘다. float32 점수를 float64 값과 비교하면
    동점 문서가 "더 높다"로 잡혀(0.8f32 > 0.8f64) 백분위가 어긋난다.
    """
    s = np.asarray(scores)
    if mask is not None:
        s = s[mask]
    if s.size == 0:
        return float("nan")
    v = np.asarray(value).astype(s.dtype, copy=False)
    return float((s > v).sum()) / float(s.size)


def format_percentile(pct: float) -> str:
    """`상위 0.08%` 형태의 표시 문자열. 관련성·확률 표현을 쓰지 않는다."""
    if pct != pct:                                  # NaN
        return "상위 비율 계산 불가"
    p = pct * 100.0
    if p == 0.0:
        return "코퍼스 최상위"
    return f"코퍼스 상위 {p:.2f}%" if p < 1 else f"코퍼스 상위 {p:.1f}%"


def annotate(scores: np.ndarray, indices: list[int], mask: np.ndarray | None = None
             ) -> tuple[RelativeStats, dict[int, dict]]:
    """선택된 문서들에 상대 점수를 붙인다. 반환: (분포 요약, {행위치: {...}})"""
    st = query_stats(scores, mask)
    out = {}
    for i in indices:
        sc = float(scores[i])
        pct = percentile_of(scores, sc, mask)
        out[i] = {"semantic_score": sc,
                  "semantic_margin": st.margin(sc),
                  "semantic_percentile": pct,
                  "percentile_label": format_percentile(pct)}
    return st, out
