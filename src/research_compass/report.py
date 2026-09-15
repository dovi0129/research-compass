"""감사 결과를 data_audit.md 와 capabilities.json 으로 출력한다."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .audit import Finding, STATUS_RANK

ICON = {"ok": "✅", "warn": "⚠️", "blocker": "⛔", "unknown": "❓"}


def render_section(title: str, findings: list[Finding]) -> str:
    lines = [f"### {title}", "", "| 상태 | 점검 | 확인 내용 |", "|---|---|---|"]
    for f in findings:
        detail = f.detail.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {ICON[f.status]} {f.status} | {f.check} | {detail} |")
    lines.append("")
    return "\n".join(lines)


def write_audit_report(
    path: Path,
    snapshots: list[dict],
    sections: dict[str, list[Finding]],
    capabilities: dict,
) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    parts = [
        "# 데이터 감사 보고서 (reports/data_audit.md)",
        "",
        f"> 생성시각(UTC): {now}  ",
        "> 이 보고서는 실제 원본 파일에서 확인된 내용만 기록한다. "
        "확인되지 않은 항목은 `unknown` 으로 남기며 임의의 값으로 채우지 않는다.",
        "",
        "## 1. 원본 스냅샷",
        "",
        "| 키 | 데이터셋 ID | 파일명 | 바이트 | SHA-256 | 인코딩 | 구분자 | 확보시각(UTC) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in snapshots:
        parts.append(
            f"| {s['key']} | {s['dataset_id']} | `{s['file_name']}` | {s['bytes']:,} | "
            f"`{s['sha256'][:16]}…` | {s['encoding']} | `{s['delimiter']}` | {s['acquired_at']} |"
        )
    parts += ["", "원본 등록 페이지:", ""]
    for s in snapshots:
        parts.append(f"- {s['key']} — {s['title']} · {s['source_url']}")
    parts += ["", "실제 헤더:", ""]
    for s in snapshots:
        parts.append(f"- **{s['key']}**: {', '.join('`'+h+'`' for h in s['header'])}")

    parts += ["", "## 2. 점검 결과", ""]
    for title, findings in sections.items():
        parts.append(render_section(title, findings))

    parts += ["## 3. 기능 가용성 판정 (capabilities.json)", "",
              "| 기능 | 상태 | 근거 |", "|---|---|---|"]
    for k, v in capabilities.items():
        parts.append(f"| `{k}` | **{v['status']}** | {v['reason']} |")

    parts += [
        "",
        "## 4. 판정 규칙",
        "",
        "- `verified` — 실제 원본에서 확인되어 사용 가능",
        "- `unverified` — 코드는 준비되었으나 실데이터 근거가 아직 부족",
        "- `disabled` — 원본이 해당 분석을 지원하지 않음. 코드 오류가 아니라 정상적인 기능 제한",
        "",
        "`disabled` 는 오류가 아니다. 서비스는 해당 영역에서 `unavailable` 과 사유를 반환한다.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")


def write_capabilities(path: Path, capabilities: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(capabilities, ensure_ascii=False, indent=2), encoding="utf-8")


def write_crosswalk_report(path: Path, payload: dict) -> None:
    """P1 대조 결과 보고서."""
    r = payload["result"]; g = payload["gate"]; s = payload["snapshots"]
    L = [
        "# P1 — D2 중심분야코드 ↔ 국가과학기술표준분류 대조",
        "",
        f"> 생성시각(UTC): {payload['generated_at']}  ",
        f"> KISTEP 데이터 역할: **{payload['policy']['kistep_role']}** — "
        "NRF 데이터를 대체하지 않는 코드·계층 복원용 보조 공공데이터  ",
        f"> 부재 코드 취급: **`{payload['policy']['absent_code_semantics']}`** — "
        "'선정 0건' 이 아니라 '이 스냅샷에서 관측되지 않음'",
        "",
        "## 1. 대조한 스냅샷",
        "",
        "| 키 | 데이터셋 | 행 | 인코딩 | SHA-256 |",
        "|---|---|---|---|---|",
    ]
    for k, v in s.items():
        L.append(f"| {k} | {v['title']} | — | {v['encoding']} | `{v['sha256'][:16]}…` |")
    L += [
        "",
        f"- D2: {r['d2_rows']}행 / 고유 코드 {r['d2_codes']}개",
        f"- KISTEP: {r['kistep_rows']}행 / 대분류 {r['kistep_major']} · 중분류 {r['kistep_mid']} · 소분류 {r['kistep_minor']}",
        "",
        "## 2. 일치율",
        "",
        "| 지표 | 값 | 게이트 | 판정 |",
        "|---|---|---|---|",
        f"| 코드 정확 일치 (전체) | {r['code_match']}/{r['d2_rows']} = **{r['code_match_rate']:.2%}** | "
        f"≥ {g['overall']['threshold']:.0%} | {'✅ 통과' if g['overall']['pass'] else '⛔ **미달**'} |",
        f"| 코드 정확 일치 (KISTEP 체계 내 한정) | **{r['in_scheme_match_rate']:.2%}** | "
        f"≥ {g['in_scheme_only']['threshold']:.0%} | {'✅ 통과' if g['in_scheme_only']['pass'] else '⛔ 미달'} |",
        f"| ↳ 해당 범위가 D2 에서 차지하는 비중 | {g['in_scheme_only']['coverage_of_d2']:.1%} "
        f"({r['in_scheme_rows']}/{r['d2_rows']}행) | — | — |",
        f"| 명칭 완전 일치 (코드 일치 건 중) | {r['name_exact']}/{r['code_match']} = {r['name_exact_rate']:.2%} | — | — |",
        f"| 명칭 정규화 후 일치 | {r['name_normalized']}/{r['code_match']} = **{r['name_normalized_rate']:.2%}** | — | — |",
        "",
        "## 3. 코드 계층",
        "",
        f"- KISTEP: 대분류 2자리 → 중분류 4자리 → 소분류 6자리 (3계층)",
        f"- D2 중심분야코드: 전부 6자리 `AA9999` 형식 — 소분류 수준 단일",
        f"- **KISTEP 체계에 속하는 D2 접두 ({len(r['in_scheme_prefixes'])}종):** "
        + ", ".join(f"`{p}`" for p in r["in_scheme_prefixes"]),
        f"- **KISTEP 체계에 없는 D2 접두 ({len(r['out_scheme_prefixes'])}종):** "
        + ", ".join(f"`{p}`" for p in r["out_scheme_prefixes"]),
        "",
        f"체계 밖 코드가 **{r['out_scheme_rows']}행**으로 D2 의 "
        f"{r['out_scheme_rows']/r['d2_rows']:.1%} 를 차지한다. "
        "이들은 국가과학기술표준분류가 아닌 다른 분류체계로 보이며, 참조 코드표가 없다.",
        "",
        "## 4. unobserved 판정",
        "",
        f"- 범위: D2 가 실제로 사용하는 KISTEP 대분류 {len(r['in_scheme_prefixes'])}종의 하위 소분류 "
        f"**{r['scope_minor_total']}개**",
        f"- 그중 D2 에서 관측된 코드: **{r['code_match']}개**",
        f"- **unobserved: {r['unobserved_in_scope']}개**",
        "",
        "> `unobserved` 는 '선정 0건' 이 아니다. 이 스냅샷의 수록 범위에서 관측되지 않았다는 뜻이며, "
        "실제로 선정 실적이 없는지 / 수록 대상이 아닌지 구분할 수 없다.",
        "",
        f"체계 밖 {r['out_scheme_rows']}행에 대해서는 참조 코드표가 없으므로 **unobserved 를 산정하지 않는다.**",
        "",
    ]
    if r["name_diff_samples"]:
        L += ["## 5. 명칭이 다른 건 (코드는 일치)", "",
              "| 코드 | D2 명칭 | KISTEP 명칭 |", "|---|---|---|"]
        for d in r["name_diff_samples"]:
            L.append(f"| `{d['code']}` | {d['d2_name']} | {d['kistep_name']} |")
        L.append("")
    if r["unmatched_in_scheme"]:
        L += ["## 6. 체계 내인데 코드가 없는 건", "",
              "| 코드 | D2 명칭 |", "|---|---|"]
        for d in r["unmatched_in_scheme"]:
            L.append(f"| `{d['code']}` | {d['d2_name']} |")
        L.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


def write_version_report(path: Path, payload: dict) -> None:
    """분류체계 버전 검증 보고서 (P1-B)."""
    v = payload["verify"]; pop = payload["population"]; old = payload.get("v2023_reference", {})
    L = [
        "# P1-B — D2 기준 분류체계 버전 검증",
        "",
        f"> 생성시각(UTC): {payload['generated_at']}  ",
        "> 목적: D2 `중심분야코드` 가 어느 판의 국가과학기술표준분류체계를 따르는지 판별  ",
        "> 정책: 부재 코드는 `unobserved`. `선정 0건` 으로 해석하지 않는다.",
        "",
        "## 1. 판정 결과",
        "",
        f"**D2 의 기준 분류체계 = {v['version_label']}**",
        "",
        "| 대조 수준 | 일치 | 비율 |",
        "|---|---|---|",
        f"| 대분류 (2자리) | {v['major_match']}/{v['d2_rows']} | **{v['major_rate']:.2%}** |",
        f"| 중분류 (4자리, exact) | {v['mid_match']}/{v['d2_rows']} | **{v['mid_rate']:.2%}** |",
        f"| 소분류명 (엄격 정규화) | {v['name_strict_match']}/{v['d2_rows']} | {v['name_strict_rate']:.2%} |",
        f"| 소분류명 (동일 중분류 내 포함관계 허용) | {v['name_contained_match']}/{v['d2_rows']} | **{v['name_contained_rate']:.2%}** |",
        f"| 코드·명칭 동시 정합 | {v['code_name_consistent']}/{v['d2_rows']} | {v['code_name_consistent']/v['d2_rows']:.2%} |",
        f"| 코드·명칭 충돌 | {v['code_name_conflict']}건 | — |",
        "",
    ]
    if old:
        L += [
            "### 2023년 개정판과의 대조 (참고)",
            "",
            f"- 소분류 6자리 정확 일치: **{old['minor_match']}/{old['rows']} = {old['minor_rate']:.2%}**",
            f"- 2023판에 없는 D2 대분류 접두: {', '.join('`'+p+'`' for p in old['missing_majors'])}",
            "",
            "2023년 개정에서 인문사회 대분류가 `HF`/`HG`/`HH` 로 재편되면서 "
            "`HA`~`HE`, `SA`~`SI` 코드가 사라졌다. 12.81% 라는 낮은 일치율은 "
            "**분류체계 불일치가 아니라 버전 불일치** 때문이다.",
            "",
        ]
    L += [
        "## 2. 미설명 항목",
        "",
        f"- 대분류 미매칭: {len(v['unmatched_majors'])}종 {v['unmatched_majors'] or '없음'}",
        f"- 중분류 미매칭: {len(v['unmatched_mids'])}종 {v['unmatched_mids'] or '없음'}",
        f"- 명칭으로 설명되지 않는 건: **{len(v['unexplained_names'])}건**",
        "",
    ]
    if v["unexplained_names"]:
        L += ["| 코드 | D2 명칭 | 해당 중분류의 후보 |", "|---|---|---|"]
        for d in v["unexplained_names"][:30]:
            L.append(f"| `{d['code']}` | {d['d2_name']} | {', '.join(d['mid_candidates'])} |")
        L.append("")
    L += [
        "## 3. 모집단(unobserved) 산정 상태",
        "",
        f"**상태: `{pop['status']}`**",
        "",
        f"- 사유: {pop['reason']}",
        f"- 관측된 소분류 코드: {pop['observed_codes']}개 (중분류 {pop['observed_mid_codes']}종)",
        f"- 참조표의 해당 범위 소분류명: {pop['reference_minor_names_in_scope']}개",
        f"- 명칭 기준 추정치(참고용): {pop['name_level_estimate_only']}개",
        "",
        f"> {pop['note']}",
        "",
        "### 철회된 이전 결과",
        "",
        "이전 보고서(`p1_crosswalk.md`)의 **`unobserved 1,608개`** 는 "
        "**2023년 개정판을 모집단으로 삼아 계산한 값이므로 철회한다.** "
        "D2 의 기준 체계는 2018년판이며, 2023판은 모집단이 될 수 없다.",
        "",
        "확정 결과로 쓸 수 있게 되는 조건: 소분류 6자리 코드가 포함된 2018년 체계 코드표 확보.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")
