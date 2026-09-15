# Research Compass — 라벨링 시트 생성 (dev 5개 + test 10개 질의)
$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "C:\venvs\research-compass\Scripts\python.exe" }
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"
$env:HF_HUB_OFFLINE = "1"; $env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
$log = Join-Path $PSScriptRoot "reports\eval_pool.log"
if (Test-Path $log) { Remove-Item $log -Force }
foreach ($split in @("dev", "test")) {
    Write-Host "===== make-eval-pool --split $split ====="
    & cmd /c "`"$py`" -m research_compass.cli make-eval-pool --split $split 2>&1" |
        ForEach-Object { Write-Host $_; Add-Content -Path $log -Value $_ -Encoding UTF8 }
}
Write-Host ""
Write-Host "라벨링 파일:  evaluation\label_sheet_dev.csv,  evaluation\label_sheet_test.csv"
Write-Host "엑셀로 열어 label 열에 2 / 1 / 0 / U 를 입력하고 CSV 그대로 저장하세요."
Write-Host "pool_key_*.csv 는 채점용이니 라벨링 중에는 열지 마세요."
Read-Host "Enter 를 누르면 창이 닫힙니다"
