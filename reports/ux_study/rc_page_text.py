# -*- coding: utf-8 -*-
# ⚠ 사용 금지 (사용자 지시 2026-09-14): 이 스크립트는 헤드리스 Edge 를 띄운다. 자식 프로세스가 남아 컴퓨터가 멈춘 적이 있다.
#   화면 확인은 tests/unit/test_app.py(AppTest) 로 하고, 실제 캡처가 꼭 필요하면 사용자에게 먼저 묻고 한 번에 하나만 돌린다.
"""페이지가 뜨지 않을 때 — 헤드리스 Edge 로 열고 N초 뒤 화면 글자·예외 블록·콘솔 오류를 그대로 덤프한다.

    python reports/ux_study/rc_page_text.py [--app=http://127.0.0.1:8765] [--wait=45]
"""
import asyncio, json, os, subprocess, sys, tempfile, time, urllib.request, socket
import websockets

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
APP = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--app=")), "http://127.0.0.1:8765")
WAIT = int(next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--wait=")), "45"))


def _free_port():
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0)); return sk.getsockname()[1]


PORT = _free_port()
profile = tempfile.mkdtemp(prefix="rc_edge_text_")
proc = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                         f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}", "--window-size=1400,1000", "about:blank"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
            if msg.get("id") == my_id:
                return msg.get("result", msg)
            if msg.get("method"):
                events.append(msg)

    async def js(expr):
        r = await call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")

    await call("Page.enable"); await call("Runtime.enable"); await call("Log.enable")
    await call("Page.navigate", url=APP)
    t0 = time.time()
    while time.time() - t0 < WAIT:
        await asyncio.sleep(3)
        n_toggle = await js("document.querySelectorAll('.st-key-rc_theme_toggle button').length")
        n_exc = await js("document.querySelectorAll('[data-testid=\"stException\"]').length")
        status = await js("!!document.querySelector('[data-testid=\"stStatusWidget\"]')")
        print(f"[{time.time()-t0:5.1f}s] toggle buttons={n_toggle} exceptions={n_exc} running={status}", flush=True)
        if n_toggle or n_exc:
            break
    print("=== innerText (앞 1500자) ===")
    print((await js("document.body.innerText") or "")[:1500])
    exc = await js("[...document.querySelectorAll('[data-testid=\"stException\"]')].map(e => e.innerText).join('\\n---\\n')")
    if exc:
        print("=== stException ===")
        print(exc[:4000])
    print("=== 콘솔/예외/로그 ===")
    for e in events:
        m, p = e.get("method"), e.get("params", {})
        if m == "Runtime.exceptionThrown":
            print("[js-exception]", str(p.get("exceptionDetails", {}).get("exception", {}).get("description", ""))[:400])
        elif m == "Runtime.consoleAPICalled" and p.get("type") in ("error", "warning"):
            print(f"[console.{p.get('type')}]", " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))[:400])
        elif m == "Log.entryAdded" and p.get("entry", {}).get("level") in ("error", "warning"):
            print(f"[log.{p['entry'].get('level')}]", str(p["entry"].get("text", ""))[:400], p["entry"].get("url", "")[:120])
    print("DONE")


try:
    asyncio.run(main())
finally:
    # 부모만 죽이면 렌더러·GPU 자식이 남아 쌓인다(2026-09-14 컴퓨터 멈춤) — 프로세스 트리 전체를 끝낸다
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
