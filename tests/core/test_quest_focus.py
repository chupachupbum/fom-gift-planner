"""
test_quest_focus.py

Unit and integration tests for Milestone 1 (R1):
- Quest dataset loading and normalization (load_quest_data)
- SaveData quest completion parsing (SaveData.get_completed_quest_keys)
- Quest completion title/ID matching (is_quest_completed)
"""

import json
from pathlib import Path
from typing import Set

import pytest

from fom_planner.constants import DEFAULT_QUEST_DATA_PATH
from fom_planner.data_loader import (
    GENERIC_QUEST_PLACEHOLDERS,
    QUEST_ITEM_ALIASES,
    load_quest_data,
)
from fom_planner.models import QUEST_TITLE_ALIASES, SaveData, is_quest_completed
from fom_planner.optimizer import (
    build_focus_crafting_trees,
    compute_focus_suggestions,
)
from fom_planner.parser import parse_save_file


# ==============================================================================
# 1. Tests for load_quest_data()
# ==============================================================================


class TestLoadQuestData:
    """Tests for quest requirement dataset loading, alias resolution, and exclusions."""

    def test_default_path_exists(self):
        """Verifies DEFAULT_QUEST_DATA_PATH is set and exists in data/ directory."""
        assert DEFAULT_QUEST_DATA_PATH.exists()
        assert DEFAULT_QUEST_DATA_PATH.is_file()

    def test_clean_loading_default_path(self):
        """Verifies clean loading from the bundled data/quest_data.json."""
        qd = load_quest_data()
        assert isinstance(qd, dict)
        assert len(qd) > 200

        # Verify structure on a known common quest item (copper_ore)
        assert "copper_ore" in qd
        copper = qd["copper_ore"]
        assert copper["name"] == "Copper Ore"
        assert isinstance(copper["total_required"], int)
        assert copper["total_required"] > 0
        assert isinstance(copper["quest_types"], list)
        assert len(copper["quest_types"]) > 0
        assert isinstance(copper["quests"], list)
        assert len(copper["quests"]) > 0

        first_quest = copper["quests"][0]
        assert "quest_name" in first_quest
        assert "quest_type" in first_quest
        assert "category" in first_quest
        assert "amount" in first_quest
        assert "requester" in first_quest

    def test_missing_file_fallback(self, tmp_path: Path):
        """Returns empty dict gracefully on nonexistent path."""
        nonexistent = tmp_path / "does_not_exist.json"
        assert load_quest_data(nonexistent) == {}
        assert load_quest_data("/invalid/path/quest.json") == {}

    def test_corrupt_file_fallback(self, tmp_path: Path):
        """Returns empty dict gracefully on corrupt/malformed JSON files."""
        corrupt_file = tmp_path / "corrupt.json"
        corrupt_file.write_text("{this is not valid json", encoding="utf-8")
        assert load_quest_data(corrupt_file) == {}

        non_dict_file = tmp_path / "list.json"
        non_dict_file.write_text("[1, 2, 3]", encoding="utf-8")
        assert load_quest_data(non_dict_file) == {}

        empty_details = tmp_path / "empty_details.json"
        empty_details.write_text(json.dumps({"item_quest_details": "not-a-dict"}), encoding="utf-8")
        assert load_quest_data(empty_details) == {}

    def test_mission_quest_exclusion(self):
        """Verifies that all 12 monster hunt Mission Quests are excluded."""
        qd = load_quest_data()

        mission_keys = [
            "green_saplings",
            "any_rockclod",
            "green_mushroom",
            "blue_enchanterns",
            "green_stalagmites",
            "blue_essence_bats",
            "mimics",
            "flame_spirits",
            "lava_cats",
            "flying_tomes",
            "rock_stacks",
            "living_gryphon_statues",
        ]
        for key in mission_keys:
            assert key not in qd, f"Mission Quest '{key}' should have been excluded"

    def test_mission_quest_filtering_within_item(self, tmp_path: Path):
        """Verifies that Mission Quests are filtered out while keeping standard quests for an item."""
        mock_data = {
            "item_quest_details": {
                "mixed_item": {
                    "name": "Mixed Item",
                    "total_required": 30,
                    "quest_types": ["Mission Quest", "Request"],
                    "quests": [
                        {
                            "quest_name": "Kill 20 Bats",
                            "quest_type": "Mission Quest",
                            "category": "Mission Quest",
                            "amount": 20,
                            "requester": None,
                        },
                        {
                            "quest_name": "Request for Mixed Item",
                            "quest_type": "Request",
                            "category": "Request",
                            "amount": 10,
                            "requester": "Adeline",
                        },
                    ],
                }
            }
        }
        mock_path = tmp_path / "mock_quest.json"
        mock_path.write_text(json.dumps(mock_data), encoding="utf-8")

        res = load_quest_data(mock_path)
        assert "mixed_item" in res
        item = res["mixed_item"]
        assert item["total_required"] == 10
        assert item["quest_types"] == ["Request"]
        assert len(item["quests"]) == 1
        assert item["quests"][0]["quest_name"] == "Request for Mixed Item"

    def test_generic_placeholders_exclusion(self):
        """Verifies generic category placeholders are excluded."""
        qd = load_quest_data()

        placeholders = [
            "crop",
            "berry",
            "fish",
            "flower",
            "soup",
            "mine_forageable",
            "monster_part",
            "baked_dishes",
            "wool",
            "copper_tool",
            "dining_tables",
            "dining_chairs",
            "stone_path",
        ]
        for p in placeholders:
            assert p not in qd, f"Placeholder '{p}' should have been excluded"

    def test_feather_disambiguation(self):
        """
        Verifies that generic Crown Request 'feather' is excluded, but
        Luc/Josephine's specific 'rooster_feather' quest is preserved under 'feather'.
        """
        qd = load_quest_data()

        assert "feather" in qd
        assert "rooster_feather" in qd
        # Both keys point to the same resolved entry
        assert qd["feather"] is qd["rooster_feather"]

        # Ensure no Crown Request for 10 feathers exists on feather
        for q in qd["feather"]["quests"]:
            assert q.get("category") != "Crown Request" or "Animal Materials" not in q.get("quest_name", "")
            assert "Rooster Feathers" in q.get("quest_name", "")

    def test_alias_resolution_and_bidirectional_lookup(self):
        """Verifies bidirectional mapping between Wiki quest IDs and canonical planner IDs on bundled data."""
        qd = load_quest_data()

        bidirectional_pairs = [
            ("milk", "cow_milk"),
            ("wood", "basic_wood"),
            ("stone", "ore_stone"),
            ("rice_ball", "riceball"),
            ("tea", "cup_of_tea"),
            ("breath_of_flame", "breath_of_fire"),
            ("archeology_shard", "shards"),
            ("chicken_egg", "egg"),
            ("clod_bomb", "bomb"),
            ("hay_bale", "spooky_haybale"),
            ("scarecrow", "starter_scarecrow"),
            ("birdhouse", "starter_bird_house_red"),
            ("shipping_bin", "starter_shipping_box"),
            ("wooden_fence", "starter_wood_fence"),
        ]

        for wiki_key, canonical_key in bidirectional_pairs:
            assert wiki_key in qd, f"Wiki key '{wiki_key}' missing from quest data"
            assert canonical_key in qd, f"Canonical key '{canonical_key}' missing from quest data"
            assert qd[wiki_key] == qd[canonical_key], (
                f"Data mismatch between alias '{wiki_key}' and canonical '{canonical_key}'"
            )

    def test_synthetic_alias_resolution(self, tmp_path: Path):
        """Verifies alias resolution on aliases like golden_milk -> golden_cow_milk using synthetic data."""
        mock_data = {
            "item_quest_details": {
                "golden_milk": {
                    "name": "Golden Milk",
                    "total_required": 5,
                    "quest_types": ["Request"],
                    "quests": [
                        {
                            "quest_name": "Request for Golden Milk",
                            "quest_type": "Request",
                            "category": "Request",
                            "amount": 5,
                            "requester": "Hayden",
                        }
                    ],
                }
            }
        }
        mock_file = tmp_path / "synthetic_quest.json"
        mock_file.write_text(json.dumps(mock_data), encoding="utf-8")

        res = load_quest_data(mock_file)
        assert "golden_milk" in res
        assert "golden_cow_milk" in res
        assert res["golden_milk"] == res["golden_cow_milk"]
        assert res["golden_cow_milk"]["total_required"] == 5

    def test_egg_merging(self):
        """Verifies that 'egg' and 'chicken_egg' are cleanly merged under canonical 'egg'."""
        qd = load_quest_data()

        assert "egg" in qd
        egg_entry = qd["egg"]
        quest_names = {q["quest_name"] for q in egg_entry["quests"]}
        # From 'egg': "Request for Eggs"
        assert "Request for Eggs" in quest_names
        # From 'chicken_egg': "Restocking Mistria's Food Reserves 2"
        assert "Restocking Mistria's Food Reserves 2" in quest_names
        assert egg_entry["total_required"] == sum(q["amount"] for q in egg_entry["quests"])

    def test_recalculated_totals_and_types(self):
        """Verifies total_required and quest_types are dynamically recomputed."""
        qd = load_quest_data()
        for item_id, item_data in qd.items():
            expected_total = sum(int(q.get("amount", 0)) for q in item_data["quests"])
            assert item_data["total_required"] == expected_total, (
                f"total_required mismatch for {item_id}: {item_data['total_required']} vs {expected_total}"
            )
            expected_types = sorted(list({str(q.get("quest_type", "Request")) for q in item_data["quests"]}))
            assert item_data["quest_types"] == expected_types, (
                f"quest_types mismatch for {item_id}: {item_data['quest_types']} vs {expected_types}"
            )


# ==============================================================================
# 2. Tests for SaveData.get_completed_quest_keys()
# ==============================================================================


class TestSaveDataCompletedQuests:
    """Tests for SaveData quest progression extraction from .sav files."""

    def test_sample_save_empty_quests(self):
        """Verifies sample_save.sav handles missing quests block gracefully."""
        sample_path = Path("samples/sample_save.sav")
        save = parse_save_file(sample_path)
        completed = save.get_completed_quest_keys()
        assert isinstance(completed, set)
        assert len(completed) == 0
        assert not save.is_quest_completed("Request for Copper")

    def test_synthetic_save_completed_quests_list(self):
        """Verifies completed_quests list extraction and normalization."""
        entries = {
            "quests": json.dumps({
                "completed_quests": [
                    "Request for Copper",
                    "The Water Tablet",
                    "A_Birdhouse",
                    "REPAIR_THE_BRIDGE",
                ]
            })
        }
        save = SaveData(Path("test.sav"), entries)
        completed = save.get_completed_quest_keys()

        assert "request_for_copper" in completed
        assert "the_water_tablet" in completed
        assert "a_birdhouse" in completed
        assert "repair_the_bridge" in completed
        assert len(completed) == 4

    def test_synthetic_save_completion_timestamps_dict(self):
        """Verifies completion_timestamps dict keys extraction and normalization."""
        entries = {
            "quests": json.dumps({
                "completion_timestamps": {
                    "bell_berry_bakewell_tart_challenge": 15465600,
                    "request_for_rabbit_wool": 7776000,
                }
            })
        }
        save = SaveData(Path("test.sav"), entries)
        completed = save.get_completed_quest_keys()

        assert "bell_berry_bakewell_tart_challenge" in completed
        assert "request_for_rabbit_wool" in completed
        assert len(completed) == 2

    def test_synthetic_save_gamedata_fallback(self):
        """Verifies gamedata['completed_quests'] fallback."""
        entries = {
            "gamedata": json.dumps({
                "completed_quests": [
                    "gamedata_quest_alpha",
                    "gamedata_quest_beta",
                ]
            })
        }
        save = SaveData(Path("test.sav"), entries)
        completed = save.get_completed_quest_keys()

        assert "gamedata_quest_alpha" in completed
        assert "gamedata_quest_beta" in completed

    def test_synthetic_save_combined_deduplication(self):
        """Verifies deduplication across completed_quests, completion_timestamps, and gamedata."""
        entries = {
            "quests": json.dumps({
                "completed_quests": ["shared_quest", "quest_one"],
                "completion_timestamps": {"shared_quest": 1234, "quest_two": 5678},
            }),
            "gamedata": json.dumps({
                "completed_quests": ["shared_quest", "quest_three"],
            }),
        }
        save = SaveData(Path("test.sav"), entries)
        completed = save.get_completed_quest_keys()

        assert completed == {"shared_quest", "quest_one", "quest_two", "quest_three"}

    def test_malformed_quest_blocks(self):
        """Handles malformed quests and gamedata entries without raising exceptions."""
        entries = {
            "quests": json.dumps({"completed_quests": None, "completion_timestamps": 12345}),
            "gamedata": json.dumps({"completed_quests": "not-a-list"}),
        }
        save = SaveData(Path("test.sav"), entries)
        completed = save.get_completed_quest_keys()
        assert completed == set()

    def test_real_save_file_if_present(self):
        """If a real steam autosave exists on this system, test comprehensive extraction."""
        autosaves = list(Path("/home/tyrell/snap/steam/common/.local/share/FieldsOfMistria/saves").glob("game-*-autosave.sav"))
        if not autosaves:
            pytest.skip("No live steam autosave file present")

        save = parse_save_file(autosaves[0])
        completed = save.get_completed_quest_keys()
        assert len(completed) > 30

        # In real save, active quests should NOT be completed
        for active in save.quests.get("active_quests", []):
            qname = active.get("quest_name")
            if qname:
                assert not save.is_quest_completed(qname), f"Active quest {qname} should not be marked completed"


# ==============================================================================
# 3. Tests for is_quest_completed()
# ==============================================================================


class TestIsQuestCompletedMatcher:
    """Tests for the is_quest_completed matcher function."""

    @pytest.fixture
    def completed_set(self) -> Set[str]:
        return {
            "request_for_copper",
            "the_water_tablet",
            "repair_the_beach_bridge",
            "request_for_a_red_toadstool",
            "request_for_rooster_feathers",
            "corrupted_mistril_sword_request",
            "request_for_uncommon_pheromone",
            "restocking_mistrias_food_reserves_2",
            "jos_cooking_class",
            "crown_request_golden_ingredients",
        }

    def test_exact_matches(self, completed_set):
        assert is_quest_completed("request_for_copper", completed_set)
        assert is_quest_completed("Request for Copper", completed_set)
        assert is_quest_completed("repair_the_beach_bridge", completed_set)
        assert is_quest_completed("Repair the Beach Bridge", completed_set)

    def test_article_stripping(self, completed_set):
        # Stripping leading 'the'
        assert is_quest_completed("Water Tablet", completed_set)
        assert is_quest_completed("The Water Tablet", completed_set)
        # Inner article handling
        assert is_quest_completed("Request for Red Toadstool", completed_set)
        assert is_quest_completed("Request for a Red Toadstool", completed_set)

    def test_singular_plural_matching(self, completed_set):
        # Quest in set is 'request_for_rooster_feathers', tested with singular
        assert is_quest_completed("Request for Rooster Feather", completed_set)
        assert is_quest_completed("Request for Rooster Feathers", completed_set)
        # Quest in set is 'crown_request_golden_ingredients', tested with singular
        assert is_quest_completed("Crown Request: Golden Ingredient", completed_set)

    def test_request_pattern_swap(self, completed_set):
        # Set has 'corrupted_mistril_sword_request', tested with 'Request for ...'
        assert is_quest_completed("Request for Corrupted Mistril Sword", completed_set)
        assert is_quest_completed("Request for a Corrupted Mistril Sword", completed_set)

        # Set has 'request_for_uncommon_pheromone', tested with '... Request'
        assert is_quest_completed("Uncommon Pheromone Request", completed_set)
        assert is_quest_completed("Uncommon Bug Pheromone Request", completed_set) is False

    def test_apostrophe_and_punctuation_handling(self, completed_set):
        # "Restocking Mistria's Food Reserves 2"
        assert is_quest_completed("Restocking Mistria's Food Reserves 2", completed_set)
        assert is_quest_completed("Restocking Mistrias Food Reserves 2", completed_set)
        # "Jo's Cooking Class"
        assert is_quest_completed("Jo's Cooking Class", completed_set)
        assert is_quest_completed("Jos Cooking Class", completed_set)

    def test_uncompleted_and_edge_cases(self, completed_set):
        assert not is_quest_completed("Request for Perch", completed_set)
        assert not is_quest_completed("Breaking The Fire Seal", completed_set)
        assert not is_quest_completed("", completed_set)
        assert not is_quest_completed(None, completed_set)
        assert not is_quest_completed("Request for Copper", set())
        assert not is_quest_completed("Request for Copper", None)

    def test_wiki_title_alias_resolution(self):
        """
        Verifies that Wiki quest titles correctly match when the save file contains
        their internal game save keys (remediating empirical challenge findings).
        """
        target_pairs = [
            ("Restocking Mistria's Food Reserves 2", {"replenishing_mistrias_food_reserves_2"}),
            ("Restocking Mistria's Food Reserves 1", {"replenishing_mistrias_food_reserves_1"}),
            ("Restocking Mistria's Food Reserves", {"replenishing_mistrias_food_reserves_1"}),
            ("Request for Wood Fencing", {"request_for_wood_fence"}),
            ("Wood Fencing Request", {"request_for_wood_fence"}),
            ("Crown Request: Archeology Shards", {"crown_request_archaeology_shards"}),
            ("Upgrade Hayden's Barn", {"repair_haydens_barn"}),
            ("Request for a Hay Bale", {"request_for_haybale"}),
            ("Request for Hay Bale", {"request_for_haybale"}),
            ("Request for a Really Round Rock", {"request_for_round_rock"}),
            ("Request for Really Round Rock", {"request_for_round_rock"}),
            ("Request for Capybara Bristles", {"request_for_bristles"}),
            ("Fried Earthshroom Challenge", {"crispy_fried_earthshroom_challenge"}),
            ("Request for a Daikon Radish", {"request_for_daikon"}),
            ("Request for Daikon Radish", {"request_for_daikon"}),
            ("Request for Bell Berry Bakewell Tart", {"request_for_bell_berry_bakewell"}),
        ]

        for wiki_title, save_keys in target_pairs:
            assert is_quest_completed(wiki_title, save_keys), (
                f"Wiki quest title '{wiki_title}' failed to match save key set {save_keys}"
            )

    def test_gerund_noun_suffix_variants(self):
        """Verifies gerund/noun suffix variants (e.g. _fencing <-> _fence)."""
        assert is_quest_completed("Request for Wood Fencing", {"request_for_wood_fence"})
        assert is_quest_completed("Request for Wood Fence", {"request_for_wood_fencing"})
        assert is_quest_completed("Wood Fencing Request", {"request_for_wood_fence"})
        assert is_quest_completed("Wood Fence Request", {"request_for_wood_fencing"})

    def test_alias_numbered_distinction(self):
        """Verifies that aliased numbered quests do not cross-match tiers."""
        reserves_1 = {"replenishing_mistrias_food_reserves_1"}
        assert is_quest_completed("Restocking Mistria's Food Reserves 1", reserves_1)
        assert is_quest_completed("Restocking Mistria's Food Reserves", reserves_1)
        assert not is_quest_completed("Restocking Mistria's Food Reserves 2", reserves_1)
        assert not is_quest_completed("Restocking Mistria's Food Reserves 3", reserves_1)

        reserves_2 = {"replenishing_mistrias_food_reserves_2"}
        assert is_quest_completed("Restocking Mistria's Food Reserves 2", reserves_2)
        assert not is_quest_completed("Restocking Mistria's Food Reserves 1", reserves_2)
        assert not is_quest_completed("Restocking Mistria's Food Reserves 3", reserves_2)

    def test_all_quest_title_aliases_mapping(self):
        """Verifies that every entry in QUEST_TITLE_ALIASES maps and matches properly."""
        assert len(QUEST_TITLE_ALIASES) >= 16
        for wiki_norm, save_key in QUEST_TITLE_ALIASES.items():
            assert is_quest_completed(wiki_norm, {save_key}), (
                f"Alias key '{wiki_norm}' did not match save key '{save_key}'"
            )

    def test_real_save_wiki_quest_resolution(self):
        """
        If a real steam autosave exists on this system, test that all target Wiki quests
        correctly evaluate to True using SaveData.is_quest_completed().
        """
        autosaves = list(Path("/home/tyrell/snap/steam/common/.local/share/FieldsOfMistria/saves").glob("game-*-autosave.sav"))
        if not autosaves:
            pytest.skip("No live steam autosave file present")

        save = parse_save_file(autosaves[0])
        target_wiki_quests = [
            "Restocking Mistria's Food Reserves 2",
            "Restocking Mistria's Food Reserves",
            "Request for Wood Fencing",
            "Crown Request: Archeology Shards",
            "Upgrade Hayden's Barn",
            "Request for a Hay Bale",
            "Request for a Really Round Rock",
            "Request for Capybara Bristles",
            "Fried Earthshroom Challenge",
            "Request for a Daikon Radish",
            "Request for Bell Berry Bakewell Tart",
        ]
        for qname in target_wiki_quests:
            assert save.is_quest_completed(qname), f"Real save should have completed quest: {qname}"


# ==============================================================================
# 4. Tests for Milestone 2 (R2): compute_focus_suggestions Quest Integration
# ==============================================================================


class TestComputeFocusSuggestionsQuestIntegration:
    """Tests for combined deficit math, crafted rollups, intermediate inventory deduction, and metadata."""

    def test_strict_gate_zero_gift_deficit_excluded(self):
        """
        Strict gate invariant: items with gift_deficit == 0 MUST NOT be returned in focus_suggestions,
        even if they have large quest demand.
        """
        # Case 1: Item is not in remaining_items_map at all
        rem_map = {"cabbage": {"loved": {"March"}}}
        synthetic_quests = {
            "copper_ore": {
                "name": "Copper Ore",
                "quests": [
                    {"quest_name": "Request for Copper", "quest_type": "Request", "category": "Request", "amount": 100, "requester": "March"}
                ],
            }
        }
        res = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory={},
            recipes={},
            quest_data=synthetic_quests,
        )
        item_ids = [item["item_id"] for item in res]
        assert "cabbage" in item_ids
        assert "copper_ore" not in item_ids, "copper_ore with gift_deficit == 0 must be gated out"

        # Case 2: Item is in remaining_items_map, but player owns enough inventory (gift_deficit == 0)
        rem_map_with_copper = {"copper_ore": {"loved": {"March"}}}
        inv_with_copper = {"copper_ore": 1}  # 1 needed, 1 owned -> gift_deficit = 0
        res2 = compute_focus_suggestions(
            remaining_items_map=rem_map_with_copper,
            inventory=inv_with_copper,
            recipes={},
            quest_data=synthetic_quests,
        )
        assert len(res2) == 0, "copper_ore with satisfied gift inventory (gift_deficit == 0) must be gated out"

        # Case 3: When gift_deficit > 0, item enters focus suggestions
        inv_empty = {"copper_ore": 0}
        res3 = compute_focus_suggestions(
            remaining_items_map=rem_map_with_copper,
            inventory=inv_empty,
            recipes={},
            quest_data=synthetic_quests,
        )
        assert len(res3) == 1
        assert res3[0]["item_id"] == "copper_ore"
        assert res3[0]["gift_deficit"] == 1
        assert res3[0]["quest_demand"] == 100
        assert res3[0]["deficit"] == 101

    def test_combined_deficit_math_raw_item(self):
        """Verifies deficit == gift_deficit + quest_demand on raw materials."""
        rem_map = {"copper_ore": {"loved": {"March"}, "liked": {"Celine"}}}  # 2 gift demand
        inv = {"copper_ore": 1}  # gift_deficit = 2 - 1 = 1
        synthetic_quests = {
            "copper_ore": {
                "name": "Copper Ore",
                "quests": [
                    {"quest_name": "Request for Copper", "quest_type": "Request", "category": "Request", "amount": 10, "requester": "March"}
                ],
            }
        }
        res = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory=inv,
            recipes={},
            quest_data=synthetic_quests,
        )
        assert len(res) == 1
        copper = res[0]
        assert copper["item_id"] == "copper_ore"
        assert copper["gift_deficit"] == 1
        assert copper["quest_demand"] == 10
        assert copper["deficit"] == 11
        assert copper["quest_count"] == 1
        assert copper["quest_categories"] == {"Request": 1}
        assert len(copper["quest_summary"]) == 1
        assert copper["quest_summary"][0]["quest_name"] == "Request for Copper"
        assert copper["quest_summary"][0]["amount"] == 10

    def test_intermediate_inventory_deduction_and_surplus_conversion(self):
        """
        Verifies:
        1. Intermediate inventory surplus = max(0, owned - direct_gift_need).
        2. Direct gift need for the intermediate item is reserved first.
        3. Surplus intermediate items reduce quest demand before rolling up to raw materials.
        4. Surplus intermediate items convert to root raw materials in effective inventory.
        """
        recipes = {
            "iron_bar": {
                "ingredients": [{"item_id": "iron_ore", "count": 5}],
                "display_name": "Iron Bar",
            },
            "iron_sword": {
                "ingredients": [{"item_id": "iron_bar", "count": 2}],
                "display_name": "Iron Sword",
            },
        }
        rem_map = {
            "iron_bar": {"loved": {"Celine"}},  # 1 direct gift need
            "iron_ore": {"loved": {f"npc_{i}" for i in range(15)}},  # 15 direct gift need
        }
        inv = {"iron_bar": 3, "iron_ore": 0}

        # Quest needs 5 iron_bar.
        # Surplus iron_bar is 3 - 1 = 2.
        # Remaining quest demand for iron_bar is 5 - 2 = 3.
        # Rolled up to iron_ore: 3 * 5 = 15 iron_ore.
        synthetic_quests = {
            "iron_bar": {
                "name": "Iron Bar",
                "quests": [
                    {
                        "quest_name": "Town Restoration",
                        "quest_type": "Town Upgrade",
                        "category": "Town Upgrade",
                        "amount": 5,
                        "requester": "Adeline",
                    }
                ],
            }
        }

        res = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory=inv,
            recipes=recipes,
            quest_data=synthetic_quests,
        )
        res_by_id = {item["item_id"]: item for item in res}
        assert "iron_ore" in res_by_id
        ore = res_by_id["iron_ore"]

        # Gift deficit: 15 demand - 10 effective inv (from 2 surplus iron_bar) = 5
        assert ore["gift_deficit"] == 5
        # Quest demand: 3 rem iron_bar * 5 ore/bar = 15
        assert ore["quest_demand"] == 15
        # Deficit: 5 + 15 = 20
        assert ore["deficit"] == 20
        assert ore["quest_count"] == 1
        assert ore["quest_categories"] == {"Town Upgrade": 1}
        assert len(ore["quest_summary"]) == 1
        summary = ore["quest_summary"][0]
        assert summary["quest_name"] == "Town Restoration"
        assert summary["amount"] == 5  # Quest requested 5 iron_bar
        assert summary["raw_amount_needed"] == 15  # Rolled up to 15 iron_ore
        assert summary["via_item_name"] == "Iron Bar"

    def test_crafted_quest_rollup_multi_tier(self):
        """Verifies multi-tier recipe tree rollups from crafted quest items to root raw materials."""
        recipes = {
            "bread": {
                "ingredients": [{"item_id": "flour", "count": 2}],
                "display_name": "Bread",
            },
            "flour": {
                "ingredients": [{"item_id": "wheat", "count": 3}],
                "display_name": "Flour",
            },
        }
        rem_map = {"wheat": {"loved": {"Hayden"}}}  # 1 gift need
        inv = {"wheat": 0}  # gift_deficit = 1
        synthetic_quests = {
            "bread": {
                "name": "Bread",
                "quests": [
                    {
                        "quest_name": "Restocking Mistria's Food Reserves 1",
                        "quest_type": "Town Upgrade",
                        "category": "Town Upgrade",
                        "amount": 4,
                        "requester": "Adeline",
                    }
                ],
            }
        }

        res = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory=inv,
            recipes=recipes,
            quest_data=synthetic_quests,
        )
        assert len(res) == 1
        wheat = res[0]
        assert wheat["item_id"] == "wheat"
        assert wheat["gift_deficit"] == 1
        # 4 bread * 2 flour * 3 wheat = 24 wheat
        assert wheat["quest_demand"] == 24
        assert wheat["deficit"] == 25
        assert len(wheat["quest_summary"]) == 1
        assert wheat["quest_summary"][0]["via_item_name"] == "Bread"
        assert wheat["quest_summary"][0]["amount"] == 4
        assert wheat["quest_summary"][0]["raw_amount_needed"] == 24

    def test_completed_quests_exclusion(self):
        """Verifies completed quests are excluded from quest demand."""
        rem_map = {"copper_ore": {"loved": {"March"}}}
        inv = {"copper_ore": 0}
        synthetic_quests = {
            "copper_ore": {
                "name": "Copper Ore",
                "quests": [
                    {"quest_name": "Request for Copper", "amount": 10, "category": "Request"},
                    {"quest_name": "Repair the Mill", "amount": 5, "category": "Town Upgrade"},
                ],
            }
        }

        # 1. No completed quests: both active -> 15 demand
        res1 = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory=inv,
            recipes={},
            quest_data=synthetic_quests,
            completed_quests=set(),
        )
        assert res1[0]["quest_demand"] == 15
        assert res1[0]["deficit"] == 16
        assert res1[0]["quest_count"] == 2

        # 2. One completed quest: only Repair the Mill active -> 5 demand
        res2 = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory=inv,
            recipes={},
            quest_data=synthetic_quests,
            completed_quests={"request_for_copper"},
        )
        assert res2[0]["quest_demand"] == 5
        assert res2[0]["deficit"] == 6
        assert res2[0]["quest_count"] == 1

        # 3. Both completed: quest demand is 0, deficit is gift_deficit
        res3 = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory=inv,
            recipes={},
            quest_data=synthetic_quests,
            completed_quests={"request_for_copper", "repair_the_mill"},
        )
        assert res3[0]["quest_demand"] == 0
        assert res3[0]["deficit"] == 1
        assert res3[0]["quest_count"] == 0
        assert res3[0]["quest_categories"] == {}
        assert res3[0]["quest_summary"] == []

    def test_completed_quests_via_save_object(self):
        """Verifies extracting completed quests from SaveData object."""
        rem_map = {"copper_ore": {"loved": {"March"}}}
        inv = {"copper_ore": 0}
        synthetic_quests = {
            "copper_ore": {
                "name": "Copper Ore",
                "quests": [
                    {"quest_name": "Request for Copper", "amount": 10},
                ],
            }
        }
        save = SaveData(Path("test.sav"), {"quests": json.dumps({"completed_quests": ["Request for Copper"]})})
        res = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory=inv,
            recipes={},
            quest_data=synthetic_quests,
            save=save,
        )
        assert res[0]["quest_demand"] == 0
        assert res[0]["deficit"] == 1

    def test_metadata_fields_types_and_structure(self):
        """Verifies the exact presence and types of all 6 quest metadata fields."""
        rem_map = {"copper_ore": {"loved": {"March"}}}
        inv = {"copper_ore": 0}
        synthetic_quests = {
            "copper_ore": {
                "name": "Copper Ore",
                "quests": [
                    {"quest_name": "Request for Copper", "quest_type": "Request", "category": "Request", "amount": 10, "requester": "March"},
                ],
            }
        }
        res = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory=inv,
            recipes={},
            quest_data=synthetic_quests,
        )
        assert len(res) == 1
        item = res[0]
        assert isinstance(item["gift_deficit"], int)
        assert isinstance(item["quest_demand"], int)
        assert isinstance(item["deficit"], int)
        assert isinstance(item["quest_count"], int)
        assert isinstance(item["quest_categories"], dict)
        assert isinstance(item["quest_summary"], list)

        summary_entry = item["quest_summary"][0]
        assert isinstance(summary_entry, dict)
        assert "quest_name" in summary_entry
        assert "quest_type" in summary_entry
        assert "category" in summary_entry
        assert "amount" in summary_entry
        assert "requester" in summary_entry
        assert "via_item_name" in summary_entry

    def test_minor_quest_title_aliases_integration(self):
        """Verifies the 4 minor quest title aliases in QUEST_TITLE_ALIASES resolve correctly."""
        rem_map = {"wood": {"loved": {"Adeline"}}}
        inv = {"wood": 0}
        synthetic_quests = {
            "wood": {
                "name": "Wood",
                "quests": [
                    {"quest_name": "The Mill Restoration Project", "amount": 10},
                    {"quest_name": "Upgrade the Inn", "amount": 10},
                    {"quest_name": "Expanding the Saturday Market", "amount": 10},
                    {"quest_name": "Request for Wild Berries", "amount": 10},
                ],
            }
        }
        # Save uses the internal game keys
        save_keys = {
            "repair_the_mill",
            "repair_the_inn",
            "upgrade_the_saturday_market",
            "request_for_wild_berry",
        }
        res = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory=inv,
            recipes={},
            quest_data=synthetic_quests,
            completed_quests=save_keys,
        )
        # All 4 aliased quests should be resolved as completed
        assert res[0]["quest_demand"] == 0
        assert res[0]["deficit"] == 1


# ==============================================================================
# 5. Tests for Milestone 2 (R2): build_focus_crafting_trees Quest Nodes
# ==============================================================================


class TestBuildFocusCraftingTreesQuestNodes:
    """Tests for terminal quest nodes in crafting trees and branch retention."""

    def test_quest_nodes_attached_to_direct_root(self):
        """Verifies terminal quest nodes are attached to root suggestion nodes."""
        suggestions = [
            {"item_id": "wood", "item_name": "Wood", "gift_deficit": 5, "quest_demand": 20, "deficit": 25}
        ]
        synthetic_quests = {
            "wood": {
                "name": "Wood",
                "quests": [
                    {
                        "quest_name": "Request for Wood",
                        "quest_type": "Request",
                        "category": "Request",
                        "amount": 20,
                        "requester": "Adeline",
                    }
                ],
            }
        }
        trees = build_focus_crafting_trees(
            focus_suggestions=suggestions,
            recipes={},
            quest_data=synthetic_quests,
            completed_quests=set(),
        )
        assert len(trees) == 1
        root = trees[0]
        assert root["item_id"] == "wood"
        assert len(root["children"]) == 1

        quest_node = root["children"][0]
        assert quest_node["is_quest"] is True
        assert quest_node["item_id"] == "_quest_request_for_wood"
        assert quest_node["item_name"] == "Request for Wood"
        assert quest_node["quest_type"] == "Request"
        assert quest_node["quest_category"] == "Request"
        assert quest_node["quest_amount"] == 20
        assert quest_node["requester"] == "Adeline"
        assert quest_node["via_item_name"] == "Wood"
        assert quest_node["children"] == []
        assert quest_node["gift_npcs"] == []
        assert quest_node["sprite_url"] == "/assets/sprites/npcs/adeline"

    def test_quest_nodes_attached_to_crafted_intermediate_node(self):
        """Verifies terminal quest nodes attach to downstream intermediate crafted nodes."""
        suggestions = [
            {"item_id": "milk", "item_name": "Milk", "gift_deficit": 1, "quest_demand": 3, "deficit": 4}
        ]
        recipes = {
            "cheese": {
                "item_id": "cheese",
                "display_name": "Cheese",
                "ingredients": [{"item_id": "milk", "count": 1}],
            }
        }
        rem_map = {"cheese": {"loved": {"Darcy"}}}
        synthetic_quests = {
            "cheese": {
                "name": "Cheese",
                "quests": [
                    {
                        "quest_name": "Restocking the Inn",
                        "quest_type": "Town Upgrade",
                        "category": "Town Upgrade",
                        "amount": 3,
                        "requester": "Darcy",
                    }
                ],
            }
        }
        trees = build_focus_crafting_trees(
            focus_suggestions=suggestions,
            recipes=recipes,
            remaining_items_map=rem_map,
            quest_data=synthetic_quests,
            completed_quests=set(),
        )
        assert len(trees) == 1
        root = trees[0]
        assert root["item_id"] == "milk"
        assert len(root["children"]) == 1

        cheese_node = root["children"][0]
        assert cheese_node["item_id"] == "cheese"
        assert len(cheese_node["children"]) == 1

        q_node = cheese_node["children"][0]
        assert q_node["is_quest"] is True
        assert q_node["item_id"] == "_quest_restocking_the_inn"
        assert q_node["item_name"] == "Restocking the Inn"
        assert q_node["via_item_name"] == "Cheese"

    def test_branch_retention_for_incomplete_quests(self):
        """
        Branch retention invariant: retain crafted branches if the product is required by
        an incomplete quest, even if it is NOT a pending gift for any NPC.
        """
        suggestions = [
            {"item_id": "milk", "item_name": "Milk", "gift_deficit": 1, "quest_demand": 2, "deficit": 3}
        ]
        recipes = {
            "butter": {
                "item_id": "butter",
                "display_name": "Butter",
                "ingredients": [{"item_id": "milk", "count": 1}],
            }
        }
        # Butter is NOT in remaining_items_map (no NPC wants butter)
        rem_map = {"cabbage": {"loved": {"March"}}}
        synthetic_quests = {
            "butter": {
                "name": "Butter",
                "quests": [
                    {
                        "quest_name": "Request for Butter",
                        "quest_type": "Request",
                        "category": "Request",
                        "amount": 2,
                        "requester": "Valen",
                    }
                ],
            }
        }

        # 1. When quest is incomplete, butter branch IS retained
        trees = build_focus_crafting_trees(
            focus_suggestions=suggestions,
            recipes=recipes,
            remaining_items_map=rem_map,
            quest_data=synthetic_quests,
            completed_quests=set(),
        )
        assert len(trees) == 1
        assert len(trees[0]["children"]) == 1
        butter_child = trees[0]["children"][0]
        assert butter_child["item_id"] == "butter"
        assert len(butter_child["children"]) == 1
        assert butter_child["children"][0]["is_quest"] is True

        # 2. When quest IS completed and no NPC wants butter, butter branch is pruned
        trees_completed = build_focus_crafting_trees(
            focus_suggestions=suggestions,
            recipes=recipes,
            remaining_items_map=rem_map,
            quest_data=synthetic_quests,
            completed_quests={"request_for_butter"},
        )
        assert len(trees_completed) == 1
        assert len(trees_completed[0]["children"]) == 0, "Unneeded branch without gifts or quests must be pruned"

    def test_completed_quest_nodes_not_attached(self):
        """Completed quests should not attach terminal quest nodes to trees."""
        suggestions = [
            {"item_id": "wood", "item_name": "Wood", "gift_deficit": 5, "quest_demand": 0, "deficit": 5}
        ]
        synthetic_quests = {
            "wood": {
                "name": "Wood",
                "quests": [
                    {"quest_name": "Request for Wood", "amount": 20, "requester": "Adeline"},
                ],
            }
        }
        trees = build_focus_crafting_trees(
            focus_suggestions=suggestions,
            recipes={},
            quest_data=synthetic_quests,
            completed_quests={"request_for_wood"},
        )
        assert len(trees) == 1
        assert len(trees[0]["children"]) == 0


class TestFutureWifeFilter:
    """Tests for Marriage-Exclusive Quest ('A Craving') Future Wife filtering."""

    def test_normalize_future_wife_and_predicate(self):
        from fom_planner.models import is_quest_applicable_for_future_wife, normalize_future_wife

        assert normalize_future_wife(None) == "none"
        assert normalize_future_wife("") == "none"
        assert normalize_future_wife("invalid_npc") == "none"
        assert normalize_future_wife("march") == "none"
        assert normalize_future_wife("Adeline") == "adeline"
        assert normalize_future_wife("ALL") == "all"

        craving_adeline = {"quest_name": "A Craving", "requester": "Adeline", "amount": 1}
        craving_celine = {"quest_name": "A Craving", "requester": "Celine", "amount": 1}
        normal_quest = {"quest_name": "Request for Wood", "requester": "Adeline", "amount": 20}

        assert is_quest_applicable_for_future_wife(normal_quest, "none") is True
        assert is_quest_applicable_for_future_wife(normal_quest, "celine") is True

        assert is_quest_applicable_for_future_wife(craving_adeline, "none") is False
        assert is_quest_applicable_for_future_wife(craving_adeline, "adeline") is True
        assert is_quest_applicable_for_future_wife(craving_celine, "adeline") is False
        assert is_quest_applicable_for_future_wife(craving_adeline, "all") is True
        assert is_quest_applicable_for_future_wife(craving_celine, "all") is True

    def test_compute_focus_suggestions_filters_a_craving_by_future_wife(self):
        from fom_planner.optimizer import load_recipes
        qd = load_quest_data()
        recipes = load_recipes()
        rem_map = {"wheat": {"loved": {"Adeline"}}}

        # 1. Default ("none"): "A Craving" is excluded
        res_none = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory={},
            recipes=recipes,
            quest_data=qd,
            completed_quests=set(),
            future_wife="none",
        )
        wheat_none = next(s for s in res_none if s["item_id"] == "wheat")
        craving_none = [q for q in wheat_none["quest_summary"] if q["quest_name"] == "A Craving"]
        assert len(craving_none) == 0

        # 2. "adeline": only Adeline's "A Craving" (Lemon Pie -> wheat) is included
        res_adeline = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory={},
            recipes=recipes,
            quest_data=qd,
            completed_quests=set(),
            future_wife="adeline",
        )
        wheat_adeline = next(s for s in res_adeline if s["item_id"] == "wheat")
        craving_adeline = [q for q in wheat_adeline["quest_summary"] if q["quest_name"] == "A Craving"]
        assert len(craving_adeline) == 1
        assert craving_adeline[0]["requester"] == "Adeline"
        assert wheat_adeline["quest_demand"] == wheat_none["quest_demand"] + 1
        assert wheat_adeline["quest_count"] == wheat_none["quest_count"] + 1
        assert sum(wheat_adeline["quest_categories"].values()) == wheat_adeline["quest_count"]

        # 3. "all": Adeline, Juniper, Reina, Seridia, and Valen all roll up to wheat with distinct quest_count
        res_all = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory={},
            recipes=recipes,
            quest_data=qd,
            completed_quests=set(),
            future_wife="all",
        )
        wheat_all = next(s for s in res_all if s["item_id"] == "wheat")
        craving_all = [q for q in wheat_all["quest_summary"] if q["quest_name"] == "A Craving"]
        assert {q["requester"] for q in craving_all} == {"Adeline", "Juniper", "Reina", "Seridia", "Valen"}
        assert wheat_all["quest_demand"] == wheat_none["quest_demand"] + 5
        assert wheat_all["quest_count"] == wheat_none["quest_count"] + 5
        assert sum(wheat_all["quest_categories"].values()) == wheat_all["quest_count"]

    def test_build_focus_crafting_trees_filters_a_craving(self):
        qd = load_quest_data()
        suggestions = [{"item_id": "lemon", "item_name": "Lemon", "deficit": 2}]
        recipes = {
            "lemon_pie": {
                "item_id": "lemon_pie",
                "display_name": "Lemon Pie",
                "ingredients": [{"item_id": "lemon", "count": 1}],
            }
        }

        trees_none = build_focus_crafting_trees(
            focus_suggestions=suggestions,
            recipes=recipes,
            remaining_items_map={},
            quest_data=qd,
            completed_quests=set(),
            future_wife="none",
        )
        # With future_wife="none", lemon_pie has no active quests or gift demand, so it is pruned
        child_ids_none = [c["item_id"] for c in trees_none[0]["children"]]
        assert "lemon_pie" not in child_ids_none

        trees_adeline = build_focus_crafting_trees(
            focus_suggestions=suggestions,
            recipes=recipes,
            remaining_items_map={},
            quest_data=qd,
            completed_quests=set(),
            future_wife="adeline",
        )
        lp_node = next(c for c in trees_adeline[0]["children"] if c["item_id"] == "lemon_pie")
        craving_nodes = [c for c in lp_node["children"] if c.get("is_quest")]
        assert len(craving_nodes) == 1
        assert craving_nodes[0]["item_id"] == "_quest_a_craving_adeline"
        assert craving_nodes[0]["requester"] == "Adeline"

    def test_config_future_wife_normalization(self):
        from companion.config import CompanionConfig, get_settings_schema
        from web.py.web_bridge import WebPlannerConfig

        c1 = CompanionConfig.from_dict({"future_wife": "Juniper"})
        assert c1.future_wife == "juniper"
        c2 = CompanionConfig.from_dict({"future_wife": "unknown"})
        assert c2.future_wife == "none"

        w1 = WebPlannerConfig({"future_wife": "Valen"})
        assert w1.future_wife == "valen"
        assert w1.to_dict()["future_wife"] == "valen"

        schema = get_settings_schema()
        focus_group = next(g for g in schema if g["id"] == "focus_suggestions")
        fw_field = next(f for f in focus_group["fields"] if f["key"] == "future_wife")
        assert fw_field["type"] == "select"
        assert len(fw_field["options"]) == 8
