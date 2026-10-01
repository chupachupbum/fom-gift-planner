"""
tests/test_web_bridge.py

Unit and parity tests for web/py/web_bridge.py.
Verifies canonical schema compliance, bytes/path ingestion, static database pre-caching,
and 100% field parity against companion/json_exporter.py:plan_to_json().
"""

import json
from pathlib import Path
import pytest

from companion.config import CompanionConfig
from companion.json_exporter import plan_to_json
from companion.planner_bridge import execute_plan
from web.py import web_bridge
from web.py.web_bridge import WebPlannerConfig, generate_plan, init_bridge, run_plan_from_vfs

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


@pytest.fixture(scope="module", autouse=True)
def setup_bridge():
    """Ensure static databases in web/data are pre-cached for all tests."""
    init_bridge("web/data")


@pytest.fixture
def sample_save_path():
    """Returns absolute path to bundled demo save fixture."""
    path = Path(__file__).resolve().parents[2] / "samples" / "sample_save.sav"
    assert path.exists(), f"Sample save fixture missing at {path}"
    return path


def test_web_planner_config_defaults():
    """Verify WebPlannerConfig has correct default values matching CompanionConfig."""
    cfg = WebPlannerConfig()
    comp_cfg = CompanionConfig()

    assert cfg.strategy == comp_cfg.strategy == "journal"
    assert cfg.mode == comp_cfg.mode == "auto"
    assert cfg.slots == comp_cfg.slots == 20
    assert cfg.loved_weight == comp_cfg.loved_weight == 3
    assert cfg.liked_weight == comp_cfg.liked_weight == 1
    assert cfg.vendor_boost == comp_cfg.vendor_boost == 1.5
    assert cfg.seasonal_boost == comp_cfg.seasonal_boost == 2.0
    assert cfg.focus_sort == comp_cfg.focus_sort == "impact"
    assert cfg.all_seasons is False
    assert cfg.focus_mode_enabled is False


def test_web_planner_config_serialization():
    """Verify WebPlannerConfig to_dict and from_dict roundtrip."""
    original_dict = {
        "strategy": "max-relationship",
        "mode": "saturday",
        "slots": 15,
        "loved_weight": 5,
        "liked_weight": 2,
        "vendor_boost": 2.5,
        "seasonal_boost": 3.0,
        "focus_npcs": ["adeline", "balor"],
        "exclude_npcs": ["celine"],
        "focus_mode_enabled": True,
        "all_seasons": True,
    }
    cfg = WebPlannerConfig(original_dict)
    assert cfg.strategy == "max-relationship"
    assert cfg.mode == "saturday"
    assert cfg.slots == 15
    assert cfg.focus_npcs == "adeline,balor"
    assert cfg.exclude_npcs == "celine"
    assert cfg.focus_mode_enabled is True
    assert cfg.all_seasons is True

    serialized = cfg.to_dict()
    assert isinstance(serialized, dict)
    assert serialized["strategy"] == "max-relationship"
    assert serialized["slots"] == 15

    roundtrip = WebPlannerConfig.from_dict(serialized)
    assert roundtrip.strategy == cfg.strategy
    assert roundtrip.slots == cfg.slots
    assert roundtrip.focus_npcs == cfg.focus_npcs


def test_init_bridge_caches_databases():
    """Verify init_bridge loads and caches all 6 databases in memory."""
    init_bridge("web/data")
    assert web_bridge._CACHED_DATA is not None
    assert "all_recipes" in web_bridge._CACHED_DATA
    assert len(web_bridge._CACHED_DATA["all_recipes"]) > 0
    assert "item_locations" in web_bridge._CACHED_DATA
    assert "recipe_sources" in web_bridge._CACHED_DATA
    assert "item_seasons" in web_bridge._CACHED_DATA
    assert "alt_sources" in web_bridge._CACHED_DATA
    assert "npc_definitions" in web_bridge._CACHED_DATA
    assert len(web_bridge._CACHED_DATA["npc_definitions"]) >= 34
    assert "metadata" in web_bridge._CACHED_DATA
    assert len(web_bridge._CACHED_DATA["metadata"]) >= 400


def test_generate_plan_canonical_keys(sample_save_path):
    """Verify generate_plan returns all 16 canonical JSON keys."""
    result_json = generate_plan(str(sample_save_path))
    data = json.loads(result_json)

    assert isinstance(data, dict)
    assert len(data.keys()) == 16
    for key in CANONICAL_KEYS:
        assert key in data, f"Missing canonical key: '{key}' in plan output"

    assert data["error"] is None
    assert data["save_info"]["found"] is True
    assert data["save_info"]["player_name"] is not None
    assert data["save_info"]["farm_name"] is not None
    assert isinstance(data["bag_plan"], list)
    assert isinstance(data["focus_suggestions"], list)
    assert isinstance(data["npc_progress"], dict)
    assert isinstance(data["completed_npcs_details"], list)
    assert isinstance(data["incomplete_npcs_details"], list)
    assert isinstance(data["unobtained_recipes"], list)
    assert isinstance(data["source_priority"], list)


def test_generate_plan_bytes_input(sample_save_path):
    """Verify generate_plan accepts raw bytes and filename parameter."""
    save_bytes = sample_save_path.read_bytes()
    result_json = generate_plan(save_bytes, filename="uploaded_test.sav")
    data = json.loads(result_json)

    assert data["error"] is None
    assert data["save_info"]["found"] is True
    assert data["save_info"]["filename"] == "uploaded_test.sav"
    assert len(data.keys()) == 16
    assert len(data["bag_plan"]) > 0


def test_generate_plan_config_variations(sample_save_path):
    """Verify generate_plan respects different configuration inputs."""
    # Test JSON string config
    cfg_str = json.dumps({"slots": 10, "strategy": "journal", "focus_sort": "deficit"})
    res1 = json.loads(generate_plan(str(sample_save_path), config_dict=cfg_str))
    assert res1["config"]["slots"] == 10
    assert res1["stats"]["max_slots"] == 10
    assert res1["config"]["focus_sort"] == "deficit"

    # Test dict config
    cfg_dict = {"slots": 7, "mode": "all", "all_seasons": True}
    res2 = json.loads(generate_plan(str(sample_save_path), config_dict=cfg_dict))
    assert res2["config"]["slots"] == 7
    assert res2["stats"]["max_slots"] == 7
    assert res2["config"]["mode"] == "all"
    assert res2["config"]["all_seasons"] is True

    # Test WebPlannerConfig instance
    cfg_obj = WebPlannerConfig(slots=12, loved_weight=5)
    res3 = json.loads(generate_plan(str(sample_save_path), config_dict=cfg_obj))
    assert res3["config"]["slots"] == 12
    assert res3["stats"]["max_slots"] == 12
    assert res3["config"]["loved_weight"] == 5


def test_run_plan_from_vfs(sample_save_path):
    """Verify run_plan_from_vfs behaves identically to generate_plan."""
    vfs_res = json.loads(run_plan_from_vfs(str(sample_save_path)))
    gen_res = json.loads(generate_plan(str(sample_save_path)))

    assert vfs_res["save_info"]["filename"] == gen_res["save_info"]["filename"]
    assert len(vfs_res["bag_plan"]) == len(gen_res["bag_plan"])
    assert vfs_res["stats"] == gen_res["stats"]


def test_parity_journal_strategy(sample_save_path):
    """Compare web_bridge against companion/json_exporter.py for 100% field parity (journal strategy)."""
    cfg_comp = CompanionConfig(save_file=str(sample_save_path))
    save, plan_res, metadata, save_path = execute_plan(cfg_comp)
    expected = plan_to_json(save, plan_res, metadata, save_path, cfg_comp)

    web_output = json.loads(generate_plan(str(sample_save_path), config_dict=cfg_comp.to_dict()))

    # Ignore generated_at timestamp differences
    assert set(expected.keys()) == set(web_output.keys())
    for key in expected:
        if key == "generated_at":
            continue
        assert expected[key] == web_output[key], f"Parity mismatch on key '{key}'"


def test_parity_max_relationship_strategy(sample_save_path):
    """Compare web_bridge against companion for 100% field parity with max-relationship strategy."""
    cfg_comp = CompanionConfig(save_file=str(sample_save_path), strategy="max-relationship", slots=15)
    save, plan_res, metadata, save_path = execute_plan(cfg_comp)
    expected = plan_to_json(save, plan_res, metadata, save_path, cfg_comp)

    web_output = json.loads(generate_plan(str(sample_save_path), config_dict=cfg_comp.to_dict()))

    assert set(expected.keys()) == set(web_output.keys())
    for key in expected:
        if key == "generated_at":
            continue
        assert expected[key] == web_output[key], f"Parity mismatch on key '{key}' with max-relationship"


def test_parity_date_override(sample_save_path):
    """Compare web_bridge against companion for 100% field parity with date overrides."""
    for override in ("winter 10", "saturday", "fall 20", "year 2 summer 6"):
        cfg_comp = CompanionConfig(save_file=str(sample_save_path), date_override=override)
        save, plan_res, metadata, save_path = execute_plan(cfg_comp)
        expected = plan_to_json(save, plan_res, metadata, save_path, cfg_comp)

        web_output = json.loads(generate_plan(str(sample_save_path), config_dict=cfg_comp.to_dict()))

        for key in expected:
            if key == "generated_at":
                continue
            assert expected[key] == web_output[key], f"Parity mismatch on '{key}' for date_override '{override}'"


def test_parity_exclusions_and_focus(sample_save_path):
    """Compare web_bridge against companion for 100% field parity with NPC exclusions."""
    cfg_comp = CompanionConfig(
        save_file=str(sample_save_path),
        exclude_npcs="adeline,balor",
        focus_npcs="celine,darcy",
        focus_mode_enabled=True,
    )
    save, plan_res, metadata, save_path = execute_plan(cfg_comp)
    expected = plan_to_json(save, plan_res, metadata, save_path, cfg_comp)

    web_output = json.loads(generate_plan(str(sample_save_path), config_dict=cfg_comp.to_dict()))

    for key in expected:
        if key == "generated_at":
            continue
        assert expected[key] == web_output[key], f"Parity mismatch on '{key}' with exclusions/focus"


def test_error_handling_corrupted_save():
    """Verify generate_plan gracefully returns JSON error payload without raising uncaught exception."""
    corrupted_bytes = b"CORRUPTED_NON_ZLIB_DATA_12345"
    result_json = generate_plan(corrupted_bytes, filename="bad_save.sav")
    data = json.loads(result_json)

    assert isinstance(data, dict)
    assert len(data.keys()) == 16
    assert data["error"] is not None
    assert "Failed to zlib-decompress" in data["error"] or "error" in data["error"].lower()
    assert data["save_info"]["found"] is False
    assert data["save_info"]["filename"] == "bad_save.sav"
    assert data["bag_plan"] == []
    assert data["focus_suggestions"] == []


def test_date_override_without_save():
    """Verify date override functions even when no save file is provided (dummy save synthesis)."""
    cfg = {"date_override": "spring 10", "mode": "auto"}
    result_json = generate_plan(None, config_dict=cfg)
    data = json.loads(result_json)

    assert data["error"] is None
    assert data["in_game_date"]["season"] == "Spring"
    assert data["in_game_date"]["day"] == 10
    assert data["in_game_date"]["is_overridden"] is True
    assert len(data["bag_plan"]) >= 0
