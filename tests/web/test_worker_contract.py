"""
tests/test_worker_contract.py

Contract, syntax, and protocol verification tests for web/planner.worker.js.
Ensures that the Pyodide Web Worker conforms to the specifications defined in
PROJECT.md § Interface Contracts and ORIGINAL_REQUEST.md.
"""

import json
from pathlib import Path
import re
import sys
import tempfile

from pygments.lexers import JavascriptLexer
from pygments.token import Error
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER_PATH = REPO_ROOT / "web" / "planner.worker.js"
SAMPLE_SAVE_PATH = REPO_ROOT / "web" / "sample_save.sav"

# 6 mandatory game databases
MANDATORY_DATA_FILES = [
    "item_data.json",
    "recipes.json",
    "alt_sources.json",
    "item_locations.json",
    "recipe_sources.json",
    "item_seasons.json",
]

# 16 canonical PlanData keys
CANONICAL_PLAN_KEYS = [
    "generated_at",
    "save_info",
    "in_game_date",
    "stats",
    "bag_plan",
    "focus_suggestions",
    "focus_trees",
    "source_priority",
    "npc_progress",
    "completed_npcs_details",
    "incomplete_npcs_details",
    "unobtained_recipes",
    "recipe_stats",
    "infused_items",
    "config",
    "error",
]


@pytest.fixture(scope="module")
def worker_code() -> str:
    """Fixture providing raw content of web/planner.worker.js."""
    assert WORKER_PATH.exists(), f"Missing worker file at {WORKER_PATH}"
    return WORKER_PATH.read_text(encoding="utf-8")


# ==============================================================================
# 1. SYNTAX, LEXICAL, AND STRUCTURAL VERIFICATION
# ==============================================================================
class TestWorkerSyntaxAndStructure:
    """Validates that web/planner.worker.js parses cleanly."""

    def test_worker_file_exists_and_non_empty(self):
        assert WORKER_PATH.exists(), f"File does not exist: {WORKER_PATH}"
        size = WORKER_PATH.stat().st_size
        assert size > 200, f"Worker file unexpectedly small: {size} bytes"

    def test_worker_lexical_tokenization_no_errors(self, worker_code: str):
        """Verifies Pygments lexer tokenizes with zero Error tokens."""
        lexer = JavascriptLexer()
        tokens = list(lexer.get_tokens(worker_code))
        errors = [t for t in tokens if t[0] is Error]
        err_msg = f"Lexical errors found in {WORKER_PATH}: {errors[:5]}"
        assert len(errors) == 0, err_msg

    def test_worker_brackets_and_quotes_balance(self, worker_code: str):
        """Verifies balancing of brackets, braces, and literals."""
        stack = []
        pairs = {")": "(", "]": "[", "}": "{"}
        i = 0
        n = len(worker_code)

        while i < n:
            c = worker_code[i]
            # Single-line comment
            if c == "/" and i + 1 < n and worker_code[i + 1] == "/":
                i = worker_code.find("\n", i)
                if i == -1:
                    break
                continue
            # Multi-line comment
            if c == "/" and i + 1 < n and worker_code[i + 1] == "*":
                end = worker_code.find("*/", i + 2)
                assert end != -1, "Unclosed block comment"
                i = end + 2
                continue
            # Single quote string
            if c == "'":
                i += 1
                while i < n:
                    if worker_code[i] == "\\":
                        i += 2
                    elif worker_code[i] == "'":
                        i += 1
                        break
                    else:
                        i += 1
                continue
            # Double quote string
            if c == '"':
                i += 1
                while i < n:
                    if worker_code[i] == "\\":
                        i += 2
                    elif worker_code[i] == '"':
                        i += 1
                        break
                    else:
                        i += 1
                continue
            # Template literal
            if c == "`":
                i += 1
                while i < n:
                    if worker_code[i] == "\\":
                        i += 2
                    elif worker_code[i] == "`":
                        i += 1
                        break
                    else:
                        i += 1
                continue
            # Brackets
            if c in "([{":
                stack.append((c, i))
            elif c in ")]}":
                assert stack, f"Unmatched closing bracket {c} at offset {i}"
                top, pos = stack.pop()
                err_detail = (
                    f"Mismatched bracket: {top} at {pos} closed by {c} at {i}"
                )
                assert pairs[c] == top, err_detail
            i += 1

        unclosed_msg = (
            f"Unclosed bracket {stack[-1][0]} at offset {stack[-1][1]}"
            if stack
            else ""
        )
        assert not stack, unclosed_msg

    def test_worker_zero_server_or_companion_deps(self, worker_code: str):
        """Web worker must not make server API calls or import backend."""
        assert "fetch('/api" not in worker_code
        assert 'fetch("/api' not in worker_code
        assert "EventSource" not in worker_code
        assert "companion." not in worker_code


# ==============================================================================
# 2. PYODIDE INITIALIZATION CONTRACT
# ==============================================================================
class TestWorkerPyodideInitializationContract:
    """Verifies Pyodide 0.26.4 runtime configuration and CDN loading."""

    def test_pyodide_cdn_url_specification(self, worker_code: str):
        cdn = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js"
        assert cdn in worker_code, f"Missing CDN URL '{cdn}' in worker"

    def test_import_scripts_called_with_cdn_url(self, worker_code: str):
        pattern = (
            r'importScripts\s*\(\s*["\']'
            r'https://cdn\.jsdelivr\.net/pyodide/v0\.26\.4/full/pyodide\.js'
            r'["\']\s*\)'
        )
        assert re.search(pattern, worker_code)

    def test_load_pyodide_invocation(self, worker_code: str):
        assert "loadPyodide(" in worker_code

    def test_micropip_loading(self, worker_code: str):
        pattern = r'loadPackage\s*\(\s*["\']micropip["\']\s*\)'
        assert re.search(pattern, worker_code)

    def test_local_wheel_resolution_and_install(self, worker_code: str):
        assert "fom_gift_planner-1.2.0-py3-none-any.whl" in worker_code
        assert "self.location.href" in worker_code
        pattern_install = r"micropip\.install\s*\(\s*(\w+)\s*\)"
        assert re.search(pattern_install, worker_code)


# ==============================================================================
# 3. VIRTUAL FILE SYSTEM (VFS) & DATA LOADING CONTRACT
# ==============================================================================
class TestWorkerVfsAndDataContract:
    """Verifies Pyodide VFS directories, data mounting, and save file paths."""

    def test_vfs_directories_created(self, worker_code: str):
        has_data = (
            'mkdirTree("/data")' in worker_code
            or "mkdirTree('/data')" in worker_code
        )
        assert has_data
        has_home = (
            'mkdirTree("/home/pyodide")' in worker_code
            or "mkdirTree('/home/pyodide')" in worker_code
        )
        assert has_home
        has_tmp = (
            'mkdirTree("/tmp")' in worker_code
            or "mkdirTree('/tmp')" in worker_code
        )
        assert has_tmp

    def test_all_6_json_databases_loaded_into_vfs(self, worker_code: str):
        for fname in MANDATORY_DATA_FILES:
            assert fname in worker_code, f"Missing {fname}"

        has_write = (
            'pyodide.FS.writeFile("/data/' in worker_code
            or "pyodide.FS.writeFile('/data/" in worker_code
        )
        assert has_write

    def test_web_bridge_loaded_into_vfs(self, worker_code: str):
        assert "py/web_bridge.py" in worker_code
        assert "/home/pyodide/web_bridge.py" in worker_code
        has_init = (
            "web_bridge.init_bridge('/data')" in worker_code
            or 'web_bridge.init_bridge("/data")' in worker_code
        )
        assert has_init

    def test_save_bytes_written_to_vfs_tmp(self, worker_code: str):
        assert "/tmp/upload.sav" in worker_code
        assert "Uint8Array" in worker_code
        assert "pyodide.FS.writeFile" in worker_code


# ==============================================================================
# 4. WORKER MESSAGE PROTOCOL CONTRACT
# ==============================================================================
class TestWorkerMessageProtocolContract:
    """Verifies complete postMessage action handling."""

    def test_self_onmessage_handler_defined(self, worker_code: str):
        assert "self.onmessage" in worker_code

    def test_actions_handled(self, worker_code: str):
        assert '"init"' in worker_code or "'init'" in worker_code
        assert '"plan"' in worker_code or "'plan'" in worker_code
        assert '"recompute"' in worker_code or "'recompute'" in worker_code

    def test_progress_events_emitted(self, worker_code: str):
        assert '"progress"' in worker_code or "'progress'" in worker_code
        steps = ["pyodide", "micropip", "wheel", "data", "bridge"]
        for step in steps:
            found = f'"{step}"' in worker_code or f"'{step}'" in worker_code
            assert found, f"Missing progress step: {step}"

    def test_ready_event_emitted(self, worker_code: str):
        pattern = r'postMessage\s*\(\s*\{\s*action:\s*["\']ready["\']'
        assert re.search(pattern, worker_code)

    def test_result_event_emitted_with_plan_and_duration(
        self, worker_code: str
    ):
        pattern_result = r'action:\s*["\']result["\']'
        assert re.search(pattern_result, worker_code)
        assert "plan:" in worker_code or "plan :" in worker_code
        assert "durationMs" in worker_code

    def test_error_event_emitted_with_message_and_detail(
        self, worker_code: str
    ):
        pattern_error = r'action:\s*["\']error["\']'
        assert re.search(pattern_error, worker_code)
        assert "message:" in worker_code or "message :" in worker_code
        assert "detail:" in worker_code or "detail :" in worker_code

    def test_error_handling_try_catch_wrapped(self, worker_code: str):
        has_try = "try {" in worker_code or "try{" in worker_code
        has_catch = "} catch" in worker_code or "}catch" in worker_code
        assert has_try and has_catch

    def test_web_bridge_generate_plan_invocation(self, worker_code: str):
        assert "generate_plan(" in worker_code
        assert "JSON.parse(" in worker_code


# ==============================================================================
# 5. PYTHON BRIDGE SIMULATION (END-TO-END EXECUTION OF WORKER ACTIONS)
# ==============================================================================
class TestWorkerBridgeExecutionSimulation:
    """
    Simulates the exact Python commands that planner.worker.js executes
    inside Pyodide to guarantee end-to-end correctness of the contract.
    """

    @pytest.fixture(autouse=True)
    def setup_bridge(self):
        sys.path.insert(0, str(REPO_ROOT / "web" / "py"))
        import web_bridge

        web_bridge.init_bridge(str(REPO_ROOT / "web" / "data"))
        self.bridge = web_bridge

    def test_simulated_init_action(self):
        """Simulates step 'bridge': web_bridge.init_bridge('/data')."""
        assert "all_recipes" in self.bridge._CACHED_DATA
        assert len(self.bridge._CACHED_DATA["all_recipes"]) > 100
        assert "item_locations" in self.bridge._CACHED_DATA
        assert "alt_sources" in self.bridge._CACHED_DATA

    def test_simulated_plan_action_execution(self):
        """Simulates action 'plan': write save bytes and generate plan."""
        assert SAMPLE_SAVE_PATH.exists()
        save_bytes = SAMPLE_SAVE_PATH.read_bytes()

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_save = Path(tmpdir) / "upload.sav"
            vfs_save.write_bytes(save_bytes)

            config = json.dumps(
                {"slots": 20, "strategy": "journal", "mode": "auto"}
            )
            result_str = self.bridge.generate_plan(
                str(vfs_save), config_dict=config, filename="upload.sav"
            )
            assert isinstance(result_str, str)

            plan = json.loads(result_str)
            assert plan["save_info"]["found"] is True
            assert plan["save_info"]["player_name"] == "Aria"
            assert plan["save_info"]["farm_name"] == "Starlight Farm"
            for key in CANONICAL_PLAN_KEYS:
                assert key in plan, f"Missing canonical key: {key}"

    def test_simulated_recompute_action_execution(self):
        """Simulates action 'recompute': re-runs plan with new config."""
        assert SAMPLE_SAVE_PATH.exists()
        save_bytes = SAMPLE_SAVE_PATH.read_bytes()

        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_save = Path(tmpdir) / "upload.sav"
            vfs_save.write_bytes(save_bytes)

            # Initial plan
            config_1 = json.dumps({"slots": 20, "strategy": "journal"})
            res_1 = json.loads(
                self.bridge.generate_plan(
                    str(vfs_save), config_dict=config_1, filename="upload.sav"
                )
            )
            assert res_1["stats"]["max_slots"] == 20

            # Recompute with updated slots
            config_2 = json.dumps(
                {"slots": 14, "strategy": "max-relationship"}
            )
            res_2 = json.loads(
                self.bridge.generate_plan(
                    str(vfs_save), config_dict=config_2, filename="upload.sav"
                )
            )
            assert res_2["stats"]["max_slots"] == 14
            assert res_2["config"]["strategy"] == "max-relationship"
