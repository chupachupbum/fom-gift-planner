"""
tests/core/test_challenger_m2_quest_deficit.py

Adversarial Challenger Stress Harness for Milestone 2:
- compute_focus_suggestions() combined deficit math
- Zero-gift-deficit gating isolation
- Intermediate inventory deduction & surplus rollup
- Multi-tier crafted recipe rollups
- Sorting stability and impact-priority invariance
- Real save end-to-end integration
"""

import json
from pathlib import Path
import pytest

from fom_planner.data_loader import load_quest_data
from fom_planner.models import SaveData
from fom_planner.optimizer import compute_focus_suggestions, resolve_root_raw_materials
from fom_planner.parser import parse_save_file


class TestAdversarialZeroGiftDeficitGating:
    """Stress tests verifying that items with gift_deficit == 0 NEVER enter focus suggestions."""

    def test_real_game_items_without_gift_preferences_never_appear(self):
        """
        Loads all real items from quest_data.json that have no loved/liked preferences
        in item_data.json (126 real game items like stone_loach, sealing_scroll, faceted_rock_gem).
        Even when all quests are incomplete, ZERO of these items must enter focus suggestions.
        """
        quest_data = load_quest_data()
        with open("data/item_data.json", "r", encoding="utf-8") as f:
            item_data = json.load(f)
        items_db = item_data.get("items", {})

        # Identify items with 0 gift preferences in the entire game
        zero_pref_items = set()
        for item_id in quest_data:
            entry = items_db.get(item_id)
            if not entry or (not entry.get("loved_by") and not entry.get("liked_by")):
                zero_pref_items.add(item_id)

        assert len(zero_pref_items) >= 100, f"Expected at least 100 zero-pref quest items, got {len(zero_pref_items)}"

        # Mock a remaining_items_map that has preferences for ordinary items (e.g. strawberry, cabbage)
        rem_map = {
            "strawberry": {"loved": {"Adeline", "Celine"}},
            "cabbage": {"liked": {"March"}},
        }

        # Run with empty inventory, all quests active
        res = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory={},
            recipes={},
            quest_data=quest_data,
            completed_quests=set(),
            top_n=1000,
        )

        suggested_ids = {item["item_id"] for item in res}
        # Invariant: Not a single zero_pref_item may appear in suggestions
        leaked_items = suggested_ids & zero_pref_items
        assert not leaked_items, f"Leaked items with 0 gift preferences into focus suggestions: {leaked_items}"

    def test_synthetic_gigantic_quest_demand_zero_gift_item(self):
        """Even with 1,000,000 quest demand, an item absent from remaining_items_map must not leak."""
        rem_map = {"apple": {"loved": {"Hayden"}}}
        synthetic_quests = {
            "hyper_ore": {
                "name": "Hyper Ore",
                "quests": [
                    {
                        "quest_name": "Galactic Restoration",
                        "quest_type": "Story Quest",
                        "category": "Story Quest",
                        "amount": 1_000_000,
                        "requester": "Alien",
                    }
                ],
            }
        }
        res = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory={},
            recipes={},
            quest_data=synthetic_quests,
            top_n=100,
        )
        suggested_ids = {item["item_id"] for item in res}
        assert "hyper_ore" not in suggested_ids
        assert len(res) == 1
        assert res[0]["item_id"] == "apple"

    def test_satisfied_gift_inventory_with_massive_quest_demand(self):
        """
        If an item has gift demand, but the player already owns enough inventory to satisfy it,
        gift_deficit == 0. Even if incomplete quests demand 5,000 units, the item MUST NOT appear.
        """
        rem_map = {
            "iron_ore": {"loved": {"March"}, "liked": {"Olric"}},  # 2 gift demand
        }
        inv = {"iron_ore": 2}  # 2 owned -> gift_deficit = 2 - 2 = 0
        synthetic_quests = {
            "iron_ore": {
                "name": "Iron Ore",
                "quests": [
                    {
                        "quest_name": "Town Upgrade: Blacksmith",
                        "quest_type": "Town Upgrade",
                        "category": "Town Upgrade",
                        "amount": 5000,
                        "requester": "Adeline",
                    }
                ],
            }
        }
        res = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory=inv,
            recipes={},
            quest_data=synthetic_quests,
        )
        assert len(res) == 0, "Item with satisfied gift demand (gift_deficit == 0) must be gated out"

    def test_focus_mode_filtering_gates_unselected_npc_quest_items(self):
        """
        When focus mode is active with selected NPCs, an item that is only desired by
        an UNSELECTED NPC must be excluded from suggestions even if it has quest demand.
        """
        rem_map = {
            "wood": {"loved": {"Adeline"}},
            "stone": {"loved": {"March"}},
        }
        synthetic_quests = {
            "stone": {
                "name": "Stone",
                "quests": [
                    {"quest_name": "Fix the Well", "category": "Story Quest", "amount": 100}
                ],
            }
        }
        # Player enables focus mode for Adeline only
        res = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory={},
            recipes={},
            quest_data=synthetic_quests,
            focus_mode_enabled=True,
            focus_npcs={"Adeline"},
        )
        suggested_ids = {item["item_id"] for item in res}
        assert "wood" in suggested_ids
        assert "stone" not in suggested_ids, "stone has 0 gift deficit for Adeline; quest demand must not bypass focus mode"


class TestAdversarialCombinedDeficitMath:
    """Stress tests verifying deficit == gift_deficit + quest_demand and metadata integrity."""

    def test_multiple_quests_same_item_aggregation(self):
        """
        An item with multiple quests across different categories must aggregate
        raw amounts correctly, deduplicate names for quest_count, and tally quest_categories.
        """
        rem_map = {"copper_ore": {"loved": {"March"}, "liked": {"Celine"}}}  # 2 gift need
        inv = {"copper_ore": 0}  # gift_deficit = 2
        synthetic_quests = {
            "copper_ore": {
                "name": "Copper Ore",
                "quests": [
                    {"quest_name": "Request for Copper 1", "quest_type": "Request", "category": "Request", "amount": 5, "requester": "March"},
                    {"quest_name": "Request for Copper 2", "quest_type": "Request", "category": "Request", "amount": 10, "requester": "Olric"},
                    {"quest_name": "Town Upgrade: Mine Bridge", "quest_type": "Town Upgrade", "category": "Town Upgrade", "amount": 25, "requester": "Adeline"},
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
        assert item["gift_deficit"] == 2
        assert item["quest_demand"] == 40  # 5 + 10 + 25
        assert item["deficit"] == 42  # 2 + 40
        assert item["quest_count"] == 3
        assert item["quest_categories"] == {"Request": 2, "Town Upgrade": 1}
        assert len(item["quest_summary"]) == 3
        summary_qnames = [q["quest_name"] for q in item["quest_summary"]]
        assert summary_qnames == ["Request for Copper 1", "Request for Copper 2", "Town Upgrade: Mine Bridge"]

    def test_partial_gift_inventory_combined_deficit(self):
        """Tests partial inventory fulfillment for gift demand combined with quests."""
        rem_map = {"iron_ore": {"loved": {f"npc_{i}" for i in range(10)}}}  # 10 gift need
        inv = {"iron_ore": 4}  # 4 owned -> gift_deficit = 6
        synthetic_quests = {
            "iron_ore": {
                "name": "Iron Ore",
                "quests": [
                    {"quest_name": "Deep Digging", "category": "Story Quest", "amount": 15}
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
        assert item["gift_deficit"] == 6
        assert item["quest_demand"] == 15
        assert item["deficit"] == 21

    def test_completed_quests_filter_precision(self):
        """Tests that only uncompleted quests contribute to quest_demand and metadata."""
        rem_map = {"gold_ore": {"loved": {"Balor"}}}
        inv = {"gold_ore": 0}
        synthetic_quests = {
            "gold_ore": {
                "name": "Gold Ore",
                "quests": [
                    {"quest_name": "Golden Statue Project", "category": "Story Quest", "amount": 50},
                    {"quest_name": "Request for Gold", "category": "Request", "amount": 5},
                    {"quest_name": "Balor's Secret Order", "category": "Request", "amount": 10},
                ],
            }
        }
        # Mark 2 quests completed
        completed = {"golden_statue_project", "request_for_gold"}
        res = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory=inv,
            recipes={},
            quest_data=synthetic_quests,
            completed_quests=completed,
        )
        assert len(res) == 1
        item = res[0]
        assert item["gift_deficit"] == 1
        assert item["quest_demand"] == 10
        assert item["deficit"] == 11
        assert item["quest_count"] == 1
        assert item["quest_categories"] == {"Request": 1}
        assert len(item["quest_summary"]) == 1
        assert item["quest_summary"][0]["quest_name"] == "Balor's Secret Order"


class TestAdversarialIntermediateInventoryDeduction:
    """Stress tests verifying surplus intermediate inventory deduction and rollups."""

    def test_surplus_intermediate_craft_inventory_deduction(self):
        """
        Item: silver_ingot (crafted from 5 silver_ore).
        Player owns 7 silver_ingot.
        Direct gift demand for silver_ingot is 2 (e.g. 2 NPCs love silver_ingot).
        Surplus silver_ingot = 7 - 2 = 5.
        Quest demands 8 silver_ingot.
        Used surplus = min(5, 8) = 5.
        Remaining quest demand = 8 - 5 = 3 silver_ingot.
        Rolled up to silver_ore: 3 * 5 = 15 silver_ore.
        """
        recipes = {
            "silver_ingot": {
                "ingredients": [{"item_id": "silver_ore", "count": 5}],
                "display_name": "Silver Ingot",
            },
            # Non-intermediate: silver_ingot is not used in another recipe here
        }
        rem_map = {
            "silver_ingot": {"loved": {"March", "Valen"}},  # 2 direct gift need
            "silver_ore": {"loved": {"Olric"}},  # 1 direct gift need
        }
        inv = {
            "silver_ingot": 7,  # 2 reserved for gifts, 5 surplus
            "silver_ore": 0,    # 0 owned -> gift_deficit = 1
        }
        synthetic_quests = {
            "silver_ingot": {
                "name": "Silver Ingot",
                "quests": [
                    {
                        "quest_name": "Town Beautification",
                        "category": "Town Upgrade",
                        "amount": 8,
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
        # silver_ingot has 2 needed, 7 owned -> gift_deficit = 0 -> gated out!
        assert "silver_ingot" not in res_by_id

        # silver_ore has gift_deficit = 1, quest_demand = 15 -> deficit = 16
        assert "silver_ore" in res_by_id
        ore = res_by_id["silver_ore"]
        assert ore["gift_deficit"] == 1
        assert ore["quest_demand"] == 15
        assert ore["deficit"] == 16
        assert ore["quest_summary"][0]["raw_amount_needed"] == 15
        assert ore["quest_summary"][0]["via_item_name"] == "Silver Ingot"

    def test_surplus_intermediate_fully_covers_quest_demand(self):
        """
        If player's surplus intermediate inventory equals or exceeds quest demand,
        remaining quest demand is 0, so root raw materials receive 0 quest demand.
        """
        recipes = {
            "cheese": {
                "ingredients": [{"item_id": "cow_milk", "count": 1}],
                "display_name": "Cheese",
            }
        }
        rem_map = {
            "cheese": {"loved": {"Celine"}},  # 1 direct gift need
            "cow_milk": {"loved": {"Hayden"}},  # 1 direct gift need
        }
        # Player has 10 cheese, 0 cow_milk.
        # Direct gift need for cheese = 1. Surplus cheese = 9.
        # Quest needs 5 cheese. Surplus (9) >= 5, so rem_q_amount = 0.
        inv = {"cheese": 10, "cow_milk": 0}
        synthetic_quests = {
            "cheese": {
                "name": "Cheese",
                "quests": [
                    {"quest_name": "Restocking Cheese", "category": "Request", "amount": 5}
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
        # cheese has 0 gift deficit -> gated out
        assert "cheese" not in res_by_id

        # If cow_milk is in res, its quest_demand must be 0!
        if "cow_milk" in res_by_id:
            assert res_by_id["cow_milk"]["quest_demand"] == 0


class TestAdversarialMultiTierCraftedRollups:
    """Stress tests for multi-tier crafting chains, branching recipes, and cyclic safety."""

    def test_three_tier_crafting_rollup(self):
        """
        Tier 3: royal_sword -> 2 steel_ingot, 1 ruby
        Tier 2: steel_ingot -> 3 iron_ore, 1 coal
        Tier 1: iron_ore, coal, ruby (root raw materials)

        Quest demands 5 royal_sword.
        Player has 0 royal_sword, 0 steel_ingot.
        Root rollups:
        - iron_ore: 5 * 2 * 3 = 30
        - coal: 5 * 2 * 1 = 10
        - ruby: 5 * 1 = 5
        """
        recipes = {
            "royal_sword": {
                "ingredients": [
                    {"item_id": "steel_ingot", "count": 2},
                    {"item_id": "ruby", "count": 1},
                ],
                "display_name": "Royal Sword",
            },
            "steel_ingot": {
                "ingredients": [
                    {"item_id": "iron_ore", "count": 3},
                    {"item_id": "coal", "count": 1},
                ],
                "display_name": "Steel Ingot",
            },
        }
        rem_map = {
            "iron_ore": {"loved": {"March"}},  # 1 gift need
            "coal": {"loved": {"Darcy"}},  # 1 gift need
            "ruby": {"loved": {"Valen"}},  # 1 gift need
        }
        inv = {"iron_ore": 0, "coal": 0, "ruby": 0}
        synthetic_quests = {
            "royal_sword": {
                "name": "Royal Sword",
                "quests": [
                    {"quest_name": "Royal Armory Upgrade", "category": "Story Quest", "amount": 5}
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
        assert res_by_id["iron_ore"]["gift_deficit"] == 1
        assert res_by_id["iron_ore"]["quest_demand"] == 30
        assert res_by_id["iron_ore"]["deficit"] == 31

        assert "coal" in res_by_id
        assert res_by_id["coal"]["gift_deficit"] == 1
        assert res_by_id["coal"]["quest_demand"] == 10
        assert res_by_id["coal"]["deficit"] == 11

        assert "ruby" in res_by_id
        assert res_by_id["ruby"]["gift_deficit"] == 1
        assert res_by_id["ruby"]["quest_demand"] == 5
        assert res_by_id["ruby"]["deficit"] == 6

    def test_cyclic_recipes_termination_and_safety(self):
        """
        Adversarial recipe input with cyclic references (A -> B -> A).
        Both resolve_root_raw_materials and compute_focus_suggestions must terminate safely.
        """
        cyclic_recipes = {
            "item_a": {
                "ingredients": [{"item_id": "item_b", "count": 1}],
                "display_name": "Item A",
            },
            "item_b": {
                "ingredients": [{"item_id": "item_a", "count": 1}],
                "display_name": "Item B",
            },
        }
        # Verify resolve_root_raw_materials terminates
        roots = resolve_root_raw_materials("item_a", cyclic_recipes)
        assert isinstance(roots, dict)

        rem_map = {"item_a": {"loved": {"March"}}}
        synthetic_quests = {
            "item_a": {
                "name": "Item A",
                "quests": [{"quest_name": "Cycle Quest", "amount": 10}],
            }
        }
        # compute_focus_suggestions must not throw RecursionError
        res = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory={"item_a": 0},
            recipes=cyclic_recipes,
            quest_data=synthetic_quests,
        )
        assert len(res) >= 1


class TestAdversarialSortingInvariance:
    """
    Stress tests verifying sorting behavior:
    In 'impact' mode (default), high-impact gift items MUST remain ahead of
    low-impact items, even when low-impact items have gigantic quest demands.
    """

    def test_high_impact_gift_remains_top_despite_gigantic_quest_demand_on_low_impact_item(self):
        """
        Item A: Strawberry
          - 10 NPCs love it -> blocked_pairs = 10, weighted_impact = 10
          - gift_deficit = 10, quest_demand = 0, deficit = 10
        Item B: Stone
          - 1 NPC loves it -> blocked_pairs = 1, weighted_impact = 1
          - gift_deficit = 1, quest_demand = 10,000, deficit = 10,001

        Under focus_sort="impact" (default):
        Strawberry MUST be Rank 1, Stone MUST be Rank 2.
        """
        rem_map = {
            "strawberry": {"loved": {f"npc_{i}" for i in range(10)}},
            "stone": {"loved": {"Olric"}},
        }
        inv = {"strawberry": 0, "stone": 0}
        synthetic_quests = {
            "stone": {
                "name": "Stone",
                "quests": [
                    {
                        "quest_name": "Grand Citadel Construction",
                        "category": "Story Quest",
                        "amount": 10_000,
                    }
                ],
            }
        }
        res = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory=inv,
            recipes={},
            quest_data=synthetic_quests,
            focus_sort="impact",
        )
        assert len(res) == 2
        # Rank 1 must be strawberry
        assert res[0]["item_id"] == "strawberry"
        assert res[0]["rank"] == 1
        assert res[0]["weighted_impact"] >= 10.0
        assert res[0]["deficit"] == 10

        # Rank 2 must be stone
        assert res[1]["item_id"] == "stone"
        assert res[1]["rank"] == 2
        assert res[1]["weighted_impact"] == 1.0
        assert res[1]["deficit"] == 10_001

    def test_tiebreaking_by_deficit_when_weighted_impact_is_equal(self):
        """
        When two items have the SAME weighted impact, the secondary sort key
        is -deficit, so the item with higher quest demand ranks higher.
        """
        rem_map = {
            "item_low_quest": {"loved": {"March", "Celine"}},   # 2 blocked pairs
            "item_high_quest": {"loved": {"Adeline", "Balor"}}, # 2 blocked pairs
        }
        inv = {"item_low_quest": 0, "item_high_quest": 0}
        synthetic_quests = {
            "item_low_quest": {
                "name": "Item Low Quest",
                "quests": [{"quest_name": "Small Quest", "amount": 5}],
            },
            "item_high_quest": {
                "name": "Item High Quest",
                "quests": [{"quest_name": "Massive Quest", "amount": 100}],
            },
        }
        res = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory=inv,
            recipes={},
            quest_data=synthetic_quests,
            focus_sort="impact",
        )
        assert len(res) == 2
        # Both have weighted_impact == 2.0
        assert res[0]["weighted_impact"] == 2.0
        assert res[1]["weighted_impact"] == 2.0
        # item_high_quest has deficit 102 vs 7, so it must win the tiebreaker
        assert res[0]["item_id"] == "item_high_quest"
        assert res[0]["deficit"] == 102
        assert res[1]["item_id"] == "item_low_quest"
        assert res[1]["deficit"] == 7

    def test_deficit_sort_mode_prioritizes_quest_demand(self):
        """
        When focus_sort="deficit", deficit descending is the PRIMARY sort key.
        The item with large quest demand ranks first.
        """
        rem_map = {
            "strawberry": {"loved": {f"npc_{i}" for i in range(10)}},  # impact 10, deficit 10
            "stone": {"loved": {"Olric"}},  # impact 1, deficit 500
        }
        synthetic_quests = {
            "stone": {
                "name": "Stone",
                "quests": [{"quest_name": "Quarry Delivery", "amount": 499}],
            }
        }
        res = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory={},
            recipes={},
            quest_data=synthetic_quests,
            focus_sort="deficit",
        )
        assert len(res) == 2
        assert res[0]["item_id"] == "stone"
        assert res[0]["deficit"] == 500
        assert res[1]["item_id"] == "strawberry"
        assert res[1]["deficit"] == 10

    def test_quick_wins_sort_mode_prioritizes_smallest_deficit(self):
        """
        When focus_sort="quick-wins", deficit ascending is the PRIMARY sort key.
        The item with smallest deficit ranks first.
        """
        rem_map = {
            "turnip": {"loved": {"Adeline"}},  # gift_deficit 1, quest 0 -> deficit 1
            "stone": {"loved": {"Olric"}},    # gift_deficit 1, quest 50 -> deficit 51
        }
        synthetic_quests = {
            "stone": {
                "name": "Stone",
                "quests": [{"quest_name": "Quarry Delivery", "amount": 50}],
            }
        }
        res = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory={},
            recipes={},
            quest_data=synthetic_quests,
            focus_sort="quick-wins",
        )
        assert len(res) == 2
        assert res[0]["item_id"] == "turnip"
        assert res[0]["deficit"] == 1
        assert res[1]["item_id"] == "stone"
        assert res[1]["deficit"] == 51


class TestAdversarialRealSaveEndToEnd:
    """Stress tests on the real game save file (samples/sample_save.sav)."""

    def test_real_save_focus_suggestions_invariants(self):
        """
        Parses sample_save.sav, runs full planning pipeline, and asserts:
        1. Every focus suggestion has gift_deficit > 0.
        2. Every focus suggestion has deficit == gift_deficit + quest_demand.
        3. If quest_demand > 0: quest_count > 0, len(quest_summary) > 0,
           and sum(quest_categories.values()) == quest_count.
        4. If quest_demand == 0: quest_count == 0, len(quest_summary) == 0, quest_categories == {}.
        5. Zero-gift-demand quest items (e.g. stone_loach, sealing_scroll) never appear.
        """
        save_path = Path("samples/sample_save.sav")
        assert save_path.exists(), "samples/sample_save.sav must exist"
        save = parse_save_file(save_path)

        quest_data = load_quest_data()
        assert len(quest_data) > 0

        # Load game databases
        with open("data/item_data.json", "r", encoding="utf-8") as f:
            item_data = json.load(f)
        with open("data/recipes.json", "r", encoding="utf-8") as f:
            recipes = json.load(f)

        # Build remaining_items_map for ungifted NPCs in save
        # Simulate typical remaining map from item_data
        rem_map = {}
        for item_id, item_entry in item_data.get("items", {}).items():
            if not isinstance(item_entry, dict):
                continue
            loved = set(item_entry.get("loved_by", []))
            liked = set(item_entry.get("liked_by", []))
            if loved or liked:
                rem_map[item_id] = {"loved": loved, "liked": liked}

        completed_keys = save.get_completed_quest_keys()

        res = compute_focus_suggestions(
            remaining_items_map=rem_map,
            inventory=save.inventory,
            recipes=recipes,
            item_metadata=item_data.get("items", {}),
            quest_data=quest_data,
            completed_quests=completed_keys,
            save=save,
            top_n=50,
        )

        assert len(res) > 0, "Expected at least some focus suggestions"

        for s in res:
            # 1. Gate invariant: gift_deficit > 0
            assert s["gift_deficit"] > 0, f"Item {s['item_id']} violated gate invariant: gift_deficit={s['gift_deficit']}"

            # 2. Combined deficit math: deficit == gift_deficit + quest_demand
            assert s["deficit"] == s["gift_deficit"] + s["quest_demand"], (
                f"Item {s['item_id']} deficit math mismatch: {s['deficit']} != {s['gift_deficit']} + {s['quest_demand']}"
            )

            # 3. Quest metadata consistency
            if s["quest_demand"] > 0:
                assert s["quest_count"] > 0, f"Item {s['item_id']} has quest_demand > 0 but quest_count == 0"
                assert len(s["quest_summary"]) > 0, f"Item {s['item_id']} has quest_demand > 0 but empty quest_summary"
                assert sum(s["quest_categories"].values()) == s["quest_count"], (
                    f"Item {s['item_id']} category sum mismatch: {sum(s['quest_categories'].values())} != {s['quest_count']}"
                )
                for q in s["quest_summary"]:
                    assert "quest_name" in q
                    assert "category" in q
                    assert "raw_amount_needed" in q
                    assert q["raw_amount_needed"] > 0
            else:
                assert s["quest_count"] == 0
                assert len(s["quest_summary"]) == 0
                assert s["quest_categories"] == {}

            # 4. Rank continuity
            assert 1 <= s["rank"] <= len(res)
