# Research Compass — 작업 맥락 (Claude Code 용)

공공데이터 활용 공모전(대전, 팀 백성) 출품작. 서면 통과 → **대면 발표 + 서비스 구현**이 목표.
한국연구재단 공공데이터(과제정보 D1 11,788행 · 선정과제 연구분야 D2 851행)로 연구주제 의미검색·분야 분석·연구기회 후보를 제시하는 웹 MVP.

## 먼저 읽을 것 (이 순서)
1. `reports/handoff.md` — **현재 상태·v2 변경 대응표·실제 실행 경로** (가장 최신)
2. `research_compass_workspace_spec_v2.md` — **최상위 명세** (탐색 작업공간). 제품 범위·작업 순서를 정한다
3. `docs/plan.md` — 현재 위치와 다음 작업 (v2 W0~W6)
4. `docs/decisions.md` — D-001~D-022. 특히 D-013(분류체계 2018판), D-016~D-022
5. `docs/implementation_spec.md` — 원본 명세 v1.0 (데이터·출처·판단 보류의 기본 계약)
6. `docs/spec_amendment_01_retrieval_v2.md` — 검색 v2 개정안 (하이브리드·상대점수·재정렬기·tau)
7. `reports/data_audit.md`, `reports/retrieval_evaluation.md` — 실측 결과

**명세 우선순위:** 작업공간 v2 > 검색 개정안 01 > 원본 v1.0. v2 는 v1.0 을 대체하지 않고 제품 범위만 개정한다.

## 절대 규칙 (명세에서 옴)
- 근거 없는 기능은 켜지 않는다. 데이터가 지원하지 않으면 `disabled`/`unavailable` 이 정상 상태다.
- 생성형 LLM 을 검색·순위 경로에 넣지 않는다. 원본에 없는 텍스트(초록 등)를 만들어 보충하지 않는다.
- 결측을 0 으로 바꾸지 않는다. 제목만 같은 행을 병합하지 않는다. "과제 수" 대신 "수록 레코드 수".
- KISTEP 코드표에 있으나 D2 에 없는 코드는 `unobserved` — **`선정 0건` 이 아니다**.
- D2 기준연도는 컬럼명(2025)을 따르되 `period_status: conflicting` 유지. D2 시계열 분석 금지.
- 코사인 유사도를 정확도·확률로 표기하지 않는다. 관련도 기준값(tau)은 라벨 표본의 정밀도 곡선으로만 정한다.
- 시연은 **노트북 단독·오프라인**. 서버·클라우드는 배치 작업 전용. kt cloud NPU 는 보류(D-018).
- 개인식별 컬럼(연구책임자명·연구자번호), 접속정보·키·비밀번호는 산출물·저장소에 넣지 않는다.
- **커밋 메시지·PR 본문·문서에 Claude 공동작성자 표기(`Co-Authored-By: Claude …`)나 `Generated with Claude Code` 류 생성 도구 문구를 넣지 않는다** (사용자 지시 2026-09-15). 작성자는 사람이다. 평가 라벨을 LLM 으로 만든 사실처럼 **방법 기록으로 필요한 언급은 예외**다.

## 현재 상태 (2026-09-09)
- G0·G1·P1 완료. 실모델(BGE-M3, rev `5617a9f6…`) 인덱스 = `artifacts/`, `local_live`.
- 서버 Lab33 (RTX 5090) **bootstrap 완료** — torch `2.11.0+cu128`, sm_120 확인. 두 모델 캐시 확보. `pytest` **240개 통과**(노트북) · 서버 **212 + 1 skipped**(streamlit 미설치, D-029 뒤 미재실행).
- **화면 있음 (D-025):** `app.py` Streamlit 단일 페이지 — 주제 입력 → E 검색 → 원문·출처 카드, 요소 입력·실제 검색문 확인·관점 1개 실행, 비교함, 질의별 점수 분포·범위 명시 구성 그래프(Altair), 분야명 탐색(D2), 기능 상태표. W3 영역(근거 비교·다음 탐색·메모)도 실제 내용으로 붙어 있다(아래 D-027). 실데이터 smoke 완료(handoff §3.1~3.3).
  `.streamlit/config.toml` = 127.0.0.1 바인딩·텔레메트리 차단. 시연 전 `client.showErrorDetails="none"` 으로 바꿀 것.
  **사용자 검토 반영 (D-026):** 화면 문구에 명세 절 번호·D-0xx·모듈명·`Retrieval-E` 같은 코드명을 쓰지 않는다(개발자용 펼침에만). 막대는 **정렬에 쓴 값**(재정렬 점수)에 그린다. 10건 이하 구성은 차트 대신 한 줄 글. 준비 안 된 기능은 "준비 중" 접힘 하나.
- `analytics.py` — 범위 명시 기술통계(`dataset_snapshot`/`displayed_results`/`selected_records`). `calibrated_relevant_corpus` 는 `ScopeError`. `scoped_distribution` = `limited`.
- **W3 (D-027):** `comparison.py`(요소×과제 literal/정규화 match, 인용 `title_raw[s:e]==quote`+SHA-256, `needs_review`, 사용자 검토 confirm/reject/not_confirmed/add_quote, stale) · `nextactions.py`(§10.2 규칙 최대 3개, 실행은 확인 후) · `memo.py`(MD/JSON, 확정=사용자 검토+유효 인용만, 결정적 생성). `title_evidence_review`=limited, `exploration_memo`=available.
- **W5 (D-028):** 비교 조건 **UX-L(목록 전용)** = `app.py -- --ux l` (또는 `RESEARCH_COMPASS_UX=l`). 관점·비교함·근거 비교표·다음 탐색·구조화 메모를
  빼고 **같은 엔진·같은 스냅샷·같은 표시 건수**로 목록만 준다. UX-L 도 `검색문 직접 고치기`·`자유 메모`(`memo.free_memo`)를 가진다 —
  약한 비교 대상을 만들지 않는다. 조건 이름은 `개발자용` 펼침에만. 대본·양식·주제 실측 = `reports/ux_study/`.
  **사용자 평가는 미실시**(참여자 미확보) — 명세 §17.6 에 따라 수행했다고 보고하지 않고 사용성 수치를 만들지 않는다. UX-W 효용은 **미확정**.
- **화면 재설계 (D-029, 2026-09-10):** `app.py` 표시 계층만 다시 썼다(계산 로직 무변경). 메인 흐름 = 머리말 → 연구주제 → **관점(segmented, 항상 표시)
  + 실제 검색문** → 가까운 연구과제 70% + 비교함 30% → 선택한 과제 비교(요소×과제 표 `제목에 있음/없음` + "확인이 필요한 요소" 한 줄) →
  탐색 메모(자유 메모 → Markdown/JSON) → `추가 분석 및 데이터 정보`(접힘: **내 판단 덧붙이기·확인 작업(선택·고급)**·관련 연구분야·데이터 범위와 제약·
  검색 상세 분석·기능 및 검증 상태). 카드에 재정렬 점수 숫자 없음(막대는 정렬 값, 숫자는 `근거 보기`). 라이트/다크 = `.streamlit/config.toml`
  `[theme.light]/[theme.dark]` + 머리말 토글(세션 유지). 자유 메모는 `ws.user_notes` → `memo.build` 의 `## 사용자 자유 메모` 절(사용자 글 그대로,
  금지어 검사 제외).
- **D-030·D-031 (사용자 결정, 명세 이탈):** v2 §9.7 검토·인용 UI 와 §10 다음 작업 UI 는 **화면에서 뺐다**(로직·메모 기록 유지, 규칙 제안은 메모에
  "제안 (미확인)"). 선택 이유 입력·전체 이력·비교함 JSON·기관 필터도 뺐다. **첫 화면은 검색칸만**(로고·제목·검색칸·예시 칩), 검색 후 결과 화면으로
  전환. 결과 화면 = [브랜드|연구주제 한 줄|주제 바꾸기(팝오버)|화면 모드] → STEP 표시 → [관점|실제 검색문|탐색] (검색칸은 이것 하나) → 최근 탐색 칩 → 결과 70%/비교함 30%(유리·sticky)
  → 비교표 → 탐색 메모 → 데이터·기능 정보(접힘). 테두리 상자 대신 표면+그림자, 스켈레톤·stagger 모션, `prefers-reduced-motion` 존중.
  이후 화면 작업은 명세보다 **사용자가 5초 안에 이해하는지**를 우선한다. 디자인 리뷰는 Sonnet 하위 에이전트에게 캡처를 보여 받는다.
  **사용자 4차 검토 반영:** 설명 캡션·절 부제·스텝퍼·예시 칩·주제 바꾸기 없음(사족 금지). 브랜드 버튼 = 처음 화면(탐색 유지, `이전 결과로 돌아가기`).
  글꼴은 `static/fonts/PretendardVariable.woff2`(OFL) 를 `enableStaticServing` + `[[theme.fontFaces]]` 로 같은 출처 제공 — 외부 요청 없음.
  **5차 검토:** 팔레트 = paper & indigo(라이트 `#F7F7F5`/`#4056D6`, 다크 `#0F1117`/`#8B9CFF`), 세그먼트·칩은 각진 연결형(타원 금지),
  카드 수치는 "의미 유사도 0.xxx (N건 중 유사도 상위 x%)" 로 묶어 백분위의 기준을 밝힌다. 팔레트를 바꾸면 `PALETTES`·`ST_THEMES`·config.toml 세 곳을 함께.
  **6차 검토 (D-032):** 비교함 카드 사이 여백·구분선. `선택한 과제 비교` 는 **기관·선정연도·사업** 행을 항상 놓고 요소 행은 그 아래(요소 없어도 표).
  표 아래 안내는 "확인이 필요한 요소: …" 만, 설명은 `title` 툴팁. 뒷문장·상시 안내 삭제는 명세 §9 이탈(사용자 결정).
  **7차 검토 (D-033):** `선택한 과제 비교` 행 = 기관·선정연도·사업 계층 4단계·같은 사업/같은 기관의 **수록 레코드 수**(연도별 병기)·찾은 검색·원본 위치(링크+행).
  요소별 표현 비교는 `데이터·기능 정보` 아래 접힘. Markdown 메모는 `memo.build_brief()` 압축판(선택 과제·탐색 기록·메모), 전체 기록은 JSON 에만.
  **자유 메모 소실 버그 수정:** `st.rerun()` 실행에서 안 그려진 위젯 상태를 Streamlit 이 지움 → `ws.user_notes` 로 위젯 생성 전 복원.
  **D-034:** `이 범위로 다시 탐색` 은 표시만 남기고 `run_refilter()` 가 `탐색` 과 같은 자리에서 실행(진행 표시 위치 통일). **콜드 스타트 실측:** HTTP 1.4 s · 첫 접속(모델·인덱스 적재) 22.9 s · 첫 검색 3.9 s · warm 4.3~4.9 s → 시연 전 접속 1회 + 검색 1회로 예열.
  **8차 (D-035, 연구 작업공간 톤):** 첫 화면 = 왼쪽 정렬 compact 머리말(작은 단색 마크·단색 제목·한 줄 설명·검색칸·자료 한 줄). 평면 표면·1px 테두리·6~8px 모서리,
  그라데이션·유리·그림자·모션 제거(검색 중 shimmer 만). 다크 `#141822`/`#1C2130`. 라벨 `탐색 관점`·`현재 검색문` 표시, `직접 수정됨` 칩, `탐색 요소 조정`.
  카드는 의미 유사도만(막대·백분위 없음) → `검색 근거 보기` 에서 **최종 표시 순위 / 1차 의미검색 위치 / 의미 유사도 / 재정렬 점수** 를 다른 값으로. 비교함 0/1/2+ 문구,
  `선택한 과제 비교` 는 2건 이상에서만 표(0~1건은 한 줄) · 행 = 발견 관점 → 검색문 → 당시 순위 → 선정연도 → 사업 → 기관 → 원본 위치, 레코드 수는 접힘.
  메모 버튼 `탐색 메모 저장`·`전체 작업기록 백업`, **지연 다운로드(callable data) + 재실행 대기**로 blur 안내 삭제. `config.toml` fontFaces 아래 theme 키 ParseError 수정.
- **9차 (D-036, 2026-09-14, 교수 검토 "첫 화면이 복합적이지 않다" · 검정·보라 기각):** 첫 화면 = 머리말 → **검색 방식** 세그먼트 `[연구주제 한 문장 | 요소별 탐색 |
  연구 요약 붙여넣기 | 연구분야로 찾기]` → 검색칸 → **검색 범위 한 줄**(첫 화면·결과 화면이 `f_years`·`f_programs`·`f_short` 공유, `filters_from_state()`) →
  **수치 띠**(수록 레코드·선정연도·대사업명·주관기관명(nunique)·연구분야명) → **바닥글**(D1·D2 ID·스냅샷·색인일·모델·"공모전 출품작 — 기관의 공식 서비스가 아닙니다").
  **설명문 0개** — 사용자 지침 "이 칸은 ~" 류 금지; "복합적" = 조작 수단의 수(NIH RePORTER 3모드·NTIS 4모드 조사 근거). D-031 "검색칸만" 을 대체.
  요약 붙여넣기는 문단 전체가 `idea_text`=검색문(관점 full)이고 512토큰 초과면 **잘라 검색하지 않고 멈춤**. 결과 화면 오른쪽 = `rc_right`(비교함 + `표시 중인 N건의 구성`) sticky 묶음.
  팔레트 **행정 네이비**: 라이트 `#F3F5F7`/`#1F4E8C`, 다크 `#1E242C`/`#7FA3D1`(보라 없음), 기본 버튼 토큰 `btn` 다크 `#3D77C9`. 시험 255. 캡처 `reports/screenshots/ui6_*.png`, 스크립트 `reports/ux_study/rc_ui6_*.py`.
  **Sonnet 리뷰 반영:** 첫 화면도 **70/30** — 왼쪽 `rc_searchbox`(검색 방식·검색칸·범위를 테두리 상자 하나로) / 오른쪽 `rc_overview`(선정연도별·대사업명별 수록 레코드 막대,
  `dataset_snapshot`). 760px 토글 한 줄(첫 화면 상단바도 `rc_topbar`). `analytics.py` 범위 주의문은 "~습니다" 로 통일하고 `(D-012)` 노출 제거.
  예시 주제 칩은 넣지 않았다(4차 검토 결정과 충돌 — 사용자 재결정 대상).
- **10차 (D-037, 2026-09-14):** 첫 화면 `연구분야로 찾기` 의 기준연도 경고 줄 삭제(`(비교 불가)` 툴팁 `FIELD_COUNT_HINT` 로 대체, 접힘 `관련 연구분야` 에는 유지) ·
  화면 모드는 **페이지 맨 아래** `기능 상태` 밑 작은 글자(같은 `theme_pick` 위젯, 상단바에서 제거) · **상단 식별 띠** `.rc-band`(`render_band()`, 첫 화면·결과 화면 공통) ·
  절 제목 왼쪽 3px 강조선 · 재정렬 실패 경고에서 엔진 notes 제거. 라이트 `muted` `#465160`(7:1) · 캡션·차트 축 색 고정(`theme=None`+`axis_style`).
- **11차 (D-038, 2026-09-14, 한 페이지 골격 — D-031 전환 구조 대체):** 첫 화면/결과 화면 구분이 없다. `render_workspace()` 하나가 띠 → 머리말 → `[검색 상자 | 오른쪽]` →
  (왼쪽 열 안 최근 탐색·결과) → 비교 → 메모 → 데이터 및 검색 정보 → 수치 띠 → 바닥글 → 화면 모드를 그린다. 검색 방식 4탭은 검색 뒤에도 남고 `연구주제 한 문장` 탭이
  첫 검색 뒤 관점 행이 된다(어느 탭에서 검색해도 `mode_seed=topic`). 검색 범위는 상자 안 한 줄만(`검색 범위` 접힘·`render_filter_panel` 삭제, `이 범위로 다시 탐색` 은 그 줄 아래).
  스켈레톤·진행 표시는 결과 자리 `_RESULTS_SLOT`(상자 아래 컨테이너를 **먼저 만들고** 전역에 둠)에 그린다. 오른쪽 30% = 검색 전 수록 데이터 구성 / 뒤 비교함(+구성).
  상단바 제거. 머리말의 `Research Compass` 는 단추(`btn_home`) = **기본 화면**(`view_home`: 결과·비교함 숨김, 검색 상자는 연구주제 칸 — 다른 문장이면 새 연구주제, 상태는 보존,
  `이전 결과로 돌아가기`). 관점 세그먼트는 검색문 줄 **위에** 따로(세 열이면 70% 상자에서 겹침). 시험 256.
- 모델 revision **양쪽 고정** (D-021): bge-m3 `5617a9f6…`, reranker `953dc6f6…`. `server.yaml` 은 `default.yaml` 에서 재생성 (device 만 다름).
- **G2-B1 완료 (D-019):** tau 표본 75건 Sonnet 블라인드 라벨. `margin`(s_sem−p99) 공간이 유일하게 깨끗함 — p99 미만 24건 전부 라벨 0, 관련 41건 전부 margin ≥ 0.
  **tau 는 여전히 미확정** (`null` 유지): 이 표본에서 `margin ≥ 0` 이 `rank ≤ 100` 과 동일 분할이라 두 공간을 구분 못함 + 순위 층화 표본이라 P(tau) 가 무편향 추정치 아님. 잠정 후보 `margin, 0.00`.
- **G2-B2 완료 (D-020): 하이브리드 채택 실패 → `retrieval.hybrid: false`.** C < A 가 dev·test 양쪽, 15질의 중 악화 5·개선 2·동일 8.
  D-017 의 "안 겹치니 결합하면 이득" 추정이 반박됨 — 어휘검색이 찾아온 건 *다른 관련* 과제가 아니라 *다른 무관* 과제였다.
- **G2-B3 완료 (D-023): E 채택.** dev 엄격 0.44→0.56, test 0.40→0.44~0.48, warm 2.2~2.7s(평가 시). E'(N_r=50) 기각.
  "검증됨" 아님: 라벨은 LLM 1차뿐, dev·test 모두 `used_for_selection`. **응답시간은 노트북 부하에 따라 2.1~6.8s 로 흔들림**(handoff §3.1) — 시연 기기에서 재측정.

## 다음 작업 (v2 W1~W6, plan.md 참조)
- ~~W1·W2~~ 완료 (D-024·D-025·D-026). ~~W3~~ 완료 (D-027): `comparison.py`·`nextactions.py`·`memo.py` + 화면 세 영역. ~~W4~~ 판정 완료 (D-023).
- **W5** 🔶 조건·양식 준비 완료(D-028). 남은 것은 **실사용자 3명 실시** — `reports/ux_study/protocol.md` 를 그대로 따르면 된다.
- **W6 (다음)** 제한 기능표·재현 실행 문서·최종 인계(v2 §22). 시연 리허설: 시연 기기에서 응답시간 재측정, `showErrorDetails=none`.
- **W4 잔여** 사람 스팟체크 30건(2/1 경계) · 새 질의 5개

**W4 는 W1 의 선행 조건이 아니다.** tau·D2 기준기간·분류표는 작업공간을 막지 않지만, 그 검증이 필요한
전체 관련 집계·추세·저빈도 후보 게이트는 그대로 잠근다. **`next_actions` 를 FR-04 완료로 보고하지 않는다.**
채택 판정은 dev·test **둘 다**. 미달 시 기본값 off + decisions.md 기록. 사람 스팟체크 30건(2/1 경계)은 발표 전 필수.

## v2 가 추가한 절대 규칙
- **표현 발견 ≠ 관련성 판단 ≠ 연구내용 사실.** 제목에 '강화학습'이 있어도 그 연구가 강화학습을 썼다는 판정이 아니다(부정·비교 문맥).
- 자동 미검출은 `needs_review` 다. **연구 부재·무관함·신규성·기회가 아니다.**
- 인용은 `title_raw[start_offset:end_offset] == quote` 로 검증한다. offset 은 **0-based Unicode 코드포인트, 끝 미포함**.
- 관점 이름은 탐색 의도의 표식이지 반환 과제가 그 의도를 충족한다는 판정이 아니다. 관점별 결과를 자동 통합(RRF·점수 평균)하지 않는다.
- 기능 상태는 **자료 지원(`data_supports`)과 구현(`implemented`)을 분리**해 기록한다. 명세에 적혀 있다는 이유로 `available` 로 올리지 않는다.
- 라벨은 `(query_id, perspective, record_id)` 로 관리한다. 충돌은 `keep=first` 로 숨기지 않고 **채점을 중단**한다.

## 명령
```bash
python -m research_compass.cli doctor --quick | audit | verify-scheme | crosswalk
python -m research_compass.cli prepare | build-index | search --query "..." --stats [--exclude-short]
python -m research_compass.cli make-eval-pool --split dev|test | evaluate --split dev [--sheet ...]
python -m research_compass.cli make-tau-probe | analyze-tau [--spaces s_sem,margin,rank,s_rr]
python -m research_compass.cli rescore-pool --split dev [--with-rerank]   # 라벨 유지, key 에 점수만 추가
python -m research_compass.cli evaluate-conditions --split dev --conditions "A,B,C,D,E,E'"
#   옵션: [--perspective full|method|target_goal] [--used-for-selection]   # 평가 단위·선택 사용 표시 (v2 §17.3~17.4)
python -m research_compass.cli prepare-reranker [--no-download]
python -m pytest            # 236개 (test_app.py 는 streamlit 없으면 skip)
# 화면 (확인된 명령): .venv/Scripts/python.exe -m streamlit run app.py --server.address 127.0.0.1 [--server.port 8765]
#   다른 포트를 쓰면 화면 모드 토글이 동작하도록 config.toml [client] allowedOrigins 에 그 포트가 있어야 한다 (app.py 가 실제 포트를 덧붙이지만 첫 적재는 config 값)
#   다른 설정: ... run app.py -- --config config/server.yaml
#   사용성 비교 조건 UX-L: ... run app.py --server.port 8781 -- --ux l   # 스크립트 인자는 `--` 뒤에만
# 서버: bash server/bootstrap.sh / bash server/run.sh <build|tau-probe|eval-pool|search "q"|test|cmd "...">
#       서버 설정은 --config config/server.yaml (bootstrap 이 생성, device=cuda)
```

## 함정 (겪은 것)
- **헤드리스 Edge 캡처 금지 (사용자 지시 2026-09-14).** `reports/ux_study/rc_*_shots.py`·`rc_*_probe.py` 는 Edge 를 띄우는데 `proc.kill()` 이 부모만 죽여
  렌더러·GPU 자식이 회차마다 남았고(임시 프로필 59개) 컴퓨터가 멈춰 재시작했다. 화면 검증은 **AppTest(`tests/unit/test_app.py`)** 로 한다. 실제 캡처가 꼭 필요하면
  사용자에게 먼저 묻고, 한 번에 하나만, 종료는 `taskkill /PID <pid> /T /F`(스크립트는 그렇게 고쳐 둠). 끝난 뒤 `msedge` 프로세스와 `%TEMP%\rc_edge_*` 를 확인한다.
- `C:\학교` 는 Google Drive 동기화 폴더. Drive 가 켜져 있으면 새 파일에 하드링크가 걸려 원격 세션이 못 읽었음. `.venv` 는 Drive 밖(`C:\venvs\research-compass`)이 낫다.
- Windows 11 스마트 앱 제어가 pyarrow parquet DLL 을 차단 → 정제 데이터는 **CSV** (`store.py`). parquet 쓰지 말 것.
- HF 다운로드: `use_safetensors` 자동 판별(`embedding.py`) — 캐시에 `.bin` 만 있으면 그걸 쓴다. 두 포맷 중복 다운로드 금지.
- RTX 5090 은 torch **cu128** 이상. cu124 는 커널 없음.
- tqdm 진행바는 파이프·로그에서 안 보인다 → 청크마다 줄바꿈 진행 줄 출력(`Embedder.encode`).
- 라벨 시트는 점수기와 독립. `pool_key_*.csv` 는 라벨러에게 절대 노출하지 않는다(블라인드).
- Streamlit 1.63: `st.altair_chart(..., width="stretch")`(use_container_width 아님), `st.button(width=...)`. `AppTest.session_state` 프록시는 `.get`·반복(iteration) 불가 — 시험은 `[]`·`in` 만 쓴다. `app.py` 는 `session_state["_engine_override"]` 로 가짜 엔진 주입(시험 전용).
- Streamlit 스크롤 컨테이너 때문에 `document.body.scrollHeight` 로는 전체 페이지 높이를 못 잡는다 — 캡처 시 모든 요소의 `scrollHeight` 최댓값을 쓴다.
- 사업년도==선정년도 (전 행 동일), 수록 연도 2023~2025 만, 88% 가 학술·인문사회사업 → 연도 감소를 "지원 축소"로 읽지 말 것(D-012).
- **Bash 도구의 heredoc 은 `\\n` 을 실제 줄바꿈으로 바꿔 파이썬 문자열 리터럴을 깨뜨린다** (`memo.py` 가 이렇게 한 번 깨졌다).
  백슬래시가 들어가는 패치 스크립트는 **Write 로 파일에 쓰고 실행**한다. 치환이 0건이면 저장하지 않고 멈추게 짤 것.
- Streamlit: 위젯 아래에서 상태를 바꾸면 **그 위에 이미 그려진 위젯은 갱신되지 않는다**. `execute()` 는 검색 후 `st.rerun()` 을 호출한다
  (없으면 탐색 이력 칩이 한 박자 늦게 나타난다 — `test_second_search_shows_history_immediately` 가 잡는다).
- 헤드리스 자동화로 화면을 검증할 때 `<input>`·`<textarea>` 값은 `document.body.innerText` 에 **없다**. `.value` 로 읽고,
  실행 여부는 `.rc-sub`/`.rc-meta` 텍스트·이력 칩 수로 판정할 것 (innerText 로 판정해 "실행 안 됨" 오진을 한 적 있다).
  **재실행 중에 보낸 클릭은 무시된다** — 클릭 뒤에는 상태 변화(이력 칩 수 증가)를 기다려야 한다. 두 번째 오진(D-029)도 이것이었다.
- Streamlit 1.63 테마: 런타임 `theme.base` 변경은 **안 통한다**. 토글은 같은 출처 `st.iframe` 에서 부모 컨텍스트로 `SET_CUSTOM_THEME_CONFIG`
  호스트 메시지를 보낸다(`client.allowedOrigins` 에 앱 출처 필요). `st.context.theme.type` 은 한 실행 늦게 바뀐다 — 그래서 **시스템 모드의 팔레트는
  파이썬에서 고르지 말고 CSS `@media (prefers-color-scheme: dark)` 로 덧씌운다**(`build_css(follow_os=True)`). 안 그러면 라이트→시스템 전환에서
  우리 배경은 라이트, 위젯은 다크인 반쪽 화면이 한 번 나온다(D-036 추기 2). 토글 재현·측정은 `reports/ux_study/rc_theme_probe.py [--dark]`.
- 서버 로그의 `No module named 'torchvision'` 트레이스백 수백 줄은 Streamlit 파일 감시기가 transformers lazy 모듈을 건드린 **warning 잡음**이다(재실행 지연 없음).
  `config.toml` `[logger] level = "error"` 로 숨겼다. `WinError 10022` 도 접속 끊김 잡음. 진짜 오류는 `Traceback` 중 이 둘을 뺀 것만 본다. `st.components.v1.html` 은
  폐기 예고 → `st.iframe(html, height=1)`.
- Streamlit 마크다운 안의 `h2` 는 자체 크기·여백 규칙이 붙는다 — `.rc-sec` 같은 클래스 규칙은 `!important` 없이는 지지 않는다.
- UX-L 시험은 `비교함`·`다음 탐색` 같은 낱말이 **CSS 주석에 있어도** 잡는다(마크다운에 스타일이 포함됨). 주석에도 그 낱말을 쓰지 말 것.
- Streamlit 1.63 DOM: `st.container(border=True, key=X)` = `stLayoutWrapper > stVerticalBlock.st-key-X`, **테두리는 그 블록 자체**에 있다
  (`stVerticalBlockBorderWrapper` 없음). 카드·패널은 `.st-key-X` 를 직접 꾸미고, `.st-key-X > div:first-child` 는 쓰지 말 것(제목 줄에 배경이 칠해져
  흰 띠). 열 쌓임·sticky 는 `stColumn > stVerticalBlock > stLayoutWrapper > 블록` 경로를 따라 CSS 를 건다 (app.py CSS 의 `@media (max-width: 1000px)` 참고).
- 위젯 생성 뒤 같은 실행에서 그 위젯의 `session_state` 값을 바꾸면 예외(`StreamlitWidgetAlreadyInstantiatedError`). 칩 선택 해제 등은 `on_change` 콜백에서.
- **`download_button` 의 data 는 렌더 시점 값이고 `text_area` 는 blur 때 값을 보낸다** → 쓰고 바로 저장하면 마지막 글이 빠진다. 1.63 은 `data=callable`(지연 다운로드)을
  지원하지만 callable 은 클릭 직후 별도 스레드에서 돌아 blur 재실행보다 먼저 실행된다 → `_wait_for_rerun` 이 실행 번호(`session_state["_sync"]["run"]`) 증가를 최대 1.2 s 기다린다.
  버튼은 `on_click="ignore"` 여야 한다 — 클릭이 재실행을 일으키면 프런트엔드가 버튼을 다시 그려 내려받기 응답을 버린다(실측). 헤드리스로 확인할 때 같은 이름 파일은 **덮어써지므로**
  새 파일명이 아니라 mtime 으로 판정하고, 버튼은 `getBoundingClientRect().width > 0` 인 것만 클릭한다(이전 프레임의 0×0 잔재가 먼저 잡힌다).
- **`config.toml` 의 `[[theme.fontFaces]]` 는 배열 표** — 그 아래 적은 `baseRadius`·`showWidgetBorder` 는 FontFace 필드로 읽혀 세션마다 `ParseError` 가 난다. theme 키는 fontFaces 위에.
- **Git Bash 에서 `streamlit run` 을 띄우면 stdout 이 cp949** → 모델 적재 로그의 `—` 에서 `UnicodeEncodeError` 로 엔진 적재 실패(화면은 '준비 안 됨'). PowerShell 이나 `PYTHONUTF8=1` 로.
- **`st.altair_chart` 기본 테마는 차트의 `configure_axis` 를 덮어쓴다** — 축 색을 직접 정하려면 `theme=None` + `axis_style()`(배경 투명·글꼴·축 색). `st.caption` 도 테마 글자색 60% 라
  `[data-testid="stCaptionContainer"]` 를 `var(--muted)` 로 고정했다. 라이트 `muted` 는 배경 대비 7:1 이상(`#465160`)으로 유지할 것 — 5.2:1 이던 때 "글자가 흐리다" 검토를 받았다.
- **폼 제출 버튼의 testid 는 `stBaseButton-primaryFormSubmit`** — `stBaseButton-primary` 규칙이 닿지 않아 config 의 primaryColor 로 그려진다. 기본 버튼 CSS 는 둘 다 잡을 것 (D-036).
- `src/research_compass/*` 를 고치면 **앱을 다시 띄워야** 화면에 반영된다(analytics 문구를 고치고 옛 문구가 캡처돼 한 번 헛돌았다). `app.py` 만 고친 경우는 자동 반영.
- **폼 안 `input` 에 거는 CSS 는 `input[type="text"]` 로 한정** — `[data-testid="stForm"] input {height}` 가 라디오의 `<input>` 에도 걸려 관점 선택이 빈 칸으로 그려졌다 (D-036).
- 열 안에서 sticky 패널 아래 다른 패널을 두려면 **한 컨테이너(`rc_right`)로 묶는다** — 따로 두면 `height:100%` 래퍼가 둘째 패널을 열 바닥으로 밀어낸다 (D-036).
- 첫 화면처럼 폼 제출이 곧 `execute()`→`st.rerun()` 인 곳에서는 **그 아래 위젯(검색 범위)을 코드에서 먼저 만들고 컨테이너로 자리만 아래에** 둔다 — 아니면 아래 함정.
- **`st.rerun()` 을 부른 실행에서 아직 그려지지 않은 위젯은 그 실행에 '없는 위젯' 이라 Streamlit 이 `session_state` 값을 지운다.**
  화면 입력칸에는 글이 남아 있어 눈으로는 못 잡는다(자유 메모가 이렇게 사라졌다, D-033). 값이 중요한 위젯은 위젯 밖(`ws.*`)에 보관하고 생성 전에 복원한다.
