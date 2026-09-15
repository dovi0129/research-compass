# 노트북 → 연구실 서버 원커맨드 실행기
#   .\run_server.ps1 push              저장소 동기화 (venv·모델·대용량 제외)
#   .\run_server.ps1 bootstrap         서버 최초 준비 (venv, torch, 모델 캐시)
#   .\run_server.ps1 build             prepare + build-index (서버 GPU/CPU)
#   .\run_server.ps1 tau-probe         tau 심층 표본 생성
#   .\run_server.ps1 eval-pool         라벨링 풀 생성
#   .\run_server.ps1 fetch             artifacts/·evaluation/·reports/ 결과를 노트북으로 가져오기
#   .\run_server.ps1 cmd "명령"        서버에서 임의 명령
# 전제: ~/.ssh/config 에 Host Lab33-minu 정의(공개키 인증). 서버 경로 ~/공공데이터/research-compass
param([Parameter(Mandatory=$true)][string]$Task, [string]$Arg = "")
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot
$HostAlias = "Lab33-minu"
$Remote    = "~/공공데이터/research-compass"

# 원격 명령은 base64 로 감싸 전달한다 — 따옴표·한글·특수문자에 안전
function Remote([string]$cmd) {
  $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($cmd))
  ssh $HostAlias "echo $b64 | base64 -d | bash -l"
}

switch ($Task) {
  "push" {
    # Compress-Archive 는 한글 파일명·경로 구분자를 리눅스가 다르게 읽을 수 있어 Python zipfile 을 쓴다 (UTF-8, '/' 보장)
    $py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $py)) { $py = "C:\venvs\research-compass\Scripts\python.exe" }
    if (-not (Test-Path $py)) { $py = "python" }
    $zip = Join-Path $env:TEMP "rc_push.zip"
    if (Test-Path $zip) { Remove-Item $zip -Force }
    $exclude = @(".venv", ".venv-server", ".git", "__pycache__", "reports", ".pytest_cache")
    $items = Get-ChildItem -Force | Where-Object { $_.Name -notin $exclude } | ForEach-Object { $_.Name }
    & $py -c "import sys,zipfile,os; z=zipfile.ZipFile(sys.argv[1],'w',zipfile.ZIP_DEFLATED); [z.write(os.path.join(r,f), os.path.relpath(os.path.join(r,f)).replace(os.sep,'/')) for it in sys.argv[2:] for r,_,fs in (os.walk(it) if os.path.isdir(it) else [(os.path.dirname(it) or '.',None,[os.path.basename(it)])]) for f in fs if '__pycache__' not in r and not f.endswith('.pyc') and not f.endswith('.npy')]; z.close()" $zip @items
    Write-Host "업로드 $([math]::Round((Get-Item $zip).Length/1MB,1)) MB"
    Remote "mkdir -p $Remote"
    scp -q $zip "${HostAlias}:$Remote/rc_push.zip"
    Remote "cd $Remote && python3 -m zipfile -e rc_push.zip . && rm rc_push.zip && chmod +x server/*.sh && echo '--- data/raw ---' && ls -la data/raw && echo '--- 파일 수' && find . -type f -not -path './.venv-server/*' | wc -l"
  }
  "bootstrap" { Remote "cd $Remote && bash server/bootstrap.sh" }
  "fetch" {
    foreach ($d in @("artifacts", "evaluation", "reports")) {
      New-Item -ItemType Directory -Force -Path $d | Out-Null
      scp -q -r "${HostAlias}:$Remote/$d/*" "$d/"
    }
    Write-Host "가져옴: artifacts/ evaluation/ reports/"
  }
  "cmd"     { Remote ("cd $Remote && bash server/run.sh cmd " + '"' + $Arg + '"') }
  default   { Remote "cd $Remote && bash server/run.sh $Task $Arg" }
}
