# Research Compass — tau 보정용 심층 표본 생성
$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "C:\venvs\research-compass\Scripts\python.exe" }
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"
$env:HF_HUB_OFFLINE = "1"; $env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
$log = Join-Path $PSScriptRoot "reports\tau_probe.log"
if (Test-Path $log) { Remove-Item $log -Force }
Write-Host "===== make-tau-probe --split dev ====="
& cmd /c "`"$py`" -m research_compass.cli make-tau-probe --split dev 2>&1" |
    ForEach-Object { Write-Host $_; Add-Content -Path $log -Value $_ -Encoding UTF8 }
Write-Host ""
Write-Host "생성: evaluation\label_sheet_tau_dev.csv  (Claude 가 이어서 라벨링·분석)"
Read-Host "Enter 를 누르면 창이 닫힙니다"
