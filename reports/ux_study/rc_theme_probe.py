# -*- coding: utf-8 -*-
# ⚠ 사용 금지 (사용자 지시 2026-09-14): 이 스크립트는 헤드리스 Edge 를 띄운다. 자식 프로세스가 남아 컴퓨터가 멈춘 적이 있다.
#   화면 확인은 tests/unit/test_app.py(AppTest) 로 하고, 실제 캡처가 꼭 필요하면 사용자에게 먼저 묻고 한 번에 하나만 돌린다.
"""화면 모드 토글 재현 — 다크 → 라이트 → 시스템 을 실제 마우스 이벤트로 누르고, 배경색·CSS 변수·브라우저 콘솔 오류를 기록한다.

    python reports/ux_study/rc_theme_probe.py [--app=http://127.0.0.1:8765]
"""
import asyncio, base64, json, os, subprocess, sys, tempfile, time, urllib.request, socket
import websockets

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "screenshots")
APP = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--app=")), "http://127.0.0.1:8765")


def _free_port():
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0)); return sk.getsockname()[1]


PORT = _free_port()
profile = tempfile.mkdtemp(prefix="rc_edge_theme_")
proc = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
                         f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}", "--window-size=1400,1000", "about:blank"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def log(*a):
    print(" ".join(str(x) for x in a), flush=True)


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
    events = []

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
                if msg.get("method") in ("Runtime.consoleAPICalled", "Runtime.exceptionThrown", "Log.entryAdded"):
                    events.append(msg)
        except asyncio.TimeoutError:
            return {}

    async def js(expr):
        r = await call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")

    async def wait_for(expr, timeout, label):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if await js(expr):
                return True
            await asyncio.sleep(0.5)
        log(f"[wait] {label}: TIMEOUT"); return False

    async def click(sel_expr):
        box = await js(f"(() => {{ const el = ({sel_expr}); if (!el) return null; el.scrollIntoView({{block:'center'}}); const r = el.getBoundingClientRect(); return [r.x + r.width/2, r.y + r.height/2]; }})()")
        if not box:
            log("[click] not found:", sel_expr[:80]); return False
        x, y = box
        await call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
        await call("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=1)
        await call("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=1)
        return True

    def toggle_btn(text):
        return f"[...document.quereliSelectorAll]"  # placeholder (unused)

    def btn(text):
        return f"[...document.querySelectorAll('.st-key-rc_theme_toggle button')].filter(b => b.innerText.trim().endsWith({json.dumps(text)}) && b.getBoundingClientRect().width > 0)[0]"

    async def state(label):
        t0 = time.time()
        await asyncio.sleep(0.3)
        await wait_for("!document.querySelector('[data-testid=\"stStatusWidget\"]')", 60, "settle")
        log(f"  [rerun] {label}: 재실행 끝까지 {time.time()-t0:.1f}s")
        await asyncio.sleep(0.8)
        bg = await js("getComputedStyle(document.querySelector('.stApp')).backgroundColor")
        var_bg = await js("getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()")
        body_bg = await js("getComputedStyle(document.body).backgroundColor")
        sel = await js("[...document.querySelectorAll('.st-key-rc_theme_toggle button')].map(b => b.innerText.trim() + (b.getAttribute('aria-checked')==='true'||b.getAttribute('aria-pressed')==='true'||b.getAttribute('aria-selected')==='true' ? '*' : '')).join(' | ')")
        bridge = await js("document.querySelectorAll('.st-key-rc_theme_bridge iframe').length")
        origins = await js("location.origin")
        log(f"[{label}] .stApp bg={bg} | --bg={var_bg} | body bg={body_bg} | toggle: {sel} | bridge iframes={bridge} | origin={origins}")
        return bg

    await call("Page.enable"); await call("Runtime.enable"); await call("Log.enable")
    DARK = "--dark" in sys.argv          # 운영체제 다크(사용자 환경) 에서 '라이트' 전환을 재현
    await call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark" if DARK else "light"}])
    await call("Emulation.setDeviceMetricsOverride", width=1400, height=1000, deviceScaleFactor=1, mobile=False)
    await call("Page.navigate", url=APP)
    ok = await wait_for("!!document.querySelector('.st-key-rc_theme_toggle button') && !!document.querySelector('input[aria-label=\"연구주제\"]')", 90, "첫 화면")
    if not ok:
        log("[diag] inputs:", await js("document.querySelectorAll('input').length"),
            "| iframes:", await js("document.querySelectorAll('iframe').length"),
            "| skeletons:", await js("document.querySelectorAll('[data-testid=\"stSkeleton\"]').length"),
            "| exceptions:", await js("document.querySelectorAll('[data-testid=\"stException\"]').length"),
            "| status:", await js("!!document.querySelector('[data-testid=\"stStatusWidget\"]')"),
            "| toggle classes:", await js("[...document.querySelectorAll('[class*=\"st-key-rc_theme\"]')].map(e=>e.className).join(' ; ')"))
        log("[diag] text:", (await js("document.body.innerText") or "")[:400].replace("\n", " / "))
        raise SystemExit("첫 화면이 뜨지 않음")
    await state("초기(시스템=라이트 에뮬레이션)")
    for name in ("다크", "라이트", "시스템", "다크", "라이트"):
        await click(btn(name))
        bg = await state(f"클릭 {name}")
        r = await call("Page.captureScreenshot", format="png")
        if "data" in r:
            with open(os.path.join(OUT, f"theme_probe_{name}.png"), "wb") as f:
                f.write(base64.b64decode(r["data"]))
    # 브라우저 콘솔·예외
    for e in events:
        m = e.get("method"); p = e.get("params", {})
        if m == "Runtime.exceptionThrown":
            log("[js-exception]", json.dumps(p.get("exceptionDetails", {}).get("exception", {}).get("description", ""))[:300])
        elif m == "Runtime.consoleAPICalled":
            args = " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))
            log(f"[console.{p.get('type')}]", args[:300])
        elif m == "Log.entryAdded":
            en = p.get("entry", {})
            log(f"[log.{en.get('level')}]", str(en.get('text', ''))[:300])
    log("DONE")


try:
    asyncio.run(main())
finally:
    # 부모만 죽이면 렌더러·GPU 자식이 남아 쌓인다(2026-09-14 컴퓨터 멈춤) — 프로세스 트리 전체를 끝낸다
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
