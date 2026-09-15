"""Research Compass CLI. 현재 구현: doctor, audit."""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import __version__
from .audit import (audit_candidate_feasibility, audit_fields, audit_join,
                    audit_projects, basic_checks, read_raw)
import numpy as np
import pandas as pd

from . import classification as cls
from . import embedding as emb
from . import evaluation as ev
from . import prepare as prep
from .baseline import CharTfidfBaseline
from .retrieval import FlatIPIndex, rank
from .store import read_table, write_table
from . import crosswalk as xw
from .capabilities import decide
from .ingest import register
from .report import (write_audit_report, write_capabilities, write_crosswalk_report,
                     write_version_report)


def load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def resolve_source_file(root: Path, src: dict, raw_rel: str = "data/raw") -> Path | None:
    raw_dir = root / raw_rel
    if src.get("file"):
        p = raw_dir / src["file"]
        return p if p.exists() else None
    # 파일명이 지정되지 않았으면 데이터셋 제목 앞부분으로 추정 탐색한다.
    stem = src["title"].split("_")[1] if "_" in src["title"] else src["title"]
    for p in sorted(raw_dir.glob("*.csv")):
        if stem[:6] in p.name or src["dataset_id"] in p.name:
            return p
    return None


def _dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def _fmt_gb(n: int) -> str:
    return f"{n / 1e9:.2f} GB" if n >= 1e8 else f"{n / 1e6:.0f} MB"


def _model_cache_report(model_id: str) -> list[str]:
    """HF 캐시에 무엇이 있는지, 지워도 되는 찌꺼기가 있는지 보고한다."""
    try:
        from huggingface_hub import constants, try_to_load_from_cache
    except ImportError:
        return ["huggingface_hub 미설치 — 캐시 확인 생략"]
    hub = Path(constants.HF_HUB_CACHE)
    repo = hub / f"models--{model_id.replace('/', '--')}"
    out = [f"위치: {repo}"]
    if not repo.exists():
        out.append("아직 내려받은 모델 없음 (build-index 첫 실행 시 다운로드)")
    else:
        out.append(f"크기: {_fmt_gb(_dir_size(repo))}")
        for fn in ("model.safetensors", "pytorch_model.bin"):
            hit = try_to_load_from_cache(model_id, fn)
            out.append(f"{fn:22s} {'있음' if isinstance(hit, str) else '없음'}")
        partial = list((repo / "blobs").glob("*.incomplete")) if (repo / "blobs").exists() else []
        for f in partial:
            out.append(f"⚠ 미완료 다운로드 {_fmt_gb(f.stat().st_size)} — 지워도 됨: {f}")
    xet = hub.parent / "xet"
    if xet.exists():
        sz = _dir_size(xet)
        if sz > 1e8:
            out.append(f"xet 청크 캐시 {_fmt_gb(sz)} — 다운로드 가속용 임시 데이터. 지워도 됨: {xet}")
    return out


def cmd_doctor(args) -> int:
    root = Path(args.root).resolve()
    cfg = load_config(root / args.config)
    def say(s: str = "", end: str = "\n"):
        print(s, end=end, flush=True)      # 느린 import 중에도 화면이 멈춘 것처럼 보이지 않게

    say(f"Research Compass {__version__}")
    say(f"Python           : {sys.version.split()[0]} ({platform.platform()})")
    say(f"저장소 루트      : {root}")

    core = ["pandas", "numpy", "yaml"]
    heavy = ["sentence_transformers", "faiss", "sklearn", "streamlit"]
    slow = {"sentence_transformers": "PyTorch 로딩 — 첫 실행은 30초~2분 걸릴 수 있습니다"}

    say("\n패키지:")
    for mod in core + ([] if args.quick else heavy):
        if mod in slow:
            say(f"  {mod:24s} … {slow[mod]}", end="")
        else:
            say(f"  {mod:24s} … ", end="")
        t0 = time.monotonic()
        try:
            m = __import__(mod)
            ver = getattr(m, "__version__", "installed")
            say(f"\n    -> {ver}  ({time.monotonic() - t0:.1f}s)" if mod in slow
                else f"{ver}  ({time.monotonic() - t0:.1f}s)")
        except ImportError:
            say("\n    -> 미설치" if mod in slow else "미설치")
    if args.quick:
        say(f"  (--quick: {', '.join(heavy)} 확인 생략)")

    say("\n모델 캐시:")
    for line in _model_cache_report(cfg["embedding"]["model_id"]):
        say("  " + line)
    rr = cfg.get("rerank", {}).get("model_id")
    if rr:
        say("  --- 재정렬기 ---")
        for line in _model_cache_report(rr):
            say("  " + line)

    say("\n원본 파일:")
    ok = True
    for src in cfg["sources"]:
        p = resolve_source_file(root, src, cfg['paths']['raw'])
        role = src.get("role", "primary")
        if p:
            say(f"  {src['key']:4s} [{role}]  {p.name}  ({p.stat().st_size:,} bytes)")
        else:
            ok = False
            say(f"  {src['key']:4s} [{role}]  — data/raw 에 없음  ({src['source_url']})")
    say("\n준비 완료" if ok else "\n원본 CSV 를 data/raw 에 넣은 뒤 실행하세요.")
    return 0


def cmd_audit(args) -> int:
    root = Path(args.root).resolve()
    cfg = load_config(root / args.config)
    acfg = cfg["audit"]

    snaps, frames = {}, {}
    for src in cfg["sources"]:
        p = resolve_source_file(root, src, cfg['paths']['raw'])
        if p is None:
            print(f"[중단] {src['key']} 원본 파일을 찾지 못했습니다: {src['source_url']}", file=sys.stderr)
            return 2
        snap = register(p, src["key"], src["dataset_id"], src["title"],
                        src["source_url"], acfg["encoding_candidates"])
        snaps[src["key"]] = snap
        frames[src["key"]] = read_raw(snap)
        print(f"[등록] {src['key']} {p.name} sha256={snap.sha256[:16]}… "
              f"encoding={snap.encoding} rows={len(frames[src['key']])}")

    d1_cfg = next(s for s in cfg["sources"] if s["key"] == "D1")
    d2_cfg = next(s for s in cfg["sources"] if s["key"] == "D2")

    d1_basic = basic_checks(frames["D1"], snaps["D1"], d1_cfg.get("registry_row_count"))
    d1_find = audit_projects(frames["D1"], acfg)
    d2_basic = basic_checks(frames["D2"], snaps["D2"], d2_cfg.get("registry_row_count"))
    d2_find = audit_fields(frames["D2"], d2_cfg.get("registry_period_claim"))
    join_find = audit_join(frames["D1"], frames["D2"])
    feas_find = audit_candidate_feasibility(frames["D1"], frames["D2"])

    caps = decide(d1_basic, d1_find, d2_basic, d2_find, join_find)

    sections = {
        "D1 · 과제정보 — 공통 점검": d1_basic,
        "D1 · 과제정보 — 항목 점검": d1_find,
        "D2 · 연구분야 — 공통 점검": d2_basic,
        "D2 · 연구분야 — 항목 점검": d2_find,
        "D1 ↔ D2 연결 가능성": join_find,
        "FR-04 후보 성립성 사전 점검": feas_find,
    }

    reports = root / cfg["paths"]["reports"]
    artifacts = root / cfg["paths"]["artifacts"]
    write_audit_report(reports / "data_audit.md",
                       [s.to_dict() for s in snaps.values()], sections, caps)
    write_capabilities(artifacts / "capabilities.json", caps)

    manifest = {
        "schema_version": cfg["schema_version"],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "snapshots": [s.to_dict() for s in snaps.values()],
        "row_counts": {k: int(len(v)) for k, v in frames.items()},
    }
    (artifacts / "data_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[출력] {reports / 'data_audit.md'}")
    print(f"[출력] {artifacts / 'capabilities.json'}")
    print(f"[출력] {artifacts / 'data_manifest.json'}")
    print("\n기능 가용성:")
    for k, v in caps.items():
        print(f"  {k:26s} {v['status']}")
    return 0


def cmd_crosswalk(args) -> int:
    """P1 — D2 중심분야코드 ↔ KISTEP 국가과학기술표준분류 대조."""
    import json as _json
    root = Path(args.root).resolve()
    cfg = load_config(root / args.config)
    acfg = cfg["audit"]
    srcs = {s["key"]: s for s in cfg["sources"]}
    if "K1" not in srcs:
        print("[중단] config 에 K1(KISTEP) 원본이 정의되어 있지 않습니다.", file=sys.stderr)
        return 2

    snaps = {}
    frames = {}
    for key in ("D2", "K1"):
        src = srcs[key]
        p = resolve_source_file(root, src, cfg["paths"]["raw"])
        if p is None:
            print(f"[중단] {key} 원본을 찾지 못했습니다: {src['source_url']}", file=sys.stderr)
            return 2
        snap = register(p, key, src["dataset_id"], src["title"], src["source_url"],
                        acfg["encoding_candidates"])
        snaps[key] = snap
        frames[key] = read_raw(snap)
        print(f"[등록] {key} {p.name} sha256={snap.sha256[:16]}… "
              f"encoding={snap.encoding} rows={len(frames[key])}")

    res = xw.build(frames["D2"], frames["K1"])
    g = xw.gate(res, cfg.get("coverage", {}).get("min_code_match_rate", 0.95))

    artifacts = root / cfg["paths"]["artifacts"]
    artifacts.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "policy": {
            "kistep_role": srcs["K1"].get("role", "auxiliary"),
            "absent_code_semantics": cfg.get("coverage", {}).get("absent_code_semantics", "unobserved"),
            "note": "KISTEP 에 있으나 D2 에 없는 코드는 '선정 0건' 이 아니라 'unobserved' 다.",
        },
        "snapshots": {k: v.to_dict() for k, v in snaps.items()},
        "result": res.to_dict(),
        "gate": g,
    }
    out = artifacts / "crosswalk.json"
    out.write_text(_json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    reports = root / cfg["paths"]["reports"]
    write_crosswalk_report(reports / "p1_crosswalk.md", payload)
    print(f"\n[출력] {out}")
    print(f"[출력] {reports / 'p1_crosswalk.md'}")
    print(f"\n정확 일치율(전체)      : {res.code_match}/{res.d2_rows} = {res.code_match_rate:.2%}"
          f"  -> 게이트 {'통과' if g['overall']['pass'] else '미달'}")
    print(f"정확 일치율(체계 내)    : {res.in_scheme_match_rate:.2%} "
          f"(D2 의 {g['in_scheme_only']['coverage_of_d2']:.1%} 에 해당)"
          f"  -> 게이트 {'통과' if g['in_scheme_only']['pass'] else '미달'}")
    print(f"명칭 일치율(정규화 후)  : {res.name_normalized}/{res.code_match} = {res.name_normalized_rate:.2%}")
    print(f"unobserved (범위 한정)  : {res.unobserved_in_scope} / 범위 소분류 {res.scope_minor_total}")
    print(f"체계 밖 코드            : {res.out_scheme_rows}행, 접두 {res.out_scheme_prefixes}")
    return 0


def cmd_verify_scheme(args) -> int:
    """P1-B — D2 기준 분류체계 버전 검증 (2018 vs 2023)."""
    import json as _json
    root = Path(args.root).resolve()
    cfg = load_config(root / args.config)
    acfg = cfg["audit"]
    srcs = {s["key"]: s for s in cfg["sources"]}

    frames, snaps = {}, {}
    for key in ("D2", "K18", "K1"):
        if key not in srcs:
            continue
        src = srcs[key]
        p = resolve_source_file(root, src, cfg["paths"]["raw"])
        if p is None:
            if key == "K1":
                continue
            print(f"[중단] {key} 원본 없음: {src['source_url']}", file=sys.stderr)
            return 2
        snap = register(p, key, src["dataset_id"], src["title"], src["source_url"],
                        acfg["encoding_candidates"])
        snaps[key] = snap
        frames[key] = read_raw(snap)
        print(f"[등록] {key} {p.name} sha256={snap.sha256[:16]}… rows={len(frames[key])}")

    ref = cls.load_2018_reference(frames["K18"])
    v = cls.verify_against_2018(frames["D2"], ref)
    pop = cls.population_status(ref, frames["D2"])

    v2023 = {}
    if "K1" in frames:
        k = frames["K1"].copy()
        for c in k.columns:
            k[c] = k[c].astype(str).str.strip()
        code = frames["D2"]["중심분야코드"].astype(str).str.strip()
        hit = code.isin(set(k["소분류코드"]))
        v2023 = {
            "rows": len(code), "minor_match": int(hit.sum()),
            "minor_rate": round(float(hit.mean()), 6),
            "missing_majors": sorted(set(code.str[:2]) - set(k["대분류코드"])),
        }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "policy": {
            "population_source": cfg["classification"]["population_source"],
            "crosswalk_source": cfg["classification"]["crosswalk_source"],
            "absent_code_semantics": "unobserved",
            "withdrawn": "p1_crosswalk.md 의 unobserved 1,608 (2023 모집단 기반) — 철회",
        },
        "snapshots": {k: s.to_dict() for k, s in snaps.items()},
        "reference_rows": int(len(ref)),
        "verify": v.to_dict(),
        "population": pop,
        "v2023_reference": v2023,
    }
    artifacts = root / cfg["paths"]["artifacts"]
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "scheme_version.json").write_text(
        _json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_version_report(root / cfg["paths"]["reports"] / "p1b_scheme_version.md", payload)

    print(f"\n[출력] {artifacts / 'scheme_version.json'}")
    print(f"[출력] {root / cfg['paths']['reports'] / 'p1b_scheme_version.md'}")
    print(f"\n기준 체계 : {v.version_label}")
    print(f"  대분류(2자리)          : {v.major_rate:.2%}")
    print(f"  중분류(4자리, exact)   : {v.mid_rate:.2%}")
    print(f"  소분류명(엄격)         : {v.name_strict_rate:.2%}")
    print(f"  소분류명(포함관계 허용) : {v.name_contained_rate:.2%}")
    print(f"  코드·명칭 충돌         : {v.code_name_conflict}건")
    print(f"  설명 안 되는 건        : {len(v.unexplained_names)}건")
    if v2023:
        print(f"  [참고] 2023판 6자리 일치 : {v2023['minor_rate']:.2%}")
    print(f"\n모집단 산정: {pop['status']} — {pop['reason']}")
    return 0


def _load_pair(root: Path, cfg: dict):
    acfg = cfg["audit"]
    srcs = {s["key"]: s for s in cfg["sources"]}
    out = {}
    for key in ("D1", "D2"):
        src = srcs[key]
        p = resolve_source_file(root, src, cfg["paths"]["raw"])
        if p is None:
            raise SystemExit(f"[중단] {key} 원본 없음: {src['source_url']}")
        snap = register(p, key, src["dataset_id"], src["title"], src["source_url"],
                        acfg["encoding_candidates"])
        out[key] = (snap, read_raw(snap))
    return out


def _load_engines(root: Path, cfg: dict, need_semantic: bool = True):
    """정제 데이터 + (있으면) 실제 인덱스 + 어휘 baseline 을 함께 로드한다."""
    import json as _json
    proc = root / cfg["paths"]["processed"]
    art = root / cfg["paths"]["artifacts"]
    projects = read_table(proc, "projects")
    base = CharTfidfBaseline(projects["search_text"].tolist(),
                             cfg["baseline"]["ngram_min"], cfg["baseline"]["ngram_max"])
    sem = None
    if need_semantic and (art / "project_embeddings.npy").exists():
        man = _json.loads((art / "index_manifest.json").read_text(encoding="utf-8"))
        e = emb.make_embedder(cfg, offline=(man["run_mode"] == "test_fixture"))
        idx = FlatIPIndex(emb.load(art / "project_embeddings.npy"))
        sem = {"embedder": e, "index": idx, "run_mode": man["run_mode"]}
    return projects, base, sem


def cmd_prepare(args) -> int:
    root = Path(args.root).resolve()
    cfg = load_config(root / args.config)
    pair = _load_pair(root, cfg)
    proc = root / cfg["paths"]["processed"]
    proc.mkdir(parents=True, exist_ok=True)

    projects, excluded = prep.build_projects(pair["D1"][1], pair["D1"][0], cfg)
    fields = prep.build_fields(pair["D2"][1], pair["D2"][0], cfg)

    p_path = write_table(projects, proc, "projects")
    f_path = write_table(fields, proc, "fields")
    excluded.to_csv(proc / "projects_excluded.csv", index=False, encoding="utf-8-sig")

    print(f"[정제] ProjectRecord {len(projects):,}건  (제외 {len(excluded)}건)")
    if len(excluded):
        print("  제외 사유:", dict(excluded["_exclude_reason"].value_counts()))
    print(f"[정제] FieldRecord   {len(fields):,}건")
    print(f"  짧은 제목(10자 미만) 표시: "
          f"{int(projects['quality_flags'].map(lambda x: 'short_title' in x).sum()):,}건")
    print(f"[출력] {p_path}")
    print(f"[출력] {f_path}")
    print(f"[출력] {proc / 'projects_excluded.csv'}")
    return 0


def cmd_build_index(args) -> int:
    if args.no_download:
        # 캐시에 없는 파일은 내려받지 않고 명시적으로 실패한다.
        os.environ["HF_HUB_OFFLINE"] = "1"
    root = Path(args.root).resolve()
    cfg = load_config(root / args.config)
    proc = root / cfg["paths"]["processed"]
    art = root / cfg["paths"]["artifacts"]
    art.mkdir(parents=True, exist_ok=True)

    projects = read_table(proc, "projects")
    fields = read_table(proc, "fields")

    e = emb.make_embedder(cfg, offline=args.offline)
    run_mode = "test_fixture" if args.offline else cfg["runtime"]["mode"]
    if args.offline:
        print("[경고] 오프라인 해시 임베더 사용 — 실제 검색 품질을 나타내지 않습니다 (test_fixture)")

    print(f"[인덱스] 과제 {len(projects):,}건 임베딩 시작 (batch={cfg['embedding'].get('batch_size', 8)})", flush=True)
    pv = e.encode(projects["search_text"].tolist(), show_progress=True, label="과제 임베딩")
    print(f"[인덱스] 분야 {len(fields):,}건 임베딩 시작", flush=True)
    fv = e.encode(fields["search_text"].tolist(), show_progress=True, label="분야 임베딩")
    emb.save(pv, art / "project_embeddings.npy")
    emb.save(fv, art / "field_embeddings.npy")

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_mode": run_mode,
        "model_id": getattr(e, "model_id", cfg["embedding"]["model_id"]),
        "model_revision": e.resolved_revision(),
        "text_template": cfg["embedding"]["text_template"],
        "normalize": True,
        "projects": emb.check_vectors(pv),
        "fields": emb.check_vectors(fv),
        "project_snapshot": str(projects["source_snapshot_id"].iloc[0]),
        "field_snapshot": str(fields["source_snapshot_id"].iloc[0]),
    }
    emb.write_manifest(art / "index_manifest.json", manifest)
    print(f"[인덱스] 과제 {pv.shape}  분야 {fv.shape}  mode={run_mode}")
    print(f"  벡터 검사(과제): {manifest['projects']}")
    print(f"[출력] {art / 'index_manifest.json'}")
    return 0


def cmd_search(args) -> int:
    import json as _json
    root = Path(args.root).resolve()
    cfg = load_config(root / args.config)
    if not cfg["runtime"].get("allow_network_during_search", False):
        os.environ["HF_HUB_OFFLINE"] = "1"       # 검색 중 외부 호출 금지 (명세 3.3)
    proc = root / cfg["paths"]["processed"]
    art = root / cfg["paths"]["artifacts"]

    projects = read_table(proc, "projects")
    ids = projects["record_id"].tolist()

    use_emb = (art / "project_embeddings.npy").exists() and not args.baseline_only
    results = {}

    # 필터: 짧은 제목 제외 (삭제가 아니라 검색 대상 마스크. 명세 5.3)
    mask = None
    if args.exclude_short:
        mask = ~projects["quality_flags"].map(lambda f: "short_title" in (f or [])).to_numpy()

    if use_emb:
        man = _json.loads((art / "index_manifest.json").read_text(encoding="utf-8"))
        e = emb.make_embedder(cfg, offline=(man["run_mode"] == "test_fixture"))
        idx = FlatIPIndex(emb.load(art / "project_embeddings.npy"))
        q = e.encode([args.query])[0]
        s = idx.scores(q)
        # T-09: FAISS vs NumPy 참조 구현 대조
        ref = idx.scores_numpy(q)
        drift = float(np.abs(s - ref).max())
        results["semantic"] = (rank(s, ids, mask, args.top_k), idx.backend, drift, man["run_mode"], s)

    base = CharTfidfBaseline(projects["search_text"].tolist(),
                             cfg["baseline"]["ngram_min"], cfg["baseline"]["ngram_max"])
    bs = base.scores(prep.normalize_text(args.query))
    results["baseline"] = rank(bs, ids, mask, args.top_k)

    print(f"질의: {args.query}" + ("   [짧은 제목 제외]" if args.exclude_short else "") + "\n")
    if "semantic" in results:
        rows, backend, drift, mode, s_all = results["semantic"]
        tag = " [테스트 임베더 — 실제 품질 아님]" if mode == "test_fixture" else ""
        print(f"── 의미 검색 (backend={backend}, FAISS-NumPy 최대 오차={drift:.2e}){tag}")
        for r, (i, sc) in enumerate(rows, 1):
            p = projects.iloc[i]
            flag = " ⚑짧은제목" if "short_title" in (p["quality_flags"] or []) else ""
            print(f"  {r:2d}. 의미 유사도 {sc:.3f}  {p['title_raw'][:64]}{flag}")
            print(f"      {p['institution']} · 선정 {p['selection_year']} · row {p['source_row']}")
        if args.stats:
            d = ev.score_distribution(s_all if mask is None else s_all[mask])
            print(f"\n  [점수 분포 · 전체 {d['n']:,}건] 최대 {d['max']}  p99.9 {d['p99.9']}  "
                  f"p99 {d['p99']}  p90 {d['p90']}  중앙값 {d['p50']}  σ {d['std']}")
            print(f"  1위−p99 = {d['top1_minus_p99']}  (작을수록 상위 결과가 무작위 배경과 구분되지 않음)")
        print()
    print("── 어휘 검색 baseline (char n-gram TF-IDF)")
    for r, (i, sc) in enumerate(results["baseline"], 1):
        p = projects.iloc[i]
        flag = " ⚑짧은제목" if "short_title" in (p["quality_flags"] or []) else ""
        print(f"  {r:2d}. 어휘 점수 {sc:.3f}  {p['title_raw'][:64]}{flag}")
    if args.stats:
        d = ev.score_distribution(bs if mask is None else bs[mask])
        print(f"  [점수 분포] 최대 {d['max']}  p99 {d['p99']}  중앙값 {d['p50']}  1위−p99 = {d['top1_minus_p99']}")
    print("\n※ 관련도 기준값 미검증 상태 — 위 결과는 '가까운 검색 결과'이며 관련성은 별도 검증 필요")
    return 0


def cmd_make_eval_pool(args) -> int:
    root = Path(args.root).resolve()
    cfg = load_config(root / args.config)
    if not cfg["runtime"].get("allow_network_during_search", False):
        os.environ["HF_HUB_OFFLINE"] = "1"
    qpath = root / "evaluation" / f"queries_{args.split}.jsonl"
    queries = ev.load_queries(qpath)
    projects, base, sem = _load_engines(root, cfg, need_semantic=True)
    if sem is None:
        print("[중단] 실제 인덱스가 없습니다. build-index 를 먼저 실행하세요.", file=sys.stderr)
        return 2
    if sem["run_mode"] == "test_fixture":
        print("[중단] 인덱스가 test_fixture 입니다. 라벨링 풀은 실제 모델 결과로만 만듭니다.", file=sys.stderr)
        return 2

    def sem_fn(q: str):
        return sem["index"].scores(sem["embedder"].encode([q])[0])

    def lex_fn(q: str):
        return base.scores(prep.normalize_text(q))

    sheet, key = ev.make_pool(queries, projects, sem_fn, lex_fn, split=args.split, k=5)
    out_dir = root / "evaluation"
    sheet_path = out_dir / f"label_sheet_{args.split}.csv"
    key_path = out_dir / f"pool_key_{args.split}.csv"          # 라벨러에게 보여주지 않음
    ev.write_sheet(sheet, sheet_path)
    key.to_csv(key_path, index=False, encoding="utf-8-sig", lineterminator="\n")
    print(f"[풀] 질의 {len(queries)}개 → 라벨 대상 {len(sheet)}건 "
          f"(질의당 평균 {len(sheet) / max(1, len(queries)):.1f}건, 의미∪어휘 중복 제거)")
    print(f"[출력] {sheet_path}   ← 엑셀로 열어 label 열에 2/1/0/U 입력")
    print(f"[출력] {key_path}     ← 채점용. 라벨링 중에는 열지 않음")
    print(f"      짧은 제목이 풀에 포함된 건수: {int(key['short_title'].sum())}")
    return 0


def cmd_evaluate(args) -> int:
    import json as _json
    root = Path(args.root).resolve()
    cfg = load_config(root / args.config)
    out_dir = root / "evaluation"
    sheet_path = out_dir / (getattr(args, "sheet", None) or f"label_sheet_{args.split}.csv")
    sheet = None
    for enc in ("utf-8-sig", "cp949"):          # 엑셀이 CP949 로 저장했을 수 있다
        try:
            sheet = pd.read_csv(sheet_path, dtype=str, keep_default_na=False, encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    if sheet is None:
        print(f"[중단] {sheet_path} 인코딩을 읽지 못했습니다 (utf-8/cp949 모두 실패)", file=sys.stderr)
        return 2
    sheet.columns = [c.strip() for c in sheet.columns]
    key = pd.read_csv(out_dir / f"pool_key_{args.split}.csv", dtype={"item_id": str, "query_id": str},
                      encoding="utf-8-sig")
    key["short_title"] = key["short_title"].astype(str).str.lower().eq("true")
    res = ev.score(sheet, key, k=5)
    s = res["summary"]
    if s["n_unlabeled"]:
        print(f"[경고] 미라벨 {s['n_unlabeled']}건 — 결과는 부분 라벨 기준입니다.")
    if s["n_invalid_labels"]:
        print(f"[경고] 허용되지 않는 라벨 {s['n_invalid_labels']}건 (2/1/0/U 만 허용)")
    print(f"질의 {s['n_queries']}개 · P@{s['k']} (하한, 상한)")
    print(f"  의미 검색  엄격 {s['semantic_strict']}   완화 {s['semantic_lenient']}")
    print(f"  어휘 검색  엄격 {s['lexical_strict']}   완화 {s['lexical_lenient']}")
    print(f"  {s['note']}")
    rep = out_dir / "results" / f"evaluation_{args.split}.json"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(_json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[출력] {rep}")
    return 0


def cmd_make_tau_probe(args) -> int:
    root = Path(args.root).resolve()
    cfg = load_config(root / args.config)
    if not cfg["runtime"].get("allow_network_during_search", False):
        os.environ["HF_HUB_OFFLINE"] = "1"
    queries = ev.load_queries(root / "evaluation" / f"queries_{args.split}.jsonl")
    projects, base, sem = _load_engines(root, cfg, need_semantic=True)
    if sem is None or sem["run_mode"] == "test_fixture":
        print("[중단] 실모델 인덱스가 필요합니다 (build-index).", file=sys.stderr)
        return 2
    sem_fn = lambda q: sem["index"].scores(sem["embedder"].encode([q])[0])
    sheet, key = ev.make_tau_probe(queries, projects, sem_fn, split=args.split)
    out = root / "evaluation"
    ev.write_sheet(sheet, out / f"label_sheet_tau_{args.split}.csv")
    key.to_csv(out / f"pool_key_tau_{args.split}.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    print(f"[tau 표본] 질의 {len(queries)}개 × (순위 {list(ev.PROBE_RANKS)} + 무작위 3) = {len(sheet)}건")
    print(f"[출력] {out / f'label_sheet_tau_{args.split}.csv'}   ← 라벨 대상 (블라인드)")
    print(f"[출력] {out / f'pool_key_tau_{args.split}.csv'}     ← 채점용")
    return 0


def _read_label_sheet(path: Path) -> pd.DataFrame:
    """엑셀이 CP949 로 저장했을 수 있다."""
    for enc in ("utf-8-sig", "cp949"):
        try:
            d = pd.read_csv(path, dtype=str, keep_default_na=False, encoding=enc)
            d.columns = [c.strip() for c in d.columns]
            return d
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"[중단] {path} 인코딩을 읽지 못했습니다 (utf-8/cp949 모두 실패)")


def cmd_analyze_tau(args) -> int:
    import json as _json
    root = Path(args.root).resolve()
    out = root / "evaluation"
    sheet = _read_label_sheet(out / (args.sheet or f"label_sheet_tau_{args.split}.csv"))
    key = pd.read_csv(out / f"pool_key_tau_{args.split}.csv", encoding="utf-8-sig",
                      dtype={"item_id": str, "query_id": str})
    m = sheet.merge(key, on=["query_id", "item_id"])
    if len(m) != len(sheet):
        print(f"[경고] 시트 {len(sheet)}행 중 {len(m)}행만 key 와 결합됨", file=sys.stderr)

    spaces = args.spaces.split(",") if args.spaces else list(ev.SCORE_SPACES)
    report = {"split": args.split, "sheet": args.sheet or f"label_sheet_tau_{args.split}.csv",
              "labeler": (m["labeler"].iloc[0] if "labeler" in m.columns and len(m) else None),
              "spaces": {}, "skipped": {}}
    for space in spaces:
        col = ev.SCORE_SPACES.get(space, (None, None))[0]
        if col not in m.columns or pd.to_numeric(m[col], errors="coerce").notna().sum() == 0:
            report["skipped"][space] = f"'{col}' 점수 없음 — rescore-pool 을 먼저 실행한다"
            continue
        res = ev.tau_curve(m, space=space)
        report["spaces"][space] = res
        unit = "순위" if res["direction"] == "asc" else "점수"
        gate = "≤" if res["direction"] == "asc" else "≥"
        print(f"\n══ 점수 공간 {space}  ({col}, {unit} {gate} tau 가 관련) ══")
        print(f"라벨된 표본 {res['n_labeled']}건 (U {res['n_U']}건 제외"
              + (f", 점수 없음 {res['n_missing_score']}건" if res["n_missing_score"] else "") + ")")
        print(f"  tau       n{gate}tau  정밀도(2)  정밀도(2∪1)")
        for r in res["cumulative"]:
            print(f"  {r['tau']:8.2f}  {r['n_at_or_above']:4d}    {r['precision_2']:.2f}       {r['precision_2or1']:.2f}")
        print("  구간별(비누적) 관련 비율(2∪1):")
        for b in res["bands"]:
            print(f"    [{b['from']:.2f}, {b['to']:.2f})  n={b['n']:3d}  관련 {b['rel_2or1']:.2f}")
        print("  제안:", res["suggest"])
    for space, why in report["skipped"].items():
        print(f"\n══ 점수 공간 {space} — 건너뜀: {why}")
    if report["spaces"]:
        print("\n ", next(iter(report["spaces"].values()))["note"])
    rep = out / "results" / f"tau_curve_{args.split}.json"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(_json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[출력] {rep}")
    return 0


def cmd_evaluate_conditions(args) -> int:
    """조건 A~D' 를 같은 라벨로 채점한다 (개정안 9.1). 미라벨 항목은 증분 시트로 뽑는다."""
    import json as _json
    from . import search as svc

    root = Path(args.root).resolve()
    cfg = load_config(root / args.config)
    if not cfg["runtime"].get("allow_network_during_search", False):
        os.environ["HF_HUB_OFFLINE"] = "1"
    out = root / "evaluation"
    queries = ev.load_queries(out / f"queries_{args.split}.jsonl")
    conditions = [c.strip() for c in args.conditions.split(",")]
    for c in conditions:
        if c not in ev.CONDITIONS:
            print(f"[중단] 알 수 없는 조건 {c!r} — {list(ev.CONDITIONS)}", file=sys.stderr)
            return 2

    # 기존 라벨 모으기 (Top-5 풀 + tau 심층 표본 + 증분). record_id 로 맞춘다.
    sheets = []
    for sname, kname in ((f"label_sheet_{args.split}.llm.csv", f"pool_key_{args.split}.csv"),
                         (f"label_sheet_tau_{args.split}.llm.csv", f"pool_key_tau_{args.split}.csv"),
                         (f"label_sheet_{args.split}_incr.llm.csv", f"pool_key_{args.split}_incr.csv")):
        if (out / sname).exists() and (out / kname).exists():
            sheets.append((sname, _read_label_sheet(out / sname),
                           pd.read_csv(out / kname, encoding="utf-8-sig",
                                       dtype={"item_id": str, "query_id": str, "record_id": str})))
            print(f"[라벨] {sname}")
    if not sheets:
        print(f"[중단] {args.split} 라벨 시트가 없습니다.", file=sys.stderr)
        return 2
    labels, problems = ev.collect_labels(sheets, perspective=args.perspective)
    src_counts = ev.label_source_counts(labels)
    print(f"[라벨] 총 {len(labels)}건  출처 {src_counts}  관점={args.perspective}")
    if problems:
        # v2 §17.5: keep=first 로 감추지 않는다. 무결성 위반은 실패다.
        print(f"[중단] 라벨·키 무결성 위반 {len(problems)}건 — 채점을 진행하지 않습니다.",
              file=sys.stderr)
        by_kind: dict[str, int] = {}
        for p in problems:
            by_kind[p["kind"]] = by_kind.get(p["kind"], 0) + 1
        for kind, n in sorted(by_kind.items()):
            print(f"  {kind}: {n}건", file=sys.stderr)
        for p in problems[:10]:
            print(f"  - {p}", file=sys.stderr)
        rep = out / "results" / f"label_integrity_{args.split}.json"
        rep.parent.mkdir(parents=True, exist_ok=True)
        rep.write_text(json.dumps(problems, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[출력] {rep}", file=sys.stderr)
        print("  key_missing 은 증분 key 덮어쓰기 회귀입니다. label_disagreement 는 조정 후 재실행하세요.",
              file=sys.stderr)
        return 2

    engine = svc.SearchEngine(root, cfg, need_semantic=True)
    if engine.semantic is None or engine.run_mode == "test_fixture":
        print("[중단] 실모델 인덱스가 필요합니다 (build-index).", file=sys.stderr)
        return 2
    need_rr = any(ev.CONDITIONS[c]["rerank"] for c in conditions)
    if need_rr and engine.reranker() is None:
        print("[중단] 재정렬기를 적재할 수 없습니다. prepare-reranker 를 먼저 실행하세요.", file=sys.stderr)
        return 2

    report = {
        "split": args.split, "k": args.k, "run_mode": engine.run_mode,
        # v2 §17.3: 평가 단위에 관점과 실제 검색문이 들어가야 한다
        "perspective": args.perspective,
        "label_sources": src_counts,
        "label_sheets": [s[0] for s in sheets],
        "labeler_note": "라벨은 기존 시트 재사용 (라벨은 점수기와 독립, 개정안 6.1). "
                        "LLM 라벨과 사람 라벨을 하나의 정확도로 섞지 않는다 (v2 §17.3).",
        # v2 §17.4: 결과를 보고 설정을 고른 분할은 개발 의사결정에 쓰인 평가로 표시한다
        "used_for_selection": bool(args.used_for_selection),
        "conditions": {}, "label_integrity_problems": problems,
    }
    all_missing: dict[tuple[str, str], dict] = {}

    for cond in conditions:
        spec = ev.CONDITIONS[cond]
        rankings, timings, warn, effective = {}, [], set(), {}
        for q in queries:
            qid, text = q["query_id"], q["query"]
            effective[qid] = prep.normalize_text(text)      # 이번 평가는 full 관점 = 원래 주제
            if cond == "B":                      # 어휘 단독은 baseline 을 직접 쓴다
                s = engine.baseline.scores(prep.normalize_text(text))
                order = sorted(range(len(s)), key=lambda i: (-float(s[i]), engine.ids[i]))
                rankings[qid] = [engine.ids[i] for i in order[:args.k]]
                continue
            req = svc.SearchRequest(query=text, top_k=args.k, hybrid=bool(spec["hybrid"]),
                                    rerank=bool(spec["rerank"]),
                                    rerank_top_n=int(spec["top_n"] or 20))
            resp = svc.search(req, engine)
            effective[qid] = resp.normalized_query
            rankings[qid] = [r.record_id for r in resp.results]
            timings.append(resp.timings.get("total_s", 0.0))
            warn.update(resp.warnings)
            if spec["rerank"] and not resp.rerank_applied:
                warn.add("RERANK_NOT_APPLIED_IN_EVAL")
        res = ev.score_condition(rankings, labels, k=args.k, perspective=args.perspective)
        res["label"] = spec["label"]
        res["warnings"] = sorted(warn)
        res["effective_queries"] = effective
        if timings:
            res["latency_s"] = {"mean": round(float(np.mean(timings)), 3),
                                "max": round(float(max(timings)), 3)}
        report["conditions"][cond] = res
        for m in res["missing"]:
            all_missing[(m["query_id"], m["record_id"])] = m
        lat = f"  평균 {res['latency_s']['mean']}s" if "latency_s" in res else ""
        flag = f"  ⚠ 미라벨 {res['n_missing_labels']}건" if res["n_missing_labels"] else ""
        print(f"  {cond:2s} {spec['label']:22s} 엄격 {res['strict']}  완화 {res['lenient']}{lat}{flag}")
        if res["warnings"]:
            print(f"       경고: {', '.join(res['warnings'])}")

    rep = out / "results" / f"evaluation_conditions_{args.split}.json"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(_json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[출력] {rep}")

    if all_missing:
        # 증분 라벨 시트 (블라인드: 조건·순위를 넣지 않는다)
        qtext = {q["query_id"]: q["query"] for q in queries}
        row_of = {rid: i for i, rid in enumerate(engine.ids)}
        rows, krows = [], []
        for (qid, rid) in sorted(all_missing):
            p = engine.projects.iloc[row_of[rid]]
            bid = ev._blind_id(f"{args.split}-incr", qid, rid)
            rows.append({"query_id": qid, "query": qtext[qid], "item_id": bid,
                         "title": p["title_raw"], "institution": p.get("institution", ""),
                         "selection_year": p.get("selection_year", ""),
                         "program": p.get("program_대사업명", ""), "label": "", "note": ""})
            krows.append({"query_id": qid, "item_id": bid, "record_id": rid,
                          "source_row": p["source_row"],
                          "short_title": "short_title" in (p.get("quality_flags") or [])})
        sp = out / f"label_sheet_{args.split}_incr.csv"
        kp = out / f"pool_key_{args.split}_incr.csv"
        # 채점 키는 **누적**한다. 덮어쓰면 앞선 증분 라운드의 라벨이 결합되지 않아 사라진다 (v2 §17.5).
        knew = pd.DataFrame(krows)
        if kp.exists():
            kold = pd.read_csv(kp, encoding="utf-8-sig",
                               dtype={"item_id": str, "query_id": str, "record_id": str})
            merged = pd.concat([kold, knew], ignore_index=True)
            # 같은 (query_id, item_id) 가 다른 record_id 를 가리키면 실패다. keep=first 로 덮지 않는다.
            clash = (merged.groupby(["query_id", "item_id"])["record_id"].nunique() > 1)
            if clash.any():
                bad = clash[clash].index.tolist()
                print(f"[중단] 증분 key 충돌 {len(bad)}건 — 같은 item_id 가 다른 레코드를 가리킵니다.",
                      file=sys.stderr)
                for q, i in bad[:10]:
                    rids = sorted(set(merged[(merged.query_id == q) & (merged.item_id == i)]
                                      ["record_id"]))
                    print(f"  {q} {i}: {rids}", file=sys.stderr)
                print(f"  {kp} 를 보존한 상태로 중단했습니다. 충돌을 해소한 뒤 재실행하세요.",
                      file=sys.stderr)
                return 2
            knew = merged.drop_duplicates(subset=["query_id", "item_id", "record_id"])
        knew.to_csv(kp, index=False, encoding="utf-8-sig", lineterminator="\n")
        # 앞선 라운드에서 이미 라벨한 항목은 다시 묻지 않는다.
        # item_id 단독이 아니라 (query_id, item_id) 로 판정한다 — item_id 전역 유일성은 보장되지 않는다.
        done = out / f"label_sheet_{args.split}_incr.llm.csv"
        if done.exists():
            d = _read_label_sheet(done)
            have = {(str(r["query_id"]), str(r["item_id"])) for _, r in d.iterrows()
                    if str(r["label"]).strip() != ""}
            rows = [r for r in rows if (r["query_id"], r["item_id"]) not in have]
        ev.write_sheet(pd.DataFrame(rows), sp)      # 시트는 아직 라벨이 없는 항목만
        print(f"[증분 라벨 필요] {len(rows)}건 → {sp}")
        print(f"                 채점 키 {len(knew)}건(누적) → {kp} (라벨링 중 열지 않음)")
        print("  위 수치는 미라벨을 포함한 (하한, 상한) 이며 확정값이 아니다.")
    else:
        # 미라벨이 없으면 남아 있던 빈 증분 시트를 비운다. 오래된 시트로 이중 라벨이 나지 않게 한다.
        sp = out / f"label_sheet_{args.split}_incr.csv"
        if sp.exists() and len(_read_label_sheet(sp)):
            ev.write_sheet(pd.DataFrame(columns=["query_id", "query", "item_id", "title",
                                                 "institution", "selection_year", "program",
                                                 "label", "note"]), sp)
            print(f"[증분 라벨] 대기 항목 없음 — 오래된 빈 시트를 비웠습니다: {sp}")
    return 0


def cmd_prepare_reranker(args) -> int:
    """재정렬기 가중치를 내려받고 manifest 를 남긴다. `search` 는 항상 오프라인이다 (개정안 5.3)."""
    from . import rerank as rr
    root = Path(args.root).resolve()
    cfg = load_config(root / args.config)
    art = root / cfg["paths"]["artifacts"]
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    if args.no_download:
        os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        r = rr.make_reranker(cfg)
    except Exception as e:
        print(f"[중단] 재정렬기 적재 실패: {e}", file=sys.stderr)
        return 2
    top_n = int(cfg.get("rerank", {}).get("top_n", 20))
    man = rr.write_manifest(art / "rerank_manifest.json", r, top_n=top_n,
                            run_mode=cfg["runtime"]["mode"])
    print(f"[재정렬기] {man['model_id']}  rev={man['model_revision']}")
    print(f"  dtype={man['dtype']} device={man['device']} max_tokens={man['max_tokens']} "
          f"top_n={man['top_n']} 적재 {man['load_seconds']}s")
    if man["model_revision"] is None:
        print("  ⚠ revision 을 확인하지 못했습니다. config 의 rerank.revision 에 커밋을 고정하세요.")
    print(f"[출력] {art / 'rerank_manifest.json'}")
    return 0


def cmd_rescore_pool(args) -> int:
    """라벨 시트를 그대로 두고 key 에 점수 컬럼(margin·percentile·s_rr)만 추가한다."""
    import json as _json
    root = Path(args.root).resolve()
    cfg = load_config(root / args.config)
    if not cfg["runtime"].get("allow_network_during_search", False):
        os.environ["HF_HUB_OFFLINE"] = "1"
    out = root / "evaluation"
    key_path = out / f"pool_key_tau_{args.split}.csv"
    if not key_path.exists():
        print(f"[중단] {key_path} 가 없습니다. make-tau-probe 를 먼저 실행하세요.", file=sys.stderr)
        return 2
    key = pd.read_csv(key_path, encoding="utf-8-sig", dtype={"item_id": str, "query_id": str})
    queries = ev.load_queries(out / f"queries_{args.split}.jsonl")
    projects, _base, sem = _load_engines(root, cfg, need_semantic=True)
    if sem is None or sem["run_mode"] == "test_fixture":
        print("[중단] 실모델 인덱스가 필요합니다 (build-index).", file=sys.stderr)
        return 2

    reranker = None
    if args.with_rerank:
        from . import rerank as rr
        try:
            reranker = rr.make_reranker(cfg)
            print(f"[재정렬기] {reranker.model_id} rev={reranker.revision} "
                  f"device={reranker.device} 적재 {reranker.load_s:.1f}s", flush=True)
        except Exception as e:                     # 조용히 넘어가지 않는다
            print(f"[중단] 재정렬기 적재 실패: {e}", file=sys.stderr)
            return 2

    sem_fn = lambda q: sem["index"].scores(sem["embedder"].encode([q])[0])
    rescored, meta = ev.rescore_pool(key, queries, projects, sem_fn, reranker=reranker,
                                     timeout_s=float(args.timeout))
    rescored.to_csv(key_path, index=False, encoding="utf-8-sig", lineterminator="\n")
    meta_path = out / "results" / f"rescore_meta_{args.split}.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(_json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    have = [c for c in ("sem_margin", "sem_percentile", "rerank_logit")
            if rescored[c].notna().any()]
    print(f"[재점수] {len(rescored)}건 · 추가된 점수 컬럼: {', '.join(have)}")
    for q in meta["queries"]:
        print(f"  {q['query_id']}: p99={q['p99']} p99.9={q['p999']} 최대={q['max']}"
              + (f" 재정렬 {q['rerank_seconds']}s" if "rerank_seconds" in q else "")
              + (f"  경고 {q['rerank_warnings']}" if "rerank_warnings" in q else ""))
    print(f"[출력] {key_path}  (라벨 시트는 변경하지 않음)")
    print(f"[출력] {meta_path}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="research_compass")
    ap.add_argument("--root", default=".", help="저장소 루트")
    ap.add_argument("--config", default="config/default.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    dc = sub.add_parser("doctor", help="환경·원본 확보 상태 점검")
    dc.add_argument("--quick", action="store_true",
                    help="torch/faiss 등 무거운 패키지 확인을 건너뜀 (빠름)")
    dc.set_defaults(fn=cmd_doctor)
    sub.add_parser("audit", help="데이터 감사 실행").set_defaults(fn=cmd_audit)
    sub.add_parser("crosswalk", help="D2 ↔ KISTEP 2023판 대조 (신구 crosswalk)").set_defaults(fn=cmd_crosswalk)
    sub.add_parser("verify-scheme", help="D2 기준 분류체계 버전 검증 (P1-B)").set_defaults(fn=cmd_verify_scheme)
    sub.add_parser("prepare", help="ProjectRecord/FieldRecord 정제").set_defaults(fn=cmd_prepare)
    bi = sub.add_parser("build-index", help="임베딩·인덱스 생성")
    bi.add_argument("--offline", action="store_true",
                    help="네트워크 없이 해시 임베더로 파이프라인만 검증 (test_fixture)")
    bi.add_argument("--no-download", action="store_true",
                    help="HF 캐시에 있는 파일만 사용. 없는 파일은 내려받지 않고 실패")
    bi.set_defaults(fn=cmd_build_index)
    se = sub.add_parser("search", help="검색")
    se.add_argument("--query", required=True)
    se.add_argument("--top-k", type=int, default=10)
    se.add_argument("--baseline-only", action="store_true")
    se.add_argument("--exclude-short", action="store_true", help="10자 미만 제목을 검색 대상에서 제외")
    se.add_argument("--stats", action="store_true", help="전체 코퍼스 점수 분포 표시 (tau 검토용)")
    se.set_defaults(fn=cmd_search)
    mp = sub.add_parser("make-eval-pool", help="라벨링 시트 생성 (의미 Top-5 ∪ 어휘 Top-5, 블라인드)")
    mp.add_argument("--split", choices=["dev", "test"], required=True)
    mp.set_defaults(fn=cmd_make_eval_pool)
    evp = sub.add_parser("evaluate", help="라벨 시트로 P@5 계산")
    evp.add_argument("--split", choices=["dev", "test"], required=True)
    evp.add_argument("--sheet", help="라벨 시트 파일명 (기본 label_sheet_{split}.csv)")
    evp.set_defaults(fn=cmd_evaluate)
    tp = sub.add_parser("make-tau-probe", help="tau 보정용 심층 표본 (순위 6~500 + 무작위)")
    tp.add_argument("--split", choices=["dev"], default="dev")
    tp.set_defaults(fn=cmd_make_tau_probe)
    at = sub.add_parser("analyze-tau", help="라벨된 tau 표본으로 정밀도 곡선 계산")
    at.add_argument("--split", choices=["dev"], default="dev")
    at.add_argument("--sheet", help="라벨 시트 파일명 (기본 label_sheet_tau_{split}.csv)")
    at.add_argument("--spaces", help=f"점수 공간 쉼표 구분 (기본 전체: {','.join(ev.SCORE_SPACES)})")
    at.set_defaults(fn=cmd_analyze_tau)
    ec = sub.add_parser("evaluate-conditions", help="조건 A~D' 를 같은 라벨로 채점 (개정안 9.1)")
    ec.add_argument("--split", choices=["dev", "test"], required=True)
    ec.add_argument("--conditions", default="A,B,C,D",
                    help=f"쉼표 구분. 사용 가능: {','.join(ev.CONDITIONS)}")
    ec.add_argument("--k", type=int, default=5)
    ec.add_argument("--perspective", default=ev.DEFAULT_PERSPECTIVE,
                    choices=["full", "method", "target_goal"],
                    help="평가 단위의 탐색 관점 (v2 §17.3). 관점이 다르면 라벨을 재사용하지 않는다")
    ec.add_argument("--used-for-selection", action="store_true",
                    help="이 실행 결과를 보고 설정을 선택했음을 기록 (v2 §17.4)")
    ec.set_defaults(fn=cmd_evaluate_conditions)
    pr = sub.add_parser("prepare-reranker", help="재정렬기 가중치 확보 + manifest 기록")
    pr.add_argument("--no-download", action="store_true", help="캐시에 있는 것만 사용")
    pr.set_defaults(fn=cmd_prepare_reranker)
    rs = sub.add_parser("rescore-pool", help="라벨 시트를 유지한 채 key 에 점수 컬럼 추가 (margin·s_rr)")
    rs.add_argument("--split", choices=["dev"], default="dev")
    rs.add_argument("--with-rerank", action="store_true", help="재정렬기 로짓(s_rr)까지 계산")
    rs.add_argument("--timeout", type=float, default=120.0, help="질의당 재정렬 시간 예산(초)")
    rs.set_defaults(fn=cmd_rescore_pool)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
