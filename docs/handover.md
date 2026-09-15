# 인수인계 — 발표자료 제작 · 시연 담당자용

이 문서 하나로 시작할 수 있게 썼다. 두 가지 역할을 나눠 적었다.

- **발표자료를 만드는 사람** → §1, §2, §6
- **다른 PC에서 시연하는 사람** → §1, §3, §5
- **코드를 이어받는 사람** → §4 부터

## 0. 30초 요약

연구주제를 한 문장 넣으면 한국연구재단 공공데이터에서 **제목 의미가 가까운 지원과제**를 찾아 주고,
몇 건을 골라 나란히 비교하고, 탐색 과정을 메모로 내보내는 **노트북 단독·오프라인 웹 도구**다.

검색 경로에 생성형 LLM 을 쓰지 않는다. 임베딩 모델(BGE-M3)로 제목 의미를 비교하고 재정렬기로 순서를 고칠 뿐,
문장을 지어내지 않는다. **이것이 이 출품작의 핵심 주장이므로 발표에서 반대로 말하면 안 된다.**

---

## 1. 발표에서 틀리면 안 되는 것 (전원 필독)

이 프로젝트는 "데이터가 받쳐 주지 않는 말은 하지 않는다"를 설계 원칙으로 잡았다.
그래서 화면 문구도 전부 이 기준에 맞춰 놨다. **발표에서 이 선을 넘으면 도구와 발표가 어긋난다.**

| 이렇게 말하면 안 된다 | 이렇게 말한다 | 왜 |
|---|---|---|
| "관련 과제를 찾아 준다" | "제목 의미가 **가까운** 검색 결과를 보여 준다" | 관련성 기준값(tau)을 확정하지 못했다 |
| "정확도 56%" | "엄격 기준 P@5 dev 0.56 (LLM 1차 라벨, 검증 아님)" | 사람 라벨이 아니다 |
| "유사도 0.72니까 72% 관련" | "의미 유사도 0.72" | 코사인 유사도는 확률·정확도가 아니다 |
| "과제 수 11,783건" | "**수록 레코드 수** 11,783건" | 제목만 같은 행을 병합하지 않았다 |
| "연도별로 지원이 줄고 있다" | (말하지 않는다) | 수록 연도가 2023~2025뿐이라 추세를 못 읽는다 |
| "AI 가 연구주제를 추천한다" | "가까운 과제를 찾아 **사용자가 판단하도록** 돕는다" | 검색 경로에 LLM 이 없다 |
| "이 분야 선정이 제일 많다" | (분야 간 비교는 하지 않는다) | D2 선정횟수의 기준연도가 확인되지 않았다 |

더 자세한 목록과 대체 표현은 **`docs/user_guide.md` §8** 에 있다. 슬라이드 문구를 쓰기 전에 한 번 읽어 두면 좋다.

---

## 2. 발표자료 만들기

### 2.1 읽는 순서 (총 40분이면 충분하다)

| 순서 | 문서 | 여기서 가져갈 것 |
|---|---|---|
| 1 | `README.md` | 한 문단 소개, 데이터·기술 스택 표, 현재 상태 |
| 2 | `docs/user_guide.md` | 화면 순서대로 된 사용법, **§8 금지 표현**, **§9 3분 시연 대본**, §9 예상 질문 |
| 3 | `reports/feature_specification.md` | 기능 명세 — 화면 각 영역이 무엇을 하는지, §6 기능 상태표, §7 하지 않는 것 |
| 4 | `reports/handoff.md` | 실측값(응답시간·검색 품질)과 그 측정 조건 |
| 5 | `docs/decisions.md` | "왜 그렇게 만들었나" 질문이 나올 때. D-023(엔진 선택)·D-020(하이브리드 기각)·D-036(화면) |

### 2.2 슬라이드에 넣을 수치와 출처

**출처 없는 숫자를 만들지 않는다.** 아래 표에 있는 것만 쓰고, 표에 없으면 만들지 말고 물어본다.

| 수치 | 값 | 출처 파일 |
|---|---|---|
| 원본 D1 과제정보 | 11,788행 | `reports/data_audit.md` |
| 정제 후 수록 레코드 수 | **11,783건** (2023~2025년 수록) | `artifacts/data_manifest.json` |
| D2 선정과제 연구분야 | 851행 | 같음 |
| 임베딩 차원 | 1,024 | `artifacts/index_manifest.json` |
| 검색 품질 (엄격 P@5) | dev 0.44→**0.56**, test 0.40→0.44~0.48 | `reports/retrieval_evaluation.md` |
| 첫 접속(모델·인덱스 적재) | 22.9초 | `docs/decisions.md` D-034 |
| 첫 검색 / 이후 검색 | 3.9초 / 4~5초 | 같음 |
| 자동 시험 | 256개 통과 | `pytest` 실행 결과 |

품질 수치를 말할 때는 **"LLM 1차 블라인드 라벨 기준이고 사람 검증 전"** 을 반드시 붙인다.
사람 스팟체크 30건은 아직 안 했다(§6).

### 2.3 화면 캡처

`reports/screenshots/` 에 82장이 있지만 **가장 새 것(`ui6_*`)도 현재 화면과 다르다.**
그 뒤에 화면 구조를 한 페이지로 바꿨다(D-038). 자세한 세대 표는 `reports/screenshots/README.md`.

→ **슬라이드용 캡처는 직접 띄워서 찍는다.** 띄우는 방법은 §3.

찍을 때:

- 브라우저 확대 100%, 창 너비 1,320px 이상(그보다 좁으면 두 단이 한 단으로 접힌다).
- 프로젝터를 쓸 거면 **라이트 모드**로 찍는다(화면 맨 아래 `화면 모드`에서 고른다).
- 검색 결과가 나온 상태, 비교함에 2건 담은 상태, `검색 근거 보기`를 연 상태 — 이 세 장이면 기능이 다 보인다.

**`reports/ux_study/rc_*_shots.py` 는 실행하지 마라.** 헤드리스 브라우저를 띄우는 스크립트인데
자식 프로세스가 남아 컴퓨터가 멈춘 적이 있다. 기록으로만 남겨 둔 파일이다.

---

## 3. 다른 PC에서 시연하기

### 3.1 저장소만 받아서는 안 된다

GitHub 에 올린 것은 **소스코드와 문서뿐**이다. 아래 셋은 저장소에 없다.

| 없는 것 | 크기 | 왜 없나 |
|---|---|---|
| 원본 데이터 `data/raw/` | 약 3.4 MB | D1 원본에 개인식별 컬럼(연구책임자명·연구자번호)이 있어 절대 커밋하지 않는다 |
| 임베딩 인덱스 `artifacts/*.npy` | 49 MB | 용량. 재생성 가능 |
| 모델 가중치 | 4.3 GB | 허깅페이스에서 받는 것이라 저장소에 넣지 않는다 |

### 3.2 방법 A — 준비된 PC에서 통째로 복사 (빠름, 권장)

이미 돌아가는 PC(현재 개발 노트북)에서 아래 세 폴더를 USB·외장디스크로 옮긴다.

```powershell
# 내보내기 (E:\rc_bundle 는 USB 경로 예시)
robocopy "data\raw"  "E:\rc_bundle\data\raw"  /E
robocopy "artifacts" "E:\rc_bundle\artifacts" /E
robocopy "$env:USERPROFILE\.cache\huggingface" "E:\rc_bundle\hf_cache" /E
```

받는 PC에서 — 저장소를 클론한 폴더 기준:

```powershell
robocopy "E:\rc_bundle\data\raw"  "data\raw"  /E
robocopy "E:\rc_bundle\artifacts" "artifacts" /E
robocopy "E:\rc_bundle\hf_cache"  "$env:USERPROFILE\.cache\huggingface" /E
```

그다음 §3.4 설치 → §3.5 실행. 인덱스를 다시 만들 필요가 없다.

### 3.3 방법 B — 처음부터 다시 만들기 (인터넷 필요, 1~2시간)

1. 공공데이터포털에서 원본 CSV 를 **로그인 후 직접** 내려받아 `data/raw/` 에 넣는다.

   | 키 | 데이터셋 | 페이지 |
   |---|---|---|
   | D1 (필수) | 한국연구재단_이알앤디_과제정보 | <https://www.data.go.kr/data/3049029/fileData.do> |
   | D2 (필수) | 한국연구재단_선정과제 연구분야 | <https://www.data.go.kr/data/15120687/fileData.do> |
   | K18 (분류체계 검증용) | KISTEP_과학기술표준분류정보 | <https://www.data.go.kr/data/15065876/fileData.do> |
   | K1 (분류체계 검증용) | KISTEP_과학기술표준분류 | <https://www.data.go.kr/data/15065871/fileData.do> |

2. §3.4 설치를 먼저 끝낸 뒤:

```powershell
python -m research_compass.cli doctor --quick
python -m research_compass.cli prepare            # 정제 → data/processed/
python -m research_compass.cli build-index        # 모델 약 2.3GB 다운로드 + 임베딩
python -m research_compass.cli prepare-reranker   # 재정렬기 가중치 (필수)
```

`build-index` 는 노트북 CPU 에서 오래 걸린다 — 개발 노트북 실측 **약 18분**(모델을 이미 받아 둔 상태에서 `doctor`+`prepare`+`build-index`+검색 확인 전체, `reports/build_index.log`). 모델을 처음 받는다면 2.3GB 다운로드 시간이 더 붙는다. **시연 전날에 해 둔다.**
끝나면 `artifacts/index_manifest.json` 의 `run_mode` 가 `local_live` 인지 확인한다.
`test_fixture` 로 보이면 합성 임베더로 만든 것이라 **검색 품질이 나오지 않는다.**

### 3.4 설치

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[search,ui,dev]"
```

- Python 3.10 이상(개발은 3.12).
- **가상환경을 Google Drive·OneDrive 동기화 폴더 안에 두지 마라.** 동기화가 파일을 잠가 설치가 깨진다.
- 설치 확인: `python -m pytest` → 256개 통과해야 한다(streamlit 이 없으면 화면 시험은 skip 된다).

### 3.5 실행

```powershell
.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8765
```

브라우저에서 <http://127.0.0.1:8765> — 자동으로 열리지 않는다.

- **Git Bash 로 띄우지 마라.** 출력 인코딩 때문에 모델 적재가 실패하고 화면이 "준비 안 됨"으로 뜬다.
  꼭 써야 하면 앞에 `PYTHONUTF8=1` 을 붙인다.
- 중지: 포그라운드면 `Ctrl+C`. 백그라운드면 포트로 찾아 끈다.

  ```powershell
  Get-NetTCPConnection -LocalPort 8765 -State Listen |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
  ```
- 자세한 내용은 `docs/run_server.md`.

### 3.6 시연 직전 점검표

- [ ] **예열** — 접속 1회 + 검색 1회를 미리 돌려 둔다. 안 하면 첫 화면에서 23초를 기다리게 된다.
- [ ] `.streamlit/config.toml` 의 `client.showErrorDetails` 를 `"none"` 으로 바꾼다(아직 안 되어 있다).
- [ ] 화면 모드를 **라이트**로 고정(페이지 맨 아래).
- [ ] 브라우저 확대 100%, 창 최대화.
- [ ] 인터넷을 끊은 채 검색이 되는지 확인한다. 검색 중 외부 접속은 없어야 정상이다.
- [ ] 시연 주제 2개를 미리 정해 둔다 — `docs/user_guide.md` §9 에 검증된 주제와 3분 대본이 있다.
- [ ] 노트북 절전·화면보호기를 끈다. 모델이 메모리에서 내려가면 다시 23초가 걸린다.

---

## 4. 코드를 이어받는다면

### 4.1 구조

```
app.py                     화면 전체 (Streamlit 단일 파일)
src/research_compass/      엔진 — 정제·임베딩·검색·재정렬·비교·메모·통계
  cli.py                   모든 배치 명령의 입구
tests/unit/                자동 시험 256개 (화면은 Streamlit AppTest)
config/default.yaml        데이터 출처·엔진 설정
artifacts/                 매니페스트(모델 revision·스냅샷 해시·기능 가용성)
docs/ · reports/           명세·판단 근거·실측 보고
```

`app.py` 만 고치면 화면이 자동으로 다시 그려진다. **`src/` 를 고치면 앱을 다시 띄워야 반영된다.**

### 4.2 먼저 읽을 것

`CLAUDE.md` — 작업 맥락 전체가 여기 있다. 특히 **"절대 규칙"** 과 맨 아래 **"함정"** 목록.
겪어서 알아낸 것들이라 같은 곳에서 두 번 막히지 않게 해 준다.

그다음 `research_compass_workspace_spec_v2.md`(최상위 명세) → `docs/decisions.md`(D-001~D-038).

### 4.3 시험

```powershell
python -m pytest              # 전체 256개
python -m pytest tests/unit/test_app.py   # 화면만
```

화면을 바꿨으면 **반드시 `test_app.py` 를 돌린다.** 브라우저 자동화 대신 이 시험으로 검증한다.

---

## 5. 하면 안 되는 것

- **`data/raw/`·`data/processed/` 를 커밋하지 마라.** D1 원본에 개인식별 컬럼이 있다. `.gitignore` 로 막아 뒀으니 `git add -f` 로 억지로 넣지 않는다.
- **`reports/ux_study/rc_*_shots.py`·`rc_*_probe.py` 를 실행하지 마라.** 헤드리스 브라우저 자식 프로세스가 남아 PC 가 멈춘다.
- **없는 수치를 만들지 마라.** §2.2 표에 없는 숫자는 쓰지 않는다.
- **라벨 시트를 줄 때 `evaluation/pool_key_*.csv` 를 같이 주지 마라.** 정답 키라 라벨이 오염된다(저장소에는 기록용으로 함께 있다).
- 화면 문구에 명세 절 번호·`D-0xx`·모듈명 같은 내부 코드명을 쓰지 않는다(개발자용 펼침 안에만).

---

## 6. 아직 안 된 것 (발표에서 물어보면 이렇게 답한다)

정직하게 "아직"이라고 말하는 편이 낫다. 이 프로젝트는 검증 안 된 것을 된 것처럼 말하지 않는 것이 원칙이다.

| 항목 | 상태 | 답변 |
|---|---|---|
| 검색 품질 사람 검증 | 미실시 | "LLM 1차 라벨로 잡은 수치이고, 사람 스팟체크 30건은 발표 전 과제입니다" |
| 관련성 기준값(tau) | 미확정 | "표본에서 두 기준이 같은 분할을 만들어 구분이 안 됐습니다. 그래서 '관련' 판정을 아예 하지 않고 '가까운 결과'로만 보여 줍니다" |
| 사용성 평가(UX-L 비교) | 미실시(참여자 미확보) | "비교 조건과 대본은 준비했지만 아직 안 돌렸습니다. 효용은 미확정입니다" |
| D2 분야 간 비교 | 잠금 | "선정횟수의 기준연도가 원본에서 확인되지 않아 분야끼리 비교하지 않습니다" |
| 시연 기기 응답시간 | 개발 노트북 값만 있음 | 시연 PC 에서 다시 재 본다 |

자세한 내용은 `reports/feature_specification.md` §10, `reports/handoff.md` §7.

---

## 7. 저장소·연락

- 코드·문서 라이선스: MIT (`LICENSE`). 데이터·글꼴·모델은 각자 출처를 따른다 — `README.md` "라이선스와 출처".
- 원 저장소 소유: 팀 백성 (공공데이터 활용 공모전, 대전).
- 이 문서에서 못 찾은 것은 `README.md` → `docs/user_guide.md` → `reports/feature_specification.md` 순서로 찾으면 대개 나온다.
