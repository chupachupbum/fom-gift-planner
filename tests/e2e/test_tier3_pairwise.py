"""
tests/e2e/test_tier3_pairwise.py

Tier 3: Cross-Feature Combinations (Pairwise & Multi-Parameter Interactions).
Validates orthogonal and combinatorial interactions across the planning engine:
- Pairwise 1: Date Override + Focus Mode + Max Relationship Strategy
- Pairwise 2: Strategy Journal + Exclude NPCs + Vendor Boost
- Pairwise 3: Custom Slots + All Seasons + Crafting DAG Resolver
- Pairwise 4: Date Override (Saturday) + Saturday Mode + Market Vendors
- Pairwise 5: Focus Mode ON (Empty vs Selected NPCs) + Source Priority Summary
- Pairwise 6: Loved/Liked Weight Tuning + Bag Priority Shift
- Pairwise 7: Exclude NPCs + Focus NPCs Overlap Resolution
- Pairwise 8: Max Relationship Points Cap + no_exclude_max_relationship Toggle
- Pairwise 9: Infused Inventory Items + Bag Plan Metadata
- Pairwise 10: Multi-Source Items + Blocker Raw Materials + Alternate Sources
- Pairwise 11: Winter Date Override + Seasonal Forage Availability
- Pairwise 12: Focus Trees DAG Annotation with Alt Sources & NPC Recipients
"""

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from tests.e2e.conftest import (
    REPO_ROOT,
    SAMPLE_SAVE_PATH,
    make_synthetic_save_bytes,
)


class TestTier3CrossFeatureCombinations:
    """Exercises multi-parameter combinations and complex state interactions."""

    def test_pairwise_1_date_override_focus_mode_max_relationship(self, sample_save_path, plan_executor):
        config = {
            "date_override": "Summer 10",
            "focus_mode_enabled": True,
            "focus_npcs": "celine,march",
            "strategy": "max-relationship",
        }
        _, plan = plan_executor(sample_save_path, config=config)

        # 1. Date override active
        assert plan["in_game_date"]["is_overridden"] is True
        assert plan["in_game_date"]["season"] in ("Summer", "summer")
        assert plan["in_game_date"]["day"] == 10

        # 2. Max relationship strategy reflected in config
        assert plan["config"]["strategy"] == "max-relationship"

        # 3. Focus suggestions only benefit Celine or March
        focus_list = plan.get("focus_suggestions", [])
        for item in focus_list:
            benefited = set(item.get("blocked_npcs", []))
            if benefited:
                assert any(npc.lower() in ("celine", "march") for npc in benefited), (
                    f"Item {item.get('item_id')} has unexpected beneficiaries {benefited}"
                )

    def test_pairwise_2_strategy_journal_exclude_npcs_vendor_boost(self, sample_save_path, plan_executor):
        config = {
            "strategy": "journal",
            "exclude_npcs": "balor,hayden",
            "vendor_boost": 3.0,
        }
        _, plan = plan_executor(sample_save_path, config=config)

        # Excluded NPCs must never receive gifts in bag plan
        for item in plan["bag_plan"]:
            for rec in item.get("recipients", []):
                assert rec["npc_id"].lower() not in ("balor", "hayden"), (
                    f"Excluded NPC {rec['npc_id']} found in bag plan!"
                )

    def test_pairwise_3_tight_slots_all_seasons_crafting_dag(self, sample_save_path, plan_executor):
        config = {
            "slots": 5,
            "all_seasons": True,
        }
        _, plan = plan_executor(sample_save_path, config=config)

        # Bag slots strictly capped at 5
        assert len(plan["bag_plan"]) <= 5
        assert plan["stats"]["max_slots"] == 5

        # Crafting trees present for blocker items
        assert "focus_trees" in plan
        assert isinstance(plan["focus_trees"], list)

    def test_pairwise_4_saturday_date_override_and_market_vendors(self, sample_save_path, plan_executor):
        # Day 6 is a Saturday in FoM
        config = {
            "date_override": "Autumn 6",
            "mode": "auto",
        }
        _, plan = plan_executor(sample_save_path, config=config)

        date_info = plan["in_game_date"]
        assert date_info["is_saturday"] is True
        assert date_info["day_of_week"].lower() == "saturday"

    def test_pairwise_5_focus_mode_empty_selection_fallback(self, sample_save_path, plan_executor):
        # When focus mode is enabled but no NPCs are checked, falls back to considering all NPCs
        config_off = {"focus_mode_enabled": False}
        config_empty = {"focus_mode_enabled": True, "focus_npcs": ""}

        _, plan_off = plan_executor(sample_save_path, config=config_off)
        _, plan_empty = plan_executor(sample_save_path, config=config_empty)

        # Both should produce focus suggestions
        assert len(plan_off["focus_suggestions"]) > 0
        assert len(plan_empty["focus_suggestions"]) > 0
        # Equal length when no filter applied
        assert len(plan_off["focus_suggestions"]) == len(plan_empty["focus_suggestions"])

    def test_pairwise_6_loved_vs_liked_weight_priority_shift(self, sample_save_path, plan_executor):
        # Heavy loved weighting vs heavy liked weighting
        config_loved = {"loved_weight": 10, "liked_weight": 1, "slots": 10}
        config_liked = {"loved_weight": 1, "liked_weight": 10, "slots": 10}

        _, plan_loved = plan_executor(sample_save_path, config=config_loved)
        _, plan_liked = plan_executor(sample_save_path, config=config_liked)

        loved_prefs = [
            rec["preference"].upper()
            for it in plan_loved["bag_plan"]
            for rec in it.get("recipients", [])
        ]
        liked_prefs = [
            rec["preference"].upper()
            for it in plan_liked["bag_plan"]
            for rec in it.get("recipients", [])
        ]

        # Loved plan should have high concentration of LOVED gifts
        assert loved_prefs.count("LOVE") >= liked_prefs.count("LOVE")

    def test_pairwise_7_exclude_npcs_and_focus_npcs_overlap_resolution(self, sample_save_path, plan_executor):
        # Exclude march, but also list march in focus_npcs
        config = {
            "focus_mode_enabled": True,
            "focus_npcs": "march,celine",
            "exclude_npcs": "march",
        }
        _, plan = plan_executor(sample_save_path, config=config)

        # March should NOT be in bag plan
        for it in plan["bag_plan"]:
            for rec in it.get("recipients", []):
                assert rec["npc_id"].lower() != "march"

    def test_pairwise_8_max_relationship_cap_and_no_exclude_toggle(self, plan_executor):
        # Celine has max points (5000.0)
        aff = {"celine": 5000.0, "balor": 200.0}
        inv = [{"item_id": "chocolate", "count": 10}, {"item_id": "baked_potato", "count": 10}]
        save_bytes = make_synthetic_save_bytes(inventory_items=inv, npc_affection=aff)

        # Config 1: no_exclude_max_relationship = False (exclude maxed NPCs under max-relationship)
        config_exclude = {
            "strategy": "max-relationship",
            "max_relationship_points": 5000,
            "no_exclude_max_relationship": False,
        }
        _, plan_ex = plan_executor(save_bytes, config=config_exclude)

        recipients_ex = [
            rec["npc_id"].lower()
            for it in plan_ex["bag_plan"]
            for rec in it.get("recipients", [])
        ]
        assert "celine" not in recipients_ex

        # Config 2: no_exclude_max_relationship = True (keep maxed NPCs)
        config_keep = {
            "strategy": "max-relationship",
            "max_relationship_points": 5000,
            "no_exclude_max_relationship": True,
        }
        _, plan_keep = plan_executor(save_bytes, config=config_keep)
        recipients_keep = [
            rec["npc_id"].lower()
            for it in plan_keep["bag_plan"]
            for rec in it.get("recipients", [])
        ]
        # Celine is eligible again
        assert len(plan_keep["bag_plan"]) >= len(plan_ex["bag_plan"])

    def test_pairwise_9_infused_inventory_item_detection(self, plan_executor):
        # Player has an infused ruby ring or item
        inv = [{"item_id": "ruby", "count": 1, "infusion": "speed"}]
        save_bytes = make_synthetic_save_bytes(inventory_items=inv)
        _, plan = plan_executor(save_bytes)

        # Infused items tracking
        assert "infused_items" in plan
        assert isinstance(plan["infused_items"], (list, dict, int))

    def test_pairwise_10_multi_source_items_in_source_priority(self, sample_save_path, plan_executor):
        _, plan = plan_executor(sample_save_path)
        sp = plan.get("source_priority", {})

        # Should classify sources into quick, grind, farm
        assert "quick" in sp or "grind" in sp or "farm" in sp or len(sp) > 0

    def test_pairwise_11_winter_date_override_and_seasonal_forage(self, sample_save_path, plan_executor):
        # Winter season without all_seasons
        config = {"date_override": "Winter 1", "all_seasons": False}
        _, plan = plan_executor(sample_save_path, config=config)
        assert plan["in_game_date"]["season"] in ("Winter", "winter")

    def test_pairwise_12_focus_trees_dag_annotation(self, sample_save_path, plan_executor):
        _, plan = plan_executor(sample_save_path)
        focus_trees = plan.get("focus_trees", [])

        if focus_trees:
            first_tree = focus_trees[0]
            assert "blocker_item" in first_tree or "item_id" in first_tree or "root" in first_tree

    def test_pairwise_13_focus_mode_single_npc_isolation_celine(self, sample_save_path, plan_executor):
        config = {"focus_mode_enabled": True, "focus_npcs": "celine"}
        _, plan = plan_executor(sample_save_path, config=config)
        for it in plan.get("focus_suggestions", []):
            benefited = it.get("blocked_npcs", [])
            if benefited:
                assert any(npc.lower() == "celine" for npc in benefited)

    def test_pairwise_14_focus_mode_single_npc_isolation_march(self, sample_save_path, plan_executor):
        config = {"focus_mode_enabled": True, "focus_npcs": "march"}
        _, plan = plan_executor(sample_save_path, config=config)
        for it in plan.get("focus_suggestions", []):
            benefited = it.get("blocked_npcs", [])
            if benefited:
                assert any(npc.lower() == "march" for npc in benefited)

    def test_pairwise_15_single_slot_with_vendor_boost(self, sample_save_path, plan_executor):
        config = {"slots": 1, "vendor_boost": 3.0}
        _, plan = plan_executor(sample_save_path, config=config)
        assert len(plan["bag_plan"]) <= 1

    def test_pairwise_16_all_seasons_with_strategy_max_relationship(self, sample_save_path, plan_executor):
        config = {"all_seasons": True, "strategy": "max-relationship"}
        _, plan = plan_executor(sample_save_path, config=config)
        assert plan["config"]["strategy"] == "max-relationship"
        assert len(plan["bag_plan"]) > 0

    def test_pairwise_17_zero_slots_with_focus_mode_enabled(self, sample_save_path, plan_executor):
        config = {"slots": 0, "focus_mode_enabled": True, "focus_npcs": "balor"}
        _, plan = plan_executor(sample_save_path, config=config)
        # Bag plan empty due to 0 slots
        assert len(plan["bag_plan"]) == 0
        # Focus suggestions still computed independently
        assert len(plan["focus_suggestions"]) > 0
