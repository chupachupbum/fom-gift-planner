"""
tests/test_challenger_parity_fuzz.py

Empirical challenger stress-test and parity fuzzer for Milestone 1:
- Wheel archive inspection, metadata verification, and module importability.
- Randomized parity fuzzing comparing web_bridge.generate_plan() with
  companion.json_exporter.plan_to_json() across journal and max-relationship strategies,
  random NPC exclusions, focus mode combinations, weights, vendor/seasonal boosts, and saves.
- Strict recursive type and value equality verification across all canonical keys and nested structures.
- Adversarial edge cases: corrupted saves, extreme config parameters, missing saves.
"""

from datetime import datetime
import glob
import importlib
import json
import math
import os
from pathlib import Path
import random
import sys
import zipfile
import pytest

from companion.config import CompanionConfig
from companion.json_exporter import plan_to_json
from companion.planner_bridge import execute_plan
from web.py import web_bridge
from web.py.web_bridge import WebPlannerConfig, generate_plan, init_bridge

CANONICAL_KEYS = (
    "generated_at",
    "save_info",
    "in_game_date",
    "config",
    "stats",
    "completed_npcs_details",
    "incomplete_npcs_details",
    "unobtained_recipes",
    "recipe_stats",
    "infused_items",
    "bag_plan",
    "focus_suggestions",
    "focus_trees",
    "source_priority",
    "npc_progress",
    "error",
)

ALL_NPCS = [
    "adeline", "balor", "caldarus", "celine", "darcy", "dell", "dozy", "eiland",
    "elsie", "errol", "hayden", "hemlock", "henrietta", "holt", "josephine",
    "juniper", "landen", "louis", "luc", "maple", "march", "merri", "nora",
    "olric", "reina", "ryis", "seridia", "stillwell", "taliferro", "terithia",
    "valen", "vera", "wheedle", "zorel",
]


@pytest.fixture(scope="module", autouse=True)
def setup_bridge_data():
    """Ensure static databases are loaded."""
    init_bridge("web/data")


def get_available_saves():
    """Gathers all valid sample and uploaded save files in repo."""
    saves = []
    candidates = (
        glob.glob("samples/*.sav")
        + glob.glob("data/uploads/*.sav")
        + glob.glob("*.sav")
    )
    for p in candidates:
        path = Path(p).resolve()
        if path.exists() and path.is_file():
            saves.append(path)
    return sorted(saves, key=lambda x: str(x))


def strict_recursive_diff(path: str, obj1: any, obj2: any, ignore_keys=None) -> list:
    """
    Recursively compares two objects for exact type and value equality.
    Returns list of mismatch descriptions.
    """
    if ignore_keys is None:
        ignore_keys = {"generated_at"}

    # Handle None
    if obj1 is None or obj2 is None:
        if obj1 is not obj2:
            return [f"Nullness mismatch at {path}: {obj1!r} vs {obj2!r}"]
        return []

    # Handle float vs int equivalence if numbers are mathematically equal
    if isinstance(obj1, (int, float)) and isinstance(obj2, (int, float)):
        # Check if one is bool (bool is subclass of int in Python)
        if isinstance(obj1, bool) or isinstance(obj2, bool):
            if type(obj1) is not type(obj2):
                return [f"Type mismatch at {path} (bool vs num): {type(obj1)} vs {type(obj2)}"]
            if obj1 != obj2:
                return [f"Bool value mismatch at {path}: {obj1} != {obj2}"]
            return []
        if not math.isclose(float(obj1), float(obj2), abs_tol=1e-6, rel_tol=1e-6):
            return [f"Numeric value mismatch at {path}: {obj1} != {obj2}"]
        return []

    # Strict type equality
    if type(obj1) is not type(obj2):
        return [f"Type mismatch at {path}: expected {type(obj1).__name__}, got {type(obj2).__name__}"]

    # Dict comparison
    if isinstance(obj1, dict):
        diffs = []
        keys1 = set(obj1.keys()) - ignore_keys
        keys2 = set(obj2.keys()) - ignore_keys
        if keys1 != keys2:
            extra_in_1 = keys1 - keys2
            extra_in_2 = keys2 - keys1
            diffs.append(f"Dict keys mismatch at {path}: extra in expected={extra_in_1}, extra in actual={extra_in_2}")
        common_keys = sorted(keys1.intersection(keys2))
        for k in common_keys:
            diffs.extend(strict_recursive_diff(f"{path}.{k}", obj1[k], obj2[k], ignore_keys))
        return diffs

    # List comparison
    if isinstance(obj1, list):
        if len(obj1) != len(obj2):
            return [f"List length mismatch at {path}: expected {len(obj1)}, got {len(obj2)}"]
        diffs = []
        for i, (item1, item2) in enumerate(zip(obj1, obj2)):
            diffs.extend(strict_recursive_diff(f"{path}[{i}]", item1, item2, ignore_keys))
        return diffs

    # Primitive values (str, bool, etc.)
    if obj1 != obj2:
        return [f"Value mismatch at {path}: {obj1!r} != {obj2!r}"]

    return []


# =========================================================================
# 1. WHEEL INTEGRITY & IMPORTABILITY VERIFICATION
# =========================================================================

def test_wheel_archive_structure_and_integrity():
    """Inspects the wheel zip archive, checks files, dist-info, and metadata."""
    wheel_path = Path("web/fom_gift_planner-1.2.0-py3-none-any.whl").resolve()
    assert wheel_path.exists(), f"Wheel file missing at {wheel_path}"
    assert wheel_path.stat().st_size > 100_000, f"Wheel suspiciously small: {wheel_path.stat().st_size} bytes"

    with zipfile.ZipFile(wheel_path, "r") as z:
        names = z.namelist()
        assert len(names) > 0

        # Verify fom_planner package is present
        fom_files = [n for n in names if n.startswith("fom_planner/")]
        assert len(fom_files) >= 8, f"Expected >= 8 files in fom_planner/, found {len(fom_files)}"

        expected_modules = {
            "fom_planner/__init__.py",
            "fom_planner/constants.py",
            "fom_planner/crafting.py",
            "fom_planner/data_loader.py",
            "fom_planner/models.py",
            "fom_planner/optimizer.py",
            "fom_planner/parser.py",
            "fom_planner/rankings.py",
        }
        for mod in expected_modules:
            assert mod in names, f"Required module {mod} missing from wheel"

        # Verify dist-info
        dist_info = [n for n in names if n.startswith("fom_gift_planner-1.2.0.dist-info/")]
        assert len(dist_info) >= 3, f"dist-info files missing: {dist_info}"

        metadata_file = "fom_gift_planner-1.2.0.dist-info/METADATA"
        assert metadata_file in names
        metadata_text = z.read(metadata_file).decode("utf-8")
        assert "Name: fom-gift-planner" in metadata_text
        assert "Version: 1.2.0" in metadata_text
        assert "Requires-Python: >=3.10" in metadata_text

        wheel_meta = "fom_gift_planner-1.2.0.dist-info/WHEEL"
        assert wheel_meta in names
        wheel_meta_text = z.read(wheel_meta).decode("utf-8")
        assert "Wheel-Version: 1.0" in wheel_meta_text
        assert "Tag: py3-none-any" in wheel_meta_text


def test_wheel_importability_on_clean_path(monkeypatch):
    """Verifies that all fom_planner modules can be imported directly from the wheel on sys.path."""
    wheel_path = str(Path("web/fom_gift_planner-1.2.0-py3-none-any.whl").resolve())

    # Temporarily prepend wheel to sys.path
    monkeypatch.syspath_prepend(wheel_path)

    modules_to_test = [
        "fom_planner",
        "fom_planner.constants",
        "fom_planner.crafting",
        "fom_planner.data_loader",
        "fom_planner.models",
        "fom_planner.optimizer",
        "fom_planner.parser",
        "fom_planner.rankings",
    ]

    for mod_name in modules_to_test:
        mod = importlib.import_module(mod_name)
        assert mod is not None, f"Failed to import {mod_name} from wheel"


# =========================================================================
# 2. RANDOMIZED PARITY FUZZING
# =========================================================================

@pytest.mark.parametrize("fuzz_seed", range(30))
def test_parity_fuzz_journal_strategy(fuzz_seed):
    """
    Parity fuzzer for Journal strategy:
    Generates random combinations of:
    - Save file selection
    - focus_mode_enabled (True / False)
    - focus_npcs (random subset of 34 NPCs)
    - exclude_npcs (random subset of 34 NPCs)
    - loved_weight (1..10)
    - liked_weight (0..5)
    - vendor_boost (0.5..3.0)
    - seasonal_boost (0.0..3.5)
    - slots (1..30)
    - mode ("auto", "saturday", "weekday", "market-only", "all")
    - focus_sort ("impact", "deficit", "quick-wins")
    - all_seasons (True / False)
    - date_override (None or festival/saturday/season string)
    """
    rng = random.Random(42_000 + fuzz_seed)

    saves = get_available_saves()
    assert len(saves) > 0
    save_path = rng.choice(saves)

    # Pick random subset of NPCs
    num_focus = rng.randint(0, 5)
    focus_npcs_sample = rng.sample(ALL_NPCS, num_focus) if num_focus > 0 else []
    focus_mode = rng.choice([True, False])

    num_exclude = rng.randint(0, 5)
    remaining_for_exclude = [n for n in ALL_NPCS if n not in focus_npcs_sample]
    exclude_npcs_sample = rng.sample(remaining_for_exclude, num_exclude) if num_exclude > 0 else []

    date_overrides = [
        None,
        "",
        "saturday",
        "winter 10",
        "summer 28",
        "spring 17",
        "fall 10",
        "spring 8",
        "autumn 14",
    ]

    config_kwargs = {
        "save_file": str(save_path),
        "strategy": "journal",
        "mode": rng.choice(["auto", "saturday", "weekday", "market-only", "all"]),
        "slots": rng.choice([1, 5, 10, 15, 20, 24, 30]),
        "loved_weight": rng.choice([1, 2, 3, 5, 8, 10]),
        "liked_weight": rng.choice([0, 1, 2, 3, 5]),
        "vendor_boost": rng.choice([0.5, 1.0, 1.5, 2.0, 2.5, 3.0]),
        "seasonal_boost": rng.choice([0.0, 1.0, 1.5, 2.0, 3.0]),
        "focus_sort": rng.choice(["impact", "deficit", "quick-wins"]),
        "all_seasons": rng.choice([True, False]),
        "focus_mode_enabled": focus_mode,
        "focus_npcs": ",".join(focus_npcs_sample),
        "exclude_npcs": ",".join(exclude_npcs_sample),
        "date_override": rng.choice(date_overrides),
    }

    # 1. Run companion reference
    cfg_comp = CompanionConfig(**config_kwargs)
    save_data, plan_res, metadata, resolved_path = execute_plan(cfg_comp)
    expected = plan_to_json(save_data, plan_res, metadata, resolved_path, cfg_comp)

    # 2. Run web_bridge
    web_res_str = generate_plan(str(save_path), config_dict=cfg_comp.to_dict())
    actual = json.loads(web_res_str)

    # 3. Assert full recursive equality
    diffs = strict_recursive_diff("root", expected, actual, ignore_keys={"generated_at"})
    assert not diffs, (
        f"Fuzz test seed={fuzz_seed} failed with {len(diffs)} diffs:\n"
        + "\n".join(diffs[:15])
        + f"\nConfig was: {config_kwargs}"
    )


@pytest.mark.parametrize("fuzz_seed", range(30))
def test_parity_fuzz_max_relationship_strategy(fuzz_seed):
    """
    Parity fuzzer for Max-Relationship strategy:
    Tests max-relationship point capping, exclusion toggles, slots, and filters.
    """
    rng = random.Random(88_000 + fuzz_seed)

    saves = get_available_saves()
    save_path = rng.choice(saves)

    num_focus = rng.randint(0, 4)
    focus_npcs_sample = rng.sample(ALL_NPCS, num_focus) if num_focus > 0 else []

    num_exclude = rng.randint(0, 4)
    exclude_npcs_sample = rng.sample(ALL_NPCS, num_exclude) if num_exclude > 0 else []

    date_overrides = [None, "saturday", "winter 10", "spring 1", "summer 15"]
    max_pts = rng.choice([None, 200.0, 500.0, 1000.0, 1755.0])

    config_kwargs = {
        "save_file": str(save_path),
        "strategy": "max-relationship",
        "mode": rng.choice(["auto", "saturday", "all"]),
        "slots": rng.choice([2, 8, 15, 20, 28]),
        "vendor_boost": rng.choice([1.0, 1.5, 2.5]),
        "seasonal_boost": rng.choice([1.0, 2.0]),
        "focus_sort": rng.choice(["impact", "deficit"]),
        "all_seasons": rng.choice([True, False]),
        "focus_mode_enabled": rng.choice([True, False]),
        "focus_npcs": ",".join(focus_npcs_sample),
        "exclude_npcs": ",".join(exclude_npcs_sample),
        "date_override": rng.choice(date_overrides),
        "max_relationship_points": max_pts,
        "no_exclude_max_relationship": rng.choice([True, False]),
        "force_all_npcs": rng.choice([True, False]),
    }

    cfg_comp = CompanionConfig(**config_kwargs)
    save_data, plan_res, metadata, resolved_path = execute_plan(cfg_comp)
    expected = plan_to_json(save_data, plan_res, metadata, resolved_path, cfg_comp)

    web_res_str = generate_plan(str(save_path), config_dict=cfg_comp.to_dict())
    actual = json.loads(web_res_str)

    diffs = strict_recursive_diff("root", expected, actual, ignore_keys={"generated_at"})
    assert not diffs, (
        f"Max-relationship fuzz seed={fuzz_seed} failed with {len(diffs)} diffs:\n"
        + "\n".join(diffs[:15])
        + f"\nConfig was: {config_kwargs}"
    )


# =========================================================================
# 3. SCHEMA TYPES & VALUE INVARIANTS VERIFICATION
# =========================================================================

def test_schema_types_and_invariants():
    """Examines every single key in the output dict for precise schema types and invariants."""
    sample_path = Path("samples/sample_save.sav").resolve()
    result_str = generate_plan(str(sample_path))
    data = json.loads(result_str)

    # 1. Top-level keys
    assert set(data.keys()) == set(CANONICAL_KEYS)

    # 2. save_info invariants
    si = data["save_info"]
    assert isinstance(si["found"], bool) and si["found"] is True
    assert isinstance(si["path"], str)
    assert isinstance(si["filename"], str) and si["filename"] == "sample_save.sav"
    assert isinstance(si["player_name"], str) and len(si["player_name"]) > 0
    assert isinstance(si["farm_name"], str) and len(si["farm_name"]) > 0

    # 3. in_game_date invariants
    igd = data["in_game_date"]
    assert isinstance(igd["year"], int) and igd["year"] >= 1
    assert isinstance(igd["season"], str) and igd["season"] in ("Spring", "Summer", "Fall", "Autumn", "Winter")
    assert isinstance(igd["day"], int) and 1 <= igd["day"] <= 28
    assert isinstance(igd["day_of_week"], str)
    assert isinstance(igd["is_saturday"], bool)
    assert isinstance(igd["is_animal_festival"], bool)
    assert isinstance(igd["formatted"], str)
    assert isinstance(igd["is_overridden"], bool)
    assert isinstance(igd["date_override"], str)

    # 4. stats invariants
    stats = data["stats"]
    assert isinstance(stats["strategy"], str)
    assert isinstance(stats["slots_used"], int) and stats["slots_used"] >= 0
    assert isinstance(stats["max_slots"], int) and stats["max_slots"] > 0
    assert isinstance(stats["total_npcs_count"], int) and stats["total_npcs_count"] == 34
    assert isinstance(stats["completed_npcs_count"], int)
    assert isinstance(stats["incomplete_npcs_count"], int)
    assert stats["completed_npcs_count"] + stats["incomplete_npcs_count"] == 34
    assert isinstance(stats["overall_gift_progress_pct"], (int, float))

    # 5. bag_plan card invariants
    for slot_item in data["bag_plan"]:
        assert isinstance(slot_item["slot"], int) and slot_item["slot"] >= 1
        assert isinstance(slot_item["item_id"], str) and slot_item["item_id"]
        assert isinstance(slot_item["item_name"], str) and slot_item["item_name"]
        assert isinstance(slot_item["quantity"], int) and slot_item["quantity"] >= 1
        assert isinstance(slot_item["status"], str) and slot_item["status"] in ("HAVE", "CRAFT", "UNAVAILABLE", "BUY", "FORAGE", "FISH", "MINE", "FARM")
        assert isinstance(slot_item["status_badge"], str)
        assert isinstance(slot_item["availability_tier"], int)
        assert isinstance(slot_item["is_infused"], bool)
        assert isinstance(slot_item["recipients"], list)
        assert slot_item["sprite_url"].startswith("/assets/sprites/items/")
        for r in slot_item["recipients"]:
            assert isinstance(r["npc_id"], str)
            assert isinstance(r["name"], str)
            assert r["preference"] in ("LOVE", "LIKE")
            assert isinstance(r["points"], (int, float))

    # 6. focus_suggestions invariants
    for f in data["focus_suggestions"]:
        assert isinstance(f["item_id"], str)
        assert isinstance(f["item_name"], str)
        assert isinstance(f["impact_score"], (int, float))
        assert isinstance(f["deficit"], int)
        assert isinstance(f["count_needed"], int)
        assert isinstance(f["location"], str)
        assert isinstance(f["seasons"], list)
        assert isinstance(f["is_seasonal"], bool)
        assert isinstance(f["blocked_npcs"], list)
        assert isinstance(f["alt_sources"], list)
        assert f["sprite_url"].startswith("/assets/sprites/items/")

    # 7. npc_progress invariants
    assert len(data["npc_progress"]) == 34
    for nid, p in data["npc_progress"].items():
        assert isinstance(p["npc_id"], str)
        assert isinstance(p["name"], str)
        assert isinstance(p["is_completed"], bool)
        assert isinstance(p["hearts"], (int, float))
        assert isinstance(p["pct_total_done"], (int, float))
        assert isinstance(p["remaining_loved"], list)
        assert isinstance(p["remaining_liked"], list)
        assert p["portrait_url"].startswith("/assets/sprites/npcs/")


# =========================================================================
# 4. RAW BYTES VS PATH CONSISTENCY
# =========================================================================

def test_raw_bytes_vs_file_path_consistency():
    """Tests that passing raw bytes vs passing file path produces identical plan results."""
    sample_path = Path("samples/sample_save.sav").resolve()
    raw_bytes = sample_path.read_bytes()

    cfg = {"strategy": "journal", "slots": 15, "vendor_boost": 2.0}

    res_path = json.loads(generate_plan(str(sample_path), config_dict=cfg))
    res_bytes = json.loads(generate_plan(raw_bytes, config_dict=cfg, filename="sample_save.sav"))

    # Only save_info.path differs (/tmp/sample_save.sav vs repo/samples/sample_save.sav)
    diffs = strict_recursive_diff(
        "root",
        res_path,
        res_bytes,
        ignore_keys={"generated_at", "path", "modified_at"},
    )
    assert not diffs, f"Bytes vs Path mismatches: {diffs}"


# =========================================================================
# 5. ADVERSARIAL EDGE CASES & STRESS HARNESS
# =========================================================================

def test_adversarial_corrupted_saves():
    """Verifies graceful handling of non-zlib and corrupted bytes."""
    corrupted_cases = [
        b"",  # Empty
        b"x",  # 1 byte
        b"not a valid save file at all",
        b"\x78\x9c\x03\x00\x00\x00\x00\x01",  # Empty zlib stream
        os.urandom(1024),  # Random bytes
    ]

    for i, bad_bytes in enumerate(corrupted_cases):
        out_str = generate_plan(bad_bytes, filename=f"corrupted_{i}.sav")
        data = json.loads(out_str)
        assert set(data.keys()) == set(CANONICAL_KEYS), f"Failed on case {i}"
        assert data["error"] is not None
        assert data["save_info"]["found"] is False
        assert data["bag_plan"] == []
        assert data["focus_suggestions"] == []


def test_adversarial_extreme_configurations():
    """Tests extreme, boundary, and unexpected configuration values."""
    sample_path = Path("samples/sample_save.sav").resolve()

    extreme_configs = [
        # Extreme numbers
        {"slots": 9999, "loved_weight": 100, "liked_weight": -10, "vendor_boost": 99.9},
        # Zero slots
        {"slots": 0},
        # Negative slots
        {"slots": -5},
        # Unknown strategy fallback
        {"strategy": "unknown_future_strategy"},
        # Unknown mode fallback
        {"mode": "hyperdrive"},
        # All NPCs excluded
        {"exclude_npcs": ",".join(ALL_NPCS)},
        # Non-existent NPC names
        {"exclude_npcs": "batman,superman,goku", "focus_npcs": "ironman,thor"},
        # Malformed date overrides
        {"date_override": "super festival 99"},
        {"date_override": "{"},
        {"date_override": "{\"invalid\": 123}"},
        # Empty string values
        {"focus_npcs": "", "exclude_npcs": "", "date_override": ""},
    ]

    for i, extreme_cfg in enumerate(extreme_configs):
        out_str = generate_plan(str(sample_path), config_dict=extreme_cfg)
        assert isinstance(out_str, str)
        data = json.loads(out_str)
        assert set(data.keys()) == set(CANONICAL_KEYS), f"Keys missing on extreme config {i}"
        assert data["error"] is None or isinstance(data["error"], str)


def test_adversarial_overlap_and_boundary_parity():
    """Stress tests boundary configs and overlapping exclude/focus sets with strict parity."""
    sample_path = Path("samples/sample_save.sav").resolve()

    boundary_cases = [
        # 1. Overlapping exclude and focus NPCs
        {
            "focus_mode_enabled": True,
            "focus_npcs": "adeline,balor,celine",
            "exclude_npcs": "adeline,balor",
        },
        # 2. Extreme vendor and seasonal boosts
        {
            "vendor_boost": 0.0,
            "seasonal_boost": 0.0,
            "loved_weight": 1,
            "liked_weight": 0,
        },
        {
            "vendor_boost": 5.0,
            "seasonal_boost": 5.0,
            "loved_weight": 10,
            "liked_weight": 5,
        },
        # 3. Minimum slots
        {"slots": 1},
        # 4. JSON date overrides
        {"date_override": '{"season": "winter", "day": 10, "year": 2}'},
        {"date_override": '{"season": "autumn", "day": 25}'},
        # 5. Relationship point boundaries
        {"strategy": "max-relationship", "max_relationship_points": 10.0},
        {"strategy": "max-relationship", "max_relationship_points": 5000.0, "no_exclude_max_relationship": True},
        # 6. Force all NPCs under restricted modes
        {"mode": "market-only", "force_all_npcs": True},
        {"mode": "weekday", "force_all_npcs": True},
    ]

    for idx, case in enumerate(boundary_cases):
        cfg_comp = CompanionConfig(save_file=str(sample_path), **case)
        save_data, plan_res, metadata, resolved_path = execute_plan(cfg_comp)
        expected = plan_to_json(save_data, plan_res, metadata, resolved_path, cfg_comp)

        web_res = json.loads(generate_plan(str(sample_path), config_dict=cfg_comp.to_dict()))
        diffs = strict_recursive_diff(f"boundary_case_{idx}", expected, web_res, ignore_keys={"generated_at"})
        assert not diffs, f"Boundary case {idx} failed with {len(diffs)} diffs:\n" + "\n".join(diffs[:10])


def test_all_available_saves_parity():
    """Runs parity checks across every unique save file found in repo."""
    saves = get_available_saves()
    assert len(saves) >= 4

    for save_file in saves:
        for strat in ("journal", "max-relationship"):
            cfg = CompanionConfig(save_file=str(save_file), strategy=strat, slots=18)
            save_data, plan_res, metadata, resolved_path = execute_plan(cfg)
            expected = plan_to_json(save_data, plan_res, metadata, resolved_path, cfg)

            web_res = json.loads(generate_plan(str(save_file), config_dict=cfg.to_dict()))
            diffs = strict_recursive_diff(
                f"save_{save_file.name}_{strat}",
                expected,
                web_res,
                ignore_keys={"generated_at"},
            )
            assert not diffs, f"Save {save_file.name} failed under {strat}:\n" + "\n".join(diffs[:10])

