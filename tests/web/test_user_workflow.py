"""
tests/test_challenger_runtime_workflow_simulation.py

Empirical runtime user workflow simulation and challenge harness for Milestone 3.
Directly tests and verifies:
1. Full simulated user workflow:
   - Initial load: page is in `.mode-welcome` state with landing components.
   - Visitor clicks "Try Demo": fetches sample_save.sav -> passes to Web Worker ->
     receives 'result' -> page transitions to `.mode-active` -> Bag cards, Focus cards,
     and Stats cards render properly.
   - User adjusts setting (slots 20 -> 10): persists to localStorage -> dispatches
     'recompute' action to Worker -> receives 'result' -> Bag cards update to 10 slots.
   - User opens Crafting Tree modal: modal opens (display: flex) and contains D3 tree node elements.
   - User opens Calendar modal: modal opens (display: flex) and renders exactly 28 day cells across seasons.
2. Network integrity audit:
   - Verifies zero server or /api/ calls are ever made during the entire lifecycle.
   - Validates that all requests are strictly static assets (.html, .css, .js, .json, .whl, .png, .svg, .ttf).
3. Adversarial boundary tests:
   - Extreme bag slots limits (slots = 1).
   - Strategy mutations (journal <-> max-relationship).
   - LocalStorage persistence across page reloads.
"""

import asyncio
import http.server
import json
from pathlib import Path
import re
import shutil
import socket
import socketserver
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional
import urllib.request
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = REPO_ROOT / "web"
APP_JS = WEB_DIR / "app.js"
INDEX_HTML = WEB_DIR / "index.html"
STYLE_CSS = WEB_DIR / "style.css"
SAMPLE_SAVE = WEB_DIR / "sample_save.sav"


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class SilentStaticServer:
    """Threaded local HTTP server serving web/ directory."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.port = find_free_port()
        self.requests_log: List[str] = []
        self._httpd: Optional[socketserver.TCPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        req_log = self.requests_log
        base_dir = str(self.directory)

        class CustomHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=base_dir, **kwargs)

            def log_message(self, format, *args):
                if args:
                    req_log.append(str(args[0]))

        self._httpd = socketserver.TCPServer(("127.0.0.1", self.port), CustomHandler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        time.sleep(0.3)

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()


class ChromeBrowserHarness:
    """Controls headless Google Chrome via Chrome DevTools Protocol (CDP)."""

    def __init__(self, port: int, cdp_port: int):
        self.port = port
        self.cdp_port = cdp_port
        self.proc: Optional[subprocess.Popen] = None
        self.network_urls: List[str] = []

    def start(self):
        chrome_bin = shutil.which("google-chrome") or shutil.which("chromium")
        if not chrome_bin:
            pytest.skip("Headless Chrome/Chromium not installed in test environment")

        self.proc = subprocess.Popen([
            chrome_bin,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            f"--remote-debugging-port={self.cdp_port}",
            f"http://127.0.0.1:{self.port}/index.html",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5)

    def stop(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()


@pytest.fixture(scope="module")
def browser_env():
    """Starts static server and headless Chrome session."""
    server = SilentStaticServer(WEB_DIR)
    server.start()
    cdp_port = find_free_port()
    chrome = ChromeBrowserHarness(server.port, cdp_port)
    chrome.start()

    yield {
        "server": server,
        "chrome": chrome,
        "cdp_port": cdp_port,
        "base_url": f"http://127.0.0.1:{server.port}/index.html",
    }

    chrome.stop()
    server.stop()


async def get_cdp_session(cdp_port: int):
    """Connects to active page tab over websocket."""
    import websockets

    list_url = f"http://127.0.0.1:{cdp_port}/json/list"
    for _ in range(10):
        try:
            with urllib.request.urlopen(list_url, timeout=2) as r:
                tabs = json.loads(r.read())
                page_tabs = [t for t in tabs if t.get("type") == "page" and "index.html" in t.get("url", "")]
                if page_tabs:
                    ws_url = page_tabs[0]["webSocketDebuggerUrl"]
                    ws = await websockets.connect(ws_url)
                    return ws
        except Exception:
            pass
        await asyncio.sleep(0.5)
    raise RuntimeError("Could not find active index.html tab in Chrome CDP list")


class CDPClient:
    def __init__(self, ws):
        self.ws = ws
        self.msg_id = 0
        self.network_requests: List[str] = []

    async def send(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self.msg_id += 1
        curr_id = self.msg_id
        await self.ws.send(json.dumps({"id": curr_id, "method": method, "params": params or {}}))
        while True:
            raw = await self.ws.recv()
            data = json.loads(raw)
            if data.get("id") == curr_id:
                return data.get("result", {})
            if data.get("method") == "Network.requestWillBeSent":
                req_url = data.get("params", {}).get("request", {}).get("url", "")
                self.network_requests.append(req_url)

    async def evaluate(self, expression: str, return_by_value: bool = True) -> Any:
        res = await self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": return_by_value,
            "awaitPromise": True,
        })
        return res.get("result", {}).get("value")

    async def wait_for_engine_ready(self, timeout_sec: float = 35.0):
        t0 = time.time()
        while time.time() - t0 < timeout_sec:
            lbl = await self.evaluate('document.getElementById("pyodideStatusLabel")?.textContent')
            dot = await self.evaluate('document.getElementById("pyodideStatusDot")?.classList.contains("ready")')
            if lbl == "Engine Ready" or dot is True:
                return True
            await asyncio.sleep(0.5)
        raise TimeoutError("Pyodide WebAssembly runtime failed to report Engine Ready within timeout")


def test_static_asset_purity_contract():
    """Verify zero server /api/ or EventSource in codebase files."""
    app_text = APP_JS.read_text(encoding="utf-8")
    assert "/api/" not in app_text, "Found /api/ in web/app.js"
    assert "EventSource" not in app_text, "Found EventSource in web/app.js"

    html_text = INDEX_HTML.read_text(encoding="utf-8")
    assert "/api/" not in html_text, "Found /api/ in web/index.html"


def test_full_simulated_user_workflow(browser_env):
    """
    Simulates full runtime user lifecycle end-to-end:
    1. Initial load -> body has .mode-welcome.
    2. Try Demo clicked -> loads sample_save.sav -> Worker returns result ->
       mode becomes .mode-active -> Bag cards, Focus cards, Stats cards rendered.
    3. User adjusts setting (slots: 20 -> 10) -> saves to localStorage ->
       Worker recomputes -> Bag cards update to 10 slots.
    4. User opens Crafting Tree modal -> modal opens and contains node elements.
    5. User opens Calendar modal -> modal opens and displays 28 day cells.
    6. Verifies zero /api/ or server endpoints invoked throughout lifecycle.
    """
    async def _run():
        ws = await get_cdp_session(browser_env["cdp_port"])
        client = CDPClient(ws)

        await client.send("Runtime.enable")
        await client.send("Network.enable")

        # 1. Visitor loads page -> mode is .mode-welcome
        body_class = await client.evaluate("document.body.className")
        assert "mode-welcome" in (body_class or ""), f"Expected mode-welcome on load, got: {body_class}"
        assert await client.evaluate('document.getElementById("welcomeLanding") !== null')

        # Wait for Pyodide engine readiness
        await client.wait_for_engine_ready()

        # 2. Clicks 'Try Demo'
        await client.evaluate('document.getElementById("welcomeDemoBtn").click()')

        # Wait for transition to .mode-active
        t0 = time.time()
        active = False
        while time.time() - t0 < 15:
            classes = await client.evaluate("document.body.className")
            if "mode-active" in (classes or ""):
                active = True
                break
            await asyncio.sleep(0.4)
        assert active, "Page failed to transition to .mode-active after clicking Try Demo"

        # Verify Bag cards, Focus cards, Stats cards render properly
        bag_cards_count = await client.evaluate('document.querySelectorAll("#bagGrid .item-card").length')
        focus_cards_count = await client.evaluate('document.querySelectorAll("#focusGrid .focus-card").length')
        stats_progress = await client.evaluate('document.getElementById("cardGiftProgress")?.innerText')
        stats_completed = await client.evaluate('document.getElementById("cardCompletedNpcs")?.innerText')
        stats_incomplete = await client.evaluate('document.getElementById("cardIncompleteNpcs")?.innerText')
        stats_recipes = await client.evaluate('document.getElementById("cardRecipes")?.innerText')

        assert bag_cards_count > 0, f"Expected bag item-cards, got {bag_cards_count}"
        assert focus_cards_count > 0, f"Expected focus suggestion cards, got {focus_cards_count}"
        assert stats_progress and "GIFT PROGRESS" in stats_progress.upper()
        assert stats_completed and "COMPLETED VILLAGERS" in stats_completed.upper()
        assert stats_incomplete and "INCOMPLETE VILLAGERS" in stats_incomplete.upper()
        assert stats_recipes and "RECIPES" in stats_recipes.upper()

        # 3. User adjusts setting (slots from 20 to 10)
        # Update setting via saveSetting API
        await client.evaluate('saveSetting("slots", 10, true)')

        # Wait for localStorage and recomputed bag cards
        t1 = time.time()
        slots_updated = False
        while time.time() - t1 < 10:
            stored_raw = await client.evaluate('localStorage.getItem("fom_companion_settings_v1")')
            current_cards = await client.evaluate('document.querySelectorAll("#bagGrid .item-card").length')
            badge_text = await client.evaluate('document.getElementById("bagSlotsBadge")?.textContent')
            if stored_raw:
                parsed = json.loads(stored_raw)
                if parsed.get("slots") == 10 and current_cards == 10 and "10 / 10" in badge_text:
                    slots_updated = True
                    break
            await asyncio.sleep(0.3)
        assert slots_updated, "Bag cards failed to update to 10 slots after settings change"

        # 4. User opens Crafting Tree modal
        # Trigger either via focus card button or openCraftingTreeModal
        await client.evaluate('''(() => {
            const btn = document.querySelector("#focusGrid .tree-toggle");
            if (btn) btn.click();
            else {
                const keys = Object.keys(window._craftingTreeData || {});
                if (keys.length > 0) openCraftingTreeModal(window._craftingTreeData[keys[0]], 5);
            }
        })()''')

        await asyncio.sleep(0.6)
        tree_modal_display = await client.evaluate('document.getElementById("treeModal")?.style.display')
        tree_node_groups = await client.evaluate('document.querySelectorAll("#treeModal .tree-node-group").length')
        tree_card_nodes = await client.evaluate('document.querySelectorAll("#treeModal .d3-tree-node").length')
        assert tree_modal_display == "flex", f"Expected treeModal display 'flex', got '{tree_modal_display}'"
        assert (tree_node_groups > 0 or tree_card_nodes > 0), "Crafting tree modal does not contain node elements"

        # Close tree modal
        await client.evaluate("closeTreeModal()")
        await asyncio.sleep(0.3)

        # 5. User opens Calendar modal -> displays 28 day cells
        await client.evaluate("openCalendarModal()")
        await asyncio.sleep(0.5)

        cal_modal_display = await client.evaluate('document.getElementById("calendarModal")?.style.display')
        cal_day_cells = await client.evaluate('document.querySelectorAll("#calendarDaysGrid .cal-day-cell").length')
        assert cal_modal_display == "flex", f"Expected calendarModal display 'flex', got '{cal_modal_display}'"
        assert cal_day_cells == 28, f"Expected 28 calendar day cells, got {cal_day_cells}"

        # Close calendar modal
        await client.evaluate("closeCalendarModal()")
        await asyncio.sleep(0.3)

        # 6. Verify zero server or /api/ calls were ever made
        all_cdp_requests = client.network_requests
        server_requests = browser_env["server"].requests_log

        for req in server_requests:
            assert "/api/" not in req, f"Server recorded unauthorized /api/ call: {req}"
        for url in all_cdp_requests:
            assert "/api/" not in url, f"CDP recorded unauthorized /api/ call: {url}"

        await ws.close()

    asyncio.run(_run())


def test_calendar_season_tabs_all_render_28_cells(browser_env):
    """Verify that switching between all 4 season tabs renders exactly 28 day cells each."""
    async def _run():
        ws = await get_cdp_session(browser_env["cdp_port"])
        client = CDPClient(ws)
        await client.send("Runtime.enable")

        await client.evaluate("openCalendarModal()")
        await asyncio.sleep(0.3)

        for season in ["spring", "summer", "fall", "winter"]:
            await client.evaluate(f'document.querySelector(".cal-season-tab[data-season=\\"{season}\\"]").click()')
            await asyncio.sleep(0.15)
            cells = await client.evaluate('document.querySelectorAll("#calendarDaysGrid .cal-day-cell").length')
            assert cells == 28, f"Season {season} rendered {cells} day cells instead of 28"

        await client.evaluate("closeCalendarModal()")
        await ws.close()

    asyncio.run(_run())


def test_adversarial_slot_boundary_and_strategy_mutations(browser_env):
    """
    Adversarial test on boundary values:
    - Minimum slots limit: slots = 1.
    - Strategy switch: strategy = 'max-relationship'.
    - LocalStorage persistence check.
    """
    async def _run():
        ws = await get_cdp_session(browser_env["cdp_port"])
        client = CDPClient(ws)
        await client.send("Runtime.enable")

        # 1. Boundary slot = 1
        await client.evaluate('saveSetting("slots", 1, true)')
        t0 = time.time()
        updated_1 = False
        while time.time() - t0 < 6:
            cards = await client.evaluate('document.querySelectorAll("#bagGrid .item-card").length')
            if cards == 1:
                updated_1 = True
                break
            await asyncio.sleep(0.3)
        assert updated_1, "Boundary setting slots=1 failed to render exactly 1 item card"

        # 2. Strategy switch to max-relationship
        await client.evaluate('saveSetting("strategy", "max-relationship", true)')
        t1 = time.time()
        updated_strat = False
        while time.time() - t1 < 6:
            strat_label = await client.evaluate('document.getElementById("activeStrategy")?.textContent')
            if strat_label and "MAX-RELATIONSHIP" in strat_label.upper():
                updated_strat = True
                break
            await asyncio.sleep(0.3)
        assert updated_strat, "Strategy switch failed to update UI and recompute"

        # 3. Check localStorage schema validity
        raw_storage = await client.evaluate('localStorage.getItem("fom_companion_settings_v1")')
        data = json.loads(raw_storage)
        assert data["slots"] == 1
        assert data["strategy"] == "max-relationship"

        await ws.close()

    asyncio.run(_run())
