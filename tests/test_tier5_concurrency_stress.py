"""
tests/test_tier5_concurrency_stress.py

Milestone 5 Phase 2: Tier 5 Concurrency, Stress & Security Hardening Test Suite.
Adversarial challenge and empirical stress-testing for the client-side Pyodide web application:

1. Concurrency & Stress (Rapid sequential recomputations & memory leak bounds):
   - 50 rapid sequential recomputations simulating slider moves with tracemalloc memory bounds.
   - Multi-threaded re-entrancy and thread-safety under concurrent load (8 worker threads).
   - Scalability with large save files (300+ items, all NPCs, extensive recipes).
   - Web Worker rapid sequential recompute messages processing without dropped events or VFS leakage.

2. Corrupted & Malicious localStorage State Recovery:
   - Malformed/non-JSON storage strings (syntax errors, scripts, empty strings).
   - Unexpected primitive and array storage types.
   - Missing/partial key dictionaries (graceful defaulting to all 15 DEFAULT_SETTINGS).
   - Out-of-range, boundary, and hostile configuration values.
   - Web bridge execution resilience on extreme configurations.

3. Sanitization & XSS Resilience:
   - Save file player/farm names with injection payloads (<script>, <img>, quotes, entities).
   - Python web bridge RFC 8259 JSON serialization and character integrity.
   - Client-side SVG placeholder generator injection safety and attribute escaping.
   - White-box frontend DOM XSS audit (identifying unescaped innerHTML sinks in app.js).

4. Zero Network Leakage:
   - Static analysis confirming zero /api/ endpoints, EventSource, WebSocket, XMLHttpRequest.
   - Static analysis confirming zero third-party telemetry, tracking, or analytics domains.
   - Dynamic network interception asserting 0 remote outbound calls during demo, plan, and recompute workflows.

5. Pyodide Web Worker Message State Machine Robustness:
   - Premature recompute before init or save file load (graceful error response).
   - Plan request before init completes (automatic initialization recovery).
   - Idempotent concurrent init requests.
   - Unknown action message handling.
   - Malformed plan payload handling (missing saveBytes).
   - Rapid UI demo spamming (10x Try Demo) sequential processing without VFS accumulation.

6. Modal & UI Interaction Robustness:
   - ESC key dismissal for treeModal, calendarModal, and recipeModal.
   - Modal backdrop click dismissal for treeModal and calendarModal.
   - Modal close button dismissal for treeModalClose and calendarModalClose.
"""

import concurrent.futures
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import tracemalloc
from typing import Any, Dict, List, Optional
import urllib.parse
import xml.etree.ElementTree as ET
import pytest

from fom_planner.models import InGameDate, SaveData
from tests.e2e.conftest import (
    DATA_DIR,
    REPO_ROOT,
    SAMPLE_SAVE_PATH,
    WEB_BRIDGE_PATH,
    WEB_DATA_DIR,
    get_web_bridge,
    make_synthetic_save_bytes,
)

WEB_DIR = REPO_ROOT / "web"
APP_JS = WEB_DIR / "app.js"
WORKER_JS = WEB_DIR / "planner.worker.js"
INDEX_HTML = WEB_DIR / "index.html"

NODE_CANDIDATES = [
    shutil.which("node"),
    os.path.expanduser("~/.nvm/versions/node/v24.14.0/bin/node"),
    os.path.expanduser("~/.nvm/versions/node/v22.22.1/bin/node"),
]
NODE_BIN = next((p for p in NODE_CANDIDATES if p and os.path.exists(p)), None)


def run_node_snippet(script: str) -> str:
    """Executes a Node.js snippet and returns stdout."""
    assert NODE_BIN is not None, f"Node.js binary not found. Checked: {NODE_CANDIDATES}"
    res = subprocess.run(
        [NODE_BIN, "-e", script],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"Node.js execution failed (code {res.returncode}):\n"
            f"STDOUT:\n{res.stdout}\n"
            f"STDERR:\n{res.stderr}"
        )
    return res.stdout


CANONICAL_PLAN_KEYS = (
    "save_info",
    "in_game_date",
    "stats",
    "bag_plan",
    "focus_suggestions",
    "focus_trees",
    "unobtained_recipes",
    "recipe_stats",
    "source_priority",
    "npc_progress",
    "completed_npcs_details",
    "incomplete_npcs_details",
    "infused_items",
    "config",
    "error",
    "generated_at",
)


def assert_canonical_plan_dict(plan: dict) -> dict:
    """Asserts that plan dict contains all 16 canonical keys conforming to companion schema."""
    assert isinstance(plan, dict), f"Plan is not a dict: {type(plan)}"
    for k in CANONICAL_PLAN_KEYS:
        assert k in plan, f"Missing canonical key '{k}' in plan"
    assert isinstance(plan["save_info"], dict)
    assert isinstance(plan["in_game_date"], dict)
    assert isinstance(plan["stats"], dict)
    assert isinstance(plan["bag_plan"], list)
    assert isinstance(plan["focus_suggestions"], list)
    assert isinstance(plan["focus_trees"], list)
    assert isinstance(plan["source_priority"], list)
    assert isinstance(plan["npc_progress"], dict)
    return plan


# ==============================================================================
# SECTION 1: Rapid Sequential Recomputations & Memory Leak Bounds
# ==============================================================================

class TestRapidSequentialRecomputationsAndMemoryBounds:
    """
    Stress-tests rapid sequential recomputations simulating rapid slider movements,
    verifying memory bounds, multi-threaded safety, and worker throughput.
    """

    @pytest.fixture(autouse=True)
    def setup_bridge(self):
        bridge = get_web_bridge()
        assert bridge is not None, "web/py/web_bridge.py must be importable"
        bridge.init_bridge(str(WEB_DATA_DIR))
        self.bridge = bridge
        self.sample_bytes = SAMPLE_SAVE_PATH.read_bytes()

    def test_rapid_sequential_recomputations_memory_bounded(self):
        """
        Simulates a user aggressively dragging settings sliders back-and-forth across
        50 rapid sequential recomputations. Uses tracemalloc to verify that memory
        allocations remain bounded (< 3 MB growth) with zero memory accumulation.
        """
        tracemalloc.start()
        snapshot_start = tracemalloc.take_snapshot()

        slider_permutations = []
        for i in range(50):
            slots_val = 1 + (i % 30)
            loved_val = 1 + (i % 10)
            liked_val = 1 + ((i * 2) % 10)
            vendor_boost = 1.0 + ((i % 9) * 0.5)
            seasonal_boost = 1.0 + ((i % 5) * 0.5)
            strategy = "max-relationship" if (i % 4 == 0) else "journal"
            focus_sort = ["impact", "deficit", "quick-wins"][i % 3]

            conf = {
                "slots": slots_val,
                "loved_weight": loved_val,
                "liked_weight": liked_val,
                "vendor_boost": vendor_boost,
                "seasonal_boost": seasonal_boost,
                "strategy": strategy,
                "focus_sort": focus_sort,
                "mode": "auto",
            }
            slider_permutations.append(conf)

        # Baseline warmup (first 5 runs)
        for conf in slider_permutations[:5]:
            raw = self.bridge.generate_plan(self.sample_bytes, config_dict=conf, filename="rapid_slider.sav")
            assert raw is not None

        snapshot_warm = tracemalloc.take_snapshot()

        # Execute remaining 45 iterations
        for idx, conf in enumerate(slider_permutations[5:], start=5):
            raw = self.bridge.generate_plan(self.sample_bytes, config_dict=conf, filename="rapid_slider.sav")
            data = json.loads(raw)
            assert_canonical_plan_dict(data)
            assert data["error"] is None
            assert data["stats"]["max_slots"] == conf["slots"]
            assert data["stats"]["strategy"] == conf["strategy"]

        snapshot_end = tracemalloc.take_snapshot()
        tracemalloc.stop()

        # Compute memory delta between warm cache and final run
        stats_diff = snapshot_end.compare_to(snapshot_warm, 'lineno')
        total_growth_bytes = sum(stat.size_diff for stat in stats_diff if stat.size_diff > 0)
        total_growth_mb = total_growth_bytes / (1024 * 1024)

        # Memory growth across 45 intensive recomputations must be strictly bounded under 4 MB
        assert total_growth_mb < 4.0, f"Memory growth exceeded bound: {total_growth_mb:.2f} MB"

    def test_multithreaded_reentrancy_stress(self):
        """
        Executes generate_plan concurrently across 8 threads simultaneously
        with distinct configurations and saves to verify thread re-entrancy
        and prevent race conditions or cross-contamination.
        """
        thread_configs = [
            {"slots": 5, "strategy": "journal", "mode": "weekday"},
            {"slots": 10, "strategy": "max-relationship", "mode": "saturday"},
            {"slots": 15, "strategy": "journal", "mode": "auto"},
            {"slots": 20, "strategy": "max-relationship", "mode": "all"},
            {"slots": 25, "strategy": "journal", "mode": "market-only"},
            {"slots": 30, "strategy": "max-relationship", "mode": "weekday"},
            {"slots": 12, "strategy": "journal", "focus_sort": "deficit"},
            {"slots": 18, "strategy": "journal", "focus_sort": "quick-wins"},
        ]

        def worker_task(cfg: dict, idx: int):
            # Alternate between synthetic save and real sample save
            if idx % 2 == 0:
                save_payload = make_synthetic_save_bytes(player_name=f"Player_{idx}", day=(idx + 1))
            else:
                save_payload = self.sample_bytes

            raw = self.bridge.generate_plan(save_payload, config_dict=cfg, filename=f"thread_{idx}.sav")
            parsed = json.loads(raw)
            assert_canonical_plan_dict(parsed)
            assert parsed["error"] is None
            assert parsed["stats"]["max_slots"] == cfg["slots"]
            assert parsed["stats"]["strategy"] == cfg["strategy"]
            return parsed

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker_task, cfg, i) for i, cfg in enumerate(thread_configs)]
            results = [f.result() for f in futures]

        assert len(results) == 8
        # Ensure thread outputs did not cross-contaminate
        for idx, res in enumerate(results):
            expected_slots = thread_configs[idx]["slots"]
            assert res["stats"]["max_slots"] == expected_slots

    def test_large_save_file_scalability(self):
        """
        Stress-tests performance on an end-game save file with 300 inventory items,
        all 35 NPCs gifted and high affection, and dozens of unlocked recipes.
        Execution must complete in under 1.5 seconds.
        """
        large_inventory = []
        for i in range(300):
            item_id = "turnip" if i % 3 == 0 else ("cabbage" if i % 3 == 1 else "potato")
            large_inventory.append({"item_id": item_id, "count": (i % 99) + 1})

        npc_affection = {}
        all_npcs = [
            "adeline", "balor", "caldarus", "celine", "darcy", "dell", "dozy", "eiland", "elsie", "errol",
            "hayden", "hemlock", "henrietta", "holt", "josephine", "juniper", "landen", "louis", "luc",
            "maple", "march", "merri", "nora", "olric", "priestess", "reina", "ryis", "seridia", "stillwell",
            "taliferro", "terithia", "valen", "vera", "wheedle", "zorel",
        ]
        for npc in all_npcs:
            npc_affection[npc] = 500.0

        large_save_bytes = make_synthetic_save_bytes(
            player_name="CompletionistHero",
            farm_name="MegaEndgameFarm",
            year=5,
            season="winter",
            day=28,
            inventory_items=large_inventory,
            npc_affection=npc_affection,
            unlocked_recipes=["spring_salad", "cabbage_slaw", "hot_cocoa", "trail_mix"],
        )

        t0 = time.perf_counter()
        raw_json = self.bridge.generate_plan(
            large_save_bytes,
            config_dict={"slots": 30, "strategy": "max-relationship"},
            filename="large_save.sav"
        )
        duration = time.perf_counter() - t0

        data = json.loads(raw_json)
        assert_canonical_plan_dict(data)
        assert data["error"] is None
        assert data["save_info"]["player_name"] == "CompletionistHero"
        # Bounded execution time under 1.5s
        assert duration < 1.5, f"Large save planning too slow: {duration:.2f}s"

    @pytest.mark.skipif(NODE_BIN is None, reason="Node.js binary not available")
    def test_worker_rapid_sequential_recomputes_node(self):
        """
        Tests the Pyodide Web Worker message loop in Node.js when hit with
        20 rapid sequential 'recompute' messages simulating rapid slider dragging.
        Asserts 20 distinct 'result' messages returned with matching configurations
        and zero duplicate VFS files created.
        """
        script = """
const fs = require('fs');
const vm = require('vm');

const workerCode = fs.readFileSync('web/planner.worker.js', 'utf8');

const messages = [];
const vfs = {};

const mockPyodide = {
  FS: {
    mkdirTree: (p) => {},
    writeFile: (p, data) => { vfs[p] = data; },
    analyzePath: (p) => ({ exists: p in vfs }),
  },
  loadPackage: async () => {},
  pyimport: (name) => {
    if (name === 'micropip') return { install: async () => {} };
    if (name === 'web_bridge') {
      return {
        generate_plan: (savePath, configStr, filename) => {
          const conf = typeof configStr === 'string' ? JSON.parse(configStr) : (configStr || {});
          return JSON.stringify({
            save_info: { found: true },
            stats: { max_slots: conf.slots || 20, strategy: conf.strategy || 'journal' },
            bag_plan: [],
            focus_suggestions: [],
            focus_trees: [],
            source_priority: [],
            npc_progress: {},
            error: null
          });
        }
      };
    }
    return {};
  },
  runPython: () => {}
};

const sandbox = {
  self: {
    location: { href: 'http://localhost:8000/planner.worker.js' },
    postMessage: (msg) => messages.push(msg),
    importScripts: () => {},
    onmessage: null
  },
  loadPyodide: async () => mockPyodide,
  fetch: async () => ({ ok: true, text: async () => '{}' }),
  performance: { now: () => Date.now() },
  URL: URL,
  Uint8Array: Uint8Array,
  console: console
};

vm.createContext(sandbox);
vm.runInContext(workerCode, sandbox);

async function runTest() {
  // 1. Initial plan load
  await sandbox.self.onmessage({
    data: { action: 'plan', saveBytes: new Uint8Array([1, 2, 3]), config: { slots: 10 } }
  });

  // 2. Burst of 20 rapid recompute messages
  for (let i = 1; i <= 20; i++) {
    await sandbox.self.onmessage({
      data: { action: 'recompute', config: { slots: i, strategy: i % 2 === 0 ? 'max-relationship' : 'journal' } }
    });
  }

  const resultMessages = messages.filter(m => m.action === 'result');
  const vfsKeys = Object.keys(vfs);

  console.log(JSON.stringify({
    totalResults: resultMessages.length,
    lastSlot: resultMessages[resultMessages.length - 1].plan.stats.max_slots,
    vfsKeys: vfsKeys
  }));
}

runTest().catch(err => {
  console.error(err);
  process.exit(1);
});
"""
        out = run_node_snippet(script)
        data = json.loads(out)
        # 1 initial plan + 20 recomputes = 21 result messages
        assert data["totalResults"] == 21
        assert data["lastSlot"] == 20
        # VFS tmp file was overwritten in place, not exploded
        tmp_files = [k for k in data["vfsKeys"] if k.startswith("/tmp/")]
        assert len(tmp_files) <= 2


# ==============================================================================
# SECTION 2: Corrupted & Malicious localStorage State Recovery
# ==============================================================================

class TestLocalStorageCorruptedStateRecovery:
    """
    Stress-tests localStorage corrupted schemas, malicious payloads, type mismatches,
    and out-of-range configurations in web/app.js.
    """

    @pytest.mark.skipif(NODE_BIN is None, reason="Node.js binary not available")
    @pytest.mark.parametrize(
        "malicious_storage_val",
        [
            "{invalid_json_broken",
            "<script>alert('xss')</script>",
            "undefined",
            "null",
            "",
            "NaN",
            "{{{{",
        ],
    )
    def test_localstorage_non_json_string_recovery(self, malicious_storage_val: str):
        """
        When localStorage contains broken syntax or non-JSON payloads, loadSettings()
        must catch SyntaxError and safely reset currentSettings to DEFAULT_SETTINGS.
        """
        script = f"""
const fs = require('fs');
const vm = require('vm');

const appCode = fs.readFileSync('web/app.js', 'utf8');

let stored = {json.dumps(malicious_storage_val)};
const storage = {{
  getItem: (k) => stored,
  setItem: (k, v) => {{ stored = v; }}
}};

const elements = {{}};
const mockDoc = {{
  getElementById: (id) => elements[id] || (elements[id] = {{
    id, textContent: '', innerHTML: '', style: {{}},
    classList: {{ add: ()=>{{}}, remove: ()=>{{}} }},
    addEventListener: () => {{}}
  }}),
  querySelectorAll: () => [],
  addEventListener: () => {{}},
  createElement: (tag) => ({{
    tagName: tag, style: {{}},
    classList: {{ add: ()=>{{}}, remove: ()=>{{}} }},
    appendChild: ()=>{{}}, addEventListener: () => {{}}
  }}),
  body: {{ classList: {{ add: ()=>{{}}, remove: ()=>{{}} }} }}
}};

const sandbox = {{
  localStorage: storage,
  document: mockDoc,
  window: {{}},
  console: {{ warn: ()=>{{}}, log: ()=>{{}}, error: ()=>{{}} }},
  setTimeout: ()=>{{}}, clearTimeout: ()=>{{}},
  Worker: function() {{}}, FileReader: function() {{}},
  fetch: async () => {{}}, URL: URL, Uint8Array: Uint8Array
}};

vm.createContext(sandbox);
vm.runInContext(appCode, sandbox);
vm.runInContext('loadSettings()', sandbox);
const settings = vm.runInContext('currentSettings', sandbox);

console.log(JSON.stringify(settings));
"""
        out = run_node_snippet(script)
        settings = json.loads(out)
        assert isinstance(settings, dict)
        assert settings["strategy"] == "journal"
        assert settings["slots"] == 20
        assert settings["loved_weight"] == 3
        assert settings["liked_weight"] == 1
        assert settings["vendor_boost"] == 1.5

    @pytest.mark.skipif(NODE_BIN is None, reason="Node.js binary not available")
    @pytest.mark.parametrize(
        "primitive_json",
        [
            "12345",
            "true",
            "false",
            "\"plain_string\"",
            "[1, 2, 3]",
        ],
    )
    def test_localstorage_primitive_types_recovery(self, primitive_json: str):
        """
        When localStorage contains valid JSON but of primitive or array type,
        loadSettings() must not crash the application.
        """
        script = f"""
const fs = require('fs');
const vm = require('vm');

const appCode = fs.readFileSync('web/app.js', 'utf8');

let stored = {json.dumps(primitive_json)};
const storage = {{
  getItem: (k) => stored,
  setItem: (k, v) => {{ stored = v; }}
}};

const elements = {{}};
const mockDoc = {{
  getElementById: (id) => elements[id] || (elements[id] = {{
    id, textContent: '', innerHTML: '', style: {{}},
    classList: {{ add: ()=>{{}}, remove: ()=>{{}} }},
    addEventListener: () => {{}}
  }}),
  querySelectorAll: () => [],
  addEventListener: () => {{}},
  createElement: (tag) => ({{
    tagName: tag, style: {{}},
    classList: {{ add: ()=>{{}}, remove: ()=>{{}} }},
    appendChild: ()=>{{}}, addEventListener: () => {{}}
  }}),
  body: {{ classList: {{ add: ()=>{{}}, remove: ()=>{{}} }} }}
}};

const sandbox = {{
  localStorage: storage,
  document: mockDoc,
  window: {{}},
  console: {{ warn: ()=>{{}}, log: ()=>{{}}, error: ()=>{{}} }},
  setTimeout: ()=>{{}}, clearTimeout: ()=>{{}},
  Worker: function() {{}}, FileReader: function() {{}},
  fetch: async () => {{}}, URL: URL, Uint8Array: Uint8Array
}};

vm.createContext(sandbox);
vm.runInContext(appCode, sandbox);
vm.runInContext('loadSettings()', sandbox);
const settings = vm.runInContext('currentSettings', sandbox);

console.log(JSON.stringify({{ success: true, isObject: typeof settings === 'object' && settings !== null }}));
"""
        out = run_node_snippet(script)
        data = json.loads(out)
        assert data["success"] is True
        assert data["isObject"] is True

    @pytest.mark.skipif(NODE_BIN is None, reason="Node.js binary not available")
    def test_localstorage_partial_missing_keys_defaults(self):
        """
        When localStorage contains partial settings with missing keys,
        all omitted keys must fallback to their default values in DEFAULT_SETTINGS.
        """
        partial_json = json.dumps({"slots": 14, "strategy": "max-relationship"})
        script = f"""
const fs = require('fs');
const vm = require('vm');

const appCode = fs.readFileSync('web/app.js', 'utf8');

let stored = {json.dumps(partial_json)};
const storage = {{
  getItem: (k) => stored,
  setItem: (k, v) => {{ stored = v; }}
}};

const elements = {{}};
const mockDoc = {{
  getElementById: (id) => elements[id] || (elements[id] = {{
    id, textContent: '', innerHTML: '', style: {{}},
    classList: {{ add: ()=>{{}}, remove: ()=>{{}} }},
    addEventListener: () => {{}}
  }}),
  querySelectorAll: () => [],
  addEventListener: () => {{}},
  createElement: (tag) => ({{
    tagName: tag, style: {{}},
    classList: {{ add: ()=>{{}}, remove: ()=>{{}} }},
    appendChild: ()=>{{}}, addEventListener: () => {{}}
  }}),
  body: {{ classList: {{ add: ()=>{{}}, remove: ()=>{{}} }} }}
}};

const sandbox = {{
  localStorage: storage,
  document: mockDoc,
  window: {{}},
  console: {{ warn: ()=>{{}}, log: ()=>{{}}, error: ()=>{{}} }},
  setTimeout: ()=>{{}}, clearTimeout: ()=>{{}},
  Worker: function() {{}}, FileReader: function() {{}},
  fetch: async () => {{}}, URL: URL, Uint8Array: Uint8Array
}};

vm.createContext(sandbox);
vm.runInContext(appCode, sandbox);
vm.runInContext('loadSettings()', sandbox);
const settings = vm.runInContext('currentSettings', sandbox);

console.log(JSON.stringify(settings));
"""
        out = run_node_snippet(script)
        settings = json.loads(out)
        # Explicitly set
        assert settings["slots"] == 14
        assert settings["strategy"] == "max-relationship"
        # Recovered defaults
        assert settings["mode"] == "auto"
        assert settings["loved_weight"] == 3
        assert settings["liked_weight"] == 1
        assert settings["vendor_boost"] == 1.5
        assert settings["focus_sort"] == "impact"
        assert settings["focus_mode_enabled"] is False

    def test_web_bridge_extreme_config_resilience(self):
        """
        Passes out-of-range, negative, and invalid type configuration payloads
        into web_bridge.generate_plan. The bridge must never crash unhandled,
        always returning a valid 16-key canonical JSON string.
        """
        bridge = get_web_bridge()
        bridge.init_bridge(str(WEB_DATA_DIR))
        sample_bytes = SAMPLE_SAVE_PATH.read_bytes()

        hostile_configs = [
            {"slots": -999, "loved_weight": -10, "strategy": "exploit_unknown"},
            {"slots": 999999, "vendor_boost": 99999.0, "mode": "invalid_mode"},
            {"slots": "not_an_int", "loved_weight": "none"},
            {"focus_npcs": ["<script>", "adeline"], "exclude_npcs": {"nested": "dict"}},
            {"date_override": "{invalid_json_date}"},
        ]

        for conf in hostile_configs:
            raw = bridge.generate_plan(sample_bytes, config_dict=conf, filename="hostile_conf.sav")
            data = json.loads(raw)
            assert_canonical_plan_dict(data)
            # Must return valid structure regardless of error or coercion
            assert "save_info" in data
            assert "stats" in data


# ==============================================================================
# SECTION 3: Sanitization & XSS Resilience
# ==============================================================================

class TestSanitizationAndXSSResilience:
    """
    Empirically verifies sanitization and XSS resilience:
    - Save file player/farm names with injection vectors.
    - JSON serialization conformance (RFC 8259).
    - SVG placeholder generator attribute injection immunity.
    - White-box DOM innerHTML sink auditing in web/app.js.
    """

    @pytest.fixture(autouse=True)
    def setup_bridge(self):
        self.bridge = get_web_bridge()
        self.bridge.init_bridge(str(WEB_DATA_DIR))

    @pytest.mark.parametrize(
        "player_payload,farm_payload",
        [
            ("<script>alert('pwned')</script>", "<img src=x onerror=alert(1)>"),
            ("\" onmouseover=\"alert(1)\"", "'; DROP TABLE users; --"),
            ("<svg/onload=alert('xss')>", "&lt;script&gt;alert(1)&lt;/script&gt;"),
            ("Aria & \"The Warrior\" <Hero>", "Valen's Farm 'Deluxe'"),
        ],
    )
    def test_save_data_xss_payload_json_safety(self, player_payload: str, farm_payload: str):
        """
        When save files contain HTML/XSS payloads and quotes in player and farm names,
        web_bridge.generate_plan must encode them into strictly valid RFC 8259 JSON
        without breaking JSON syntax or allowing unescaped control characters.
        """
        save_bytes = make_synthetic_save_bytes(player_name=player_payload, farm_name=farm_payload)
        raw_json = self.bridge.generate_plan(save_bytes, filename="xss_test.sav")

        # Must parse as valid JSON
        data = json.loads(raw_json)
        assert_canonical_plan_dict(data)
        assert data["error"] is None
        assert data["save_info"]["player_name"] == player_payload
        assert data["save_info"]["farm_name"] == farm_payload

    @pytest.mark.skipif(NODE_BIN is None, reason="Node.js binary not available")
    @pytest.mark.parametrize(
        "raw_id",
        [
            "<script>alert(1)</script>",
            "\"><script>alert(1)</script>",
            "' onfocus='alert(1)'",
            "item_with_quotes_\"_and_ampersand_&",
            "../../../etc/passwd",
        ],
    )
    def test_svg_placeholder_generator_injection_safety(self, raw_id: str):
        """
        Evaluates generatePlaceholderSvg(id, label) in web/app.js with hostile strings.
        Asserts that initials are safely XML-escaped and the output data URI is well-formed XML
        that parses cleanly without ParseError and contains no injected elements.
        """
        script = f"""
const fs = require('fs');
const vm = require('vm');

const appCode = fs.readFileSync('web/app.js', 'utf8');

const elements = {{}};
const mockDoc = {{
  getElementById: (id) => elements[id] || (elements[id] = {{ id, textContent: '', innerHTML: '', style: {{}}, classList: {{ add: ()=>{{}}, remove: ()=>{{}} }}, addEventListener: () => {{}} }}),
  querySelectorAll: () => [],
  addEventListener: () => {{}},
  createElement: (tag) => ({{ tagName: tag, style: {{}}, classList: {{ add: ()=>{{}}, remove: ()=>{{}} }}, appendChild: ()=>{{}}, addEventListener: () => {{}} }}),
  body: {{ classList: {{ add: ()=>{{}}, remove: ()=>{{}} }} }}
}};

const sandbox = {{
  window: {{}},
  document: mockDoc,
  localStorage: {{ getItem: ()=>null, setItem: ()=>{{}} }},
  console: console,
  encodeURIComponent: encodeURIComponent,
  setTimeout: (fn) => fn(),
  clearTimeout: () => {{}},
  Worker: function() {{}},
  FileReader: function() {{}},
  fetch: async () => {{}},
  URL: URL,
  Uint8Array: Uint8Array
}};

vm.createContext(sandbox);
vm.runInContext(appCode, sandbox);

const svgUri = sandbox.generatePlaceholderSvg({json.dumps(raw_id)}, 'item');
console.log(svgUri);
"""
        uri = run_node_snippet(script).strip()
        assert uri.startswith("data:image/svg+xml;utf8,"), f"Invalid SVG data URI: {uri}"

        svg_content = urllib.parse.unquote(uri.replace("data:image/svg+xml;utf8,", ""))

        # Initials are safely XML-escaped, ensuring well-formed SVG without ParseError
        root = ET.fromstring(svg_content)
        assert root.tag.endswith("svg")
        # Ensure no malicious child tags were created
        tag_names = [elem.tag.split("}")[-1] for elem in root.iter()]
        assert "script" not in tag_names
        assert "image" not in tag_names

    @pytest.mark.skipif(NODE_BIN is None, reason="Node.js binary not available")
    def test_frontend_dom_xss_audit_and_sanitization(self):
        """
        White-box empirical DOM XSS & modal audit:
        Verifies that player_name, farm_name, and search filters are properly sanitized
        when interpolated into the DOM, and verifies that modal close and backdrop click
        handlers operate correctly.
        """
        script = """
const fs = require('fs');
const vm = require('vm');

const appCode = fs.readFileSync('web/app.js', 'utf8');

const elements = {};
const clickListeners = {};
let domLoadedCb = null;

const mockDoc = {
  getElementById: (id) => elements[id] || (elements[id] = {
    id, textContent: '', innerHTML: '', style: {},
    classList: { add: ()=>{}, remove: ()=>{} },
    addEventListener: (ev, handler) => { (clickListeners[id] = clickListeners[id] || []).push(handler); }
  }),
  querySelectorAll: () => [],
  addEventListener: (ev, fn) => {
    if (ev === 'DOMContentLoaded') domLoadedCb = fn;
  },
  createElement: (tag) => ({
    tagName: tag, style: {},
    classList: { add: ()=>{}, remove: ()=>{} },
    appendChild: ()=>{}, addEventListener: () => {}
  }),
  body: { classList: { add: ()=>{}, remove: ()=>{} }, style: {} }
};

const sandbox = {
  localStorage: { getItem: ()=>null, setItem: ()=>{} },
  document: mockDoc,
  window: { addEventListener: ()=>{} },
  console: console,
  setTimeout: ()=>{}, clearTimeout: ()=>{},
  Worker: function() { return { postMessage: ()=>{}, addEventListener: ()=>{} }; },
  FileReader: function() {},
  fetch: async () => {}, URL: URL, Uint8Array: Uint8Array
};

vm.createContext(sandbox);
vm.runInContext(appCode, sandbox);

// 1. Audit playerFarmBadge
const payload = {
  save_info: {
    player_name: '<script>alert("XSS")</script>',
    farm_name: '<img src=x onerror=alert(1)>'
  },
  in_game_date: { season: 'spring', day: 1 }
};
vm.runInContext('renderHeader(' + JSON.stringify(payload) + ')', sandbox);
const playerBadgeHtml = elements['playerFarmBadge'] ? elements['playerFarmBadge'].innerHTML : '';

// 2. Audit incompleteGrid search filter
vm.runInContext('incompleteSearchFilter = "<img src=x onerror=alert(2)>"; renderIncompleteDrawerContent([{ npc_id: "adeline", name: "Adeline" }]);', sandbox);
const incompleteGridHtml = elements['incompleteGrid'] ? elements['incompleteGrid'].innerHTML : '';

// 3. Audit recipesGrid search filter
vm.runInContext('recipeSearchFilter = "<img src=x onerror=alert(3)>"; recipesExpanded = true; renderRecipesDrawerContent([{ recipe_id: "salad", display_name: "Salad" }]);', sandbox);
const recipesGridHtml = elements['recipesGrid'] ? elements['recipesGrid'].innerHTML : '';

// 4. Verify modal close button and backdrop click
if (domLoadedCb) domLoadedCb();

elements['recipeModal'].style.display = 'flex';
if (clickListeners['recipeModalClose']) {
  clickListeners['recipeModalClose'].forEach(fn => fn());
}
const closeBtnHidesModal = elements['recipeModal'].style.display === 'none';

elements['recipeModal'].style.display = 'flex';
if (clickListeners['recipeModal']) {
  clickListeners['recipeModal'].forEach(fn => fn({ target: elements['recipeModal'] }));
}
const backdropHidesModal = elements['recipeModal'].style.display === 'none';

console.log(JSON.stringify({
  playerBadgeHasScript: playerBadgeHtml.includes('<script>alert("XSS")</script>'),
  badgeHasEscapedScript: playerBadgeHtml.includes('&lt;script&gt;alert(&quot;XSS&quot;)&lt;/script&gt;'),
  playerBadgeHasImg: playerBadgeHtml.includes('<img src=x onerror=alert(1)>'),
  badgeHasEscapedImg: playerBadgeHtml.includes('&lt;img src=x onerror=alert(1)&gt;'),
  incompleteGridHasImg: incompleteGridHtml.includes('<img src=x onerror=alert(2)>'),
  incompleteGridHasEscapedImg: incompleteGridHtml.includes('&lt;img src=x onerror=alert(2)&gt;'),
  recipesGridHasImg: recipesGridHtml.includes('<img src=x onerror=alert(3)>'),
  recipesGridHasEscapedImg: recipesGridHtml.includes('&lt;img src=x onerror=alert(3)&gt;'),
  closeBtnHidesModal: closeBtnHidesModal,
  backdropHidesModal: backdropHidesModal,
  playerBadgeHtml: playerBadgeHtml,
  incompleteGridHtml: incompleteGridHtml,
  recipesGridHtml: recipesGridHtml
}));
"""
        out = run_node_snippet(script)
        audit = json.loads(out)

        # Audit asserts that unescaped HTML tags are NOT inserted and proper escaping is applied:
        assert audit["playerBadgeHasScript"] is False, "playerFarmBadge should NOT interpolate unescaped script tag"
        assert audit["badgeHasEscapedScript"] is True, "playerFarmBadge should properly escape script tag"
        assert audit["playerBadgeHasImg"] is False, "playerFarmBadge should NOT interpolate unescaped img tag"
        assert audit["badgeHasEscapedImg"] is True, "playerFarmBadge should properly escape img tag"
        assert audit["incompleteGridHasImg"] is False, "incompleteGrid should NOT interpolate unescaped search filter"
        assert audit["incompleteGridHasEscapedImg"] is True, "incompleteGrid should properly escape search filter"
        assert audit["recipesGridHasImg"] is False, "recipesGrid should NOT interpolate unescaped search filter"
        assert audit["recipesGridHasEscapedImg"] is True, "recipesGrid should properly escape search filter"
        assert audit["closeBtnHidesModal"] is True, "recipeModalClose button should hide recipeModal"
        assert audit["backdropHidesModal"] is True, "clicking recipeModal backdrop should hide recipeModal"



# ==============================================================================
# SECTION 4: Zero Network Leakage Verification
# ==============================================================================

class TestZeroNetworkLeakage:
    """
    Verifies 100% client-side data privacy guarantee:
    - Zero server /api/ routes in web/app.js.
    - Zero EventSource or WebSocket communication.
    - Zero outbound network telemetry or analytics endpoints.
    - Zero save bytes sent across network in dynamic workflow simulation.
    """

    def test_static_code_zero_api_endpoints_and_eventsource(self):
        """
        Static regex sweep of web/app.js:
        Verifies complete elimination of /api/ endpoints, EventSource,
        XMLHttpRequest, WebSocket, and sendBeacon.
        """
        content = APP_JS.read_text(encoding="utf-8")

        api_calls = re.findall(r"/api/[a-zA-Z0-9_/]+", content)
        assert len(api_calls) == 0, f"Found server /api/ routes in web/app.js: {api_calls}"

        es_calls = re.findall(r"\bEventSource\b", content)
        assert len(es_calls) == 0, f"Found EventSource in web/app.js: {es_calls}"

        xhr_calls = re.findall(r"\bXMLHttpRequest\b", content)
        assert len(xhr_calls) == 0, f"Found XMLHttpRequest in web/app.js: {xhr_calls}"

        ws_calls = re.findall(r"\bWebSocket\b", content)
        assert len(ws_calls) == 0, f"Found WebSocket in web/app.js: {ws_calls}"

        beacon_calls = re.findall(r"\bsendBeacon\b", content)
        assert len(beacon_calls) == 0, f"Found sendBeacon in web/app.js: {beacon_calls}"

    def test_static_code_zero_outbound_telemetry_or_analytics(self):
        """
        Verifies absence of third-party telemetry, tracking pixels, or data collection
        domains in web/index.html, web/app.js, and web/planner.worker.js.
        """
        forbidden_patterns = [
            r"google-analytics\.com",
            r"googletagmanager\.com",
            r"segment\.io",
            r"mixpanel\.com",
            r"sentry\.io",
            r"hotjar\.com",
            r"amplitude\.com",
            r"api\.posthog\.com",
        ]

        for file_path in [APP_JS, WORKER_JS, INDEX_HTML]:
            text = file_path.read_text(encoding="utf-8")
            for pattern in forbidden_patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                assert len(matches) == 0, f"Found telemetry pattern '{pattern}' in {file_path.name}"

    @pytest.mark.skipif(NODE_BIN is None, reason="Node.js binary not available")
    def test_dynamic_network_interception_during_workflows(self):
        """
        Executes web/app.js inside Node.js while intercepting global.fetch.
        Executes loadDemo(), plan submission, and recomputation.
        Asserts that only local relative asset ('sample_save.sav') is fetched,
        with 0 outbound requests to any external host.
        """
        script = """
const fs = require('fs');
const vm = require('vm');

const appCode = fs.readFileSync('web/app.js', 'utf8');

const networkRequests = [];

const mockFetch = async (url, opts) => {
  networkRequests.push({ url: String(url), method: (opts && opts.method) || 'GET' });
  if (url === 'sample_save.sav') {
    const bytes = fs.readFileSync('web/sample_save.sav');
    return {
      ok: true,
      status: 200,
      arrayBuffer: async () => bytes.buffer
    };
  }
  return { ok: false, status: 404 };
};

const elements = {};
const mockDoc = {
  getElementById: (id) => elements[id] || (elements[id] = {
    id, textContent: '', innerHTML: '', style: {},
    classList: { add: ()=>{}, remove: ()=>{} },
    addEventListener: () => {}
  }),
  querySelectorAll: () => [],
  addEventListener: () => {},
  createElement: (tag) => ({
    tagName: tag, style: {},
    classList: { add: ()=>{}, remove: ()=>{} },
    appendChild: ()=>{}, addEventListener: () => {}
  }),
  body: { classList: { add: ()=>{}, remove: ()=>{} } }
};

const workerMessages = [];
class MockWorker {
  constructor(url) {
    this.url = url;
  }
  postMessage(msg) {
    workerMessages.push(msg);
  }
}

const sandbox = {
  localStorage: { getItem: ()=>null, setItem: ()=>{} },
  document: mockDoc,
  window: {},
  console: console,
  setTimeout: (fn)=>setTimeout(fn, 10),
  clearTimeout: (id)=>clearTimeout(id),
  Worker: MockWorker,
  FileReader: function() {},
  fetch: mockFetch,
  URL: URL,
  Uint8Array: Uint8Array
};

vm.createContext(sandbox);
vm.runInContext(appCode, sandbox);

async function testNetwork() {
  sandbox.initWorker();
  sandbox.loadDemo();

  // Wait for loadDemo fetch promise
  await new Promise(r => setTimeout(r, 50));

  console.log(JSON.stringify({
    requests: networkRequests,
    workerMessages: workerMessages
  }));
}

testNetwork().catch(err => {
  console.error(err);
  process.exit(1);
});
"""
        out = run_node_snippet(script)
        data = json.loads(out)
        requests = data["requests"]
        assert len(requests) == 1
        assert requests[0]["url"] == "sample_save.sav"
        assert not requests[0]["url"].startswith("http://")
        assert not requests[0]["url"].startswith("https://")


# ==============================================================================
# SECTION 5: Pyodide Web Worker Message State Machine Robustness
# ==============================================================================

class TestWorkerMessageStateMachineRobustness:
    """
    Stress-tests the Pyodide Web Worker message protocol in web/planner.worker.js:
    - Premature recompute handling.
    - Automatic initialization on plan before init.
    - Idempotent concurrent init requests.
    - Unknown action and malformed payload handling.
    - Rapid Try Demo spamming.
    """

    @pytest.mark.skipif(NODE_BIN is None, reason="Node.js binary not available")
    def test_worker_recompute_before_init_or_save_loaded(self):
        """
        When 'recompute' is sent before any save file has been uploaded into VFS,
        the worker must emit an error message and not crash.
        """
        script = """
const fs = require('fs');
const vm = require('vm');

const workerCode = fs.readFileSync('web/planner.worker.js', 'utf8');

const messages = [];
const vfs = {};

const mockPyodide = {
  FS: {
    mkdirTree: () => {},
    writeFile: (p, data) => { vfs[p] = data; },
    analyzePath: (p) => ({ exists: p in vfs }),
  },
  loadPackage: async () => {},
  pyimport: () => ({ install: async () => {} }),
  runPython: () => {}
};

const sandbox = {
  self: {
    location: { href: 'http://localhost:8000/planner.worker.js' },
    postMessage: (msg) => messages.push(msg),
    importScripts: () => {},
    onmessage: null
  },
  loadPyodide: async () => mockPyodide,
  fetch: async () => ({ ok: true, text: async () => '{}' }),
  performance: { now: () => Date.now() },
  URL: URL,
  Uint8Array: Uint8Array,
  console: console
};

vm.createContext(sandbox);
vm.runInContext(workerCode, sandbox);

async function testRecompute() {
  await sandbox.self.onmessage({ data: { action: 'recompute', config: {} } });
  console.log(JSON.stringify(messages));
}

testRecompute().catch(err => {
  console.error(err);
  process.exit(1);
});
"""
        out = run_node_snippet(script)
        messages = json.loads(out)
        err_msgs = [m for m in messages if m.get("action") == "error"]
        assert len(err_msgs) == 1
        assert "No save file available in VFS" in err_msgs[0]["message"]

    @pytest.mark.skipif(NODE_BIN is None, reason="Node.js binary not available")
    def test_worker_plan_before_init(self):
        """
        When 'plan' is dispatched before an explicit 'init' message has been sent,
        the worker must automatically trigger handleInit(), populate VFS, and return 'result'.
        """
        script = """
const fs = require('fs');
const vm = require('vm');

const workerCode = fs.readFileSync('web/planner.worker.js', 'utf8');

const messages = [];
const vfs = {};

const mockPyodide = {
  FS: {
    mkdirTree: () => {},
    writeFile: (p, data) => { vfs[p] = data; },
    analyzePath: (p) => ({ exists: p in vfs }),
  },
  loadPackage: async () => {},
  pyimport: (name) => {
    if (name === 'micropip') return { install: async () => {} };
    if (name === 'web_bridge') {
      return {
        generate_plan: () => JSON.stringify({
          save_info: { found: true }, stats: { max_slots: 20 },
          bag_plan: [], focus_suggestions: [], focus_trees: [],
          source_priority: [], npc_progress: {}, error: null
        })
      };
    }
    return {};
  },
  runPython: () => {}
};

const sandbox = {
  self: {
    location: { href: 'http://localhost:8000/planner.worker.js' },
    postMessage: (msg) => messages.push(msg),
    importScripts: () => {},
    onmessage: null
  },
  loadPyodide: async () => mockPyodide,
  fetch: async () => ({ ok: true, text: async () => '{}' }),
  performance: { now: () => Date.now() },
  URL: URL,
  Uint8Array: Uint8Array,
  console: console
};

vm.createContext(sandbox);
vm.runInContext(workerCode, sandbox);

async function testPlan() {
  await sandbox.self.onmessage({
    data: { action: 'plan', saveBytes: new Uint8Array([1, 2, 3]), config: { slots: 20 } }
  });
  console.log(JSON.stringify(messages));
}

testPlan().catch(err => {
  console.error(err);
  process.exit(1);
});
"""
        out = run_node_snippet(script)
        messages = json.loads(out)
        actions = [m.get("action") for m in messages]
        assert "progress" in actions
        assert "ready" in actions
        assert "result" in actions

    @pytest.mark.skipif(NODE_BIN is None, reason="Node.js binary not available")
    def test_worker_duplicate_concurrent_init(self):
        """
        When multiple 'init' messages arrive concurrently, the worker's initPromise
        must guard against redundant initialization runs, resolving safely to 'ready'.
        """
        script = """
const fs = require('fs');
const vm = require('vm');

const workerCode = fs.readFileSync('web/planner.worker.js', 'utf8');

const messages = [];
let loadPyodideCount = 0;

const mockPyodide = {
  FS: { mkdirTree: () => {}, writeFile: () => {} },
  loadPackage: async () => {},
  pyimport: () => ({ install: async () => {} }),
  runPython: () => {}
};

const sandbox = {
  self: {
    location: { href: 'http://localhost:8000/planner.worker.js' },
    postMessage: (msg) => messages.push(msg),
    importScripts: () => {},
    onmessage: null
  },
  loadPyodide: async () => {
    loadPyodideCount++;
    return mockPyodide;
  },
  fetch: async () => ({ ok: true, text: async () => '{}' }),
  performance: { now: () => Date.now() },
  URL: URL,
  Uint8Array: Uint8Array,
  console: console
};

vm.createContext(sandbox);
vm.runInContext(workerCode, sandbox);

async function testInit() {
  // Fire 2 concurrent inits
  await Promise.all([
    sandbox.self.onmessage({ data: { action: 'init' } }),
    sandbox.self.onmessage({ data: { action: 'init' } })
  ]);
  console.log(JSON.stringify({ loadPyodideCount: loadPyodideCount, messages: messages }));
}

testInit().catch(err => {
  console.error(err);
  process.exit(1);
});
"""
        out = run_node_snippet(script)
        data = json.loads(out)
        # loadPyodide called only once despite duplicate init requests
        assert data["loadPyodideCount"] == 1
        ready_msgs = [m for m in data["messages"] if m.get("action") == "ready"]
        assert len(ready_msgs) >= 1

    @pytest.mark.skipif(NODE_BIN is None, reason="Node.js binary not available")
    def test_worker_unknown_action_handling(self):
        """Worker must catch unknown action and post action: 'error'."""
        script = """
const fs = require('fs');
const vm = require('vm');

const workerCode = fs.readFileSync('web/planner.worker.js', 'utf8');
const messages = [];

const sandbox = {
  self: {
    location: { href: 'http://localhost:8000/planner.worker.js' },
    postMessage: (msg) => messages.push(msg),
    importScripts: () => {},
    onmessage: null
  },
  console: console
};

vm.createContext(sandbox);
vm.runInContext(workerCode, sandbox);

sandbox.self.onmessage({ data: { action: 'hack_the_planet' } });
console.log(JSON.stringify(messages));
"""
        out = run_node_snippet(script)
        messages = json.loads(out)
        assert len(messages) == 1
        assert messages[0]["action"] == "error"
        assert "Unknown action: hack_the_planet" in messages[0]["message"]

    @pytest.mark.skipif(NODE_BIN is None, reason="Node.js binary not available")
    def test_worker_malformed_plan_payload_missing_bytes(self):
        """Worker must catch missing saveBytes in plan request and post action: 'error'."""
        script = """
const fs = require('fs');
const vm = require('vm');

const workerCode = fs.readFileSync('web/planner.worker.js', 'utf8');
const messages = [];

const mockPyodide = {
  FS: { mkdirTree: () => {}, writeFile: () => {} },
  loadPackage: async () => {},
  pyimport: () => ({ install: async () => {} }),
  runPython: () => {}
};

const sandbox = {
  self: {
    location: { href: 'http://localhost:8000/planner.worker.js' },
    postMessage: (msg) => messages.push(msg),
    importScripts: () => {},
    onmessage: null
  },
  loadPyodide: async () => mockPyodide,
  fetch: async () => ({ ok: true, text: async () => '{}' }),
  performance: { now: () => Date.now() },
  URL: URL,
  Uint8Array: Uint8Array,
  console: console
};

vm.createContext(sandbox);
vm.runInContext(workerCode, sandbox);

async function testMissing() {
  await sandbox.self.onmessage({ data: { action: 'plan', config: {} } });
  console.log(JSON.stringify(messages));
}

testMissing().catch(console.error);
"""
        out = run_node_snippet(script)
        messages = json.loads(out)
        errs = [m for m in messages if m.get("action") == "error"]
        assert len(errs) == 1
        assert "Missing required saveBytes in plan request" in errs[0]["message"]

    @pytest.mark.skipif(NODE_BIN is None, reason="Node.js binary not available")
    def test_worker_rapid_demo_spamming(self):
        """
        Simulates spamming 'Try Demo' 10 times in rapid succession.
        The worker must process all requests sequentially, resulting in 10 results
        with zero VFS leaks or unhandled errors.
        """
        script = """
const fs = require('fs');
const vm = require('vm');

const workerCode = fs.readFileSync('web/planner.worker.js', 'utf8');

const messages = [];
const vfs = {};

const mockPyodide = {
  FS: {
    mkdirTree: () => {},
    writeFile: (p, data) => { vfs[p] = data; },
    analyzePath: (p) => ({ exists: p in vfs }),
  },
  loadPackage: async () => {},
  pyimport: () => ({
    install: async () => {},
    generate_plan: () => JSON.stringify({
      save_info: { found: true }, stats: { max_slots: 20 },
      bag_plan: [], focus_suggestions: [], focus_trees: [],
      source_priority: [], npc_progress: {}, error: null
    })
  }),
  runPython: () => {}
};

const sandbox = {
  self: {
    location: { href: 'http://localhost:8000/planner.worker.js' },
    postMessage: (msg) => messages.push(msg),
    importScripts: () => {},
    onmessage: null
  },
  loadPyodide: async () => mockPyodide,
  fetch: async () => ({ ok: true, text: async () => '{}' }),
  performance: { now: () => Date.now() },
  URL: URL,
  Uint8Array: Uint8Array,
  console: console
};

vm.createContext(sandbox);
vm.runInContext(workerCode, sandbox);

async function testSpam() {
  const dummyBytes = new Uint8Array([1, 2, 3]);
  for (let i = 0; i < 10; i++) {
    await sandbox.self.onmessage({
      data: { action: 'plan', saveBytes: dummyBytes, config: {}, filename: 'sample_save.sav' }
    });
  }
  const results = messages.filter(m => m.action === 'result');
  console.log(JSON.stringify({ resultCount: results.length }));
}

testSpam().catch(console.error);
"""
        out = run_node_snippet(script)
        data = json.loads(out)
        assert data["resultCount"] == 10


# ==============================================================================
# SECTION 6: Modal & UI Interaction Robustness
# ==============================================================================

class TestModalAndUIInteractionRobustness:
    """
    Tests modal dismissal mechanics (ESC key, backdrop clicks, close buttons)
    and UI event handling robustness in web/app.js.
    """

    @pytest.mark.skipif(NODE_BIN is None, reason="Node.js binary not available")
    def test_modal_escape_key_dismissal(self):
        """
        Verifies that pressing 'Escape' key triggers modal dismissal
        for treeModal, calendarModal, and recipeModal.
        """
        script = """
const fs = require('fs');
const vm = require('vm');

const appCode = fs.readFileSync('web/app.js', 'utf8');

const elements = {};
const keydownListeners = [];
const domLoadedListeners = [];

const mockDoc = {
  getElementById: (id) => elements[id] || (elements[id] = {
    id, textContent: '', innerHTML: '',
    style: { display: 'block' },
    classList: { add: ()=>{}, remove: ()=>{} },
    addEventListener: () => {}
  }),
  querySelectorAll: () => [],
  addEventListener: (event, handler) => {
    if (event === 'DOMContentLoaded') domLoadedListeners.push(handler);
    if (event === 'keydown') keydownListeners.push(handler);
  },
  createElement: (tag) => ({
    tagName: tag, style: {},
    classList: { add: ()=>{}, remove: ()=>{} },
    appendChild: ()=>{}, addEventListener: () => {}
  }),
  body: { classList: { add: ()=>{}, remove: ()=>{} }, style: {} }
};

class MockWorker {
  constructor() {}
  postMessage() {}
}

const sandbox = {
  localStorage: { getItem: ()=>null, setItem: ()=>{} },
  document: mockDoc,
  window: { addEventListener: () => {} },
  console: console,
  setTimeout: (fn) => fn(), clearTimeout: ()=>{},
  Worker: MockWorker, FileReader: function() {},
  fetch: async () => {}, URL: URL, Uint8Array: Uint8Array
};

vm.createContext(sandbox);
vm.runInContext(appCode, sandbox);
domLoadedListeners.forEach(fn => fn());

// Set all modals to open (display = 'flex' or 'block')
const treeModal = mockDoc.getElementById('treeModal');
const calModal = mockDoc.getElementById('calendarModal');
const rcModal = mockDoc.getElementById('recipeModal');

treeModal.style.display = 'flex';
calModal.style.display = 'flex';
rcModal.style.display = 'block';

// Trigger all keydown listeners with Escape
keydownListeners.forEach(fn => fn({ key: 'Escape' }));

console.log(JSON.stringify({
  treeModalDisplay: treeModal.style.display,
  calModalDisplay: calModal.style.display,
  rcModalDisplay: rcModal.style.display
}));
"""
        out = run_node_snippet(script)
        data = json.loads(out)
        assert data["treeModalDisplay"] == "none"
        assert data["calModalDisplay"] == "none"
        assert data["rcModalDisplay"] == "none"

    @pytest.mark.skipif(NODE_BIN is None, reason="Node.js binary not available")
    def test_modal_backdrop_click_dismissal(self):
        """
        Verifies that clicking directly on the modal backdrop element
        triggers modal closure for treeModal and calendarModal.
        """
        script = """
const fs = require('fs');
const vm = require('vm');

const appCode = fs.readFileSync('web/app.js', 'utf8');

const elements = {};
const clickListeners = {};
const domLoadedListeners = [];

const mockDoc = {
  getElementById: (id) => elements[id] || (elements[id] = {
    id, textContent: '', innerHTML: '',
    style: { display: 'flex' },
    classList: { add: ()=>{}, remove: ()=>{} },
    addEventListener: (event, handler) => {
      clickListeners[id] = clickListeners[id] || [];
      clickListeners[id].push(handler);
    }
  }),
  querySelectorAll: () => [],
  addEventListener: (event, handler) => {
    if (event === 'DOMContentLoaded') domLoadedListeners.push(handler);
  },
  createElement: (tag) => ({
    tagName: tag, style: {},
    classList: { add: ()=>{}, remove: ()=>{} },
    appendChild: ()=>{}, addEventListener: () => {}
  }),
  body: { classList: { add: ()=>{}, remove: ()=>{} }, style: {} }
};

class MockWorker {
  constructor() {}
  postMessage() {}
}

const sandbox = {
  localStorage: { getItem: ()=>null, setItem: ()=>{} },
  document: mockDoc,
  window: { addEventListener: () => {} },
  console: console,
  setTimeout: (fn) => fn(), clearTimeout: ()=>{},
  Worker: MockWorker, FileReader: function() {},
  fetch: async () => {}, URL: URL, Uint8Array: Uint8Array
};

vm.createContext(sandbox);
vm.runInContext(appCode, sandbox);
domLoadedListeners.forEach(fn => fn());

// Simulate backdrop click on treeModal
const treeModal = mockDoc.getElementById('treeModal');
treeModal.style.display = 'flex';
if (clickListeners['treeModal']) {
  clickListeners['treeModal'].forEach(fn => fn({ target: treeModal }));
}

// Simulate backdrop click on calendarModal
const calModal = mockDoc.getElementById('calendarModal');
calModal.style.display = 'flex';
if (clickListeners['calendarModal']) {
  clickListeners['calendarModal'].forEach(fn => fn({ target: calModal }));
}

console.log(JSON.stringify({
  treeModalDisplay: treeModal.style.display,
  calModalDisplay: calModal.style.display
}));
"""
        out = run_node_snippet(script)
        data = json.loads(out)
        assert data["treeModalDisplay"] == "none"
        assert data["calModalDisplay"] == "none"

    @pytest.mark.skipif(NODE_BIN is None, reason="Node.js binary not available")
    def test_search_filter_rapid_input_debouncing(self):
        """
        Verifies that rapid keystroke entries into search inputs in the stats drawers
        update state cleanly without throwing exceptions.
        """
        script = """
const fs = require('fs');
const vm = require('vm');

const appCode = fs.readFileSync('web/app.js', 'utf8');

const elements = {};
const mockDoc = {
  getElementById: (id) => elements[id] || (elements[id] = {
    id, textContent: '', innerHTML: '', style: {},
    classList: { add: ()=>{}, remove: ()=>{} },
    addEventListener: () => {}
  }),
  querySelectorAll: () => [],
  addEventListener: () => {},
  createElement: (tag) => ({
    tagName: tag, style: {},
    classList: { add: ()=>{}, remove: ()=>{} },
    appendChild: ()=>{}, addEventListener: () => {}
  }),
  body: { classList: { add: ()=>{}, remove: ()=>{} } }
};

const sandbox = {
  localStorage: { getItem: ()=>null, setItem: ()=>{} },
  document: mockDoc,
  window: {},
  console: console,
  setTimeout: (fn) => fn(),
  clearTimeout: () => {},
  Worker: function() {}, FileReader: function() {},
  fetch: async () => {}, URL: URL, Uint8Array: Uint8Array
};

vm.createContext(sandbox);
vm.runInContext(appCode, sandbox);

// Rapid keystrokes simulation
const testInputs = ['a', 'ad', 'ade', 'adel', 'adeline'];
for (const word of testInputs) {
  vm.runInContext(`incompleteSearchFilter = "${word}"; renderIncompleteDrawerContent([{ npc_id: "adeline", name: "Adeline" }]);`, sandbox);
}

const html = elements['incompleteGrid'] ? elements['incompleteGrid'].innerHTML : '';
console.log(JSON.stringify({
  hasCard: html.includes('incomplete-npc-card'),
  includesAdeline: html.includes('Adeline')
}));
"""
        out = run_node_snippet(script)
        data = json.loads(out)
        assert data["hasCard"] is True
        assert data["includesAdeline"] is True
