#!/usr/bin/env bash
# 연구실 서버 최초 준비: venv, 패키지(GPU 자동 감지), 모델 캐시(BGE-M3 + 재정렬기)
# 실행: bash server/bootstrap.sh     (저장소 루트에서)
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
echo "[bootstrap] 저장소: $ROOT"

PY=${PYTHON:-python3}
$PY --version
if [ ! -d .venv-server ]; then
  $PY -m venv .venv-server
fi
# shellcheck disable=SC1091
source .venv-server/bin/activate
pip install -q --upgrade pip

# 순서 주의: 패키지 extras 를 **먼저** 설치한다. torch>=2.2 를 PyPI 기본 휠(cu124)로 끌어오기 때문에,
# 장치에 맞는 휠은 그 뒤에 덮어써야 한다. 순서를 바꾸면 cu128 이 cu124 로 되돌아간다.
pip install -q -e ".[search,dev]"

if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  echo "[bootstrap] GPU 감지:"; nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
  # RTX 50 시리즈(Blackwell, sm_120)는 CUDA 12.8 이상 빌드가 필요하다. cu128 은 구형 GPU 도 지원한다.
  pip install -q --upgrade --force-reinstall torch --index-url https://download.pytorch.org/whl/cu128
  DEVICE=cuda
  python - <<'PY2'
import torch
assert torch.cuda.is_available(), "torch 가 CUDA 를 보지 못함"
name = torch.cuda.get_device_name(0); cap = torch.cuda.get_device_capability(0)
sm, archs = f"sm_{cap[0]}{cap[1]}", torch.cuda.get_arch_list()
# cuda.is_available() 만으로는 부족하다. 커널이 없는 조합(cu124 + sm_120)도 True 를 반환한다.
assert sm in archs, (f"{name}({sm}) 용 커널이 없다. torch {torch.__version__} 지원 아키텍처: {archs}. "
                     f"cu128 이상 휠이 필요하다.")
(torch.ones(1024, 1024, device="cuda") @ torch.ones(1024, 1024, device="cuda")).sum().item()  # 커널 실행 확인
print(f"[bootstrap] CUDA OK: {name}, {sm}, torch {torch.__version__}, cuda {torch.version.cuda}")
PY2
else
  echo "[bootstrap] GPU 없음 — CPU 모드"
  pip install -q --upgrade --force-reinstall torch --index-url https://download.pytorch.org/whl/cpu
  DEVICE=cpu
fi

# 서버 전용 설정: device 만 덮어쓴다 (나머지는 default.yaml 과 동일)
mkdir -p config
python - "$DEVICE" <<'PY'
import sys, yaml, pathlib
dev = sys.argv[1]
cfg = yaml.safe_load(pathlib.Path("config/default.yaml").read_text(encoding="utf-8"))
cfg["embedding"]["device"] = dev
cfg["embedding"]["batch_size"] = 64 if dev == "cuda" else 8
cfg.setdefault("rerank", {})["device"] = dev
pathlib.Path("config/server.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
print(f"[bootstrap] config/server.yaml 생성 (device={dev})")
PY

# 모델 미리 받기 (가중치는 저장소에 있는 한 포맷만). 이후 실행은 HF_HUB_OFFLINE=1 로 돌아간다.
export HF_HUB_DISABLE_XET=1 HF_HUB_DISABLE_SYMLINKS_WARNING=1
python - <<'PY'
import os
from huggingface_hub import HfApi, snapshot_download, hf_hub_download, try_to_load_from_cache

# 설정 파일과 같은 revision 을 쓴다. 노트북에서 만든 인덱스와 질의 임베딩이 같은 커밋이어야 한다.
REPOS = {
    "BAAI/bge-m3": "5617a9f61b028005a4858fdac845db406aefb181",
    "BAAI/bge-reranker-v2-m3": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
}
# 가중치 파일명은 저장소마다 다르다. bge-m3 는 pytorch_model.bin 만 있고 safetensors 가 없다.
# 하드코딩하면 404 로 bootstrap 이 죽는다 → 실제 파일 목록에서 고른다. 한 포맷만 받는다.
api = HfApi()
for repo, rev in REPOS.items():
    snapshot_download(repo, revision=rev,
                      allow_patterns=["*.json", "*.model", "1_Pooling/*", "2_Normalize/*"])
    files = api.list_repo_files(repo, revision=rev)
    weight = next((f for f in ("model.safetensors", "pytorch_model.bin") if f in files), None)
    if weight is None:
        raise SystemExit(f"[bootstrap] {repo}: 루트 가중치 파일을 찾지 못했다 — {files[:20]}")
    hit = try_to_load_from_cache(repo, weight, revision=rev)
    if not isinstance(hit, str):
        print(f"[bootstrap] {repo}/{weight} 다운로드 (한 포맷만)", flush=True)
        hit = hf_hub_download(repo, weight, revision=rev)
    print(f"[bootstrap] {repo}/{weight}  {os.path.getsize(hit)/1e9:.2f} GB  rev={rev[:8]}")
PY

python -m research_compass.cli --config config/server.yaml doctor --quick
echo "[bootstrap] 완료. 다음: bash server/run.sh build"
