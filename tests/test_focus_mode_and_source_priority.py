"""
tests/test_focus_mode_and_source_priority.py

Comprehensive test suite for:
- NPC Focus Mode (R1)
- Source Priority Summary (R2)
- Companion UI Integration & Schemas (R3)
- Config Persistence & API Serialization (R4)
- Non-Regression and Invariant Guarantees
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Set

import pytest
from starlette.testclient import TestClient

from companion.config import (
    CompanionConfig,
    get_settings_schema,
    load_companion_config,
    save_companion_config,
)
from companion.json_exporter import plan_to_json
from companion.planner_bridge import execute_plan
from companion.server import app
from fom_planner.crafting import load_recipes
from fom_planner.data_loader import (
    load_alt_sources,
    load_item_locations,
    load_item_metadata,
    load_npc_preferences_from_json,
)
from fom_planner.models import SaveData
from fom_planner.optimizer import (
    _split_compound_locations,
    classify_source_tier,
    compute_focus_suggestions,
    compute_source_priorities,
    filter_remaining_items_for_focus,
    normalize_source_name,
    plan_daily_gift_bag,
    plan_max_relationship,
)
from fom_planner.parser import parse_save_file


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def sample_save(repo_root: Path) -> SaveData:
    save_path = repo_root / "samples" / "sample_save.sav"
    return parse_save_file(save_path)


@pytest.fixture
def game_data(repo_root: Path) -> Dict[str, Any]:
    item_data_path = repo_root / "data" / "item_data.json"
    fiddle_path = repo_root / "data" / "npc_gift_preferences.json"
    npcs_def, _ = load_npc_preferences_from_json(item_data_path)
    metadata = load_item_metadata(fiddle_path, item_data_path, None)
    locations = load_item_locations()
    return {
        "npc_gift_definitions": npcs_def,
        "item_metadata": metadata,
        "item_locations": locations,
    }


# ============================================================================
# 1. TestFocusModeConfig (R4)
# ============================================================================

class TestFocusModeConfig:
    def test_default_values(self):
        config = CompanionConfig()
        assert config.focus_mode_enabled is False
        assert config.focus_npcs == ""
        assert config.exclude_npcs == ""

    def test_serialization_roundtrip(self):
        config = CompanionConfig(
            focus_mode_enabled=True,
            focus_npcs="adeline,march,balor",
            strategy="max-relationship",
            slots=16,
        )
        d = config.to_dict()
        assert d["focus_mode_enabled"] is True
        assert d["focus_npcs"] == "adeline,march,balor"
        assert d["slots"] == 16

        restored = CompanionConfig.from_dict(d)
        assert restored.focus_mode_enabled is True
        assert restored.focus_npcs == "adeline,march,balor"
        assert restored.slots == 16

    def test_backward_compatibility_missing_fields(self):
        # Emulate older companion_config.json omitting focus mode fields
        old_data = {
            "strategy": "journal",
            "mode": "auto",
            "slots": 20,
            "exclude_npcs": "balor",
        }
        config = CompanionConfig.from_dict(old_data)
        assert config.focus_mode_enabled is False
        assert config.focus_npcs == ""
        assert config.exclude_npcs == "balor"

    def test_from_dict_coercion(self):
        data = {
            "focus_mode_enabled": 1,
            "focus_npcs": ["adeline", "balor"],
        }
        config = CompanionConfig.from_dict(data)
        assert config.focus_mode_enabled is True
        assert config.focus_npcs == "adeline,balor"

    def test_settings_schema(self):
        schema = get_settings_schema()
        assert isinstance(schema, list)
        focus_group = next((g for g in schema if g.get("id") == "focus_suggestions"), None)
        assert focus_group is not None, "focus_suggestions group must exist in settings schema"

        focus_fields = {f["key"]: f for f in focus_group.get("fields", [])}
        assert "focus_mode_enabled" in focus_fields
        assert "focus_npcs" in focus_fields
        assert "focus_sort" in focus_fields
        assert "all_seasons" in focus_fields
        assert "seasonal_boost" in focus_fields

        assert focus_fields["focus_mode_enabled"]["type"] == "checkbox"
        assert focus_fields["focus_npcs"]["type"] == "focus_npc_picker"

        planning_group = next((g for g in schema if g.get("id") == "planning"), None)
        assert planning_group is not None
        planning_fields = {f["key"]: f for f in planning_group.get("fields", [])}
        assert "exclude_npcs" in planning_fields
        assert planning_fields["exclude_npcs"]["type"] == "exclude_npc_picker"
        assert "max_relationship_points" not in planning_fields

    def test_config_file_save_and_load(self, tmp_path):
        config = CompanionConfig(
            focus_mode_enabled=True,
            focus_npcs="celine,march",
            slots=18,
        )
        save_companion_config(config, tmp_path)
        loaded = load_companion_config(tmp_path)
        assert loaded.focus_mode_enabled is True
        assert loaded.focus_npcs == "celine,march"
        assert loaded.slots == 18


# ============================================================================
# 2. TestFocusModeOptimizer (R1)
# ============================================================================

class TestFocusModeOptimizer:
    def test_filter_remaining_items_basic(self):
        remaining_items_map = {
            "apple": {"loved": {"adeline", "celine"}, "liked": {"balor"}},
            "carrot": {"loved": set(), "liked": {"march", "olric"}},
            "ruby": {"loved": {"valen"}, "liked": set()},
        }

        # Empty/falsy focus_npcs returns original unmodified
        res_none = filter_remaining_items_for_focus(remaining_items_map, None)
        assert res_none == remaining_items_map

        res_empty = filter_remaining_items_for_focus(remaining_items_map, "")
        assert res_empty == remaining_items_map

        res_empty_set = filter_remaining_items_for_focus(remaining_items_map, set())
        assert res_empty_set == remaining_items_map

        # Filter for Adeline only
        res_adeline = filter_remaining_items_for_focus(remaining_items_map, "adeline")
        assert "apple" in res_adeline
        assert "carrot" not in res_adeline
        assert "ruby" not in res_adeline
        assert res_adeline["apple"]["loved"] == {"adeline"}
        assert res_adeline["apple"]["liked"] == set()

        # Filter for March and Balor (list of strings)
        res_mb = filter_remaining_items_for_focus(remaining_items_map, ["march", "balor"])
        assert "apple" in res_mb  # balor liked
        assert "carrot" in res_mb  # march liked
        assert "ruby" not in res_mb
        assert res_mb["apple"]["loved"] == set()
        assert res_mb["apple"]["liked"] == {"balor"}
        assert res_mb["carrot"]["liked"] == {"march"}

    def test_focus_mode_off_preserves_baseline(self, sample_save: SaveData, game_data: Dict[str, Any]):
        plan_baseline = plan_daily_gift_bag(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
        )
        plan_focus_off = plan_daily_gift_bag(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
            focus_mode_enabled=False,
            focus_npcs="adeline,march",
        )

        assert len(plan_focus_off["focus_suggestions"]) == len(plan_baseline["focus_suggestions"])
        for b, f in zip(plan_baseline["focus_suggestions"], plan_focus_off["focus_suggestions"]):
            assert b["item_id"] == f["item_id"]
            assert b["deficit"] == f["deficit"]
            assert b["blocked_pairs"] == f["blocked_pairs"]

    def test_focus_mode_on_empty_npcs_preserves_baseline(self, sample_save: SaveData, game_data: Dict[str, Any]):
        plan_baseline = plan_daily_gift_bag(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
        )
        plan_focus_empty_str = plan_daily_gift_bag(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
            focus_mode_enabled=True,
            focus_npcs="",
        )
        plan_focus_empty_set = plan_daily_gift_bag(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
            focus_mode_enabled=True,
            focus_npcs=set(),
        )

        assert len(plan_focus_empty_str["focus_suggestions"]) == len(plan_baseline["focus_suggestions"])
        assert len(plan_focus_empty_set["focus_suggestions"]) == len(plan_baseline["focus_suggestions"])
        for b, f in zip(plan_baseline["focus_suggestions"], plan_focus_empty_str["focus_suggestions"]):
            assert b["item_id"] == f["item_id"]
            assert b["deficit"] == f["deficit"]

    def test_focus_mode_filters_1_or_2_npcs(self, sample_save: SaveData, game_data: Dict[str, Any]):
        plan_baseline = plan_daily_gift_bag(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
        )
        baseline_suggestions = plan_baseline["focus_suggestions"]
        assert len(baseline_suggestions) > 0

        # Focus only on Adeline
        plan_adeline = plan_daily_gift_bag(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
            focus_mode_enabled=True,
            focus_npcs="adeline",
        )
        sug_adeline = plan_adeline["focus_suggestions"]
        assert 0 < len(sug_adeline) <= len(baseline_suggestions)

        for item in sug_adeline:
            blocked = {str(n).lower() for n in item.get("blocked_npcs", [])}
            # Must benefit Adeline directly or via crafting recipe
            assert "adeline" in blocked

        # Focus on Adeline and March
        plan_adm = plan_daily_gift_bag(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
            focus_mode_enabled=True,
            focus_npcs={"adeline", "march"},
        )
        sug_adm = plan_adm["focus_suggestions"]
        assert 0 < len(sug_adm) <= len(baseline_suggestions)
        for item in sug_adm:
            blocked = {str(n).lower() for n in item.get("blocked_npcs", [])}
            assert bool(blocked & {"adeline", "march"})

    def test_focus_mode_crafted_gifts_resolve_raw_materials(self):
        # Synthesize a scenario with a crafted gift
        # recipe: iron_bar = 5 iron_ore, steel_sword = 2 iron_bar
        # NPC March loves steel_sword; NPC Celine loves salad (lettuce)
        remaining_items_map = {
            "steel_sword": {"loved": {"march"}, "liked": set()},
            "salad": {"loved": {"celine"}, "liked": set()},
        }
        recipes = {
            "steel_sword": {"ingredients": {"iron_bar": 2}},
            "iron_bar": {"ingredients": {"iron_ore": 5}},
            "salad": {"ingredients": {"lettuce": 1}},
        }
        inventory = {}

        # Focus on March only
        suggestions_march = compute_focus_suggestions(
            remaining_items_map=remaining_items_map,
            inventory=inventory,
            recipes=recipes,
            focus_mode_enabled=True,
            focus_npcs={"march"},
        )
        item_ids_march = {s["item_id"] for s in suggestions_march}
        # iron_ore or steel_sword or iron_bar should be present for March
        assert bool(item_ids_march & {"iron_ore", "iron_bar", "steel_sword"})
        # lettuce or salad must NOT be present since Celine is not focused
        assert "lettuce" not in item_ids_march
        assert "salad" not in item_ids_march

        # Focus on Celine only
        suggestions_celine = compute_focus_suggestions(
            remaining_items_map=remaining_items_map,
            inventory=inventory,
            recipes=recipes,
            focus_mode_enabled=True,
            focus_npcs={"celine"},
        )
        item_ids_celine = {s["item_id"] for s in suggestions_celine}
        assert bool(item_ids_celine & {"lettuce", "salad"})
        assert "iron_ore" not in item_ids_celine
        assert "iron_bar" not in item_ids_celine
        assert "steel_sword" not in item_ids_celine

    def test_gift_bag_invariance_journal_and_max_relationship(self, sample_save: SaveData, game_data: Dict[str, Any]):
        """
        CRITICAL INVARIANT (Design Decision 2):
        Focus NPCs filter applies ONLY to the Focus Suggestions section.
        The daily gift bag plan loadout is 100% NOT affected.
        """
        # 1. Journal mode
        plan_unfiltered_j = plan_daily_gift_bag(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
            focus_mode_enabled=False,
        )
        plan_focused_j = plan_daily_gift_bag(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
            focus_mode_enabled=True,
            focus_npcs={"adeline", "march"},
        )
        assert plan_unfiltered_j["bag_plan"] == plan_focused_j["bag_plan"]
        assert plan_unfiltered_j["target_npcs"] == plan_focused_j["target_npcs"]

        # 2. Max relationship mode
        plan_unfiltered_m = plan_max_relationship(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
            focus_mode_enabled=False,
        )
        plan_focused_m = plan_max_relationship(
            save=sample_save,
            npc_gift_definitions=game_data["npc_gift_definitions"],
            item_metadata=game_data["item_metadata"],
            item_locations=game_data["item_locations"],
            focus_mode_enabled=True,
            focus_npcs={"valen", "celine"},
        )
        assert plan_unfiltered_m["bag_plan"] == plan_focused_m["bag_plan"]
        assert plan_unfiltered_m["target_npcs"] == plan_focused_m["target_npcs"]


# ============================================================================
# 3. TestSourcePrioritySummary (R2)
# ============================================================================

class TestSourcePrioritySummary:
    def test_source_schema_validation(self):
        focus_suggestions = [
            {
                "item_id": "apple",
                "item_name": "Apple",
                "deficit": 3,
                "blocked_pairs": 8,
                "blocked_npcs": ["adeline", "celine"],
            },
            {
                "item_id": "copper_ore",
                "item_name": "Copper Ore",
                "deficit": 10,
                "blocked_pairs": 15,
                "blocked_npcs": ["march"],
            },
        ]
        item_locations = {
            "apple": "General Store / Balor's Wagon",
            "copper_ore": "Mines (Upper Levels)",
        }
        alt_sources = {
            "apple": [{"type": "shop", "vendor": "Balor's Wagon"}],
        }
        npc_names = {"adeline": "Adeline", "celine": "Celine", "march": "March"}

        source_priorities = compute_source_priorities(
            focus_suggestions=focus_suggestions,
            item_locations=item_locations,
            alt_sources=alt_sources,
            npc_names=npc_names,
        )

        assert isinstance(source_priorities, list)
        assert len(source_priorities) > 0

        for src in source_priorities:
            assert "source_name" in src
            assert "tier" in src
            assert src["tier"] in ("Quick", "Grind", "Farm")
            assert "total_score" in src
            assert isinstance(src["total_score"], int)
            assert "items" in src
            assert isinstance(src["items"], list)
            assert "benefited_npcs" in src
            assert isinstance(src["benefited_npcs"], list)

            for it in src["items"]:
                assert "item_id" in it
                assert "item_name" in it
                assert "deficit" in it
                assert "blocked_pairs" in it

    def test_total_score_equals_sum_of_blocked_pairs(self):
        focus_suggestions = [
            {
                "item_id": "iron_ore",
                "item_name": "Iron Ore",
                "deficit": 5,
                "blocked_pairs": 12,
                "blocked_npcs": ["march"],
            },
            {
                "item_id": "silver_ore",
                "item_name": "Silver Ore",
                "deficit": 2,
                "blocked_pairs": 7,
                "blocked_npcs": ["march", "olric"],
            },
        ]
        item_locations = {
            "iron_ore": "The Mines",
            "silver_ore": "The Mines",
        }
        sources = compute_source_priorities(
            focus_suggestions=focus_suggestions,
            item_locations=item_locations,
            alt_sources={},
        )
        assert len(sources) >= 1
        mines = next(s for s in sources if "Mines" in s["source_name"])
        expected_score = sum(it["blocked_pairs"] for it in mines["items"])
        assert mines["total_score"] == 12 + 7
        assert mines["total_score"] == expected_score

    def test_tier_mapping_classification(self):
        # Quick
        assert classify_source_tier("Balor's Wagon") == "Quick"
        assert classify_source_tier("General Store") == "Quick"
        assert classify_source_tier("The Inn") == "Quick"
        assert classify_source_tier("Darcy's Saturday Stall") == "Quick"
        assert classify_source_tier("Mill") == "Quick"
        assert classify_source_tier("Museum") == "Quick"
        assert classify_source_tier("Hayden's Shop") == "Quick"

        # Grind
        assert classify_source_tier("The Mines (Floors 1-20)") == "Grind"
        assert classify_source_tier("River Fishing") == "Grind"
        assert classify_source_tier("Wild Foraging") == "Grind"
        assert classify_source_tier("Deep Mines") == "Grind"

        # Farm
        assert classify_source_tier("Ranch Animals") == "Farm"
        assert classify_source_tier("Crops (Farm)") == "Farm"
        assert classify_source_tier("Animal Care") == "Farm"
        assert classify_source_tier("Coop / Barn") == "Farm"

    def test_multi_source_items(self):
        # An item present in multiple sources should appear under all of them
        focus_suggestions = [
            {
                "item_id": "apple",
                "item_name": "Apple",
                "deficit": 3,
                "blocked_pairs": 10,
                "blocked_npcs": ["adeline"],
            }
        ]
        item_locations = {
            "apple": "Wild Foraging",
        }
        alt_sources = {
            "apple": [
                {"type": "shop", "vendor": "Balor's Wagon"},
                {"type": "market_stall", "vendor": "Darcy's Stall"},
            ]
        }
        sources = compute_source_priorities(
            focus_suggestions=focus_suggestions,
            item_locations=item_locations,
            alt_sources=alt_sources,
        )
        source_names = [s["source_name"] for s in sources]
        assert any("Balor" in n for n in source_names)
        assert any("Darcy" in n for n in source_names)
        assert any("Foraging" in n or "Wild" in n for n in source_names)

        # Each source that includes apple awards it 10 points
        for s in sources:
            if any(it["item_id"] == "apple" for it in s["items"]):
                assert s["total_score"] >= 10

    def test_source_priority_empty_when_no_suggestions(self):
        assert compute_source_priorities([]) == []
        assert compute_source_priorities(None) == []  # type: ignore

    def test_compound_location_parsing(self):
        # Splitting compound locations on " / " outside parentheses
        loc_str = "General Store / The Mines (Floors 1-20 / Upper) / Balor's Wagon"
        parts = _split_compound_locations(loc_str)
        assert len(parts) == 3
        assert parts[0] == "General Store"
        assert parts[1] == "The Mines (Floors 1-20 / Upper)"
        assert parts[2] == "Balor's Wagon"

    def test_source_priority_living_off_the_land_farm_tier(self):
        """Living off the land alternate sources must be classified into the 'Farm' tier."""
        focus_suggestions = [
            {
                "item_id": "pumpkin_pie",
                "item_name": "Pumpkin Pie",
                "deficit": 2,
                "blocked_pairs": 7,
                "blocked_npcs": ["celine"],
            }
        ]
        alt_sources = {
            "pumpkin_pie": [
                {
                    "type": "living_off_the_land",
                    "location": "Living Off The Land",
                    "note": "Harvesting: Pumpkin",
                    "icon": "living_off_the_land",
                }
            ]
        }
        sources = compute_source_priorities(
            focus_suggestions=focus_suggestions,
            item_locations={},
            alt_sources=alt_sources,
        )
        lotl = next((s for s in sources if s["source_name"] == "Living Off The Land"), None)
        assert lotl is not None
        assert lotl["tier"] == "Farm"
        assert lotl["total_score"] == 7
        assert any(it["item_id"] == "pumpkin_pie" for it in lotl["items"])


# ============================================================================
# 4. TestCompanionAPIAndExporter (R3 & R4)
# ============================================================================

class TestCompanionAPIAndExporter:
    def test_json_exporter_includes_source_priority_with_sprite_url(self, repo_root: Path):
        config = CompanionConfig(strategy="journal", slots=20)
        save, plan_res, meta, save_path = execute_plan(config, repo_root)
        data = plan_to_json(save, plan_res, meta, save_path, config)

        assert "source_priority" in data
        assert isinstance(data["source_priority"], list)

        # If source_priority has entries, verify schema and sprite_url
        for src in data["source_priority"]:
            assert "source_name" in src
            assert "tier" in src
            assert "total_score" in src
            assert "items" in src
            assert "benefited_npcs" in src

            for it in src["items"]:
                assert "sprite_url" in it
                assert it["sprite_url"].startswith("/assets/sprites/items/")

        # Verify full JSON serialization
        serialized = json.dumps(data)
        assert len(serialized) > 0

    def test_api_get_settings(self):
        client = TestClient(app)
        res = client.get("/api/settings")
        assert res.status_code == 200
        body = res.json()
        assert "config" in body
        assert "schema" in body
        assert "focus_mode_enabled" in body["config"]
        assert "focus_npcs" in body["config"]

    def test_api_post_settings_updates_focus_mode_and_returns_plan(self):
        client = TestClient(app)
        try:
            # 1. Update settings with Focus Mode enabled for Adeline and March
            payload = {
                "focus_mode_enabled": True,
                "focus_npcs": "adeline,march",
            }
            res = client.post("/api/settings", json=payload)
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["config"]["focus_mode_enabled"] is True
            assert data["config"]["focus_npcs"] == "adeline,march"

            # 2. Returned plan has source_priority and filtered suggestions
            plan = data.get("plan", {})
            assert "source_priority" in plan
            assert "focus_suggestions" in plan

            for item in plan["focus_suggestions"]:
                blocked = {str(n).lower() for n in item.get("blocked_npcs", [])}
                assert bool(blocked & {"adeline", "march"})

            # 3. Test array payload coercion
            res_arr = client.post("/api/settings", json={"focus_npcs": ["celine", "valen"]})
            assert res_arr.status_code == 200
            data_arr = res_arr.json()
            assert data_arr["config"]["focus_npcs"] == "celine,valen"

        finally:
            # Clean up settings to avoid polluting tests
            client.post("/api/settings", json={"focus_mode_enabled": False, "focus_npcs": ""})
