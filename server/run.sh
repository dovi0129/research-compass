#!/usr/bin/env bash
# 서버 작업 실행기. 사용: bash server/run.sh <build|tau-probe|eval-pool|search "질의"|test|cmd "임의 명령">
# 모든 출력은 reports/server_<작업>.log 에도 저장된다.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source .venv-server/bin/activate
export PYTHONUTF8=1 HF_HUB_OFFLINE=1 HF_HUB_DISABLE_SYMLINKS_WARNING=1 TQDM_MININTERVAL=5
CFG="--config config/server.yaml"
task="${1:-}"; shift || true
mkdir -p reports
log="reports/server_${task//[^a-zA-Z0-9_-]/_}.log"
run() { echo "> $*" | tee -a "$log"; "$@" 2>&1 | tee -a "$log"; }
echo "===== $(date -Is) server/run.sh $task =====" | tee "$log"
case "$task" in
  build)      run python -m research_compass.cli $CFG prepare
              run python -m research_compass.cli $CFG build-index ;;
  tau-probe)  run python -m research_compass.cli $CFG make-tau-probe --split dev ;;
  eval-pool)  run python -m research_compass.cli $CFG make-eval-pool --split dev
              run python -m research_compass.cli $CFG make-eval-pool --split test ;;
  search)     run python -m research_compass.cli $CFG search --query "$1" --top-k "${2:-10}" --stats ;;
  test)       run python -m pytest -q ;;
  cmd)        run bash -lc "$*" ;;
  *) echo "사용법: bash server/run.sh <build|tau-probe|eval-pool|search \"질의\"|test|cmd \"명령\">"; exit 2 ;;
esac
echo "===== 완료 $(date -Is) =====" | tee -a "$log"
