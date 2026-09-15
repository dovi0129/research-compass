"""Research Compass — 연구탐색 작업공간 (Streamlit 단일 페이지, 명세 v2 §13).

실행
    python -m streamlit run app.py                      # .streamlit/config.toml 이 127.0.0.1 바인딩·텔레메트리 차단
    python -m streamlit run app.py -- --config config/server.yaml
    python -m streamlit run app.py -- --ux l             # 사용자 작업 비교용 목록 전용 조건 (UX-L)

이 파일은 **상태 입력·표시**만 한다. 규칙은 research_compass.workspace / search / analytics / comparison /
nextactions / memo 의 시험된 함수가 수행한다 (v2 §15.3). 새 HTTP API·DB·프런트엔드 프레임워크를 만들지 않는다 (v2 §5).
그래프는 Streamlit 동봉 Altair 로 그린다 — 외부 CDN·추가 의존성 없음.

화면 구조 (D-029 재설계 · D-035 연구 작업공간 톤) — 위에서 아래로
    1 머리말·화면 모드   2 연구주제 입력   3 [탐색 관점] [현재 검색문] [탐색] 한 줄 (+ 탐색 요소 조정·검색 범위 접힘)
    4 제목이 유사한 과제 70% + 비교함 30%   5 선택한 과제 비교(2건 이상일 때 표: 탐색 관점·검색문·당시 순위·선정연도·사업·기관·원본 위치)
    6 탐색 메모(자유 메모 → 저장/백업)   7 데이터 및 검색 정보 (접힘: 관련 연구분야 · 데이터 범위와 한계 · 검색 상세 정보 · 기능 상태)
    한 페이지 (D-038): 띠 → 머리말 → [검색 상자 70% | 오른쪽 30%] → (왼쪽 열 안: 최근 탐색 · 결과) → 선택한 과제 비교 → 탐색 메모 →
    데이터 및 검색 정보 → 수치 띠 → 바닥글 → 화면 모드. **검색 전후 골격이 같고** 결과만 검색 상자 아래에 붙는다 (첫 화면 → 결과 화면 전환 없음).
    검색 상자 = 검색 방식 [연구주제 한 문장 | 요소별 탐색 | 연구 요약 붙여넣기 | 연구분야로 찾기] + 검색칸(첫 검색 뒤 = 탐색 관점 · 현재 검색문 · 탐색) + 검색 범위 한 줄.
    오른쪽 = 검색 전 수록 데이터 구성 / 검색 뒤 비교함 + 표시 중인 구성. 설명문은 두지 않는다 (D-036). 검토·인용 UI·다음 탐색 절은 D-030·D-031 로 화면에서 뺐다.
    시각 원칙 (D-035): 평면 표면 · 얇은 테두리 · 6~8px 반경 · 강조색은 주요 동작과 선택에만 · 배경 그라데이션·유리·모션 없음.

표시 원칙 (v2 §7.3·§12·§13.4·§21.4, D-026·D-029 사용자 검토)
- 결과는 `제목이 유사한 과제` 목록이다. 직접 관련 과제로 자동 분류하지 않는다.
- 점수는 `의미 유사도`·`재정렬 점수` 로만 부르고 확률·정확도로 바꾸지 않는다. 카드 본문에는 의미 유사도만 두고,
  재정렬 점수·백분위·두 순위(최종 표시 순위 / 1차 의미검색 위치)는 `검색 근거 보기` 에서 서로 다른 값으로 밝힌다.
- 모든 집계에 범위(scope)를 붙인다. 추세·증감 문구를 만들지 않는다.
- 사용자에게 보이는 문장에는 명세 절 번호·결정 번호·모듈명·엔진 코드명을 쓰지 않는다. 그런 정보는 `기능 및 검증 상태` 의
  개발자용 표에만 둔다.
- 원문·사용자 텍스트는 전부 escape 해서 그린다. 실행 가능한 HTML 을 만들지 않는다.
- test_fixture / saved_replay 를 실제 모델 결과처럼 보이지 않게 한다.
- 라이트/다크 두 팔레트는 같은 정보 위계를 가진다. 색은 의미가 있을 때만 쓴다 (강조=선택·주요 동작, 노랑=확인 필요,
  초록=가능, 회색=불가·보조). 점수를 초록/빨강으로 칠하지 않는다.
"""
from __future__ import annotations

import html
import json
import math
import os
import re
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def _config_path() -> Path:
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--config" and i + 1 < len(args):
            return ROOT / args[i + 1]
        if a.startswith("--config="):
            return ROOT / a.split("=", 1)[1]
    return ROOT / os.environ.get("RESEARCH_COMPASS_CONFIG", "config/default.yaml")


CFG_PATH = _config_path()
CFG: dict = yaml.safe_load(CFG_PATH.read_text(encoding="utf-8"))
if not CFG.get("runtime", {}).get("allow_network_during_search", False):
    os.environ.setdefault("HF_HUB_OFFLINE", "1")         # 검색 중 외부 호출 금지 (v2 §21.3)
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import altair as alt            # noqa: E402  (Streamlit 동봉)
import pandas as pd             # noqa: E402
import streamlit as st          # noqa: E402
from streamlit import config as st_config      # noqa: E402

from datetime import datetime, timezone                # noqa: E402

from research_compass import analytics as an          # noqa: E402
from research_compass import capabilities as capm     # noqa: E402
from research_compass import comparison as cmp        # noqa: E402
from research_compass import memo as memo_mod         # noqa: E402
from research_compass import nextactions as na        # noqa: E402
from research_compass import prepare as prep          # noqa: E402
from research_compass import search as svc            # noqa: E402
from research_compass import workspace as wsm         # noqa: E402

# ---------------------------------------------------------------------------
# 설계값 (v2 §7.2 · config retrieval_policy)
# ---------------------------------------------------------------------------
_POLICY = CFG.get("retrieval_policy", {})
DEFAULT_TOP_K = int(_POLICY.get("workspace_default_top_k", 5))
MAX_TOP_K = int(_POLICY.get("workspace_max_top_k", 10))
REQUESTED_ENGINE = str(_POLICY.get("default_engine") or "")
FIELD_TOP_N = 8
TEXT_SUMMARY_MAX = 10          # 이 건수 이하의 구성은 차트 대신 한 줄 글로 (D-026 #10)
RECENT_RUNS = 5                # 최근 탐색 칩 개수. 나머지는 '전체 이력 보기' (D-029)
BASKET_RECOMMENDED = 3         # 비교함 권장 건수 (UI 안내). 상한은 workspace.MAX_SELECTED 그대로

MODE_LABELS = {"local_live": ("실제 모델", "ok"),
               "test_fixture": ("테스트 임베더 — 실제 품질 아님", "warn"),
               "saved_replay": ("저장 결과 재생 — 새 질의 불가", "warn"),
               "unknown": ("모드 미상", "warn")}
STATUS_LABELS = {"available": ("가능", "ok"), "limited": ("일부만", "info"),
                 "unavailable": ("불가", "off"), "unverified": ("미검증", "warn")}
FEATURE_LABELS = {
    "ranked_project_search": "가까운 과제 검색", "perspective_search": "관점별 탐색",
    "comparison_workspace": "비교함", "title_evidence_review": "제목 근거 비교",
    "exploration_memo": "탐색 메모 내보내기", "field_name_search": "분야명 찾아보기",
    "field_count_display": "분야별 선정횟수 비교", "scoped_distribution": "범위를 밝힌 구성 통계",
    "calibrated_relevant_corpus": "'관련 과제 N건' 집계", "comparable_trend": "연도별 추세",
    "project_field_join": "과제-분야 공식 연결", "opportunity_candidates": "연구기회 후보 제안"}
STAGES = (("s1_semantic_s", "1) 의미 검색 (질의 임베딩 + 최근접 탐색)"),
          ("s1_lexical_s", "2) 어휘 점수 (기록용)"),
          ("s2_fusion_s", "3) 후보 구성"),
          ("s3_relative_s", "4) 상대 점수"),
          ("s4_rerank_s", "5) 재정렬 (cross-encoder)"))
SOURCE_URL_D1 = next((str(x.get("source_url")) for x in CFG.get("sources", []) if x.get("key") == "D1"), None)

# 관점 — 짧은 이름(선택 버튼)·한 줄 뜻. 긴 이름은 workspace.PERSPECTIVE_LABELS (이력·메모·상태줄에 그대로)
PERSP_SHORT = {"full": "전체 연구주제", "method": "방법·접근", "target_goal": "대상·문제"}
ROLE_HINTS = {"target_context": "예: 노인", "method_approach": "예: 디지털 치료제", "goal_question": "예: 우울증 예방"}

# 화면 조건 (v2 §17.6 사용자 작업 비교). 기본은 작업공간(UX-W)이고, 목록 전용 비교 조건은
#     python -m streamlit run app.py -- --ux l        (또는 RESEARCH_COMPASS_UX=l)
# 두 조건은 **같은 엔진·같은 원자료·같은 표시 건수**를 쓴다. 목록 조건에서도 검색문 직접 수정과
# 자유 메모를 제공한다 — 비현실적으로 약한 비교 대상을 만들지 않는다.
UX_ONLY_W = ("perspective_search", "comparison_workspace", "title_evidence_review", "exploration_memo")


def _argv_ux() -> str:
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--ux" and i + 1 < len(args):
            return args[i + 1]
        if a.startswith("--ux="):
            return a.split("=", 1)[1]
    return ""


UX_DEFAULT = (_argv_ux() or os.environ.get("RESEARCH_COMPASS_UX") or "w").strip().lower()


def ux_mode() -> str:
    """`l` = 목록 전용(UX-L), `w` = 작업공간(UX-W). 시험은 session_state 로 덮어쓴다."""
    v = str(st.session_state.get("_ux_override") or UX_DEFAULT).strip().lower()
    return "l" if v in ("l", "list", "ux-l", "ux_l") else "w"


# ---------------------------------------------------------------------------
# 테마 — 라이트/다크 두 팔레트 (D-029). 처음에는 운영체제 설정을 따르고(.streamlit/config.toml 의
# [theme.light]/[theme.dark]), 사용자가 머리말의 토글로 바꾸면 그 선택을 세션 동안 유지한다.
# ---------------------------------------------------------------------------
PALETTES = {
    # D-036 행정 네이비. 라이트: 연회색 배경 + 흰 표면 + 짙은 슬레이트 글자 + 짙은 파랑 강조.
    # 다크: 채도 낮은 슬레이트 배경 + 스틸 블루 강조 — 보라 기운을 넣지 않는다 (교수 검토: 검정·보라 조합 기각).
    # 보조 글자(muted)는 배경 #F3F5F7 위에서 7:1 이상 — 5.2:1(#5A6675)이던 때 작은 글자가 옅게 보였다 (사용자 검토, 2026-09-14)
    "light": dict(bg="#F3F5F7", surface="#FFFFFF", surface2="#EAEEF2", ink="#1A2433", muted="#465160",
                  line="#D9DEE4", line_strong="#BFC7D1", accent="#1F4E8C", accent_deep="#163A69", accent_soft="#E4ECF6", on_accent="#FFFFFF",
                  focus="rgba(31,78,140,.25)", warn="#8A5A00", warn_soft="#FBF1DA", ok="#1B6E3A", ok_soft="#E3F3E8",
                  off="#5B6472", off_soft="#ECEFF2", info="#1F4E8C", info_soft="#E4ECF6", mark="#FFE9A8",
                  track="#E1E6EB", chart_bar="#CFD8E3", chart_muted="#4B5563", chart_bar2="#5B7DB1", chart_bar3="#C5CFDA",
                  btn="#1F4E8C", on_btn="#FFFFFF", band="#1F4E8C", on_band="#E8EEF7"),
    "dark": dict(bg="#1E242C", surface="#262D36", surface2="#2E3640", ink="#E4E8ED", muted="#A0AAB6",
                 line="#3A434E", line_strong="#4A5460", accent="#7FA3D1", accent_deep="#5F87B8", accent_soft="#2A3644", on_accent="#1E242C",
                 focus="rgba(127,163,209,.30)", warn="#E4BC5F", warn_soft="#302A1A", ok="#6BD08F", ok_soft="#17301F",
                 off="#8B95A5", off_soft="#2E3640", info="#9DBBE0", info_soft="#2A3644", mark="#6B5A1A",
                 track="#3A434E", chart_bar="#3A434E", chart_muted="#A0AAB6", chart_bar2="#5F87B8", chart_bar3="#4A5460",
                 # 기본 동작 버튼만 채도를 올린 파랑 — 선택 상태(accent)와 무게가 같아 '비활성' 으로 읽히던 것을 구분 (Sonnet 리뷰 6)
                 btn="#3D77C9", on_btn="#FFFFFF", band="#161B23", on_band="#A0AAB6"),
}
# Streamlit 자체 위젯 팔레트 (config.toml 의 [theme.light]/[theme.dark] 와 같은 값). 토글이 프런트엔드에 보낸다.
ST_THEMES = {
    "light": {"primaryColor": "#1F4E8C", "backgroundColor": "#F3F5F7", "secondaryBackgroundColor": "#FFFFFF",
              "textColor": "#1A2433", "borderColor": "#D9DEE4", "linkColor": "#1F4E8C",
              "codeBackgroundColor": "#EAEEF2"},
    "dark": {"primaryColor": "#7FA3D1", "backgroundColor": "#1E242C", "secondaryBackgroundColor": "#262D36",
             "textColor": "#E4E8ED", "borderColor": "#3A434E", "linkColor": "#9DBBE0",
             "codeBackgroundColor": "#2E3640"},
}
ST_THEME_COMMON = {"bodyFont": "'Pretendard Variable', Pretendard, 'Apple SD Gothic Neo', 'Malgun Gothic', system-ui, sans-serif",
                   "headingFont": "'Pretendard Variable', Pretendard, 'Apple SD Gothic Neo', 'Malgun Gothic', system-ui, sans-serif",
                   "baseRadius": "6px", "showWidgetBorder": True}
# 작은 컴퍼스 마크 — 단색(currentColor). 상단 브랜드 버튼의 배경 이미지로 쓸 때는 build_css 가 강조색을 채운다.
LOGO_SVG = ('<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
            '<circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.5"/>'
            '<path d="M14.8 9.2 12.9 13.9 9.2 14.8 11.1 10.1z" fill="currentColor"/></svg>')
THEME_OPTS = ("system", "light", "dark")
THEME_LABELS = {"system": "시스템", "light": "라이트", "dark": "다크"}
THEME_ICONS = {"system": ":material/contrast:", "light": ":material/light_mode:", "dark": ":material/dark_mode:"}


def theme_now() -> str:
    """지금 화면 팔레트. 토글 선택이 있으면 그것, 없으면 브라우저가 알려준 테마(운영체제 설정)."""
    c = st.session_state.get("theme_choice", "system")
    if c in ("light", "dark"):
        return c
    try:
        t = st.context.theme.type
    except Exception:                                      # 시험 환경(AppTest)·구버전
        t = None
    return "dark" if t == "dark" else "light"


def _css_vars(p: dict) -> str:
    return ";".join(f"--{k.replace('_', '-')}:{v}" for k, v in p.items())


def _logo_uri(p: dict) -> str:
    logo = LOGO_SVG.replace("currentColor", p["accent"])
    return "data:image/svg+xml;utf8," + logo.replace("#", "%23").replace('"', "'").replace("<", "%3C").replace(">", "%3E")


def build_css(p: dict, follow_os: bool = False) -> str:
    """팔레트 → CSS. `follow_os` 면(화면 모드 = 시스템) 라이트를 기본으로 두고 `prefers-color-scheme: dark` 에서 다크 변수를 덧씌운다.

    시스템 모드에서 팔레트를 `st.context.theme.type` 으로 고르면 **한 실행 늦게** 바뀌어, 토글을 라이트→시스템으로 돌릴 때 우리 CSS 는 라이트인데
    Streamlit 위젯은 다크인 반쪽 화면이 한 번 그려졌다(헤드리스 재현, 2026-09-14). CSS 가 직접 운영체제 설정을 보면 그 어긋남이 없다."""
    css = ":root{" + _css_vars(p) + "}" + CSS.replace("%LOGO%", _logo_uri(p))
    if follow_os:
        d = PALETTES["dark"]
        css += ("@media (prefers-color-scheme: dark){:root{" + _css_vars(d) + "}"
                '.st-key-rc_home button{background-image:url("' + _logo_uri(d) + '") !important}}')
    return css


CSS = """
/* ============ 기본: 폭·배경·타이포 ============ */
.block-container, [data-testid="stMainBlockContainer"] { max-width: 1440px; padding: .9rem 2rem 3rem; margin: 0 auto; }
@media (max-width: 900px) { .block-container, [data-testid="stMainBlockContainer"] { padding: .8rem 1rem 2.5rem; } }
.stApp { background: var(--bg); }
[data-testid="stHeader"] { background: transparent; }
[data-testid="InputInstructions"] { display: none; }
.stApp p, .stApp li, .stApp span, .stApp div, .stApp label, .stApp summary, .stApp td, .stApp th, .stApp button {
  word-break: keep-all; overflow-wrap: break-word; }
.stApp code, .stApp .rc-mono, .stApp .rc-id { overflow-wrap: anywhere; word-break: break-all; }
.stApp p { line-height: 1.58; }
.stApp :is(p, span, div, label, summary, td, th, button, input, textarea, h1, h2, h3, li, a):not([data-testid="stIconMaterial"]):not(.material-symbols-rounded):not(code):not(pre) {
  font-family: 'Pretendard Variable', Pretendard, 'Apple SD Gothic Neo', 'Malgun Gothic', system-ui, sans-serif; }
.stApp code, .stApp pre, .stApp kbd { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
hr { margin: 1.25rem 0 !important; border: 0 !important; height: 1px; background: var(--line) !important; }
@media (max-width: 1000px) {
  /* 구조: .st-key-X(stVerticalBlock) > stLayoutWrapper > stHorizontalBlock > stColumn */
  .st-key-rc_topbar > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
  .st-key-rc_page > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
  .st-key-rc_brand > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
  .st-key-rc_persp > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
  .st-key-rc_main > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
  .st-key-rc_main_anim > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
    flex: 1 1 100% !important; min-width: 100% !important; }
  .st-key-rc_theme_toggle { justify-content: flex-start; }
  [class*="st-key-rc_card_"] [data-testid="stColumn"] { flex: 1 1 auto !important; min-width: 7rem !important; }
  .st-key-rc_right { position: static; }
}
[data-testid="stBaseButton-primary"] p, [data-testid="stBaseButton-secondary"] p { white-space: nowrap; overflow: visible; text-overflow: clip; }
[data-testid="stColumn"] { min-width: 0; }
@media (prefers-reduced-motion: reduce) { .stApp *, .stApp *::before, .stApp *::after { animation: none !important; transition: none !important; } }

/* ============ Streamlit 위젯 ============ */
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="textarea"], [data-baseweb="select"] > div { border-radius: 6px !important; }
[data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within { box-shadow: 0 0 0 3px var(--focus); }
/* 폼 제출 버튼은 testid 가 `stBaseButton-primaryFormSubmit` 라 별도로 잡아야 한다 — 빠지면 config 의 primaryColor(다크에서 옅은 파랑)로 그려진다 */
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] { background: var(--btn) !important; border: 1px solid var(--btn) !important;
  color: var(--on-btn) !important; font-weight: 600; border-radius: 6px !important; box-shadow: none !important; }
[data-testid="stBaseButton-primary"] p, [data-testid="stBaseButton-primaryFormSubmit"] p { color: var(--on-btn) !important; }
[data-testid="stBaseButton-primaryFormSubmit"]:hover { background: var(--accent-deep) !important; border-color: var(--accent-deep) !important; }
[data-testid="stBaseButton-primary"]:hover { background: var(--accent-deep) !important; border-color: var(--accent-deep) !important; }
[data-testid="stBaseButton-secondary"] { border-radius: 6px !important; border: 1px solid var(--line-strong) !important; background: var(--surface) !important;
  color: var(--ink) !important; box-shadow: none !important; }
[data-testid="stBaseButton-secondary"]:hover:not(:disabled) { border-color: var(--accent) !important; color: var(--accent) !important; }
[data-testid="stBaseButton-secondary"]:disabled { opacity: .55; }
[data-testid="stBaseButton-primary"]:focus-visible, [data-testid="stBaseButton-secondary"]:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
/* 세그먼트·칩: 각진 연결형 */
[data-testid="stButtonGroup"] { flex-wrap: wrap; gap: 0; overflow: visible; row-gap: .3rem; }
[data-testid="stButtonGroup"] button { border-radius: 0 !important; padding: .3rem .8rem !important; margin: 0 0 0 -1px !important;
  border: 1px solid var(--line-strong) !important; background: var(--surface) !important; color: var(--muted) !important; box-shadow: none !important; }
[data-testid="stButtonGroup"] button:first-child { border-radius: 6px 0 0 6px !important; margin-left: 0 !important; }
[data-testid="stButtonGroup"] button:last-child { border-radius: 0 6px 6px 0 !important; }
[data-testid="stButtonGroup"] button:only-child { border-radius: 6px !important; }
[data-testid="stButtonGroup"] button p { white-space: nowrap; overflow: visible; text-overflow: clip; font-size: .86rem; }
[data-testid="stButtonGroup"] button:hover { color: var(--ink) !important; background: var(--surface2) !important; }
[data-testid="stButtonGroup"] button[aria-checked="true"], [data-testid="stButtonGroup"] button[aria-pressed="true"],
[data-testid="stButtonGroup"] button[aria-selected="true"] { background: var(--accent-soft) !important; color: var(--accent) !important;
  border-color: var(--accent) !important; font-weight: 600; position: relative; z-index: 1; }
[data-testid="stExpander"] details { border: 0 !important; background: transparent; }
[data-testid="stExpander"] summary { padding-left: 0; border-radius: 6px; }
[data-testid="stExpander"] summary:hover { color: var(--accent); }
[data-testid="stExpander"] summary p { font-weight: 600; font-size: .9rem; }
[data-testid="stPopover"] > div, [data-baseweb="popover"] > div { border-radius: 8px !important; }
/* 테두리 컨테이너 = 카드·패널. 1.63 에서는 테두리가 stVerticalBlock 자체에 있고 st-key-* 도 그 블록에 붙는다 */
[data-testid="stVerticalBlock"][class*="st-key-rc_card_"], [data-testid="stVerticalBlock"].st-key-rc_basket,
[data-testid="stVerticalBlock"].st-key-rc_side, [data-testid="stVerticalBlock"].st-key-rc_searchbox,
[data-testid="stVerticalBlock"].st-key-rc_overview {
  border: 1px solid var(--line) !important; border-radius: 8px !important; background: var(--surface); box-shadow: none !important;
  padding: .85rem 1rem .75rem !important; }
.st-key-rc_theme_bridge { height: 0 !important; overflow: hidden; margin: 0 !important; padding: 0 !important; }
/* st.caption 은 테마 글자색을 60% 로 흐리게 그린다 — 우리 보조 글자색(대비 7:1)으로 통일 */
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: var(--muted) !important; }
[data-testid="stWidgetLabel"] p { color: var(--ink); }

/* ============ 첫 화면 — 검색 방식·범위·수치 띠·바닥글 (D-036: 설명문 없이 조작 수단만) ============ */
.st-key-rc_page { max-width: 1320px; }
.rc-landing { padding: 0; }
/* 머리말 = 로고 단추(기본 화면으로) + 부제. 로고 단추는 상단 브랜드 단추 규칙(.st-key-rc_home)을 크게 쓴다 */
.st-key-rc_brand { margin: .2rem 0 .7rem; }
.st-key-rc_brand .st-key-rc_home button { padding-left: 2.5rem !important; background-size: 1.7rem 1.7rem !important; background-position: .15rem center !important; }
.st-key-rc_brand .st-key-rc_home button, .st-key-rc_brand .st-key-rc_home button p { font-size: 1.5rem !important; letter-spacing: -0.02em; }
.st-key-rc_brand .rc-landing .sub { display: inline-block; }
/* 검색 조건은 상자 하나로 묶어 '양식' 으로 읽히게, 오른쪽은 수록 데이터 구성 (Sonnet 리뷰 1·2·8) */
[data-testid="stVerticalBlock"].st-key-rc_searchbox { padding: 1rem 1.1rem .9rem !important; }
[data-testid="stVerticalBlock"].st-key-rc_overview { padding: .9rem 1.1rem 1rem !important; }
.st-key-rc_overview .rc-h { margin-bottom: .2rem; }
.st-key-rc_overview [data-testid="stCaptionContainer"] p { margin: .2rem 0 0; font-size: .78rem; }
.rc-landing .brandline { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; }
.rc-mark { display: inline-flex; width: 28px; height: 28px; align-items: center; justify-content: center; color: var(--accent);
  border: 1px solid var(--line-strong); border-radius: 6px; background: var(--surface); flex: 0 0 auto; }
.rc-mark svg { width: 17px; height: 17px; }
.stApp .rc-landing h1, [data-testid="stMarkdownContainer"] .rc-landing h1 { font-size: 1.55rem !important; font-weight: 700 !important;
  letter-spacing: -0.02em; margin: 0 !important; padding: 0 !important; line-height: 1.2 !important; color: var(--ink); }
.rc-landing .sub { color: var(--muted); font-size: .95rem; padding-left: .6rem; border-left: 1px solid var(--line-strong); line-height: 1.25; }
.st-key-rc_mode { margin: .1rem 0 .55rem; }
.st-key-rc_searchbox input[type="text"] { font-size: 1rem; height: 2.7rem; }   /* radio 의 input 에 닿으면 관점 선택이 빈 칸으로 그려진다 — type 한정 */
.st-key-rc_searchbox [data-testid="stFormSubmitButton"] button,
.st-key-rc_searchbox .st-key-rc_persp [data-testid="stBaseButton-primary"] { height: 2.7rem; }
.st-key-rc_searchbox textarea { font-size: .95rem; line-height: 1.55; }
.st-key-rc_results { margin-top: 1rem; }
.st-key-rc_filters { margin-top: .1rem; }
.st-key-rc_filters [data-testid="stWidgetLabel"] p { font-size: .76rem; color: var(--muted); font-weight: 600; letter-spacing: .02em; }
.st-key-rc_filters [data-baseweb="select"] > div { min-height: 2.2rem; font-size: .88rem; }
.st-key-rc_filters [data-testid="stCheckbox"] p { font-size: .86rem; }
.rc-stats { display: flex; flex-wrap: wrap; align-items: stretch; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line);
  margin: 1.1rem 0 .3rem; }
.rc-stats > div { display: flex; flex-direction: column; gap: .1rem; padding: .6rem 1.2rem .55rem 0; margin-right: 1.2rem;
  border-right: 1px solid var(--line); }
.rc-stats > div.last { border-right: 0; }
.rc-stats b { font-size: 1.15rem; font-weight: 650; color: var(--ink); font-variant-numeric: tabular-nums; letter-spacing: -0.01em; line-height: 1.2; }
.rc-stats span { font-size: .74rem; color: var(--muted); letter-spacing: .02em; }
.rc-stats .rc-chip { align-self: center; margin-left: auto; }
.rc-foot { color: var(--muted); font-size: .76rem; line-height: 1.7; border-top: 1px solid var(--line); margin-top: 1.1rem; padding-top: .6rem; }
.rc-brand { display: flex; align-items: center; gap: .55rem; }
.stApp .rc-brand h1, [data-testid="stMarkdownContainer"] .rc-brand h1 { font-size: 1.12rem !important; font-weight: 700 !important; letter-spacing: -0.015em;
  margin: 0 !important; padding: 0 !important; color: var(--ink); line-height: 1.2 !important; white-space: nowrap; }
.rc-topic { color: var(--ink); font-size: .92rem; line-height: 1.4; display: flex; gap: .5rem; align-items: baseline; }
.rc-topic .lab { color: var(--muted); font-size: .74rem; font-weight: 600; letter-spacing: .04em; flex: 0 0 auto; }
/* 화면 모드 — 페이지 맨 아래, 버튼이 아니라 작은 글자 (사용자 검토 2026-09-14). 선택된 것만 글자색+밑줄 */
.st-key-rc_theme_toggle { display: flex; align-items: center; gap: .6rem; margin-top: .4rem; }
.st-key-rc_theme_toggle .rc-mode-lab { color: var(--muted); font-size: .74rem; letter-spacing: .02em; white-space: nowrap; }
.st-key-rc_theme_toggle [data-testid="stButtonGroup"] { gap: .1rem; }
.st-key-rc_theme_toggle [data-testid="stButtonGroup"] button,
.st-key-rc_theme_toggle [data-testid="stButtonGroup"] button:first-child,
.st-key-rc_theme_toggle [data-testid="stButtonGroup"] button:last-child { border: 0 !important; background: transparent !important;
  padding: .1rem .35rem !important; margin: 0 !important; border-radius: 3px !important; min-height: 0; }
.st-key-rc_theme_toggle [data-testid="stButtonGroup"] button p { font-size: .74rem; color: var(--muted); }
.st-key-rc_theme_toggle [data-testid="stButtonGroup"] button:hover { background: var(--surface2) !important; }
.st-key-rc_theme_toggle [data-testid="stButtonGroup"] button[aria-checked="true"], .st-key-rc_theme_toggle [data-testid="stButtonGroup"] button[aria-pressed="true"],
.st-key-rc_theme_toggle [data-testid="stButtonGroup"] button[aria-selected="true"] { background: transparent !important; border-color: transparent !important; }
.st-key-rc_theme_toggle [data-testid="stButtonGroup"] button[aria-checked="true"] p, .st-key-rc_theme_toggle [data-testid="stButtonGroup"] button[aria-pressed="true"] p,
.st-key-rc_theme_toggle [data-testid="stButtonGroup"] button[aria-selected="true"] p { color: var(--ink); font-weight: 600; text-decoration: underline; text-underline-offset: 3px; }
/* 상단 식별 띠 — 공공 포털의 얇은 기관 줄. 장식이 아니라 출처·성격을 밝히는 자리 */
.rc-band { background: var(--band); color: var(--on-band); font-size: .74rem; letter-spacing: .01em; padding: .38rem .9rem; border-radius: 0 0 6px 6px;
  display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap; margin: -.9rem 0 .9rem; }
.rc-band b { font-weight: 600; color: var(--on-band); }

/* ============ 상단 브랜드 버튼(홈) ============ */
.st-key-rc_home button { padding: .25rem .5rem .25rem 2.1rem !important; background: url("%LOGO%") no-repeat .3rem center / 1.3rem 1.3rem !important;
  border: 0 !important; box-shadow: none !important; white-space: nowrap; min-height: 2.2rem; }
.st-key-rc_home button, .st-key-rc_home button p, .st-key-rc_home button span, .st-key-rc_home button div {
  font-weight: 700 !important; font-size: 1.05rem !important; letter-spacing: -0.015em; color: var(--ink) !important; }
.st-key-rc_home button:hover, .st-key-rc_home button:hover p { color: var(--accent) !important; }
.st-key-rc_back { display: flex; justify-content: flex-start; margin-top: .2rem; }
.st-key-rc_back button { color: var(--muted) !important; border: 0 !important; background: transparent !important; box-shadow: none !important; font-size: .86rem; padding-left: 0 !important; }
.st-key-rc_back button:hover { color: var(--accent) !important; }

/* ============ 절 제목·보조 글 ============ */
.stApp h2.rc-sec, [data-testid="stMarkdownContainer"] h2.rc-sec { font-size: 1.2rem !important; font-weight: 650 !important;
  margin: .15rem 0 .15rem !important; padding: 0 0 0 .6rem !important; color: var(--ink); letter-spacing: -0.01em; line-height: 1.3 !important;
  border-left: 3px solid var(--accent); }   /* 절 제목 왼쪽 강조선 — 공공 포털 관행 */
.rc-sec .count { color: var(--muted); font-weight: 500; font-size: .86rem; margin-left: .55rem; }
.rc-sub { color: var(--ink); font-size: .95rem; margin: 0 0 .15rem; }
.rc-meta { color: var(--muted); font-size: .84rem; margin: 0 0 .3rem; }
.rc-note { color: var(--muted); font-size: .84rem; line-height: 1.5; }
.rc-h { font-size: .98rem; font-weight: 650; margin: .2rem 0 .3rem; color: var(--ink); }
.rc-h .count { color: var(--muted); font-weight: 500; font-size: .82rem; margin-left: .4rem; }
.rc-gap { height: .6rem; } .rc-gap-lg { height: 1.6rem; }
.rc-compact { color: var(--muted); font-size: .9rem; padding: .1rem 0 .2rem; line-height: 1.55; }
.rc-compact b { color: var(--ink); font-weight: 600; margin-right: .45rem; }
.rc-edited { color: var(--muted); font-size: .78rem; margin-top: .3rem; display: flex; gap: .4rem; align-items: center; flex-wrap: wrap; }
[class*="st-key-rc_card_"] { margin-bottom: -.3rem; }
.st-key-rc_main [data-testid="stLayoutWrapper"]:has(> [class*="st-key-rc_card_"]),
.st-key-rc_main_anim [data-testid="stLayoutWrapper"]:has(> [class*="st-key-rc_card_"]) { margin-bottom: .1rem; }

/* ============ 칩·태그 ============ */
.rc-chips { display: flex; gap: .4rem; flex-wrap: wrap; margin: .35rem 0 .6rem; align-items: center; }
.rc-chips .lead { color: var(--muted); font-size: .8rem; margin-right: .1rem; }
.rc-chip { border: 1px solid var(--line); border-radius: 4px; padding: .12rem .5rem; font-size: .78rem;
           background: var(--surface); color: var(--ink); line-height: 1.35; max-width: 100%; white-space: nowrap; }
.rc-chip.wrap { white-space: normal; }
.rc-chip b { color: var(--muted); font-weight: 500; margin-right: .35rem; }
.rc-chip.accent { background: var(--accent-soft); border-color: transparent; color: var(--accent); }
.rc-chip.warn { background: var(--warn-soft); border-color: transparent; color: var(--warn); }
.rc-chip.ok { background: var(--ok-soft); border-color: transparent; color: var(--ok); }
.rc-chip.info { background: var(--info-soft); border-color: transparent; color: var(--info); }
.rc-chip.off { background: var(--off-soft); border-color: transparent; color: var(--off); }
.rc-tag { display: inline-block; font-size: .72rem; padding: .04rem .45rem; border-radius: 4px; border: 1px solid var(--line);
          color: var(--muted); margin-left: .4rem; vertical-align: middle; font-weight: 500; white-space: nowrap; }
.rc-tag.warn { background: var(--warn-soft); color: var(--warn); border-color: transparent; }
.rc-tag.accent { background: var(--accent-soft); color: var(--accent); border-color: transparent; }

/* ============ 결과 카드 ============ */
.rc-card { margin: -.1rem 0 .1rem; }
.rc-card .title { display: flex; align-items: flex-start; gap: .6rem; font-size: 1.02rem; font-weight: 600; line-height: 1.5; color: var(--ink); }
.rc-card .title .t { flex: 1 1 auto; min-width: 0; }
.rc-card .rank { display: inline-flex; align-items: center; justify-content: center; min-width: 1.6rem; height: 1.45rem; padding: 0 .35rem;
                 border-radius: 4px; border: 1px solid var(--line-strong); color: var(--muted); font-weight: 600; font-size: .78rem;
                 font-variant-numeric: tabular-nums; flex: 0 0 auto; margin-top: .2rem; }
.rc-card .meta { color: var(--muted); font-size: .85rem; margin-top: .25rem; }
.rc-score { margin-top: .4rem; font-size: .84rem; color: var(--muted); }
.rc-score b { color: var(--ink); font-weight: 600; font-variant-numeric: tabular-nums; }
.st-key-rc_main [data-testid="stPopoverButton"] button, .st-key-rc_main_anim [data-testid="stPopoverButton"] button {
  background: transparent !important; border-color: transparent !important; color: var(--muted) !important; box-shadow: none !important; }
.st-key-rc_main [data-testid="stPopoverButton"] button:hover, .st-key-rc_main_anim [data-testid="stPopoverButton"] button:hover { color: var(--accent) !important; background: var(--accent-soft) !important; }
.rc-kv { font-size: .84rem; line-height: 1.7; color: var(--ink); }
.rc-kv .ids { margin-top: .5rem; padding-top: .45rem; border-top: 1px dashed var(--line); font-size: .78rem; color: var(--muted); }
.rc-kv .ids b { min-width: 5.5rem; }
.rc-kv b { color: var(--muted); font-weight: 500; display: inline-block; min-width: 7.5rem; }
.rc-kv .v { color: var(--ink); font-weight: 600; font-variant-numeric: tabular-nums; }
.rc-kv .x { color: var(--muted); }
.rc-kv code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: .78rem;
              background: var(--surface2); padding: 0 .3rem; border-radius: 4px; }
/* 검색 중 자리표시 */
.rc-skel { border: 1px solid var(--line); border-radius: 8px; background: var(--surface); padding: .9rem 1rem; margin: .5rem 0; }
.rc-skel i { display: block; height: 12px; border-radius: 4px; margin: .45rem 0;
  background: linear-gradient(90deg, var(--surface2) 25%, var(--track) 50%, var(--surface2) 75%); background-size: 400px 100%;
  animation: rc-shimmer 1.3s linear infinite; }
.rc-skel i.t { height: 16px; width: 62%; } .rc-skel i.m { width: 40%; } .rc-skel i.s { width: 28%; }

/* ============ 오른쪽 패널 ============ */
/* 오른쪽 두 패널을 rc_right 하나로 묶어 그 묶음이 sticky. (따로 두면 100% 높이 래퍼가 둘째 패널을 열 바닥으로 밀어낸다 — D-036 실측)
   주의: 이 주석에 UX-L 화면에 없는 절 이름을 쓰지 말 것 — CSS 가 마크다운에 포함돼 UX-L 시험이 낱말을 잡는다 */
.st-key-rc_right { position: sticky; top: 3.4rem; flex: 0 0 auto !important; align-self: flex-start; }
[data-testid="stColumn"]:has(.st-key-rc_right) > [data-testid="stVerticalBlock"],
[data-testid="stColumn"]:has(.st-key-rc_right) [data-testid="stLayoutWrapper"]:has(> .st-key-rc_right) { height: 100%; align-self: stretch; }
.rc-bk { padding: .15rem 0 .1rem; }
.st-key-rc_basket .rc-h { margin-bottom: .45rem; }
.st-key-rc_basket > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] { padding: .45rem 0; }
.st-key-rc_basket > [data-testid="stLayoutWrapper"]:has(> [data-testid="stHorizontalBlock"]) + [data-testid="stLayoutWrapper"]:has(> [data-testid="stHorizontalBlock"]) { border-top: 1px solid var(--line); }
[data-testid="stVerticalBlock"].st-key-rc_basket { padding: .95rem 1.1rem .9rem !important; }
.rc-bk .title { display: flex; align-items: flex-start; gap: .45rem; font-size: .93rem; font-weight: 600; line-height: 1.45; color: var(--ink); }
.rc-bk .title .t { flex: 1 1 auto; min-width: 0; }
.rc-bk .meta { color: var(--muted); font-size: .8rem; margin-top: .15rem; }
.rc-bk .rank { display: inline-flex; align-items: center; justify-content: center; min-width: 1.6rem; height: 1.25rem; border-radius: 4px;
               background: var(--accent-soft); color: var(--accent); font-weight: 700; font-size: .7rem; padding: 0 .3rem; flex: 0 0 auto; margin-top: .15rem; }
.rc-empty { color: var(--muted); font-size: .88rem; line-height: 1.55; padding: .2rem 0 .2rem; }
.rc-empty b { color: var(--ink); font-weight: 600; }
.rc-empty .sec { display: block; margin-top: .35rem; font-size: .82rem; }
.rc-hint { color: var(--muted); font-size: .82rem; padding-top: .55rem; margin-top: .35rem; border-top: 1px dashed var(--line); }
.rc-hint b { color: var(--ink); font-weight: 600; }

/* ============ 비교 표 ============ */
table.rc-table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: .86rem; background: var(--surface);
  border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
table.rc-table th { text-align: left; color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--line); padding: .65rem .85rem; vertical-align: bottom;
  background: var(--surface2); }
table.rc-table td { border-bottom: 1px solid var(--line); padding: .65rem .85rem; vertical-align: top; color: var(--ink); }
table.rc-table tr:last-child td { border-bottom: 0; }
table.rc-table th .ttl { color: var(--ink); font-weight: 600; display: block; line-height: 1.4; }
table.rc-table th .ref { color: var(--accent); font-weight: 700; font-size: .74rem; margin-right: .3rem; }
table.rc-table a { color: var(--accent); font-weight: 600; text-decoration: none; }
table.rc-table a:hover { text-decoration: underline; }
table.rc-table td .q { color: var(--ink); }
table.rc-table td .rc-ln { display: flex; gap: .4rem; align-items: baseline; margin: .1rem 0; }
table.rc-table td .rc-ln .n { color: var(--muted); font-size: .72rem; font-weight: 600; flex: 0 0 auto; min-width: 1rem; }
.rc-path { line-height: 1.5; } .rc-path .sep { color: var(--muted); margin: 0 .05rem; }
.rc-cell { display: inline-flex; align-items: center; gap: .35rem; border-radius: 4px; padding: .16rem .55rem; font-size: .8rem; font-weight: 600; white-space: nowrap; }
.rc-cell::before { content: ""; width: .5rem; height: .5rem; border-radius: 50%; background: currentColor; opacity: .85; }
.rc-cell.found { background: var(--accent-soft); color: var(--accent); }
.rc-cell.user { background: var(--info-soft); color: var(--info); }
.rc-cell.none { background: var(--off-soft); color: var(--off); }
.rc-cell.review { background: var(--warn-soft); color: var(--warn); }
.rc-cell.rej { background: var(--off-soft); color: var(--off); text-decoration: line-through; }
mark.rc-mark { background: var(--mark); color: var(--ink); padding: 0 .1rem; border-radius: 3px; }
.rc-ev .ttl { font-weight: 600; font-size: .98rem; line-height: 1.5; color: var(--ink); }
.rc-callout { border-left: 3px solid var(--warn); background: var(--warn-soft); color: var(--ink); padding: .5rem .8rem; border-radius: 6px; font-size: .85rem; margin: .2rem 0 .6rem; }
.rc-notice { color: var(--muted); padding: .45rem .9rem .45rem .9rem; font-size: .85rem; margin: .7rem 0 .2rem; line-height: 1.55;
  border-radius: 6px; background: var(--surface2); border-left: 3px solid var(--accent); }
.rc-notice b { color: var(--ink); }
.rc-pending { color: var(--muted); font-size: .95rem; padding: .6rem 0 .2rem; }
.rc-pending b { color: var(--ink); }

/* ============ 모션 — 검색 중 자리표시만 ============ */
@keyframes rc-shimmer { from { background-position: -400px 0; } to { background-position: 400px 0; } }
"""

esc = html.escape
_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>#|~])")
_SPEC_REF = re.compile(r"\s*\((?:명세|v2|개정안|D-\d+|T-\d+)[^)]*\)")


def md_esc(s: str) -> str:
    """Streamlit 라벨(markdown)에 넣는 데이터 텍스트 — 서식 문자를 무력화한다."""
    return _MD_SPECIAL.sub(r"\\\1", str(s))


def plain(reason: str) -> str:
    """사용자용 표시에서 명세 절·결정 번호 괄호를 뗀다. 원문은 개발자용 표에 그대로 남긴다."""
    return _SPEC_REF.sub("", reason or "").strip()


def chip(label: str, value: str, kind: str = "", wrap: bool = False) -> str:
    cls = f"rc-chip {kind}" + (" wrap" if wrap else "")
    lab = f"<b>{esc(label)}</b>" if label else ""
    return f'<span class="{cls}">{lab}{esc(str(value))}</span>'


def chips(items: list[str], lead: str = "") -> str:
    head = f'<span class="lead">{esc(lead)}</span>' if lead else ""
    return '<div class="rc-chips">' + head + "".join(items) + "</div>"


def section(title: str, count: str = "") -> None:
    c = f'<span class="count">{esc(count)}</span>' if count else ""
    st.markdown(f'<h2 class="rc-sec">{esc(title)}{c}</h2>', unsafe_allow_html=True)


def gap(large: bool = False) -> None:
    st.markdown('<div class="rc-gap-lg"></div>' if large else '<div class="rc-gap"></div>', unsafe_allow_html=True)


def short_rev(rev: str | None, n: int = 8) -> str:
    return (rev or "unpinned")[:n]


def pct_fill(pct: float | None) -> float:
    """0~1 백분위 → 막대 채움 비율(0~1). 로그 눈금: 상위 0.001% → 1.0, 상위 1% → 0.4, 전체 → 0."""
    if pct is None or pct != pct:
        return 0.0
    p = max(float(pct), 1e-5)
    return max(0.0, min(1.0, -math.log10(p) / 5.0))


def pct_text(label: str, n_corpus: int | None = None) -> str:
    """`relative.format_percentile` 문구를 화면 문구로 — 무엇의 상위인지(검색 대상 전체에서 유사도 위치) 밝힌다.
    '1위' 라고 쓰지 않는다: 카드의 최종 표시 순위(재정렬 순)와 다른 값이라 혼동을 만든다."""
    base = f"{n_corpus:,}건 중 유사도" if n_corpus else "검색 대상 전체에서 유사도"
    if label == "코퍼스 최상위":
        return f"{base} 가장 높음"
    return label.replace("코퍼스 상위", f"{base} 상위")


def filters_text(f: dict) -> str:
    parts = []
    if f.get("years"):
        parts.append("선정년도 " + "·".join(str(y) for y in f["years"]))
    if f.get("programs"):
        parts.append("사업 " + "·".join(f["programs"]))
    if f.get("institutions"):
        n = len(f["institutions"])
        parts.append("기관 " + (f["institutions"][0] if n == 1 else f"{n}개"))
    if f.get("exclude_short"):
        parts.append("짧은 제목 제외")
    return ", ".join(parts)


def contains_local_path(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]:\\|/home/|/Users/", text))


def secs(ms: float | None) -> str:
    return f"{(ms or 0) / 1000:.1f}초"


def clip(s: str, n: int) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------------------------------------------------------------------------
# 자원 적재 — 준비 안 됨은 명시적 안내, 가짜 결과 없음 (v2 §13.3)
# ---------------------------------------------------------------------------
def readiness(root: Path, cfg: dict) -> list[str]:
    proc, art = root / cfg["paths"]["processed"], root / cfg["paths"]["artifacts"]
    missing = []
    if not (proc / "projects.csv").exists():
        missing.append("정제 데이터(`data/processed/projects.csv`) 없음 → `python -m research_compass.cli prepare`")
    if not (art / "project_embeddings.npy").exists() or not (art / "index_manifest.json").exists():
        missing.append("의미 인덱스(`artifacts/project_embeddings.npy`) 없음 → `python -m research_compass.cli build-index`")
    else:
        man = json.loads((art / "index_manifest.json").read_text(encoding="utf-8"))
        want = cfg.get("embedding", {}).get("revision")
        if want and man.get("model_revision") != want:
            missing.append(f"인덱스 모델 revision `{short_rev(man.get('model_revision'))}` ≠ 설정 "
                           f"`{short_rev(want)}` — 인덱스와 관련도 기준선이 무효입니다. `build-index` 재실행")
    return missing


@st.cache_resource(show_spinner=False)
def load_engine(root_str: str, cfg_path: str, cfg_mtime: float) -> svc.SearchEngine:
    cfg = yaml.safe_load(Path(cfg_path).read_text(encoding="utf-8"))
    return svc.SearchEngine(Path(root_str), cfg, need_semantic=True)


@st.cache_resource(show_spinner=False)
def load_fields(root_str: str, cfg_path: str, cfg_mtime: float):
    """D2 분야명 인덱스. index_manifest 의 분야 스냅샷·행수와 맞아야 적재한다."""
    from research_compass import embedding as emb
    from research_compass.retrieval import FlatIPIndex
    from research_compass.store import read_table
    cfg = yaml.safe_load(Path(cfg_path).read_text(encoding="utf-8"))
    root = Path(root_str)
    art = root / cfg["paths"]["artifacts"]
    fields = read_table(root / cfg["paths"]["processed"], "fields")
    vecs = emb.load(art / "field_embeddings.npy")
    man = json.loads((art / "index_manifest.json").read_text(encoding="utf-8"))
    if len(vecs) != len(fields) or man.get("fields", {}).get("rows") != len(fields):
        raise RuntimeError(f"분야 임베딩 {len(vecs)}행 ≠ fields.csv {len(fields)}행 — build-index 재실행")
    if str(fields["source_snapshot_id"].iloc[0]) != man.get("field_snapshot"):
        raise RuntimeError("분야 스냅샷이 인덱스 manifest 와 다르다 — build-index 재실행")
    return fields, FlatIPIndex(vecs)


@st.cache_data(show_spinner=False)
def load_manifests(root_str: str, cfg_path: str) -> list[dict]:
    """스냅샷·메모에 붙일 출처 manifest. 로컬 절대 경로가 있는 data_manifest 는 넣지 않는다."""
    cfg = yaml.safe_load(Path(cfg_path).read_text(encoding="utf-8"))
    art = Path(root_str) / cfg["paths"]["artifacts"]
    out = []
    for name in ("index_manifest.json", "rerank_manifest.json"):
        p = art / name
        if p.exists():
            text = p.read_text(encoding="utf-8")
            if not contains_local_path(text):
                out.append({"name": name, **json.loads(text)})
    return out


def feature_states(root: Path, cfg: dict) -> dict:
    if "_caps_override" in st.session_state:
        caps = dict(st.session_state["_caps_override"])
    else:
        p = root / cfg["paths"]["artifacts"] / "capabilities.json"
        caps = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return capm.v2_feature_states(capm.refresh_workspace_states(caps))


def get_engine() -> tuple[svc.SearchEngine | None, list[str]]:
    if "_engine_override" in st.session_state:                # 시험용 주입 (가짜 엔진, test_fixture)
        return st.session_state["_engine_override"], []
    problems = readiness(ROOT, CFG)
    if problems:
        return None, problems
    try:
        return load_engine(str(ROOT), str(CFG_PATH), CFG_PATH.stat().st_mtime), []
    except Exception as e:                                     # 모델 캐시 없음 등. 가짜 결과 없이 실패 표시
        return None, [f"모델·인덱스 적재 실패: {type(e).__name__}: {e}",
                      "모델 캐시 확인 → `python -m research_compass.cli doctor --quick` / "
                      "`prepare-reranker --no-download`"]


def corpus_facts(engine: svc.SearchEngine) -> tuple[int, str]:
    years = sorted({int(y) for y in engine.projects["selection_year"].dropna().tolist()})
    span = f"{years[0]}~{years[-1]}년" if len(years) > 1 else (f"{years[0]}년" if years else "")
    return len(engine.projects), span


# ---------------------------------------------------------------------------
# 검색 실행 — 기존 서비스 1회 호출 (v2 §7.1). 응답 통계는 실행 ID 별로 세션에만 둔다.
# ---------------------------------------------------------------------------
_RESULTS_SLOT = None     # 결과가 놓이는 자리(검색 상자 아래 컨테이너). render_workspace 가 매 실행 새로 만든다 — 스켈레톤·진행 표시가 여기 그려진다 (D-038)


def execute(ws: wsm.Workspace, plan: wsm.QueryPlan, engine: svc.SearchEngine) -> wsm.SearchRun | None:
    S = st.session_state
    sink: dict = {}

    def capture(req, eng):
        resp = svc.search(req, eng)
        sink["resp"] = resp
        return resp

    target = _RESULTS_SLOT if _RESULTS_SLOT is not None else st.container()
    skel = target.empty()
    skel.markdown("".join('<div class="rc-skel"><i class="t"></i><i class="m"></i><i class="s"></i></div>' for _ in range(3)),
                  unsafe_allow_html=True)
    with target, st.status(f"검색 중 · {md_esc(plan.effective_query)}", expanded=False) as status:
        try:
            run = wsm.run_perspective_search(
                ws, plan, engine, engine.cfg, capture, svc.SearchRequest,
                top_k=MAX_TOP_K, filters=S["filters"], requested_engine=REQUESTED_ENGINE or None)
        except wsm.WorkspaceError as e:
            status.update(label="검색 실행 불가", state="error")
            st.error(str(e))
            return None
        except Exception as e:                                 # 실패는 실패로 (v2 §13.4)
            status.update(label="검색 실패", state="error")
            st.error(f"검색 실패: {type(e).__name__}: {e}")
            return None
        resp = sink.get("resp")
        S["run_stats"][run.run_id] = {"stats": dict(resp.stats) if resp else {},
                                      "notes": list(resp.notes) if resp else []}
        status.update(label=f"검색 완료 · {secs(run.latency_ms.get('total_s'))}", state="complete")
    skel.empty()
    S["view_home"] = False
    S["active_run_id"] = run.run_id
    S["shown"] = DEFAULT_TOP_K
    S["just_ran"] = True
    S["mode_seed"] = "topic"      # 어느 검색 방식에서 실행했든, 결과를 만든 관점·검색문이 보이는 탭으로 돌아온다
    st.rerun()          # 새 실행을 이력·상태·결과·오른콀 패널에 즉시 반영 (골격이 같아 자리 이동 없이 결과만 붙는다)
    return run          # 도달하지 않음 (rerun 이 스크립트를 다시 시작)


def apply_elements(ws: wsm.Workspace, values: dict[str, str]) -> None:
    for role, text in values.items():
        cur = next((e for e in ws.elements if e.role == role), None)
        t = prep.normalize_text(text or "")
        if t and cur is None:
            ws.add_element(wsm.make_element(role, t))
        elif t and cur is not None and cur.text != t:
            ws.update_element(cur.element_id, t)
        elif not t and cur is not None:
            ws.remove_element(cur.element_id)


# ---------------------------------------------------------------------------
# 그래프 (Altair · 범위 명시 · 테마 팔레트)
# ---------------------------------------------------------------------------
def axis_style(chart, p: dict):
    """축 글자·선을 팔레트 값으로 고정한다. Streamlit 의 Altair 테마(`theme="streamlit"`)는 차트 설정 위에 자기 값을 덮어 축 라벨을 흐린
    글자색으로 그리므로, 그리는 쪽에서 `theme=None` 으로 끄고 배경·글꼴도 여기서 정한다 (라이트에서 축 글자가 옅게 보임 — 사용자 검토)."""
    font = "'Pretendard Variable', Pretendard, 'Apple SD Gothic Neo', 'Malgun Gothic', system-ui, sans-serif"
    return (chart.configure(background="transparent", font=font)
            .configure_view(strokeWidth=0)
            .configure_axis(labelColor=p["chart_muted"], titleColor=p["chart_muted"], labelFontSize=11, titleFontSize=11,
                            labelFont=font, titleFont=font, domainColor=p["line_strong"], tickColor=p["line_strong"], gridColor=p["line"])
            .configure_text(font=font))


def hist_chart(hist: dict, stats: dict, rows: list[wsm.ResultRow], p: dict):
    edges, counts = hist.get("edges", []), hist.get("counts", [])
    if not counts:
        return None
    df = pd.DataFrame({"lo": edges[:-1], "hi": edges[1:], "count": counts})
    height = 240
    bars = alt.Chart(df).mark_bar(color=p["chart_bar"]).encode(
        x=alt.X("lo:Q", title="의미 유사도 (0~1 상대 점수)"), x2="hi:Q",
        y=alt.Y("count:Q", title="레코드 수 (로그 눈금)", scale=alt.Scale(type="symlog")),
        tooltip=[alt.Tooltip("lo:Q", format=".3f", title="구간 시작"),
                 alt.Tooltip("hi:Q", format=".3f", title="구간 끝"),
                 alt.Tooltip("count:Q", title="레코드 수")])
    marks = pd.DataFrame([{"x": stats.get("p50"), "label": "중앙값"},
                          {"x": stats.get("p99"), "label": "상위 1% 경계"},
                          {"x": stats.get("max"), "label": "최댓값"}]).dropna()
    rules = alt.Chart(marks).mark_rule(strokeDash=[4, 3], color=p["chart_muted"]).encode(x="x:Q")
    texts = alt.Chart(marks).mark_text(align="left", dx=3, color=p["chart_muted"], fontSize=11).encode(
        x="x:Q", y=alt.value(10), text="label:N")
    pts = pd.DataFrame([{"x": r.semantic_score, "y": 0, "rank": r.rank, "title": r.title_raw[:40]}
                        for r in rows])
    ticks = alt.Chart(pts).mark_point(shape="triangle-up", size=120, color=p["accent"], filled=True,
                                      yOffset=-7).encode(
        x="x:Q", y=alt.Y("y:Q"),
        tooltip=[alt.Tooltip("rank:Q", title="표시 순위"), alt.Tooltip("title:N", title="제목 (앞 40자)"),
                 alt.Tooltip("x:Q", format=".3f", title="의미 유사도")])
    return axis_style((bars + rules + texts + ticks).properties(height=height), p)


def latency_chart(latency_ms: dict, p: dict):
    rows = [{"stage": lbl, "ms": float(latency_ms.get(k, 0.0)), "order": i}
            for i, (k, lbl) in enumerate(STAGES) if k in latency_ms]
    if not rows:
        return None
    df = pd.DataFrame(rows)
    bars = alt.Chart(df).mark_bar(color=p["accent"], cornerRadiusEnd=3).encode(
        y=alt.Y("stage:N", sort=alt.SortField("order"), title=None,
                axis=alt.Axis(labelLimit=340, labelFontSize=11)),
        x=alt.X("ms:Q", title="처리시간 (ms)"),
        tooltip=[alt.Tooltip("stage:N", title="단계"), alt.Tooltip("ms:Q", format=".1f", title="ms")])
    text = bars.mark_text(align="left", dx=4, color=p["ink"], fontSize=11).encode(text=alt.Text("ms:Q", format=".0f"))
    return axis_style((bars + text).properties(height=30 * len(rows) + 40), p)


def dist_chart(d: an.ScopedDistribution, p: dict, other_label: str = "기타", max_rows: int = 6,
               label_limit: int = 260, headroom: float = 1.22):
    """가로 막대. 작은 항목은 '기타 (N개)' 로 묶어 표기하되 수치는 그대로 합한다. 값 라벨 잘림 방지용 여백(headroom).
    좁은 패널(첫 화면 오른쪽)에서는 label_limit 을 줄이고 headroom 을 늘려 값 라벨이 잘리지 않게 한다."""
    items = [{"value": k, "count": v, "kind": "관측"} for k, v in d.counts.items()]
    if len(items) > max_rows:
        head, tail = items[:max_rows - 1], items[max_rows - 1:]
        items = head + [{"value": f"{other_label} ({len(tail)}개 항목)", "count": sum(t["count"] for t in tail),
                         "kind": "관측"}]
    if d.n_unknown:
        items.append({"value": "미상", "count": d.n_unknown, "kind": "미상"})
    if not items:
        return None
    df = pd.DataFrame(items)
    top = max(int(x["count"]) for x in items)
    bars = alt.Chart(df).mark_bar(cornerRadiusEnd=3, size=16).encode(
        y=alt.Y("value:N", sort=None, title=None, axis=alt.Axis(labelLimit=label_limit, labelFontSize=11)),
        x=alt.X("count:Q", title=None, scale=alt.Scale(domain=[0, top * headroom]),
                axis=alt.Axis(tickMinStep=1, labelFontSize=10, grid=False)),
        color=alt.Color("kind:N", scale=alt.Scale(domain=["관측", "미상"], range=[p["chart_bar2"], p["chart_bar3"]]),
                        legend=None),
        tooltip=[alt.Tooltip("value:N", title=d.by), alt.Tooltip("count:Q", title="레코드 수")])
    text = bars.mark_text(align="left", dx=4, color=p["ink"], fontSize=11).encode(text=alt.Text("count:Q", format=","))
    return axis_style((bars + text).properties(height=28 * len(items) + 36), p)


def rows_as_records(rows) -> list[dict]:
    return [{"source_snapshot_id": r.source_snapshot_id, "record_id": r.record_id,
             "selection_year": r.selection_year, "program": r.program, "institution": r.institution}
            for r in rows]


def composition_text(records: list[dict], scope: str, run_ids: list[str], filters: dict) -> tuple[str, list[str]]:
    """소규모 집합의 구성은 차트 대신 한 줄 글로 (D-026 #10). 범위·대상 수·미상 수를 항상 붙인다."""
    parts, caveats = [], []
    for by, name, suffix in (("selection_year", "선정년도", "년"), ("program", "대사업명", "")):
        d = an.distribution(records, by, scope, run_ids=run_ids, filters=filters)
        problems = an.check_invariants(d)
        if problems:
            parts.append(f"{name}: 집계 불변성 위반 ({'; '.join(problems)})")
            continue
        seg = " · ".join(f"{k}{suffix} {v}" for k, v in d.counts.items())
        if d.n_unknown:
            seg += f" · 미상 {d.n_unknown}"
        parts.append(f"{name} — {seg or '대상 없음'}")
        caveats = list(d.caveats)
    n = an.distribution(records, "selection_year", scope).n
    return f"{an.SCOPE_LABELS[scope]} {n}건: " + " / ".join(parts), caveats


def render_composition(records: list[dict], scope: str, run_ids: list[str], filters: dict, p: dict) -> None:
    """건수가 적으면 글로, 많으면 차트로. 어느 쪽이든 범위와 주의 문구를 붙인다."""
    n = an.distribution(records, "selection_year", scope).n
    if n <= TEXT_SUMMARY_MAX:
        text, caveats = composition_text(records, scope, run_ids, filters)
        st.markdown(f'<div class="rc-note" style="color:var(--ink)">{esc(text)}</div>', unsafe_allow_html=True)
        st.caption(" · ".join(caveats))
        return
    c1, c2 = st.columns(2)
    caveats: list[str] = []
    for col, by, name in ((c1, "selection_year", "선정년도"), (c2, "program", "대사업명")):
        d = an.distribution(records, by, scope, run_ids=run_ids, filters=filters)
        problems = an.check_invariants(d)
        caveats = list(d.caveats)
        with col:
            st.caption(f"**{name}별 레코드 수** — {an.describe(d)}")
            ch = dist_chart(d, p)
            if ch is not None:
                st.altair_chart(ch, width="stretch", theme=None)
            else:
                st.caption("대상 없음")
            if problems:
                st.error("집계 불변성 위반: " + "; ".join(problems))
    st.caption(" · ".join(caveats))


# ---------------------------------------------------------------------------
# 머리말 · 테마 토글 · 연구주제 입력
# ---------------------------------------------------------------------------
def render_theme_toggle() -> None:
    S = st.session_state
    if "theme_pick" not in S:
        S["theme_pick"] = S.get("theme_choice", "system")
    with st.container(key="rc_theme_toggle"):
        c1, c2 = st.columns([0.7, 9.3], vertical_alignment="center")
        c1.markdown('<span class="rc-mode-lab">화면 모드</span>', unsafe_allow_html=True)
        with c2:
            pick = st.segmented_control("화면 모드", THEME_OPTS, format_func=lambda k: THEME_LABELS[k],
                                        key="theme_pick", label_visibility="collapsed")
    choice = pick if pick in THEME_OPTS else "system"
    if choice != S.get("theme_choice", "system"):
        S["theme_choice"] = choice
        S["theme_touched"] = True
        st.rerun()


def push_theme_to_frontend(choice: str) -> None:
    """토글 선택을 Streamlit 프런트엔드 테마에 적용한다 (같은 출처 iframe → 호스트 메시지). 세션 상태를 잃지 않는다."""
    info = {**ST_THEME_COMMON, **ST_THEMES[choice if choice in ("light", "dark") else "light"]}
    dark = {**ST_THEME_COMMON, **ST_THEMES["dark"]}
    js = """<script>(function(){
  var choice = %s, light = %s, dark = %s, p = window.parent;
  var info = choice === 'dark' ? dark : (choice === 'light' ? light
             : ((p.matchMedia && p.matchMedia('(prefers-color-scheme: dark)').matches) ? dark : light));
  var msg = {stCommVersion: 1, type: 'SET_CUSTOM_THEME_CONFIG', themeName: 'Custom Theme', themeInfo: info};
  try { p.Function('m', 'window.postMessage(m, window.location.origin)')(msg); } catch (e) {}
})();</script>""" % (json.dumps(choice), json.dumps(info), json.dumps(dark))
    with st.container(key="rc_theme_bridge"):            # 보이지 않는 같은 출처 iframe (스크립트만 실행)
        st.iframe(js, height=1)


def render_band() -> None:
    """상단 식별 띠 — 무엇을 바탕으로 한 어떤 성격의 도구인지 한 줄. 공공 포털의 기관 줄 자리이되 기관을 사칭하지 않는다."""
    st.markdown('<div class="rc-band"><span>한국연구재단 공공데이터 활용 — 과제정보 · 선정과제 연구분야</span>'
                '<span>공공데이터 활용 공모전 출품작</span></div>', unsafe_allow_html=True)


# 첫 화면의 검색 방식 (D-036). 진입점만 다르고 엔진은 하나다 — 어느 방식이든 검색문 하나로 검색 1회를 실행한다.
#   topic    연구주제 한 문장            → 관점 `full`
#   elements 요소별 탐색 (주제 + 대상·방법·목표 + 관점 선택) → 고른 관점 1개
#   summary  연구 요약 붙여넣기 (여러 줄)  → 관점 `full`, 요약 전체가 검색문 (NIH Matchmaker · NTIS 문장검색에 대응)
#   field    연구분야로 찾기 (D2 분야명)   → 고른 분야명을 연구주제 칸에 넣기만 한다 (실행은 사용자가)
SEARCH_MODES = ("topic", "elements", "summary", "field")
SEARCH_MODES_L = ("topic", "summary", "field")          # UX-L 은 관점이 없으므로 요소별 탐색도 없다
SEARCH_MODE_LABELS = {"topic": "연구주제 한 문장", "elements": "요소별 탐색", "summary": "연구 요약 붙여넣기",
                      "field": "연구분야로 찾기"}
SUMMARY_MAX_CHARS = 1000
EMBED_MAX_TOKENS = int(CFG.get("embedding", {}).get("max_tokens", 512))


def render_workspace(engine: svc.SearchEngine, ux: str, states: dict, palette: dict) -> None:
    """한 페이지 (D-038). 검색 전후 골격이 같고, 검색하면 검색 상자 **아래 같은 자리**에 결과가 붙는다.

        머리말 → [검색 상자(검색 방식 · 검색칸 · 검색 범위) 70% | 오른쪽 30%] → (최근 탐색 · 결과: 왼쪽 열 안) →
        선택한 과제 비교 → 탐색 메모 → 데이터 및 검색 정보 → 수치 띠 → 바닥글 → 화면 모드

    - 검색 방식 `연구주제 한 문장` 탭은 첫 검색 뒤 [탐색 관점 | 현재 검색문 | 탐색] 행이 된다. 다른 탭에서 검색해도 결과가 나오면 이 탭으로 돌아온다.
    - 오른쪽 30% 는 검색 전 `수록 데이터 구성`, 검색 뒤 `비교함 + 표시 중인 구성`(UX-L 은 늘 수록 데이터 구성).
    - 스켈레톤·진행 표시는 결과 자리(`_RESULTS_SLOT`)에 그린다 — 검색 상자 안이 아니라. 그래서 로딩 → 결과가 같은 자리에서 교체된다.
    - 검색 범위 위젯은 검색칸보다 **먼저 만들고**(컨테이너로 자리만 아래에) 그린다 — 검색칸의 실행이 st.rerun 을 부르는데,
      그 실행에서 아직 안 그려진 위젯의 상태를 Streamlit 이 지우기 때문이다 (D-033 함정)."""
    global _RESULTS_SLOT
    S = st.session_state
    ws: wsm.Workspace | None = S["ws"]
    active = (ws.run(S["active_run_id"]) if S.get("active_run_id") else ws.latest_run()) if ws is not None else None
    home = bool(S.get("view_home"))                  # 로고를 눌러 기본 화면으로 — 결과·비교함은 숨기되 지우지 않는다
    has_results = ws is not None and bool(ws.search_runs) and not home
    shown = min(S.get("shown", DEFAULT_TOP_K), len(active.results)) if active is not None else 0
    modes = SEARCH_MODES_L if ux == "l" else SEARCH_MODES
    if "mode_seed" in S:
        S["search_mode"] = S.pop("mode_seed")
    if S.get("search_mode") not in modes:
        S["search_mode"] = "topic"

    with st.container(key="rc_brand"):               # 머리말 = 로고 단추(기본 화면으로) + 부제
        c1, c2 = st.columns([2.6, 7.4], vertical_alignment="center")
        with c1, st.container(key="rc_home"):
            if st.button("Research Compass", key="btn_home", type="tertiary", help="기본 화면으로 (탐색 이력·비교함·메모는 남습니다)"):
                S["view_home"] = True
                S["mode_seed"] = "topic"
                st.rerun()
        c2.markdown('<div class="rc-landing"><span class="sub">한국연구재단 지원과제 탐색</span></div>', unsafe_allow_html=True)
    left, right = st.columns([7, 3], gap="large")
    with left:
        box = st.container(border=True, key="rc_searchbox")
        slot = st.container(key="rc_results")            # 결과 자리 — 상자 아래. 만들기만 먼저 하고 내용은 상자 뒤에 채운다
        _RESULTS_SLOT = slot
        with box:
            with st.container(key="rc_mode"):
                mode = st.segmented_control("검색 방식", modes, key="search_mode", format_func=lambda k: SEARCH_MODE_LABELS[k],
                                            label_visibility="collapsed")
            mode = mode if mode in modes else "topic"
            box_form, box_filter = st.container(), st.container()
            if mode != "field":
                with box_filter, st.container(key="rc_filters"):
                    render_filter_row(engine, ws, active)
            with box_form:
                if mode == "topic":
                    if ws is None or home:              # 검색 전 · 기본 화면: 연구주제 칸 (여기서 낸 문장이 다르면 새 연구주제가 된다)
                        render_idea_form(ws, engine, compact=False)
                    elif ux == "l":
                        render_query_editor(ws, engine, active)
                    else:
                        render_perspective_row(ws, engine, active)
                elif mode == "elements":
                    render_landing_elements_form(ws, engine)
                elif mode == "summary":
                    render_summary_form(ws, engine)
                else:
                    render_landing_field(ws, engine, ux, states)
            if ws is not None and run_refilter(ws, engine, active):
                return
        if home and ws is not None and ws.search_runs:
            with st.container(key="rc_back"):
                if st.button("이전 결과로 돌아가기", key="btn_back", type="tertiary"):
                    S["view_home"] = False
                    st.rerun()
        if has_results:
            with slot:
                render_history(ws)
                active = ws.run(S["active_run_id"]) if S.get("active_run_id") else ws.latest_run()
                shown = min(S.get("shown", DEFAULT_TOP_K), len(active.results))
                gap()
                render_status(ws, active, shown)
                render_results(ws, active, ux)
    with right:
        if has_results and ux != "l":
            with st.container(key="rc_right"):              # 비교함 + 구성 패널 = 한 sticky 묶음
                render_basket(ws, active)
                gap()
                render_side_composition(active, shown, palette)
        else:
            render_overview_panel(engine, palette)

    observations: list = []
    actions: list = []
    if has_results:
        st.divider()
        if ux == "l":                       # 목록 전용 조건: 관점·비교함·비교표·구조화 메모 없음
            render_free_memo(ws)
        else:
            observations = render_evidence(ws, engine)
            actions = compute_actions(ws, observations)
            st.divider()
            render_memo(ws, states, observations, actions)
    st.divider()
    section("데이터 및 검색 정보")
    if has_results:                         # 검색 전에는 `연구분야로 찾기` 탭과 같은 기능이라 싣지 않는다
        render_field_search(ws, engine, states, ux)
    render_dataset_panel(engine, palette)
    render_search_details(ws, active, palette, ux)
    if ws is not None:
        render_element_matrix(ws, observations)
    render_feature_table(states, engine, ux, ws)
    stats = corpus_stats(engine)
    render_stats_strip(engine, stats)
    render_footer(engine, stats)
    render_theme_toggle()


def dataset_records(engine: svc.SearchEngine) -> list[dict]:
    """전체 수록 데이터 → 범위 명시 집계용 레코드 (analytics.distribution 입력)."""
    pr = engine.projects
    prog_col = "program_대사업명" if "program_대사업명" in pr.columns else None
    return [{"source_snapshot_id": a, "record_id": b, "selection_year": c, "program": d}
            for a, b, c, d in zip(pr["source_snapshot_id"], pr["record_id"], pr["selection_year"],
                                  pr[prog_col] if prog_col else [""] * len(pr))]


def render_overview_panel(engine: svc.SearchEngine, p: dict) -> None:
    """첫 화면 오른쪽 — 전체 수록 데이터의 선정연도·대사업명 구성 (범위 `dataset_snapshot`). 실데이터 막대만, 추세 문구 없음."""
    recs = dataset_records(engine)
    with st.container(border=True, key="rc_overview"):
        st.markdown(f'<div class="rc-h">수록 데이터 구성<span class="count">{len(recs):,}건</span></div>', unsafe_allow_html=True)
        caveats: list[str] = []
        for by, label in (("selection_year", "선정연도별 수록 레코드"), ("program", "대사업명별 수록 레코드")):
            d = an.distribution(recs, by, "dataset_snapshot")
            caveats = list(d.caveats)
            st.caption(label)
            ch = dist_chart(d, p, max_rows=6, label_limit=150, headroom=1.45)
            if ch is not None:
                st.altair_chart(ch, width="stretch", theme=None)
        if caveats:
            st.caption(" · ".join(caveats))


def corpus_stats(engine: svc.SearchEngine) -> dict:
    """첫 화면 수치 띠의 재료 — 전부 수록 데이터에서 센 값(구별되는 이름의 수)이다. 실제 기관·사업 수와 같다고 주장하지 않는다."""
    p = engine.projects
    n, span = corpus_facts(engine)

    def n_distinct(col: str) -> int | None:
        if col not in p.columns:
            return None
        s = p[col].dropna().astype(str).str.strip()
        return int(s[s != ""].nunique())

    out = {"n": n, "span": span, "n_programs": n_distinct("program_대사업명"), "n_inst": n_distinct("institution"),
           "n_fields": None, "indexed_at": ""}
    if "_engine_override" not in st.session_state:
        try:
            for m in load_manifests(str(ROOT), str(CFG_PATH)):
                if m.get("name") == "index_manifest.json":
                    rows = (m.get("fields") or {}).get("rows")
                    out["n_fields"] = int(rows) if rows else None
                    out["indexed_at"] = str(m.get("generated_at", ""))[:10]
        except Exception:
            pass
    return out


def render_stats_strip(engine: svc.SearchEngine, stats: dict) -> None:
    tiles = [(f"{stats['n']:,}", "수록 레코드"), (stats["span"], "선정연도")]
    if stats["n_programs"]:
        tiles.append((f"{stats['n_programs']:,}", "대사업명"))
    if stats["n_inst"]:
        tiles.append((f"{stats['n_inst']:,}", "주관기관명"))
    if stats["n_fields"]:
        tiles.append((f"{stats['n_fields']:,}", "연구분야명 (D2)"))
    cells = "".join(f'<div{" class=\"last\"" if i == len(tiles) - 1 else ""}><b>{esc(v)}</b><span>{esc(k)}</span></div>'
                    for i, (v, k) in enumerate(tiles))
    mode_label, mode_kind = MODE_LABELS.get(engine.run_mode, MODE_LABELS["unknown"])
    mode = chip("", mode_label, mode_kind) if engine.run_mode != "local_live" else ""
    st.markdown(f'<div class="rc-stats">{cells}{mode}</div>', unsafe_allow_html=True)


def render_footer(engine: svc.SearchEngine, stats: dict) -> None:
    """출처·스냅샷·모델 식별 정보 한 줄. 설명이 아니라 식별자다. 기관의 공식 서비스로 읽히지 않게 마지막에 밝힌다."""
    ids = [str(x.get("dataset_id")) for x in CFG.get("sources", [])
           if x.get("key") in ("D1", "D2") and x.get("dataset_id")]        # KISTEP 코드표(K18·K1)는 검증용이라 바닥글에 싣지 않는다
    snap = str(engine.projects["source_snapshot_id"].iloc[0]) if len(engine.projects) else "—"
    emb = CFG.get("embedding", {})
    model = str(emb.get("model_id", "")).split("/")[-1] or "임베딩"
    parts = ["한국연구재단 공공데이터", "data.go.kr " + " · ".join(ids) if ids else "data.go.kr", f"스냅샷 {snap}"]
    if stats.get("indexed_at"):
        parts.append(f"색인 {stats['indexed_at']}")
    parts.append(f"{model} {short_rev(emb.get('revision'))}")
    parts.append("공공데이터 활용 공모전 출품작 — 기관의 공식 서비스가 아닙니다")
    st.markdown(f'<div class="rc-foot">{" · ".join(esc(x) for x in parts)}</div>', unsafe_allow_html=True)


def ensure_workspace(ws: wsm.Workspace | None, idea: str, engine: svc.SearchEngine) -> wsm.Workspace:
    S = st.session_state
    if ws is None:
        ws = wsm.new_workspace(idea, run_mode=engine.run_mode)   # type: ignore[arg-type]
        S["ws"] = ws
    elif idea != ws.idea_text:
        ws.change_idea(idea)
    return ws


def render_landing_elements_form(ws: wsm.Workspace | None, engine: svc.SearchEngine) -> None:
    """요소별 탐색 — 주제 + 대상·맥락 / 방법·접근 / 목표·질문 + 관점 하나. 고른 관점으로 검색 1회 (자동 통합 없음)."""
    S = st.session_state
    with st.form("landing_elements_form", border=False):
        idea = st.text_input("연구주제", key="idea_input_el", placeholder="연구주제를 한 문장으로", label_visibility="collapsed")
        cols = st.columns(3)
        vals = {}
        for col, role in zip(cols, wsm.ROLES):
            vals[role] = col.text_input(wsm.ROLE_LABELS[role], key=f"el_land_{role}", placeholder=ROLE_HINTS[role])
        c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
        persp = c1.radio("탐색 관점", wsm.PERSPECTIVES, key="persp_land", horizontal=True,
                         format_func=lambda k: PERSP_SHORT[k])
        go = c2.form_submit_button("탐색", type="primary", key="btn_search_el", width="stretch")
    if not go:
        return
    t = prep.normalize_text(idea or "")
    if not t:
        st.warning("연구주제를 입력하세요.")
        return
    ws = ensure_workspace(ws, t, engine)
    try:
        apply_elements(ws, vals)
        plan = wsm.build_effective_query(ws.idea_text, ws.elements, persp)
    except wsm.WorkspaceError as e:
        st.error(str(e))
        return
    if not plan.available:
        st.info(plan.reason)
        return
    S["persp_seed"] = persp                       # 결과 화면의 관점 선택을 지금 고른 관점으로
    execute(ws, plan, engine)


def token_count(engine: svc.SearchEngine, text: str) -> int | None:
    """임베더 토크나이저 기준 토큰 수. 가짜 엔진·구버전이면 None (그때는 상한 검사를 하지 않는다)."""
    emb = (getattr(engine, "semantic", None) or {}).get("embedder")
    tok = getattr(getattr(emb, "model", None), "tokenizer", None)
    if tok is None:
        return None
    try:
        return len(tok(text, add_special_tokens=True)["input_ids"])
    except Exception:
        return None


def render_summary_form(ws: wsm.Workspace | None, engine: svc.SearchEngine) -> None:
    """연구 요약 붙여넣기 — 여러 줄 텍스트 전체가 연구주제이자 검색문(관점 `full`). 임베더 상한을 넘으면 잘라서 검색하지 않고 멈춘다."""
    with st.form("summary_form", border=False):
        text = st.text_area("연구 요약", key="summary_input", height=170, max_chars=SUMMARY_MAX_CHARS,
                            placeholder="연구 요약이나 계획 문단을 붙여 넣기", label_visibility="collapsed")
        _, c2 = st.columns([5, 1])
        go = c2.form_submit_button("탐색", type="primary", key="btn_search_summary", width="stretch")
    if not go:
        return
    t = prep.normalize_text(text or "")
    if not t:
        st.warning("연구 요약을 입력하세요.")
        return
    n_tok = token_count(engine, t)
    if n_tok is not None and n_tok > EMBED_MAX_TOKENS:
        st.warning(f"검색에 쓸 수 있는 길이는 {EMBED_MAX_TOKENS}토큰까지입니다 (지금 {n_tok}토큰). 앞부분만 잘라 검색하지 않으니 줄여 주세요.")
        return
    ws = ensure_workspace(ws, t, engine)
    plan = wsm.build_effective_query(ws.idea_text, ws.elements, "full")
    execute(ws, plan, engine)


def render_landing_field(ws: wsm.Workspace | None, engine: svc.SearchEngine, ux: str, states: dict) -> None:
    """연구분야로 찾기 — D2 분야명과의 의미 유사도 상위 8개. 고른 분야명은 연구주제 칸에 넣기만 한다 (v2 §12.3 실행은 사용자가)."""
    S = st.session_state
    fields, fidx, why = field_index(states)
    if fields is None:
        st.info(why)
        return
    # 기준연도 경고 한 줄은 첫 화면에서 뺐다 (사용자 검토 2026-09-14) — 각 결과의 `(비교 불가)` 툴팁이 같은 사실을 담고, 비교·순위 기능 자체가 없다
    with st.form("landing_field_form", border=False):
        c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
        q = c1.text_input("분야명을 찾을 문장", key="fq_land", placeholder="연구주제나 낱말", label_visibility="collapsed")
        go = c2.form_submit_button("분야명 찾기", type="primary", key="btn_fields_land", width="stretch")
    if go and prep.normalize_text(q or ""):
        S["field_hits"] = field_hits(engine, fields, fidx, prep.normalize_text(q))

    def pick(h: dict) -> None:
        if ws is None:                        # 아직 검색 전이면 연구주제 칸에, 검색 뒤면 현재 검색문 칸에 (실행은 사용자가)
            S["idea_seed"] = h["name"]
        else:
            S["query_seed"] = h["name"]
        S["mode_seed"] = "topic"
        if ux != "l":
            sel = {"field_record_id": h["code"], "field_name": h["name"]}
            if sel not in S["field_selections"]:
                S["field_selections"].append(sel)
        st.rerun()

    label, tip = (("연구주제로 넣기", "연구주제 칸에 넣습니다. 검색은 실행되지 않습니다.") if ws is None
                  else ("검색문에 넣기", "현재 검색문 칸에 넣습니다. 검색은 실행되지 않습니다."))
    render_field_hits(S.get("field_hits"), label, tip, "fld_land", pick)


def render_not_ready(problems: list[str]) -> None:
    st.error("데이터·모델이 준비되지 않아 검색할 수 없습니다.")
    for p in problems:
        st.markdown(f"- {p}")
    st.code("python -m research_compass.cli doctor --quick\n"
            "python -m research_compass.cli prepare\n"
            "python -m research_compass.cli build-index\n"
            "python -m research_compass.cli prepare-reranker", language="bash")


def render_idea_form(ws: wsm.Workspace | None, engine: svc.SearchEngine, compact: bool) -> None:
    S = st.session_state
    if "idea_seed" in S:                          # 연구분야로 찾기 → '연구주제로 넣기' 가 넣어 둔 분야명 (위젯 생성 전에만 넣을 수 있다)
        S["idea_input"] = S.pop("idea_seed")
    with st.form("idea_form", border=False):
        c1, c2 = st.columns([6, 1] if compact else [5, 1], vertical_alignment="bottom")
        idea = c1.text_input("연구주제", key="idea_input", placeholder="연구주제를 한 문장으로",
                             label_visibility="collapsed")
        go = c2.form_submit_button("탐색", type="primary", key="btn_search", width="stretch")
    if not go:
        return
    t = prep.normalize_text(idea or "")
    if not t:
        st.warning("연구주제를 입력하세요.")
        return
    ws = ensure_workspace(ws, t, engine)
    plan = wsm.build_effective_query(ws.idea_text, ws.elements, "full")
    execute(ws, plan, engine)


# ---------------------------------------------------------------------------
# 관점 · 실제 검색문 · 요소 · 검색 범위 (한 줄 + 접힘 둘)
# ---------------------------------------------------------------------------
def _take_query_seed() -> str | None:
    S = st.session_state
    if "query_seed" in S:
        S["query_seq"] = S.get("query_seq", 0) + 1
        return S.pop("query_seed")
    return None


def render_elements_form(ws: wsm.Workspace) -> None:
    with st.form("elements_form", border=False):
        cols = st.columns(3)
        vals = {}
        for col, role in zip(cols, wsm.ROLES):
            cur = next((e.text for e in ws.elements if e.role == role), "")
            vals[role] = col.text_input(wsm.ROLE_LABELS[role], value=cur,
                                        key=f"el_{role}_{ws.idea_revision}", placeholder=ROLE_HINTS[role])
        applied = st.form_submit_button("요소 반영", key="btn_elements")
    if applied:
        try:
            apply_elements(ws, vals)
            st.rerun()
        except wsm.WorkspaceError as e:
            st.error(str(e))


def filter_options(engine: svc.SearchEngine) -> tuple[list[int], list[str]]:
    p = engine.projects
    years_all = sorted({int(y) for y in p["selection_year"].dropna().tolist()})
    prog_col = "program_대사업명" if "program_대사업명" in p.columns else None
    programs_all = sorted(p[prog_col].dropna().astype(str).unique().tolist()) if prog_col else []
    return years_all, programs_all


def filters_from_state() -> dict:
    """검색 범위 위젯(f_years · f_programs · f_short)의 현재 값 → 검색 요청 필터. 첫 화면과 결과 화면이 같은 키를 쓴다."""
    S = st.session_state
    f = {"years": list(S.get("f_years") or []), "programs": list(S.get("f_programs") or []),
         "exclude_short": bool(S.get("f_short"))}
    return {k: v for k, v in f.items() if v}


def render_filter_row(engine: svc.SearchEngine, ws: wsm.Workspace | None, active: wsm.SearchRun | None) -> None:
    """검색 상자의 검색 범위 한 줄 — 검색 전에 범위를 정하고(D-036), 검색 뒤 범위를 바꾸면 `이 범위로 다시 탐색` 이 나타난다(D-034).
    (기관 필터는 거의 쓰이지 않아 화면에서 뺐다 — 로직은 그대로 지원)"""
    S = st.session_state
    years_all, programs_all = filter_options(engine)
    c1, c2, c3 = st.columns([2.2, 3.4, 1.8], vertical_alignment="bottom")
    c1.multiselect("선정년도", years_all, key="f_years", placeholder="전체")
    c2.multiselect("대사업명", programs_all, key="f_programs", placeholder="전체")
    c3.checkbox("짧은 제목 제외", key="f_short")
    S["filters"] = filters_from_state()
    if ws is not None and active is not None and S["filters"] != active.filters:
        if st.button("이 범위로 다시 탐색", key="btn_refilter"):
            S["_refilter"] = True          # 실행은 호출자(검색 상자 끝)가 한다 — 진행 표시는 결과 자리에 그려진다


def run_refilter(ws: wsm.Workspace, engine: svc.SearchEngine, active: wsm.SearchRun | None) -> bool:
    """`이 범위로 다시 탐색` 의 실제 실행. 검색 상자 끝에서 부른다."""
    S = st.session_state
    if not S.pop("_refilter", False) or active is None:
        return False
    override = active.effective_query if active.query_origin == "user_edited" else None
    try:
        plan = wsm.build_effective_query(ws.idea_text, ws.elements, active.perspective, user_override=override)
    except wsm.WorkspaceError as e:
        st.error(str(e))
        return True
    execute(ws, plan, engine)
    return True


def render_perspective_row(ws: wsm.Workspace, engine: svc.SearchEngine, active: wsm.SearchRun | None) -> None:
    """[탐색 관점] [현재 검색문 …] [탐색] 한 줄. 관점은 검색문을 바꾸는 제안이고, 검색문은 언제나 직접 고칠 수 있다."""
    S = st.session_state
    plans = wsm.available_perspectives(ws.idea_text, ws.elements)      # 미리보기만, 실행 아님
    if "persp_seed" in S:
        S["persp"] = S.pop("persp_seed")
    if S.get("persp") not in wsm.PERSPECTIVES:
        S["persp"] = "full"
    seed = _take_query_seed()
    row = st.container(key="rc_persp")
    # 관점 줄은 검색문 줄 **위에** 따로 둔다 — 70% 검색 상자 안에서 세 열로 놓으면 세그먼트가 옆 열(현재 검색문)을 덮었다 (사용자 검토 2026-09-14)
    persp = row.segmented_control(
        "탐색 관점", wsm.PERSPECTIVES, key="persp", format_func=lambda k: PERSP_SHORT[k],
        help="관점에 따라 아래 검색문이 바뀝니다. ‘방법·접근’과 ‘대상·문제’는 탐색 요소를 재료로 씁니다.")
    persp = persp if persp in wsm.PERSPECTIVES else "full"
    plan = plans[persp]
    if not plan.available:
        row.info(plan.reason)
        with st.expander("탐색 요소 조정", expanded=True):
            render_elements_form(ws)
        return
    c2, c3 = row.columns([8.6, 1.0], vertical_alignment="bottom")
    key = f"query_edit_{persp}_{ws.revision}_{S.get('query_seq', 0)}"
    edited = c2.text_input("현재 검색문", value=seed if seed is not None else plan.effective_query, key=key,
                           help="이 문장이 그대로 검색에 들어갑니다. 직접 고칠 수 있고, 낱말을 자동으로 늘리지 않습니다.")
    run_it = c3.button("탐색", type="primary", key="btn_run_persp", width="stretch")
    override = edited if prep.normalize_text(edited or "") != plan.effective_query else None
    if override is not None:
        c2.markdown(f'<div class="rc-edited">{chip("", "직접 수정됨", "info")}'
                    f'<span>관점 제안: “{esc(clip(plan.effective_query, 60))}”</span></div>', unsafe_allow_html=True)
    with st.expander("탐색 요소 조정", expanded=bool(seed is None and not ws.elements and persp != "full")):
        render_elements_form(ws)                     # 검색 범위는 검색 상자의 범위 한 줄이 맡는다 (D-038)
    if run_it:
        try:
            final = wsm.build_effective_query(ws.idea_text, ws.elements, persp, user_override=override)
        except wsm.WorkspaceError as e:
            st.error(str(e))
            return
        execute(ws, final, engine)


def render_query_editor(ws: wsm.Workspace, engine: svc.SearchEngine, active: wsm.SearchRun | None) -> None:
    """UX-L 의 검색문 직접 수정 (관점 없음). 목록 조건에도 같은 편집 권한을 준다 (v2 §17.6)."""
    S = st.session_state
    run = ws.run(S["active_run_id"]) if S.get("active_run_id") else ws.latest_run()
    base = run.effective_query if run is not None else ws.idea_text
    seed = _take_query_seed()
    key = f"query_edit_l_{ws.revision}_{S.get('query_seq', 0)}"
    row = st.container(key="rc_persp")
    c2, c3 = row.columns([8.5, 1.0], vertical_alignment="bottom")
    edited = c2.text_input("현재 검색문", value=seed if seed is not None else base, key=key,
                           help="이 문장이 그대로 검색에 들어갑니다. 직접 고칠 수 있고, 낱말을 자동으로 늘리지 않습니다.")
    run_it = c3.button("탐색", type="primary", key="btn_run_query", width="stretch")
    if run_it:
        t = prep.normalize_text(edited or "")
        if not t:
            st.warning("검색문을 입력하세요.")
            return
        override = None if t == prep.normalize_text(ws.idea_text) else edited
        try:
            plan = wsm.build_effective_query(ws.idea_text, ws.elements, "full", user_override=override)
        except wsm.WorkspaceError as e:
            st.error(str(e))
            return
        execute(ws, plan, engine)


# ---------------------------------------------------------------------------
# 탐색 이력 · 결과 · 비교함
# ---------------------------------------------------------------------------
def _run_label(r: wsm.SearchRun, i: int) -> str:
    return f"#{i} {PERSP_SHORT[r.perspective]} · {clip(r.effective_query, 26)}"


def render_history(ws: wsm.Workspace) -> wsm.SearchRun | None:
    S = st.session_state
    runs = ws.search_runs
    if not runs:
        return None
    active_id = S.get("active_run_id") or runs[-1].run_id
    if len(runs) > 1:
        labels = {r.run_id: _run_label(r, i) for i, r in enumerate(runs, 1)}
        recent = runs[-RECENT_RUNS:]
        default = active_id if any(r.run_id == active_id for r in recent) else None
        pick = st.pills("최근 탐색", [r.run_id for r in recent], format_func=lambda k: labels[k], default=default,
                        key=f"hist_{len(runs)}", label_visibility="collapsed",
                        help="다시 검색하지 않고 그 결과로 표시만 바꿉니다.")
        if pick and pick != active_id:
            S["active_run_id"] = pick
            S["shown"] = DEFAULT_TOP_K
            st.rerun()              # 오른쪽 패널(비교함·구성)은 이 칩보다 먼저 그려졌다 — 같은 실행으로 맞춘다 (D-038)
    return ws.run(active_id)


def evidence_popover(row: wsm.ResultRow, run: wsm.SearchRun, n_corpus: int | None = None) -> None:
    """카드의 `검색 근거 보기` — 순위 두 가지(최종 표시 · 1차 의미검색 위치)를 다른 값으로 밝히고, 점수·식별자를 둔다.
    카드 본문에서 뺀 개발자성 정보는 여기에만."""
    with st.popover("검색 근거 보기", width="stretch"):
        st.markdown(f'<div class="rc-ev"><div class="ttl">{esc(row.title_raw)}</div></div>', unsafe_allow_html=True)
        order_basis = "재정렬 점수 순" if (run.rerank_applied and row.rerank_score is not None) else "의미 유사도 순"
        kv = [("최종 표시 순위", f'<span class="v">{row.rank}위</span> <span class="x">— 이 목록의 순서 ({esc(order_basis)})</span>'),
              ("1차 의미검색 위치", f'<span class="v">{esc(pct_text(row.percentile_label, n_corpus))}</span> '
                                 '<span class="x">— 재정렬 전 의미 유사도 위치. 최종 순위와 다를 수 있음</span>'),
              ("의미 유사도", f'<span class="v">{row.semantic_score:.3f}</span> '
                          '<span class="x">— 검색문과 제목이 의미상 가까운 정도. 0~1 상대 점수이며 정확도·확률이 아님</span>')]
        if run.rerank_applied and row.rerank_score is not None:
            kv.append(("재정렬 점수", f'<span class="v">{row.rerank_score:.3f}</span> '
                                  '<span class="x">— 최종 순서를 정한 값. 확률·정확도가 아님</span>'))
        if row.relevance_gate == svc.GATE_PASS:            # tau 가 확정된 경우에만 행이 생긴다. 미확정이면 행을 두지 않는다 —
            kv.append(("관련도 기준선", "기준값 이상"))       # "없음" 을 알리는 행은 사용자에게 줄 정보가 없다 (사용자 검토 2026-09-14).
        elif row.relevance_gate == svc.GATE_FAIL:          # 미확정 사실은 기능 상태표('관련 과제 N건' 집계 = 미검증)에 있다
            kv.append(("관련도 기준선", "기준값 미만"))
        if row.short_title:
            kv.append(("제목 길이", '<span class="x">10자 미만 짧은 제목 — 의미 비교가 불안정할 수 있음</span>'))
        ids = [("원본 행", f"{row.source_row}행"),
               ("레코드 ID", f"<code>{esc(row.record_id)}</code>"),
               ("스냅샷", f"<code>{esc(row.source_snapshot_id)}</code>")]
        st.markdown('<div class="rc-kv">' + "".join(f"<div><b>{esc(k)}</b>{v}</div>" for k, v in kv)
                    + '<div class="ids">' + "".join(f"<div><b>{esc(k)}</b>{v}</div>" for k, v in ids) + "</div></div>",
                    unsafe_allow_html=True)
        if SOURCE_URL_D1:
            st.caption(f"원본 데이터 페이지: {SOURCE_URL_D1}")


def result_card_html(row: wsm.ResultRow, i: int, anim: bool, reranked: bool, n_corpus: int | None = None) -> str:
    """결과 카드 본문 — 순위 · 제목 · 기관 · 선정연도 · 사업 · 의미 유사도. 백분위·재정렬 점수·정렬 막대는 `검색 근거 보기` 에만."""
    tags = []
    if row.short_title:
        tags.append('<span class="rc-tag warn">짧은 제목</span>')
    if row.relevance_gate == svc.GATE_PASS:              # tau 미확정(uncalibrated)이면 태그 없음
        tags.append('<span class="rc-tag accent">기준값 이상</span>')
    elif row.relevance_gate == svc.GATE_FAIL:
        tags.append('<span class="rc-tag">기준값 미만</span>')
    year = f"{row.selection_year}년 선정" if row.selection_year is not None else "선정연도 미상"
    meta = " · ".join(x for x in (esc(row.institution), year, esc(row.program)) if x)
    sim_tip = "검색문과 제목이 의미상 가까운 정도. 0~1 상대 점수이며 정확도·관련성 판정이 아닙니다"
    score = f'<span class="sim" title="{esc(sim_tip)}">의미 유사도 <b>{row.semantic_score:.3f}</b></span>'
    return (f'<div class="rc-card">'
            f'<div class="title"><span class="rank">{row.rank}</span><span class="t">{esc(row.title_raw)}{"".join(tags)}</span></div>'
            f'<div class="meta">{meta}</div>'
            f'<div class="rc-score">{score}</div></div>')


def render_status(ws: wsm.Workspace, run: wsm.SearchRun, shown: int) -> None:
    S = st.session_state
    info = S["run_stats"].get(run.run_id, {})
    stats = info.get("stats", {})
    section("제목이 유사한 과제", f"{shown}건")
    q = run.effective_query                           # 요약 붙여넣기는 문단이 그대로 검색문 — 상태 줄에서는 줄이고 전체는 툴팁에
    sub = (f"{esc(PERSP_SHORT.get(run.perspective, run.perspective))} · 검색문 "
           f'<b title="{esc(q)}">{esc(clip(q, 160))}</b>')
    tags = []
    if run.query_origin == "user_edited":
        tags.append(chip("", "직접 수정됨", "info"))
    if run.idea_revision != ws.idea_revision:
        tags.append(chip("", "이전 연구주제의 결과", "warn"))
    if run.run_mode != "local_live":
        mode_label, mode_kind = MODE_LABELS.get(run.run_mode, MODE_LABELS["unknown"])
        tags.append(chip("", mode_label, mode_kind))
    if run.actual_engine != run.requested_engine:
        tags.append(chip("", "다른 검색 방식으로 실행됨", "warn"))
    st.markdown(f'<div class="rc-sub">{sub}{" ".join(tags)}</div>', unsafe_allow_html=True)
    n_after, n_corpus = stats.get("n_after_filter"), stats.get("n_corpus")
    facts = []
    if n_after is not None and n_corpus is not None:
        facts.append(f"{n_corpus:,}건에서 검색" if n_after == n_corpus
                     else f"전체 {n_corpus:,}건 중 {n_after:,}건에서 검색")
    ft = filters_text(run.filters)
    if ft:
        facts.append("범위: " + ft)
    facts.append(secs(run.latency_ms.get("total_s")))
    st.markdown(f'<div class="rc-meta">{esc(" · ".join(facts))}</div>', unsafe_allow_html=True)


def render_results(ws: wsm.Workspace, run: wsm.SearchRun, ux: str = "w") -> None:
    S = st.session_state
    info = S["run_stats"].get(run.run_id, {})
    shown = min(S.get("shown", DEFAULT_TOP_K), len(run.results))
    if not run.results:
        st.warning("검색 범위 안에 결과가 없습니다. 범위를 넓혀 보세요.")
        return
    if run.rerank_badge:                 # 엔진 메모(notes)는 개발자 문장이라 여기 붙이지 않는다 — `검색 상세 정보` 실행 로그에 그대로 있다
        st.warning(f"{run.rerank_badge} — 의미 유사도 순서로 표시합니다.")
    for w in run.warnings:
        if w == svc.HYBRID_DISABLED_BY_EVAL:
            st.warning("평가에서 기준 미달로 꺼둔 어휘 결합이 명시적으로 켜졌습니다.")

    rows = list(run.results[:shown])
    st.markdown('<p class="rc-note">제목의 의미만 비교한 결과입니다. 연구내용은 원문에서 확인하세요.</p>',
                unsafe_allow_html=True)
    anim = bool(S.get("just_ran"))
    n_corpus = info.get("stats", {}).get("n_corpus")
    for i, row in enumerate(rows):
        with st.container(border=True, key=f"rc_card_{i}"):
            st.markdown(result_card_html(row, i, anim, run.rerank_applied, n_corpus), unsafe_allow_html=True)
            if ux == "l":                       # 목록 전용 조건 — 담기 없음 (v2 §17.6)
                b1, _ = st.columns([1.2, 5])
                with b1:
                    evidence_popover(row, run, n_corpus)
                continue
            in_basket = any(s.record_id == row.record_id and s.source_snapshot_id == row.source_snapshot_id
                            for s in ws.selected)
            b1, b2, _ = st.columns([1.35, 1.45, 3.85])
            if b1.button("✓ 담김" if in_basket else "비교함에 담기", key=f"sel_{run.run_id}_{row.record_id}",
                         disabled=in_basket, width="stretch"):
                try:
                    ws.select(run.run_id, row.record_id)
                    st.rerun()
                except wsm.WorkspaceError as e:
                    st.error(str(e))
            with b2:
                evidence_popover(row, run, n_corpus)

    b1, b2, _ = st.columns([1, 1, 4])
    if shown < len(run.results):
        if b1.button(f"더 보기 (+{min(5, len(run.results) - shown)})", key="btn_more"):
            S["shown"] = min(shown + 5, len(run.results), MAX_TOP_K)
            st.rerun()
    if shown > DEFAULT_TOP_K:
        if b2.button("접기", key="btn_less"):
            S["shown"] = DEFAULT_TOP_K
            st.rerun()


def basket_card(s: wsm.SelectedProject, in_view: bool) -> str:
    r = s.project_record
    year = f"{r.selection_year}년" if r.selection_year is not None else "선정연도 미상"
    meta = " · ".join(x for x in (esc(r.institution), year) if x)
    out_tag = "" if in_view else '<span class="rc-tag warn">지금 보는 결과에 없음</span>'
    return (f'<div class="rc-bk"><div class="title"><span class="rank">E{s.selection_order}</span>'
            f'<span class="t">{esc(r.title_raw)}{out_tag}</span></div><div class="meta">{meta}</div></div>')


def render_basket(ws: wsm.Workspace, active: wsm.SearchRun | None) -> None:
    """비교함 패널 — 0건: 담아 달라는 한 줄 · 1건: 한 개 더 · 2건 이상: 안내 없이 목록만."""
    n = len(ws.selected)
    with st.container(border=True, key="rc_basket"):
        st.markdown(f'<div class="rc-h">비교함<span class="count">{n}개</span></div>', unsafe_allow_html=True)
        if not ws.selected:
            st.markdown('<div class="rc-empty">비교할 과제를 담아 주세요.</div>', unsafe_allow_html=True)
            return
        in_view = {(r.source_snapshot_id, r.record_id) for r in (active.results if active else ())}
        for s in ws.selected:
            c1, c2 = st.columns([4.6, 1.6], vertical_alignment="center")
            c1.markdown(basket_card(s, (s.source_snapshot_id, s.record_id) in in_view), unsafe_allow_html=True)
            if c2.button("빼기", key=f"desel_{s.source_snapshot_id}_{s.record_id}", width="stretch",
                         help="검색 결과에서는 사라지지 않습니다"):
                ws.deselect(s.record_id, s.source_snapshot_id)
                st.rerun()
        if n == 1:
            st.markdown('<div class="rc-hint">한 개 더 담으면 비교할 수 있습니다.</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 선택한 과제 비교 · 탐색 메모 (로직은 comparison / nextactions / memo)
# ---------------------------------------------------------------------------
def current_refs(ws: wsm.Workspace) -> list[cmp.TitleRef]:
    return [cmp.TitleRef(record_id=s.record_id, source_snapshot_id=s.source_snapshot_id,
                         source_dataset_id=s.project_record.source_dataset_id or s.source_snapshot_id.split("-")[0],
                         title_raw=s.project_record.title_raw) for s in ws.selected]


def refresh_observations(ws: wsm.Workspace) -> tuple[list[cmp.EvidenceObservation], list[cmp.EvidenceObservation]]:
    """요소 × 비교함 자동 관측을 다시 만들고 (이전 세션 검토가 있으면) 보존한다. 요소·원문이 바뀐 것은 stale."""
    S = st.session_state
    auto = cmp.build_matrix(ws.elements, current_refs(ws))
    merged, stale = cmp.merge_reviews(auto, list(S["observations"].values()))
    S["observations"] = {o.observation_id: o for o in merged}
    known = {o.observation_id for o in S["stale_observations"]}
    S["stale_observations"] = S["stale_observations"] + [o for o in stale if o.observation_id not in known]
    cur = {(o.element_id, o.source_snapshot_id, o.record_id): o.element_revision for o in merged}
    S["stale_observations"] = [o for o in S["stale_observations"]
                               if cur.get((o.element_id, o.source_snapshot_id, o.record_id)) not in (None, o.element_revision)]
    return merged, S["stale_observations"]


def matrix_cell(o: cmp.EvidenceObservation) -> str:
    """비교표 한 칸 — 제목에 있음 / 제목에 없음. 없음을 '연구에 없음' 으로 바꾸지 않는다."""
    if o.finding == "expression_found" and o.review_status != "rejected":
        return '<span class="rc-cell found">제목에 있음</span>'
    return '<span class="rc-cell none">제목에 없음</span>'


def unresolved_elements(ws: wsm.Workspace, observations: list[cmp.EvidenceObservation]) -> list:
    """표에서 '없음' 으로 남은 요소 — 원문 확인이 필요한 것."""
    out = []
    for e in sorted(ws.elements, key=lambda x: wsm.ROLES.index(x.role)):
        if any(o.element_id == e.element_id and not (o.finding == "expression_found" and o.review_status != "rejected")
               for o in observations):
            out.append(e)
    return out


PROGRAM_LEVELS = ("대사업명", "중사업명", "소사업명", "세부사업명")
PROGRAM_LEVEL_SHORT = {"대사업명": "대사업", "중사업명": "중사업", "소사업명": "소사업", "세부사업명": "세부사업"}
NEEDS_REVIEW_HINT = "제목에 이 낱말이 없을 뿐, 그 연구에 없다는 뜻은 아닙니다. 원문의 연구목표·요약에서 확인하세요."


def _clean(v) -> str:
    """정제 데이터 칸 값 → 표시 문자열. NaN·None·'nan' 은 빈칸 (0 이나 '미상' 으로 바꾸지 않는다)."""
    if v is None or (isinstance(v, float) and v != v):
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none") else s


def project_row(engine, record_id: str):
    """정제 데이터(engine.projects)에서 이 레코드의 행. 없으면 None (시험용 가짜 엔진 등)."""
    p = getattr(engine, "projects", None)
    if p is None or "record_id" not in p.columns:
        return None, p
    hit = p[p["record_id"] == record_id]
    return (hit.iloc[0] if len(hit) else None), p


def program_levels(row, p, fallback: str) -> list[tuple[str, str]]:
    """(단계, 값) — 값이 있는 단계만, 대사업 → 세부사업 순. 원본 D1 의 사업명 계층 4개 컬럼."""
    out: list[tuple[str, str]] = []
    if row is not None:
        for lv in PROGRAM_LEVELS:
            col = f"program_{lv}"
            if col in p.columns:
                v = _clean(row[col])
                if v:
                    out.append((lv, v))
    if not out and fallback:
        out.append(("대사업명", fallback))
    return out


def count_same(p, col: str, value: str) -> tuple[int, list[tuple[int, int]]]:
    """전체 수록 데이터(dataset_snapshot 범위)에서 col == value 인 **수록 레코드 수**와 선정연도별 수.
    기술통계일 뿐 관련성·추세 판정이 아니다 (D-012: 연도 차이를 지원 증감으로 읽지 않는다)."""
    if p is None or col not in p.columns or not value:
        return 0, []
    mask = p[col].astype(str).str.strip() == value
    n = int(mask.sum())
    counts: dict[int, int] = {}
    if "selection_year" in p.columns:
        for y in p.loc[mask, "selection_year"].dropna().tolist():
            try:
                counts[int(y)] = counts.get(int(y), 0) + 1
            except (TypeError, ValueError):
                continue
    return n, sorted(counts.items())


def program_path_text(levels: list[tuple[str, str]]) -> str:
    return " › ".join(v for _, v in levels)


def _ref_head(selected) -> str:
    return "".join(f'<th><span class="ref">E{i}</span><span class="ttl" title="{esc(s_.project_record.title_raw)}">'
                   f'{esc(clip(s_.project_record.title_raw, 38))}</span></th>' for i, s_ in enumerate(selected, 1))


def _table(head: str, rows: list[tuple[str, str, list[str]]], first_col: str = "") -> str:
    body = ""
    for label, note, cells in rows:
        n = f'<div class="rc-note">{esc(note)}</div>' if note else ""
        body += f"<tr><td><b>{esc(label)}</b>{n}</td>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"
    return (f'<table class="rc-table"><thead><tr><th style="width:22%">{esc(first_col)}</th>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table>")


def render_evidence(ws: wsm.Workspace, engine) -> list[cmp.EvidenceObservation]:
    """선택한 과제 비교 — 과제(열) × 행. 가장 중요한 정보는 '이 과제를 어느 탐색에서 발견했는가' 이므로
    탐색 관점 → 검색문 → 당시 순위를 앞에, 선정연도 · 사업 · 기관 · 원본 위치를 그 뒤에 둔다 (D-035).
    같은 사업·같은 기관의 수록 레코드 수(D-033)는 보조 접힘. 값은 전부 원본 D1 에 있거나 수록 데이터에서 센 것이다.
    담은 과제가 0~1건이면 큰 빈 절 대신 한 줄만 둔다. 요소별 제목 표현 비교는 `데이터 및 검색 정보` 아래 접힘(render_element_matrix)."""
    S = st.session_state
    sel = ws.selected
    if not sel:
        st.markdown('<div class="rc-compact"><b>선택한 과제 비교</b>과제 2개 이상을 담으면 탐색 관점과 '
                    '기관·선정연도·사업을 나란히 놓습니다.</div>', unsafe_allow_html=True)
        S["_program_paths"] = {}
        return []
    refs = current_refs(ws)
    S["_refs"] = {(r.source_snapshot_id, r.record_id): r for r in refs}
    observations, _stale = refresh_observations(ws)

    p_all = getattr(engine, "projects", None)
    total = int(len(p_all)) if p_all is not None else 0
    facts = []
    paths: dict[tuple[str, str], str] = {}
    for s_ in sel:
        r = s_.project_record
        row, p = project_row(engine, s_.record_id)
        levels = program_levels(row, p, r.program)
        fine_lv, fine_val = levels[-1] if levels else ("", "")
        n_prog, y_prog = count_same(p, f"program_{fine_lv}", fine_val) if fine_lv else (0, [])
        n_inst, y_inst = count_same(p, "institution", r.institution)
        facts.append({"levels": levels, "fine_lv": fine_lv, "n_prog": n_prog, "y_prog": y_prog,
                      "n_inst": n_inst, "y_inst": y_inst})
        paths[(s_.source_snapshot_id, s_.record_id)] = program_path_text(levels)
    S["_program_paths"] = paths                       # 메모 압축판이 사업 계층을 쓴다 — 1건일 때도 계산해 둔다

    if len(sel) < 2:
        st.markdown('<div class="rc-compact"><b>선택한 과제 비교</b>1건 담김</div>', unsafe_allow_html=True)
        return observations

    section("선택한 과제 비교", f"{len(sel)}건")

    def origins(s_) -> list[tuple[str, str, int]]:
        out = []
        for o in s_.origin_runs:
            run = ws.run(o["run_id"])
            out.append((PERSP_SHORT.get(o["perspective"], o["perspective"]), run.effective_query if run else "", int(o["rank"])))
        return out

    def lines(items: list[str]) -> str:
        """한 과제가 여러 검색에서 발견되면 ①②… 로 줄을 매겨 세 행(관점·검색문·순위)이 같은 번호로 읽히게 한다."""
        if not items:
            return "—"
        if len(items) == 1:
            return items[0]
        return "".join(f'<div class="rc-ln"><span class="n">{i}</span><span>{x}</span></div>' for i, x in enumerate(items, 1))

    def years_note(ys, prefix: str = "") -> str:
        parts = ([prefix] if prefix else []) + [f"{y}년 {n:,}" for y, n in ys]
        return f'<div class="rc-note">{esc(" · ".join(parts))}</div>' if parts else ""

    def count_cell(n: int, ys, prefix: str = "") -> str:
        return f"{n:,}건" + years_note(ys, prefix) if n else "—"

    def path_cell(levels) -> str:
        if not levels:
            return "—"
        return '<div class="rc-path">' + ' <span class="sep">›</span> '.join(esc(v) for _, v in levels) + "</div>"

    def source_cell(s_) -> str:
        link = (f'<a href="{esc(SOURCE_URL_D1)}" target="_blank" rel="noopener">원본 데이터 페이지 ↗</a>'
                if SOURCE_URL_D1 else "원본 데이터 페이지 —")
        return f'{link}<div class="rc-note">원본 행 {s_.project_record.source_row}</div>'

    org = [origins(s_) for s_ in sel]
    rows = [
        ("탐색 관점", "", [lines([esc(pp) for pp, _, _ in o]) for o in org]),
        ("검색문", "", [lines([f'<span class="q">“{esc(q)}”</span>' for _, q, _ in o]) for o in org]),
        ("당시 순위", "", [lines([f"{rk}위" for _, _, rk in o]) for o in org]),
        ("선정연도", "", [f"{s_.project_record.selection_year}년" if s_.project_record.selection_year is not None else "—"
                        for s_ in sel]),
        ("사업", "", [path_cell(f["levels"]) for f in facts]),
        ("기관", "", [esc(s_.project_record.institution) or "—" for s_ in sel]),
        ("원본 위치", "", [source_cell(s_) for s_ in sel]),
    ]
    head = _ref_head(sel)
    st.markdown(_table(head, rows), unsafe_allow_html=True)
    with st.expander("수록 데이터 기준 참고"):
        rows2 = [
            ("같은 사업의 수록 레코드", f"수록 {total:,}건 중",
             [count_cell(f["n_prog"], f["y_prog"], PROGRAM_LEVEL_SHORT.get(f["fine_lv"], "") + " 기준" if f["fine_lv"] else "")
              for f in facts]),
            ("같은 기관의 수록 레코드", f"수록 {total:,}건 중", [count_cell(f["n_inst"], f["y_inst"]) for f in facts]),
        ]
        st.markdown(_table(head, rows2), unsafe_allow_html=True)
        st.caption("수록 레코드 수이며, 연도별 차이는 지원 규모의 증감을 뜻하지 않습니다.")
    return observations


def render_element_matrix(ws: wsm.Workspace, observations: list[cmp.EvidenceObservation]) -> None:
    """요소 × 과제 제목 표현 비교 — 참고용 접힘 (D-033). 자동 판정은 '제목에 그 낱말이 있는가' 하나뿐이다."""
    if not ws.selected or not ws.elements or not observations:
        return
    with st.expander("요소별 제목 표현 비교"):
        by_key = {(o.element_id, o.source_snapshot_id, o.record_id): o for o in observations}
        head = "".join(f'<th><span class="ref">E{i}</span><span class="ttl" title="{esc(s_.project_record.title_raw)}">'
                       f'{esc(clip(s_.project_record.title_raw, 38))}</span></th>' for i, s_ in enumerate(ws.selected, 1))
        body = ""
        for e in sorted(ws.elements, key=lambda x: wsm.ROLES.index(x.role)):
            cells = "".join(f"<td>{matrix_cell(by_key[(e.element_id, s_.source_snapshot_id, s_.record_id)])}</td>"
                            if (e.element_id, s_.source_snapshot_id, s_.record_id) in by_key else "<td>—</td>"
                            for s_ in ws.selected)
            body += f'<tr><td><b>{esc(e.text)}</b><div class="rc-note">{esc(wsm.ROLE_LABELS[e.role])}</div></td>{cells}</tr>'
        st.markdown(f'<table class="rc-table"><thead><tr><th style="width:22%">탐색 요소</th>{head}</tr></thead>'
                    f'<tbody>{body}</tbody></table>', unsafe_allow_html=True)
        todo = unresolved_elements(ws, observations)
        if todo:
            names = " · ".join(f"<b>{esc(e.text)}</b>" for e in todo)
            st.markdown(f'<div class="rc-notice" title="{NEEDS_REVIEW_HINT}">확인이 필요한 요소: {names}</div>',
                        unsafe_allow_html=True)


def compute_actions(ws: wsm.Workspace, observations: list[cmp.EvidenceObservation]) -> list[na.NextAction]:
    """규칙 기반 확인 작업(로직은 nextactions) — 화면에는 없고 메모의 '다음 탐색·확인' 절에 제안으로 들어간다."""
    S = st.session_state
    if not ws.search_runs:
        return []
    plans = wsm.available_perspectives(ws.idea_text, ws.elements)
    return na.propose(ws, observations, plans, insufficient=False, field_selections=S["field_selections"])


MEMO_KEEP_NOTE = "메모는 현재 브라우저 세션에만 유지되며 서버에 저장되지 않습니다."


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sync_box() -> dict:
    """세션 동안 같은 객체로 남는 상자. 지연 다운로드 callable 이 실행 번호를 읽어 '클릭이 일으킨 재실행이 시작됐는지' 를 안다."""
    return st.session_state.setdefault("_sync", {"run": 0})


def _wait_for_rerun(sync: dict, seen: int, timeout: float = 1.2) -> None:
    """내려받기 클릭 → (메모 칸 blur 로 값 전송) → 재실행 시작(위젯 콜백이 ws.user_notes 갱신) 순서를 기다린다.

    Streamlit 지연 다운로드는 클릭 직후 별도 스레드에서 callable 을 부르므로, 기다리지 않으면 마지막으로 쓴 글이 빠진
    파일이 만들어진다(실측). 글이 바뀌었으면 blur 가 재실행을 일으켜 수십 ms 안에 풀리고, 바뀐 게 없으면 재실행이 없어
    timeout 만큼만 기다린다. 버튼은 on_click="ignore" — 클릭 자체가 재실행을 일으키면 프런트엔드가 버튼을 다시 그려
    진행 중인 내려받기 응답을 버린다(실측: 파일이 내려오지 않음)."""
    t0 = time.monotonic()
    while sync.get("run", 0) <= seen and time.monotonic() - t0 < timeout:
        time.sleep(0.05)


def _sync_notes(ws: wsm.Workspace, key: str) -> None:
    """메모 칸 값을 작업공간에 즉시 반영한다 (위젯 콜백 — 내려받기 파일이 마지막으로 쓴 글을 담도록)."""
    v = st.session_state.get(key)
    ws.user_notes = (v or "").strip() or None


def render_memo(ws: wsm.Workspace, states: dict, observations: list[cmp.EvidenceObservation],
                actions: list[na.NextAction]) -> None:
    """탐색 메모 — 최종 산출물. 자유 메모 → 저장(Markdown)/백업(JSON) → 미리보기.
    내려받기 파일은 **클릭 시점에** 만든다(Streamlit 지연 다운로드) — 칸 밖을 먼저 클릭하라는 안내가 필요 없다."""
    S = st.session_state
    section("탐색 메모")
    if "free_memo" not in S and ws.user_notes:
        S["free_memo"] = ws.user_notes      # st.rerun 으로 위젯이 한 실행 건너뛰면 Streamlit 이 상태를 지운다 → 작업공간 값으로 복원 (D-033)
    txt = st.text_area("자유 메모", key="free_memo", height=140, label_visibility="collapsed",
                       placeholder="고른 이유, 확인하지 못한 점, 다음에 확인할 것",
                       on_change=_sync_notes, args=(ws, "free_memo"))
    ws.user_notes = (txt or "").strip() or None
    try:
        manifests = [] if "_engine_override" in S else load_manifests(str(ROOT), str(CFG_PATH))
    except Exception:
        manifests = []
    all_obs = observations + list(S.get("stale_observations", []))
    program_paths = dict(S.get("_program_paths", {}))
    sync, seen = _sync_box(), _sync_box()["run"]

    def make_snapshot() -> dict:
        return wsm.snapshot(ws, capabilities=states, observations=[o.to_dict() for o in all_obs],
                            next_actions=[a.to_dict() for a in actions], source_manifests=manifests)

    snap = make_snapshot()
    try:
        res = memo_mod.build(snap, all_obs, actions, generated_at=_utc_now(), source_url=SOURCE_URL_D1)
    except memo_mod.MemoError as e:
        st.error(f"메모를 만들 수 없습니다: {e}")
        return
    if res.problems:
        st.warning("검증에 실패한 근거는 메모에서 제외했습니다: " + "; ".join(res.problems))
    brief = memo_mod.build_brief(snap, generated_at=_utc_now(), source_url=SOURCE_URL_D1, program_paths=program_paths)

    def brief_now() -> bytes:
        """저장 클릭 시점의 작업공간(마지막으로 쓴 메모 포함)으로 압축 메모를 만든다."""
        _wait_for_rerun(sync, seen)
        try:
            return memo_mod.build_brief(make_snapshot(), generated_at=_utc_now(), source_url=SOURCE_URL_D1,
                                        program_paths=program_paths).encode("utf-8")
        except memo_mod.MemoError as e:
            return f"메모를 만들 수 없습니다: {e}\n".encode("utf-8")

    def json_now() -> bytes:
        _wait_for_rerun(sync, seen)
        try:
            r = memo_mod.build(make_snapshot(), all_obs, actions, generated_at=_utc_now(), source_url=SOURCE_URL_D1)
            return memo_mod.to_json(r).encode("utf-8")
        except memo_mod.MemoError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")

    d1, d2, _ = st.columns([1.4, 1.4, 3.2])
    d1.download_button("탐색 메모 저장", data=brief_now, file_name="research_compass_memo.md", mime="text/markdown",
                       key="dl_memo_md", on_click="ignore", width="stretch",
                       help="Markdown(.md) — 선택한 과제와 탐색 기록, 메모")
    d2.download_button("전체 작업기록 백업", data=json_now, file_name="research_compass_workspace.json", mime="application/json",
                       key="dl_memo_json", on_click="ignore", width="stretch",
                       help="JSON(.json) — 모든 검색 실행과 선택, 관측, 출처 정보")
    st.caption(MEMO_KEEP_NOTE)
    with st.expander("메모 미리보기", expanded=False):
        st.markdown(brief)                                       # 원문·사용자 텍스트는 memo 가 escape 했다


def render_free_memo(ws: wsm.Workspace) -> None:
    """UX-L 의 자유 메모 — 두 조건에 같은 기록·반출 수단을 준다 (v2 §17.6). 자동 문장을 만들지 않는다."""
    S = st.session_state
    section("자유 메모")
    if "free_memo" not in S and ws.user_notes:
        S["free_memo"] = ws.user_notes      # st.rerun 으로 위젯이 한 실행 건너뛰면 Streamlit 이 상태를 지운다 → 작업공간 값으로 복원 (D-033)
    txt = st.text_area("자유 메모", key="free_memo", height=140, label_visibility="collapsed",
                       placeholder="고른 이유, 확인하지 못한 점, 다음에 확인할 것",
                       on_change=_sync_notes, args=(ws, "free_memo"))
    ws.user_notes = (txt or "").strip() or None

    sync, seen = _sync_box(), _sync_box()["run"]

    def doc_now() -> bytes:
        _wait_for_rerun(sync, seen)
        return memo_mod.free_memo(ws.user_notes or "", idea_text=ws.idea_text, generated_at=_utc_now()).encode("utf-8")

    st.download_button("메모 저장", data=doc_now, file_name="research_compass_notes.md", mime="text/markdown",
                       key="dl_free_memo", on_click="ignore", help="Markdown(.md)")
    st.caption(MEMO_KEEP_NOTE)


# ---------------------------------------------------------------------------
# 데이터·기능 정보 (접힘) — 관련 연구분야 · 데이터 범위와 제약 · 검색 상세 분석 · 기능 및 검증 상태
# ---------------------------------------------------------------------------
def render_field_search(ws: wsm.Workspace | None, engine: svc.SearchEngine, states: dict, ux: str = "w") -> None:
    S = st.session_state
    with st.expander("관련 연구분야"):
        fields, fidx, why = field_index(states)
        if fields is None:
            st.info(why)
            return
        st.caption("**분야 이름 한 줄**만 주제 문장과 비교한 결과라 무관한 분야가 섞일 수 있습니다. "
                   "개별 과제의 공식 분류가 아니며 과제에 분야를 배정하지 않습니다.")
        render_field_notice()
        q = st.text_input("분야명을 찾을 문장", value=(ws.idea_text if ws else ""),
                          key=f"fq_{ws.idea_revision if ws else 0}")
        if st.button("분야명 찾기", key="btn_fields") and prep.normalize_text(q or ""):
            S["field_hits"] = field_hits(engine, fields, fidx, prep.normalize_text(q))

        def pick(h: dict) -> None:
            S["query_seed"] = h["name"]
            if ux != "l":
                sel = {"field_record_id": h["code"], "field_name": h["name"]}
                if sel not in S["field_selections"]:
                    S["field_selections"].append(sel)
            st.rerun()

        render_field_hits(S.get("field_hits"), "검색문에 넣기", "위 현재 검색문 칸에 넣습니다. 검색은 실행되지 않습니다.", "fld", pick)


FIELD_COUNT_HINT = "원문 값 그대로입니다. 선정횟수의 기준연도가 확인되지 않아(컬럼명 2025년 · 설명문 2023년) 분야 간 비교나 순위에 쓰지 않습니다."


def field_index(states: dict):
    """D2 분야명 인덱스 — (fields, fidx, None) 또는 (None, None, 안 되는 이유). 첫 화면과 결과 화면이 같이 쓴다."""
    fs = states.get("field_name_search", {})
    if fs.get("status") != "available":
        return None, None, f"분야명 찾기를 제공하지 않습니다: {plain(fs.get('reason', ''))}"
    if "_engine_override" in st.session_state:
        return None, None, "시험 모드에서는 분야 인덱스를 적재하지 않습니다."
    try:
        fields, fidx = load_fields(str(ROOT), str(CFG_PATH), CFG_PATH.stat().st_mtime)
    except Exception as e:
        return None, None, f"분야 인덱스 준비 안 됨: {type(e).__name__}: {e}"
    return fields, fidx, None


def render_field_notice() -> None:
    """선정횟수 기준연도 충돌 — 짧은 경고 한 줄 + 자세히. 분야명 결과가 보이는 곳마다 붙인다 (절대 규칙)."""
    w1, w2 = st.columns([5, 1], vertical_alignment="center")
    w1.markdown('<div class="rc-callout">선정횟수의 기준연도가 확인되지 않아 분야 간 비교는 제공하지 않습니다.</div>',
                unsafe_allow_html=True)
    with w2.popover("자세히", width="stretch"):
        st.write("원본에서 선정횟수의 기준연도가 어긋납니다 — 컬럼명은 2025년, 설명문은 2023년. 그래서 분야 간 비교·순위를 "
                 "제공하지 않고 원문 값만 참고로 보여 줍니다. 코드표에 있으나 자료에 없는 분야는 ‘선정 0건’이 아니라 "
                 "‘관측 없음’이며, 연도별 추세도 만들지 않습니다.")


def field_hits(engine: svc.SearchEngine, fields, fidx, qn: str) -> dict:
    qv = engine.semantic["embedder"].encode([qn])[0]
    sc = fidx.scores(qv)
    order = sorted(range(len(sc)), key=lambda i: -float(sc[i]))[:FIELD_TOP_N]
    return {"query": qn, "rows": [
        {"name": str(fields.iloc[i]["field_name"]), "code": str(fields.iloc[i]["field_code"]),
         "score": float(sc[i]), "count_raw": fields.iloc[i]["selection_count"],
         "count_col": str(fields.iloc[i]["count_column_raw"]),
         "scheme": str(fields.iloc[i]["classification_scheme"])} for i in order]}


def render_field_hits(hits: dict | None, button: str, help_text: str, key_prefix: str, on_pick) -> None:
    if not hits:
        return
    st.markdown(f'<div class="rc-note">“{esc(hits["query"])}”와 이름이 가까운 분야 {len(hits["rows"])}개</div>',
                unsafe_allow_html=True)
    for j, h in enumerate(hits["rows"]):
        c1, c2 = st.columns([6, 2], vertical_alignment="center")
        cnt = h["count_raw"]
        cnt_txt = (f"{int(cnt)}" if cnt == cnt and cnt is not None else "미상")
        c1.markdown(f'<div class="rc-card"><div class="title"><span class="rank">{j + 1}</span>{esc(h["name"])}'
                    f'<span class="rc-tag">분류코드 {esc(h["code"])} · {esc(h["scheme"])}년 체계</span></div>'
                    f'<div class="meta">의미 유사도 {h["score"]:.3f} · {esc(h["count_col"])} {cnt_txt} '
                    f'<span class="sec" title="{esc(FIELD_COUNT_HINT)}">(비교 불가)</span></div></div>',
                    unsafe_allow_html=True)
        if c2.button(button, key=f"{key_prefix}_{j}", help=help_text):
            on_pick(h)


def render_dataset_panel(engine: svc.SearchEngine, p: dict) -> None:
    n, span = corpus_facts(engine)
    with st.expander("데이터 범위와 한계"):
        st.markdown(f"- {span} 수록 {n:,}건. 제목과 공개 메타데이터만 씁니다. "
                    "초록·연구내용은 원본에 없고, 개인식별 컬럼은 싣지 않았습니다.\n"
                    "- 목록은 가까운 검색 결과이며 관련 과제 판정이 아닙니다. 점수는 상대 점수로, 정확도·확률이 아닙니다.\n"
                    "- 같은 제목의 행을 합치지 않았고, 결측을 0 으로 바꾸지 않았습니다.")
        st.markdown('<div class="rc-callout">아래는 <b>수록 레코드 수</b>입니다. 사업별 수록 범위가 연도마다 달라 '
                    '연도별 차이를 지원 규모의 증감으로 해석하지 않습니다.</div>', unsafe_allow_html=True)
        render_composition(dataset_records(engine), "dataset_snapshot", [], {}, p)


def render_side_composition(run: wsm.SearchRun, shown: int, p: dict) -> None:
    """결과 화면 오른쪽 — 표시 중인 결과의 선정연도·대사업명 구성 (D-036). 10건 이하는 D-026 에 따라 차트 대신 글 한 줄."""
    rows = list(run.results[:shown])
    if not rows:
        return
    with st.container(border=True, key="rc_side"):
        st.markdown(f'<div class="rc-h">표시 중인 {len(rows)}건의 구성</div>', unsafe_allow_html=True)
        render_composition(rows_as_records(rows), "displayed_results", [run.run_id], run.filters, p)


def render_search_details(ws: wsm.Workspace | None, run: wsm.SearchRun | None, p: dict, ux: str = "w") -> None:
    if ws is None or run is None:
        return
    S = st.session_state
    info = S["run_stats"].get(run.run_id, {})
    stats = info.get("stats", {})
    shown = min(S.get("shown", DEFAULT_TOP_K), len(run.results))
    rows = list(run.results[:shown])
    with st.expander("검색 상세 정보"):
        hist = stats.get("histogram")
        if hist and hist.get("counts"):
            n_hist = hist["n"]
            st.markdown(f'<div class="rc-h">검색문과 전체 {n_hist:,}건의 의미 유사도 분포'
                        f'<span class="count">▲ 표시 중인 {len(rows)}건</span></div>', unsafe_allow_html=True)
            ch = hist_chart(hist, stats, rows, p)
            if ch is not None:
                st.altair_chart(ch, width="stretch", theme=None)
            p99 = float(stats.get("p99", 0))
            above = sum(1 for r in rows if r.semantic_score > p99)
            gap_v = float(stats.get("max", 0)) - p99
            st.caption(f"표시된 {len(rows)}건 중 {above}건이 상위 1% 경계보다 오른쪽에 있습니다. 대다수 과제보다 "
                       f"가깝다는 뜻일 뿐 관련성 판정이 아닙니다. "
                       f"(최댓값 − 상위 1% 경계 = {gap_v:.3f} · 작을수록 상위 결과가 나머지와 덜 구분됨)")
        if run.rerank_applied and len(rows) >= 2:
            sc = [r.rerank_score for r in rows if r.rerank_score is not None]
            if len(sc) >= 2:
                st.caption(f"정렬은 재정렬 점수 순입니다. 표시된 {len(sc)}건의 점수 폭은 {max(sc) - min(sc):.3f} — 순번 차이가 곧 내용 차이는 아닙니다.")
        if ux == "l":                       # 작업공간 조건은 오른쪽 패널(render_side_composition)에 같은 내용이 있다
            st.markdown(f'<div class="rc-h" style="margin-top:.6rem">표시 중인 {len(rows)}건의 구성</div>',
                        unsafe_allow_html=True)
            render_composition(rows_as_records(rows), "displayed_results", [run.run_id], run.filters, p)
        if ws.selected:
            st.markdown('<div class="rc-h" style="margin-top:.6rem">담은 과제의 구성</div>', unsafe_allow_html=True)
            render_composition(rows_as_records([s.project_record for s in ws.selected]), "selected_records",
                               sorted({o["run_id"] for s in ws.selected for o in s.origin_runs}), {}, p)
        st.markdown('<div class="rc-h" style="margin-top:.6rem">개발자용 실행 로그<span class="count">엔진 · 처리시간 · manifest</span></div>',
                    unsafe_allow_html=True)
        mode_label, mode_kind = MODE_LABELS.get(run.run_mode, MODE_LABELS["unknown"])
        st.markdown(chips([chip("요청 엔진", run.requested_engine), chip("실제 엔진", run.actual_engine),
                           chip("재정렬", "적용" if run.rerank_applied else "미적용"),
                           chip("모드", mode_label, mode_kind), chip("run_id", run.run_id)]),
                    unsafe_allow_html=True)
        ch = latency_chart(run.latency_ms, p)
        if ch is not None:
            st.altair_chart(ch, width="stretch", theme=None)
        st.markdown(chips([chip("index manifest", run.index_manifest_id or "—"),
                           chip("model manifests", ", ".join(run.model_manifest_ids) or "—"),
                           chip("engine config", run.engine_config_id or "—")]), unsafe_allow_html=True)
        if info.get("notes"):
            st.caption(" / ".join(info["notes"]))


def render_feature_table(states: dict, engine: svc.SearchEngine, ux: str = "w", ws: wsm.Workspace | None = None) -> None:
    S = st.session_state
    with st.expander("기능 상태"):
        st.caption("자료가 뒷받침하는지와 실제로 구현됐는지를 따로 확인해 표시합니다.")
        rows = []
        for k, v in states.items():
            if ux == "l" and k in UX_ONLY_W:            # 이 화면에 없는 기능은 싣지 않는다
                continue
            label, kind = STATUS_LABELS.get(v.get("status"), (v.get("status"), "warn"))
            rows.append(f'<tr><td>{esc(FEATURE_LABELS.get(k, k))}</td><td>{chip("", label, kind)}</td>'
                        f'<td>{esc(plain(v.get("reason", "")))}</td></tr>')
        st.markdown('<table class="rc-table"><thead><tr><th style="width:24%">기능</th><th style="width:10%">상태</th>'
                    '<th>이유</th></tr></thead><tbody>' + "".join(rows) + '</tbody></table>', unsafe_allow_html=True)
        st.markdown('<div class="rc-h" style="margin-top:.8rem">데이터·모델 정보<span class="count">개발자용</span></div>',
                    unsafe_allow_html=True)
        cfg = engine.cfg
        snap = str(engine.projects["source_snapshot_id"].iloc[0]) if len(engine.projects) else "—"
        mode_label, mode_kind = MODE_LABELS.get(engine.run_mode, MODE_LABELS["unknown"])
        st.markdown(chips([
            chip("모드", mode_label, mode_kind),
            chip("화면 조건", "UX-L (목록 전용)" if ux == "l" else "UX-W (작업공간)"),
            chip("자료 D1 스냅샷", snap),
            chip("임베딩", f"{cfg.get('embedding', {}).get('model_id', '?')}@{short_rev(cfg.get('embedding', {}).get('revision'))}"),
            chip("재정렬", f"{cfg.get('rerank', {}).get('model_id', '?')}@{short_rev(cfg.get('rerank', {}).get('revision'))}"
                           + ("" if cfg.get("rerank", {}).get("enabled", True) else " (꺼짐)")),
            chip("기본 엔진", REQUESTED_ENGINE or wsm.actual_engine_name(
                bool(cfg.get("retrieval", {}).get("hybrid", False)), bool(cfg.get("rerank", {}).get("enabled", True)))),
            chip("네트워크", "검색 중 외부 호출 차단" if os.environ.get("HF_HUB_OFFLINE") == "1" else "차단 안 됨",
                 "ok" if os.environ.get("HF_HUB_OFFLINE") == "1" else "warn"),
        ]), unsafe_allow_html=True)
        st.markdown('<div class="rc-h" style="margin-top:.6rem">기능 상태 상세<span class="count">내부 키 · 자료 지원 · 구현 · 원문 사유</span></div>',
                    unsafe_allow_html=True)
        flag = lambda x: "—" if x is None else ("예" if x else "아니오")   # noqa: E731
        det = [f'<tr><td><code>{esc(k)}</code></td><td>{esc(v.get("status", ""))}</td><td>{flag(v.get("data_supports"))}</td>'
               f'<td>{flag(v.get("implemented"))}</td><td>{esc(v.get("reason", ""))}</td></tr>' for k, v in states.items()]
        st.markdown('<table class="rc-table"><thead><tr><th>key</th><th>status</th><th>자료 지원</th><th>구현</th><th>사유 원문</th>'
                    '</tr></thead><tbody>' + "".join(det) + '</tbody></table>', unsafe_allow_html=True)
        if ws is not None:
            st.markdown('<div class="rc-h" style="margin-top:.8rem">작업공간 초기화<span class="count">되돌릴 수 없음</span></div>',
                        unsafe_allow_html=True)
            if st.button("탐색 이력·비교함·메모 모두 지우기", key="btn_reset"):
                ws.reset()
                S["active_run_id"] = None
                S["run_stats"] = {}
                S["observations"], S["stale_observations"], S["action_edits"], S["field_selections"] = {}, [], {}, []
                S.pop("free_memo", None)
                st.rerun()


# ---------------------------------------------------------------------------
# 페이지 — 검색 전(검색칸만) / 검색 뒤(결과 화면)
# ---------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="Research Compass", page_icon="🧭", layout="wide",
                       initial_sidebar_state="collapsed")
    S = st.session_state
    S.setdefault("ws", None)
    S.setdefault("active_run_id", None)
    S.setdefault("shown", DEFAULT_TOP_K)
    S.setdefault("filters", {})
    S.setdefault("run_stats", {})
    S.setdefault("just_ran", False)
    S.setdefault("observations", {})
    S.setdefault("stale_observations", [])
    S.setdefault("action_edits", {})
    S.setdefault("field_selections", [])
    S.setdefault("theme_choice", "system")
    S.setdefault("view_home", False)
    _sync_box()["run"] += 1          # 스크립트 실행 번호 — 지연 다운로드가 '클릭이 일으킨 재실행 시작' 을 기다리는 데 쓴다

    # 테마 토글이 프런트엔드에 메시지를 보낼 수 있게 이 앱의 출처를 허용한다 (로컬 전용). 첫 적재는 config.toml 값을 쓴다.
    try:
        port = int(st_config.get_option("server.port"))
        origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
        cur = set(st_config.get_option("client.allowedOrigins") or [])
        if not origins <= cur:
            st_config.set_option("client.allowedOrigins", sorted(cur | origins))
    except Exception:
        pass

    palette = PALETTES[theme_now()]                  # 차트 색 등 파이썬 쪽 팔레트 (시스템 모드에서는 한 실행 늦을 수 있다)
    follow_os = S.get("theme_choice", "system") == "system"
    st.markdown(f"<style>{build_css(PALETTES['light'] if follow_os else palette, follow_os=follow_os)}</style>",
                unsafe_allow_html=True)
    if S.get("theme_touched"):
        push_theme_to_frontend(S["theme_choice"])

    ux = ux_mode()
    engine, problems = get_engine()
    if engine is None:
        st.markdown('<div class="rc-brand"><h1>Research Compass</h1></div>', unsafe_allow_html=True)
        render_not_ready(problems)
        return
    states = feature_states(ROOT, CFG)

    with st.container(key="rc_page"):              # 한 페이지 (D-038): 검색 전후 골격이 같고 결과만 아래에 붙는다
        render_band()
        render_workspace(engine, ux, states, palette)
    S["just_ran"] = False


main()
