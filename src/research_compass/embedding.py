"""임베딩 (명세 6.3). 모델 revision 을 고정하고 L2 정규화한다."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np


def _fmt_sec(s: float) -> str:
    if s != s or s == float("inf"):
        return "?"
    s = int(s)
    return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"


def cached_weight_format(model_id: str, revision: str | None = None) -> str | None:
    """로컬 HF 캐시에 이미 있는 가중치 포맷을 알려준다: 'safetensors' | 'bin' | None.

    같은 가중치를 두 포맷으로 중복 다운로드(2.27GB × 2)하지 않기 위해,
    이미 받아둔 포맷이 있으면 그것을 그대로 쓴다.
    """
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return None
    kw = {"revision": revision} if revision else {}
    st = try_to_load_from_cache(model_id, "model.safetensors", **kw)
    bn = try_to_load_from_cache(model_id, "pytorch_model.bin", **kw)
    if isinstance(st, str):
        return "safetensors"
    if isinstance(bn, str):
        return "bin"
    return None


class Embedder:
    def __init__(self, model_id: str, revision: str | None = None,
                 device: str = "cpu", batch_size: int = 8, max_tokens: int = 512):
        from sentence_transformers import SentenceTransformer

        fmt = cached_weight_format(model_id, revision)
        # 캐시에 .bin 만 있으면 .bin 을 쓰고, 그 외에는 safetensors 한 가지만 받는다.
        use_safetensors = fmt != "bin"
        self.weight_format = "pytorch_model.bin" if not use_safetensors else "model.safetensors"
        print(f"[모델] {model_id} — 가중치 포맷: {self.weight_format}"
              f"{' (캐시 재사용)' if fmt else ' (다운로드)'}", flush=True)

        kw = {"device": device, "model_kwargs": {"use_safetensors": use_safetensors}}
        if revision:
            kw["revision"] = revision
        t0 = time.monotonic()
        self.model = SentenceTransformer(model_id, **kw)
        print(f"[모델] 로딩 완료 ({_fmt_sec(time.monotonic() - t0)}), device={device}", flush=True)
        self.model.max_seq_length = max_tokens
        self.model_id = model_id
        self.batch_size = batch_size
        self.max_tokens = max_tokens
        # sentence-transformers 6.x 에서 메서드명이 바뀌었다. 양쪽 모두 지원.
        get_dim = getattr(self.model, "get_embedding_dimension", None) \
            or getattr(self.model, "get_sentence_embedding_dimension")
        self.dim = get_dim()

    def resolved_revision(self) -> str | None:
        """실제 내려받은 커밋 해시. 재현성 기록용."""
        try:
            for m in self.model.modules():
                cfg = getattr(m, "auto_model", None)
                if cfg is not None:
                    return getattr(cfg.config, "_commit_hash", None)
        except Exception:
            pass
        return None

    def encode(self, texts: list[str], show_progress: bool = False,
               chunk_size: int = 256, label: str = "임베딩") -> np.ndarray:
        """청크 단위로 인코딩하며 **줄바꿈이 있는** 진행 줄을 출력한다.

        tqdm 진행바는 \r 로 덧쓰기 때문에 파이프/로그 파일로는 끝날 때까지 보이지 않는다.
        파이프라인이 멈춘 것처럼 보이지 않도록 청크마다 한 줄씩 남긴다.
        """
        n = len(texts)
        if n == 0:
            return np.zeros((0, self.dim), dtype="float32")
        out, done, t0 = [], 0, time.monotonic()
        for i in range(0, n, chunk_size):
            chunk = texts[i:i + chunk_size]
            v = self.model.encode(chunk, batch_size=self.batch_size,
                                  normalize_embeddings=True,      # L2 정규화 (명세 6.3-3)
                                  convert_to_numpy=True,
                                  show_progress_bar=False)
            out.append(v.astype("float32"))
            done += len(chunk)
            if show_progress:
                el = time.monotonic() - t0
                rate = done / el if el > 0 else 0.0
                eta = (n - done) / rate if rate > 0 else float("nan")
                print(f"[{label}] {done:,}/{n:,} ({done / n:.0%})  경과 {_fmt_sec(el)}  "
                      f"예상 잔여 {_fmt_sec(eta)}  ({rate:.1f}건/s)", flush=True)
        return np.vstack(out)


def save(vectors: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, vectors)


def load(path: Path) -> np.ndarray:
    return np.load(path)


def check_vectors(v: np.ndarray) -> dict:
    """NaN·영벡터·정규화 검사 (명세 T-08)."""
    norms = np.linalg.norm(v, axis=1)
    return {
        "rows": int(v.shape[0]), "dim": int(v.shape[1]), "dtype": str(v.dtype),
        "nan_rows": int(np.isnan(v).any(axis=1).sum()),
        "zero_rows": int((norms < 1e-6).sum()),
        "norm_min": float(norms.min()), "norm_max": float(norms.max()),
        "normalized": bool(np.allclose(norms, 1.0, atol=1e-3)),
    }


def write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class HashEmbedder:
    """오프라인 테스트용 결정적 임베더. **실제 모델이 아니다.**

    네트워크가 없는 환경에서 파이프라인(정규화·인덱스·순위·필터)을 검증하기 위한 것으로,
    산출물에는 반드시 run_mode=test_fixture 로 표시한다. (명세 13.3)
    """

    model_id = "hash-fixture-v1"

    def __init__(self, dim: int = 256, **_):
        self.dim = dim

    def resolved_revision(self):
        return None

    def encode(self, texts, show_progress: bool = False, **_):
        import hashlib
        v = np.zeros((len(texts), self.dim), dtype="float32")
        for i, t in enumerate(texts):
            s = str(t)
            grams = [s[j:j + 3] for j in range(max(1, len(s) - 2))]
            for g in grams:
                h = int(hashlib.md5(g.encode()).hexdigest()[:8], 16)
                v[i, h % self.dim] += 1.0
        n = np.linalg.norm(v, axis=1, keepdims=True)
        n[n == 0] = 1.0
        return (v / n).astype("float32")


def make_embedder(cfg: dict, offline: bool = False):
    e = cfg["embedding"]
    if offline:
        return HashEmbedder(dim=256)
    return Embedder(model_id=e["model_id"], revision=e.get("revision"),
                    device=e.get("device", "cpu"), batch_size=e.get("batch_size", 8),
                    max_tokens=e.get("max_tokens", 512))
