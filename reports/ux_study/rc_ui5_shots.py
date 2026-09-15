# -*- coding: utf-8 -*-
# ⚠ 사용 금지 (사용자 지시 2026-09-14): 이 스크립트는 헤드리스 Edge 를 띄운다. 자식 프로세스가 남아 컴퓨터가 멈춘 적이 있다.
#   화면 확인은 tests/unit/test_app.py(AppTest) 로 하고, 실제 캡처가 꼭 필요하면 사용자에게 먼저 묻고 한 번에 하나만 돌린다.
"""UI5 실화면 검증 — 헤드리스 Edge(CDP). 캡처 + 상태 판정 + 메모 지연 다운로드 확인.

판정은 innerText 가 아니라 상태 변화(.rc-sub 검색문, 카드 수, 비교함 건수)로 한다 (CLAUDE.md 함정 참조).
"""
import asyncio, base64, json, os, subprocess, sys, tempfile, time, urllib.request, glob
import websockets

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
import socket
def _free_port():
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0)); return sk.getsockname()[1]
PORT, APP = _free_port(), "http://127.0.0.1:8790"          # 포트 고정 시 좀비 Edge 에 붙어 엉뚱한 탭을 조작한 적이 있다
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "ui5")
DL = os.path.join(HERE, "dl")
os.makedirs(OUT, exist_ok=True); os.makedirs(DL, exist_ok=True)
for f in glob.glob(os.path.join(DL, "*")):
    os.remove(f)
import shutil
profile = tempfile.mkdtemp(prefix="rc_edge_profile_ui5_")   # 실행마다 고유 프로필 — 직전 Edge 가 아직 종료 중이면 같은 폴더 재사용이 실패한다
DARK = "--dark" in sys.argv
args = [EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
        f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}", "--window-size=1400,1000", "about:blank"]
proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
IDEA = "노인 우울증 예방을 위한 디지털 치료제 효과 연구"
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True); LOG.append(s)


def targets():
    for _ in range(120):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=2) as r:
                t = [x for x in json.load(r) if x.get("type") == "page"]
                if t:
                    return t
        except Exception:
            pass
        time.sleep(0.5)
    raise SystemExit("no debug target")


async def main():
    ws = await websockets.connect(targets()[0]["webSocketDebuggerUrl"], max_size=200 * 1024 * 1024)
    mid = 0

    async def call(method, **params):
        nonlocal mid
        mid += 1
        my_id = mid
        await ws.send(json.dumps({"id": my_id, "method": method, "params": params}))
        try:
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=40))
                if msg.get("id") == my_id:
                    return msg.get("result", msg)
        except asyncio.TimeoutError:
            log(f"[cdp] TIMEOUT {method}")
            return {}

    async def js(expr):
        r = await call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")

    async def wait_for(expr, timeout, label):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if await js(expr):
                log(f"[wait] {label}: {time.time()-t0:.1f}s")
                return True
            await asyncio.sleep(0.6)
        log(f"[wait] {label}: TIMEOUT {timeout}s")
        return False

    async def set_width(width, height=1000):
        await call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)

    async def shot(name, width=1400, cap=6000):
        await wait_for("document.querySelectorAll('.rc-skel').length === 0 && !document.querySelector('[data-testid=\"stStatusWidget\"]')", 60, "shot-settle")
        await set_width(width)
        await asyncio.sleep(0.6)
        h = await js("Math.max(...Array.from(document.querySelectorAll('*'), e => e.scrollHeight || 0))")
        h = int(min(max(h or 1000, 900), cap))
        await set_width(width, h)
        await asyncio.sleep(0.9)
        r = await call("Page.captureScreenshot", format="png", captureBeyondViewport=True,
                       clip={"x": 0, "y": 0, "width": width, "height": h, "scale": 1})
        if "data" not in r:
            log(f"[shot] {name} FAILED {r}"); await set_width(width); return
        data = base64.b64decode(r["data"])
        with open(os.path.join(OUT, name), "wb") as f:
            f.write(data)
        import struct
        pw, ph = struct.unpack(">II", data[16:24])
        vw = await js("[window.innerWidth, window.innerHeight].join('x')")
        log(f"[shot] {name} {width}x{h} → png {pw}x{ph} (viewport {vw})")
        await set_width(width)

    async def type_into(sel, value, enter=True):
        ok = await js(f"(() => {{ const el = document.querySelector({json.dumps(sel)}); if (!el) return false; el.focus(); el.select && el.select(); return true; }})()")
        if not ok:
            log("[type] no element", sel); return False
        await call("Input.dispatchKeyEvent", type="keyDown", key="a", code="KeyA", modifiers=2, windowsVirtualKeyCode=65)
        await call("Input.dispatchKeyEvent", type="keyUp", key="a", code="KeyA", modifiers=2, windowsVirtualKeyCode=65)
        await call("Input.dispatchKeyEvent", type="keyDown", key="Backspace", code="Backspace", windowsVirtualKeyCode=8)
        await call("Input.dispatchKeyEvent", type="keyUp", key="Backspace", code="Backspace", windowsVirtualKeyCode=8)
        await call("Input.insertText", text=value)
        await asyncio.sleep(0.3)
        if enter:
            await call("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", windowsVirtualKeyCode=13)
            await call("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter", windowsVirtualKeyCode=13)
        await asyncio.sleep(0.5)
        return True

    async def mouse_click_sel(sel_expr):
        """실제 마우스 이벤트로 클릭 (blur 등 브라우저 동작을 그대로 일으킨다). sel_expr 은 요소를 돌려주는 JS."""
        box = await js(f"(() => {{ const el = ({sel_expr}); if (!el) return null; el.scrollIntoView({{block:'center'}}); const r = el.getBoundingClientRect(); return [r.x + r.width/2, r.y + r.height/2]; }})()")
        if not box:
            log("[click] element not found:", sel_expr[:80]); return False
        x, y = box
        await asyncio.sleep(0.2)
        await call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
        await call("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=1)
        await call("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=1)
        return True

    def btn_expr(text, exact=True, nth=0):
        cond = f"b.innerText.trim() === {json.dumps(text)}" if exact else f"b.innerText.includes({json.dumps(text)})"
        return f"[...document.querySelectorAll('button')].filter(b => ({cond}) && b.getBoundingClientRect().width > 0)[{nth}]"

    async def click_button(text, nth=0, exact=True):
        return await mouse_click_sel(btn_expr(text, exact, nth))

    async def open_expander(label):
        return await js(f"""(() => {{ for (const s of document.querySelectorAll('summary')) {{ const t = (s.innerText || '').trim(); if (t.includes({json.dumps(label)}) && !s.parentElement.open) {{ s.click(); return true; }} }} return false; }})()""")

    async def sub_text():
        return await js("(document.querySelector('.rc-sub') || {}).innerText || ''")

    async def basket_count():
        return await js("document.querySelectorAll('.rc-bk').length")

    async def cards():
        return await js("document.querySelectorAll('.rc-card').length")

    async def settle(timeout=60):
        await asyncio.sleep(0.4)
        return await wait_for("document.querySelectorAll('.rc-skel').length === 0 && !document.querySelector('[data-testid=\"stStatusWidget\"]') && !document.body.innerText.includes('검색 중 ·')", timeout, "settle")

    async def wait_sub(contains, timeout=90):
        return await wait_for(f"((document.querySelector('.rc-sub') || {{}}).innerText || '').includes({json.dumps(contains)})", timeout, f"검색문 '{contains[:20]}'")

    await call("Page.enable"); await call("Runtime.enable")
    await call("Browser.setDownloadBehavior", behavior="allow", downloadPath=DL, eventsEnabled=True)
    await call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark" if DARK else "light"}])
    await set_width(1400)
    await call("Page.navigate", url=APP)
    ok = await wait_for("!!document.querySelector('input[aria-label=\"내 연구주제 (한 문장으로)\"]')", 150, "첫 화면")
    await asyncio.sleep(1.2)
    vp = await js("[innerWidth, innerHeight].join('x')")
    href = await js("location.href")
    log("[env] port", PORT, "| viewport", vp, "| href", href, "| rc-landing:", await js("document.querySelectorAll('.rc-landing').length"))
    if not str(vp).startswith("1400") or not str(href).startswith(APP):
        raise SystemExit(f"환경 이상 — viewport {vp}, href {href}. 좀비 브라우저/포트 충돌 의심")
    bg = await js("getComputedStyle(document.querySelector('.stApp')).backgroundColor")
    log("[landing] bg", bg, "| h1:", await js("(document.querySelector('.rc-landing h1')||{}).innerText"),
        "| facts:", await js("(document.querySelector('.rc-facts')||{}).innerText"))
    sfx = "_dark" if DARK else "_light"
    await shot(f"01_landing{sfx}.png", cap=1100)
    await shot(f"01b_landing_760{sfx}.png", width=760, cap=1100)
    await set_width(1400)

    # ---- 검색 (Enter) ----
    await type_into('input[aria-label="내 연구주제 (한 문장으로)"]', IDEA)
    await wait_for("document.querySelectorAll('.rc-card').length >= 5", 150, "첫 검색")
    await asyncio.sleep(1.5)
    log("[results] sub:", await sub_text(), "| cards:", await cards(),
        "| persp label:", await js("[...document.querySelectorAll('label')].map(l=>l.innerText).filter(t=>t.includes('탐색 관점')||t.includes('현재 검색문'))"),
        "| card texts has 상위?:", await js("[...document.querySelectorAll('.rc-card')].some(c => c.innerText.includes('상위'))"))
    await shot(f"02_results{sfx}.png", cap=2600)

    # ---- 근거 보기 팝오버 ----
    await settle()
    await click_button("검색 근거 보기", 0, exact=False)
    await asyncio.sleep(1.5)
    ev = await js("[...document.querySelectorAll('.rc-kv')].map(e=>e.innerText).join(' ')")
    log("[evidence] has 최종 표시 순위:", "최종 표시 순위" in ev, "| 1차 의미검색 위치:", "1차 의미검색 위치" in ev, "| 재정렬 점수:", "재정렬 점수" in ev)
    await shot(f"03_evidence{sfx}.png", cap=1900)
    await call("Input.dispatchKeyEvent", type="keyDown", key="Escape", code="Escape", windowsVirtualKeyCode=27)
    await call("Input.dispatchKeyEvent", type="keyUp", key="Escape", code="Escape", windowsVirtualKeyCode=27)
    await asyncio.sleep(0.6)

    # ---- 비교함 1건 ----
    await settle()
    await click_button("비교함에 담기", 0, exact=False)
    await wait_for("document.querySelectorAll('.rc-bk').length === 1", 60, "담기 1")
    await asyncio.sleep(0.8)
    log("[basket1] hint:", await js("(document.querySelector('.rc-hint')||{}).innerText"), "| compact:", await js("(document.querySelector('.rc-compact')||{}).innerText"))
    await shot(f"04_basket1{sfx}.png", cap=2600)

    # ---- 관점: 요소 반영 → 대상·문제 ----
    await click_button("방법·접근", 0)
    await wait_for("!!document.querySelector('input[aria-label=\"방법·접근\"]')", 30, "요소 폼")
    await type_into('input[aria-label="대상·맥락"]', "노인", enter=False)
    await type_into('input[aria-label="방법·접근"]', "디지털 치료제", enter=False)
    await type_into('input[aria-label="목표·질문"]', "우울증 예방", enter=True)
    await asyncio.sleep(2.0)
    await click_button("대상·문제", 0)
    await asyncio.sleep(1.5)
    q = await js("(document.querySelector('input[aria-label=\"현재 검색문\"]')||{}).value")
    log("[persp] 대상·문제 검색문:", q)
    await click_button("탐색", 0)
    await asyncio.sleep(2.0)
    await settle(); await wait_sub("우울증 예방")
    await asyncio.sleep(1.2)
    log("[persp] sub:", await sub_text(), "| basket kept:", await basket_count())
    await shot(f"05_target_perspective{sfx}.png", cap=2600)

    # ---- 비교함 2건 (다른 관점에서) → 비교표 ----
    await settle()
    await click_button("비교함에 담기", 0, exact=False)
    await wait_for("document.querySelectorAll('.rc-bk').length === 2", 60, "담기 2")
    await asyncio.sleep(1.0)
    rows = await js("[...document.querySelectorAll('table.rc-table tbody tr td:first-child b')].map(b=>b.innerText)")
    log("[compare2] rows:", rows)
    await shot(f"06_compare2{sfx}.png", cap=3400)

    # ---- 방법·접근 → 검색문 직접 수정 → 탐색 ----
    await click_button("방법·접근", 0)
    await asyncio.sleep(1.5)
    await type_into('input[aria-label="현재 검색문"]', "디지털 치료제 노인 우울", enter=False)
    await js("document.querySelector('input[aria-label=\"현재 검색문\"]').blur()")
    await asyncio.sleep(1.5)
    log("[edit] 직접 수정됨 표시:", await js("!!document.querySelector('.rc-edited')"))
    await shot(f"07_edited_query{sfx}.png", cap=1300)
    await click_button("탐색", 0)
    await asyncio.sleep(2.0)
    await settle(); await wait_sub("디지털 치료제 노인 우울")
    await asyncio.sleep(1.0)
    log("[edit] sub:", await sub_text())

    # ---- 비교함 3건 → 비교표 3열 + 더 보기 10건 ----
    await settle()
    await click_button("비교함에 담기", 0, exact=False)
    await wait_for("document.querySelectorAll('.rc-bk').length === 3", 60, "담기 3")
    await settle()
    await click_button("더 보기", 0, exact=False)
    await wait_for("document.querySelectorAll('.rc-card').length >= 10", 30, "10건")
    await asyncio.sleep(1.0)
    await open_expander("수록 데이터 안의 맥락")
    await asyncio.sleep(0.8)
    await shot(f"08_compare3_10cards{sfx}.png", cap=4200)

    # ---- 메모: 쓰고 바로 저장 클릭 (blur 없이) → 파일에 마지막 글이 있어야 한다 ----
    await settle()
    await js("document.querySelector('textarea').scrollIntoView({block:'center'})")
    await asyncio.sleep(0.3)
    memo = "E1이 가장 가깝다. 저장 직전에 쓴 문장 " + str(int(time.time()))
    await type_into("textarea", memo, enter=False)
    await asyncio.sleep(0.2)
    before = set(os.listdir(DL))
    await click_button("탐색 메모 저장", 0)
    t0 = time.time(); got = None
    while time.time() - t0 < 20:
        new = [f for f in os.listdir(DL) if f not in before and not f.endswith(".crdownload")]
        if new:
            got = os.path.join(DL, new[0]); break
        await asyncio.sleep(0.4)
    if got:
        txt = open(got, encoding="utf-8").read()
        log("[memo-dl] file:", os.path.basename(got), "| contains last text:", memo in txt, "| size:", len(txt))
    else:
        log("[memo-dl] NO FILE downloaded")
    before = set(os.listdir(DL))
    await click_button("전체 작업기록 백업", 0)
    t0 = time.time(); got2 = None
    while time.time() - t0 < 20:
        new = [f for f in os.listdir(DL) if f not in before and not f.endswith(".crdownload")]
        if new:
            got2 = os.path.join(DL, new[0]); break
        await asyncio.sleep(0.4)
    if got2:
        j = json.load(open(got2, encoding="utf-8"))
        log("[json-dl] file:", os.path.basename(got2), "| user_notes ok:", (j.get("workspace") or j).get("user_notes", "") == memo if isinstance(j, dict) else None,
            "| keys:", list(j.keys())[:8] if isinstance(j, dict) else type(j))
    else:
        log("[json-dl] NO FILE downloaded")
    await asyncio.sleep(1.0)
    await open_expander("메모 미리보기")
    await asyncio.sleep(0.8)
    await shot(f"09_memo{sfx}.png", cap=3200)

    # ---- 재검색 후 메모 유지 ----
    await settle()
    await click_button("전체 연구주제", 0)
    await asyncio.sleep(1.5)
    await click_button("탐색", 0)
    await asyncio.sleep(2.0)
    await settle(); await wait_sub(IDEA[:12])
    await asyncio.sleep(1.0)
    log("[memo-keep] textarea after re-search:", (await js("(document.querySelector('textarea')||{}).value")) == memo, "| basket:", await basket_count())

    # ---- 검색 범위: 빈 결과 ----
    await open_expander("검색 범위")
    await asyncio.sleep(0.8)
    await mouse_click_sel("[...document.querySelectorAll('[data-testid=\"stMultiSelect\"] input')][1]")
    await asyncio.sleep(0.6)
    await call("Input.insertText", text="원자력")
    await asyncio.sleep(0.8)
    await call("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", windowsVirtualKeyCode=13)
    await call("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter", windowsVirtualKeyCode=13)
    await asyncio.sleep(1.2)
    await mouse_click_sel("[...document.querySelectorAll('[data-testid=\"stMultiSelect\"] input')][0]")
    await asyncio.sleep(0.6)
    await call("Input.insertText", text="2025")
    await asyncio.sleep(0.8)
    await call("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", windowsVirtualKeyCode=13)
    await call("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter", windowsVirtualKeyCode=13)
    await asyncio.sleep(1.5)
    await asyncio.sleep(1.0)
    ok = await click_button("이 범위로 다시 탐색", 0, exact=False)
    log("[filter] refilter button:", ok)
    await wait_for("document.body.innerText.includes('범위를 통과한 대상이 없습니다') || (document.querySelector('.rc-meta')||{}).innerText.includes('범위:')", 90, "범위 재탐색")
    await asyncio.sleep(1.2)
    log("[filter] empty:", await js("document.body.innerText.includes('범위를 통과한 대상이 없습니다')"), "| meta:", await js("(document.querySelector('.rc-meta')||{}).innerText"))
    await shot(f"10_empty_result{sfx}.png", cap=2200)

    # ---- 반응형 ----
    await click_button("전체 연구주제", 0)
    await asyncio.sleep(0.8)
    # 이전 결과(전체 주제)로 표시 전환: 최근 탐색 칩 첫 번째
    for w in (1920, 1366, 1000, 760):
        await shot(f"11_results_w{w}{sfx}.png", width=w, cap=3000)
    await set_width(1400)

    # ---- 테마 토글 ----
    other = "라이트" if DARK else "다크"
    await click_button(other, 0, exact=False)
    await asyncio.sleep(2.5)
    log(f"[theme] {other} bg:", await js("getComputedStyle(document.querySelector('.stApp')).backgroundColor"), "| basket kept:", await basket_count())
    await shot(f"12_toggle_{other}{sfx}.png", cap=2600)
    await click_button("시스템", 0, exact=False)
    await asyncio.sleep(2.0)
    log("[theme] 시스템 bg:", await js("getComputedStyle(document.querySelector('.stApp')).backgroundColor"))

    # ---- 홈 → 첫 화면(탐색 유지) ----
    await click_button("Research Compass", 0)
    await asyncio.sleep(1.5)
    log("[home] landing:", await js("!!document.querySelector('.rc-landing')"), "| back btn:", await js("!!" + btn_expr("이전 결과로 돌아가기")))
    await shot(f"13_home_with_back{sfx}.png", cap=1100)
    await ws.close()
    open(os.path.join(OUT, f"log{sfx}.txt"), "w", encoding="utf-8").write("\n".join(LOG))


try:
    asyncio.run(main())
finally:
    # 부모만 죽이면(terminate/kill) 렌더러·GPU 자식이 남아 쌓인다(2026-09-14 컴퓨터 멈춤) — 프로세스 트리 전체를 끝낸다
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
