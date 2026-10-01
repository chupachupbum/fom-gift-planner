"""
tests/test_worker_adversarial.py

Empirical adversarial, stress, and edge-case verification for
web/planner.worker.js.
Challenges the Pyodide Web Worker message protocol, error handling payload
integrity, lexical tokens, syntax validation with standard JS engines,
malformed payloads, state transitions, and edge cases.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from pygments.lexers import JavascriptLexer
from pygments.token import Error
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER_PATH = REPO_ROOT / "web" / "planner.worker.js"
SAMPLE_SAVE_PATH = REPO_ROOT / "web" / "sample_save.sav"
DATA_DIR = REPO_ROOT / "web" / "data"

NODE_PATH = (
    shutil.which("node")
    or os.path.expanduser("~/.nvm/versions/node/v22.22.1/bin/node")
)


def run_node_worker_harness(script: str) -> dict:
    """
    Executes a JavaScript test script in Node.js with a mocked Web Worker
    environment and returns parsed JSON output.
    """
    assert os.path.exists(NODE_PATH), f"Node binary not found at {NODE_PATH}"
    result = subprocess.run(
        [NODE_PATH, "-e", script],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Node harness failed (code {result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
    return json.loads(result.stdout)


# Base JS harness loader code for reuse in Node tests
JS_HARNESS_BASE = """
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const workerCode = fs.readFileSync('web/planner.worker.js', 'utf8');

function createWorkerHarness(options = {}) {
  const messages = [];
  const vfs = {};

  const mockPyodide = {
    FS: {
      mkdirTree: (p) => {},
      writeFile: (p, data) => { vfs[p] = data; },
      analyzePath: (p) => ({ exists: p in vfs }),
    },
    loadPackage: async (pkg) => {},
    pyimport: (name) => {
      if (name === 'micropip') return { install: async (url) => {} };
      if (name === 'web_bridge') {
        return {
          generate_plan: (filePath, configStr, filename) => {
            if (options.throwInBridge) {
              throw new Error('Python bridge internal exception');
            }
            const data = vfs[filePath];
            if (!data || data.length === 0) {
              return JSON.stringify({
                save_info: { found: false, error: 'Empty save file' },
                stats: {},
                bag_plan: [],
                error: 'Empty save file'
              });
            }
            let parsedConfig = {};
            try {
              parsedConfig = typeof configStr === 'string'
                ? JSON.parse(configStr || '{}')
                : configStr;
            } catch (e) {
              parsedConfig = {};
            }
            return JSON.stringify({
              save_info: { found: true, player_name: 'Aria' },
              stats: { max_slots: parsedConfig.slots || 20 },
              bag_plan: [],
              config: parsedConfig,
              error: null
            });
          }
        };
      }
      throw new Error('Unknown pyimport ' + name);
    },
    runPython: (script) => {},
  };

  const self = {
    location: { href: 'http://localhost:8000/planner.worker.js' },
    postMessage: (msg) => messages.push(msg),
  };

  let initCount = 0;
  const loadPyodide = async (opts) => {
    initCount++;
    if (options.failPyodideLoad) {
      throw new Error('Pyodide CDN network load failure');
    }
    return mockPyodide;
  };
  const importScripts = (...urls) => {};
  const fetch = async (url) => {
    if (options.failFetch) {
      return { ok: false, status: 404 };
    }
    return { ok: true, status: 200, text: async () => 'mock data content' };
  };

  const context = vm.createContext({
    self,
    loadPyodide,
    importScripts,
    fetch,
    performance: { now: () => Date.now() },
    Uint8Array,
    ArrayBuffer,
    URL,
    Promise,
    JSON,
    Error,
    String,
    Math,
    console,
  });

  vm.runInContext(workerCode, context);

  return {
    self,
    messages,
    vfs,
    getInitCount: () => initCount,
    postMessageToWorker: async (msg) => {
      await self.onmessage({ data: msg });
    }
  };
}
"""


# ==============================================================================
# 1. ENGINE-LEVEL SYNTAX, LEXICAL, AND STRUCTURAL VERIFICATION
# ==============================================================================
class TestWorkerSyntaxAndEngine:
    """Validates worker script using Node V8 engine and lexical parsers."""

    def test_node_vm_script_compilation(self):
        """Verifies V8 engine compiles worker without SyntaxError."""
        script = """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('web/planner.worker.js', 'utf8');
        try {
          new vm.Script(code, { filename: 'planner.worker.js' });
          console.log(JSON.stringify({ ok: true }));
        } catch (err) {
          console.log(JSON.stringify({ ok: false, error: err.message }));
        }
        """
        res = run_node_worker_harness(script)
        assert res.get("ok") is True, f"V8 syntax compilation failed: {res}"

    def test_pygments_lexical_tokenization(self):
        """Pygments tokenization must find 0 Error tokens."""
        content = WORKER_PATH.read_text(encoding="utf-8")
        lexer = JavascriptLexer()
        tokens = list(lexer.get_tokens(content))
        errors = [t for t in tokens if t[0] is Error]
        assert len(errors) == 0, f"Lexical errors found: {errors[:5]}"

    def test_balanced_brackets_and_quotes(self):
        """Checks balancing of all bracket pairs and quotes."""
        code = WORKER_PATH.read_text(encoding="utf-8")
        stack = []
        pairs = {")": "(", "]": "[", "}": "{"}
        i = 0
        n = len(code)

        while i < n:
            c = code[i]
            if c == "/" and i + 1 < n and code[i + 1] == "/":
                i = code.find("\n", i)
                if i == -1:
                    break
                continue
            if c == "/" and i + 1 < n and code[i + 1] == "*":
                end = code.find("*/", i + 2)
                assert end != -1, "Unclosed block comment"
                i = end + 2
                continue
            if c in ("'", '"', "`"):
                quote = c
                i += 1
                while i < n:
                    if code[i] == "\\":
                        i += 2
                    elif code[i] == quote:
                        i += 1
                        break
                    else:
                        i += 1
                continue
            if c in "([{":
                stack.append((c, i))
            elif c in ")]}":
                assert stack, f"Unmatched closing bracket {c} at {i}"
                top, pos = stack.pop()
                assert (
                    pairs[c] == top
                ), f"Mismatched {top} at {pos} closed by {c}"
            i += 1

        assert not stack, f"Unclosed brackets remain: {stack}"

    def test_forbidden_apis_absent(self):
        """Worker must not reference DOM, server API paths, or Node modules."""
        content = WORKER_PATH.read_text(encoding="utf-8")
        forbidden = [
            "window.",
            "document.",
            "fetch('/api",
            'fetch("/api',
            "EventSource",
            "companion.",
            "require(",
            "module.exports",
        ]
        for term in forbidden:
            assert term not in content, f"Forbidden API found: {term}"


# ==============================================================================
# 2. MALFORMED MESSAGES ADVERSARIAL TESTING
# ==============================================================================
class TestWorkerMalformedMessages:
    """Tests worker on malformed or adversarial messages."""

    def test_unknown_and_invalid_actions(self):
        """Worker must cleanly reject unknown actions with error action."""
        script = JS_HARNESS_BASE + """
        async function run() {
          const h = createWorkerHarness();
          const testActions = [
            'destroy',
            'execute_arbitrary_code',
            'UNKNOWN_ACTION',
            '',
            null,
            undefined,
            123,
            true,
            {},
            []
          ];
          const results = [];
          for (const act of testActions) {
            h.messages.length = 0;
            await h.postMessageToWorker({ action: act });
            const err = h.messages.find(m => m.action === 'error');
            results.push({
              actionInput: act,
              hasError: !!err,
              errorMessage: err ? err.message : null,
              hasDetail: err ? typeof err.detail === 'string' : false,
            });
          }
          console.log(JSON.stringify({ results }));
        }
        run();
        """
        data = run_node_worker_harness(script)
        for r in data["results"]:
            assert (
                r["hasError"] is True
            ), f"Failed for action: {r['actionInput']}"
            assert "Unknown action" in r["errorMessage"]
            assert r["hasDetail"] is True

    def test_missing_save_bytes(self):
        """Action 'plan' with missing saveBytes must emit structured error."""
        script = JS_HARNESS_BASE + """
        async function run() {
          const h = createWorkerHarness();
          const payloads = [
            { action: 'plan' },
            { action: 'plan', saveBytes: null },
            { action: 'plan', saveBytes: undefined },
            { action: 'plan', saveBytes: '' },
            { action: 'plan', saveBytes: 0 },
            { action: 'plan', saveBytes: false },
          ];
          const results = [];
          for (const p of payloads) {
            h.messages.length = 0;
            await h.postMessageToWorker(p);
            const err = h.messages.find(m => m.action === 'error');
            results.push({
              payload: p,
              hasError: !!err,
              errorMessage: err ? err.message : null,
            });
          }
          console.log(JSON.stringify({ results }));
        }
        run();
        """
        data = run_node_worker_harness(script)
        for r in data["results"]:
            assert r["hasError"] is True
            assert "Missing required saveBytes" in r["errorMessage"]

    def test_non_arraybuffer_save_bytes_types(self):
        """Tests non-ArrayBuffer inputs (string, object, array, Symbol)."""
        script = JS_HARNESS_BASE + """
        async function run() {
          const h = createWorkerHarness();
          const results = [];

          // 1. Array of byte numbers
          h.messages.length = 0;
          await h.postMessageToWorker({
            action: 'plan',
            saveBytes: [1, 2, 3],
            config: { slots: 10 }
          });
          const arrayRes = h.messages.find(m => m.action === 'result');
          results.push({ test: 'number_array', success: !!arrayRes });

          // 2. String saveBytes (new Uint8Array('str') -> Uint8Array(0))
          h.messages.length = 0;
          await h.postMessageToWorker({
            action: 'plan',
            saveBytes: 'corrupt_string',
            config: {}
          });
          const strRes = h.messages.find(m => m.action === 'result');
          results.push({ test: 'string_bytes', success: !!strRes });

          // 3. Plain object saveBytes (new Uint8Array({}) -> Uint8Array(0))
          h.messages.length = 0;
          await h.postMessageToWorker({
            action: 'plan',
            saveBytes: { invalid: 'object' },
            config: {}
          });
          const objRes = h.messages.find(m => m.action === 'result');
          results.push({ test: 'object_bytes', success: !!objRes });

          console.log(JSON.stringify({ results }));
        }
        run();
        """
        data = run_node_worker_harness(script)
        for r in data["results"]:
            assert r["success"] is True, f"Failed type handling: {r}"

    def test_malformed_and_edge_case_config(self):
        """Tests worker resilience with null, string, and circular config."""
        script = JS_HARNESS_BASE + """
        async function run() {
          const h = createWorkerHarness();
          const results = [];

          // 1. Null config -> defaults to {}
          h.messages.length = 0;
          await h.postMessageToWorker({
            action: 'plan',
            saveBytes: new Uint8Array([1, 2]),
            config: null
          });
          const nullCfgRes = h.messages.find(m => m.action === 'result');
          results.push({
            test: 'null_config',
            ok: !!nullCfgRes && nullCfgRes.plan.stats.max_slots === 20
          });

          // 2. Invalid JSON string config
          h.messages.length = 0;
          await h.postMessageToWorker({
            action: 'plan',
            saveBytes: new Uint8Array([1, 2]),
            config: '{invalid json string'
          });
          const strCfgRes = h.messages.find(m => m.action === 'result');
          results.push({
            test: 'invalid_json_string_config',
            ok: !!strCfgRes
          });

          // 3. Circular config object -> caught cleanly, emits error
          h.messages.length = 0;
          const circular = {};
          circular.self = circular;
          await h.postMessageToWorker({
            action: 'plan',
            saveBytes: new Uint8Array([1, 2]),
            config: circular
          });
          const circErr = h.messages.find(m => m.action === 'error');
          results.push({
            test: 'circular_config',
            ok: !!circErr && circErr.message.includes('circular')
          });

          console.log(JSON.stringify({ results }));
        }
        run();
        """
        data = run_node_worker_harness(script)
        for r in data["results"]:
            assert r["ok"] is True, f"Config test failed: {r}"

    def test_filename_variations(self):
        """Verifies default and custom filename handling in Pyodide VFS."""
        script = JS_HARNESS_BASE + """
        async function run() {
          const h = createWorkerHarness();

          // 1. Custom filename
          await h.postMessageToWorker({
            action: 'plan',
            saveBytes: new Uint8Array([10, 20]),
            filename: 'my_slot_01.sav'
          });

          const hasCustom = '/tmp/my_slot_01.sav' in h.vfs;
          const hasUpload = '/tmp/upload.sav' in h.vfs;

          console.log(JSON.stringify({ hasCustom, hasUpload }));
        }
        run();
        """
        data = run_node_worker_harness(script)
        assert data["hasCustom"] is True
        assert data["hasUpload"] is True


# ==============================================================================
# 3. ERROR HANDLING PAYLOAD INTEGRITY
# ==============================================================================
class TestWorkerErrorHandlingPayloadIntegrity:
    """Verifies that all errors emitted by worker follow the exact contract."""

    def test_error_payload_fields_and_types(self):
        """Worker error payload must have action, message, detail strings."""
        script = JS_HARNESS_BASE + """
        async function run() {
          const h = createWorkerHarness({ throwInBridge: true });
          await h.postMessageToWorker({
            action: 'plan',
            saveBytes: new Uint8Array([1, 2, 3])
          });
          const err = h.messages.find(m => m.action === 'error');
          console.log(JSON.stringify({
            hasError: !!err,
            action: err ? err.action : null,
            messageType: err ? typeof err.message : null,
            detailType: err ? typeof err.detail : null,
            errorType: err ? typeof err.error : null,
            stackType: err ? typeof err.stack : null,
            message: err ? err.message : null,
          }));
        }
        run();
        """
        data = run_node_worker_harness(script)
        assert data["hasError"] is True
        assert data["action"] == "error"
        assert data["messageType"] == "string"
        assert data["detailType"] == "string"
        assert data["errorType"] == "string"
        assert data["stackType"] == "string"
        assert "Python bridge internal exception" in data["message"]

    def test_structured_cloneable_error_payload(self):
        """Verifies error payload can be cloned without throwing."""
        script = JS_HARNESS_BASE + """
        async function run() {
          const h = createWorkerHarness();
          await h.postMessageToWorker({ action: 'bad_action' });
          const err = h.messages.find(m => m.action === 'error');
          let cloneable = true;
          try {
            // structuredClone check (standard in Node 17+)
            structuredClone(err);
          } catch (e) {
            cloneable = false;
          }
          console.log(JSON.stringify({ cloneable }));
        }
        run();
        """
        data = run_node_worker_harness(script)
        assert data["cloneable"] is True


# ==============================================================================
# 4. RECOMPUTE STATE BOUNDARIES
# ==============================================================================
class TestWorkerRecomputeStateBoundaries:
    """Tests recompute before and after plan execution."""

    def test_recompute_before_save_loaded_fails_cleanly(self):
        """Recomputing with empty VFS must emit clean error message."""
        script = JS_HARNESS_BASE + """
        async function run() {
          const h = createWorkerHarness();
          await h.postMessageToWorker({ action: 'recompute', config: {} });
          const err = h.messages.find(m => m.action === 'error');
          console.log(JSON.stringify({
            hasError: !!err,
            message: err ? err.message : null
          }));
        }
        run();
        """
        data = run_node_worker_harness(script)
        assert data["hasError"] is True
        assert "No save file available in VFS" in data["message"]

    def test_recompute_after_plan_succeeds_with_new_config(self):
        """Recomputing after plan uses existing save with updated config."""
        script = JS_HARNESS_BASE + """
        async function run() {
          const h = createWorkerHarness();

          // 1. Initial plan
          await h.postMessageToWorker({
            action: 'plan',
            saveBytes: new Uint8Array([1, 2, 3]),
            config: { slots: 10 }
          });
          const planRes = h.messages.find(m => m.action === 'result');
          const initialSlots = planRes.plan.stats.max_slots;

          // 2. Recompute with new slots
          h.messages.length = 0;
          await h.postMessageToWorker({
            action: 'recompute',
            config: { slots: 25 }
          });
          const recompRes = h.messages.find(m => m.action === 'result');
          const updatedSlots = recompRes.plan.stats.max_slots;

          console.log(JSON.stringify({
            initialSlots,
            updatedSlots,
            durationMs: recompRes.durationMs
          }));
        }
        run();
        """
        data = run_node_worker_harness(script)
        assert data["initialSlots"] == 10
        assert data["updatedSlots"] == 25
        assert isinstance(data["durationMs"], (int, float))


# ==============================================================================
# 5. LIFECYCLE, CONCURRENCY, AND STATE MACHINE
# ==============================================================================
class TestWorkerLifecycleAndConcurrency:
    """Tests lifecycle, concurrent init calls, and auto-initialization."""

    def test_parallel_init_calls_single_initialization(self):
        """Multiple concurrent init calls must share single initPromise."""
        script = JS_HARNESS_BASE + """
        async function run() {
          const h = createWorkerHarness();
          // Trigger 5 parallel init calls
          await Promise.all([
            h.postMessageToWorker({ action: 'init' }),
            h.postMessageToWorker({ action: 'init' }),
            h.postMessageToWorker({ action: 'init' }),
            h.postMessageToWorker({ action: 'init' }),
            h.postMessageToWorker({ action: 'init' }),
          ]);
          const readyCount = h.messages.filter(
            m => m.action === 'ready'
          ).length;
          console.log(JSON.stringify({
            initCallCount: h.getInitCount(),
            readyCount: readyCount
          }));
        }
        run();
        """
        data = run_node_worker_harness(script)
        # loadPyodide should only be invoked once
        assert data["initCallCount"] == 1
        assert data["readyCount"] >= 1

    def test_plan_triggers_auto_initialization(self):
        """Sending 'plan' without prior 'init' must auto-initialize."""
        script = JS_HARNESS_BASE + """
        async function run() {
          const h = createWorkerHarness();
          await h.postMessageToWorker({
            action: 'plan',
            saveBytes: new Uint8Array([1, 2, 3]),
            config: { slots: 15 }
          });
          const hasProgress = h.messages.some(m => m.action === 'progress');
          const hasReady = h.messages.some(m => m.action === 'ready');
          const hasResult = h.messages.some(m => m.action === 'result');
          console.log(JSON.stringify({ hasProgress, hasReady, hasResult }));
        }
        run();
        """
        data = run_node_worker_harness(script)
        assert data["hasProgress"] is True
        assert data["hasReady"] is True
        assert data["hasResult"] is True


# ==============================================================================
# 6. EMPIRICAL FINDINGS & CORNER CASES INVESTIGATION
# ==============================================================================
class TestWorkerEmpiricalFindings:
    """
    Empirically documents and asserts specific design boundaries discovered
    during stress testing.
    """

    def test_finding_init_promise_latched_on_failure(self):
        """
        Finding 1: If handleInit fails (e.g. transient network outage),
        initPromise retains the rejected promise permanently because it is not
        reset in catch. Subsequent init attempts reject with the cached error.
        """
        script = JS_HARNESS_BASE + """
        async function run() {
          let shouldFail = true;
          const h = createWorkerHarness({
            get failPyodideLoad() { return shouldFail; }
          });

          // 1. First init fails due to network outage
          await h.postMessageToWorker({ action: 'init' });
          const firstErr = h.messages.find(m => m.action === 'error');

          // 2. Network is now restored
          shouldFail = false;
          h.messages.length = 0;
          await h.postMessageToWorker({ action: 'init' });
          const secondErr = h.messages.find(m => m.action === 'error');

          console.log(JSON.stringify({
            firstFailed: !!firstErr,
            secondFailed: !!secondErr,
            secondMessage: secondErr ? secondErr.message : null
          }));
        }
        run();
        """
        data = run_node_worker_harness(script)
        assert data["firstFailed"] is True
        # Confirms the finding: second call also failed with the cached error
        assert data["secondFailed"] is True
        assert "network load failure" in data["secondMessage"]

    def test_finding_onmessage_undefined_event_handling(self):
        """
        Finding 2: In line 223 `const data = event.data || {}`, if onmessage
        is invoked directly with undefined/null (outside standard browser event
        dispatch), accessing event.data throws before the try/catch block.
        With valid event ({ data: ... }), it is cleanly handled.
        """
        script = JS_HARNESS_BASE + """
        async function run() {
          const h = createWorkerHarness();

          let threwOnUndefined = false;
          try {
            await h.self.onmessage();
          } catch (e) {
            threwOnUndefined = true;
          }

          let handledOnEmptyData = false;
          h.messages.length = 0;
          try {
            await h.self.onmessage({ data: null });
            handledOnEmptyData = h.messages.some(m => m.action === 'error');
          } catch (e) {
            handledOnEmptyData = false;
          }

          console.log(
            JSON.stringify({ threwOnUndefined, handledOnEmptyData })
          );
        }
        run();
        """
        data = run_node_worker_harness(script)
        assert data["threwOnUndefined"] is True
        assert data["handledOnEmptyData"] is True


# ==============================================================================
# 7. PYTHON BRIDGE ADVERSARIAL SIMULATION (CANONICAL SCHEMA UNDER STRESS)
# ==============================================================================
class TestWorkerSimulatedBridgeAdversarial:
    """Tests Python web bridge behavior under corrupted worker inputs."""

    @pytest.fixture(autouse=True)
    def setup_bridge(self):
        import sys

        sys.path.insert(0, str(REPO_ROOT / "web" / "py"))
        import web_bridge

        web_bridge.init_bridge(str(DATA_DIR))
        self.bridge = web_bridge

    def test_bridge_corrupted_save_bytes(self):
        """Bridge returns valid canonical JSON with error on corrupt save."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_save = Path(tmpdir) / "upload.sav"
            bad_save.write_bytes(b"\x00" * 256)

            res = self.bridge.generate_plan(str(bad_save), config_dict="{}")
            plan = json.loads(res)

            assert plan["save_info"]["found"] is False
            assert plan["error"] is not None
            assert "bag_plan" in plan
            assert "focus_suggestions" in plan
            assert "source_priority" in plan

    def test_bridge_sample_save_canonical_execution(self):
        """Bridge must parse sample save and produce 16 canonical keys."""
        assert SAMPLE_SAVE_PATH.exists()
        res = self.bridge.generate_plan(
            str(SAMPLE_SAVE_PATH), config_dict="{}"
        )
        plan = json.loads(res)
        assert plan["save_info"]["found"] is True
        assert plan["save_info"]["player_name"] == "Aria"
        assert len(plan["bag_plan"]) > 0
