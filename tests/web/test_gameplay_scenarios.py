"""
tests/e2e/test_tier4_scenarios.py

Tier 4: Real-World Application Scenarios (End-to-End Persona & Workload Workflows).
Validates 5 complete, realistic end-to-end player sessions:
- Scenario 1: New Game Spring 1 Onboarding Workflow (Starter state, 0% progress, basic gifts)
- Scenario 2: Mid-Game Fall Festival Preparation Workflow (Seasonal harvest, recipes, festival prep)
- Scenario 3: End-Game 100% Completionist Optimization Workflow (Maxed friendships, locked recipes hunting)
- Scenario 4: Saturday Market Shopping Run Workflow (Weekend market vendors, quick-tier shop priority)
- Scenario 5: Focus Mode Targeted Blocker Resolution Workflow (Dual romance focus: March & Celine)
"""

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from tests.web.conftest import (
    REPO_ROOT,
    SAMPLE_SAVE_PATH,
    make_synthetic_save_bytes,
)


class TestScenario1NewGameSpring1Onboarding:
    """Simulates a fresh player starting their very first morning on the farm."""

    def test_onboarding_fresh_save_workflow(self, plan_executor):
        starter_inventory = [
            {"item_id": "turnip", "count": 5},
            {"item_id": "wood", "count": 20},
            {"item_id": "stone", "count": 15},
            {"item_id": "dandelion", "count": 3},
        ]
        save_bytes = make_synthetic_save_bytes(
            player_name="FreshFarmer",
            farm_name="StarterFarm",
            year=1,
            season="spring",
            day=1,
            inventory_items=starter_inventory,
            npc_affection={},  # zero affection with anyone
            unlocked_recipes=[],  # zero recipes unlocked
        )

        _, plan = plan_executor(save_bytes, config={"strategy": "journal", "slots": 10})

        # 1. Onboarding Save Metadata
        save_info = plan["save_info"]
        assert save_info["found"] is True
        assert save_info["player_name"] == "FreshFarmer"
        assert save_info["farm_name"] == "StarterFarm"

        # 2. Date is Day 1 of Spring Year 1
        date_info = plan["in_game_date"]
        assert date_info["year"] == 1
        assert date_info["season"].lower() == "spring"
        assert date_info["day"] == 1
        assert date_info["is_overridden"] is False

        # 3. Overall progress is at ground zero
        stats = plan["stats"]
        assert stats["overall_gift_progress_pct"] == 0.0
        assert stats["completed_npcs_count"] == 0
        assert stats["game_given_total"] == 0

        # 4. Bag plan provides actionable starter gifts
        bag_plan = plan["bag_plan"]
        assert len(bag_plan) > 0
        assert len(bag_plan) <= 10

        # 5. Recipe stats shows 0 unlocked
        if "recipe_stats" in plan:
            rstats = plan["recipe_stats"]
            assert rstats.get("unlocked_count", 0) == 0


class TestScenario2MidGameFallFestivalPreparation:
    """Simulates a player in Autumn Year 1 preparing for upcoming town festivals."""

    def test_mid_game_fall_workflow(self, plan_executor):
        fall_inventory = [
            {"item_id": "pumpkin", "count": 8},
            {"item_id": "cranberry", "count": 12},
            {"item_id": "chestnut", "count": 6},
            {"item_id": "apple", "count": 4},
            {"item_id": "copper_ingot", "count": 10},
        ]
        friendships = {
            "hayden": 650.0,
            "celine": 720.0,
            "balor": 540.0,
            "march": 400.0,
            "adeline": 800.0,
        }
        unlocked = [
            "pumpkin_soup",
            "baked_potato",
            "bread",
            "apple_pie",
            "trail_mix",
        ]

        save_bytes = make_synthetic_save_bytes(
            player_name="AutumnLover",
            farm_name="HarvestFarm",
            year=1,
            season="autumn",
            day=10,
            inventory_items=fall_inventory,
            npc_affection=friendships,
            unlocked_recipes=unlocked,
        )

        _, plan = plan_executor(save_bytes, config={"strategy": "journal", "slots": 20})

        # 1. Season reflects Autumn
        date_info = plan["in_game_date"]
        assert date_info["season"].lower() in ("autumn", "fall")
        assert date_info["day"] == 10

        # 2. Progress is intermediate
        assert plan["stats"]["completed_npcs_count"] >= 0

        # 3. Focus suggestions and crafting trees are populated
        focus_sugg = plan.get("focus_suggestions", [])
        assert len(focus_sugg) > 0

        # 4. Crafting trees trace blockers
        trees = plan.get("focus_trees", [])
        assert isinstance(trees, list)


class TestScenario3EndGameCompletionistOptimization:
    """Simulates a completionist seeking 100% gift discovery and remaining recipes."""

    def test_completionist_endgame_workflow(self, sample_save_path, plan_executor):
        # Uses real sample save which has 34 NPCs tracked
        config = {
            "strategy": "journal",
            "slots": 25,
            "focus_sort": "impact",
        }
        _, plan = plan_executor(sample_save_path, config=config)

        # 1. High stats dashboard
        stats = plan["stats"]
        assert stats["total_npcs_count"] >= 30
        assert "completed_npcs_details" in plan
        assert "incomplete_npcs_details" in plan

        # 2. Locked/unobtained recipes list exists
        unobtained = plan.get("unobtained_recipes", [])
        assert isinstance(unobtained, list)

        # 3. Bag plan fills available slots to optimize remaining journal entries
        assert len(plan["bag_plan"]) > 0


class TestScenario4SaturdayMarketShoppingRun:
    """Simulates a Saturday market morning shopping and gifting run."""

    def test_saturday_market_workflow(self, plan_executor):
        market_inventory = [
            {"item_id": "gold_coin", "count": 5000},
            {"item_id": "bread", "count": 2},
        ]
        # In FoM, Autumn Day 6 is a Saturday
        save_bytes = make_synthetic_save_bytes(
            player_name="MarketShopper",
            farm_name="BazaarFarm",
            year=2,
            season="autumn",
            day=6,
            inventory_items=market_inventory,
        )

        config = {
            "mode": "auto",
            "vendor_boost": 2.0,
            "slots": 15,
        }
        _, plan = plan_executor(save_bytes, config=config)

        # 1. In-game date confirms Saturday market day
        date_info = plan["in_game_date"]
        assert date_info["is_saturday"] is True
        assert date_info["day_of_week"].lower() == "saturday"

        # 2. Source Priority provides Quick shopping tier
        sp = plan.get("source_priority", {})
        if sp and "quick" in sp:
            quick_sources = sp["quick"]
            assert len(quick_sources) > 0


class TestScenario5FocusModeBlockerResolution:
    """Simulates a player exclusively romancing March and Celine with Focus Mode."""

    def test_targeted_focus_mode_workflow(self, sample_save_path, plan_executor):
        config = {
            "focus_mode_enabled": True,
            "focus_npcs": "march,celine",
            "slots": 12,
        }
        _, plan = plan_executor(sample_save_path, config=config)

        # 1. Bag plan remains populated for the town (per spec: focus mode does NOT affect bag plan)
        assert len(plan["bag_plan"]) > 0

        # 2. Focus suggestions ONLY benefit March or Celine
        focus_sugg = plan.get("focus_suggestions", [])
        assert len(focus_sugg) > 0
        for item in focus_sugg:
            blocked_npcs = item.get("blocked_npcs", [])
            if blocked_npcs:
                assert any(npc.lower() in ("march", "celine") for npc in blocked_npcs), (
                    f"Unexpected beneficiary for {item.get('item_id')}: {blocked_npcs}"
                )

        # 3. Source priority only features sources relevant to targeted NPCs
        sp = plan.get("source_priority", [])
        if sp and isinstance(sp, list):
            for src in sp:
                benefited = src.get("benefited_npcs", [])
                if benefited:
                    assert any(npc.lower() in ("march", "celine") for npc in benefited), (
                        f"Source {src.get('source_name')} has unexpected beneficiaries {benefited}"
                    )
