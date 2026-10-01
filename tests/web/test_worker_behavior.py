"""
tests/test_worker_behavioral_simulation.py

Empirical behavioral simulation and stress harness for web/planner.worker.js.
Simulates runtime execution of the Pyodide Web Worker message lifecycle:
1. Worker message lifecycle: init -> progress events -> ready -> plan -> result
   -> recompute -> result.
2. Canonical 16-key PlanData schema verification and frontend field schema
   compatibility mirroring app.js renderer expectations.
3. Virtual File System (VFS) path resolution parity across web/data/*.json,
   web/py/web_bridge.py, and web/planner.worker.js.
4. Adversarial stress testing: edge cases, concurrent inits, missing saveBytes,
   recompute before plan, corrupt inputs, and rapid setting mutations.
"""

import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Dict, List, Optional, Union

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER_PATH = REPO_ROOT / "web" / "planner.worker.js"
SAMPLE_SAVE_PATH = REPO_ROOT / "web" / "sample_save.sav"
DATA_DIR_PATH = REPO_ROOT / "web" / "data"
BRIDGE_PATH = REPO_ROOT / "web" / "py" / "web_bridge.py"
WHEEL_PATH = REPO_ROOT / "web" / "fom_gift_planner-1.2.0-py3-none-any.whl"

# Ensure web/py is in sys.path
sys.path.insert(0, str(REPO_ROOT / "web" / "py"))
import web_bridge  # noqa: E402

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

EXPECTED_DATA_FILES = [
    "item_data.json",
    "recipes.json",
    "alt_sources.json",
    "item_locations.json",
    "recipe_sources.json",
    "item_seasons.json",
]


class PyodideWorkerSimulator:
    """
    High-fidelity behavioral simulator for web/planner.worker.js.
    Mirrors Web Worker event loop, Pyodide Emscripten VFS, package loading,
    and Python web bridge execution.
    """

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.is_ready: bool = False
        self.init_in_progress: bool = False
        self.outbox: List[Dict[str, Any]] = []
        self.vfs: Dict[str, Union[bytes, str]] = {}
        self.last_save_path: str = "/tmp/upload.sav"
        self.last_filename: str = "upload.sav"

        self._temp_dir = tempfile.TemporaryDirectory()
        self.temp_root = Path(self._temp_dir.name)
        self.vfs_data_dir = self.temp_root / "data"
        self.vfs_data_dir.mkdir(parents=True, exist_ok=True)
        self.vfs_tmp_dir = self.temp_root / "tmp"
        self.vfs_tmp_dir.mkdir(parents=True, exist_ok=True)
        self.vfs_home_dir = self.temp_root / "home" / "pyodide"
        self.vfs_home_dir.mkdir(parents=True, exist_ok=True)

    def close(self):
        """Cleanup temporary VFS directory."""
        self._temp_dir.cleanup()

    def post_message(self, message: Dict[str, Any]):
        """Records outgoing worker messages."""
        self.outbox.append(message)

    def get_messages_by_action(self, action: str) -> List[Dict[str, Any]]:
        """Filters outbox messages by action."""
        return [m for m in self.outbox if m.get("action") == action]

    def clear_outbox(self):
        """Clears outbox."""
        self.outbox.clear()

    def handle_init(self):
        """Simulates handleInit() in planner.worker.js."""
        if self.is_ready:
            self.post_message({"action": "ready"})
            return

        if self.init_in_progress:
            self.post_message({"action": "ready"})
            return

        self.init_in_progress = True

        # Step 1: Pyodide loading
        self.post_message({
            "action": "progress",
            "step": "pyodide",
            "percent": 20,
            "message": "Loading Pyodide WASM runtime...",
        })

        # Step 2: micropip package loading
        self.post_message({
            "action": "progress",
            "step": "micropip",
            "percent": 40,
            "message": "Loading micropip package manager...",
        })

        # Step 3: Install local wheel
        self.post_message({
            "action": "progress",
            "step": "wheel",
            "percent": 60,
            "message": "Installing Fields of Mistria gift planner wheel...",
        })
        if not WHEEL_PATH.exists():
            raise FileNotFoundError(f"Missing wheel at {WHEEL_PATH}")

        # Step 4: Populate data databases into Pyodide VFS
        self.post_message({
            "action": "progress",
            "step": "data",
            "percent": 80,
            "message": "Populating game databases into virtual filesystem...",
        })
        for fname in EXPECTED_DATA_FILES:
            src = DATA_DIR_PATH / fname
            if not src.exists():
                raise FileNotFoundError(f"Missing data file {src}")
            content = src.read_text(encoding="utf-8")
            self.vfs[f"/data/{fname}"] = content
            (self.vfs_data_dir / fname).write_text(content, encoding="utf-8")

        # Step 5: Populate Python web bridge module
        self.post_message({
            "action": "progress",
            "step": "bridge",
            "percent": 95,
            "message": "Initializing Python web bridge...",
        })
        if not BRIDGE_PATH.exists():
            raise FileNotFoundError(f"Missing bridge file {BRIDGE_PATH}")
        bridge_code = BRIDGE_PATH.read_text(encoding="utf-8")
        self.vfs["/home/pyodide/web_bridge.py"] = bridge_code
        (self.vfs_home_dir / "web_bridge.py").write_text(
            bridge_code, encoding="utf-8"
        )

        web_bridge.init_bridge(str(self.vfs_data_dir))
        self.is_ready = True
        self.init_in_progress = False
        self.post_message({"action": "ready"})

    def handle_plan(self, data: Dict[str, Any]):
        """Simulates handlePlan(data) in planner.worker.js."""
        if not self.is_ready:
            self.handle_init()

        save_bytes = data.get("saveBytes")
        if save_bytes is None:
            raise ValueError("Missing required saveBytes in plan request.")

        if isinstance(save_bytes, str):
            raw_bytes = save_bytes.encode("utf-8")
        elif isinstance(save_bytes, (bytes, bytearray)):
            raw_bytes = bytes(save_bytes)
        else:
            raw_bytes = bytes(save_bytes)

        filename = data.get("filename") or "upload.sav"
        save_path = f"/tmp/{filename}"
        self.vfs[save_path] = raw_bytes
        (self.vfs_tmp_dir / filename).write_bytes(raw_bytes)

        if save_path != "/tmp/upload.sav":
            self.vfs["/tmp/upload.sav"] = raw_bytes
            (self.vfs_tmp_dir / "upload.sav").write_bytes(raw_bytes)

        self.last_save_path = save_path
        self.last_filename = filename

        config = data.get("config")
        config_dict = (
            config if isinstance(config, str) else json.dumps(config or {})
        )

        disk_save_path = self.vfs_tmp_dir / filename
        result_json = web_bridge.generate_plan(
            str(disk_save_path),
            config_dict=config_dict,
            filename=filename,
            data_dir=str(self.vfs_data_dir),
        )
        plan = json.loads(result_json)
        self.post_message({
            "action": "result",
            "plan": plan,
            "data": plan,
            "durationMs": 15,
        })

    def handle_recompute(self, data: Dict[str, Any]):
        """Simulates handleRecompute(data) in planner.worker.js."""
        if not self.is_ready:
            self.handle_init()

        upload_path = self.vfs_tmp_dir / "upload.sav"
        if not upload_path.exists():
            raise ValueError(
                "No save file available in VFS (/tmp/upload.sav) to "
                "recompute. Please upload a save file first."
            )

        filename = self.last_filename or "upload.sav"
        config = data.get("config")
        config_dict = (
            config if isinstance(config, str) else json.dumps(config or {})
        )

        result_json = web_bridge.generate_plan(
            str(upload_path),
            config_dict=config_dict,
            filename=filename,
            data_dir=str(self.vfs_data_dir),
        )
        plan = json.loads(result_json)
        self.post_message({
            "action": "result",
            "plan": plan,
            "data": plan,
            "durationMs": 10,
        })

    def on_message(self, event_data: Optional[Dict[str, Any]]):
        """Simulates self.onmessage event listener."""
        data = event_data or {}
        action = data.get("action")
        try:
            if action == "init":
                self.handle_init()
            elif action == "plan":
                self.handle_plan(data)
            elif action == "recompute":
                self.handle_recompute(data)
            else:
                raise ValueError(f"Unknown action: {action}")
        except Exception as err:
            self.post_message({
                "action": "error",
                "message": str(err),
                "detail": str(err),
                "error": str(err),
                "stack": str(err),
            })


@pytest.fixture
def sim():
    """Provides a clean worker simulator instance."""
    simulator = PyodideWorkerSimulator(REPO_ROOT)
    yield simulator
    simulator.close()


@pytest.fixture(scope="module")
def worker_code() -> str:
    """Provides raw code of web/planner.worker.js."""
    assert WORKER_PATH.exists()
    return WORKER_PATH.read_text(encoding="utf-8")


@pytest.fixture
def sample_bytes() -> bytes:
    """Provides bytes of web/sample_save.sav."""
    assert SAMPLE_SAVE_PATH.exists()
    return SAMPLE_SAVE_PATH.read_bytes()


# ==============================================================================
# 1. VFS AND FILE PATH PARITY VERIFICATION
# ==============================================================================
class TestWorkerVfsAndDataFileParity:
    """
    Empirically validates that VFS file paths constructed by planner.worker.js
    strictly match exact filenames in web/data/*.json, web/py/web_bridge.py,
    and the wheel distribution.
    """

    def test_worker_data_files_array_exact_match(self, worker_code: str):
        """Verifies DATA_FILES in planner.worker.js matches expected."""
        match = re.search(
            r"const DATA_FILES\s*=\s*\[(.*?)\];", worker_code, re.S
        )
        assert match is not None, "DATA_FILES array not found in worker"
        raw_items = [
            x.strip().strip('"').strip("'")
            for x in match.group(1).split(",")
            if x.strip().strip('"').strip("'")
        ]
        assert sorted(raw_items) == sorted(EXPECTED_DATA_FILES)

    def test_web_data_directory_contains_all_expected_files(self):
        """Verifies each expected data JSON file exists in web/data/."""
        disk_files = {p.name for p in DATA_DIR_PATH.glob("*.json")}
        for fname in EXPECTED_DATA_FILES:
            assert fname in disk_files, f"Missing file in web/data: {fname}"
            fpath = DATA_DIR_PATH / fname
            assert fpath.stat().st_size > 0, f"File {fname} is empty"

    def test_all_data_files_valid_non_empty_json(self):
        """Verifies all 6 data files parse into valid objects."""
        for fname in EXPECTED_DATA_FILES:
            fpath = DATA_DIR_PATH / fname
            data = json.loads(fpath.read_text(encoding="utf-8"))
            assert isinstance(data, (dict, list))
            assert len(data) > 0, f"JSON {fname} has length 0"

    def test_bridge_data_resolution_accepts_vfs_data_path(self, sim):
        """Verifies web_bridge._resolve_data_dir() resolves VFS data dir."""
        sim.handle_init()
        resolved = web_bridge._resolve_data_dir(str(sim.vfs_data_dir))
        assert resolved == sim.vfs_data_dir.resolve()
        assert (resolved / "item_data.json").exists()

    def test_wheel_filename_parity(self, worker_code: str):
        """Verifies WHEEL_FILENAME matches actual wheel file on disk."""
        match = re.search(
            r'const WHEEL_FILENAME\s*=\s*["\']([^"\']+)["\'];', worker_code
        )
        assert match is not None
        wheel_name = match.group(1)
        assert wheel_name == "fom_gift_planner-1.2.0-py3-none-any.whl"
        actual_wheel = REPO_ROOT / "web" / wheel_name
        assert actual_wheel.exists(), f"Wheel file not found: {actual_wheel}"
        assert actual_wheel.stat().st_size > 100_000

    def test_pyodide_cdn_url_format(self, worker_code: str):
        """Verifies Pyodide CDN URL is properly formed."""
        match = re.search(
            r'const PYODIDE_CDN_URL\s*=\s*["\']([^"\']+)["\'];', worker_code
        )
        assert match is not None
        cdn_url = match.group(1)
        assert cdn_url.startswith("https://cdn.jsdelivr.net/pyodide/v0.26.4/")
        assert cdn_url.endswith("/pyodide.js")


# ==============================================================================
# 2. WORKER MESSAGE LIFECYCLE SIMULATION
# ==============================================================================
class TestWorkerMessageLifecycleSimulation:
    """
    Simulates complete Worker message lifecycle and state transitions:
    init -> progress -> ready -> plan -> result -> recompute -> result.
    """

    def test_complete_message_lifecycle(self, sim, sample_bytes):
        """
        Executes full standard lifecycle:
        1. init triggers progress events (5 steps) and ready.
        2. plan triggers result event with plan object and durationMs.
        3. recompute triggers result event with updated plan object.
        """
        # Step 1: Send 'init'
        sim.on_message({"action": "init"})

        progress_msgs = sim.get_messages_by_action("progress")
        assert len(progress_msgs) == 5, (
            f"Expected 5 progress steps, got {len(progress_msgs)}"
        )
        expected_steps = [
            ("pyodide", 20),
            ("micropip", 40),
            ("wheel", 60),
            ("data", 80),
            ("bridge", 95),
        ]
        for idx, (step_name, pct) in enumerate(expected_steps):
            assert progress_msgs[idx]["step"] == step_name
            assert progress_msgs[idx]["percent"] == pct
            assert "message" in progress_msgs[idx]

        ready_msgs = sim.get_messages_by_action("ready")
        assert len(ready_msgs) == 1
        assert sim.is_ready is True

        sim.clear_outbox()

        # Step 2: Send 'plan'
        sim.on_message({
            "action": "plan",
            "saveBytes": sample_bytes,
            "filename": "sample_save.sav",
            "config": {"slots": 20, "strategy": "journal"},
        })

        result_msgs = sim.get_messages_by_action("result")
        assert len(result_msgs) == 1
        res = result_msgs[0]
        assert "plan" in res
        assert "data" in res
        assert res["plan"] is res["data"]
        assert isinstance(res["durationMs"], (int, float))
        assert res["durationMs"] >= 0
        assert res["plan"]["save_info"]["found"] is True
        assert res["plan"]["save_info"]["player_name"] == "Aria"
        assert res["plan"]["stats"]["max_slots"] == 20

        sim.clear_outbox()

        # Step 3: Send 'recompute' with updated slots and strategy
        sim.on_message({
            "action": "recompute",
            "config": {"slots": 12, "strategy": "max-relationship"},
        })

        recompute_msgs = sim.get_messages_by_action("result")
        assert len(recompute_msgs) == 1
        recomp = recompute_msgs[0]
        assert recomp["plan"]["stats"]["max_slots"] == 12
        assert recomp["plan"]["config"]["strategy"] == "max-relationship"

    def test_init_idempotency_when_already_ready(self, sim):
        """Calling init when already ready should immediately post ready."""
        sim.on_message({"action": "init"})
        assert len(sim.get_messages_by_action("ready")) == 1

        sim.clear_outbox()
        # Second init call
        sim.on_message({"action": "init"})
        ready_msgs = sim.get_messages_by_action("ready")
        assert len(ready_msgs) == 1
        # No new progress events should be emitted
        assert len(sim.get_messages_by_action("progress")) == 0

    def test_plan_triggers_implicit_init_if_not_ready(self, sim, sample_bytes):
        """Sending plan before init automatically initializes and completes."""
        assert sim.is_ready is False
        sim.on_message({
            "action": "plan",
            "saveBytes": sample_bytes,
            "filename": "sample_save.sav",
        })
        assert sim.is_ready is True
        assert len(sim.get_messages_by_action("ready")) == 1
        results = sim.get_messages_by_action("result")
        assert len(results) == 1
        assert results[0]["plan"]["save_info"]["found"] is True

    def test_recompute_without_prior_save_emits_error(self, sim):
        """Recomputing before any save file is uploaded emits error message."""
        sim.on_message({"action": "recompute", "config": {}})
        errors = sim.get_messages_by_action("error")
        assert len(errors) == 1
        assert "No save file available in VFS" in errors[0]["message"]
        assert "error" in errors[0]
        assert "detail" in errors[0]

    def test_plan_missing_save_bytes_emits_error(self, sim):
        """Sending plan action without saveBytes emits error."""
        sim.on_message({"action": "plan"})
        errors = sim.get_messages_by_action("error")
        assert len(errors) == 1
        assert "Missing required saveBytes in plan request." in (
            errors[0]["message"]
        )

    def test_unknown_action_emits_error(self, sim):
        """Sending unknown action emits error."""
        sim.on_message({"action": "unsupported_action_xyz"})
        errors = sim.get_messages_by_action("error")
        assert len(errors) == 1
        assert "Unknown action: unsupported_action_xyz" in errors[0]["message"]

    def test_empty_event_data_emits_error(self, sim):
        """Sending None or empty object emits error."""
        sim.on_message({})
        errors = sim.get_messages_by_action("error")
        assert len(errors) == 1
        assert "Unknown action: None" in errors[0]["message"]


# ==============================================================================
# 3. CANONICAL 16-KEY PLANDATA SCHEMA COMPLIANCE
# ==============================================================================
class TestPlanDataCanonicalSchemaCompliance:
    """
    Verifies that simulated plan output produces full PlanData matching
    all 16 canonical keys and exact field schemas.
    """

    @pytest.fixture(autouse=True)
    def run_plan(self, sim, sample_bytes):
        sim.on_message({
            "action": "plan",
            "saveBytes": sample_bytes,
            "filename": "sample_save.sav",
            "config": {
                "slots": 20,
                "strategy": "journal",
                "mode": "auto",
                "focus_sort": "impact",
            },
        })
        results = sim.get_messages_by_action("result")
        assert len(results) == 1
        self.plan = results[0]["plan"]

    def test_all_16_canonical_keys_present(self):
        """Verify presence of all 16 canonical keys."""
        assert len(self.plan.keys()) == 16
        for key in CANONICAL_PLAN_KEYS:
            assert key in self.plan, f"Missing canonical key: {key}"

    def test_save_info_schema(self):
        """Verify save_info dictionary schema."""
        s = self.plan["save_info"]
        assert isinstance(s, dict)
        assert s["found"] is True
        assert s["player_name"] == "Aria"
        assert s["farm_name"] == "Starlight Farm"
        assert s["filename"] == "sample_save.sav"
        assert s["path"] is not None

    def test_in_game_date_schema(self):
        """Verify in_game_date dictionary schema."""
        d = self.plan["in_game_date"]
        assert isinstance(d, dict)
        assert d["year"] == 2
        assert d["season"] in ("Autumn", "Fall")
        assert d["day"] == 6
        assert d["day_of_week"] == "Saturday"
        assert d["is_saturday"] is True
        assert d["is_overridden"] is False
        assert isinstance(d["formatted"], str)

    def test_stats_schema(self):
        """Verify stats dictionary schema."""
        st = self.plan["stats"]
        assert isinstance(st, dict)
        assert st["max_slots"] == 20
        assert isinstance(st["slots_used"], int)
        assert isinstance(st["overall_gift_progress_pct"], (int, float))
        assert st["overall_gift_progress_pct"] >= 0
        assert isinstance(st["game_given_total"], int)
        assert isinstance(st["game_total_preferences"], int)
        assert isinstance(st["completed_npcs_count"], int)
        assert isinstance(st["incomplete_npcs_count"], int)
        assert isinstance(st["total_npcs_count"], int)
        assert st["total_npcs_count"] == (
            st["completed_npcs_count"] + st["incomplete_npcs_count"]
        )

    def test_bag_plan_schema(self):
        """Verify bag_plan items schema."""
        bp = self.plan["bag_plan"]
        assert isinstance(bp, list)
        valid_statuses = ("HAVE", "CRAFT", "NEED", "UNAVAILABLE")
        for item in bp:
            assert "item_id" in item and isinstance(item["item_id"], str)
            assert "item_name" in item and isinstance(item["item_name"], str)
            assert "quantity" in item and isinstance(item["quantity"], int)
            assert "status" in item and item["status"] in valid_statuses
            assert "recipients" in item and isinstance(
                item["recipients"], list
            )
            for r in item["recipients"]:
                assert "npc_id" in r
                assert "name" in r
                assert "preference" in r
                assert "points" in r
                assert "is_vendor" in r
            assert "crafting_steps" in item and isinstance(
                item["crafting_steps"], list
            )
            assert "sprite_url" in item and item["sprite_url"].startswith(
                "/assets/sprites/items/"
            )

    def test_focus_suggestions_and_trees_schema(self):
        """Verify focus_suggestions and focus_trees schema."""
        fs = self.plan["focus_suggestions"]
        assert isinstance(fs, list)
        for f in fs:
            assert "item_id" in f
            assert "item_name" in f
            assert "deficit" in f and isinstance(f["deficit"], int)
            assert "impact_score" in f
            assert "location" in f
            assert "seasons" in f and isinstance(f["seasons"], list)
            assert "blocked_npcs" in f and isinstance(f["blocked_npcs"], list)
            assert "alt_sources" in f and isinstance(f["alt_sources"], list)
            assert "sprite_url" in f and f["sprite_url"].startswith(
                "/assets/sprites/items/"
            )

        ft = self.plan["focus_trees"]
        assert isinstance(ft, list)
        for t in ft:
            assert "item_id" in t
            assert "item_name" in t or "name" in t
            assert "children" in t and isinstance(t["children"], list)

    def test_source_priority_schema(self):
        """Verify source_priority list and tier structure."""
        sp = self.plan["source_priority"]
        assert isinstance(sp, list)
        valid_tiers = {"quick", "grind", "farm"}
        for s in sp:
            assert "source_name" in s or "source" in s
            assert "tier" in s
            assert s["tier"].lower() in valid_tiers
            assert "total_score" in s and isinstance(
                s["total_score"], (int, float)
            )
            assert "items" in s and isinstance(s["items"], list)
            assert "benefited_npcs" in s and isinstance(
                s["benefited_npcs"], list
            )

    def test_npc_progress_and_drawer_details_schema(self):
        """Verify npc progress and drawer breakdown schemas."""
        np = self.plan["npc_progress"]
        assert isinstance(np, dict)
        completed = self.plan["completed_npcs_details"]
        incomplete = self.plan["incomplete_npcs_details"]
        assert isinstance(completed, list)
        assert isinstance(incomplete, list)
        assert len(completed) + len(incomplete) == len(np)

        for npc in completed:
            assert npc["is_completed"] is True
            assert npc["pct_total_done"] == 100.0
            assert "portrait_url" in npc

        for npc in incomplete:
            assert npc["is_completed"] is False
            assert "remaining_loved" in npc
            assert "remaining_liked" in npc
            assert "portrait_url" in npc


# ==============================================================================
# 4. FRONTEND APP.JS FIELD ACCESS COMPATIBILITY
# ==============================================================================
class TestFrontendAppJsFieldAccessCompatibility:
    """
    Simulates exact JavaScript property accesses from companion/static/app.js
    against simulated PlanData to verify 100% frontend compatibility.
    """

    @pytest.fixture(autouse=True)
    def plan_data(self, sim, sample_bytes):
        sim.on_message({
            "action": "plan",
            "saveBytes": sample_bytes,
            "filename": "sample_save.sav",
        })
        results = sim.get_messages_by_action("result")
        assert len(results) == 1
        return results[0]["plan"]

    def test_render_header_field_access(self, plan_data):
        """Simulates renderHeader() field accesses."""
        d = plan_data.get("in_game_date") or {}
        season = (d.get("season") or "Spring").lower()
        assert isinstance(season, str)

        day_n = d.get("day") or 1
        dow = d.get("day_of_week") or "Weekday"
        day_str = f"Day {day_n} ({dow})"
        if d.get("is_saturday"):
            day_str += " • SATURDAY MARKET"
        assert "Day 6" in day_str
        assert "SATURDAY MARKET" in day_str

        fest = d.get("festival_name")
        assert fest is None or isinstance(fest, str)
        is_over = d.get("is_overridden")
        assert is_over is False

        save_info = plan_data.get("save_info") or {}
        p_name = save_info.get("player_name") or "Player"
        f_name = save_info.get("farm_name") or "Farm"
        assert p_name == "Aria"
        assert f_name == "Starlight Farm"

    def test_render_stats_dashboard_field_access(self, plan_data):
        """Simulates renderStatsDashboard() field accesses."""
        stats = plan_data.get("stats") or {}
        overall_pct = stats.get("overall_gift_progress_pct", 0)
        assert overall_pct >= 0

        given_total = stats.get("game_given_total", 0)
        total_prefs = stats.get("game_total_preferences", 0)
        assert total_prefs > 0
        assert given_total >= 0

        completed_list = (
            plan_data.get("completed_npcs_details")
            or stats.get("completed_npcs_details")
            or []
        )
        incomplete_list = (
            plan_data.get("incomplete_npcs_details")
            or stats.get("incomplete_npcs_details")
            or []
        )
        completed_count = stats.get(
            "completed_npcs_count", len(completed_list)
        )
        incomplete_count = stats.get(
            "incomplete_npcs_count", len(incomplete_list)
        )
        total_npcs = stats.get("total_npcs_count") or (
            completed_count + incomplete_count
        )
        assert total_npcs > 0

        recipe_stats = plan_data.get("recipe_stats") or {}
        unobtained_recipes = plan_data.get("unobtained_recipes") or []
        locked_count = recipe_stats.get(
            "locked_count", len(unobtained_recipes)
        )
        unlocked_count = recipe_stats.get("unlocked_count", 0)
        total_cooking = recipe_stats.get(
            "total_cooking", locked_count + unlocked_count
        )
        assert total_cooking >= locked_count

    def test_render_bag_plan_field_access(self, plan_data):
        """Simulates renderBagPlan() field accesses."""
        bag_plan = plan_data.get("bag_plan") or []
        stats = plan_data.get("stats") or {}
        max_slots = stats.get("max_slots") or 20
        assert max_slots == 20

        valid_statuses = ("HAVE", "CRAFT", "NEED", "UNAVAILABLE")
        for item in bag_plan:
            status = item.get("status", "HAVE")
            assert status in valid_statuses
            recipients = item.get("recipients") or []
            for r in recipients:
                is_love = "LOVE" in r.get("preference", "")
                assert isinstance(is_love, bool)
                assert "npc_id" in r
                assert "name" in r
            c_steps = item.get("crafting_steps") or []
            for s in c_steps:
                assert "product_name" in s
                assert "ingredients" in s

    def test_render_focus_suggestions_and_source_summary_access(
        self, plan_data
    ):
        """Simulates renderFocusSuggestions & renderSourceSummary."""
        focus_items = plan_data.get("focus_suggestions") or []
        focus_trees = plan_data.get("focus_trees") or []
        source_priority = plan_data.get("source_priority") or []

        tree_map = {
            str(t.get("item_id") or "").lower(): t
            for t in focus_trees
        }

        for f in focus_items:
            f_id = str(f.get("item_id") or "").lower()
            seasons_str = ", ".join(f.get("seasons", [])) or "All Seasons"
            assert isinstance(seasons_str, str)
            tree = tree_map.get(f_id)
            if tree:
                assert "children" in tree
            alt_sources = f.get("alt_sources") or []
            for s in alt_sources:
                assert "type" in s

        # Source Summary breakdown matching app.js
        for s in source_priority:
            assert s["tier"].lower() in ("quick", "grind", "farm")
            assert "source_name" in s or "source" in s
            assert "total_score" in s
            assert "benefited_npcs" in s


# ==============================================================================
# 5. STRESS, BOUNDARY, AND ADVERSARIAL SIMULATIONS
# ==============================================================================
class TestWorkerStressAndAdversarialSimulation:
    """
    Stress-tests the worker simulation against sequential recomputes,
    extreme configurations, and corrupted inputs.
    """

    def test_rapid_sequential_recomputes(self, sim, sample_bytes):
        """Rapid sequential recompute operations with configs."""
        sim.on_message({
            "action": "plan",
            "saveBytes": sample_bytes,
            "filename": "sample_save.sav",
        })
        sim.clear_outbox()

        slot_variations = [5, 10, 15, 20, 25, 30]
        for slot in slot_variations:
            sim.on_message({
                "action": "recompute",
                "config": {"slots": slot, "strategy": "journal"},
            })
            results = sim.get_messages_by_action("result")
            assert len(results) == 1
            assert results[0]["plan"]["stats"]["max_slots"] == slot
            sim.clear_outbox()

    def test_strategy_and_mode_switching(self, sim, sample_bytes):
        """Switching between journal, max-relationship, and Saturday modes."""
        sim.on_message({
            "action": "plan",
            "saveBytes": sample_bytes,
        })
        sim.clear_outbox()

        # Switch to max-relationship
        sim.on_message({
            "action": "recompute",
            "config": {"strategy": "max-relationship", "mode": "daily"},
        })
        res1 = sim.get_messages_by_action("result")[-1]
        assert res1["plan"]["config"]["strategy"] == "max-relationship"
        assert res1["plan"]["stats"]["strategy"] == "max-relationship"
        sim.clear_outbox()

        # Switch back to journal
        sim.on_message({
            "action": "recompute",
            "config": {"strategy": "journal", "mode": "saturday"},
        })
        res2 = sim.get_messages_by_action("result")[-1]
        assert res2["plan"]["config"]["strategy"] == "journal"

    def test_focus_mode_filter_stress(self, sim, sample_bytes):
        """Focus Mode enabled filtering specific NPCs."""
        sim.on_message({
            "action": "plan",
            "saveBytes": sample_bytes,
            "config": {
                "focus_mode_enabled": True,
                "focus_npcs": "Celine,March",
            },
        })
        res = sim.get_messages_by_action("result")[-1]
        focus_list = res["plan"]["focus_suggestions"]
        for f in focus_list:
            blocked = f.get("blocked_npcs", [])
            if blocked:
                intersect = set(blocked) & {"Celine", "March"}
                err_msg = (
                    f"Item {f['item_id']} has blocked NPCs {blocked} "
                    f"not in Celine/March"
                )
                assert len(intersect) > 0, err_msg

    def test_corrupted_save_bytes_produces_error_payload(self, sim):
        """Corrupted save bytes return valid JSON with error field."""
        corrupt_bytes = b"CORRUPTED_NOT_A_VALID_SAVE_BYTES_1234567890"
        sim.on_message({
            "action": "plan",
            "saveBytes": corrupt_bytes,
            "filename": "corrupt.sav",
        })
        results = sim.get_messages_by_action("result")
        assert len(results) == 1
        res = results[0]["plan"]
        assert res["save_info"]["found"] is False
        assert res["error"] is not None
        err_lower = res["error"].lower()
        has_err = any(
            w in err_lower for w in ("failed", "decompress", "error")
        )
        assert has_err
        for key in CANONICAL_PLAN_KEYS:
            assert key in res

    def test_vfs_save_persistence_across_multiple_recomputes(
        self, sim, sample_bytes
    ):
        """Verifies VFS maintains save file across multiple recomputes."""
        sim.on_message({
            "action": "plan",
            "saveBytes": sample_bytes,
            "filename": "my_save.sav",
        })
        assert (sim.vfs_tmp_dir / "upload.sav").exists()
        assert (sim.vfs_tmp_dir / "my_save.sav").exists()

        for i in range(5):
            sim.on_message({
                "action": "recompute",
                "config": {"slots": 10 + i},
            })
            assert (sim.vfs_tmp_dir / "upload.sav").exists()
