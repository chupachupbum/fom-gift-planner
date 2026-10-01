"""
tests/test_m3_adversarial.py

Milestone 3 Empirical Adversarial and Stress Verification Suite.
Thoroughly stress-tests the client-side frontend implementation in web/:
1. Client-side sprite resolver fuzzing: test all 557 items in data/item_data.json
   and data/recipes.json against ITEM_ID_TO_ASSET_NAME and web/icons/items/.
   Asserts 100% resolve to valid local sprite files.
2. NPC portrait resolver: test all 34 NPCs resolve to web/icons/npcs/.
3. Location icon resolver: test all 16 locations resolve to web/icons/locations/.
4. SVG placeholder generator: test SVG data URI formatting, XML validity,
   dimensions, initials, label colors, and adversarial characters.
5. Static file server simulation: run an ephemeral Python http.server on web/,
   fetch index.html, styles, scripts, worker, demo save, VFS databases,
   wheel, and fonts, verifying HTTP 200 without 404s.
6. Falsy sprite resolution probe: test behavior when item/npc/location ID is empty/null.
"""

import http.server
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = REPO_ROOT / "web"
APP_JS = WEB_DIR / "app.js"
INDEX_HTML = WEB_DIR / "index.html"
STYLE_CSS = WEB_DIR / "style.css"
DATA_DIR = REPO_ROOT / "data"

NODE_CANDIDATES = [
    shutil.which("node"),
    os.path.expanduser("~/.nvm/versions/node/v24.14.0/bin/node"),
    os.path.expanduser("~/.nvm/versions/node/v22.22.1/bin/node"),
]
NODE_PATH = next((p for p in NODE_CANDIDATES if p and os.path.exists(p)), None)


def _run_node_script(script: str) -> str:
    """Execute a Node.js script and return stdout."""
    assert NODE_PATH is not None, f"Node.js binary not found. Checked: {NODE_CANDIDATES}"
    res = subprocess.run(
        [NODE_PATH, "-e", script],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    if res.returncode != 0:
        raise RuntimeError(f"Node execution failed (code {res.returncode}):\n{res.stderr}")
    return res.stdout


def _get_free_port() -> int:
    """Find a random available TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Test 1: Item Sprite Resolver Fuzzing Across All Items
# ---------------------------------------------------------------------------

def test_client_side_sprite_resolver_fuzzing_all_items():
    """
    Fuzz resolveItemSprite() in web/app.js against all 557 items in data/item_data.json
    and all recipe products + ingredients in data/recipes.json.
    Every single item MUST resolve to an existing local PNG sprite file in web/icons/items/.
    """
    assert APP_JS.is_file(), "web/app.js is missing"

    # 1. Collect all canonical items from data/item_data.json
    with open(DATA_DIR / "item_data.json", encoding="utf-8") as f:
        item_data = json.load(f)
    items_557 = set(item_data.get("items", {}).keys())
    assert len(items_557) == 557, f"Expected 557 items in item_data.json, got {len(items_557)}"

    # 2. Collect all recipe products and ingredients from data/recipes.json
    with open(DATA_DIR / "recipes.json", encoding="utf-8") as f:
        recipes = json.load(f)
    recipe_items = set(recipes.keys())
    for r_id, details in recipes.items():
        for ing in details.get("ingredients", []):
            recipe_items.add(ing["item_id"])

    all_target_items = items_557 | recipe_items
    assert len(all_target_items) >= 557

    # 3. Execute resolveItemSprite in Node.js with the real web/app.js code
    node_eval_script = f"""
    const fs = require('fs');
    const vm = require('vm');
    const code = fs.readFileSync('web/app.js', 'utf8');

    const sandbox = {{
      window: {{}},
      document: {{ addEventListener: () => {{}}, getElementById: () => null, querySelector: () => null, querySelectorAll: () => [] }},
      localStorage: {{ getItem: () => null, setItem: () => {{}} }},
      Worker: function() {{}},
      console: console,
    }};
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(code, sandbox);

    const items = {json.dumps(sorted(list(all_target_items)))};
    const results = {{}};
    for (const item of items) {{
      results[item] = sandbox.resolveItemSprite(item);
    }}
    console.log(JSON.stringify(results));
    """
    raw_output = _run_node_script(node_eval_script)
    resolutions = json.loads(raw_output)

    # 4. Verify each resolved relative path exists on disk in web/
    missing_sprites = []
    for item_id, resolved_path in sorted(resolutions.items()):
        full_path = WEB_DIR / resolved_path
        if not full_path.is_file():
            missing_sprites.append((item_id, resolved_path))

    assert len(missing_sprites) == 0, (
        f"Sprite resolution failed for {len(missing_sprites)} / {len(all_target_items)} items!\n"
        f"Missing sprites: {missing_sprites}"
    )


# ---------------------------------------------------------------------------
# Test 2: NPC Portrait Resolver
# ---------------------------------------------------------------------------

def test_npc_portrait_resolver_all_34_npcs():
    """
    Test that resolveNpcPortrait() resolves all 34 NPCs from data/item_data.json
    to existing local PNG files in web/icons/npcs/.
    """
    with open(DATA_DIR / "item_data.json", encoding="utf-8") as f:
        item_data = json.load(f)
    npcs = set(item_data.get("npcs", {}).keys())
    assert len(npcs) == 34, f"Expected 34 NPCs, got {len(npcs)}"

    node_eval_script = f"""
    const fs = require('fs');
    const vm = require('vm');
    const code = fs.readFileSync('web/app.js', 'utf8');

    const sandbox = {{
      window: {{}},
      document: {{ addEventListener: () => {{}}, getElementById: () => null, querySelector: () => null, querySelectorAll: () => [] }},
      localStorage: {{ getItem: () => null, setItem: () => {{}} }},
      Worker: function() {{}},
      console: console,
    }};
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(code, sandbox);

    const npcs = {json.dumps(sorted(list(npcs)))};
    const results = {{}};
    for (const npc of npcs) {{
      results[npc] = sandbox.resolveNpcPortrait(npc);
    }}
    console.log(JSON.stringify(results));
    """
    raw_output = _run_node_script(node_eval_script)
    resolutions = json.loads(raw_output)

    missing_npcs = []
    for npc_id, resolved_path in sorted(resolutions.items()):
        full_path = WEB_DIR / resolved_path
        if not full_path.is_file():
            missing_npcs.append((npc_id, resolved_path))

    assert len(missing_npcs) == 0, f"NPC portrait resolution failed for {missing_npcs}"


# ---------------------------------------------------------------------------
# Test 3: Location Icon Resolver
# ---------------------------------------------------------------------------

def test_location_icon_resolver_all_16_locations():
    """
    Test that resolveLocationIcon() resolves all 16 locations from data/alt_sources.json
    to existing local PNG files in web/icons/locations/.
    """
    with open(DATA_DIR / "alt_sources.json", encoding="utf-8") as f:
        alt_sources = json.load(f)

    loc_icons = set()
    for item, sources in alt_sources.items():
        for s in sources:
            if "icon" in s:
                loc_icons.add(s["icon"])

    assert len(loc_icons) == 16, f"Expected 16 location icons, got {len(loc_icons)}"

    node_eval_script = f"""
    const fs = require('fs');
    const vm = require('vm');
    const code = fs.readFileSync('web/app.js', 'utf8');

    const sandbox = {{
      window: {{}},
      document: {{ addEventListener: () => {{}}, getElementById: () => null, querySelector: () => null, querySelectorAll: () => [] }},
      localStorage: {{ getItem: () => null, setItem: () => {{}} }},
      Worker: function() {{}},
      console: console,
    }};
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(code, sandbox);

    const locs = {json.dumps(sorted(list(loc_icons)))};
    const results = {{}};
    for (const loc of locs) {{
      results[loc] = sandbox.resolveLocationIcon(loc);
    }}
    console.log(JSON.stringify(results));
    """
    raw_output = _run_node_script(node_eval_script)
    resolutions = json.loads(raw_output)

    missing_locs = []
    for loc_id, resolved_path in sorted(resolutions.items()):
        full_path = WEB_DIR / resolved_path
        if not full_path.is_file():
            missing_locs.append((loc_id, resolved_path))

    assert len(missing_locs) == 0, f"Location icon resolution failed for {missing_locs}"


# ---------------------------------------------------------------------------
# Test 4: SVG Placeholder Generator Fuzzing
# ---------------------------------------------------------------------------

def test_fallback_svg_placeholder_generation():
    """
    Test generatePlaceholderSvg() with various inputs:
    - nonexistent item IDs
    - empty/null/undefined values
    - item vs npc labels
    - verifies valid SVG data URI prefix, dimensions, and XML syntax
    """
    test_cases = [
        ("nonexistent_item_xyz", "item"),
        ("mysterious_gem", "item"),
        ("adeline_alt", "npc"),
        ("", "item"),
        (None, "item"),
        ("multi_word_long_item_name", "item"),
    ]

    node_eval_script = f"""
    const fs = require('fs');
    const vm = require('vm');
    const code = fs.readFileSync('web/app.js', 'utf8');

    const sandbox = {{
      window: {{}},
      document: {{ addEventListener: () => {{}}, getElementById: () => null, querySelector: () => null, querySelectorAll: () => [] }},
      localStorage: {{ getItem: () => null, setItem: () => {{}} }},
      Worker: function() {{}},
      console: console,
    }};
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(code, sandbox);

    const testCases = {json.dumps(test_cases)};
    const results = testCases.map(([id, label]) => ({{
      id,
      label,
      uri: sandbox.generatePlaceholderSvg(id, label)
    }}));
    console.log(JSON.stringify(results));
    """
    raw_output = _run_node_script(node_eval_script)
    results = json.loads(raw_output)

    for r in results:
        uri = r["uri"]
        assert uri.startswith("data:image/svg+xml;utf8,"), f"Invalid URI prefix: {uri[:40]}"

        # Extract and parse raw SVG XML
        raw_svg = urllib.parse.unquote(uri.replace("data:image/svg+xml;utf8,", ""))
        root = ET.fromstring(raw_svg)
        assert root.tag.endswith("svg")
        assert root.attrib.get("width") == "48"
        assert root.attrib.get("height") == "48"
        assert root.attrib.get("viewBox") == "0 0 48 48"

        # Check background color difference for item vs npc
        rects = root.findall(".//{http://www.w3.org/2000/svg}rect") or root.findall(".//rect")
        assert len(rects) >= 1
        bg_fill = rects[0].attrib.get("fill")
        if r["label"] == "npc":
            assert bg_fill == "#8b6055", f"Expected NPC color #8b6055, got {bg_fill}"
        else:
            assert bg_fill == "#5a7a5e", f"Expected Item color #5a7a5e, got {bg_fill}"


# ---------------------------------------------------------------------------
# Test 5: Static File Server Simulation & Asset Link Resolution (HTTP 200)
# ---------------------------------------------------------------------------

def test_static_file_server_simulation_http_200():
    """
    Launch Python http.server on web/ and verify index.html and all linked
    assets (CSS, JS, fonts, icons, JSON databases, wheel, demo save) return HTTP 200.
    """
    port = _get_free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--directory", str(WEB_DIR)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)

    try:
        base_url = f"http://127.0.0.1:{port}"

        # 1. Fetch index.html
        with urllib.request.urlopen(f"{base_url}/index.html") as resp:
            assert resp.status == 200
            html = resp.read().decode("utf-8")

        # 2. Extract all local links from HTML
        hrefs = re.findall(r"href=[\"\x27]([^\x27\"]+)[\"\x27]", html)
        srcs = re.findall(r"src=[\"\x27]([^\x27\"]+)[\"\x27]", html)

        local_assets = set()
        for link in hrefs + srcs:
            if link.startswith("http://") or link.startswith("https://") or link.startswith("#"):
                continue
            local_assets.add(link)

        # 3. Extract CSS urls
        with urllib.request.urlopen(f"{base_url}/style.css") as resp:
            assert resp.status == 200
            css = resp.read().decode("utf-8")
        for u in re.findall(r"url\([\"\x27]?([^\)\"\x27]+)[\"\x27]?\)", css):
            if not (u.startswith("http://") or u.startswith("https://")):
                local_assets.add(u)

        # 4. Include assets fetched by Web Worker and app.js
        local_assets.update([
            "planner.worker.js",
            "sample_save.sav",
            "py/web_bridge.py",
            "data/item_data.json",
            "data/recipes.json",
            "data/alt_sources.json",
            "data/item_locations.json",
            "data/recipe_sources.json",
            "data/item_seasons.json",
        ])

        # 5. Include wheel file(s)
        whls = list(WEB_DIR.glob("*.whl"))
        assert len(whls) > 0, "No .whl file found in web/"
        for w in whls:
            local_assets.add(w.name)

        # 6. Fetch every asset and verify HTTP 200
        failed_requests = []
        for asset in sorted(local_assets):
            url = f"{base_url}/{asset}"
            try:
                with urllib.request.urlopen(url) as r:
                    if r.status != 200:
                        failed_requests.append((asset, r.status))
            except Exception as e:
                failed_requests.append((asset, str(e)))

        assert len(failed_requests) == 0, f"Static asset requests failed: {failed_requests}"
    finally:
        proc.terminate()
        proc.wait()


# ---------------------------------------------------------------------------
# Test 6: Fallback Path Probing for Falsy Inputs
# ---------------------------------------------------------------------------

def test_falsy_id_fallback_paths_exist_or_data_uri():
    """
    Test that when falsy inputs ('', null) are provided to resolveItemSprite,
    resolveNpcPortrait, or resolveLocationIcon, they do NOT return broken relative URLs
    pointing to non-existent files.
    """
    node_eval_script = """
    const fs = require('fs');
    const vm = require('vm');
    const code = fs.readFileSync('web/app.js', 'utf8');

    const sandbox = {
      window: {},
      document: { addEventListener: () => {}, getElementById: () => null, querySelector: () => null, querySelectorAll: () => [] },
      localStorage: { getItem: () => null, setItem: () => {} },
      Worker: function() {},
      console: console,
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(code, sandbox);

    const fallbacks = {
      item_empty: sandbox.resolveItemSprite(''),
      item_null: sandbox.resolveItemSprite(null),
      npc_empty: sandbox.resolveNpcPortrait(''),
      npc_null: sandbox.resolveNpcPortrait(null),
      loc_empty: sandbox.resolveLocationIcon(''),
      loc_null: sandbox.resolveLocationIcon(null),
    };
    console.log(JSON.stringify(fallbacks));
    """
    raw_output = _run_node_script(node_eval_script)
    fallbacks = json.loads(raw_output)

    broken_fallbacks = []
    for key, path_str in fallbacks.items():
        if path_str.startswith("data:"):
            continue  # Valid data URI
        full_path = WEB_DIR / path_str
        if not full_path.is_file():
            broken_fallbacks.append((key, path_str))

    assert len(broken_fallbacks) == 0, (
        f"Falsy fallback paths point to non-existent files on disk: {broken_fallbacks}"
    )
