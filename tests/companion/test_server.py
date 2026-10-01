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
    return Path(__file__).resolve().parents[2]


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
    assert len(schema) == 2
    group_ids = [g["id"] for g in schema]
    assert "planning" in group_ids
    assert "focus_suggestions" in group_ids

    planning_group = next(g for g in schema if g["id"] == "planning")
    planning_fields = {f["key"]: f for f in planning_group["fields"]}
    assert "strategy" in planning_fields
    assert "mode" in planning_fields
    assert "slots" in planning_fields
    assert planning_fields["slots"]["max"] == 30
    assert "date_override" in planning_fields
    assert "exclude_npcs" in planning_fields
    assert planning_fields["exclude_npcs"]["type"] == "exclude_npc_picker"
    assert "force_all_npcs" in planning_fields
    assert "no_exclude_max_relationship" in planning_fields
    assert "loved_weight" in planning_fields
    assert "liked_weight" in planning_fields
    assert "vendor_boost" in planning_fields
    assert "max_relationship_points" not in planning_fields

    focus_group = next(g for g in schema if g["id"] == "focus_suggestions")
    focus_fields = {f["key"]: f for f in focus_group["fields"]}
    assert "focus_mode_enabled" in focus_fields
    assert "focus_npcs" in focus_fields
    assert "focus_sort" in focus_fields
    assert "all_seasons" in focus_fields
    assert "seasonal_boost" in focus_fields

    # Verify every configurable parameter has help text for tooltips
    for group in schema:
        for f in group["fields"]:
            assert "help" in f and len(f["help"]) > 0, f"Field {f['key']} must have help text"


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


def test_planner_bridge_focus_suggestions_consistency_between_strategies(repo_root):
    cfg_journal = CompanionConfig(strategy="journal", mode="auto", slots=20)
    _, plan_j, _, _ = execute_plan(cfg_journal, repo_root)

    cfg_max = CompanionConfig(strategy="max-relationship", mode="auto", slots=20)
    _, plan_m, _, _ = execute_plan(cfg_max, repo_root)

    assert "focus_suggestions" in plan_j
    assert "focus_suggestions" in plan_m
    # Both strategies must produce consistent focus suggestions (up to 20, > 5 when deficits exist)
    assert len(plan_m["focus_suggestions"]) == len(plan_j["focus_suggestions"])
    assert len(plan_m["focus_suggestions"]) > 5


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


def test_fastapi_endpoints(repo_root):
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
        res_sprite = client.get("/assets/sprites/items/nonexistent_test_item")
        assert res_sprite.status_code == 200
        assert "image/svg+xml" in res_sprite.headers.get("content-type", "")
        assert "<svg" in res_sprite.text

        # Real sprite returns PNG
        res_apple = client.get("/assets/sprites/items/apple")
        assert res_apple.status_code == 200
        assert "image/png" in res_apple.headers.get("content-type", "")

        res_bead = client.get("/assets/sprites/items/animal_currency")
        assert res_bead.status_code == 200
        assert "image/png" in res_bead.headers.get("content-type", "")

        res_bead_id = client.get("/assets/sprites/items/shiny_bead")
        assert res_bead_id.status_code == 200
        assert "image/png" in res_bead_id.headers.get("content-type", "")

        res_adeline = client.get("/assets/sprites/npcs/adeline")
        assert res_adeline.status_code == 200
        assert "image/png" in res_adeline.headers.get("content-type", "")

        # 7. Upload Save File (.sav) — Valid
        sample_save = repo_root / "samples" / "sample_save.sav"
        with open(sample_save, "rb") as f:
            res_upload = client.post(
                "/api/save/upload",
                files={"file": ("custom_test.sav", f, "application/octet-stream")},
            )
        assert res_upload.status_code == 200
        up_data = res_upload.json()
        assert up_data["success"] is True
        assert up_data["filename"] == "custom_test.sav"
        assert "custom_test.sav" in up_data["config"]["save_file"]
        assert "bag_plan" in up_data["plan"]

        # 8. Upload Save File — Invalid extension
        res_bad_ext = client.post(
            "/api/save/upload",
            files={"file": ("invalid.txt", b"not a save", "text/plain")},
        )
        assert res_bad_ext.status_code == 400
        assert "Fields of Mistria save file" in res_bad_ext.json()["detail"]

        # 9. Upload Save File — Corrupted content
        res_corrupt = client.post(
            "/api/save/upload",
            files={"file": ("corrupt.sav", b"short", "application/octet-stream")},
        )
        assert res_corrupt.status_code == 400

        # 10. Reset save_file to auto-detect
        res_reset = client.post("/api/settings", json={"save_file": ""})
        assert res_reset.status_code == 200
        reset_data = res_reset.json()
        assert reset_data["config"]["save_file"] is None

        # 11. Discovered saves list endpoint
        res_saves = client.get("/api/saves")
        assert res_saves.status_code == 200
        saves_data = res_saves.json()
        assert "saves" in saves_data
        assert isinstance(saves_data["saves"], list)
        assert saves_data["is_auto"] is True

        # 12. Static Assets for Focus Suggestion Blocked NPCs Expand/Collapse
        res_js = client.get("/static/app.js")
        assert res_js.status_code == 200
        assert "renderBlockedNpcs" in res_js.text
        assert "toggleBlockedNpcs" in res_js.text
        assert "npc-expand-btn" in res_js.text
        assert "npc-collapse-btn" in res_js.text
        assert "and +" in res_js.text
        assert "Collapse" in res_js.text

        res_css = client.get("/static/style.css")
        assert res_css.status_code == 200
        assert ".blocked-npcs-wrapper" in res_css.text
        assert ".blocked-npcs-extra" in res_css.text
        assert ".npc-toggle-btn" in res_css.text
        assert ".npc-collapse-btn" in res_css.text


def test_focus_suggestions_blocked_npcs_structure():
    """Verify that companion app.js correctly truncates >3 NPCs and provides expand/collapse buttons."""
    static_app_js = Path(__file__).resolve().parents[2] / "companion" / "static" / "app.js"
    assert static_app_js.exists()
    content = static_app_js.read_text(encoding="utf-8")

    # Verify key tokens and logic exist
    assert "function renderBlockedNpcs(blockedNpcs)" in content
    assert "validNpcs.length <= 3" in content
    assert "validNpcs.slice(0, 3)" in content
    assert "extraCount = validNpcs.length - 3" in content
    assert "and +${extraCount} more" in content
    assert ">Collapse<" in content or "Collapse</button>" in content
    assert "is-expanded" in content

    static_style_css = Path(__file__).resolve().parents[2] / "companion" / "static" / "style.css"
    assert static_style_css.exists()
    css_content = static_style_css.read_text(encoding="utf-8")
    assert ".is-expanded" in css_content


def test_focus_suggestions_sample_save_has_items_exceeding_three_npcs(repo_root):
    """Verify that sample save contains focus items with >3 blocked NPCs where expand button triggers."""
    cfg = CompanionConfig(strategy="journal", slots=20)
    save, res, meta, path = execute_plan(cfg, repo_root)
    data = plan_to_json(save, res, meta, path, cfg)

    items_over_3 = [f for f in data.get("focus_suggestions", []) if len(f.get("blocked_npcs", [])) > 3]
    assert len(items_over_3) > 0
    feather = next(f for f in items_over_3 if f["item_id"] == "golden_duck_feather")
    assert len(feather["blocked_npcs"]) == 4
    assert feather["blocked_npcs"] == ["Landen", "Louis", "Merri", "Wheedle"]


def test_parameter_help_and_beta_marker_and_exclude_npc_picker():
    """Verify that companion app.js and style.css contain the beta badge, help icons, and exclude NPC picker."""
    static_app_js = Path(__file__).resolve().parents[2] / "companion" / "static" / "app.js"
    assert static_app_js.exists()
    js_content = static_app_js.read_text(encoding="utf-8")

    # Acquisition Source Priority is collapsed by default and has BETA badge
    assert '<details class="source-tier-accordion tier-${tierKey}">' in js_content
    assert '<details class="source-tier-accordion tier-${tierKey}" open>' not in js_content
    assert '<span class="badge-beta">BETA</span>' in js_content

    # Help icon rendering helper exists and is used
    assert "function renderHelpIcon" in js_content
    assert "param-help-btn" in js_content
    assert "param-help-tooltip" in js_content

    # Exclude NPC picker logic exists
    assert 'field.type === "exclude_npc_picker"' in js_content
    assert 'exclude-npc-cb' in js_content
    assert 'excludeNpcSelectAll' in js_content
    assert 'excludeNpcDeselectAll' in js_content
    assert 'excludeNpcCounterBadge' in js_content

    static_style_css = Path(__file__).resolve().parents[2] / "companion" / "static" / "style.css"
    assert static_style_css.exists()
    css_content = static_style_css.read_text(encoding="utf-8")

    # CSS styles for beta badge, tooltips, and exclude picker
    assert ".badge-beta" in css_content
    assert ".param-help-wrap" in css_content
    assert ".param-help-btn" in css_content
    assert ".param-help-tooltip" in css_content
    assert ".exclude-npc-picker-group" in css_content


def test_mistria_gift_planner_brand_and_disclaimer(repo_root):
    """Verify name is 'Mistria Gift Planner', disclaimer matches specification, and Buy Me a Coffee link is present."""
    index_html = (repo_root / "companion" / "static" / "index.html").read_text(encoding="utf-8")

    # Name check
    assert "<title>Mistria Gift Planner</title>" in index_html
    assert "Mistria Gift Planner</h1>" in index_html
    assert "Mistria Gift Planner — Handcrafted by fans, for fans" not in index_html
    assert app.title == "Mistria Gift Planner"

    # Buy Me a Coffee link check next to disclaimer
    assert "https://buymeacoffee.com/chupachupbum" in index_html
    assert "Buy Me a Coffee" in index_html
    assert "footer-disclaimer-wrap" in index_html

    # Disclaimer 3-paragraph check
    p1 = "Mistria Gift Planner is an unofficial fan-made tool, not affiliated with or endorsed by NPC Studio."
    p2 = "Fields of Mistria and all related assets, art, characters, and trademarks are © NPC Studio. Copyright holders who want content removed can contact me via GitHub."
    p3 = "Save files are parsed locally in your browser. No save data or personal information is sent to any server."

    assert p1 in index_html
    assert p2 in index_html
    assert p3 in index_html

    # Villager terminology check
    assert "Completed Villagers" in index_html
    assert "Incomplete Villagers" in index_html
    assert 'placeholder="Search recipe or villager..."' in index_html
    assert 'placeholder="Search villager..."' in index_html

    # Verify settings schema labels changed to Villager
    schema = get_settings_schema()
    general_fields = schema[0]["fields"]
    focus_fields = schema[1]["fields"]
    assert any(f["label"] == "Exclude Villagers" for f in general_fields)
    assert any(f["label"] == "Focus Villagers" for f in focus_fields)
    assert any(f["label"] == "Include Already-Gifted Villagers" for f in general_fields)


def test_tooltip_right_overflow_prevention(repo_root):
    """Verify CSS and JS prevent parameter help tooltips from overflowing the right border."""
    style_css = (repo_root / "companion" / "static" / "style.css").read_text(encoding="utf-8")
    app_js = (repo_root / "companion" / "static" / "app.js").read_text(encoding="utf-8")

    # CSS right-aligned classes
    assert ".param-help-tooltip.align-right" in style_css
    assert ".param-help-wrap.tooltip-align-right" in style_css
    assert "right: -6px;" in style_css
    assert "right: 12px;" in style_css

    # JS alignment logic
    assert "function adjustHelpTooltipPosition" in app_js
    assert "function updateAllHelpTooltipPositions" in app_js
    assert 'tooltip.classList.add("align-right")' in app_js
    assert 'document.addEventListener("mouseenter"' in app_js


def test_focus_suggestions_tree_button_and_alt_sources(repo_root):
    """Verify focus suggestions omit tree button when no branch and display all alternate sources."""
    app_js = (repo_root / "companion" / "static" / "app.js").read_text(encoding="utf-8")
    style_css = (repo_root / "companion" / "static" / "style.css").read_text(encoding="utf-8")

    # 1. Tree button conditional on having branches (children.length > 0)
    assert "hasBranches = Boolean(tree && Array.isArray(tree.children) && tree.children.length > 0)" in app_js
    assert "if (hasBranches)" in app_js

    # 2. Shows all alternate sources on focus suggestions
    assert "altSources = (f.alt_sources && Array.isArray(f.alt_sources) && f.alt_sources.length > 0)" in app_js
    assert "focus-alt-badge" in app_js
    assert "focus-alt-sources-row" in app_js

    # 3. CSS styles for alt sources badges
    assert ".focus-alt-sources-row" in style_css
    assert ".focus-alt-badges" in style_css
    assert ".focus-alt-badge" in style_css

    # 4. plan_to_json exports alt_sources for focus suggestions
    cfg = CompanionConfig()
    save, plan_res, meta, save_path = execute_plan(cfg, repo_root)
    json_data = plan_to_json(save, plan_res, meta, save_path, cfg)
    assert "focus_suggestions" in json_data
    for item in json_data["focus_suggestions"]:
        assert "alt_sources" in item
        assert isinstance(item["alt_sources"], list)





