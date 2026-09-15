# 화면(Streamlit) 실행·중지

노트북 단독·로컬 전용. `127.0.0.1` 만 바인딩하고 검색 중 외부 호출이 없다.
설정은 `.streamlit/config.toml`, 엔진 설정은 `config/default.yaml`.

## 실행

PowerShell 에서 프로젝트 폴더에서:

```powershell
.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8765
```

접속: <http://127.0.0.1:8765>

- **Git Bash 로 띄우지 말 것.** stdout 이 cp949 라 모델 적재 로그의 `—` 에서 `UnicodeEncodeError` 가 나고
  화면이 '준비 안 됨' 으로 뜬다. Bash 를 써야 하면 `PYTHONUTF8=1` 을 붙인다.
- 브라우저는 자동으로 열리지 않는다(`headless = true`).

### 변형

```powershell
# 사용성 비교 조건 UX-L (목록 전용) — 스크립트 인자는 `--` 뒤에만
.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8781 -- --ux l

# 다른 엔진 설정 (예: 서버용 cuda 설정)
.venv\Scripts\python.exe -m streamlit run app.py -- --config config/server.yaml
```

**포트를 바꾸면** `.streamlit/config.toml` 의 `client.allowedOrigins` 에 그 포트가 있어야 화면 모드(라이트/다크)
토글이 동작한다. 현재 등록: `8501 · 8765 · 8781`. (`app.py` 가 실행 중 실제 포트를 덧붙이지만 첫 적재는 config 값을 쓴다.)

## 중지

포그라운드로 띄웠으면 그 창에서 `Ctrl+C`. 백그라운드로 띄웠으면 **포트로 찾아 종료**한다.

```powershell
Get-NetTCPConnection -LocalPort 8765 -State Listen |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

`Win32_Process` 의 `CommandLine` 으로 찾아 죽이는 방식은 쓰지 말 것 — 검색어(`streamlit run app.py`)가
**그 명령을 실행하는 셸 자신의 명령줄에도 들어 있어** 셸까지 함께 죽는다(실제로 겪음).
꼭 그렇게 찾아야 하면 검색어를 쪼갠다: `$pat = 'streamli' + 't run app'`.

## 로그에서 무시해도 되는 것

- `ModuleNotFoundError: No module named 'torchvision'` 트레이스백 — Streamlit 파일 감시기가 transformers 모듈을 훑다 내는 **경고 잡음**. 검색과 무관하고
  재실행도 늦추지 않는다. `config.toml` 의 `[logger] level = "error"` 가 숨긴다(기본값으로 두면 한 실행에 수백 줄).
- `OSError: [WinError 10022]` (`_call_connection_lost`) — 브라우저·health check 접속이 끊길 때 나는 잡음.

## 알아둘 것

- **예열이 필요하다** (이 노트북 실측): 프로세스 실행 → HTTP 응답 1.4초, **첫 접속 → 검색칸 22.9초**(모델·인덱스 적재),
  첫 검색 3.9초(재정렬기 적재), 이후 검색 4~5초. 시연 전 **접속 1회 + 검색 1회**로 예열해 둔다.
- `src/research_compass/` 를 고치면 앱을 다시 띄워야 한다. `app.py` 만 고친 경우는 새로 고침으로 반영된다.
- **시연 직전** `.streamlit/config.toml` 의 `client.showErrorDetails` 를 `"none"` 으로 바꾼다(로컬 경로 노출 방지).
- 데이터·인덱스가 없으면 화면이 검색을 막고 복구 명령을 보여 준다. 그때 실행할 것:
  `cli doctor --quick` → `cli prepare` → `cli build-index` → `cli prepare-reranker`.

## 연구실 서버(Lab33)는 배치 전용

RTX 5090 서버는 인덱스 생성·평가 같은 배치 작업만 돌린다. 화면은 노트북에서 띄운다.

```bash
bash server/bootstrap.sh                 # 최초 1회 (config/server.yaml 생성, device=cuda)
bash server/run.sh <build|tau-probe|eval-pool|search "질의"|test|cmd "...">
```
