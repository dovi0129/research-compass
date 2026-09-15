# 명세 개정안 01 — 검색 v2: 하이브리드·상대 점수·재정렬기·관련도 게이트

> 문서 버전: 1.0 (2026-09-09)
> 성격: `implementation_spec.md` v1.0 에 대한 **개정안**. 원본은 수정하지 않는다. 본 문서가 원본과 충돌하면 본 문서가 우선한다.
> 영향 절: 3.2(스택), 6.3~6.5(검색·점수), 8.1(전체 집계), 14.2(계약), 15(설정), 17(작업 패키지), 18(평가), 19(테스트), 20.2(응답성)
> 근거: `docs/decisions.md` D-016(점수 압축·짧은 제목·커버리지), D-017(1차 평가), D-018(자원 배치)

---

## 0. 왜 개정하는가

실모델 1차 평가(D-017, 15질의·129건·LLM 1차 라벨)에서 확인된 사실:

| 사실 | 수치 | 함의 |
|---|---|---|
| 의미검색 > 어휘검색 | 엄격 P@5 0.40~0.44 vs 0.22~0.28 | 의미검색을 기본으로 유지 |
| 두 방식의 상위 결과가 거의 안 겹침 | 겹침 9/50, 12/100 | **결합하면 이득일 가능성** |
| 엄격 P@5 ≈ 0.4 | 상위 5개 중 2개만 "직접 관련" | **재정렬 단계** 필요 |
| 코사인 점수 압축 | Top-5 가 0.02 폭, 라벨 2/1/0 분포 겹침 | **절대 tau 불가.** 상대 기준·심층 표본 필요 |
| 짧은 제목 노이즈 | 풀 내 효과 미미(0.40→0.41) | 기본 제외 안 함. 옵션 유지 |

원본 명세는 "임베딩 → Top-K → 절대 tau" 한 단계 구조였다. 본 개정안은 이를 **4단계 파이프라인**으로 바꾼다.
원본 2.4 가 "재정렬 모델(reranker)"을 별도 확장으로 분류했으므로, 이 개정안이 그 승인 기록이다.

## 1. 목표 / 비목표

**목표**
- 엄격 P@5 를 의미검색 단독 대비 유의하게 높인다. 목표치는 정하지 않는다(실측으로 보고). 다만 **어휘 baseline 보다 낮으면 채택하지 않는다.**
- 관련도 게이트(tau)를 **측정 근거로** 확정하여 FR-03 전체 집계와 FR-04 후보의 판단 보류를 해제할 수 있게 한다.
- 시연은 **노트북 단독·오프라인**으로 동작한다.

**비목표**
- 생성형 LLM 을 검색 경로에 넣지 않는다. 질의 확장·순위 판정에 LLM 을 쓰지 않는다. (원본 11.2 유지)
- 초록·본문 등 원본에 없는 텍스트를 만들어 보충하지 않는다. (원본 6.2 유지)
- NPU(kt cloud) 의존성을 만들지 않는다. (D-018)
- recall 을 측정한다고 주장하지 않는다. (원본 18.3)

## 2. 파이프라인

```
질의 q
 ├─ S1 의미 검색   BGE-M3 → 전체 코퍼스 점수 s_sem(d)        [기존]
 ├─ S1' 어휘 검색  char n-gram TF-IDF → s_lex(d)             [기존 baseline]
 ├─ S2 결합       RRF(rank_sem, rank_lex) → 후보 상위 N_c     [신규 FR-01a]
 ├─ S3 상대 점수  margin(d) = s_sem(d) − p99(s_sem)          [신규 FR-01b]
 ├─ S4 재정렬     cross-encoder(q, title_d) → s_rr(d), 상위 N_r  [신규 FR-01c]
 └─ S5 게이트     relevant(d) := s_rr(d) ≥ tau_rr  (tau 미확정 시 보류)   [개정 FR-01d]
        → 표시 Top-K / 전체 집계 R (원본 8.1) / 후보 생성 입력 (원본 9)
```

- S2·S3 은 모델 추가가 없다. S4 만 모델 1개(재정렬기)를 추가한다.
- 각 단계는 **끌 수 있다.** `hybrid=false` 면 S2 는 의미검색 순위를 그대로 통과시키고, `rerank=false` 면 S4 를 건너뛰고 S5 는 `s_sem` 기반 tau 를 쓴다(단, 그 tau 도 미확정이면 보류).
- 실행 위치: 전 단계 **노트북 CPU**. 연구실 서버는 설정 실험·재인덱싱에만 쓴다(D-018).

## 3. FR-01a — 하이브리드 결합 (RRF)

**정의.** 방식 m ∈ {sem, lex} 의 순위 r_m(d) (1부터, 필터 통과 집합 기준)에 대해

```
rrf(d) = Σ_m  1 / (k + r_m(d))       k = 60 (초기값, 설정 노출)
```

한 방식에만 등장한 문서는 그 방식 항만 더한다. 후보 집합은 각 방식 상위 N_c/2 의 합집합(기본 N_c = 100).

**규칙**
- 필터(연도·사업·기관)는 두 방식 **모두**에 먼저 적용한다(원본 6.3-5).
- 동점은 `record_id` 로 안정 정렬(원본 6.3-6).
- RRF 값은 화면에 **표시하지 않는다.** 결합 순위만 쓰고, 사용자에게는 의미 유사도·재정렬 점수·"어휘 일치" 표지만 보여준다.
- 채택 조건: dev·test 모두에서 RRF 상위 후보의 P@5 가 의미검색 단독 이상. 미달이면 `hybrid=false` 를 기본값으로 두고 결과를 기록한다.

## 4. FR-01b — 질의 상대 점수

**정의.** 질의별 전체 코퍼스 의미 점수 분포에서

```
p99(q)   = s_sem 의 99 백분위          margin(d) = s_sem(d) − p99(q)
pct(d)   = d 보다 점수가 높은 문서 비율 (예: 0.0008 → "상위 0.08%")
```

**용도**
- 표시: 유사도 옆에 `코퍼스 상위 0.08%` 처럼 **상대 위치**를 함께 보여 절대값 오독을 막는다.
- 게이트 후보: 재정렬기가 꺼져 있을 때 S5 의 tau 를 절대 코사인 대신 `margin` 또는 순위로 정의할 수 있다. 어느 공간이 정밀도 곡선이 깨끗한지는 7절 절차로 결정한다.

**금지.** `pct` 를 "정확도"나 "관련 확률"로 표기하지 않는다. "상위 0.1%" 는 분포 위치이며 관련성 판정이 아님을 툴팁에 적는다.

## 5. FR-01c — 재정렬 (cross-encoder)

### 5.1 모델
- 기본: `BAAI/bge-reranker-v2-m3` (XLM-RoBERTa 계열, 다국어, 568M). BGE-M3 와 동일 계열이라 토크나이저·언어 커버리지가 맞는다.
- revision 을 고정하고 `rerank_manifest.json` 에 기록한다(원본 20.1).
- 대체 후보(성능·속도 문제 시): `BAAI/bge-reranker-base`(278M). 교체는 결정 기록 후에만.

### 5.2 입력·출력
- 입력 쌍: (정규화 질의, `search_text` = 정규화 과제명). 기관·연구자·사업명은 넣지 않는다(원본 6.2).
- 대상: S2 결합 순위 상위 **N_r** 건 (기본 20, 허용 10~50). 표시 Top-K 는 N_r 이하.
- 출력: `s_rr(d)` = 모델 로짓. 화면에는 `재정렬 점수 0.XX`(시그모이드) 로 표기하되 **확률·정확도가 아니라고 명시**한다.
- 재정렬 후 표시 순위는 `s_rr` 내림차순, 동점은 RRF 순위.

### 5.3 실행 경로와 폴백
| 경로 | 기본값 | 조건 |
|---|---|---|
| 노트북 CPU | **기본** | 모델이 로컬 캐시에 있음 |
| 연구실 서버(SSH 터널) | 실험용 | 설정 sweep·대량 재점수. 시연 경로 아님 |
| kt cloud NPU | 보류 | D-018 |

- 재정렬기 로딩 실패·시간 초과(설정 `rerank.timeout_s`, 기본 10초) 시 **S4 를 건너뛰고** S2 순위로 표시하며 화면에 `재정렬 미적용` 배지를 붙인다. 조용히 대체하지 않는다.
- `search` 는 항상 오프라인(HF_HUB_OFFLINE). 모델은 `build-index` 또는 `prepare-reranker` 단계에서만 내려받는다.

### 5.4 재현성
- 같은 입력·같은 revision·같은 N_r 에서 순위가 재현되어야 한다. CPU/서버 간 로짓 차이의 허용 오차(1e-3)와 순위 뒤집힘 여부를 T-29 로 기록한다.

### 5.5 채택 조건
- dev·test 모두에서 **엄격 P@5 가 S2 단독 대비 상승**하고 어휘 baseline 을 넘는다.
- warm 응답(모델 적재 후)이 N_r=20 에서 **5초 이내**(원본 20.2 목표). 초과 시 N_r 을 줄여 재측정하고, 10 까지 줄여도 초과면 `rerank=false` 기본값.

## 6. FR-01d — 관련도 게이트(tau) 절차

원본 6.4 의 "사람 평가로 정한다" 를 **절차**로 구체화한다.

### 6.1 표본
- `make-tau-probe`: 개발 질의마다 S1 순위 6·7·8·9·10·15·20·30·50·100·200·500 위 + 무작위 3건. (Top-5 는 이미 라벨됨)
- 라벨은 **점수기(scorer)와 독립**이다. 같은 항목을 `s_sem`, `margin`, `rrf`, `s_rr` 어느 공간에서도 다시 점수 매길 수 있다(`rescore-pool`). 라벨 시트는 재사용하고 key 에 점수 컬럼만 추가한다.

### 6.2 곡선
- 점수 공간 X ∈ {s_sem, margin, 순위, s_rr} 각각에 대해 `P_X(t) = score_X ≥ t 인 항목 중 라벨 2∪1 비율` 과 구간별(비누적) 관련 비율을 계산한다(`analyze-tau`).
- U 는 분모에서 제외하고 건수를 보고한다.

### 6.3 선택 규칙
1. 곡선이 **단조 감소에 가깝고 구간별 비율이 한 지점에서 뚝 떨어지는** 점수 공간을 고른다. 여러 공간이 비슷하면 재정렬기가 켜진 기본 경로의 공간(`s_rr`)을 우선한다.
2. tau 는 `P_X(tau) ≥ 0.7` 을 만족하는 **가장 낮은 t**. 0.7 은 초기 목표이며 설정에 노출한다. 만족하는 t 가 없으면 tau 는 `null` 로 남기고 게이트는 보류를 유지한다.
3. 결정과 근거(곡선 표, 표본 수, 라벨러, 날짜)를 `evaluation/results/tau_decision.json` 과 `decisions.md` 에 기록한다. 설정 파일에는 값과 함께 `threshold_evidence_path` 를 채운다(원본 15).

### 6.4 갱신 조건
- 모델 revision·텍스트 구성·N_r 이 바뀌면 tau 는 무효가 되고 재측정한다. `capabilities.json` 의 `opportunity_candidates`·`year_distribution(전체 집계)` 는 tau 가 유효할 때만 `verified`.

## 7. 데이터 계약 변경 (원본 14.2 보강)

`SearchRequest` 추가 필드
```
hybrid: bool = true
rerank: bool = true
rerank_top_n: int = 20        # 10~50
exclude_short: bool = false
```

`ProjectResult` 추가 필드
```
semantic_score        # 기존 s_sem
semantic_percentile   # pct(d)
semantic_margin       # margin(d)
lexical_rank | null
fusion_rank           # RRF 순위 (표시하지 않음, 감사용)
rerank_score | null   # s_rr 시그모이드. rerank=false 또는 실패 시 null
relevance_gate        # "pass" | "fail" | "uncalibrated"
```

`SearchResponse.warnings` 코드 추가: `RERANK_SKIPPED`, `RERANK_TIMEOUT`, `HYBRID_DISABLED_BY_EVAL`.

산출물 추가: `artifacts/rerank_manifest.json` (model_id, revision, dtype, top_n, device, 적재시간), `evaluation/results/tau_decision.json`.

## 8. 설정 (원본 15 보강)

```yaml
retrieval:
  hybrid: true
  rrf_k: 60
  candidate_pool: 100
  project_relevance_threshold: null      # tau (6절 절차로만 채움)
  threshold_space: null                  # s_sem | margin | rank | s_rr
  threshold_target_precision: 0.7
  threshold_evidence_path: null

rerank:
  enabled: true
  model_id: BAAI/bge-reranker-v2-m3
  revision: null                         # 확보한 커밋으로 고정
  top_n: 20
  max_tokens: 256
  device: cpu
  timeout_s: 10
```

## 9. 평가 프로토콜 (원본 18 보강)

### 9.1 조건 매트릭스
| 조건 | S2 | S4 | 비고 |
|---|---|---|---|
| A 의미 단독 | off | off | 기준선 (D-017 값) |
| B 어휘 단독 | — | — | baseline (D-017 값) |
| C RRF | on | off | FR-01a 채택 판정 |
| D RRF + 재정렬 | on | on (N_r=20) | FR-01c 채택 판정 |
| D' | on | on (N_r=50) | 지연 vs 품질 |

같은 라벨 시트로 채점한다. 새 조건에서 Top-5 에 처음 등장하는 항목만 추가 라벨한다(증분 풀).

### 9.2 지표
- 엄격·완화 P@5 (하한, 상한), 질의별 표 (원본 18.3)
- 라벨 시트 증분 건수, U 건수
- cold(모델 적재 포함)·warm 응답시간, N_r 별
- tau 곡선 (6절)

### 9.3 라벨러 정책
- 1차 라벨: LLM(Claude Sonnet), 블라인드(채점 키 격리). 시트에 `labeler` 기록.
- **사람 스팟체크 30건 이상**(2/1 경계 위주)을 발표 전 수행, AI–사람 일치율을 보고서에 병기. 이것 없이 P@5 를 "검증됨"으로 표기하지 않는다.
- 평가 질의(test)는 tau·설정 조정에 쓰지 않는다(원본 18.1).

## 10. 성능·운영 (원본 20.2 보강)

| 항목 | 목표 | 측정 |
|---|---|---|
| warm 검색 (S1+S2+S3) | ≤ 1초 | 노트북 |
| warm 검색 + 재정렬 N_r=20 | ≤ 5초 | 노트북 |
| cold (BGE-M3 + 재정렬기 적재) | 보고만 | 노트북 |
| 메모리 | BGE-M3 2.3GB + 재정렬기 2.2GB 동시 적재 → RAM 6GB 이상 권고 | `doctor` 에 표시 |

디스크: 재정렬기 2.2GB 추가(safetensors 만). `doctor` 의 모델 캐시 항목에 포함.

## 11. 작업 패키지 (원본 17 보강)

| 패키지 | 작업 | 산출물 | 통과 조건 |
|---|---|---|---|
| **G2-B1** tau 표본 | `make-tau-probe` 실행 → LLM 라벨 → `analyze-tau`(s_sem·margin·rank) | `label_sheet_tau_dev.llm.csv`, `tau_curve_dev.json` | 곡선 산출. tau 확정 여부와 근거 기록 |
| **G2-B2** 하이브리드·상대점수 | `fusion.py`(RRF), `relative.py`, `search` 통합, 증분 라벨, 조건 C 채점 | 코드·테스트·`evaluation_C.json` | C ≥ A (dev·test). 미달 시 hybrid 기본 off 기록 |
| **G2-B3** 재정렬기 | `rerank.py`(CPU, 폴백, manifest), `prepare-reranker`, `search --rerank`, 조건 D/D' 채점, 지연 실측 | 코드·테스트·`rerank_manifest.json`·`evaluation_D.json` | D 엄격 P@5 > C, warm ≤ 5초. 미달 시 N_r 축소 또는 rerank 기본 off 기록 |
| **G2-B4** tau 확정 | `rescore-pool`(s_rr)·`analyze-tau`(s_rr) → 6.3 규칙 적용 → config·capabilities 갱신 | `tau_decision.json`, config, `capabilities.json` | tau 값 또는 `null`+사유. FR-03 전체 집계·FR-04 게이트 상태 갱신 |
| **G2-B5** 보고 | `retrieval_evaluation.md` v2 (A~D' 표, 지연, tau, 라벨러 정책) | 보고서 | 21.4 형식 준수. 사람 스팟체크 일정 명시 |

순서: B1 → B2 → B3 → B4 → B5. B2·B3 코드는 B1 과 병행 가능. 서버는 B3 의 sweep 에만 사용.

## 12. 필수 테스트 추가 (원본 19 보강)

| ID | 시험 | 통과 조건 |
|---|---|---|
| T-25 | RRF 계산 | 두 방식 순위 → 정의식대로 결합, 한쪽만 있는 문서 처리, k 변경 반영 |
| T-26 | 필터 후 결합 | 필터 통과 집합에서만 순위·결합. 필터 밖 문서 등장 없음 |
| T-27 | 상대 점수 | p99·margin·pct 계산, 단일 문서 코퍼스에서도 NaN 없음 |
| T-28 | 재정렬 입력 | 기관·연구자·사업명이 쌍에 포함되지 않음 |
| T-29 | 재정렬 재현성 | 동일 입력 반복 시 순위 동일. 로짓 오차 ≤ 1e-3 |
| T-30 | 재정렬 폴백 | 로딩 실패·타임아웃 시 S2 순위로 표시 + `RERANK_SKIPPED` 경고. 조용한 대체 없음 |
| T-31 | 게이트 보류 | tau=null 이면 `relevance_gate=uncalibrated`, 전체 집계·후보 생성 안 함 |
| T-32 | tau 곡선 | 라벨·점수 → 누적/구간 정밀도, U 제외·보고, 제안 규칙 |
| T-33 | 라벨 재사용 | 같은 시트를 다른 점수기로 rescore 해도 라벨·item_id 불변 |
| T-34 | 표시 문구 | 화면·내보내기에 "정확도", "확률" 표기 없음. `상위 x%` 에 분포 위치 설명 부착 |

## 13. 리스크와 미결

| 리스크 | 대응 |
|---|---|
| 재정렬기가 짧은 제목에도 높은 점수를 줄 수 있음 | 조건 D 채점에서 `short_title` 별도 집계. 악화 시 `exclude_short` 기본값 재검토 |
| CPU 지연이 목표 초과 | N_r 20→10, max_tokens 256→128. 그래도 초과면 기본 off |
| 라벨이 LLM 1차뿐 | 사람 스팟체크 30건 필수 (9.3). 발표 자료에 라벨러 명시 |
| 이공계 질의의 약한 커버리지는 재정렬로 해결되지 않음 | 데이터 한계로 보고. 시연 질의는 인문사회 중심 |
| 재정렬기 다운로드가 노트북에서만 가능 | `prepare-reranker` 명령 + `run_*.bat` 로 절차화 |

## 14. 발표 문구 가이드

말할 수 있는 것: "의미검색 위에 교차인코더 재정렬을 두어 상위 결과의 직접 관련 비율을 A→D 로 높였다(수치)", "관련도 기준값은 라벨 표본의 정밀도 곡선에서 정했고 근거 파일이 있다", "모델·설정이 바뀌면 기준값을 무효화하는 규칙이 있다".
말하지 않는 것: "정확도 N%", "관련 확률", "연구공백 탐지". 재정렬 점수는 확률이 아니다.

---

## 워커 시작 지시

> 본 개정안 11절 순서로 진행한다. B1 은 사용자가 `run_tau_probe.bat` 을 실행해 표본을 만든 뒤 LLM 라벨·분석으로 이어간다.
> B2·B3 은 실모델 없이 단위 테스트가 통과하도록 구현하되, 실측(P@5·지연)은 노트북 실행 결과로만 기록한다.
> 모든 채택 판정은 dev 와 test 둘 다에서 성립해야 하며, 미달 시 기본값을 끄고 그 사실을 `decisions.md` 에 남긴다.
