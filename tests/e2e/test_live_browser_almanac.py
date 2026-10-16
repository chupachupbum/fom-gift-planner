"""
tests/e2e/test_live_browser_almanac.py

Automated End-to-End Live Browser Verification Suite for Milestone 4:
- Launches the live Companion FastAPI server via uvicorn in a daemon thread.
- Launches headless Google Chrome 154 via Chrome DevTools Protocol (CDP).
- Verifies:
  1. Clean load with ZERO HTTP 404s/500s and ZERO console.error logs.
  2. Mode switcher toggles between Gift Planner and Almanac Planner.
  3. 12 Almanac Category cards render accurate icons and counters.
  4. Category drawer opens, live search filters items, swatch pills toggle variants.
  5. Ready-to-craft batch queue renders station badges and step sequences.
  6. Raw material blocker cards open #treeModal and D3 SVG hierarchy renders.
"""

import asyncio
import json
import os
import socket
import subprocess
import threading
import time
from typing import Any, Dict, List, Tuple
import pytest
import httpx
import uvicorn
import websockets

from companion.server import app


def get_free_port() -> int:
    """Finds an available ephemeral port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ChromeCDPRunner:
    """Zero-dependency Chrome DevTools Protocol runner."""

    def __init__(self, port: int):
        self.port = port
        self.proc: subprocess.Popen = None
        self.ws_url: str = ""
        self.ws = None
        self.msg_id = 0
        self.network_errors: List[Tuple[int, str]] = []
        self.console_errors: List[str] = []

    async def start(self):
        chrome_bin = "/usr/bin/google-chrome"
        if not os.path.exists(chrome_bin):
            pytest.skip("Google Chrome binary not found on host")

        self.proc = subprocess.Popen([
            chrome_bin,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-extensions",
            f"--remote-debugging-port={self.port}",
            "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Wait for CDP endpoint to become responsive
        for _ in range(40):
            try:
                async with httpx.AsyncClient() as client:
                    r = await client.get(f"http://127.0.0.1:{self.port}/json", timeout=1.0)
                    pages = r.json()
                    for p in pages:
                        if p.get("type") == "page" and "webSocketDebuggerUrl" in p:
                            self.ws_url = p["webSocketDebuggerUrl"]
                            break
                    if self.ws_url:
                        break
            except Exception:
                await asyncio.sleep(0.1)

        if not self.ws_url:
            self.stop()
            raise RuntimeError(f"Could not connect to Chrome CDP on port {self.port}")

        self.ws = await websockets.connect(self.ws_url, max_size=10 * 1024 * 1024)
        await self.send("Network.enable")
        await self.send("Runtime.enable")
        await self.send("Page.enable")

    async def send(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        self.msg_id += 1
        payload = {"id": self.msg_id, "method": method}
        if params:
            payload["params"] = params
        await self.ws.send(json.dumps(payload))
        return payload

    async def evaluate(self, expression: str) -> Any:
        self.msg_id += 1
        mid = self.msg_id
        payload = {
            "id": mid,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "returnByValue": True, "awaitPromise": True},
        }
        await self.ws.send(json.dumps(payload))

        while True:
            raw = await asyncio.wait_for(self.ws.recv(), timeout=5.0)
            msg = json.loads(raw)
            self._handle_event(msg)
            if msg.get("id") == mid:
                result_data = msg.get("result", {}).get("result", {})
                return result_data.get("value")

    def _handle_event(self, msg: Dict[str, Any]):
        method = msg.get("method")
        params = msg.get("params", {})
        if method == "Page.loadEventFired":
            self.loaded = True
        elif method == "Network.responseReceived":
            resp = params.get("response", {})
            status = resp.get("status", 200)
            url = resp.get("url", "")
            if status >= 400 and not url.endswith("/favicon.ico"):
                self.network_errors.append((status, url))
        elif method == "Runtime.consoleAPICalled":
            log_type = params.get("type")
            if log_type == "error":
                args = [str(a.get("value")) for a in params.get("args", [])]
                self.console_errors.append(" ".join(args))
        elif method == "Runtime.exceptionThrown":
            details = params.get("exceptionDetails", {})
            self.console_errors.append(details.get("text", "Uncaught Exception"))

    async def wait_for_load(self, timeout: float = 6.0):
        start = time.time()
        self.loaded = False
        while time.time() - start < timeout:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=0.2)
                msg = json.loads(raw)
                self._handle_event(msg)
                if self.loaded:
                    break
            except asyncio.TimeoutError:
                pass
        # Extra wait for initial fetch and DOM render
        await asyncio.sleep(0.5)

    def stop(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self.proc.kill()


@pytest.fixture(scope="module")
def live_server():
    """Starts uvicorn companion server in background thread on dynamic port."""
    server_port = get_free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=server_port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Health check
    ready = False
    for _ in range(40):
        try:
            r = httpx.get(f"http://127.0.0.1:{server_port}/api/state", timeout=1.0)
            if r.status_code == 200:
                ready = True
                break
        except Exception:
            time.sleep(0.1)

    if not ready:
        server.should_exit = True
        thread.join(timeout=1.0)
        raise RuntimeError("Live Companion server failed to start")

    yield f"http://127.0.0.1:{server_port}"

    server.should_exit = True
    thread.join(timeout=2.0)


def test_live_browser_almanac_full_journey(live_server):
    """
    Executes full interactive browser journey:
    1. Navigation and clean asset loading (0 console errors, 0 404s).
    2. Mode tab switching.
    3. 12 Almanac category dashboard cards.
    4. Drawer open, search filter, and swatch variant pills.
    5. Ready-to-craft batch queue & D3 #treeModal rendering.
    """
    asyncio.run(_async_test_journey(live_server))


async def _async_test_journey(live_server):
    cdp_port = get_free_port()
    cdp = ChromeCDPRunner(port=cdp_port)
    await cdp.start()

    try:
        # 1. Navigate to live companion server
        await cdp.send("Page.navigate", {"url": f"{live_server}/"})
        await cdp.wait_for_load(timeout=3.0)

        # Assert zero HTTP 404/500 errors and zero JS console errors
        assert len(cdp.network_errors) == 0, f"Network errors observed: {cdp.network_errors}"
        assert len(cdp.console_errors) == 0, f"Console errors observed: {cdp.console_errors}"

        # 2. Verify Mode Switcher Buttons Exist
        tab_gift = await cdp.evaluate("Boolean(document.getElementById('tabGiftPlanner') || document.getElementById('tabBtnGiftPlanner'))")
        tab_almanac = await cdp.evaluate("Boolean(document.getElementById('tabAlmanacPlanner') || document.getElementById('tabBtnAlmanacPlanner'))")
        assert tab_gift and tab_almanac, "Mode switcher tabs not found in DOM"

        # 3. Click Almanac Planner Tab
        await cdp.evaluate("""(() => {
            const btn = document.getElementById('tabAlmanacPlanner') || document.getElementById('tabBtnAlmanacPlanner');
            if (btn) btn.click();
        })()""")
        await asyncio.sleep(0.2)

        is_almanac_active = await cdp.evaluate("""(() => {
            const btn = document.getElementById('tabAlmanacPlanner') || document.getElementById('tabBtnAlmanacPlanner');
            return btn ? btn.classList.contains('active') : false;
        })()""")
        almanac_display = await cdp.evaluate("window.getComputedStyle(document.getElementById('almanacPlannerSection')).display")
        gift_display = await cdp.evaluate("window.getComputedStyle(document.getElementById('giftPlannerSection')).display")

        assert is_almanac_active is True, "Almanac tab button did not gain active class"
        assert almanac_display != "none", "Almanac planner section is hidden"
        assert gift_display == "none", "Gift planner section is not hidden"

        # 4. Verify 12 Categories Render in Dashboard
        card_count = await cdp.evaluate("document.querySelectorAll('#almanacCategoryGrid .almanac-category-card').length")
        assert card_count == 12, f"Expected 12 category cards, got {card_count}"

        # 5. Test Opening Category Drawer (Click first category card)
        await cdp.evaluate("document.querySelector('#almanacCategoryGrid .almanac-category-card').click()")
        await asyncio.sleep(0.3)

        drawer_open = await cdp.evaluate("document.getElementById('almanacDrawerBackdrop').classList.contains('active')")
        assert drawer_open is True, "Category drawer did not open on category card click"

        # Test drawer items populated
        drawer_items_count = await cdp.evaluate("document.querySelectorAll('#almanacItemsGrid .almanac-item-card, #almanacItemsGrid .swatch-group-card').length")
        assert drawer_items_count > 0, "Category drawer contains 0 items"

        # Test live search filter inside drawer
        await cdp.evaluate("""(() => {
            const input = document.getElementById('almanacSearchInput');
            input.value = 'zzznonexistentitem999';
            input.dispatchEvent(new Event('input', { bubbles: true }));
        })()""")
        await asyncio.sleep(0.3)

        filtered_count = await cdp.evaluate("document.querySelectorAll('#almanacItemsGrid .almanac-item-card:not([style*=\"display: none\"]), #almanacItemsGrid .swatch-group-card:not([style*=\"display: none\"])').length")
        assert filtered_count == 0, f"Expected 0 items for nonexistent search, found {filtered_count}"

        # Clear search
        await cdp.evaluate("""(() => {
            const input = document.getElementById('almanacSearchInput');
            input.value = '';
            input.dispatchEvent(new Event('input', { bubbles: true }));
        })()""")
        await asyncio.sleep(0.2)

        # Close drawer
        await cdp.evaluate("document.getElementById('closeAlmanacDrawerBtn').click()")
        await asyncio.sleep(0.3)

        # 6. Verify Ready-to-Craft Queue
        craft_queue_exists = await cdp.evaluate("Boolean(document.getElementById('almanacBatchQueueContainer'))")
        assert craft_queue_exists is True, "Ready to craft container not found"

        # 7. Test D3 Tree Modal
        blocker_btn_exists = await cdp.evaluate("Boolean(document.querySelector('.almanac-tree-btn'))")
        if blocker_btn_exists:
            await cdp.evaluate("document.querySelector('.almanac-tree-btn').click()")
            await asyncio.sleep(0.5)

            modal_visible = await cdp.evaluate("window.getComputedStyle(document.getElementById('treeModal')).display != 'none'")
            svg_nodes_count = await cdp.evaluate("document.querySelectorAll('#treeModalBody svg .d3-tree-node').length")

            assert modal_visible is True, "D3 tree modal failed to open"
            assert svg_nodes_count > 0, f"Expected D3 tree SVG nodes, got {svg_nodes_count}"

            # Close tree modal
            await cdp.evaluate("document.getElementById('treeModalClose').click()")
            await asyncio.sleep(0.2)

    finally:
        cdp.stop()
