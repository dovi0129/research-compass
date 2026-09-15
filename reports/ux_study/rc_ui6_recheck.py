# -*- coding: utf-8 -*-
# ⚠ 사용 금지 (사용자 지시 2026-09-14): 이 스크립트는 헤드리스 Edge 를 띄운다. 자식 프로세스가 남아 컴퓨터가 멈춘 적이 있다.
#   화면 확인은 tests/unit/test_app.py(AppTest) 로 하고, 실제 캡처가 꼭 필요하면 사용자에게 먼저 묻고 한 번에 하나만 돌린다.
"""UI6 수정 확인 캡처 — 요소별 탐색(관점 라디오) · 결과 오른쪽 묶음. rc_ui6_shots.py 의 도우미를 import 없이 다시 쓴다 (짧게)."""
import asyncio, base64, json, os, subprocess, sys, tempfile, time, urllib.request, socket, struct
import websockets

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "screenshots")
APP = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--app=")), "http://127.0.0.1:8790")
DARK = "--dark" in sys.argv
SFX = "_dark" if DARK else "_light"
IDEA = "지역 소멸 위기 대응 주민 참여 거버넌스"


def _free_port():
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0)); return sk.getsockname()[1]


PORT = _free_port()
profile = tempfile.mkdtemp(prefix="rc_edge_profile_ui6r_")
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
            return {}

    async def js(expr):
        r = await call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")

    async def wait_for(expr, timeout, label):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if await js(expr):
                return True
            await asyncio.sleep(0.6)
        log(f"[wait] {label}: TIMEOUT"); return False

    async def set_width(width, height=1000):
        await call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)

    async def shot(name, width=1400, cap=3000):
        await wait_for("document.querySelectorAll('.rc-skel').length === 0 && !document.querySelector('[data-testid=\"stStatusWidget\"]')", 60, "settle")
        await set_width(width); await asyncio.sleep(0.6)
        h = await js("Math.max(...Array.from(document.querySelectorAll('*'), e => e.scrollHeight || 0))")
        h = int(min(max(h or 900, 800), cap))
        await set_width(width, h); await asyncio.sleep(0.9)
        r = await call("Page.captureScreenshot", format="png", captureBeyondViewport=True, clip={"x": 0, "y": 0, "width": width, "height": h, "scale": 1})
        data = base64.b64decode(r["data"])
        with open(os.path.join(OUT, name), "wb") as f:
            f.write(data)
        log(f"[shot] {name} → {struct.unpack('>II', data[16:24])}")
        await set_width(width)

    async def click(sel_expr):
        box = await js(f"(() => {{ const el = ({sel_expr}); if (!el) return null; el.scrollIntoView({{block:'center'}}); const r = el.getBoundingClientRect(); return [r.x + r.width/2, r.y + r.height/2]; }})()")
        if not box:
            log("[click] not found"); return False
        x, y = box
        await call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
        await call("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=1)
        await call("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=1)
        return True

    def btn(text):
        return f"[...document.querySelectorAll('button')].filter(b => b.innerText.trim() === {json.dumps(text)} && b.getBoundingClientRect().width > 0)[0]"

    await call("Page.enable"); await call("Runtime.enable")
    await call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark" if DARK else "light"}])
    await set_width(1400)
    await call("Page.navigate", url=APP)
    await wait_for("!!document.querySelector('input[aria-label=\"연구주제\"]') && !!document.querySelector('.rc-stats')", 180, "첫 화면")
    await asyncio.sleep(1.0)
    log("[foot]", await js("(document.querySelector('.rc-foot')||{}).innerText"))
    await shot(f"ui6_01_landing{SFX}.png", cap=1300)
    await click(btn("요소별 탐색"))
    await wait_for("!!document.querySelector('input[aria-label=\"방법·접근\"]')", 60, "elements")
    await asyncio.sleep(0.8)
    log("[radio] labels:", await js("[...document.querySelectorAll('[role=radiogroup] label')].map(l=>l.innerText.trim())"))
    await shot(f"ui6_02_mode_elements{SFX}.png", cap=1300)
    await click(btn("연구주제 한 문장"))
    await wait_for("!!document.querySelector('input[aria-label=\"연구주제\"]')", 60, "topic")
    # 모드 클릭이 일으킨 재실행이 끝나기 전에 focus 하면 입력칸이 다시 그려져 포커스를 잃는다 → 재실행 종료를 기다린다
    await wait_for("!document.querySelector('[data-testid=\"stStatusWidget\"]')", 60, "rerun-settle")
    await asyncio.sleep(1.2)
    await js("(() => { const el = document.querySelector('input[aria-label=\"연구주제\"]'); el.focus(); el.select && el.select(); return true; })()")
    await asyncio.sleep(0.3)
    await call("Input.insertText", text=IDEA)
    await call("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", windowsVirtualKeyCode=13)
    await call("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter", windowsVirtualKeyCode=13)
    await wait_for("document.querySelectorAll('.rc-card').length >= 5", 180, "검색")
    await asyncio.sleep(1.5)
    log("[right] basket y:", await js("Math.round(document.querySelector('.st-key-rc_basket').getBoundingClientRect().top)"),
        "| side y:", await js("Math.round(document.querySelector('.st-key-rc_side').getBoundingClientRect().top)"))
    await shot(f"ui6_05_results{SFX}.png", cap=2600)
    log("DONE")


try:
    asyncio.run(main())
finally:
    # 부모만 죽이면 렌더러·GPU 자식이 남아 쌓인다(2026-09-14 컴퓨터 멈춤) — 프로세스 트리 전체를 끝낸다
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
