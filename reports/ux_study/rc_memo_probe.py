# -*- coding: utf-8 -*-
# ⚠ 사용 금지 (사용자 지시 2026-09-14): 이 스크립트는 헤드리스 Edge 를 띄운다. 자식 프로세스가 남아 컴퓨터가 멈춘 적이 있다.
#   화면 확인은 tests/unit/test_app.py(AppTest) 로 하고, 실제 캡처가 꼭 필요하면 사용자에게 먼저 묻고 한 번에 하나만 돌린다.
"""메모 내려받기 경쟁 조건 집중 확인 — (1) 쓰고 blur 없이 바로 저장 (2) 바꾼 것 없이 저장 (3) JSON 백업."""
import asyncio, base64, json, os, subprocess, sys, tempfile, time, urllib.request, glob
import websockets

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT, APP = 9342, "http://127.0.0.1:8790"
HERE = os.path.dirname(os.path.abspath(__file__))
DL = os.path.join(HERE, "dl2")
os.makedirs(DL, exist_ok=True)
for f in glob.glob(os.path.join(DL, "*")):
    os.remove(f)
profile = os.path.join(tempfile.gettempdir(), "rc_edge_profile_memo")
proc = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
                         f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}", "--window-size=1400,1000", "about:blank"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
IDEA = "제조공정 에너지 최적화"


def targets():
    for _ in range(60):
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
        await ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("id") == mid:
                return msg.get("result", msg)

    async def js(expr):
        r = await call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")

    async def wait_for(expr, timeout, label):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if await js(expr):
                print(f"[wait] {label}: {time.time()-t0:.1f}s", flush=True); return True
            await asyncio.sleep(0.5)
        print(f"[wait] {label}: TIMEOUT", flush=True); return False

    async def settle():
        """재실행이 완전히 끝나 화면이 고요할 때까지: 스켈레톤·상태 위젯 없음 + 메모 저장 버튼 존재 + 1초 정지."""
        await asyncio.sleep(0.4)
        ok = await wait_for("document.querySelectorAll('.rc-skel').length === 0 && !document.querySelector('[data-testid=\"stStatusWidget\"]') && !document.body.innerText.includes('검색 중 ·') && [...document.querySelectorAll('button')].some(b => b.innerText.includes('탐색 메모 저장'))", 60, "settle")
        await asyncio.sleep(1.0)
        return ok

    async def mouse_click(sel_expr):
        box = await js(f"(() => {{ const el = ({sel_expr}); if (!el) return null; el.scrollIntoView({{block:'center'}}); const r = el.getBoundingClientRect(); return [r.x + r.width/2, r.y + r.height/2]; }})()")
        if not box:
            print("[click] not found", sel_expr[:60]); return False
        x, y = box
        await asyncio.sleep(0.15)
        await call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
        await call("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=1)
        await call("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=1)
        return True

    def btn(text):
        return f"[...document.querySelectorAll('button')].filter(b => b.innerText.includes({json.dumps(text)}) && b.getBoundingClientRect().width > 0)[0]"

    async def download(text, timeout=20):
        before = {f: os.path.getmtime(os.path.join(DL, f)) for f in os.listdir(DL)}   # 같은 이름은 덮어써지므로 mtime 으로 판정
        info = await js(f"(() => {{ const b = {btn(text)}; if (!b) return 'NO BUTTON'; const r = b.getBoundingClientRect(); return JSON.stringify({{disabled: b.disabled, text: b.innerText, w: r.width, h: r.height, running: !!document.querySelector('[data-testid=\"stStatusWidget\"]')}}); }})()")
        print("   [pre-click]", info, flush=True)
        t_click = time.time()
        await mouse_click(btn(text))
        await asyncio.sleep(0.6)
        err = await js("(document.querySelector('[data-testid=\"stDownloadButtonError\"]')||{}).innerText || ''")
        spin = await js("!!document.querySelector('[data-testid=\"stDownloadButton\"] [data-testid=\"stSpinner\"], [data-testid=\"stDownloadButton\"] svg.spinner, [data-testid=\"stDownloadButton\"] [class*=spinner]')")
        print("   [post-click] error:", repr(err), "| spinner:", spin, "| running:", await js("!!document.querySelector('[data-testid=\"stStatusWidget\"]')"), flush=True)
        while time.time() - t_click < timeout:
            new = [f for f in os.listdir(DL) if not f.endswith(".crdownload")
                   and os.path.getmtime(os.path.join(DL, f)) != before.get(f)]
            if new:
                await asyncio.sleep(0.3)
                return os.path.join(DL, new[0]), time.time() - t_click
            await asyncio.sleep(0.3)
        return None, None

    async def type_textarea(value):
        await js("(() => { const t = document.querySelector('textarea'); t.scrollIntoView({block:'center'}); t.focus(); t.select(); })()")
        await call("Input.dispatchKeyEvent", type="keyDown", key="a", code="KeyA", modifiers=2, windowsVirtualKeyCode=65)
        await call("Input.dispatchKeyEvent", type="keyUp", key="a", code="KeyA", modifiers=2, windowsVirtualKeyCode=65)
        await call("Input.dispatchKeyEvent", type="keyDown", key="Backspace", code="Backspace", windowsVirtualKeyCode=8)
        await call("Input.dispatchKeyEvent", type="keyUp", key="Backspace", code="Backspace", windowsVirtualKeyCode=8)
        await call("Input.insertText", text=value)
        await asyncio.sleep(0.15)

    await call("Page.enable"); await call("Runtime.enable")
    await call("Browser.setDownloadBehavior", behavior="allow", downloadPath=DL, eventsEnabled=True)
    await call("Emulation.setDeviceMetricsOverride", width=1400, height=1000, deviceScaleFactor=1, mobile=False)
    await call("Page.navigate", url=APP)
    await wait_for("!!document.querySelector('input[aria-label=\"내 연구주제 (한 문장으로)\"]')", 150, "첫 화면")
    await js("(() => { const el = document.querySelector('input[aria-label=\"내 연구주제 (한 문장으로)\"]'); el.focus(); })()")
    await call("Input.insertText", text=IDEA)
    await call("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", windowsVirtualKeyCode=13)
    await call("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter", windowsVirtualKeyCode=13)
    await wait_for("document.querySelectorAll('.rc-card').length >= 5", 150, "검색")
    await settle()

    # (0) 아무 것도 건드리지 않고 저장 — 클릭 자체가 동작하는지
    f, dt = await download("탐색 메모 저장")
    print(f"[0] 바로 저장 → 파일 {bool(f)} · {dt and round(dt,1)}s", flush=True)
    await settle()
    # (1) 쓰고 바로 저장
    m1 = f"첫 메모 {int(time.time())}"
    await type_textarea(m1)
    f, dt = await download("탐색 메모 저장")
    ok1 = bool(f) and m1 in open(f, encoding="utf-8").read()
    print(f"[1] 쓰고 바로 저장 → 파일 {bool(f)} · 마지막 글 포함 {ok1} · {dt and round(dt,1)}s", flush=True)
    await settle()
    # (2) 바꾼 것 없이 다시 저장
    f, dt = await download("탐색 메모 저장")
    ok2 = bool(f) and m1 in open(f, encoding="utf-8").read()
    print(f"[2] 변경 없이 저장 → 파일 {bool(f)} · 글 포함 {ok2} · {dt and round(dt,1)}s", flush=True)
    await settle()
    # (3) 다시 고쳐 쓰고 바로 JSON 백업
    m2 = f"둘째 메모 {int(time.time())}"
    await type_textarea(m2)
    f, dt = await download("전체 작업기록 백업")
    ok3 = False
    if f:
        d = json.load(open(f, encoding="utf-8"))
        ok3 = (d.get("workspace") or {}).get("user_notes") == m2
    print(f"[3] 고쳐 쓰고 바로 JSON 백업 → 파일 {bool(f)} · user_notes 최신 {ok3} · {dt and round(dt,1)}s", flush=True)
    await settle()
    # (4) 한 번 더 Markdown — 미리보기와 일치
    f, dt = await download("탐색 메모 저장")
    ok4 = bool(f) and m2 in open(f, encoding="utf-8").read()
    print(f"[4] 변경 없이 Markdown 재저장 → {ok4} · {dt and round(dt,1)}s", flush=True)
    print("RESULT", all([ok1, ok2, ok3, ok4]), flush=True)
    await ws.close()


try:
    asyncio.run(main())
finally:
    # 부모만 죽이면(terminate/kill) 렌더러·GPU 자식이 남아 쌓인다(2026-09-14 컴퓨터 멈춤) — 프로세스 트리 전체를 끝낸다
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
