# 인수인계 — 어떤 도구이고 어떻게 띄우는가

기능 요약과 실행 방법만 적었다.
화면을 하나씩 따라 하는 사용법은 `docs/user_guide.md`, 기능의 정확한 범위와 제한은 `reports/feature_specification.md` 에 있다.

## 1. 무엇을 하는 도구인가

연구주제를 한 문장 넣으면 한국연구재단 공공데이터(과제정보 정제 11,783건 · 선정과제 연구분야 851행)에서
**제목 의미가 가까운 지원과제**를 찾아 주고, 몇 건을 골라 나란히 비교하고, 탐색 과정을 메모로 내보낸다.

노트북 한 대에서 오프라인으로 돌아간다. 검색 경로에 생성형 LLM 이 없다 —
임베딩 모델(BGE-M3)로 제목 의미를 비교하고 재정렬기로 순서를 고칠 뿐, 문장을 지어내지 않는다.

## 2. 기능

화면은 **한 페이지**다. 검색하면 검색 상자는 그 자리에 남고 바로 아래에 결과가 붙는다.

### 검색 상자

- **검색 방식 4개** — `연구주제 한 문장` · `요소별 탐색`(대상·방법·목표를 나눠 입력) ·
  `연구 요약 붙여넣기`(문단 전체를 검색문으로) · `연구분야로 찾기`(D2 분야명으로 찾아 검색문에 넣기)
- **검색 범위** — 선정년도·대사업명 선택, 짧은 제목 제외. 검색 전에도 걸 수 있다
- **탐색 관점** (첫 검색 뒤) — 같은 주제를 `전체 연구주제` / `방법·접근` / `대상·문제` 세 각도로 다시 검색
- **현재 검색문** — 실제로 검색에 들어간 문장을 보여 주고 직접 고칠 수 있다

### 결과

- 제목이 유사한 과제 카드 — 과제명, 주관기관, 선정년도, 사업, 의미 유사도. 기본 5건, 더 보기로 10건
- **검색 근거 보기** — 최종 표시 순위 / 1차 의미검색 위치 / 의미 유사도 / 재정렬 점수를 각각 보여 준다
- 최근 탐색 칩으로 이전 검색으로 되돌아간다

### 비교와 기록

- **비교함** (오른쪽) — 관심 과제를 담는다. 담긴 과제의 연도·사업 구성을 그래프로 보여 준다
- **선택한 과제 비교** — 담은 과제를 한 표에 놓는다. 발견한 관점, 그때 쓴 검색문, 당시 순위,
  선정년도·사업·기관, 원본 위치(행 번호)까지 나온다
- **탐색 메모** — Markdown(요약본)과 JSON(전체 기록)으로 내려받는다

### 맨 아래

수록 데이터 구성·관련 연구분야·검색 상세 분석·기능 상태표가 접힘으로 들어 있고,
수록 레코드 수 띠와 출처 바닥글, 화면 모드(시스템/라이트/다크) 전환이 있다.

> 근거가 없는 기능은 **잠가 놨다.** 분야 간 선정횟수 비교, 전체 관련 집계 같은 것이 그렇다.
> 화면에 "준비 중"·"제공하지 않습니다"로 나오면 버그가 아니라 의도된 제한이다. 무엇이 왜 잠겼는지는
> `reports/feature_specification.md` §6 기능 상태표에 있다.

---

## 3. 실행

### 3.1 저장소에 없는 것

소스코드와 문서만 올려 두었다. 아래 셋은 각자 준비해야 한다.

| 없는 것 | 크기 | 어떻게 |
|---|---|---|
| 원본 데이터 `data/raw/` | 약 3.4 MB | 공공데이터포털에서 직접 받는다 (3.3) |
| 임베딩 인덱스 `artifacts/*.npy` | 49 MB | `build-index` 로 만든다 (3.4) |
| 모델 가중치 | 4.3 GB | `build-index`·`prepare-reranker` 가 자동으로 받는다 |

원본에 개인식별 컬럼(연구책임자명·연구자번호)이 있어 저장소에 넣지 않는다.

### 3.2 설치

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[search,ui,dev]"
```

Python 3.10 이상(개발은 3.12). 가상환경을 Google Drive·OneDrive 동기화 폴더 안에 두면 설치가 깨진다.

확인: `python -m pytest` → **256개 통과**(streamlit 이 없으면 화면 시험은 skip).

### 3.3 원본 데이터 받기

공공데이터포털에서 **로그인 후 직접** 내려받아 `data/raw/` 에 그대로 넣는다. 파일명은 바꾸지 않아도 된다.

| 키 | 데이터셋 | 페이지 |
|---|---|---|
| D1 (필수) | 한국연구재단_이알앤디_과제정보 | <https://www.data.go.kr/data/3049029/fileData.do> |
| D2 (필수) | 한국연구재단_선정과제 연구분야 | <https://www.data.go.kr/data/15120687/fileData.do> |
| K18 (분류체계 확인용) | KISTEP_과학기술표준분류정보 | <https://www.data.go.kr/data/15065876/fileData.do> |
| K1 (분류체계 확인용) | KISTEP_과학기술표준분류 | <https://www.data.go.kr/data/15065871/fileData.do> |

### 3.4 정제·인덱스 만들기

```powershell
python -m research_compass.cli doctor --quick
python -m research_compass.cli prepare            # 정제 → data/processed/
python -m research_compass.cli build-index        # 모델 약 2.3GB 다운로드 + 임베딩
python -m research_compass.cli prepare-reranker   # 재정렬기 가중치 (필수)
```

Windows 라면 `run_build.bat` 을 더블클릭해도 된다(`prepare-reranker` 는 따로 돌려야 한다).

개발 노트북 CPU 실측 **약 18분**(모델을 이미 받아 둔 상태 기준, `reports/build_index.log`).
처음이면 다운로드 시간이 더 붙는다. **미리 해 둔다.**

끝나면 `artifacts/index_manifest.json` 의 `run_mode` 가 `local_live` 인지 본다.
`test_fixture` 면 합성 임베더로 만든 것이라 검색 품질이 나오지 않는다.

### 3.5 띄우기

```powershell
.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8765
```

브라우저에서 <http://127.0.0.1:8765> — 자동으로 열리지 않는다.

중지는 `Ctrl+C`, 백그라운드로 띄웠다면 포트로 찾아 끈다.

```powershell
Get-NetTCPConnection -LocalPort 8765 -State Listen |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

### 3.6 미리 알아둘 것

- **첫 접속이 23초 걸린다.** 모델과 인덱스를 그때 올린다. 이후 검색은 4~5초.
  누구한테 보여 주기 전에 **접속 1회 + 검색 1회**로 예열해 둔다.
- **Git Bash 로 띄우지 마라.** 출력 인코딩 때문에 모델 적재가 실패하고 화면이 "준비 안 됨"으로 뜬다.
  꼭 써야 하면 앞에 `PYTHONUTF8=1` 을 붙인다.
- 데이터나 인덱스가 없으면 화면이 검색을 막고 복구 명령을 보여 준다. 가짜 결과를 만들지 않는다.
- 목록만 있는 비교 조건(UX-L)도 있다: `... run app.py --server.port 8781 -- --ux l`
- 더 자세한 실행·중지·로그 읽는 법은 `docs/run_server.md`.

---

## 4. 더 볼 문서

| 문서 | 내용 |
|---|---|
| `docs/user_guide.md` | 화면을 순서대로 따라 하는 사용법 |
| `reports/feature_specification.md` | 기능 명세 — 기능별 범위·제한·상태표 |
| `reports/handoff.md` | 실측값(응답시간·검색 품질)과 측정 조건 |
| `docs/decisions.md` | "왜 그렇게 만들었나" — 판단 근거 D-001~D-038 |
| `CLAUDE.md` | 코드를 고칠 사람용 작업 맥락. **절대 규칙**과 맨 아래 **함정** 목록 |

코드·문서 라이선스는 MIT(`LICENSE`). 데이터·글꼴·모델은 각자 출처를 따른다 — `README.md` "라이선스와 출처".
