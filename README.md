# Research Compass

연구주제를 한 문장으로 입력하면 한국연구재단 공공데이터(과제정보)에서 **제목 의미가 가까운 지원과제**를 찾아
보여 주고, 그중 몇 건을 골라 나란히 비교하고, 탐색 과정을 메모로 내보내는 **로컬 웹 도구**.

공공데이터 활용 공모전(대전) 출품작. 노트북 단독·오프라인으로 돌아가며 검색 경로에 생성형 LLM 을 쓰지 않는다.

| | |
|---|---|
| 입력 | 연구주제 한 문장 (+ 선택: 대상·방법·목표 낱말, 선정년도·사업 범위) |
| 출력 | 제목이 유사한 과제 목록(기본 5, 최대 10), 선택 과제 비교표, 탐색 메모(Markdown·JSON) |
| 데이터 | D1 과제정보 11,788행 → 정제 **11,783건**(2023~2025년 수록) · D2 선정과제 연구분야 851행 |
| 기술 | Python 3.12 · Streamlit 1.63 · BGE-M3 임베딩(FAISS flat IP) · bge-reranker-v2-m3 재정렬 · pandas · Altair |
| 실행 | `127.0.0.1` 바인딩, 검색 중 외부 호출 없음(`HF_HUB_OFFLINE=1`), 텔레메트리 차단 |

### 하지 않는 것

- 원본에 없는 텍스트(초록 등)를 생성해 보충하지 않는다. 검색·순위·문장 생성에 생성형 LLM 을 쓰지 않는다.
- 유사도를 정확도·확률·관련성 판정으로 표기하지 않는다. **"가까운 검색 결과"** 라고만 말한다.
- 결측을 0 으로 바꾸지 않고, 제목만 같은 행을 병합하지 않으며, "과제 수" 대신 **"수록 레코드 수"** 를 쓴다.
- 근거가 없는 기능은 켜지 않는다. `capabilities.json` 의 `unavailable` 은 **버그가 아니라 정상적인 기능 제한**이다.

## 현재 상태 (2026-09-14)

| 단계 | 상태 |
|---|---|
| G0 환경·저장소 · G1 감사·정제 · P1 분류체계 검증 | ✅ 완료 |
| G2 검색 엔진 (실모델 인덱스·재정렬) | ✅ 완료 — 기본 엔진 **E**(의미+재정렬) 채택 (D-023) |
| W1·W2 화면·관점·비교함 · W3 근거·메모 | ✅ 완료 (D-024~D-027) |
| W4 검색 조건 판정 | ✅ 판정 완료 (E 채택) |
| W5 사용성 비교(UX-L vs UX-W) | 🔶 조건·양식만 준비 — **사용자 평가 미실시**(참여자 미확보) |
| 화면 재설계 11차 | ✅ 완료 (D-029~D-038) — **한 페이지 골격**(검색 상자 아래에 결과가 붙는다), 검색 방식 4개·검색 전 범위·수치 띠·바닥글, 행정 네이비 팔레트 |
| W6 제한 기능표·재현 문서·최종 인계 | ⬜ 진행 중 |

**남은 일** — ① 검색 품질 사람 스팟체크 30건(발표 전 필수) ② tau 확정 또는 미확정 유지 결정
③ 시연 기기에서 응답시간 재측정 + `showErrorDetails="none"`.

검색 품질 실측(엄격 P@5): dev 0.44→0.56, test 0.40→0.44~0.48. 라벨이 LLM 1차 블라인드 라벨이라
**"검증됨"이 아니다.** 근거는 `reports/retrieval_evaluation.md`.

## 문서

읽는 순서.

| 문서 | 내용 |
|---|---|
| `docs/handover.md` | **인수인계** — 기능 요약과 실행 방법. **처음 받았다면 여기부터** |
| `docs/user_guide.md` | **사용 설명서** — 화면 순서대로 따라 하는 사용법, 시연 대본, 발표에서 쓸 표현 |
| `reports/feature_specification.md` | **현재 구현된 기능 명세** — 화면·엔진·제한의 기준 |
| `reports/handoff.md` | 현재 상태·실제 실행 경로·실측값 |
| `research_compass_workspace_spec_v2.md` | 최상위 명세(탐색 작업공간). 제품 범위를 정한다 |
| `docs/plan.md` · `docs/decisions.md` | 계획(W0~W6) · 판단 근거 D-001~D-038 |
| `docs/implementation_spec.md` · `docs/spec_amendment_01_retrieval_v2.md` | 원본 명세 v1.0 · 검색 v2 개정안 |
| `docs/run_server.md` | **화면 실행·중지 상세** |
| `reports/data_audit.md` · `reports/retrieval_evaluation.md` | 데이터 감사 · 검색 평가 실측 |

명세 우선순위: **작업공간 v2 > 검색 개정안 01 > 원본 v1.0.**

---

## 빠른 시작

이미 이 폴더에서 `data/processed/` 와 `artifacts/` 가 만들어져 있다면 **4번만** 하면 된다.

> **저장소를 막 클론했다면 둘 다 없다.** 원본 데이터·임베딩·모델 가중치는 저장소에 넣지 않는다(이유는 [개인정보·보안](#개인정보보안)). 1 → 2 → 3 → 4 를 차례로 하면 된다. 같은 내용을 짧게 정리한 것이 **`docs/handover.md` §3**.

### 1. 설치

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[search,ui,dev]"
```

- Python 3.10 이상(이 프로젝트는 3.12 로 돌린다).
- `C:\학교` 는 Google Drive 동기화 폴더다. Drive 가 켜져 있으면 새 파일에 하드링크가 걸려 원격 세션이 못 읽는다.
  **`.venv` 는 Drive 밖(`C:\venvs\research-compass`)에 두는 편이 낫다.**
- 감사(G1)만 할 거면 extra 없이 `pip install -e ".[dev]"` 로 충분하다.

### 2. 원본 데이터

공공데이터포털에서 **로그인 후 직접 내려받는다.** URL 을 CSV 주소로 쓰지 않는다.

D1·D2 는 필수다. K18·K1 은 분류체계 확인(`verify-scheme`·`crosswalk`)에만 쓴다.

| 키 | 데이터셋 | ID | 페이지 |
|---|---|---|---|
| D1 | 한국연구재단_이알앤디_과제정보 | 3049029 | <https://www.data.go.kr/data/3049029/fileData.do> |
| D2 | 한국연구재단_선정과제 연구분야 | 15120687 | <https://www.data.go.kr/data/15120687/fileData.do> |
| K18 | 한국과학기술기획평가원(KISTEP)_과학기술표준분류정보 | 15065876 | <https://www.data.go.kr/data/15065876/fileData.do> |
| K1 | 한국과학기술기획평가원(KISTEP)_과학기술표준분류 | 15065871 | <https://www.data.go.kr/data/15065871/fileData.do> |

내려받은 CSV 를 `data/raw/` 에 그대로 넣는다. 파일명은 바꾸지 않아도 된다
(고정하려면 `config/default.yaml` 의 `sources[].file`).

### 3. 정제·인덱스 빌드

**원클릭(Windows)** — `run_build.bat` 을 더블클릭하면 캐시 정리 → `doctor --quick` → `prepare` →
`build-index` → 검색 확인이 차례로 돌고 전체 출력이 `reports\build_index.log` 에 남는다.

**직접 실행**

```powershell
python -m research_compass.cli doctor --quick
python -m research_compass.cli prepare            # 정제 → data/processed/*.csv
python -m research_compass.cli build-index        # BGE-M3 임베딩 + FAISS (최초 1회 모델 약 2.3GB 다운로드)
python -m research_compass.cli prepare-reranker   # 재정렬기 가중치 — 기본 엔진 E 에 필요. run_build.bat 에는 없다
```

`artifacts/*.npy` 는 Git 제외 대상이라 **새 환경에서는 반드시 빌드해야 한다.**
현재 이 폴더의 인덱스는 실모델로 만든 것이다(`index_manifest.json` 의 `run_mode: local_live`,
BGE-M3 `5617a9f6…`, 재정렬기 `953dc6f6…`). `run_mode: test_fixture` 로 보이면 오프라인 해시 임베더로
만든 것이라 **검색 품질을 나타내지 않는다.**

### 4. 화면 실행

```powershell
.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8765
```

접속 <http://127.0.0.1:8765> — 브라우저는 자동으로 열리지 않는다.
화면은 한 페이지다 — 검색 방식 4개(연구주제 한 문장 · 요소별 탐색 · 연구 요약 붙여넣기 · 연구분야로 찾기)와 검색 범위가 든 검색 상자 아래에 결과가 붙고,
수록 데이터 수치 띠·출처 바닥글이 맨 아래에 있다(`docs/user_guide.md` §1).

- **Git Bash 로 띄우지 말 것.** stdout 이 cp949 라 모델 적재 로그에서 `UnicodeEncodeError` 가 나고
  화면이 '준비 안 됨' 으로 뜬다. Bash 를 써야 하면 `PYTHONUTF8=1` 을 붙인다.
- **예열이 필요하다**(이 노트북 실측): 첫 접속 → 검색칸 22.9초(모델·인덱스 적재), 첫 검색 3.9초,
  이후 4~5초. 시연 전 **접속 1회 + 검색 1회**로 예열해 둔다.
- 중지: 포그라운드면 `Ctrl+C`, 백그라운드면 포트로 찾아 종료한다.
  ```powershell
  Get-NetTCPConnection -LocalPort 8765 -State Listen |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
  ```
- 사용성 비교 조건(목록 전용 UX-L): `... run app.py --server.port 8781 -- --ux l`
- 데이터·인덱스가 없으면 화면이 검색을 막고 복구 명령을 보여 준다. **가짜 결과를 만들지 않는다.**

자세한 내용(포트 변경 시 `allowedOrigins`, 다른 설정 파일, 시연 전 점검)은 **`docs/run_server.md`**.

---

## 명령

```bash
# 점검·감사
python -m research_compass.cli doctor [--quick]      # 환경·원본·모델 캐시 확인
python -m research_compass.cli audit                 # 전수 감사 → reports/data_audit.md, artifacts/capabilities.json
python -m research_compass.cli verify-scheme         # D2 기준 분류체계(2018판) 확인
python -m research_compass.cli crosswalk             # 2018 ↔ 2023 신구 코드 대조 (모집단 산정용 아님)

# 정제·인덱스·검색
python -m research_compass.cli prepare
python -m research_compass.cli build-index [--no-download]
python -m research_compass.cli prepare-reranker [--no-download]
python -m research_compass.cli search --query "산업 전력 이상탐지" --top-k 5 [--stats] [--exclude-short]

# 평가 (라벨 시트는 라벨러에게 블라인드로 준다 — pool_key_*.csv 를 절대 같이 주지 않는다)
python -m research_compass.cli make-eval-pool --split dev|test
python -m research_compass.cli evaluate --split dev
python -m research_compass.cli evaluate-conditions --split dev --conditions "A,B,C,D,E"
python -m research_compass.cli rescore-pool --split dev [--with-rerank]
python -m research_compass.cli make-tau-probe
python -m research_compass.cli analyze-tau [--spaces s_sem,margin,rank,s_rr]

# 시험
python -m pytest            # 256개 (test_app.py 는 streamlit 미설치 시 skip)
```

원클릭 배치: `run_build.bat`(빌드) · `run_eval_pool.bat`(라벨 시트) · `run_tau_probe.bat`(tau 표본).

## 연구실 서버 (선택 · 배치 전용)

RTX 5090 서버(Lab33)는 인덱스 생성·평가 같은 **배치 작업만** 돌린다. 시연은 노트북 단독으로 한다(D-018).
`~/.ssh/config` 에 `Host Lab33-minu` 가 있으면 노트북에서 한 줄로 실행한다.

```powershell
.\run_server.ps1 push        # 저장소 동기화 (venv·모델·reports 제외)
.\run_server.ps1 bootstrap   # 최초 1회: venv, torch(cu128), 모델 캐시, config/server.yaml 생성
.\run_server.ps1 build       # prepare + build-index
.\run_server.ps1 tau-probe   # tau 심층 표본
.\run_server.ps1 test        # 서버에서 pytest
.\run_server.ps1 fetch       # artifacts/ evaluation/ reports/ 가져오기
```

서버에서 직접 돌릴 때는 `bash server/run.sh <build|tau-probe|eval-pool|search "질의"|test|cmd "...">`.
RTX 5090 은 torch **cu128 이상**이 필요하다(cu124 는 커널이 없다).

## 산출물

| 경로 | 내용 |
|---|---|
| `data/processed/projects.csv` · `fields.csv` | 정제 데이터 (CSV — parquet 은 쓰지 않는다) |
| `artifacts/index_manifest.json` · `rerank_manifest.json` | 모델 ID·revision 고정, 스냅샷·행수 |
| `artifacts/capabilities.json` | 기능별 가용성 판정과 근거 (자료 지원·구현 분리) |
| `artifacts/data_manifest.json` | 원본 스냅샷 해시·인코딩·행수 |
| `reports/data_audit.md` · `retrieval_evaluation.md` · `feature_specification.md` | 감사 · 평가 · 기능 명세 |
| 화면 내보내기 | `research_compass_memo.md`(압축 메모) · `research_compass_workspace.json`(전체 기록) — 사용자 컴퓨터로만 |

## 트러블슈팅

**`doctor` 가 `yaml` 다음에서 멈춘 것처럼 보일 때** — 멈춘 게 아니라 `sentence_transformers` 가 PyTorch 를
로딩하는 중입니다. 첫 실행은 30초~2분 걸립니다. 빠르게 확인만 하려면 `doctor --quick`.

**`sentence_transformers — 미설치`** — torch 의존성 때문에 이것만 실패하는 경우가 있습니다.

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install sentence-transformers
```

**`Unable to find a usable engine ... pyarrow` / `애플리케이션 제어 정책에서 이 파일을 차단했습니다`**
— 이 프로젝트는 parquet 을 쓰지 않습니다(Windows 스마트 앱 제어가 pyarrow 의 DLL 을 차단한 사례가 있어
CSV 로 고정했습니다, D-015). 이 오류가 보이면 옛 버전 코드입니다.

**`build-index` 가 모델을 내려받는 이유** — BGE-M3 가중치(약 2.3GB)를 최초 1회만 받아
`~/.cache/huggingface/hub` 에 캐시합니다. 가중치는 **한 포맷만** 받습니다(캐시에 `.bin` 이 있으면 그것을 재사용).
`HF_TOKEN` 경고는 무해합니다. 다운로드를 막고 캐시만 쓰려면 `--no-download`.
`search` 는 항상 오프라인으로 동작합니다(`runtime.allow_network_during_search: false`).

**설치가 끝까지 안 될 때** — 임베딩 없이도 어휘 검색 baseline 은 동작합니다.

```bash
pip install -e ".[search-min,dev]"
python -m research_compass.cli search --query "산업 전력 이상탐지" --baseline-only
```

합성 자료로 파이프라인만 확인하려면 `--config config/fixture.yaml audit`.
그 결과 예시는 `reports/_sample_fixture/` 에 있습니다. **실제 공공데이터가 아닙니다.**

## 라이선스와 출처

**코드·문서** — MIT (`LICENSE`). 이 저장소에서 우리가 쓴 것에만 적용된다.

함께 쓰는 것들은 각자의 출처와 조건을 따른다.

| 무엇 | 출처 | 조건 |
|---|---|---|
| D1 한국연구재단_이알앤디_과제정보 (ID 3049029) | 공공데이터포털 | 포털의 이용허락범위를 따른다. **저장소에 포함하지 않는다** |
| D2 한국연구재단_선정과제 연구분야 (ID 15120687) | 공공데이터포털 | 같음 |
| K18·K1 KISTEP 과학기술표준분류 (ID 15065876 · 15065871) | 공공데이터포털 | 같음 |
| Pretendard 글꼴 (`static/fonts/`) | [orioncactus/pretendard](https://github.com/orioncactus/pretendard) | SIL Open Font License 1.1 — 전문은 `static/fonts/LICENSE-Pretendard.txt` |
| BAAI/bge-m3 (임베딩, revision `5617a9f6…`) | Hugging Face | 고정 revision 의 모델 카드에 `license: mit` |
| BAAI/bge-reranker-v2-m3 (재정렬, revision `953dc6f6…`) | Hugging Face | 모델 카드를 따른다 — 로컬 캐시에 카드가 없어 **확인하지 못했다.** 인용·재배포 전에 [모델 카드](https://huggingface.co/BAAI/bge-reranker-v2-m3)를 볼 것 |

모델 가중치는 저장소에 없다. `build-index`·`prepare-reranker` 가 각자의 PC 로 내려받는다.

이 서비스는 **공공데이터 활용 공모전 출품작이며 한국연구재단·KISTEP 의 공식 서비스가 아니다.**

## 개인정보·보안

- `연구책임자명`·`연구자번호` 는 정제 단계에서 제거된다(assert 로 검증). 화면·메모·인덱스 어디에도 없다.
- 접속정보·키·비밀번호는 산출물·저장소에 넣지 않는다. `data/raw/`·`data/processed/`·`config/server.yaml` 은 Git 제외.
- 사용자 질의·메모를 서버에 저장하지 않는다. 내보내기는 사용자가 직접 내려받는 파일뿐이다.
- 참가신청서의 개인정보(학번·전화번호·서명)는 서비스 데이터가 아니며 저장소에 넣지 않는다.
