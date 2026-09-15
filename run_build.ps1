# Research Compass — 인덱스 빌드 원클릭 스크립트
# 하는 일: 미완료 다운로드 정리 -> doctor -> prepare -> build-index -> 검색 확인 -> 로그 저장
# 로그: reports\build_index.log  (Claude 가 읽을 수 있음)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot

$log = Join-Path $PSScriptRoot "reports\build_index.log"
New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot "reports") | Out-Null
if (Test-Path $log) { Remove-Item $log -Force }

function Log([string]$s) {
    Write-Host $s
    Add-Content -Path $log -Value $s -Encoding UTF8
}
function Run([string]$title, [string]$cmd) {
    Log ""
    Log "===== $title  ($(Get-Date -Format 'HH:mm:ss')) ====="
    Log "> $cmd"
    # cmd 를 거쳐 stderr 를 stdout 으로 합친다 (PowerShell 5.1 의 NativeCommandError 잡음 방지)
    & cmd /c "$cmd 2>&1" | ForEach-Object { Write-Host $_; Add-Content -Path $log -Value $_ -Encoding UTF8 }
    Log "(종료 코드 $LASTEXITCODE)"
    return $LASTEXITCODE
}

Log "===== run_build 시작 $(Get-Date -Format s) ====="
Log "폴더: $PSScriptRoot"

# --- 0. 가상환경 확인 -------------------------------------------------------
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "C:\venvs\research-compass\Scripts\python.exe" }
if (-not (Test-Path $py)) {
    Log "[중단] 가상환경이 없습니다: $py"
    Log "        python -m venv .venv  후  .venv\Scripts\pip install -e "".[search,dev]"""
    Read-Host "Enter 를 누르면 창이 닫힙니다"; exit 1
}
Log "python: $py"

# --- 환경변수: 한글 출력, 진행바 10초 간격, xet 청크캐시 비활성 -------------
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:TQDM_MININTERVAL = "2"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
$env:HF_HUB_DISABLE_XET = "1"
$env:HF_HUB_DISABLE_TELEMETRY = "1"

# --- 1. HF 캐시 정리: 끊긴 다운로드 조각과 xet 임시 청크만 삭제 --------------
$hfhome = if ($env:HF_HOME) { $env:HF_HOME } else { Join-Path $env:USERPROFILE ".cache\huggingface" }
$blobs  = Join-Path $hfhome "hub\models--BAAI--bge-m3\blobs"
Log ""
Log "===== 1. 캐시 정리 ====="
Log "HF 캐시: $hfhome"
if (Test-Path $blobs) {
    $partials = Get-ChildItem $blobs -Filter "*.incomplete" -ErrorAction SilentlyContinue
    foreach ($f in $partials) {
        Log ("삭제(미완료 다운로드): {0}  {1} MB" -f $f.Name, [math]::Round($f.Length / 1MB))
        Remove-Item $f.FullName -Force
    }
    if (-not $partials) { Log "미완료 다운로드 없음" }
    $bin = Get-ChildItem $blobs -File | Where-Object { $_.Length -gt 1GB }
    foreach ($f in $bin) { Log ("가중치 파일 유지: {0} MB" -f [math]::Round($f.Length / 1MB)) }
} else {
    Log "bge-m3 캐시 폴더 없음 (첫 실행이면 정상)"
}
$xet = Join-Path $hfhome "xet"
if (Test-Path $xet) {
    $sz = (Get-ChildItem $xet -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
    Log ("삭제(xet 임시 청크 캐시): {0} MB" -f [math]::Round(($sz | ForEach-Object { $_ }) / 1MB))
    Remove-Item $xet -Recurse -Force -ErrorAction SilentlyContinue
}

# --- 2~5. 파이프라인 ---------------------------------------------------------
Run "2. doctor"      "`"$py`" -m research_compass.cli doctor --quick" | Out-Null
$rc = Run "3. prepare" "`"$py`" -m research_compass.cli prepare"
if ($rc -ne 0) { Log "[중단] prepare 실패"; Read-Host "Enter 를 누르면 창이 닫힙니다"; exit $rc }

Log ""
Log "build-index 는 CPU 에서 10~30분 걸릴 수 있습니다. 256건마다 진행 줄이 찍힙니다."
$rc = Run "4. build-index" "`"$py`" -m research_compass.cli build-index"
if ($rc -ne 0) { Log "[중단] build-index 실패 — 위 로그를 Claude 에게 보여주세요"; Read-Host "Enter 를 누르면 창이 닫힙니다"; exit $rc }

Run "5. 검색 확인" "`"$py`" -m research_compass.cli search --query `"산업 전력 데이터 이상탐지`" --top-k 5" | Out-Null

Log ""
Log "===== 완료 $(Get-Date -Format s) ====="
Log "로그: $log"
Log "산출물: artifacts\index_manifest.json, artifacts\project_embeddings.npy"
Read-Host "Enter 를 누르면 창이 닫힙니다"
