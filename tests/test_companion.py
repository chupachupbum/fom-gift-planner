"""
tests/test_companion.py

Comprehensive test suite for the Fields of Mistria Live Companion App.
Tests config management, planner bridge, JSON exporter, watcher, retry logic,
and FastAPI REST/SSE endpoints.
"""

import json
from pathlib import Path
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from companion.config import (
    CompanionConfig,
    get_settings_schema,
    load_companion_config,
    save_companion_config,
)
from companion.json_exporter import plan_to_json
from companion.planner_bridge import execute_plan, read_save_with_retry, resolve_path
from companion.server import app, state
from companion.watcher import SaveFileEventHandler, resolve_watch_directories


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parent.parent


def test_config_serialization(tmp_path):
    config = CompanionConfig(
        strategy="max-relationship",
        mode="saturday",
        slots=15,
        loved_weight=4,
        exclude_npcs="balor, eiland",
    )
    d = config.to_dict()
    assert d["strategy"] == "max-relationship"
    assert d["mode"] == "saturday"
    assert d["slots"] == 15
    assert d["loved_weight"] == 4
    assert d["exclude_npcs"] == "balor, eiland"

    restored = CompanionConfig.from_dict(d)
    assert restored.strategy == "max-relationship"
    assert restored.slots == 15

    # Test file save and load
    save_companion_config(restored, tmp_path)
    loaded = load_companion_config(tmp_path)
    assert loaded.strategy == "max-relationship"
    assert loaded.slots == 15


def test_settings_schema_structure():
    schema = get_settings_schema()
    assert isinstance(schema, list)
    assert len(schema) >= 4
    group_ids = [g["id"] for g in schema]
    assert "planning" in group_ids
    assert "scoring" in group_ids
    assert "npc_filters" in group_ids
    assert "paths" in group_ids


def test_planner_bridge_execution(repo_root):
    config = CompanionConfig(
        strategy="journal",
        mode="auto",
        slots=20,
    )
    save, plan_res, meta, save_path = execute_plan(config, repo_root)
    assert plan_res is not None
    assert "bag_plan" in plan_res
    assert "focus_suggestions" in plan_res
    assert "overall_stats" in plan_res
    assert len(plan_res["bag_plan"]) > 0


def test_planner_bridge_max_relationship(repo_root):
    config = CompanionConfig(
        strategy="max-relationship",
        mode="saturday",
        slots=12,
    )
    save, plan_res, meta, save_path = execute_plan(config, repo_root)
    assert plan_res is not None
    assert "bag_plan" in plan_res
    assert len(plan_res["bag_plan"]) <= 12


def test_json_exporter_is_serializable(repo_root):
    config = CompanionConfig(strategy="journal", slots=20)
    save, plan_res, meta, save_path = execute_plan(config, repo_root)
    data = plan_to_json(save, plan_res, meta, save_path, config)

    # Must serialize to pure JSON string with no TypeError
    json_str = json.dumps(data)
    assert len(json_str) > 0
    parsed = json.loads(json_str)

    assert "bag_plan" in parsed
    assert "focus_suggestions" in parsed
    assert "in_game_date" in parsed
    assert "save_info" in parsed
    assert "stats" in parsed

    for item in parsed["bag_plan"]:
        assert "item_id" in item
        assert "item_name" in item
        assert "status_badge" in item
        assert "recipients" in item
        assert "crafting_steps" in item
        assert "crafting_summary" in item

    # Ensure craftable items have non-empty structured crafting_steps with ingredients
    craft_items = [it for it in parsed["bag_plan"] if it["status"] == "CRAFT"]
    assert len(craft_items) > 0
    for it in craft_items:
        assert len(it["crafting_steps"]) > 0
        step0 = it["crafting_steps"][0]
        assert "product_name" in step0
        assert len(step0["product_name"]) > 0
        assert "ingredients" in step0
        assert len(step0["ingredients"]) > 0



def test_watcher_event_handler_filtering():
    callback = MagicMock()
    handler = SaveFileEventHandler(on_save_changed=callback, debounce_seconds=0.05)

    # Non .sav file should be ignored
    event_txt = MagicMock(is_directory=False, src_path="/saves/notes.txt")
    handler.on_created(event_txt)
    time.sleep(0.1)
    callback.assert_not_called()

    # Case-insensitive .sav, .SAV should trigger
    event_sav = MagicMock(is_directory=False, src_path="/saves/game-123.sav")
    handler.on_created(event_sav)
    time.sleep(0.1)
    assert callback.call_count == 1

    callback.reset_mock()
    event_caps = MagicMock(is_directory=False, src_path="/saves/GAME-999.SAV")
    handler.on_modified(event_caps)
    time.sleep(0.1)
    assert callback.call_count == 1

    # on_moved (rename) to .sav
    callback.reset_mock()
    event_moved = MagicMock(is_directory=False, src_path="/saves/temp.tmp", dest_path="/saves/game-final.sav")
    handler.on_moved(event_moved)
    time.sleep(0.1)
    assert callback.call_count == 1


def test_read_save_with_retry_permission_error():
    # Simulate 2 initial PermissionErrors followed by successful read
    mock_save = MagicMock()
    attempts = [0]

    def faulty_parse(path):
        attempts[0] += 1
        if attempts[0] < 3:
            raise PermissionError("File locked by process")
        return mock_save

    with patch("companion.planner_bridge.parse_save_file", side_effect=faulty_parse):
        res = read_save_with_retry(Path("dummy.sav"), max_attempts=5)
        assert res == mock_save
        assert attempts[0] == 3


def test_fastapi_endpoints():
    with TestClient(app) as client:
        # 1. Root HTML
        res_root = client.get("/")
        assert res_root.status_code == 200
        assert "Fields of Mistria" in res_root.text

        # 2. Plan API
        res_plan = client.get("/api/plan")
        assert res_plan.status_code == 200
        plan_data = res_plan.json()
        assert "bag_plan" in plan_data
        assert "in_game_date" in plan_data

        # 3. Settings API
        res_settings = client.get("/api/settings")
        assert res_settings.status_code == 200
        settings_data = res_settings.json()
        assert "config" in settings_data
        assert "schema" in settings_data

        # 4. Settings Update (POST)
        res_update = client.post("/api/settings", json={"slots": 16, "strategy": "max-relationship"})
        assert res_update.status_code == 200
        updated = res_update.json()
        assert updated["success"] is True
        assert updated["config"]["slots"] == 16
        assert updated["config"]["strategy"] == "max-relationship"

        # 5. Plan Refresh (POST)
        res_refresh = client.post("/api/plan/refresh")
        assert res_refresh.status_code == 200

        # 6. Sprite endpoint with SVG fallback
        res_sprite = client.get("/assets/sprites/items/apple")
        assert res_sprite.status_code == 200
        assert "image/svg+xml" in res_sprite.headers.get("content-type", "")
        assert "<svg" in res_sprite.text
