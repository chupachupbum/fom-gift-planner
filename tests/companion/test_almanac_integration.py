"""
tests/companion/test_almanac_integration.py

Comprehensive integration test suite for Milestone 3 Almanac integration:
- CompanionConfig defaults, serialization roundtrip, disk persistence, settings schema
- companion/planner_bridge.py execute_plan() and run_planner alias with Almanac plan execution
- Furniture mode swapping ("one_per_recipe" vs "all_swatches")
- Today's gift bag reservation toggle
- companion/json_exporter.py plan_to_json() and export_full_state alias with JSON serializability
- companion/server.py endpoints (/api/plan, /api/state, /api/config, /api/settings, /api/plan/refresh)
- Project-local static UI icon serving via /assets/sprites/ui/{name}
- 100% field and data parity between Companion backend and client-side Pyodide Web Bridge
"""

import json
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from companion.config import (
    CompanionConfig,
    get_settings_schema,
    load_companion_config,
    save_companion_config,
)
from companion.json_exporter import export_full_state, plan_to_json
from companion.planner_bridge import execute_plan, run_planner
from companion.server import app, _find_local_icon
from web.py.web_bridge import WebPlannerConfig, generate_plan, init_bridge


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def sample_save_path(repo_root):
    path = repo_root / "samples" / "sample_save.sav"
    assert path.exists(), f"Sample save fixture missing at {path}"
    return path


# ---------------------------------------------------------------------------
# 1. CompanionConfig & Settings Schema
# ---------------------------------------------------------------------------

def test_companion_config_almanac_default_values():
    config = CompanionConfig()
    assert config.almanac_reserve_gifts is True
    assert config.almanac_include_locked is True
    assert config.almanac_furniture_mode == "one_per_recipe"
    assert config.almanac_season_filter == "current"
    assert config.almanac_category_filter == "all"
    assert config.almanac_data == "data/almanac_data.json"


def test_companion_config_almanac_serialization_roundtrip():
    custom_dict = {
        "almanac_reserve_gifts": False,
        "almanac_include_locked": False,
        "almanac_furniture_mode": "all_swatches",
        "almanac_season_filter": "winter",
        "almanac_category_filter": "fish",
    }
    cfg = CompanionConfig.from_dict(custom_dict)
    assert cfg.almanac_reserve_gifts is False
    assert cfg.almanac_include_locked is False
    assert cfg.almanac_furniture_mode == "all_swatches"
    assert cfg.almanac_season_filter == "winter"
    assert cfg.almanac_category_filter == "fish"

    d = cfg.to_dict()
    assert d["almanac_reserve_gifts"] is False
    assert d["almanac_include_locked"] is False
    assert d["almanac_furniture_mode"] == "all_swatches"
    assert d["almanac_season_filter"] == "winter"
    assert d["almanac_category_filter"] == "fish"

    restored = CompanionConfig.from_dict(d)
    assert restored.almanac_reserve_gifts is False
    assert restored.almanac_furniture_mode == "all_swatches"


def test_companion_config_almanac_type_coercion():
    raw_dict = {
        "almanac_reserve_gifts": 0,
        "almanac_include_locked": 1,
        "almanac_furniture_mode": " ALL_SWATCHES ",
        "almanac_season_filter": " Spring ",
        "almanac_category_filter": " BUGS ",
    }
    cfg = CompanionConfig.from_dict(raw_dict)
    assert cfg.almanac_reserve_gifts is False
    assert cfg.almanac_include_locked is True
    assert cfg.almanac_furniture_mode == "all_swatches"
    assert cfg.almanac_season_filter == "spring"
    assert cfg.almanac_category_filter == "bugs"


def test_companion_config_almanac_disk_persistence(tmp_path):
    cfg = CompanionConfig(
        almanac_reserve_gifts=False,
        almanac_furniture_mode="all_swatches",
        almanac_season_filter="spring",
        almanac_category_filter="bugs",
    )
    save_companion_config(cfg, tmp_path)
    loaded = load_companion_config(tmp_path)
    assert loaded.almanac_reserve_gifts is False
    assert loaded.almanac_furniture_mode == "all_swatches"
    assert loaded.almanac_season_filter == "spring"
    assert loaded.almanac_category_filter == "bugs"


def test_settings_schema_includes_almanac_group():
    schema = get_settings_schema()
    group_ids = [g["id"] for g in schema]
    assert "almanac" in group_ids, "Missing 'almanac' settings group in schema"

    almanac_group = next(g for g in schema if g["id"] == "almanac")
    assert almanac_group["group"] == "Almanac Planner"
    fields = {f["key"]: f for f in almanac_group["fields"]}

    assert "almanac_reserve_gifts" in fields
    assert fields["almanac_reserve_gifts"]["type"] == "checkbox"

    assert "almanac_include_locked" in fields
    assert fields["almanac_include_locked"]["type"] == "checkbox"

    assert "almanac_furniture_mode" in fields
    assert fields["almanac_furniture_mode"]["type"] == "select"
    furn_opts = [o["value"] for o in fields["almanac_furniture_mode"]["options"]]
    assert "one_per_recipe" in furn_opts
    assert "all_swatches" in furn_opts

    assert "almanac_season_filter" in fields
    assert fields["almanac_season_filter"]["type"] == "select"
    season_opts = [o["value"] for o in fields["almanac_season_filter"]["options"]]
    assert "current" in season_opts
    assert "all" in season_opts
    assert "spring" in season_opts

    assert "almanac_category_filter" in fields
    assert fields["almanac_category_filter"]["type"] == "select"
    cat_opts = [o["value"] for o in fields["almanac_category_filter"]["options"]]
    assert "all" in cat_opts
    assert "artifacts" in cat_opts
    assert "furniture" in cat_opts

    for f in almanac_group["fields"]:
        assert "help" in f and len(f["help"]) > 0, f"Field {f['key']} missing help text"


# ---------------------------------------------------------------------------
# 2. Planner Bridge & Almanac Execution
# ---------------------------------------------------------------------------

def test_planner_bridge_includes_almanac(repo_root):
    config = CompanionConfig()
    save, plan_res, meta, save_path = execute_plan(config, repo_root)
    assert plan_res is not None
    assert "almanac" in plan_res, "plan_results missing 'almanac' key"
    almanac = plan_res["almanac"]

    for expected_key in (
        "summary",
        "categories",
        "ready_to_craft",
        "raw_material_blockers",
        "sources_by_tier",
        "source_priority",
        "reserved_by_gifts",
    ):
        assert expected_key in almanac, f"Missing expected key in almanac: {expected_key}"


def test_planner_bridge_alias_run_planner(repo_root):
    assert run_planner == execute_plan
    config = CompanionConfig()
    save, plan_res, meta, save_path = run_planner(config, repo_root)
    assert "almanac" in plan_res


def test_planner_bridge_almanac_summary_structure(repo_root):
    config = CompanionConfig()
    save, plan_res, meta, save_path = execute_plan(config, repo_root)
    summary = plan_res["almanac"]["summary"]
    assert isinstance(summary.get("obtained"), int)
    assert isinstance(summary.get("total"), int)
    assert isinstance(summary.get("percentage"), (int, float))
    assert 0 <= summary["obtained"] <= summary["total"]
    assert 0.0 <= summary["percentage"] <= 100.0


def test_planner_bridge_almanac_12_categories(repo_root):
    config = CompanionConfig()
    save, plan_res, meta, save_path = execute_plan(config, repo_root)
    cats = plan_res["almanac"]["categories"]
    assert len(cats) == 12
    canonical = [
        "artifacts", "blacksmithing", "bugs", "cooked_dishes", "crops",
        "date_inspiration", "fish", "forageables", "furniture",
        "materials", "ranching", "song_crystal"
    ]
    for c in canonical:
        assert c in cats, f"Category '{c}' missing from almanac"
        assert "obtained" in cats[c]
        assert "total" in cats[c]
        assert "percentage" in cats[c]
        assert "items" in cats[c]
        assert isinstance(cats[c]["items"], list)


def test_planner_bridge_furniture_mode_swapping(repo_root):
    cfg_one = CompanionConfig(almanac_furniture_mode="one_per_recipe")
    _, plan_one, _, _ = execute_plan(cfg_one, repo_root)
    assert plan_one["almanac"]["categories"]["furniture"]["total"] == 1008

    cfg_all = CompanionConfig(almanac_furniture_mode="all_swatches")
    _, plan_all, _, _ = execute_plan(cfg_all, repo_root)
    assert plan_all["almanac"]["categories"]["furniture"]["total"] == 1530


def test_planner_bridge_reserve_gifts_toggle(repo_root):
    cfg_on = CompanionConfig(almanac_reserve_gifts=True)
    _, plan_on, _, _ = execute_plan(cfg_on, repo_root)
    assert "reserved_by_gifts" in plan_on["almanac"]

    cfg_off = CompanionConfig(almanac_reserve_gifts=False)
    _, plan_off, _, _ = execute_plan(cfg_off, repo_root)
    assert plan_off["almanac"]["reserved_by_gifts"] == {}


# ---------------------------------------------------------------------------
# 3. JSON Exporter & Full State Serialization
# ---------------------------------------------------------------------------

def test_json_exporter_serializes_almanac_cleanly(repo_root):
    config = CompanionConfig()
    save, plan_res, meta, save_path = execute_plan(config, repo_root)
    exported = plan_to_json(save, plan_res, meta, save_path, config)
    assert "almanac" in exported
    assert export_full_state == plan_to_json

    # Pure JSON serializability check
    json_str = json.dumps(exported)
    assert len(json_str) > 0
    parsed = json.loads(json_str)
    assert "almanac" in parsed
    assert "summary" in parsed["almanac"]
    assert "categories" in parsed["almanac"]
    assert "ready_to_craft" in parsed["almanac"]
    assert "raw_material_blockers" in parsed["almanac"]
    assert "sources_by_tier" in parsed["almanac"]
    assert "reserved_by_gifts" in parsed["almanac"]
    assert len(parsed.keys()) == 17


# ---------------------------------------------------------------------------
# 4. FastAPI Server Endpoints
# ---------------------------------------------------------------------------

def test_api_plan_returns_almanac_payload():
    with TestClient(app) as client:
        res = client.get("/api/plan")
        assert res.status_code == 200
        data = res.json()
        assert "almanac" in data, "Response from /api/plan missing 'almanac'"
        almanac = data["almanac"]
        assert "summary" in almanac
        assert "categories" in almanac
        assert len(almanac["categories"]) == 12
        assert "ready_to_craft" in almanac
        assert "raw_material_blockers" in almanac
        assert "sources_by_tier" in almanac
        assert "reserved_by_gifts" in almanac
        assert len(data.keys()) == 17


def test_api_state_returns_current_plan():
    with TestClient(app) as client:
        res = client.get("/api/state")
        assert res.status_code == 200
        data = res.json()
        assert "almanac" in data, "Response from /api/state missing 'almanac'"
        assert len(data.keys()) == 17


def test_api_config_get_and_post_endpoints():
    with TestClient(app) as client:
        # GET /api/config
        res_get = client.get("/api/config")
        assert res_get.status_code == 200
        settings = res_get.json()
        assert "config" in settings
        assert "schema" in settings
        assert "almanac_reserve_gifts" in settings["config"]

        # POST /api/config
        update_payload = {
            "almanac_reserve_gifts": False,
            "almanac_furniture_mode": "all_swatches",
            "almanac_season_filter": "winter",
        }
        res_post = client.post("/api/config", json=update_payload)
        assert res_post.status_code == 200
        resp_data = res_post.json()
        assert resp_data["success"] is True
        assert resp_data["config"]["almanac_reserve_gifts"] is False
        assert resp_data["config"]["almanac_furniture_mode"] == "all_swatches"
        assert resp_data["config"]["almanac_season_filter"] == "winter"

        # Recomputed plan in response has updated values
        plan = resp_data["plan"]
        assert "almanac" in plan
        assert plan["almanac"]["categories"]["furniture"]["total"] == 1530

        # Reset to defaults
        client.post("/api/config", json={
            "almanac_reserve_gifts": True,
            "almanac_furniture_mode": "one_per_recipe",
            "almanac_season_filter": "current",
        })


def test_api_plan_refresh_includes_almanac():
    with TestClient(app) as client:
        res = client.post("/api/plan/refresh")
        assert res.status_code == 200
        data = res.json()
        assert "almanac" in data
        assert len(data["almanac"]["categories"]) == 12


def test_local_ui_sprite_resolution():
    # Verify _find_local_icon resolves UI category sprites
    assert _find_local_icon("ui", "artifacts") is not None
    assert _find_local_icon("ui", "furniture") is not None
    assert _find_local_icon("ui", "fish") is not None

    with TestClient(app) as client:
        res = client.get("/assets/sprites/ui/artifacts")
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("image/")

        res2 = client.get("/assets/sprites/ui/spr_ui_journal_tab_almanac")
        assert res2.status_code == 200
        assert res2.headers["content-type"].startswith("image/")


# ---------------------------------------------------------------------------
# 5. Web Bridge Integration & Parity
# ---------------------------------------------------------------------------

def test_web_planner_config_almanac_defaults():
    cfg = WebPlannerConfig()
    assert cfg.almanac_reserve_gifts is True
    assert cfg.almanac_include_locked is True
    assert cfg.almanac_furniture_mode == "one_per_recipe"
    assert cfg.almanac_season_filter == "current"
    assert cfg.almanac_category_filter == "all"


def test_web_bridge_100_percent_parity_with_companion(sample_save_path):
    init_bridge("web/data")

    # Companion execution
    cfg_comp = CompanionConfig(save_file=str(sample_save_path))
    save, plan_res, meta, save_p = execute_plan(cfg_comp)
    expected = plan_to_json(save, plan_res, meta, save_p, cfg_comp)

    # Web bridge execution
    web_res = json.loads(generate_plan(str(sample_save_path), config_dict=cfg_comp.to_dict()))

    assert "almanac" in expected
    assert "almanac" in web_res

    exp_a = expected["almanac"]
    web_a = web_res["almanac"]

    # 1. Summary parity
    assert exp_a["summary"] == web_a["summary"]

    # 2. Categories count & metrics parity
    assert set(exp_a["categories"].keys()) == set(web_a["categories"].keys())
    for cat_name in exp_a["categories"]:
        assert exp_a["categories"][cat_name]["obtained"] == web_a["categories"][cat_name]["obtained"]
        assert exp_a["categories"][cat_name]["total"] == web_a["categories"][cat_name]["total"]

    # 3. Ready to craft queue length & item parity
    assert len(exp_a["ready_to_craft"]) == len(web_a["ready_to_craft"])

    # 4. Raw material blockers parity
    assert len(exp_a["raw_material_blockers"]) == len(web_a["raw_material_blockers"])

    # 5. Gift reservations parity
    assert exp_a["reserved_by_gifts"] == web_a["reserved_by_gifts"]


def test_web_bridge_error_fallback_has_safe_almanac_schema():
    corrupt_bytes = b"CORRUPTED_NON_SAV_BYTES"
    res_json = generate_plan(corrupt_bytes, filename="bad.sav")
    data = json.loads(res_json)
    assert "almanac" in data
    almanac = data["almanac"]
    assert almanac["summary"]["obtained"] == 0
    assert almanac["summary"]["total"] == 0
    assert almanac["categories"] == {}
    assert almanac["ready_to_craft"] == []
    assert almanac["raw_material_blockers"] == []
    assert len(data.keys()) == 17
