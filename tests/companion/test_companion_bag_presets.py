"""
tests/companion/test_companion_bag_presets.py

Unit and integration tests for Bag Presets (Marriage Candidate & Custom Presets)
in the Local Companion server and UI.
"""

from pathlib import Path
import pytest
from starlette.testclient import TestClient

from companion.config import CompanionConfig, get_settings_schema
from companion.planner_bridge import execute_plan
from companion.server import app
from fom_planner.constants import MARRIAGE_CANDIDATES


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parents[2]


def test_companion_config_schema_includes_marriage():
    """Verify get_settings_schema includes 'marriage' option in mode field."""
    schema = get_settings_schema()
    planning_group = next(g for g in schema if g["id"] == "planning")
    mode_field = next(f for f in planning_group["fields"] if f["key"] == "mode")
    option_values = [opt["value"] for opt in mode_field["options"]]
    assert "marriage" in option_values
    marriage_opt = next(opt for opt in mode_field["options"] if opt["value"] == "marriage")
    assert "Marriage Candidates" in marriage_opt["label"]


def test_companion_config_custom_preset_npcs_field():
    """Verify CompanionConfig supports custom_preset_npcs serialization."""
    cfg = CompanionConfig(mode="custom", custom_preset_npcs="adeline,march,celine")
    assert cfg.custom_preset_npcs == "adeline,march,celine"
    d = cfg.to_dict()
    assert d["custom_preset_npcs"] == "adeline,march,celine"

    restored = CompanionConfig.from_dict({
        "mode": "custom",
        "custom_preset_npcs": ["adeline", "march", "celine"],
    })
    assert restored.custom_preset_npcs == "adeline,march,celine"


def test_companion_execute_plan_marriage_mode(repo_root):
    """Verify execute_plan with mode='marriage' filters targets to marriage candidates."""
    sample_save = repo_root / "samples" / "sample_save.sav"
    cfg = CompanionConfig(strategy="journal", mode="marriage", slots=20, save_file=str(sample_save))
    save, plan_res, meta, save_path = execute_plan(cfg, repo_root)

    target_npcs = set(plan_res.get("target_npcs", []))
    assert len(target_npcs) > 0
    assert target_npcs.issubset(MARRIAGE_CANDIDATES)

    for item in plan_res.get("bag_plan", []):
        for recipient in item.get("recipients", []):
            assert recipient["npc_id"].lower() in MARRIAGE_CANDIDATES


def test_companion_execute_plan_custom_preset(repo_root):
    """Verify execute_plan with mode='custom' and custom_preset_npcs restricts planning."""
    sample_save = repo_root / "samples" / "sample_save.sav"
    chosen_npcs = ["adeline", "march", "juniper"]
    cfg = CompanionConfig(
        strategy="journal",
        mode="custom",
        custom_preset_npcs=",".join(chosen_npcs),
        slots=20,
        save_file=str(sample_save),
    )
    save, plan_res, meta, save_path = execute_plan(cfg, repo_root)

    target_npcs = set(plan_res.get("target_npcs", []))
    assert target_npcs.issubset(set(chosen_npcs))

    for item in plan_res.get("bag_plan", []):
        for recipient in item.get("recipients", []):
            assert recipient["npc_id"].lower() in chosen_npcs


def test_companion_api_settings_marriage_and_custom(repo_root):
    """Verify FastAPI /api/settings handles mode='marriage' and custom presets."""
    sample_save = str(repo_root / "samples" / "sample_save.sav")
    with TestClient(app) as client:
        # Set save file and reset strategy to journal to avoid pollution from other tests
        res_setup = client.post("/api/settings", json={
            "save_file": sample_save,
            "strategy": "journal",
            "focus_mode_enabled": False,
        })
        assert res_setup.status_code == 200

        try:
            # Switch to marriage mode
            res_m = client.post("/api/settings", json={"mode": "marriage"})
            assert res_m.status_code == 200
            data_m = res_m.json()
            assert data_m["config"]["mode"] == "marriage"
            assert len(data_m["plan"]["bag_plan"]) > 0
            for item in data_m["plan"]["bag_plan"]:
                for r in item.get("recipients", []):
                    assert r["npc_id"].lower() in MARRIAGE_CANDIDATES

            # Switch to custom preset mode
            res_c = client.post("/api/settings", json={
                "mode": "custom",
                "custom_preset_npcs": "adeline,celine",
            })
            assert res_c.status_code == 200
            data_c = res_c.json()
            assert data_c["config"]["mode"] == "custom"
            assert "adeline" in data_c["config"]["custom_preset_npcs"]
            assert len(data_c["plan"]["bag_plan"]) > 0
            for item in data_c["plan"]["bag_plan"]:
                for r in item.get("recipients", []):
                    assert r["npc_id"].lower() in {"adeline", "celine"}
        finally:
            # Always clean up test settings to leave companion_config.json clean
            client.post("/api/settings", json={
                "mode": "auto",
                "custom_preset_npcs": "",
                "focus_mode_enabled": False,
                "focus_npcs": "",
                "strategy": "journal",
                "slots": 20,
            })


def test_companion_static_assets_preset_parity(repo_root):
    """Verify static index.html, style.css, and app.js have preset DOM and logic parity."""
    index_html = (repo_root / "companion" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="bagPresetBar"' in index_html
    assert 'id="bagPresetPills"' in index_html
    assert 'id="customPresetModal"' in index_html
    assert 'id="presetVillagerGrid"' in index_html
    assert 'id="presetSaveBtn"' in index_html
    assert 'id="presetDeleteBtn"' in index_html

    style_css = (repo_root / "companion" / "static" / "style.css").read_text(encoding="utf-8")
    assert ".bag-preset-bar" in style_css
    assert ".bag-preset-pill" in style_css
    assert ".preset-modal-backdrop" in style_css
    assert ".preset-villager-grid" in style_css

    app_js = (repo_root / "companion" / "static" / "app.js").read_text(encoding="utf-8")
    assert "fom_custom_presets_v1" in app_js
    assert "renderBagPresetToolbar" in app_js
    assert "openPresetModal" in app_js
    assert "handleSavePreset" in app_js
    assert "handleDeletePreset" in app_js
    assert "handleModeSelectChange" in app_js
