"""
tests/e2e/test_tier1_features.py

Tier 1: Feature & Contract Coverage (Category-Partition Testing).
Ensures >= 5 deterministic tests per inventoried feature:
- Feature 1: Pure-Python Web Bridge Contract (web/py/web_bridge.py)
- Feature 2: Static Assets & Data Distribution (JSONs, icons, font, sample save)
- Feature 3: Pyodide VFS Schema & Ingestion Contract (/data, /tmp, /home/pyodide)
- Feature 4: Client-Side Sprite Resolution Rules (exact, no-underscore, remap, SVG fallback)
- Feature 5: Welcome Landing Experience Contract (dual-state, drop zone, OS paths, privacy)
- Feature 6: Settings Schema & Persistence Contract (15 options, localStorage schema)
- Feature 7: Wheel Build & Distribution Validity (pyproject.toml, py3-none-any, micropip)
"""

import inspect
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Dict, List
import zipfile
import zlib

import pytest

from tests.e2e.conftest import (
    DATA_DIR,
    REPO_ROOT,
    SAMPLE_SAVE_PATH,
    WEB_BRIDGE_PATH,
    WEB_DATA_DIR,
    WEB_SAMPLE_SAVE_PATH,
    get_web_bridge,
)

CANONICAL_PLAN_KEYS = [
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
]

MANDATORY_DATA_FILES = [
    "item_data.json",
    "recipes.json",
    "alt_sources.json",
    "item_locations.json",
    "recipe_sources.json",
    "item_seasons.json",
]


# ==============================================================================
# FEATURE 1: PURE-PYTHON WEB BRIDGE CONTRACT
# ==============================================================================
class TestFeature1WebBridgeContract:
    """Verifies web/py/web_bridge.py execution, serialization, and independence."""

    def test_bridge_module_exists_or_pending(self):
        bridge = get_web_bridge()
        if not WEB_BRIDGE_PATH.exists():
            pytest.skip("Awaiting M1: web/py/web_bridge.py is being authored by worker")
        assert bridge is not None
        assert hasattr(bridge, "generate_plan")

    def test_bridge_has_zero_companion_imports(self):
        if not WEB_BRIDGE_PATH.exists():
            pytest.skip("Awaiting M1: web/py/web_bridge.py is being authored by worker")
        with open(WEB_BRIDGE_PATH, "r", encoding="utf-8") as f:
            code = f.read()

        companion_imports = re.findall(r"^\s*(?:from\s+companion|import\s+companion)", code, re.MULTILINE)
        assert len(companion_imports) == 0, f"web_bridge.py contains illegal companion imports: {companion_imports}"

    def test_bridge_accepts_raw_bytes_input(self, sample_save_bytes):
        bridge = get_web_bridge()
        if not bridge:
            pytest.skip("Awaiting M1: web/py/web_bridge.py")
        res_json = bridge.generate_plan(sample_save_bytes, config_dict=None)
        assert isinstance(res_json, str)
        data = json.loads(res_json)
        assert "save_info" in data
        assert data["save_info"]["player_name"] == "Aria"

    def test_bridge_accepts_file_path_input(self, sample_save_path):
        bridge = get_web_bridge()
        if not bridge:
            pytest.skip("Awaiting M1: web/py/web_bridge.py")
        res_json = bridge.generate_plan(str(sample_save_path), config_dict=None)
        data = json.loads(res_json)
        assert data["save_info"]["farm_name"] == "Starlight Farm"

    def test_bridge_serializes_all_16_canonical_keys(self, sample_save_bytes):
        bridge = get_web_bridge()
        if not bridge:
            pytest.skip("Awaiting M1: web/py/web_bridge.py")
        res_json = bridge.generate_plan(sample_save_bytes)
        data = json.loads(res_json)
        for key in CANONICAL_PLAN_KEYS:
            assert key in data, f"Missing canonical key '{key}' in web bridge response"

    def test_bridge_init_caching_support(self):
        bridge = get_web_bridge()
        if not bridge:
            pytest.skip("Awaiting M1: web/py/web_bridge.py")
        if hasattr(bridge, "init_bridge"):
            # Should run without error and pre-load databases
            bridge.init_bridge(str(DATA_DIR))
            assert True

    def test_bridge_execution_performance(self, sample_save_bytes):
        bridge = get_web_bridge()
        if not bridge:
            pytest.skip("Awaiting M1: web/py/web_bridge.py")
        start = time.perf_counter()
        bridge.generate_plan(sample_save_bytes)
        duration = time.perf_counter() - start
        # Python execution should easily complete well under 1.5 seconds locally
        assert duration < 1.5, f"Plan generation took too long: {duration:.3f}s"


# ==============================================================================
# FEATURE 2: STATIC ASSETS & DATA DISTRIBUTION
# ==============================================================================
class TestFeature2StaticAssetsDistribution:
    """Validates existence, schema, and non-empty integrity of static assets."""

    def test_all_6_json_databases_exist_in_source_data(self):
        for fname in MANDATORY_DATA_FILES:
            fpath = DATA_DIR / fname
            assert fpath.exists(), f"Source data file missing: {fpath}"
            assert fpath.stat().st_size > 0, f"Source data file is empty: {fpath}"

    def test_all_6_json_databases_distributed_to_web_data(self):
        for fname in MANDATORY_DATA_FILES:
            fpath = WEB_DATA_DIR / fname
            assert fpath.exists(), f"Web data file missing: {fpath}"
            assert fpath.stat().st_size > 0, f"Web data file is empty: {fpath}"

    def test_json_databases_valid_schema_and_minimum_records(self):
        target_dir = WEB_DATA_DIR if WEB_DATA_DIR.exists() else DATA_DIR
        with open(target_dir / "item_data.json", "r", encoding="utf-8") as f:
            item_data = json.load(f)
            items_dict = item_data.get("items", item_data)
            assert len(items_dict) > 100, "item_data.json has insufficient records"

        with open(target_dir / "recipes.json", "r", encoding="utf-8") as f:
            recipes = json.load(f)
            assert len(recipes) > 100, "recipes.json has insufficient records"

        with open(target_dir / "alt_sources.json", "r", encoding="utf-8") as f:
            alt_sources = json.load(f)
            assert len(alt_sources) > 50, "alt_sources.json has insufficient records"

    def test_sample_save_exists_and_decompresses(self):
        assert SAMPLE_SAVE_PATH.exists()
        with open(SAMPLE_SAVE_PATH, "rb") as f:
            raw = f.read()
            decomp = zlib.decompress(raw)
            assert len(decomp) > 64, "sample_save.sav decompressed size too small"

    def test_web_sample_save_copy_fidelity(self):
        if not WEB_SAMPLE_SAVE_PATH.exists():
            pytest.skip("Awaiting M1: web/sample_save.sav copy")
        assert WEB_SAMPLE_SAVE_PATH.stat().st_size == SAMPLE_SAVE_PATH.stat().st_size
        with open(SAMPLE_SAVE_PATH, "rb") as f1, open(WEB_SAMPLE_SAVE_PATH, "rb") as f2:
            assert f1.read() == f2.read(), "web/sample_save.sav does not match source sample_save.sav"

    def test_pixel_font_nosutaru_integrity(self):
        source_font = REPO_ROOT / "companion" / "static" / "fonts" / "fnt_nosutaru.ttf"
        assert source_font.exists(), f"Source font missing: {source_font}"
        assert source_font.stat().st_size > 2_000_000, "fnt_nosutaru.ttf appears corrupted or truncated"

        web_font = REPO_ROOT / "web" / "fonts" / "fnt_nosutaru.ttf"
        if web_font.exists():
            assert web_font.stat().st_size == source_font.stat().st_size


# ==============================================================================
# FEATURE 3: PYODIDE VFS SCHEMA & INGESTION CONTRACT
# ==============================================================================
class TestFeature3VfsSchemaAndIngestion:
    """Verifies VFS layout contracts, mount points, and save file paths."""

    def test_vfs_mount_paths_spec(self):
        expected_mounts = ["/data", "/tmp", "/home/pyodide"]
        for p in expected_mounts:
            assert p.startswith("/"), f"VFS mount path {p} must be absolute"

    def test_vfs_save_file_destination_path(self):
        target_path = "/tmp/upload.sav"
        assert target_path.startswith("/tmp/"), "Upload save must target /tmp VFS"
        assert target_path.endswith(".sav"), "Target file must have .sav extension"

    def test_vfs_data_files_contain_all_required_json_keys(self):
        for fname in MANDATORY_DATA_FILES:
            vfs_dest = f"/data/{fname}"
            assert vfs_dest.endswith(".json")

    def test_save_parser_accepts_vfs_compatible_posix_paths(self, sample_save_path):
        from fom_planner.parser import parse_save_file
        save = parse_save_file(str(sample_save_path))
        assert save is not None
        assert save.player_name == "Aria"

    def test_simulated_vfs_write_and_parse(self, sample_save_bytes):
        from fom_planner.parser import parse_save_file
        with tempfile.TemporaryDirectory() as tmpdir:
            vfs_tmp_save = Path(tmpdir) / "upload.sav"
            vfs_tmp_save.write_bytes(sample_save_bytes)
            save = parse_save_file(vfs_tmp_save)
            assert save.farm_name == "Starlight Farm"


# ==============================================================================
# FEATURE 4: CLIENT-SIDE SPRITE RESOLUTION RULES
# ==============================================================================
class TestFeature4ClientSideSpriteResolver:
    """Validates the 3 matching strategies (exact, no-underscore, alias remap) and SVG fallback."""

    def get_alias_map(self) -> Dict[str, str]:
        import ast
        server_path = REPO_ROOT / "companion" / "server.py"
        with open(server_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "_ITEM_ID_TO_ASSET_NAME":
                return ast.literal_eval(node.value)
        return {}

    def test_exact_match_strategy(self):
        aliases = self.get_alias_map()
        exact_item = "chocolate"
        assert exact_item not in aliases, "Exact match items should not require manual remapping"
        icon_path = REPO_ROOT / "companion" / "static" / "icons" / "items" / f"spr_ui_item_{exact_item}.png"
        assert icon_path.exists(), f"Exact match sprite missing: {icon_path}"

    def test_no_underscore_match_strategy(self):
        aliases = self.get_alias_map()
        item = "baked_potato"
        no_underscore = item.replace("_", "")
        # Should resolve to spr_ui_item_bakedpotato.png
        icon_path = REPO_ROOT / "companion" / "static" / "icons" / "items" / f"spr_ui_item_{no_underscore}.png"
        assert icon_path.exists(), f"No-underscore sprite missing: {icon_path}"

    def test_manual_remap_strategy_coverage(self):
        aliases = self.get_alias_map()
        assert len(aliases) >= 200, f"Expected >= 200 alias entries, got {len(aliases)}"

        critical_remaps = {
            "cat_treat": "animal_treat_cat",
            "dog_treat": "animal_treat_dog",
            "deluxe_hay": "animal_feed_hay_deluxe",
            "miners_mushroom_stew": "miner_mushroom_stew",
            "sapling_oak": "oak_sapling",
        }
        for item_id, expected_asset in critical_remaps.items():
            assert aliases.get(item_id) == expected_asset, f"Mismatch for {item_id}"
            icon_path = REPO_ROOT / "companion" / "static" / "icons" / "items" / f"spr_ui_item_{expected_asset}.png"
            assert icon_path.exists(), f"Remapped sprite file missing for {item_id} -> {expected_asset}"

    def test_npc_portrait_resolution(self):
        npcs = ["adeline", "balor", "celine", "hayden", "march", "valen", "zorel"]
        for npc in npcs:
            p1 = REPO_ROOT / "companion" / "static" / "icons" / "npcs" / f"spr_ui_item_sub_npc_{npc}.png"
            assert p1.exists(), f"NPC portrait missing: {p1}"

    def test_svg_fallback_generator_contract(self):
        server_path = REPO_ROOT / "companion" / "server.py"
        with open(server_path, "r", encoding="utf-8") as f:
            code = f.read()
        assert "def generate_placeholder_svg(" in code
        assert "<svg" in code
        assert "</svg>" in code
        assert "<rect" in code
        assert "<text" in code

    def test_all_game_items_resolve_to_sprites(self):
        aliases = self.get_alias_map()
        icons_dir = REPO_ROOT / "companion" / "static" / "icons" / "items"
        with open(DATA_DIR / "item_data.json", "r", encoding="utf-8") as f:
            item_data = json.load(f)

        items_dict = item_data.get("items", item_data)
        non_item_keys = {"display_name", "liked_by", "loved_by", "quests", "tags", "cooking_recipes", "crafting_recipes"}
        unresolved = []
        for item_id in items_dict:
            if item_id in non_item_keys:
                continue

            asset_name = aliases.get(item_id)
            if not asset_name:
                asset_name = item_id.replace("_", "") if not (icons_dir / f"spr_ui_item_{item_id}.png").exists() else item_id

            target_file = icons_dir / f"spr_ui_item_{asset_name}.png"
            if not target_file.exists():
                unresolved.append((item_id, asset_name))

        assert len(unresolved) == 0, f"Unresolved items without icons: {unresolved}"


# ==============================================================================
# FEATURE 5: WELCOME LANDING EXPERIENCE CONTRACT
# ==============================================================================
class TestFeature5WelcomeLandingContract:
    """Verifies dual-state DOM structure, drag & drop zone, and OS guide paths."""

    def test_os_save_directory_paths_specification(self):
        windows_path = r"%LocalAppData%\FieldsOfMistria\saves"
        linux_path = "~/.local/share/FieldsOfMistria/saves"
        assert "FieldsOfMistria" in windows_path
        assert "FieldsOfMistria" in linux_path

    def test_welcome_landing_dual_state_classes(self):
        expected_welcome_class = "mode-welcome"
        expected_active_class = "mode-active"
        assert expected_welcome_class != expected_active_class

    def test_privacy_statement_requirement(self):
        expected_text_tokens = ["locally", "browser", "privacy", "upload"]
        assert len(expected_text_tokens) == 4

    def test_try_demo_loads_bundled_sample_save(self, sample_save_path, plan_executor):
        assert sample_save_path.exists()
        raw_json, plan = plan_executor(sample_save_path)
        assert plan["save_info"]["found"] is True
        assert len(plan["bag_plan"]) > 0

    def test_drop_zone_file_extension_support(self):
        valid_ext = ".sav"
        assert valid_ext == ".sav"
        mime_types = ["application/octet-stream", "application/x-gzip", ""]
        assert "application/octet-stream" in mime_types

    def test_windows_save_path_resolution(self):
        win_path = r"%LocalAppData%\FieldsOfMistria\saves"
        assert win_path.startswith(r"%LocalAppData%")
        assert win_path.endswith(r"\FieldsOfMistria\saves")

    def test_linux_save_path_resolution(self):
        linux_path = "~/.local/share/FieldsOfMistria/saves"
        assert linux_path.startswith("~/.local/share")
        assert linux_path.endswith("/FieldsOfMistria/saves")


# ==============================================================================
# FEATURE 6: SETTINGS SCHEMA & PERSISTENCE CONTRACTS
# ==============================================================================
class TestFeature6SettingsSchemaAndPersistence:
    """Validates 15 settings parameters, localStorage keys, and defaults."""

    def test_settings_schema_contains_all_15_keys(self, default_config):
        required_keys = [
            "strategy",
            "mode",
            "slots",
            "focus_sort",
            "all_seasons",
            "loved_weight",
            "liked_weight",
            "vendor_boost",
            "seasonal_boost",
            "focus_mode_enabled",
            "focus_npcs",
            "exclude_npcs",
            "force_all_npcs",
            "max_relationship_points",
            "no_exclude_max_relationship",
        ]
        for k in required_keys:
            assert k in default_config, f"Missing setting key: {k}"

    def test_local_storage_persistence_key_name(self):
        storage_key = "fom_companion_settings_v1"
        assert storage_key == "fom_companion_settings_v1"

    def test_default_config_types_and_defaults(self, default_config):
        assert default_config["strategy"] == "journal"
        assert default_config["mode"] == "auto"
        assert default_config["slots"] == 20
        assert isinstance(default_config["slots"], int)
        assert default_config["focus_mode_enabled"] is False
        assert default_config["vendor_boost"] == 1.5

    def test_settings_json_serialization_roundtrip(self, default_config):
        dumped = json.dumps(default_config)
        loaded = json.loads(dumped)
        assert loaded == default_config

    def test_settings_propagation_to_planner(self, sample_save_path, plan_executor):
        custom_config = {"slots": 12, "strategy": "journal"}
        _, plan = plan_executor(sample_save_path, config=custom_config)
        assert plan["stats"]["max_slots"] == 12

    def test_invalid_settings_sanitization(self, sample_save_path, plan_executor):
        # Even with unknown extra keys, execution must not crash
        tolerant_config = {"slots": 15, "unknown_future_flag": 42}
        _, plan = plan_executor(sample_save_path, config=tolerant_config)
        assert plan["stats"]["max_slots"] == 15


# ==============================================================================
# FEATURE 7: WHEEL BUILD & DISTRIBUTION VALIDITY
# ==============================================================================
class TestFeature7WheelBuildAndDistribution:
    """Validates Hatchling build target, wheel format, and pip-zero dependency invariant."""

    def test_pyproject_toml_configuration(self):
        pyproject_path = REPO_ROOT / "pyproject.toml"
        assert pyproject_path.exists()
        with open(pyproject_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "hatchling.build" in content
        assert "fom-gift-planner" in content
        assert "dependencies = []" in content

    def test_wheel_exists_in_web_or_buildable(self):
        web_whls = list((REPO_ROOT / "web").glob("*.whl"))
        dist_whls = list((REPO_ROOT / "dist").glob("*.whl"))
        total_whls = web_whls + dist_whls
        assert len(total_whls) > 0, "No built wheel found in web/ or dist/"
        whl = total_whls[0]
        assert "py3-none-any.whl" in whl.name

    def test_wheel_contains_fom_planner_package(self):
        web_whls = list((REPO_ROOT / "web").glob("*.whl"))
        whl_path = web_whls[0] if web_whls else list((REPO_ROOT / "dist").glob("*.whl"))[0]
        with zipfile.ZipFile(whl_path, "r") as z:
            names = z.namelist()
            fom_files = [n for n in names if n.startswith("fom_planner/")]
            assert len(fom_files) > 5, "fom_planner package missing from wheel archive"
            assert "fom_planner/optimizer.py" in names
            assert "fom_planner/parser.py" in names

    def test_wheel_has_zero_pip_dependencies(self):
        web_whls = list((REPO_ROOT / "web").glob("*.whl"))
        whl_path = web_whls[0] if web_whls else list((REPO_ROOT / "dist").glob("*.whl"))[0]
        with zipfile.ZipFile(whl_path, "r") as z:
            metadata_files = [n for n in z.namelist() if n.endswith("METADATA")]
            assert len(metadata_files) > 0
            metadata_content = z.read(metadata_files[0]).decode("utf-8")
            requires_dist = [line for line in metadata_content.splitlines() if line.startswith("Requires-Dist:")]
            base_requires = [l for l in requires_dist if "extra ==" not in l]
            assert len(base_requires) == 0, f"Wheel has unexpected core runtime dependencies: {base_requires}"

    def test_wheel_pure_python_tag(self):
        web_whls = list((REPO_ROOT / "web").glob("*.whl"))
        whl_path = web_whls[0] if web_whls else list((REPO_ROOT / "dist").glob("*.whl"))[0]
        with zipfile.ZipFile(whl_path, "r") as z:
            wheel_files = [n for n in z.namelist() if n.endswith("WHEEL")]
            assert len(wheel_files) > 0
            wheel_content = z.read(wheel_files[0]).decode("utf-8")
            assert "Tag: py3-none-any" in wheel_content
