"""원본 파일 등록: 해시·인코딩·구분자 확인만 담당한다.

이 모듈은 컬럼의 의미를 추정하지 않는다. (명세 14.1)
"""
from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Snapshot:
    key: str
    dataset_id: str
    title: str
    source_url: str
    file_name: str
    file_path: str
    bytes: int
    sha256: str
    snapshot_id: str
    acquired_at: str
    encoding: str
    encoding_confidence: str
    delimiter: str
    header: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def looks_like_html(raw: bytes) -> bool:
    head = raw[:2048].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<head>" in head


def detect_encoding(raw: bytes, candidates: list[str]) -> tuple[str, str]:
    """후보 인코딩을 순서대로 시도한다. 실패하면 오류를 숨기지 않는다."""
    for enc in candidates:
        try:
            raw.decode(enc)
        except UnicodeDecodeError:
            continue
        # 한글이 전혀 없거나 치환문자가 섞이면 신뢰도를 낮춘다.
        text = raw.decode(enc, errors="replace")
        confidence = "low" if "�" in text else "ok"
        return enc, confidence
    raise UnicodeDecodeError("none", raw, 0, 1, f"후보 인코딩 {candidates} 모두 실패")


def detect_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t|;").delimiter
    except csv.Error:
        return ","


def register(
    path: Path,
    key: str,
    dataset_id: str,
    title: str,
    source_url: str,
    encoding_candidates: list[str],
) -> Snapshot:
    path = Path(path)
    raw = path.read_bytes()
    if looks_like_html(raw):
        raise ValueError(
            f"{path.name}: CSV가 아니라 HTML 문서로 보입니다. "
            "로그인/오류 페이지를 저장했을 가능성이 있습니다. (명세 4.3-2)"
        )
    enc, conf = detect_encoding(raw, encoding_candidates)
    text_head = raw[:65536].decode(enc, errors="replace")
    delim = detect_delimiter(text_head)
    header = next(csv.reader(io.StringIO(text_head), delimiter=delim), [])
    digest = sha256_of(path)
    return Snapshot(
        key=key,
        dataset_id=dataset_id,
        title=title,
        source_url=source_url,
        file_name=path.name,
        file_path=str(path),
        bytes=len(raw),
        sha256=digest,
        snapshot_id=f"{dataset_id}-{digest[:12]}",
        acquired_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        encoding=enc,
        encoding_confidence=conf,
        delimiter=delim,
        header=[h.strip().lstrip("﻿") for h in header],
    )
