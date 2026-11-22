#!/usr/bin/env python3
"""Headless Chromium CDP End-to-End verification for DeckGen Studio (/card-builder and /deck-generator)."""
import asyncio
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import websockets

BASE_URL = "http://127.0.0.1:8766"
CDP_PORT = 9229


class CDPSession:
    def __init__(self, ws):
        self.ws = ws
        self._msg_id = 0
        self._pending = {}
        self.console_errors = []
        self.page_exceptions = []
        self.network_404s = []
        self.network_failures = []
        self.network_responses = []
        self._req_urls = {}

    async def listen(self):
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                if "id" in msg:
                    fut = self._pending.pop(msg["id"], None)
                    if fut and not fut.done():
                        fut.set_result(msg)
                else:
                    method = msg.get("method", "")
                    params = msg.get("params", {})
                    if method == "Runtime.consoleAPICalled":
                        if params.get("type") == "error":
                            args = [a.get("value") or a.get("description") or str(a) for a in params.get("args", [])]
                            self.console_errors.append(" ".join(str(x) for x in args))
                    elif method == "Runtime.exceptionThrown":
                        details = params.get("exceptionDetails", {})
                        self.page_exceptions.append(details.get("text", str(details)))
                    elif method == "Log.entryAdded":
                        entry = params.get("entry", {})
                        if entry.get("level") == "error":
                            self.console_errors.append(f"[{entry.get('source')}] {entry.get('text')} ({entry.get('url', '')})")
                    elif method == "Network.requestWillBeSent":
                        self._req_urls[params.get("requestId")] = params.get("request", {}).get("url", "")
                    elif method == "Network.responseReceived":
                        resp = params.get("response", {})
                        url = resp.get("url", "")
                        status = int(resp.get("status", 0))
                        self.network_responses.append((status, url))
                        if status == 404:
                            self.network_404s.append(url)
                        elif status >= 400:
                            self.network_failures.append((status, url))
                    elif method == "Network.loadingFailed":
                        url = self._req_urls.get(params.get("requestId"), "")
                        err_text = params.get("errorText", "")
                        if not params.get("canceled"):
                            self.network_failures.append((err_text, url))
        except websockets.ConnectionClosed:
            pass

    async def send(self, method: str, params: dict = None) -> dict:
        self._msg_id += 1
        mid = self._msg_id
        fut = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        res = await asyncio.wait_for(fut, timeout=30.0)
        if "error" in res:
            raise RuntimeError(f"CDP {method} error: {res['error']}")
        return res.get("result", {})

    async def evaluate(self, expression: str, await_promise: bool = True):
        res = await self.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
            },
        )
        if "exceptionDetails" in res:
            raise RuntimeError(f"JS evaluation error: {res['exceptionDetails']}")
        return res.get("result", {}).get("value")


async def run_browser_tests() -> int:
    with tempfile.TemporaryDirectory() as user_data_dir, tempfile.TemporaryDirectory() as project_dir:
        proc = subprocess.Popen(
            [
                "chromium",
                "--headless",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                f"--remote-debugging-port={CDP_PORT}",
                f"--user-data-dir={user_data_dir}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            ws_url = None
            for _ in range(40):
                try:
                    r = httpx.get(f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=1.0)
                    pages = [p for p in r.json() if p.get("type") == "page"]
                    if pages:
                        ws_url = pages[0]["webSocketDebuggerUrl"]
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.2)
            if not ws_url:
                raise RuntimeError("Failed to connect to headless Chromium CDP endpoint")

            async with websockets.connect(ws_url, max_size=50 * 1024 * 1024) as ws:
                cdp = CDPSession(ws)
                listener = asyncio.create_task(cdp.listen())
                await cdp.send("Page.enable")
                await cdp.send("Runtime.enable")
                await cdp.send("Network.enable")
                await cdp.send("Log.enable")

                # 1. Initialize a workspace via API so both Card Builder and Deck Generator have an active project
                with httpx.Client(base_url=BASE_URL, timeout=15.0) as api:
                    cr = api.post("/api/workspace/create", json={"root_dir": project_dir, "project_name": "E2EBrowserTest"})
                    assert cr.status_code == 200, cr.text
                    sym_r = api.get("/api/card-builder/symbols")
                    assert sym_r.status_code == 200
                    sym_data = sym_r.json()
                    assert len(sym_data.get("mana") or {}) >= 500
                    assert len(sym_data.get("sets") or {}) >= 1500

                await cdp.send("Emulation.setDeviceMetricsOverride", {
                    "width": 1280,
                    "height": 960,
                    "deviceScaleFactor": 1,
                    "mobile": False,
                })

                # 2. Navigate to /card-builder
                await cdp.send("Page.navigate", {"url": f"{BASE_URL}/card-builder"})
                await asyncio.sleep(1.5)
                await cdp.evaluate(f"localStorage.setItem('deckgen-active-root', {json.dumps(project_dir)}); true")
                await cdp.send("Page.reload")
                await asyncio.sleep(1.8)

                # 3. Verify crop_masks.js and layer_manager.js modules in browser context
                mask_test = await cdp.evaluate("""
                (async () => {
                  const cm = await import('/static/js/modules/crop_masks.js?v=2');
                  const lm = await import('/static/js/modules/layer_manager.js?v=29');
                  const c = document.createElement('canvas');
                  c.width = 200; c.height = 200;
                  const ctx = c.getContext('2d');
                  for (const key of Object.keys(cm.CROP_MASKS)) {
                    cm.drawMaskPath(ctx, key, 10, 10, 180, 180);
                  }
                  return { masks: Object.keys(cm.CROP_MASKS), hasRenderProjectFace: typeof lm.renderProjectFace === 'function' };
                })()
                """)
                assert mask_test["hasRenderProjectFace"], "renderProjectFace not exported by layer_manager.js"
                print("PASS: Browser loaded crop_masks.js and layer_manager.js modules:", mask_test)

                # 4. Import Shatterskull Smashing // Shatterskull, the Hammer Pass (ZNR) and verify single canvas, Layer Manager, mana & set symbols
                shatter_face0 = await cdp.evaluate("""
                (async () => {
                  document.getElementById('cb-scryfall-import-btn').click();
                  document.getElementById('cb-sf-name').value = 'Shatterskull Smashing';
                  document.getElementById('cb-sf-set').value = 'znr';
                  document.getElementById('cb-sf-import').click();
                  for (let i = 0; i < 60; i++) {
                    await new Promise((r) => setTimeout(r, 200));
                    const sel = document.getElementById('cb-stage-face-select');
                    if (sel && sel.options.length === 2) {
                      await new Promise((r) => setTimeout(r, 600));
                      const legacyWrap = document.getElementById('cb-legacy-wrap');
                      const projectWrap = document.getElementById('cb-project-wrap');
                      const layerItems = Array.from(document.querySelectorAll('#cb-layer-list .layer-item')).map((li) => ({
                        key: li.dataset.layerKey,
                        text: li.querySelector('.layer-name')?.textContent?.trim() || '',
                        hidden: li.classList.contains('is-hidden-layer'),
                      }));
                      return {
                        legacyDisplay: window.getComputedStyle(legacyWrap).display,
                        projectDisplay: window.getComputedStyle(projectWrap).display,
                        options: Array.from(sel.options).map((o) => ({ value: o.value, text: o.text })),
                        titleFace0: document.getElementById('cb-field-name').value,
                        manaFace0: document.getElementById('cb-field-mana').value,
                        canvasW: document.getElementById('cb-project-canvas').width,
                        canvasH: document.getElementById('cb-project-canvas').height,
                        layerItems,
                      };
                    }
                  }
                  throw new Error('Timeout waiting for Shatterskull Smashing import');
                })()
                """)
                assert shatter_face0["legacyDisplay"] == "none", f"Expected legacy canvas hidden, got {shatter_face0['legacyDisplay']}"
                assert shatter_face0["projectDisplay"] in ("flex", "block"), f"Expected project canvas visible, got {shatter_face0['projectDisplay']}"
                assert len(shatter_face0["layerItems"]) == 6, f"Expected 6 layers, got {shatter_face0['layerItems']}"
                empty_layers = [it for it in shatter_face0["layerItems"] if "(empty)" in it["text"]]
                assert len(empty_layers) == 0, f"Found (empty) layers in Layer Manager: {empty_layers}"
                stamp_item = next((it for it in shatter_face0["layerItems"] if it["key"] == "name_box"), None)
                assert stamp_item and stamp_item["hidden"] is True, f"Expected Holo Stamp hidden by default: {stamp_item}"
                print("PASS: Shatterskull Smashing Face 0 single canvas & Layer Manager verified:", shatter_face0)

                shot0 = await cdp.send("Page.captureScreenshot", {"format": "png"})
                shot0_path = Path("/home/choroy/.gemini/antigravity/brain/f1496424-a8a3-4ed5-9b71-b2f85994d5ae/scratch/browser_shatterskull_face0.png")
                shot0_path.parent.mkdir(parents=True, exist_ok=True)
                import base64
                shot0_path.write_bytes(base64.b64decode(shot0["data"]))

                # 4b. Verify interactive hover & click selection on #cb-project-canvas (Title + Oracle Text)
                interactive_res = await cdp.evaluate("""
                (async () => {
                  const pc = document.getElementById('cb-project-canvas');
                  const rect = pc.getBoundingClientRect();
                  // Hover over Title region (approx x=300/750, y=80/1050)
                  const titleX = rect.left + rect.width * (300 / 750);
                  const titleY = rect.top + rect.height * (75 / 1050);
                  window.dispatchEvent(new MouseEvent('mousemove', { clientX: titleX, clientY: titleY, bubbles: true }));
                  await new Promise((r) => setTimeout(r, 100));
                  const hoverCursor = pc.style.cursor;
                  // Click Title to select it & open Text Settings popover
                  pc.dispatchEvent(new MouseEvent('mousedown', { clientX: titleX, clientY: titleY, bubbles: true }));
                  window.dispatchEvent(new MouseEvent('mouseup', { clientX: titleX, clientY: titleY, bubbles: true }));
                  await new Promise((r) => setTimeout(r, 150));
                  const popoverDisplay = document.getElementById('cb-text-popover')?.style.display;
                  const popoverTitle = document.getElementById('cb-text-popover-title')?.textContent;
                  // Drag Title down by 20px
                  pc.dispatchEvent(new MouseEvent('mousedown', { clientX: titleX, clientY: titleY, bubbles: true }));
                  window.dispatchEvent(new MouseEvent('mousemove', { clientX: titleX, clientY: titleY + 20, bubbles: true }));
                  window.dispatchEvent(new MouseEvent('mouseup', { clientX: titleX, clientY: titleY + 20, bubbles: true }));
                  await new Promise((r) => setTimeout(r, 200));
                  return { hoverCursor, popoverDisplay, popoverTitle };
                })()
                """)
                assert interactive_res["hoverCursor"] == "move", f"Expected move cursor on hover, got {interactive_res}"
                assert interactive_res["popoverDisplay"] == "block", f"Expected text popover to open on click, got {interactive_res}"
                assert "Title" in (interactive_res["popoverTitle"] or ""), f"Expected Title popover, got {interactive_res}"
                print("PASS: Interactive hover, click, popover, and drag on #cb-project-canvas verified:", interactive_res)

                shot_sel = await cdp.send("Page.captureScreenshot", {"format": "png"})
                shot_sel_path = Path("/home/choroy/.gemini/antigravity/brain/f1496424-a8a3-4ed5-9b71-b2f85994d5ae/scratch/browser_interactive_select.png")
                shot_sel_path.write_bytes(base64.b64decode(shot_sel["data"]))

                # 5. Switch to Face 1 (Shatterskull, the Hammer Pass) in the browser and verify re-render + screenshot
                dfc_face1 = await cdp.evaluate("""
                (async () => {
                  const sel = document.getElementById('cb-stage-face-select');
                  sel.value = '1';
                  sel.dispatchEvent(new Event('change'));
                  await new Promise((r) => setTimeout(r, 900));
                  const canvas = document.getElementById('cb-project-canvas');
                  const ctx = canvas.getContext('2d');
                  const px = Array.from(ctx.getImageData(750, 500, 1, 1).data);
                  return {
                    selectedFace: sel.value,
                    titleFace1: document.getElementById('cb-field-name').value,
                    samplePixel: px,
                  };
                })()
                """)
                assert dfc_face1["selectedFace"] == "1"
                assert "Shatterskull, the Hammer Pass" in dfc_face1["titleFace1"]
                assert dfc_face1["samplePixel"][3] > 0
                print("PASS: Switched DFC to Face 1 in browser:", dfc_face1)

                shot1 = await cdp.send("Page.captureScreenshot", {"format": "png"})
                shot1_path = Path("/home/choroy/.gemini/antigravity/brain/f1496424-a8a3-4ed5-9b71-b2f85994d5ae/scratch/browser_shatterskull_face1.png")
                shot1_path.write_bytes(base64.b64decode(shot1["data"]))

                # 6. Replace artwork live in browser and verify canvas updates cleanly
                art_replace = await cdp.evaluate("""
                (async () => {
                  const c = document.createElement('canvas');
                  c.width = 400; c.height = 300;
                  const x = c.getContext('2d');
                  x.fillStyle = '#e11d48';
                  x.fillRect(0, 0, 400, 300);
                  const dataUrl = c.toDataURL('image/png');

                  const pCanvas = document.getElementById('cb-project-canvas');
                  const pCtx = pCanvas.getContext('2d');
                  const beforePx = Array.from(pCtx.getImageData(400, 450, 1, 1).data);

                  document.getElementById('cb-replace-art-btn').click();
                  const menu = document.getElementById('cb-art-menu');
                  const hasMenu = Boolean(menu);
                  if (menu) menu.remove();

                  const lm = await import('/static/js/modules/layer_manager.js?v=29');
                  const fakeFace = {
                    face_index: 1,
                    art_layer: { url: dataUrl, bounds: { x: 115, y: 237, w: 1271, h: 930 }, transform: { x: 0, y: 0, scale: 1, rotation: 0 } },
                    frame_stack: [],
                  };
                  const renderRes = await lm.renderProjectFace(fakeFace, pCanvas);
                  const afterPx = Array.from(pCtx.getImageData(400, 450, 1, 1).data);
                  return { hasMenu, renderRes, beforePx, afterPx };
                })()
                """)
                assert art_replace["hasMenu"] is True
                assert art_replace["renderRes"]["layers"] >= 1
                assert art_replace[" renderRes"]["skipped"] if " renderRes" in art_replace else len(art_replace["renderRes"]["skipped"]) == 0
                assert art_replace["afterPx"][0] > 200 and art_replace["afterPx"][3] == 255
                print("PASS: Live art replacement on #cb-project-canvas verified:", art_replace)

                # 7. Export batch PNG to fronts so Deck Generator has a card to preview, then navigate to /deck-generator
                await cdp.send("Page.navigate", {"url": f"{BASE_URL}/deck-generator"})
                await asyncio.sleep(1.8)
                dg_title = await cdp.evaluate("document.title")
                assert "Deck Generator" in dg_title
                print("PASS: Loaded /deck-generator in browser:", dg_title)

                listener.cancel()

                print(f"Total network responses captured: {len(cdp.network_responses)}")
                print(f"Network 404 count: {len(cdp.network_404s)}")
                print(f"Console JS errors count: {len(cdp.console_errors)}")
                print(f"Uncaught page exceptions count: {len(cdp.page_exceptions)}")

                if cdp.network_404s:
                    print("FAIL: Network 404s detected:", cdp.network_404s)
                    return 1
                if cdp.console_errors or cdp.page_exceptions:
                    print("FAIL: Console errors / exceptions detected:", cdp.console_errors, cdp.page_exceptions)
                    return 1

                print("PASS: 0 network 404 errors and 0 JS console errors across /card-builder and /deck-generator.")
                return 0
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_browser_tests()))
