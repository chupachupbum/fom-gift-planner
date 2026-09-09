"""
tests/test_max_relationship.py

Comprehensive test suite for --strategy max-relationship:
- Priority hierarchy (5 tiers: Specific Love > Universal Love > Specific Like > Universal Like > Skip)
- MRV greedy constrained allocation and dynamic inventory deduction
- Saturday Market presence, weekday absence, and Animal Festival calendar rules
- SaveData relationship tracking and exclusion of NPCs at maximum relationship
- Capacity budgeting, max slots truncation, and clean rollback
- Test harness compatibility and adversarial scenario verifications (Scenarios 1 to 15)
"""

import copy
import io
import itertools
import json
import math
import os
from pathlib import Path
import tempfile
import time
import unittest
from typing import Any, Dict, List, Optional, Set, Tuple
from unittest.mock import MagicMock, patch

from fom_planner.constants import (
    ANIMAL_FESTIVAL_ATTENDING_VENDORS,
    AvailabilityTier,
    DEFAULT_MAX_RELATIONSHIP_POINTS,
    SATURDAY_MARKET_BASE_VENDORS,
    SATURDAY_MARKET_UPGRADE_1_VENDORS,
    SATURDAY_MARKET_UPGRADE_2_VENDORS,
    SATURDAY_MARKET_VENDORS,
    STORY_GATED_TOWNSFOLK,
)
from fom_planner.data_loader import load_item_metadata, load_npc_preferences_from_json
from fom_planner.models import InGameDate, SaveData
from fom_planner.optimizer import plan_max_relationship
from fom_planner.parser import parse_save_file

from tests.test_gift_planner import (
    create_mock_slot,
    create_synthetic_save_entries,
    create_synthetic_save_file,
    get_mock_meta,
    get_mock_npcs,
    get_mock_recipes,
)

ITEM_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "item_data.json"


# ============================================================================
# 1. SAVE DATA RELATIONSHIP DETECTION & MAX RELATIONSHIP EXCLUSION
# ============================================================================

class TestSaveDataMaxRelationship(unittest.TestCase):
    """Tests for SaveData relationship and max-relationship detection methods."""

    def test_get_npc_heart_points_affection_fallback(self):
        """Verify get_npc_heart_points retrieves heart_points or falls back to affection."""
        entries = {
            "npcs": json.dumps({
                "adeline": {"affection": 500, "gift_history": ["coffee"]},
                "balor": {"heart_points": 350.0},
                "celine": {"affection": "200"},
                "march": {},
            })
        }
        save = SaveData(Path("mock.sav"), entries)
        self.assertEqual(save.get_npc_heart_points("adeline"), 500.0)
        self.assertEqual(save.get_npc_heart_points("balor"), 350.0)
        self.assertEqual(save.get_npc_heart_points("celine"), 200.0)
        self.assertEqual(save.get_npc_heart_points("march"), 0.0)
        self.assertEqual(save.get_npc_heart_points("nonexistent"), 0.0)

    def test_get_npc_gifts_given_history_fallback(self):
        """Verify get_npc_gifts_given retrieves gifts_given or falls back to gift_history."""
        entries = {
            "npcs": json.dumps({
                "adeline": {"gift_history": ["coffee", "tea"]},
                "balor": {"gifts_given": ["ruby"]},
                "march": {},
            })
        }
        save = SaveData(Path("mock.sav"), entries)
        self.assertEqual(save.get_npc_gifts_given("adeline"), {"coffee", "tea"})
        self.assertEqual(save.get_npc_gifts_given("balor"), {"ruby"})
        self.assertEqual(save.get_npc_gifts_given("march"), set())

    def test_is_npc_max_relationship_threshold(self):
        """Verify threshold comparison against DEFAULT_MAX_RELATIONSHIP_POINTS (1755.0) and custom thresholds."""
        entries = {
            "npcs": json.dumps({
                "adeline": {"affection": 1755},
                "balor": {"heart_points": 1755.0},
                "celine": {"affection": 500},
                "darcy": {"heart_points": 200.0},
            })
        }
        save = SaveData(Path("mock.sav"), entries)
        self.assertTrue(save.is_npc_max_relationship("adeline"))
        self.assertTrue(save.is_npc_max_relationship("balor"))
        self.assertFalse(save.is_npc_max_relationship("celine"))
        self.assertFalse(save.is_npc_max_relationship("darcy"))

        # Custom threshold
        self.assertTrue(save.is_npc_max_relationship("celine", max_points=500.0))
        self.assertFalse(save.is_npc_max_relationship("celine", max_points=600.0))
        self.assertFalse(save.is_npc_max_relationship("adeline", max_points=2000.0))

    def test_is_npc_max_relationship_flags(self):
        """Verify explicit boolean flags denote max relationship regardless of numerical points."""
        entries = {
            "npcs": json.dumps({
                "adeline": {"affection": 100, "is_max_relationship": True},
                "balor": {"heart_points": 50, "max_relationship": True},
                "celine": {"affection": 0, "is_max_hearts": True},
                "darcy": {"affection": 0, "heart_cap": True},
                "dell": {"affection": 0, "is_capped": True},
            })
        }
        save = SaveData(Path("mock.sav"), entries)
        self.assertTrue(save.is_npc_max_relationship("adeline"))
        self.assertTrue(save.is_npc_max_relationship("balor"))
        self.assertTrue(save.is_npc_max_relationship("celine"))
        self.assertTrue(save.is_npc_max_relationship("darcy"))
        self.assertTrue(save.is_npc_max_relationship("dell"))

    def test_get_max_relationship_npc_ids(self):
        """Verify get_max_relationship_npc_ids returns the set of all maxed NPC IDs."""
        entries = {
            "npcs": json.dumps({
                "Adeline": {"affection": 1755},
                "Balor": {"heart_points": 1755.0},
                "Celine": {"affection": 500},
            })
        }
        save = SaveData(Path("mock.sav"), entries)
        self.assertEqual(save.get_max_relationship_npc_ids(), {"adeline", "balor"})


class TestPlanMaxRelationshipExclusion(unittest.TestCase):
    """Tests for plan_max_relationship excluding max-relationship NPCs."""

    def setUp(self):
        self.npcs_def = {
            "adeline": {"name": "Adeline", "loved": ["golden_cheesecake"], "liked": ["coffee"]},
            "balor": {"name": "Balor", "loved": ["ruby"], "liked": ["beer"]},
            "celine": {"name": "Celine", "loved": ["strawberry"], "liked": ["flour"]},
            "march": {"name": "March", "loved": ["iron_ingot"], "liked": ["copper_ore"]},
        }
        self.metadata = {
            "golden_cheesecake": {"display_name": "Golden Cheesecake"},
            "coffee": {"display_name": "Coffee"},
            "ruby": {"display_name": "Ruby"},
            "beer": {"display_name": "Beer"},
            "strawberry": {"display_name": "Strawberry"},
            "flour": {"display_name": "Flour"},
            "iron_ingot": {"display_name": "Iron Ingot"},
            "copper_ore": {"display_name": "Copper Ore"},
        }

    def test_exclude_max_relationship_npcs_from_plan(self):
        """Verify NPCs with max relationship (1755 pts) are excluded from assignments and target list."""
        entries = {
            "npcs": json.dumps({
                "adeline": {"affection": 1755, "gift_flag": True},  # Maxed out
                "balor": {"affection": 200, "gift_flag": True},
                "celine": {"affection": 200, "gift_flag": True},
                "march": {"affection": 1755, "gift_flag": True},   # Maxed out
            })
        }
        save = SaveData(Path("mock.sav"), entries)
        inv = {
            "golden_cheesecake": 5,
            "ruby": 5,
            "strawberry": 5,
            "iron_ingot": 5,
        }

        plan = plan_max_relationship(
            save=save,
            npc_gift_definitions=self.npcs_def,
            item_metadata=self.metadata,
            inventory=inv,
            mode="all",
        )

        stats = plan["overall_stats"]
        progress = plan["npc_progress"]

        # Adeline and March are maxed -> excluded
        self.assertIn("Adeline", stats["max_relationship_npcs"])
        self.assertIn("March", stats["max_relationship_npcs"])
        self.assertEqual(stats["max_relationship_npcs_count"], 2)

        # Target NPCs only include Balor and Celine
        self.assertEqual(stats["target_npcs_count"], 2)
        self.assertEqual(stats["covered_npcs_count"], 2)
        self.assertNotIn("adeline", plan["target_npcs"])
        self.assertNotIn("march", plan["target_npcs"])
        self.assertIn("balor", plan["target_npcs"])
        self.assertIn("celine", plan["target_npcs"])

        # Assignments must be None for Adeline and March
        self.assertIsNone(progress["adeline"]["assigned_item_id"])
        self.assertIsNone(progress["march"]["assigned_item_id"])
        self.assertTrue(progress["adeline"]["is_max_relationship"])
        self.assertTrue(progress["march"]["is_max_relationship"])

        # Balor and Celine got assigned
        self.assertEqual(progress["balor"]["assigned_item_id"], "ruby")
        self.assertEqual(progress["celine"]["assigned_item_id"], "strawberry")

        # Total points should only be for Balor and Celine (2 x 20 = 40)
        self.assertEqual(stats["total_relationship_points"], 40)

        # Bag plan only packs items for Balor and Celine
        packed_ids = [b["item_id"] for b in plan["bag_plan"]]
        self.assertNotIn("golden_cheesecake", packed_ids)
        self.assertNotIn("iron_ingot", packed_ids)
        self.assertIn("ruby", packed_ids)
        self.assertIn("strawberry", packed_ids)

    def test_force_all_npcs_preserves_max_relationship_exclusion(self):
        """Verify force_all_npcs does NOT override max-relationship exclusion."""
        entries = {
            "npcs": json.dumps({
                "adeline": {"affection": 1755, "gift_flag": False},
                "balor": {"affection": 200, "gift_flag": False},
            })
        }
        save = SaveData(Path("mock.sav"), entries)
        inv = {"golden_cheesecake": 5, "ruby": 5}

        plan = plan_max_relationship(
            save=save,
            npc_gift_definitions=self.npcs_def,
            item_metadata=self.metadata,
            inventory=inv,
            mode="all",
            force_all_npcs=True,
        )

        # Balor is included because force_all_npcs bypassed gift_flag
        self.assertIn("balor", plan["target_npcs"])
        # Adeline is STILL excluded because relationship is maxed
        self.assertNotIn("adeline", plan["target_npcs"])
        self.assertIn("Adeline", plan["overall_stats"]["max_relationship_npcs"])

    def test_no_exclude_max_relationship_flag(self):
        """Verify setting exclude_max_relationship=False includes maxed NPCs."""
        entries = {
            "npcs": json.dumps({
                "adeline": {"affection": 1755, "gift_flag": True},
                "balor": {"affection": 200, "gift_flag": True},
            })
        }
        save = SaveData(Path("mock.sav"), entries)
        inv = {"golden_cheesecake": 5, "ruby": 5}

        plan = plan_max_relationship(
            save=save,
            npc_gift_definitions=self.npcs_def,
            item_metadata=self.metadata,
            inventory=inv,
            mode="all",
            exclude_max_relationship=False,
        )

        self.assertIn("adeline", plan["target_npcs"])
        self.assertIn("balor", plan["target_npcs"])
        self.assertEqual(len(plan["overall_stats"]["max_relationship_npcs"]), 0)

    def test_sample_save_file_relationship_thresholds(self):
        """Verify behavior against actual samples/sample_save.sav with default (1755) and custom (500) thresholds."""
        sample_path = Path("samples/sample_save.sav")
        if not sample_path.exists():
            self.skipTest("sample_save.sav not found")

        save = parse_save_file(sample_path)
        from fom_planner.data_loader import load_npc_preferences_from_json, load_item_metadata
        npcs_def, _ = load_npc_preferences_from_json(Path("data/item_data.json"))
        meta = load_item_metadata(Path("assets/fiddle"), Path("data/item_data.json"))

        # Default threshold (1755.0): sample_save NPCs have at most 500 affection, so none are capped at 1755
        plan_default = plan_max_relationship(
            save=save,
            npc_gift_definitions=npcs_def,
            item_metadata=meta,
            mode="saturday",
            force_all_npcs=True,
        )
        self.assertEqual(plan_default["overall_stats"]["max_relationship_npcs_count"], 0)
        self.assertEqual(plan_default["overall_stats"]["target_npcs_count"], 34)

        # Custom threshold (500.0): The 5 romanceable NPCs with 500 affection in sample_save.sav are excluded
        plan_500 = plan_max_relationship(
            save=save,
            npc_gift_definitions=npcs_def,
            item_metadata=meta,
            mode="saturday",
            force_all_npcs=True,
            max_relationship_points=500.0,
        )
        stats_500 = plan_500["overall_stats"]
        expected_maxed = {"Adeline", "Balor", "Juniper", "March", "Valen"}
        self.assertEqual(set(stats_500["max_relationship_npcs"]), expected_maxed)
        self.assertEqual(stats_500["max_relationship_npcs_count"], 5)
        self.assertEqual(stats_500["target_npcs_count"], 29)


# ============================================================================
# 2. SATURDAY MARKET & ANIMAL FESTIVAL VENDOR PRESENCE RULES
# ============================================================================

def make_mock_save(entries: Dict[str, str]) -> SaveData:
    """Helper to construct SaveData from synthetic entries dictionary."""
    return SaveData(Path("mock.sav"), entries)


class TestSaturdayMarketVendorPresence(unittest.TestCase):
    """Stress testing Saturday Market vendor presence vs absence across calendar and modes."""

    @classmethod
    def setUpClass(cls):
        cls.real_defs, _ = load_npc_preferences_from_json(ITEM_DATA_PATH)
        cls.real_meta = load_item_metadata(None, ITEM_DATA_PATH)

    def test_saturday_market_vendors_included_on_saturday_auto_mode(self):
        """On Saturday with mode='auto', all unlocked visiting vendors must be targetable."""
        # Winter 6 is Saturday
        entries = create_synthetic_save_entries(
            year=2, season="winter", day=6, giftable_all=True
        )
        save = make_mock_save(entries)
        self.assertTrue(save.in_game_date.is_saturday)

        inventory = {
            "golden_cheesecake": 10,   # Loved by Darcy (vendor) & others
            "golden_rabbit_wool": 10,  # Loved by Merri & Louis (vendors)
            "perfect_iron_ore": 10,    # Loved by March (townsfolk)
        }

        result = plan_max_relationship(
            save=save,
            npc_gift_definitions=self.real_defs,
            item_metadata=self.real_meta,
            mode="auto",
            inventory=inventory,
        )

        stats = result["overall_stats"]
        self.assertTrue(stats["planning_for_saturday"])
        self.assertFalse(stats["is_animal_festival"])

        # All 8 Saturday Market vendors must be in target_npcs
        for vendor in SATURDAY_MARKET_VENDORS:
            self.assertIn(
                vendor,
                result["target_npcs"],
                f"Expected vendor '{vendor}' to be in target_npcs on Saturday",
            )
            self.assertTrue(result["npc_progress"][vendor]["is_present_today"])
            self.assertTrue(result["npc_progress"][vendor]["can_gift_today"])
            self.assertTrue(result["npc_progress"][vendor]["is_vendor"])

        # Darcy, Merri, Louis, March must be covered
        covered = result["covered_npcs"]
        self.assertIn("darcy", covered)
        self.assertIn("merri", covered)
        self.assertIn("louis", covered)
        self.assertIn("march", covered)

        self.assertGreaterEqual(stats["vendors_covered_today"], 3)
        self.assertGreaterEqual(stats["total_relationship_points"], 80)

    def test_saturday_market_vendors_excluded_on_weekdays_auto_mode(self):
        """On weekdays with mode='auto', visiting vendors must be absent and not targetable."""
        # Winter 5 is Friday (weekday)
        entries = create_synthetic_save_entries(
            year=2, season="winter", day=5, giftable_all=True
        )
        save = make_mock_save(entries)
        self.assertFalse(save.in_game_date.is_saturday)
        self.assertFalse(save.in_game_date.is_animal_festival)

        inventory = {
            "golden_cheesecake": 10,   # Loved by Darcy (vendor) & others
            "golden_rabbit_wool": 10,  # Loved by Merri & Louis (vendors)
            "perfect_iron_ore": 10,    # Loved by March (townsfolk)
        }

        result = plan_max_relationship(
            save=save,
            npc_gift_definitions=self.real_defs,
            item_metadata=self.real_meta,
            mode="auto",
            inventory=inventory,
        )

        stats = result["overall_stats"]
        self.assertFalse(stats["planning_for_saturday"])
        self.assertEqual(stats["vendors_covered_today"], 0)

        # Visiting vendors must NOT be in target_npcs
        for vendor in SATURDAY_MARKET_VENDORS:
            self.assertNotIn(
                vendor,
                result["target_npcs"],
                f"Vendor '{vendor}' should NOT be in target_npcs on a weekday",
            )
            self.assertFalse(result["npc_progress"][vendor]["is_present_today"])
            self.assertIsNone(result["npc_progress"][vendor]["assigned_item_id"])

        # March gets a gift; all vendors are completely omitted
        self.assertIn("march", result["covered_npcs"])
        self.assertNotIn("darcy", result["covered_npcs"])
        self.assertNotIn("merri", result["covered_npcs"])
        self.assertNotIn("louis", result["covered_npcs"])
        self.assertNotIn("taliferro", result["covered_npcs"])
        self.assertNotIn("wheedle", result["covered_npcs"])

        # No vendors should be in bag_plan market_vendors_covered
        for slot in result["bag_plan"]:
            self.assertEqual(slot["market_vendors_covered"], [])

    def test_mode_overrides_weekday_and_saturday(self):
        """Mode overrides should force vendor inclusion or exclusion regardless of calendar day."""
        # Weekday save
        entries_fri = create_synthetic_save_entries(year=2, season="winter", day=5)
        save_fri = make_mock_save(entries_fri)

        # mode='saturday' on Friday forces vendors present
        res_forced_sat = plan_max_relationship(
            save=save_fri,
            npc_gift_definitions=self.real_defs,
            item_metadata=self.real_meta,
            mode="saturday",
        )
        self.assertTrue(res_forced_sat["overall_stats"]["planning_for_saturday"])
        for vendor in SATURDAY_MARKET_VENDORS:
            self.assertIn(vendor, res_forced_sat["target_npcs"])

        # mode='market-only' on Friday forces ONLY vendors present
        res_market_only = plan_max_relationship(
            save=save_fri,
            npc_gift_definitions=self.real_defs,
            item_metadata=self.real_meta,
            mode="market-only",
        )
        for vendor in SATURDAY_MARKET_VENDORS:
            self.assertIn(vendor, res_market_only["target_npcs"])
        self.assertNotIn("march", res_market_only["target_npcs"])
        self.assertNotIn("adeline", res_market_only["target_npcs"])

        # Saturday save
        entries_sat = create_synthetic_save_entries(year=2, season="winter", day=6)
        save_sat = make_mock_save(entries_sat)

        # mode='weekday' on Saturday forces vendors absent
        res_forced_weekday = plan_max_relationship(
            save=save_sat,
            npc_gift_definitions=self.real_defs,
            item_metadata=self.real_meta,
            mode="weekday",
        )
        for vendor in SATURDAY_MARKET_VENDORS:
            self.assertNotIn(vendor, res_forced_weekday["target_npcs"])
        self.assertIn("march", res_forced_weekday["target_npcs"])

        # mode='townsfolk' on Saturday forces vendors absent
        res_forced_townsfolk = plan_max_relationship(
            save=save_sat,
            npc_gift_definitions=self.real_defs,
            item_metadata=self.real_meta,
            mode="townsfolk",
        )
        for vendor in SATURDAY_MARKET_VENDORS:
            self.assertNotIn(vendor, res_forced_townsfolk["target_npcs"])
        self.assertIn("adeline", res_forced_townsfolk["target_npcs"])

    def test_vendor_boost_priority_on_saturday(self):
        """On Saturday, vendor boost gives priority to vendors over townsfolk when candidate counts tie."""
        # Custom gift defs with 1 vendor and 1 townsfolk competing for the same single item
        defs = {
            "darcy": {"name": "Darcy", "loved": {"rare_gem"}, "liked": set()},
            "march": {"name": "March", "loved": {"rare_gem"}, "liked": set()},
        }
        meta = {"rare_gem": {"display_name": "Rare Gem"}}

        entries_sat = create_synthetic_save_entries(year=2, season="winter", day=6)
        save_sat = make_mock_save(entries_sat)

        # Saturday: Darcy (vendor) has vendor boost (0 vs 1) -> Darcy gets the 1 item
        res_sat = plan_max_relationship(
            save=save_sat,
            npc_gift_definitions=defs,
            item_metadata=meta,
            mode="auto",
            inventory={"rare_gem": 1},
        )
        self.assertIn("darcy", res_sat["covered_npcs"])
        self.assertNotIn("march", res_sat["covered_npcs"])
        self.assertEqual(res_sat["npc_progress"]["darcy"]["assigned_item_id"], "rare_gem")
        self.assertIsNone(res_sat["npc_progress"]["march"]["assigned_item_id"])

        # Weekday: Darcy is absent; March gets the 1 item
        entries_fri = create_synthetic_save_entries(year=2, season="winter", day=5)
        save_fri = make_mock_save(entries_fri)
        res_fri = plan_max_relationship(
            save=save_fri,
            npc_gift_definitions=defs,
            item_metadata=meta,
            mode="auto",
            inventory={"rare_gem": 1},
        )
        self.assertIn("march", res_fri["covered_npcs"])
        self.assertNotIn("darcy", res_fri["covered_npcs"])
        self.assertEqual(res_fri["npc_progress"]["march"]["assigned_item_id"], "rare_gem")

    def test_vendor_progression_unlocks_on_saturday(self):
        """Locked vendors should not be present or targetable even on Saturdays."""
        # Unlocked only base vendors: Darcy, Louis, Merri, Vera + townsfolk March
        unlocked_npcs = list(SATURDAY_MARKET_BASE_VENDORS) + ["march"]
        entries = create_synthetic_save_entries(
            year=2, season="winter", day=6, npc_ids=unlocked_npcs
        )
        save = make_mock_save(entries)

        result = plan_max_relationship(
            save=save,
            npc_gift_definitions=self.real_defs,
            item_metadata=self.real_meta,
            mode="auto",
        )

        stats = result["overall_stats"]
        # Base vendors unlocked
        for bv in SATURDAY_MARKET_BASE_VENDORS:
            self.assertIn(bv, result["target_npcs"])

        # Upgrade 1 and 2 vendors must be locked and NOT in target_npcs
        for locked_v in SATURDAY_MARKET_UPGRADE_1_VENDORS | SATURDAY_MARKET_UPGRADE_2_VENDORS:
            self.assertNotIn(locked_v, result["target_npcs"])
            self.assertFalse(result["npc_progress"][locked_v]["is_unlocked"])
            self.assertIn(self.real_defs[locked_v]["name"], stats["locked_npcs"])


class TestAnimalFestivalVendorAttendance(unittest.TestCase):
    """Stress testing Animal Festival (Winter 10) vendor attendance logic."""

    @classmethod
    def setUpClass(cls):
        cls.real_defs, _ = load_npc_preferences_from_json(ITEM_DATA_PATH)
        cls.real_meta = load_item_metadata(None, ITEM_DATA_PATH)

    def test_animal_festival_winter_10_presence(self):
        """On Winter 10 (Tuesday), only Merri & Louis should be present; other 6 vendors absent."""
        # Winter 10 is Tuesday
        entries = create_synthetic_save_entries(
            year=2, season="winter", day=10, giftable_all=True
        )
        save = make_mock_save(entries)
        self.assertTrue(save.in_game_date.is_animal_festival)
        self.assertFalse(save.in_game_date.is_saturday)

        result = plan_max_relationship(
            save=save,
            npc_gift_definitions=self.real_defs,
            item_metadata=self.real_meta,
            mode="auto",
        )

        stats = result["overall_stats"]
        self.assertTrue(stats["is_animal_festival"])
        self.assertFalse(stats["planning_for_saturday"])

        # Louis and Merri must be present and targetable
        self.assertIn("merri", result["target_npcs"])
        self.assertIn("louis", result["target_npcs"])
        self.assertTrue(result["npc_progress"]["merri"]["is_present_today"])
        self.assertTrue(result["npc_progress"]["louis"]["is_present_today"])

        # Other 6 vendors must be absent
        absent_vendors = SATURDAY_MARKET_VENDORS - ANIMAL_FESTIVAL_ATTENDING_VENDORS
        for av in absent_vendors:
            self.assertNotIn(av, result["target_npcs"])
            self.assertFalse(result["npc_progress"][av]["is_present_today"])
            self.assertIn(self.real_defs[av]["name"], stats["not_present_npcs"])

        # Regular townsfolk (March, Adeline, Celine) must be present
        self.assertIn("march", result["target_npcs"])
        self.assertIn("adeline", result["target_npcs"])
        self.assertIn("celine", result["target_npcs"])

    def test_animal_festival_gifting_and_vendor_boost(self):
        """On Winter 10, Merri and Louis can receive gifts and receive festival vendor boost."""
        defs = {
            "merri": {"name": "Merri", "loved": {"cabbage"}, "liked": set()},
            "louis": {"name": "Louis", "loved": {"onion"}, "liked": set()},
            "darcy": {"name": "Darcy", "loved": {"chestnut"}, "liked": set()},
            "march": {"name": "March", "loved": {"onion"}, "liked": set()},
        }
        meta = {
            "cabbage": {"display_name": "Cabbage"},
            "onion": {"display_name": "Onion"},
            "chestnut": {"display_name": "Chestnut"},
        }

        entries = create_synthetic_save_entries(year=2, season="winter", day=10)
        save = make_mock_save(entries)

        # Inventory has 1 cabbage (Merri), 1 chestnut (Darcy - absent!), and 1 onion (shared by Louis & March)
        inventory = {"cabbage": 1, "chestnut": 1, "onion": 1}

        result = plan_max_relationship(
            save=save,
            npc_gift_definitions=defs,
            item_metadata=meta,
            mode="auto",
            inventory=inventory,
        )

        covered = result["covered_npcs"]
        # Merri gets cabbage
        self.assertIn("merri", covered)
        self.assertEqual(result["npc_progress"]["merri"]["assigned_item_id"], "cabbage")

        # Darcy is absent on Winter 10, gets nothing
        self.assertNotIn("darcy", covered)
        self.assertIsNone(result["npc_progress"]["darcy"]["assigned_item_id"])

        # Louis vs March: Louis has festival boost on Winter 10 -> Louis gets onion, March gets nothing
        self.assertIn("louis", covered)
        self.assertNotIn("march", covered)
        self.assertEqual(result["npc_progress"]["louis"]["assigned_item_id"], "onion")
        self.assertIsNone(result["npc_progress"]["march"]["assigned_item_id"])

    def test_animal_festival_with_locked_merri(self):
        """If Merri is locked in progression, she should not attend the festival."""
        # Unlocked all except Merri
        all_except_merri = [nid for nid in SATURDAY_MARKET_BASE_VENDORS if nid != "merri"] + ["march"]
        entries = create_synthetic_save_entries(
            year=2, season="winter", day=10, npc_ids=all_except_merri
        )
        save = make_mock_save(entries)

        result = plan_max_relationship(
            save=save,
            npc_gift_definitions=self.real_defs,
            item_metadata=self.real_meta,
            mode="auto",
        )

        self.assertNotIn("merri", result["target_npcs"])
        self.assertFalse(result["npc_progress"]["merri"]["is_unlocked"])
        self.assertIn("louis", result["target_npcs"])

    def test_other_festivals_do_not_admit_vendors(self):
        """Other festivals (e.g. Spring 17 Spring Festival) must NOT admit any visiting vendors."""
        # Spring 17 is a Tuesday festival
        entries = create_synthetic_save_entries(year=2, season="spring", day=17)
        save = make_mock_save(entries)
        self.assertEqual(save.in_game_date.festival_name, "Spring Festival")
        self.assertFalse(save.in_game_date.is_saturday)
        self.assertFalse(save.in_game_date.is_animal_festival)

        result = plan_max_relationship(
            save=save,
            npc_gift_definitions=self.real_defs,
            item_metadata=self.real_meta,
            mode="auto",
        )

        for vendor in SATURDAY_MARKET_VENDORS:
            self.assertNotIn(
                vendor,
                result["target_npcs"],
                f"Vendor '{vendor}' should NOT be at Spring Festival",
            )


class TestEmptyInventoryAndZeroAvailableItems(unittest.TestCase):
    """Stress testing empty inventory, zero counts, and non-giftable items."""

    @classmethod
    def setUpClass(cls):
        cls.real_defs, _ = load_npc_preferences_from_json(ITEM_DATA_PATH)
        cls.real_meta = load_item_metadata(None, ITEM_DATA_PATH)

    def test_completely_empty_inventory_and_infusions(self):
        """Empty inventory must return empty plan, 0 pts, and no crashes."""
        entries = create_synthetic_save_entries(bag_items={}, year=2, season="winter", day=6)
        save = make_mock_save(entries)

        result = plan_max_relationship(
            save=save,
            npc_gift_definitions=self.real_defs,
            item_metadata=self.real_meta,
            mode="auto",
            inventory={},
            infused_items={},
        )

        self.assertEqual(result["bag_plan"], [])
        self.assertEqual(result["covered_npcs"], set())
        self.assertEqual(result["overall_stats"]["total_relationship_points"], 0)
        self.assertEqual(result["overall_stats"]["slots_used"], 0)
        self.assertEqual(result["overall_stats"]["today_loved_completed"], 0)
        self.assertEqual(result["overall_stats"]["today_liked_completed"], 0)
        self.assertEqual(result["overall_stats"]["strategy"], "max-relationship")

        # Target NPCs should still be populated, but all assigned None
        self.assertGreater(len(result["target_npcs"]), 0)
        for nid in result["target_npcs"]:
            p = result["npc_progress"][nid]
            self.assertIsNone(p["assigned_item_id"])
            self.assertIsNone(p["assigned_pref_type"])
            self.assertEqual(p["assigned_points"], 0)

    def test_zero_and_negative_inventory_counts(self):
        """Zero and negative counts must be pruned cleanly."""
        inv = {
            "apple_pie": 0,
            "rose": -5,
            "cheese": 0.0,
            "tulip": -1,
        }
        infused = {
            "lovable": {"apple_pie": 0, "berry_tart": -3},
            "likable": [{"item_id": "soup", "count": 0}],
        }

        result = plan_max_relationship(
            npc_gift_definitions=self.real_defs,
            item_metadata=self.real_meta,
            mode="all",
            inventory=inv,
            infused_items=infused,
        )

        self.assertEqual(result["bag_plan"], [])
        self.assertEqual(result["covered_npcs"], set())
        self.assertEqual(result["overall_stats"]["total_relationship_points"], 0)

    def test_inventory_with_only_unloved_unliked_items(self):
        """Items not loved/liked by anyone must NOT be assigned as neutral (+3) gifts."""
        inv = {
            "acorn": 999,
            "bomb": 500,
            "bell_berry": 250,
            "ash_mushroom": 50,
        }

        result = plan_max_relationship(
            npc_gift_definitions=self.real_defs,
            item_metadata=self.real_meta,
            mode="all",
            inventory=inv,
        )

        self.assertEqual(result["bag_plan"], [])
        self.assertEqual(result["covered_npcs"], set())
        self.assertEqual(result["overall_stats"]["total_relationship_points"], 0)

    def test_malformed_and_none_infused_items_inputs(self):
        """Various malformed infused_items parameters should not crash the optimizer."""
        malformed_inputs = [
            None,
            {},
            [],
            [None],
            {"lovable": None, "likable": None},
            {"lovable": [None, {}, {"item_id": ""}]},
            {"likable": [{"item_id": None, "count": 1}]},
            [{"corrupted": True}],
            12345,
        ]

        for malformed in malformed_inputs:
            result = plan_max_relationship(
                npc_gift_definitions=self.real_defs,
                item_metadata=self.real_meta,
                mode="all",
                inventory={},
                infused_items=malformed,
            )
            self.assertEqual(result["bag_plan"], [])
            self.assertEqual(result["overall_stats"]["total_relationship_points"], 0)


class TestAllNPCsGiftedOrExcluded(unittest.TestCase):
    """Stress testing edge cases where all NPCs are already gifted or excluded."""

    @classmethod
    def setUpClass(cls):
        cls.real_defs, _ = load_npc_preferences_from_json(ITEM_DATA_PATH)
        cls.real_meta = load_item_metadata(None, ITEM_DATA_PATH)

    def test_all_npcs_already_gifted_today(self):
        """When gift_flag is False for all NPCs, target_npcs must be empty (unless force_all_npcs)."""
        entries = create_synthetic_save_entries(
            year=2, season="winter", day=6, giftable_all=False
        )
        save = make_mock_save(entries)

        inv = {"apple_pie": 10, "rose": 10, "copper_ore": 10}

        # force_all_npcs = False (default)
        result = plan_max_relationship(
            save=save,
            npc_gift_definitions=self.real_defs,
            item_metadata=self.real_meta,
            mode="auto",
            inventory=inv,
            force_all_npcs=False,
        )

        self.assertEqual(result["target_npcs"], set())
        self.assertEqual(result["covered_npcs"], set())
        self.assertEqual(result["bag_plan"], [])
        self.assertEqual(result["overall_stats"]["target_npcs_count"], 0)
        self.assertEqual(result["overall_stats"]["total_relationship_points"], 0)
        self.assertGreater(len(result["overall_stats"]["ungiftable_npcs"]), 0)

        # force_all_npcs = True bypasses gift_flag
        res_forced = plan_max_relationship(
            save=save,
            npc_gift_definitions=self.real_defs,
            item_metadata=self.real_meta,
            mode="auto",
            inventory=inv,
            force_all_npcs=True,
        )
        self.assertGreater(len(res_forced["target_npcs"]), 0)
        self.assertGreater(len(res_forced["covered_npcs"]), 0)
        self.assertGreater(res_forced["overall_stats"]["total_relationship_points"], 0)

    def test_all_npcs_excluded(self):
        """When all NPCs are in exclude_npcs, return empty plan with zero points."""
        all_ids = list(self.real_defs.keys())
        # Mixed casing and whitespace in exclude list
        noisy_excluded = [f"  {nid.upper()}  " for nid in all_ids]

        inv = {"apple_pie": 50, "rose": 50}

        result = plan_max_relationship(
            npc_gift_definitions=self.real_defs,
            item_metadata=self.real_meta,
            mode="all",
            inventory=inv,
            exclude_npcs=noisy_excluded,
        )

        self.assertEqual(result["target_npcs"], set())
        self.assertEqual(result["npc_progress"], {})
        self.assertEqual(result["covered_npcs"], set())
        self.assertEqual(result["bag_plan"], [])
        self.assertEqual(result["overall_stats"]["total_relationship_points"], 0)
        self.assertEqual(result["overall_stats"]["target_npcs_count"], 0)
        self.assertEqual(result["focus_suggestions"], [])

    def test_mixed_already_gifted_and_excluded(self):
        """Only NPCs that are both unexcluded and giftable today should receive gifts."""
        defs = {
            "adeline": {"name": "Adeline", "loved": {"apple_pie"}, "liked": set()},
            "march": {"name": "March", "loved": {"copper_ore"}, "liked": set()},
            "celine": {"name": "Celine", "loved": {"tulip"}, "liked": set()},
        }
        meta = {
            "apple_pie": {"display_name": "Apple Pie"},
            "copper_ore": {"display_name": "Copper Ore"},
            "tulip": {"display_name": "Tulip"},
        }
        inv = {"apple_pie": 2, "copper_ore": 2, "tulip": 2}

        # Mock save where March has gift_flag=False, Adeline is excluded, Celine is eligible
        entries = create_synthetic_save_entries(year=2, season="winter", day=6)
        npcs_data = json.loads(entries["npcs"])
        npcs_data["march"]["gift_flag"] = False
        entries["npcs"] = json.dumps(npcs_data)
        save = make_mock_save(entries)

        result = plan_max_relationship(
            save=save,
            npc_gift_definitions=defs,
            item_metadata=meta,
            mode="auto",
            inventory=inv,
            exclude_npcs=["adeline"],
        )

        # Adeline excluded -> not in npc_progress
        self.assertNotIn("adeline", result["npc_progress"])
        # March ungiftable -> in npc_progress, but not in target_npcs
        self.assertIn("march", result["npc_progress"])
        self.assertNotIn("march", result["target_npcs"])
        # Celine eligible -> in target_npcs and covered
        self.assertIn("celine", result["target_npcs"])
        self.assertIn("celine", result["covered_npcs"])
        self.assertEqual(result["overall_stats"]["total_relationship_points"], 20)

    def test_defensive_handling_of_invalid_exclude_npcs(self):
        """Invalid or corrupt items in exclude_npcs should be silently ignored."""
        result = plan_max_relationship(
            npc_gift_definitions=self.real_defs,
            item_metadata=self.real_meta,
            mode="all",
            exclude_npcs=[None, "", "nonexistent_character_xyz", 999],
        )
        self.assertGreater(len(result["target_npcs"]), 0)


class TestCapacityTruncationAndCleanRollback(unittest.TestCase):
    """Stress testing max_slots capacity budgeting, priority sorting, and assignment rollback."""

    def test_max_slots_truncation_exact_slot_and_points_accounting(self):
        """Truncation beyond max_slots must cleanly roll back NPC assignment and points."""
        defs = {
            f"npc_{i}": {"name": f"NPC {i}", "loved": {f"item_{i}"}, "liked": set()}
            for i in range(1, 9)
        }
        meta = {f"item_{i}": {"display_name": f"Item {i}"} for i in range(1, 9)}
        inv = {f"item_{i}": 1 for i in range(1, 9)}

        max_slots = 3
        result = plan_max_relationship(
            npc_gift_definitions=defs,
            item_metadata=meta,
            mode="all",
            max_slots=max_slots,
            inventory=inv,
        )

        # Bag plan must have exactly max_slots items
        self.assertEqual(len(result["bag_plan"]), max_slots)
        self.assertEqual(result["overall_stats"]["slots_used"], max_slots)
        self.assertEqual(len(result["covered_npcs"]), max_slots)
        self.assertEqual(result["overall_stats"]["covered_npcs_count"], max_slots)
        self.assertEqual(result["overall_stats"]["total_relationship_points"], max_slots * 20)

        packed_items = {slot["item_id"] for slot in result["bag_plan"]}
        covered_npcs = result["covered_npcs"]

        # Exactly 3 NPCs covered with points 20
        # Exactly 5 NPCs rolled back with points 0 and assigned_item_id None
        covered_count = 0
        reverted_count = 0
        for nid, p in result["npc_progress"].items():
            if nid in covered_npcs:
                covered_count += 1
                self.assertIn(p["assigned_item_id"], packed_items)
                self.assertEqual(p["assigned_pref_type"], "LOVE")
                self.assertEqual(p["assigned_points"], 20)
            else:
                reverted_count += 1
                self.assertIsNone(p["assigned_item_id"])
                self.assertIsNone(p["assigned_item_name"])
                self.assertIsNone(p["assigned_pref_type"])
                self.assertEqual(p["assigned_points"], 0)

        self.assertEqual(covered_count, 3)
        self.assertEqual(reverted_count, 5)

    def test_shared_item_multi_recipient_efficiency_under_capacity_limit(self):
        """Item covering multiple recipients yields more points and must beat single-recipient items."""
        # Item A is loved by 3 NPCs (60 pts in 1 slot)
        # Item B is loved by 1 NPC (20 pts in 1 slot, with abundance 10)
        defs = {
            "npc_a1": {"name": "Alice", "loved": {"item_a"}, "liked": set()},
            "npc_a2": {"name": "Amy", "loved": {"item_a"}, "liked": set()},
            "npc_a3": {"name": "Anna", "loved": {"item_a"}, "liked": set()},
            "npc_b": {"name": "Bob", "loved": {"item_b"}, "liked": set()},
        }
        meta = {
            "item_a": {"display_name": "Apple"},
            "item_b": {"display_name": "Banana"},
        }
        inv = {"item_a": 3, "item_b": 10}

        # Restrict to 1 slot: item_a delivers 60 pts, item_b delivers 20 pts
        result = plan_max_relationship(
            npc_gift_definitions=defs,
            item_metadata=meta,
            mode="all",
            max_slots=1,
            inventory=inv,
        )

        self.assertEqual(len(result["bag_plan"]), 1)
        packed_slot = result["bag_plan"][0]
        self.assertEqual(packed_slot["item_id"], "item_a")
        self.assertEqual(packed_slot["quantity_to_pack"], 3)
        self.assertEqual(result["overall_stats"]["total_relationship_points"], 60)

        # All 3 recipients of item_a must be covered
        self.assertEqual(result["covered_npcs"], {"npc_a1", "npc_a2", "npc_a3"})
        self.assertNotIn("npc_b", result["covered_npcs"])
        self.assertIsNone(result["npc_progress"]["npc_b"]["assigned_item_id"])
        self.assertEqual(result["npc_progress"]["npc_b"]["assigned_points"], 0)

    def test_vendor_tie_breaking_under_equal_points_capacity_truncation(self):
        """Under equal points and recipient count, vendor item must be prioritized into bag slot."""
        # Darcy (vendor) loves item_vendor (+20 pts, 1 recip)
        # March (townsfolk) loves item_townsfolk (+20 pts, 1 recip)
        defs = {
            "darcy": {"name": "Darcy", "loved": {"item_vendor"}, "liked": set()},
            "march": {"name": "March", "loved": {"item_townsfolk"}, "liked": set()},
        }
        meta = {
            "item_vendor": {"display_name": "Vendor Specialty"},
            "item_townsfolk": {"display_name": "Town Specialty"},
        }
        inv = {"item_vendor": 1, "item_townsfolk": 1}

        entries_sat = create_synthetic_save_entries(year=2, season="winter", day=6)
        save_sat = make_mock_save(entries_sat)

        result = plan_max_relationship(
            save=save_sat,
            npc_gift_definitions=defs,
            item_metadata=meta,
            mode="auto",
            max_slots=1,
            inventory=inv,
        )

        # Darcy's item must take slot 1 due to vendor_hits=1 > 0
        self.assertEqual(len(result["bag_plan"]), 1)
        self.assertEqual(result["bag_plan"][0]["item_id"], "item_vendor")
        self.assertEqual(result["covered_npcs"], {"darcy"})
        self.assertNotIn("march", result["covered_npcs"])
        self.assertIsNone(result["npc_progress"]["march"]["assigned_item_id"])
        self.assertEqual(result["npc_progress"]["march"]["assigned_points"], 0)

    def test_zero_and_negative_max_slots(self):
        """max_slots <= 0 must result in empty bag_plan and clean rollback for all NPCs."""
        defs = {
            "npc_1": {"name": "One", "loved": {"item_1"}, "liked": set()},
            "npc_2": {"name": "Two", "loved": {"item_2"}, "liked": set()},
        }
        meta = {
            "item_1": {"display_name": "Item 1"},
            "item_2": {"display_name": "Item 2"},
        }
        inv = {"item_1": 5, "item_2": 5}

        for ms in [0, -1, -10]:
            result = plan_max_relationship(
                npc_gift_definitions=defs,
                item_metadata=meta,
                mode="all",
                max_slots=ms,
                inventory=inv,
            )
            self.assertEqual(result["bag_plan"], [])
            self.assertEqual(result["covered_npcs"], set())
            self.assertEqual(result["overall_stats"]["slots_used"], 0)
            self.assertEqual(result["overall_stats"]["total_relationship_points"], 0)
            self.assertIsNone(result["npc_progress"]["npc_1"]["assigned_item_id"])
            self.assertIsNone(result["npc_progress"]["npc_2"]["assigned_item_id"])

    def test_mixed_tier_rollback_points_preservation(self):
        """Capacity truncation must retain high-tier (+20) items over lower-tier (+10) items."""
        # Alice gets specific love (+20)
        # Bob gets universal love (+20, name 'Bob' < 'David')
        # Charlie gets specific like (+10)
        # David gets universal like (+10)
        defs = {
            "npc_love": {"name": "Alice", "loved": {"apple_pie"}, "liked": set()},
            "npc_univ_love": {"name": "Bob", "loved": set(), "liked": set()},
            "npc_like": {"name": "Charlie", "loved": set(), "liked": {"soup"}},
            "npc_univ_like": {"name": "David", "loved": set(), "liked": set()},
        }
        meta = {
            "apple_pie": {"display_name": "Apple Pie"},
            "infused_pie": {"display_name": "Infused Pie"},
            "soup": {"display_name": "Soup"},
            "infused_soup": {"display_name": "Infused Soup"},
        }
        inv = {"apple_pie": 1, "soup": 1}
        infused = {
            "lovable": {"infused_pie": 1},
            "likable": {"infused_soup": 1},
        }

        # 4 distinct items across 4 tiers:
        # - apple_pie: +20 pts (Alice)
        # - infused_pie: +20 pts (Bob)
        # - soup: +10 pts (Charlie)
        # - infused_soup: +10 pts (David)
        # If max_slots=2, the two +20 items must be kept (total 40 pts).
        result = plan_max_relationship(
            npc_gift_definitions=defs,
            item_metadata=meta,
            mode="all",
            max_slots=2,
            inventory=inv,
            infused_items=infused,
        )

        self.assertEqual(len(result["bag_plan"]), 2)
        packed_ids = {s["item_id"] for s in result["bag_plan"]}
        self.assertEqual(packed_ids, {"apple_pie", "infused_pie"})
        self.assertEqual(result["overall_stats"]["total_relationship_points"], 40)

        # Charlie and David must be reverted
        self.assertIn("npc_love", result["covered_npcs"])
        self.assertIn("npc_univ_love", result["covered_npcs"])
        self.assertNotIn("npc_like", result["covered_npcs"])
        self.assertNotIn("npc_univ_like", result["covered_npcs"])

        self.assertIsNone(result["npc_progress"]["npc_like"]["assigned_item_id"])
        self.assertEqual(result["npc_progress"]["npc_like"]["assigned_points"], 0)
        self.assertIsNone(result["npc_progress"]["npc_univ_like"]["assigned_item_id"])
        self.assertEqual(result["npc_progress"]["npc_univ_like"]["assigned_points"], 0)


# ============================================================================
# 3. 5-TIER PRIORITY HIERARCHY, MRV ALLOCATION & INVENTORY INVARIANTS
# ============================================================================

def make_mock_slot(
    item_id: Optional[str] = None,
    count: Any = 1,
    infusion: Optional[str] = None,
) -> Dict[str, Any]:
    """Builds a single save inventory slot dict."""
    if item_id is None or (isinstance(count, (int, float)) and count <= 0):
        return {"count": 0, "item": None, "required_tags": []}
    item_dict: Dict[str, Any] = {"item_id": str(item_id)}
    if infusion is not None:
        item_dict["infusion"] = infusion
    return {
        "count": float(count),
        "item": item_dict,
        "required_tags": [],
    }


def make_synthetic_save(
    bag_slots: Optional[List[Dict[str, Any]]] = None,
    chest_locations: Optional[Dict[str, List[List[Dict[str, Any]]]]] = None,
    year: int = 1,
    season: str = "spring",
    day: int = 1,  # Day 1 is Monday (weekday)
    present_npcs: Optional[List[str]] = None,
    giftable_npcs: Optional[List[str]] = None,
    unlocked_npcs: Optional[List[str]] = None,
    heart_points: Optional[Dict[str, float]] = None,
    extra_npc_ids: Optional[List[str]] = None,
) -> SaveData:
    """Constructs a fully-featured synthetic SaveData instance."""
    season_idx = {"spring": 0, "summer": 1, "autumn": 2, "fall": 2, "winter": 3}.get(season.lower(), 0)
    cal_days = (year - 1) * 112 + season_idx * 28 + (day - 1)
    cal_time = cal_days * 86400

    raw: Dict[str, str] = {
        "header": json.dumps({
            "name": "ChallengerHero",
            "farm_name": "AdversarialFarm",
            "playtime": 3600.0,
            "calendar_time": cal_time,
            "clock_time": 21600,
        }),
        "player": json.dumps({
            "name": "ChallengerHero",
            "farm_name": "AdversarialFarm",
            "inventory": bag_slots if bag_slots is not None else [make_mock_slot(None, 0)] * 30,
        }),
    }

    all_34_npcs = [
        "adeline", "balor", "celine", "darcy", "dell", "dozy", "eiland", "elsie", "errol",
        "hayden", "hemlock", "henrietta", "holt", "josephine", "juniper", "landen", "louis",
        "luc", "maple", "march", "merri", "nora", "olric", "reina", "ryis", "seridia",
        "stillwell", "taliferro", "terithia", "valen", "vera", "wheedle", "zorel", "caldarus",
    ]
    if extra_npc_ids:
        all_34_npcs.extend([x.lower() for x in extra_npc_ids if x.lower() not in all_34_npcs])

    npcs_dict: Dict[str, Any] = {}
    is_sat = (day % 7 == 6)
    is_animal_fest = (season.lower() == "winter" and day == 10)

    for nid in all_34_npcs:
        is_vendor = nid in SATURDAY_MARKET_VENDORS
        is_fest_vendor = is_animal_fest and (nid in ANIMAL_FESTIVAL_ATTENDING_VENDORS)

        if present_npcs is not None:
            in_town = (nid in present_npcs)
        else:
            in_town = is_sat or (not is_vendor) or is_fest_vendor

        loc_id = "town" if in_town else "aldaria"
        can_gift = (nid in giftable_npcs) if giftable_npcs is not None else True
        hp = heart_points.get(nid, 0.0) if heart_points else 0.0

        npcs_dict[nid] = {
            "heart_points": hp,
            "gifts_given": [],
            "known_gift_preferences": [],
            "last_gift_date": None if can_gift else cal_time,
            "location_position": {"location_id": loc_id},
        }

    raw["npcs"] = json.dumps(npcs_dict)

    if chest_locations:
        for loc_name, chests in chest_locations.items():
            raw[loc_name] = json.dumps({"inventories": chests})

    save = SaveData(Path("/synthetic/test.sav"), raw)

    if unlocked_npcs is not None:
        save.get_unlocked_npc_ids = lambda: set(unlocked_npcs)
        save.is_npc_unlocked = lambda n: n.lower() in set(unlocked_npcs)

    return save


# ==============================================================================
# TEST SUITE 1: STRICT 5-TIER PRIORITY HIERARCHY
# ==============================================================================

class TestStrict5TierPriorityHierarchy(unittest.TestCase):
    """
    Stress-tests the strict 5-tier priority hierarchy:
      Specific Love (+20) > Universal Love (+20) > Specific Like (+10) > Universal Like (+10) > Skip (+0).
    Verifies all 2^4 = 16 boolean availability combinations for an NPC.
    """

    def setUp(self):
        self.npc_defs = {
            "adeline": {
                "name": "Adeline",
                "loved": {"apple_pie"},
                "liked": {"tulip"},
            }
        }
        self.item_meta = {
            "apple_pie": {"display_name": "Apple Pie"},
            "tulip": {"display_name": "Tulip"},
            "lovable_dish": {"display_name": "Lovable Dish"},
            "likable_dish": {"display_name": "Likable Dish"},
        }

    def test_all_16_tier_combinations(self):
        """
        Tests every possible combination of item availability for an NPC.
        Specific Love > Universal Love > Specific Like > Universal Like > Skip.
        """
        for has_spec_love, has_univ_love, has_spec_like, has_univ_like in itertools.product([True, False], repeat=4):
            with self.subTest(
                spec_love=has_spec_love,
                univ_love=has_univ_love,
                spec_like=has_spec_like,
                univ_like=has_univ_like,
            ):
                inventory: Dict[str, int] = {}
                if has_spec_love:
                    inventory["apple_pie"] = 1
                if has_spec_like:
                    inventory["tulip"] = 1

                infused_items: Dict[str, Any] = {}
                if has_univ_love:
                    infused_items["lovable"] = [{"item_id": "lovable_dish", "count": 1}]
                if has_univ_like:
                    infused_items["likable"] = [{"item_id": "likable_dish", "count": 1}]

                res = plan_max_relationship(
                    npc_gift_definitions=self.npc_defs,
                    item_metadata=self.item_meta,
                    inventory=inventory,
                    infused_items=infused_items,
                    force_all_npcs=True,
                )

                prog = res["npc_progress"]["adeline"]
                stats = res["overall_stats"]

                if has_spec_love:
                    self.assertEqual(prog["assigned_pref_type"], "LOVE")
                    self.assertEqual(prog["assigned_item_id"], "apple_pie")
                    self.assertEqual(prog["assigned_points"], 20)
                    self.assertEqual(stats["total_relationship_points"], 20)
                    self.assertIn("adeline", res["covered_npcs"])
                elif has_univ_love:
                    self.assertEqual(prog["assigned_pref_type"], "UNIV_LOVE")
                    self.assertEqual(prog["assigned_item_id"], "lovable_dish")
                    self.assertEqual(prog["assigned_points"], 20)
                    self.assertEqual(stats["total_relationship_points"], 20)
                    self.assertIn("adeline", res["covered_npcs"])
                elif has_spec_like:
                    self.assertEqual(prog["assigned_pref_type"], "LIKE")
                    self.assertEqual(prog["assigned_item_id"], "tulip")
                    self.assertEqual(prog["assigned_points"], 10)
                    self.assertEqual(stats["total_relationship_points"], 10)
                    self.assertIn("adeline", res["covered_npcs"])
                elif has_univ_like:
                    self.assertEqual(prog["assigned_pref_type"], "UNIV_LIKE")
                    self.assertEqual(prog["assigned_item_id"], "likable_dish")
                    self.assertEqual(prog["assigned_points"], 10)
                    self.assertEqual(stats["total_relationship_points"], 10)
                    self.assertIn("adeline", res["covered_npcs"])
                else:
                    self.assertIsNone(prog["assigned_pref_type"])
                    self.assertIsNone(prog["assigned_item_id"])
                    self.assertEqual(prog["assigned_points"], 0)
                    self.assertEqual(stats["total_relationship_points"], 0)
                    self.assertNotIn("adeline", res["covered_npcs"])

    def test_multi_npc_simultaneous_priority_tiers(self):
        """
        4 NPCs present simultaneously, each hitting a distinct tier of the hierarchy.
        Total relationship points must equal 20 + 20 + 10 + 10 = 60.
        """
        npc_defs = {
            "adeline": {"name": "Adeline", "loved": {"apple_pie"}, "liked": set()},
            "balor": {"name": "Balor", "loved": set(), "liked": set()},  # Univ Love
            "celine": {"name": "Celine", "loved": set(), "liked": {"tulip"}},
            "darcy": {"name": "Darcy", "loved": set(), "liked": set()},   # Univ Like
        }
        inventory = {
            "apple_pie": 1,
            "tulip": 1,
        }
        infused = {
            "lovable": [{"item_id": "berry_tart", "count": 1}],
            "likable": [{"item_id": "soup", "count": 1}],
        }
        res = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            item_metadata=self.item_meta,
            inventory=inventory,
            infused_items=infused,
            force_all_npcs=True,
        )
        self.assertEqual(res["npc_progress"]["adeline"]["assigned_pref_type"], "LOVE")
        self.assertEqual(res["npc_progress"]["balor"]["assigned_pref_type"], "UNIV_LOVE")
        self.assertEqual(res["npc_progress"]["celine"]["assigned_pref_type"], "LIKE")
        self.assertEqual(res["npc_progress"]["darcy"]["assigned_pref_type"], "UNIV_LIKE")
        self.assertEqual(res["overall_stats"]["total_relationship_points"], 60)
        self.assertEqual(len(res["covered_npcs"]), 4)


# ==============================================================================
# TEST SUITE 2: ABUNDANCE AND DETERMINISTIC TIE-BREAKING
# ==============================================================================

class TestMostAbundantItemAndTieBreaking(unittest.TestCase):
    """
    Stress-tests abundance ranking and deterministic tie-breaking:
    1. Highest inventory count is strictly prioritized.
    2. Equal inventory count is tie-broken by case-insensitive display name ascending.
    3. Equal display name is tie-broken by item_id ascending.
    4. Missing metadata gracefully falls back to item_id.
    5. Same rules apply to Universal dishes in infusion pools.
    """

    def test_specific_love_abundance_strictly_prioritized(self):
        """When multiple loved items are in inventory, the one with highest count is selected."""
        npc_defs = {
            "march": {"name": "March", "loved": {"iron_ingot", "copper_ingot", "gold_ingot"}, "liked": set()}
        }
        inventory = {
            "iron_ingot": 3,
            "copper_ingot": 12,  # Most abundant
            "gold_ingot": 7,
        }
        res = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            inventory=inventory,
            force_all_npcs=True,
        )
        self.assertEqual(res["npc_progress"]["march"]["assigned_item_id"], "copper_ingot")

    def test_specific_like_abundance_strictly_prioritized(self):
        """When multiple liked items are in inventory, the one with highest count is selected."""
        npc_defs = {
            "celine": {"name": "Celine", "loved": set(), "liked": {"daisy", "rose", "tulip"}}
        }
        inventory = {
            "daisy": 2,
            "rose": 15,  # Most abundant
            "tulip": 5,
        }
        res = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            inventory=inventory,
            force_all_npcs=True,
        )
        self.assertEqual(res["npc_progress"]["celine"]["assigned_item_id"], "rose")

    def test_equal_count_tie_broken_by_display_name_alphabetical(self):
        """Equal count items are tie-broken by display_name ascending."""
        npc_defs = {
            "adeline": {"name": "Adeline", "loved": {"item_z", "item_a"}, "liked": set()}
        }
        item_meta = {
            "item_z": {"display_name": "Albatross Feathers"},  # 'A'
            "item_a": {"display_name": "Zebra Hide"},          # 'Z'
        }
        inventory = {
            "item_z": 5,
            "item_a": 5,
        }
        res = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            item_metadata=item_meta,
            inventory=inventory,
            force_all_npcs=True,
        )
        # item_z has display_name 'Albatross Feathers', which comes before 'Zebra Hide'
        self.assertEqual(res["npc_progress"]["adeline"]["assigned_item_id"], "item_z")

    def test_equal_count_case_insensitive_display_name(self):
        """Display name tie-breaking is case-insensitive ('apple' before 'Banana')."""
        npc_defs = {
            "adeline": {"name": "Adeline", "loved": {"item_1", "item_2"}, "liked": set()}
        }
        item_meta = {
            "item_1": {"display_name": "apple tart"},  # lowercase 'a'
            "item_2": {"display_name": "Banana Pie"},  # uppercase 'B'
        }
        inventory = {"item_1": 4, "item_2": 4}
        res = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            item_metadata=item_meta,
            inventory=inventory,
            force_all_npcs=True,
        )
        self.assertEqual(res["npc_progress"]["adeline"]["assigned_item_id"], "item_1")

    def test_identical_display_name_tie_broken_by_item_id(self):
        """When display names are identical, item_id ascending breaks the tie."""
        npc_defs = {
            "adeline": {"name": "Adeline", "loved": {"beta_gem", "alpha_gem"}, "liked": set()}
        }
        item_meta = {
            "beta_gem": {"display_name": "Shiny Gem"},
            "alpha_gem": {"display_name": "Shiny Gem"},
        }
        inventory = {"beta_gem": 5, "alpha_gem": 5}
        res = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            item_metadata=item_meta,
            inventory=inventory,
            force_all_npcs=True,
        )
        self.assertEqual(res["npc_progress"]["adeline"]["assigned_item_id"], "alpha_gem")

    def test_missing_metadata_tie_broken_by_item_id(self):
        """When item_metadata is None or missing keys, item_id ascending breaks ties."""
        npc_defs = {
            "adeline": {"name": "Adeline", "loved": {"xylophone", "accordion"}, "liked": set()}
        }
        inventory = {"xylophone": 2, "accordion": 2}
        res = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            item_metadata=None,
            inventory=inventory,
            force_all_npcs=True,
        )
        self.assertEqual(res["npc_progress"]["adeline"]["assigned_item_id"], "accordion")

    def test_universal_love_abundance_and_tie_breaking(self):
        """Universal dishes also respect count abundance, then display name tie-breaking."""
        npc_defs = {
            "adeline": {"name": "Adeline", "loved": set(), "liked": set()},
        }
        item_meta = {
            "rare_pie": {"display_name": "Rare Apple Pie"},
            "common_pie": {"display_name": "Common Berry Tart"},
        }
        infused = {
            "lovable": [
                {"item_id": "rare_pie", "count": 1},
                {"item_id": "common_pie", "count": 5},  # More abundant
            ]
        }
        # 1 NPC: should pick common_pie (count 5 > 1)
        res1 = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            item_metadata=item_meta,
            infused_items=infused,
            force_all_npcs=True,
        )
        self.assertEqual(res1["npc_progress"]["adeline"]["assigned_item_id"], "common_pie")

        # 3 NPCs: common_pie count 2, rare_pie count 1
        # NPC 1: common_pie (count 2 > 1)
        # NPC 2: common_pie (count 1 == 1, Common 'C' < Rare 'R')
        # NPC 3: rare_pie (only one left)
        npc_defs_3 = {
            "npc_1": {"name": "NPC 1", "loved": set(), "liked": set()},
            "npc_2": {"name": "NPC 2", "loved": set(), "liked": set()},
            "npc_3": {"name": "NPC 3", "loved": set(), "liked": set()},
        }
        infused_3 = {
            "lovable": [
                {"item_id": "rare_pie", "count": 1},
                {"item_id": "common_pie", "count": 2},
            ]
        }
        res3 = plan_max_relationship(
            npc_gift_definitions=npc_defs_3,
            item_metadata=item_meta,
            infused_items=infused_3,
            force_all_npcs=True,
        )
        assigned = [
            res3["npc_progress"]["npc_1"]["assigned_item_id"],
            res3["npc_progress"]["npc_2"]["assigned_item_id"],
            res3["npc_progress"]["npc_3"]["assigned_item_id"],
        ]
        self.assertEqual(assigned.count("common_pie"), 2)
        self.assertEqual(assigned.count("rare_pie"), 1)


# ==============================================================================
# TEST SUITE 3: GREEDY CONSTRAINED ALLOCATION (MRV)
# ==============================================================================

class TestGreedyConstrainedAllocationMRV(unittest.TestCase):
    """
    Stress-tests Minimum Remaining Values (MRV) greedy allocation:
    Constrained NPCs (fewest available valid items in inventory) MUST be allocated
    before flexible NPCs, guaranteeing that shared items are not stolen.
    """

    def test_mrv_two_npc_shared_item_conflict(self):
        """
        NPC_Constrained loves only 'shared_item' (count 1).
        NPC_Flexible loves 'shared_item' (count 1) AND 'flexible_item' (count 1).
        MRV must assign 'shared_item' to NPC_Constrained, leaving 'flexible_item' for NPC_Flexible.
        Total points = 40 (both covered).
        """
        npc_defs = {
            "flexible_npc": {"name": "Flexible Frank", "loved": {"shared_item", "flexible_item"}, "liked": set()},
            "constrained_npc": {"name": "Constrained Carl", "loved": {"shared_item"}, "liked": set()},
        }
        inventory = {
            "shared_item": 1,
            "flexible_item": 1,
        }
        res = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            inventory=inventory,
            force_all_npcs=True,
        )
        self.assertEqual(res["npc_progress"]["constrained_npc"]["assigned_item_id"], "shared_item")
        self.assertEqual(res["npc_progress"]["flexible_npc"]["assigned_item_id"], "flexible_item")
        self.assertEqual(res["overall_stats"]["total_relationship_points"], 40)
        self.assertEqual(len(res["covered_npcs"]), 2)

    def test_mrv_three_npc_cascade(self):
        """
        Chain dependency:
          NPC_1 loves {A}.
          NPC_2 loves {A, B}.
          NPC_3 loves {B, C}.
        Inventory: A: 1, B: 1, C: 1.
        MRV cascade must assign A -> NPC_1, then B -> NPC_2, then C -> NPC_3.
        Total points = 60.
        """
        npc_defs = {
            "npc_1": {"name": "NPC One", "loved": {"item_a"}, "liked": set()},
            "npc_2": {"name": "NPC Two", "loved": {"item_a", "item_b"}, "liked": set()},
            "npc_3": {"name": "NPC Three", "loved": {"item_b", "item_c"}, "liked": set()},
        }
        inventory = {"item_a": 1, "item_b": 1, "item_c": 1}
        res = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            inventory=inventory,
            force_all_npcs=True,
        )
        self.assertEqual(res["npc_progress"]["npc_1"]["assigned_item_id"], "item_a")
        self.assertEqual(res["npc_progress"]["npc_2"]["assigned_item_id"], "item_b")
        self.assertEqual(res["npc_progress"]["npc_3"]["assigned_item_id"], "item_c")
        self.assertEqual(res["overall_stats"]["total_relationship_points"], 60)
        self.assertEqual(len(res["covered_npcs"]), 3)

    def test_mrv_five_npc_complex_cascade(self):
        """
        5 NPCs with complex overlapping sets:
          N1: {A}
          N2: {A, B}
          N3: {A, B, C}
          N4: {B, C, D}
          N5: {C, D, E}
        Inventory: A: 1, B: 1, C: 1, D: 1, E: 1.
        Every NPC must be assigned an optimal gift (total 100 points).
        """
        npc_defs = {
            "n1": {"name": "N1", "loved": {"a"}, "liked": set()},
            "n2": {"name": "N2", "loved": {"a", "b"}, "liked": set()},
            "n3": {"name": "N3", "loved": {"a", "b", "c"}, "liked": set()},
            "n4": {"name": "N4", "loved": {"b", "c", "d"}, "liked": set()},
            "n5": {"name": "N5", "loved": {"c", "d", "e"}, "liked": set()},
        }
        inventory = {"a": 1, "b": 1, "c": 1, "d": 1, "e": 1}
        res = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            inventory=inventory,
            force_all_npcs=True,
        )
        self.assertEqual(res["npc_progress"]["n1"]["assigned_item_id"], "a")
        self.assertEqual(res["npc_progress"]["n2"]["assigned_item_id"], "b")
        self.assertEqual(res["npc_progress"]["n3"]["assigned_item_id"], "c")
        self.assertEqual(res["npc_progress"]["n4"]["assigned_item_id"], "d")
        self.assertEqual(res["npc_progress"]["n5"]["assigned_item_id"], "e")
        self.assertEqual(res["overall_stats"]["total_relationship_points"], 100)
        self.assertEqual(len(res["covered_npcs"]), 5)

    def test_mrv_in_specific_like_stage(self):
        """MRV must also operate in Stage 3 for specific like gifts."""
        npc_defs = {
            "n1": {"name": "Like One", "loved": set(), "liked": {"item_x"}},
            "n2": {"name": "Like Two", "loved": set(), "liked": {"item_x", "item_y"}},
        }
        inventory = {"item_x": 1, "item_y": 1}
        res = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            inventory=inventory,
            force_all_npcs=True,
        )
        self.assertEqual(res["npc_progress"]["n1"]["assigned_item_id"], "item_x")
        self.assertEqual(res["npc_progress"]["n2"]["assigned_item_id"], "item_y")
        self.assertEqual(res["overall_stats"]["total_relationship_points"], 20)

    def test_mrv_equal_constraint_vendor_boost_on_saturday(self):
        """
        When two NPCs have identical MRV constraints (len(avail) == 1) on a Saturday,
        the Saturday Market visiting vendor receives priority over the permanent townsfolk.
        """
        npc_defs = {
            "adeline": {"name": "Adeline", "loved": {"rare_gem"}, "liked": set()},
            "darcy": {"name": "Darcy", "loved": {"rare_gem"}, "liked": set()},  # Visiting vendor
        }
        inventory = {"rare_gem": 1}
        save = make_synthetic_save(day=6)  # Day 6 is Saturday
        res = plan_max_relationship(
            save=save,
            npc_gift_definitions=npc_defs,
            inventory=inventory,
            mode="auto",
        )
        # Darcy is a Saturday vendor and boosted on Saturday -> Darcy gets the gem
        self.assertEqual(res["npc_progress"]["darcy"]["assigned_item_id"], "rare_gem")
        self.assertIsNone(res["npc_progress"]["adeline"]["assigned_item_id"])


# ==============================================================================
# TEST SUITE 4: EXACT INVENTORY DEDUCTION
# ==============================================================================

class TestExactInventoryDeduction(unittest.TestCase):
    """
    Stress-tests exact inventory deduction:
    Shared items cannot be over-allocated beyond the exact available count.
    """

    def test_oversubscribed_love_item_capped_strictly_at_inventory_count(self):
        """
        6 NPCs all love 'ruby'. Inventory has only 2 'ruby'.
        Exactly 2 NPCs must receive 'ruby'. Remaining 4 must be unassigned.
        Quantity packed in bag_plan must be exactly 2.
        """
        npc_defs = {
            f"npc_{i}": {"name": f"NPC {i}", "loved": {"ruby"}, "liked": set()}
            for i in range(6)
        }
        inventory = {"ruby": 2}
        res = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            inventory=inventory,
            force_all_npcs=True,
        )
        assigned_ruby_count = sum(
            1 for p in res["npc_progress"].values() if p.get("assigned_item_id") == "ruby"
        )
        self.assertEqual(assigned_ruby_count, 2)
        self.assertEqual(len(res["covered_npcs"]), 2)
        self.assertEqual(res["overall_stats"]["total_relationship_points"], 40)

        # Check bag plan slot
        self.assertEqual(len(res["bag_plan"]), 1)
        self.assertEqual(res["bag_plan"][0]["item_id"], "ruby")
        self.assertEqual(res["bag_plan"][0]["quantity_to_pack"], 2)

    def test_mixed_love_and_like_oversubscribed_item(self):
        """
        2 NPCs love 'bread', 2 NPCs like 'bread'. Inventory has 3 'bread'.
        Stage 1 (Love) consumes 2 'bread'.
        Stage 3 (Like) has only 1 'bread' left -> only 1 Like NPC gets 'bread'.
        1 Like NPC is skipped. Total assigned = 3.
        """
        npc_defs = {
            "love_1": {"name": "Love 1", "loved": {"bread"}, "liked": set()},
            "love_2": {"name": "Love 2", "loved": {"bread"}, "liked": set()},
            "like_1": {"name": "Like 1", "loved": set(), "liked": {"bread"}},
            "like_2": {"name": "Like 2", "loved": set(), "liked": {"bread"}},
        }
        inventory = {"bread": 3}
        res = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            inventory=inventory,
            force_all_npcs=True,
        )
        self.assertEqual(res["npc_progress"]["love_1"]["assigned_item_id"], "bread")
        self.assertEqual(res["npc_progress"]["love_2"]["assigned_item_id"], "bread")

        assigned_likes = [
            res["npc_progress"]["like_1"]["assigned_item_id"],
            res["npc_progress"]["like_2"]["assigned_item_id"],
        ]
        self.assertEqual(assigned_likes.count("bread"), 1)
        self.assertEqual(assigned_likes.count(None), 1)

        self.assertEqual(res["bag_plan"][0]["quantity_to_pack"], 3)
        self.assertEqual(res["overall_stats"]["total_relationship_points"], 20 + 20 + 10)  # 50

    def test_deduction_across_save_data_bag_and_chests(self):
        """
        Bag has 1 'soup', chest in 'farm' has 2 'soup', chest in 'mines' has 1 'soup'. Total = 4.
        6 NPCs love 'soup'. Exactly 4 must be assigned.
        """
        bag = [make_mock_slot("soup", 1)]
        chests = {
            "farm": [[make_mock_slot("soup", 2)]],
            "mines": [[make_mock_slot("soup", 1)]],
        }
        npc_defs = {
            f"npc_{i}": {"name": f"NPC {i}", "loved": {"soup"}, "liked": set()}
            for i in range(6)
        }
        save = make_synthetic_save(
            bag_slots=bag,
            chest_locations=chests,
            extra_npc_ids=list(npc_defs.keys()),
        )
        res = plan_max_relationship(
            save=save,
            npc_gift_definitions=npc_defs,
            force_all_npcs=True,
        )
        assigned_count = sum(
            1 for p in res["npc_progress"].values() if p.get("assigned_item_id") == "soup"
        )
        self.assertEqual(assigned_count, 4)
        self.assertEqual(res["bag_plan"][0]["quantity_to_pack"], 4)
        self.assertEqual(res["overall_stats"]["total_relationship_points"], 80)


# ==============================================================================
# TEST SUITE 5: DOUBLE-SPENDING PREVENTION
# ==============================================================================

class TestDoubleSpendingPrevention(unittest.TestCase):
    """
    Stress-tests double-spending prevention between physical inventory and infusion pools:
    An item stack cannot be gifted as a specific love/like gift AND as a universal gift
    if the total assignments exceed the available physical count.
    """

    def test_specific_love_exhausts_physical_and_infused_pool(self):
        """
        Player has 2 'apple_pie' (both infused 'lovable').
        Physical inventory = 2. Lovable pool = 2.
        NPC_1 and NPC_2 love 'apple_pie' specifically.
        NPC_3 needs Universal Love.
        Stage 1 consumes both apple pies as Specific Love.
        Stage 2 MUST NOT assign apple pie as Universal Love to NPC_3 (pool clamped to 0).
        """
        npc_defs = {
            "npc_1": {"name": "NPC 1", "loved": {"apple_pie"}, "liked": set()},
            "npc_2": {"name": "NPC 2", "loved": {"apple_pie"}, "liked": set()},
            "npc_3": {"name": "NPC 3", "loved": set(), "liked": set()},  # Needs univ love
        }
        bag = [make_mock_slot("apple_pie", 2, infusion="lovable")]
        save = make_synthetic_save(
            bag_slots=bag,
            extra_npc_ids=list(npc_defs.keys()),
        )

        res = plan_max_relationship(
            save=save,
            npc_gift_definitions=npc_defs,
            force_all_npcs=True,
        )
        self.assertEqual(res["npc_progress"]["npc_1"]["assigned_item_id"], "apple_pie")
        self.assertEqual(res["npc_progress"]["npc_1"]["assigned_pref_type"], "LOVE")
        self.assertEqual(res["npc_progress"]["npc_2"]["assigned_item_id"], "apple_pie")
        self.assertEqual(res["npc_progress"]["npc_2"]["assigned_pref_type"], "LOVE")
        # NPC_3 must be skipped (no dishes left)
        self.assertIsNone(res["npc_progress"]["npc_3"]["assigned_item_id"])
        self.assertEqual(res["overall_stats"]["total_relationship_points"], 40)
        self.assertEqual(res["bag_plan"][0]["quantity_to_pack"], 2)

    def test_universal_love_exhausts_physical_preventing_specific_like(self):
        """
        Player has 1 'berry_tart' (infused 'lovable').
        NPC_1 needs Universal Love.
        NPC_2 likes 'berry_tart' specifically.
        Stage 2 assigns 'berry_tart' to NPC_1 as Universal Love (+20).
        Stage 3 MUST NOT assign 'berry_tart' to NPC_2 as Specific Like (inventory is 0).
        Total assigned = 1.
        """
        npc_defs = {
            "npc_1": {"name": "NPC 1", "loved": set(), "liked": set()},  # Univ Love
            "npc_2": {"name": "NPC 2", "loved": set(), "liked": {"berry_tart"}},  # Specific Like
        }
        inventory = {"berry_tart": 1}
        infused = {"lovable": [{"item_id": "berry_tart", "count": 1}]}

        res = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            inventory=inventory,
            infused_items=infused,
            force_all_npcs=True,
        )
        self.assertEqual(res["npc_progress"]["npc_1"]["assigned_item_id"], "berry_tart")
        self.assertEqual(res["npc_progress"]["npc_1"]["assigned_pref_type"], "UNIV_LOVE")
        self.assertIsNone(res["npc_progress"]["npc_2"]["assigned_item_id"])
        self.assertEqual(res["overall_stats"]["total_relationship_points"], 20)
        self.assertEqual(res["bag_plan"][0]["quantity_to_pack"], 1)

    def test_mixed_regular_and_infused_stacks_exact_partition(self):
        """
        Player has 1 regular 'apple_pie' + 1 lovable 'apple_pie'. Total physical = 2.
        Lovable pool count = 1.
        NPC_1 loves 'apple_pie'.
        NPC_2 needs Universal Love.
        NPC_3 needs Universal Love.
        NPC_1 gets 'apple_pie' (Specific Love).
        NPC_2 gets 'apple_pie' (Universal Love).
        NPC_3 gets NOTHING (both apple pies exhausted).
        """
        npc_defs = {
            "npc_1": {"name": "NPC 1", "loved": {"apple_pie"}, "liked": set()},
            "npc_2": {"name": "NPC 2", "loved": set(), "liked": set()},
            "npc_3": {"name": "NPC 3", "loved": set(), "liked": set()},
        }
        bag = [
            make_mock_slot("apple_pie", 1, infusion=None),
            make_mock_slot("apple_pie", 1, infusion="lovable"),
        ]
        save = make_synthetic_save(
            bag_slots=bag,
            extra_npc_ids=list(npc_defs.keys()),
        )
        res = plan_max_relationship(
            save=save,
            npc_gift_definitions=npc_defs,
            force_all_npcs=True,
        )
        self.assertEqual(res["npc_progress"]["npc_1"]["assigned_item_id"], "apple_pie")
        self.assertEqual(res["npc_progress"]["npc_1"]["assigned_pref_type"], "LOVE")
        self.assertEqual(res["npc_progress"]["npc_2"]["assigned_item_id"], "apple_pie")
        self.assertEqual(res["npc_progress"]["npc_2"]["assigned_pref_type"], "UNIV_LOVE")
        self.assertIsNone(res["npc_progress"]["npc_3"]["assigned_item_id"])
        self.assertEqual(res["overall_stats"]["total_relationship_points"], 40)
        self.assertEqual(res["bag_plan"][0]["quantity_to_pack"], 2)

    def test_cross_pool_lovable_and_likable_zero_double_spending(self):
        """
        Player has 1 lovable 'soup' and 1 likable 'soup'. Total physical = 2.
        NPC_1 loves 'soup'.
        NPC_2 needs Universal Love.
        NPC_3 needs Universal Like.
        Stage 1: NPC_1 gets 'soup' (Specific Love). Rem = 1.
        Stage 2: NPC_2 gets 'soup' (Universal Love). Rem = 0.
        Stage 4: NPC_3 CANNOT get 'soup' (Universal Like pool clamped to 0!).
        Total assigned = 2.
        """
        npc_defs = {
            "npc_1": {"name": "NPC 1", "loved": {"soup"}, "liked": set()},
            "npc_2": {"name": "NPC 2", "loved": set(), "liked": set()},
            "npc_3": {"name": "NPC 3", "loved": set(), "liked": set()},
        }
        bag = [
            make_mock_slot("soup", 1, infusion="lovable"),
            make_mock_slot("soup", 1, infusion="likable"),
        ]
        save = make_synthetic_save(
            bag_slots=bag,
            extra_npc_ids=list(npc_defs.keys()),
        )
        res = plan_max_relationship(
            save=save,
            npc_gift_definitions=npc_defs,
            force_all_npcs=True,
        )
        self.assertEqual(res["npc_progress"]["npc_1"]["assigned_item_id"], "soup")
        self.assertEqual(res["npc_progress"]["npc_1"]["assigned_pref_type"], "LOVE")
        self.assertEqual(res["npc_progress"]["npc_2"]["assigned_item_id"], "soup")
        self.assertEqual(res["npc_progress"]["npc_2"]["assigned_pref_type"], "UNIV_LOVE")
        self.assertIsNone(res["npc_progress"]["npc_3"]["assigned_item_id"])
        self.assertEqual(res["overall_stats"]["total_relationship_points"], 40)
        self.assertEqual(res["bag_plan"][0]["quantity_to_pack"], 2)


# ==============================================================================
# TEST SUITE 6: CAPACITY BUDGETING AND ROLLBACK
# ==============================================================================

class TestCapacityBudgetingAndRollback(unittest.TestCase):
    """
    Stress-tests bag slot capacity limits (max_slots):
    1. Items beyond max_slots are truncated from bag_plan.
    2. Assignments for truncated items are cleanly rolled back in npc_progress.
    3. overall_stats['total_relationship_points'] matches only packed items.
    4. max_slots=0 and max_slots < 0 are handled safely.
    """

    def test_max_slots_truncation_and_clean_rollback(self):
        """
        3 NPCs love 3 distinct items (A, B, C).
        max_slots=2 means 1 item must be dropped.
        Item delivering fewest points / lowest rank is dropped, and its NPC is rolled back.
        """
        npc_defs = {
            "n1": {"name": "N1", "loved": {"item_a"}, "liked": set()},
            "n2": {"name": "N2", "loved": {"item_b"}, "liked": set()},
            "n3": {"name": "N3", "loved": set(), "liked": {"item_c"}},  # 10 pts (lowest)
        }
        inventory = {"item_a": 1, "item_b": 1, "item_c": 1}
        res = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            inventory=inventory,
            max_slots=2,
            force_all_npcs=True,
        )
        self.assertEqual(len(res["bag_plan"]), 2)
        packed_ids = {b["item_id"] for b in res["bag_plan"]}
        self.assertEqual(packed_ids, {"item_a", "item_b"})

        # N3 was assigned item_c (10 pts), but item_c was truncated -> N3 rolled back
        prog_n3 = res["npc_progress"]["n3"]
        self.assertIsNone(prog_n3["assigned_item_id"])
        self.assertIsNone(prog_n3["assigned_pref_type"])
        self.assertEqual(prog_n3["assigned_points"], 0)
        self.assertNotIn("n3", res["covered_npcs"])

        # Total points must reflect only packed items (20 + 20 = 40)
        self.assertEqual(res["overall_stats"]["total_relationship_points"], 40)

    def test_max_slots_zero_and_negative(self):
        """max_slots=0 or negative results in empty bag_plan, 0 points, and no errors."""
        npc_defs = {
            "n1": {"name": "N1", "loved": {"item_a"}, "liked": set()},
        }
        inventory = {"item_a": 5}
        for slots in [0, -1, -10]:
            with self.subTest(max_slots=slots):
                res = plan_max_relationship(
                    npc_gift_definitions=npc_defs,
                    inventory=inventory,
                    max_slots=slots,
                    force_all_npcs=True,
                )
                self.assertEqual(len(res["bag_plan"]), 0)
                self.assertEqual(res["overall_stats"]["total_relationship_points"], 0)
                self.assertEqual(len(res["covered_npcs"]), 0)
                self.assertIsNone(res["npc_progress"]["n1"]["assigned_item_id"])


# ==============================================================================
# TEST SUITE 7: NPC PRESENCE, FESTIVAL & LOCK STATE RULES
# ==============================================================================

class TestNPCPresenceAndFestivalRules(unittest.TestCase):
    """
    Stress-tests game calendar, Saturday Market, festival, and progression lock logic.
    """

    def setUp(self):
        self.npc_defs = {
            "adeline": {"name": "Adeline", "loved": {"apple_pie"}, "liked": set()},
            "darcy": {"name": "Darcy", "loved": {"apple_pie"}, "liked": set()},      # Saturday Vendor
            "louis": {"name": "Louis", "loved": {"apple_pie"}, "liked": set()},      # Fest Vendor
            "merri": {"name": "Merri", "loved": {"apple_pie"}, "liked": set()},      # Fest Vendor
            "caldarus": {"name": "Caldarus", "loved": {"apple_pie"}, "liked": set()},# Story gated
        }
        self.inventory = {"apple_pie": 10}

    def test_saturday_market_vendors_absent_on_weekdays_in_auto_mode(self):
        """On a weekday (Monday), Darcy is absent in town and cannot receive gifts."""
        save = make_synthetic_save(day=1)  # Day 1 is Monday
        res = plan_max_relationship(
            save=save,
            npc_gift_definitions=self.npc_defs,
            inventory=self.inventory,
            mode="auto",
        )
        self.assertNotIn("darcy", res["target_npcs"])
        self.assertIn("Darcy", res["overall_stats"]["not_present_npcs"])
        self.assertIsNone(res["npc_progress"]["darcy"]["assigned_item_id"])

    def test_saturday_market_vendors_present_on_saturdays_in_auto_mode(self):
        """On Saturday (Day 6), Darcy is present in town and can receive gifts."""
        save = make_synthetic_save(day=6)  # Day 6 is Saturday
        res = plan_max_relationship(
            save=save,
            npc_gift_definitions=self.npc_defs,
            inventory=self.inventory,
            mode="auto",
        )
        self.assertIn("darcy", res["target_npcs"])
        self.assertEqual(res["npc_progress"]["darcy"]["assigned_item_id"], "apple_pie")

    def test_animal_festival_winter_10_presence(self):
        """
        On Winter 10 (Animal Festival):
        Louis and Merri attend the festival and are present in town.
        Darcy does not attend and is absent.
        """
        save = make_synthetic_save(season="winter", day=10)
        res = plan_max_relationship(
            save=save,
            npc_gift_definitions=self.npc_defs,
            inventory=self.inventory,
            mode="auto",
        )
        self.assertIn("louis", res["target_npcs"])
        self.assertIn("merri", res["target_npcs"])
        self.assertNotIn("darcy", res["target_npcs"])
        self.assertEqual(res["npc_progress"]["louis"]["assigned_item_id"], "apple_pie")
        self.assertEqual(res["npc_progress"]["merri"]["assigned_item_id"], "apple_pie")

    def test_locked_npcs_excluded_from_targeting(self):
        """Locked NPCs (e.g. story gated Caldarus) must not be targeted."""
        unlocked = ["adeline", "darcy", "louis", "merri"]  # caldarus locked
        save = make_synthetic_save(day=6, unlocked_npcs=unlocked)
        res = plan_max_relationship(
            save=save,
            npc_gift_definitions=self.npc_defs,
            inventory=self.inventory,
            mode="all",
        )
        self.assertNotIn("caldarus", res["target_npcs"])
        self.assertIn("Caldarus", res["overall_stats"]["locked_npcs"])
        self.assertIsNone(res["npc_progress"]["caldarus"]["assigned_item_id"])

    def test_exclude_npcs_case_insensitive(self):
        """exclude_npcs parameter correctly filters out specified NPCs case-insensitively."""
        res = plan_max_relationship(
            npc_gift_definitions=self.npc_defs,
            inventory=self.inventory,
            exclude_npcs={"ADELINE", "  darcy  "},
            force_all_npcs=True,
        )
        self.assertNotIn("adeline", res["target_npcs"])
        self.assertNotIn("darcy", res["target_npcs"])


# ==============================================================================
# TEST SUITE 8: SCALE, FUZZING & INVARIANT PROPERTY VERIFICATION
# ==============================================================================

class TestScaleFuzzingAndInvariants(unittest.TestCase):
    """
    Scale and property-based stress tests:
    1. Large scale: 50 NPCs, 100 items, verify execution speed (< 0.5s).
    2. Strict invariant: total items allocated across all NPCs <= initial inventory count for every item.
    3. Strict invariant: total_relationship_points == sum(assigned_points for covered NPCs).
    4. Strict invariant: every covered NPC receives an item in their preference set (or universal dish).
    """

    def test_large_scale_and_property_invariants(self):
        """Simulates 40 NPCs and 80 items with random overlapping preferences."""
        import random
        rng = random.Random(42)

        items = [f"item_{i:03d}" for i in range(80)]
        meta = {iid: {"display_name": f"Item {iid.upper()}"} for iid in items}

        npc_defs: Dict[str, dict] = {}
        for n_idx in range(40):
            nid = f"npc_{n_idx:02d}"
            loved = set(rng.sample(items, k=5))
            liked = set(rng.sample(items, k=10)) - loved
            npc_defs[nid] = {
                "name": f"NPC {n_idx}",
                "loved": loved,
                "liked": liked,
            }

        # Sparse inventory
        inventory = {iid: rng.randint(0, 3) for iid in items}
        infused = {
            "lovable": [{"item_id": "item_000", "count": 2}],
            "likable": [{"item_id": "item_001", "count": 3}],
        }

        t0 = time.perf_counter()
        res = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            item_metadata=meta,
            inventory=inventory,
            infused_items=infused,
            force_all_npcs=True,
            max_slots=20,
        )
        elapsed = time.perf_counter() - t0

        self.assertLess(elapsed, 0.5, f"Execution too slow: {elapsed:.4f}s")

        # Invariant 1: Total points == sum of individual points of covered NPCs
        expected_points = sum(
            res["npc_progress"][nid]["assigned_points"]
            for nid in res["covered_npcs"]
        )
        self.assertEqual(res["overall_stats"]["total_relationship_points"], expected_points)

        # Invariant 2: Slots packed <= max_slots
        self.assertLessEqual(len(res["bag_plan"]), 20)

        # Invariant 3: Quantity allocated per item in bag_plan <= initial inventory (or infused)
        for b in res["bag_plan"]:
            iid = b["item_id"]
            packed_qty = b["quantity_to_pack"]
            init_cnt = inventory.get(iid, 0)
            # If infused, count could include infused pool
            infused_cnt = 0
            if iid == "item_000":
                infused_cnt = 2
            elif iid == "item_001":
                infused_cnt = 3
            max_avail = max(init_cnt, infused_cnt, init_cnt + infused_cnt)
            self.assertLessEqual(
                packed_qty,
                max_avail,
                f"Item {iid} over-allocated: packed {packed_qty}, available {max_avail}",
            )



# ==============================================================================
# TEST SUITE 9: ADVERSARIAL INPUT TYPES AND DEFENSIVE NORMALIZATION
# ==============================================================================

class TestAdversarialInputDataTypes(unittest.TestCase):
    """
    Stress-tests edge case data types, corrupted inputs, and normalization robustness:
    1. Inventory with negative, zero, float, string-numeric, non-numeric, and None counts.
    2. Infused items in all supported formats: R1 SaveData, count dict, string lists, slot dicts, 'likeable' spelling.
    3. Malformed and corrupted save data surviving gracefully without uncaught exceptions.
    """

    def test_inventory_count_types_and_normalization(self):
        """Validates that exotic inventory counts (strings, floats, negatives) are parsed safely."""
        npc_defs = {
            "adeline": {"name": "Adeline", "loved": {"apple", "banana", "cherry", "date"}, "liked": set()}
        }
        adversarial_inv = {
            "apple": -5,           # Negative -> ignored
            "banana": 0,           # Zero -> ignored
            "cherry": "2.0",       # Numeric string -> parsed to 2
            "date": 3.7,           # Float -> rounded to 4
            "invalid_str": "foo",  # Non-numeric string -> ignored
            "": 10,                # Empty key -> ignored
            None: 5,               # None key -> ignored
            "elderberry": None,    # None value -> ignored
        }
        res = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            inventory=adversarial_inv,
            force_all_npcs=True,
        )
        # Most abundant among valid candidates: date has 4 (rounded from 3.7), cherry has 2
        # apple (-5) and banana (0) are not available
        self.assertEqual(res["npc_progress"]["adeline"]["assigned_item_id"], "date")

    def test_infused_items_all_format_variations(self):
        """Tests that _normalize_infused_pool handles all supported formats and spellings."""
        npc_defs = {"adeline": {"name": "Adeline", "loved": set(), "liked": set()}}

        # Format 1: String list
        res_list = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            infused_items={"lovable": ["dish_a", "dish_b"]},
            force_all_npcs=True,
        )
        self.assertEqual(res_list["npc_progress"]["adeline"]["assigned_pref_type"], "UNIV_LOVE")

        # Format 2: Count dict
        res_dict = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            infused_items={"lovable": {"dish_c": 3}},
            force_all_npcs=True,
        )
        self.assertEqual(res_dict["npc_progress"]["adeline"]["assigned_item_id"], "dish_c")

        # Format 3: Flat list of slot dicts
        slot_list = [
            {"item": {"item_id": "dish_d", "infusion": "lovable"}, "count": 1},
        ]
        res_slots = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            infused_items=slot_list,
            force_all_npcs=True,
        )
        self.assertEqual(res_slots["npc_progress"]["adeline"]["assigned_item_id"], "dish_d")

        # Format 4: 'likeable' alternative spelling
        res_spelling = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            infused_items={"likeable": [{"item_id": "soup_alt", "count": 1}]},
            force_all_npcs=True,
        )
        self.assertEqual(res_spelling["npc_progress"]["adeline"]["assigned_item_id"], "soup_alt")
        self.assertEqual(res_spelling["npc_progress"]["adeline"]["assigned_pref_type"], "UNIV_LIKE")

    def test_corrupted_save_methods_fallback_cleanly(self):
        """When save methods raise exceptions, plan_max_relationship recovers gracefully."""
        class CorruptSave:
            def get_all_available_items(self):
                raise RuntimeError("Simulated bag corruption!")
            def get_infused_items(self):
                raise ValueError("Simulated chest corruption!")
            def is_npc_unlocked(self, nid):
                raise KeyError("Simulated lock state error!")
            def can_gift_npc_today(self, nid):
                raise AttributeError("Simulated calendar crash!")

        npc_defs = {"adeline": {"name": "Adeline", "loved": {"apple"}, "liked": set()}}
        res = plan_max_relationship(
            save=CorruptSave(),
            npc_gift_definitions=npc_defs,
            inventory={"apple": 1},
            force_all_npcs=True,
        )
        self.assertEqual(res["npc_progress"]["adeline"]["assigned_item_id"], "apple")
        self.assertEqual(res["overall_stats"]["total_relationship_points"], 20)


# ==============================================================================
# TEST SUITE 10: COMPLEX MRV TOPOLOGIES
# ==============================================================================

class TestComplexMRVTopologies(unittest.TestCase):
    """
    Stress-tests complex dependency topologies to ensure MRV always finds optimal allocations:
    1. Star topology: 1 hyper-flexible hub NPC, 5 constrained leaf NPCs.
    2. Cyclic preference chain: A->B, B->C, C->A.
    """

    def test_star_topology_hub_vs_leaves(self):
        """
        Hub NPC loves {A, B, C, D, E}.
        Leaf NPCs:
          L1 loves {A}
          L2 loves {B}
          L3 loves {C}
          L4 loves {D}
        Inventory: 1 of each (A, B, C, D, E).
        At every step, leaves have MRV=1 while Hub has MRV >= 2.
        MRV must allocate exclusive items to leaves L1-L4, and Hub gets E.
        Total points = 100 (all 5 covered).
        """
        npc_defs = {
            "hub": {"name": "Hub", "loved": {"item_a", "item_b", "item_c", "item_d", "item_e"}, "liked": set()},
            "leaf_1": {"name": "Leaf 1", "loved": {"item_a"}, "liked": set()},
            "leaf_2": {"name": "Leaf 2", "loved": {"item_b"}, "liked": set()},
            "leaf_3": {"name": "Leaf 3", "loved": {"item_c"}, "liked": set()},
            "leaf_4": {"name": "Leaf 4", "loved": {"item_d"}, "liked": set()},
        }
        inventory = {"item_a": 1, "item_b": 1, "item_c": 1, "item_d": 1, "item_e": 1}
        res = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            inventory=inventory,
            force_all_npcs=True,
        )
        self.assertEqual(res["npc_progress"]["leaf_1"]["assigned_item_id"], "item_a")
        self.assertEqual(res["npc_progress"]["leaf_2"]["assigned_item_id"], "item_b")
        self.assertEqual(res["npc_progress"]["leaf_3"]["assigned_item_id"], "item_c")
        self.assertEqual(res["npc_progress"]["leaf_4"]["assigned_item_id"], "item_d")
        self.assertEqual(res["npc_progress"]["hub"]["assigned_item_id"], "item_e")
        self.assertEqual(res["overall_stats"]["total_relationship_points"], 100)
        self.assertEqual(len(res["covered_npcs"]), 5)

    def test_cyclic_preference_chain(self):
        """
        Cyclic loop:
          C1: {A, B}
          C2: {B, C}
          C3: {C, A}
        Inventory: A: 1, B: 1, C: 1.
        All 3 NPCs must receive a loved gift (total points = 60).
        """
        npc_defs = {
            "c1": {"name": "C1", "loved": {"item_a", "item_b"}, "liked": set()},
            "c2": {"name": "C2", "loved": {"item_b", "item_c"}, "liked": set()},
            "c3": {"name": "C3", "loved": {"item_c", "item_a"}, "liked": set()},
        }
        inventory = {"item_a": 1, "item_b": 1, "item_c": 1}
        res = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            inventory=inventory,
            force_all_npcs=True,
        )
        assigned = {
            res["npc_progress"]["c1"]["assigned_item_id"],
            res["npc_progress"]["c2"]["assigned_item_id"],
            res["npc_progress"]["c3"]["assigned_item_id"],
        }
        self.assertEqual(assigned, {"item_a", "item_b", "item_c"})
        self.assertEqual(res["overall_stats"]["total_relationship_points"], 60)
        self.assertEqual(len(res["covered_npcs"]), 3)


# ==============================================================================
# TEST SUITE 11: INTERFACE CONTRACT AND FIELD COMPLIANCE
# ==============================================================================

class TestInterfaceContractAndKeyCompliance(unittest.TestCase):
    """
    Validates complete interface contract compliance of the returned dictionary:
    1. Top-level dictionary keys.
    2. bag_plan slot entry keys and types.
    3. npc_progress dictionary keys and types.
    4. overall_stats dictionary keys and types.
    """

    def test_complete_return_dictionary_structure(self):
        """Verifies every required key is present with expected types."""
        npc_defs = {
            "adeline": {"name": "Adeline", "loved": {"apple_pie"}, "liked": {"tulip"}},
            "darcy": {"name": "Darcy", "loved": set(), "liked": {"soup"}},
        }
        inventory = {"apple_pie": 2, "soup": 1}
        res = plan_max_relationship(
            npc_gift_definitions=npc_defs,
            inventory=inventory,
            force_all_npcs=True,
        )

        expected_top_keys = {
            "bag_plan", "npc_progress", "covered_npcs", "target_npcs",
            "remaining_items_map", "all_remaining_items_map", "today_remaining_items_map",
            "focus_suggestions", "overall_stats", "infused_items",
        }
        self.assertTrue(expected_top_keys.issubset(set(res.keys())))

        # Validate bag_plan keys
        self.assertGreater(len(res["bag_plan"]), 0)
        slot_entry = res["bag_plan"][0]
        expected_slot_keys = {
            "slot", "item_id", "item_name", "quantity_to_pack", "status",
            "availability_tier", "status_badge", "crafting_chain", "crafting_plan",
            "max_craftable", "raw_materials_needed", "loved_recipients_today",
            "liked_recipients_today", "all_recipients_today", "market_vendors_covered",
            "all_potential_loved", "all_potential_liked", "bin_price", "store_price",
            "tags", "description",
        }
        self.assertTrue(expected_slot_keys.issubset(set(slot_entry.keys())))

        # Validate npc_progress keys
        prog_entry = res["npc_progress"]["adeline"]
        expected_prog_keys = {
            "name", "hp", "is_vendor", "is_unlocked", "is_present_today",
            "can_gift_today", "loved", "liked", "gifts_given_count",
            "given_loved_count", "given_liked_count", "remaining_loved",
            "remaining_liked", "remaining_loved_count", "remaining_liked_count",
            "total_remaining", "pct_loved_done", "pct_total_done",
            "assigned_item_id", "assigned_item_name", "assigned_pref_type",
            "assigned_points",
        }
        self.assertTrue(expected_prog_keys.issubset(set(prog_entry.keys())))

        # Validate overall_stats keys
        stats = res["overall_stats"]
        expected_stats_keys = {
            "strategy", "total_relationship_points", "mode", "planning_for_saturday",
            "is_animal_festival", "target_npcs_count", "covered_npcs_count",
            "unlocked_npcs_count", "unlocked_vendors_count", "unlocked_townsfolk_count",
            "slots_used", "max_slots", "today_loved_completed", "today_liked_completed",
            "today_total_completed", "vendors_covered_today", "game_total_loved",
            "game_total_liked", "game_total_preferences", "game_given_loved",
            "game_given_liked", "game_given_total", "remaining_unique_items",
            "ungiftable_npcs", "not_present_npcs", "locked_npcs", "infused_items_detected",
        }
        self.assertTrue(expected_stats_keys.issubset(set(stats.keys())))
        self.assertEqual(stats["strategy"], "max-relationship")


# ============================================================================
# 4. ADVERSARIAL SCENARIOS 9 TO 15
# ============================================================================

class TestM4AdversarialScenarios9To15(unittest.TestCase):
    """
    Adversarial challenge test suite for Milestone 4 (Scenarios 9 to 15).
    Evaluates algorithmic correctness, invariant preservation, mutation sensitivity,
    and stress boundaries for:
      - Priority hierarchy (5 tiers)
      - Shared inventory deduction without negative balances
      - MRV greedy constrained allocation
      - Empty inventory & no giftable NPCs resilience
      - Mathematical points calculation
      - Saturday Market vendor presence vs absence
    """

    def setUp(self):
        self.mock_meta = get_mock_meta()
        self.mock_npcs = get_mock_npcs()

    # =========================================================================
    # 1. MRV ALLOCATION & DISCRIMINATION (Scenario 11 Adversarial Stress)
    # =========================================================================

    def test_mrv_true_discriminator_prevents_flexible_starvation(self):
        """
        Adversarial Challenge for Scenario 11:
        Verifies that when flexible NPC (Aaron, 'a') has a tie-breaking preference
        for the shared item over their alternative, MRV correctly prioritizes
        the constrained NPC (Zoe, 'z') first.
        
        Without MRV, Aaron would steal golden_cheesecake (since 'Golden Cheesecake' < 'Strawberry Shortcake'
        alphabetically), starving Zoe (0 points, total 20).
        With MRV, Zoe receives golden_cheesecake and Aaron receives strawberry_shortcake (total 40).
        """
        custom_npcs = {
            "zoe": {"name": "Zoe", "loved": ["golden_cheesecake"], "liked": []},
            "aaron": {"name": "Aaron", "loved": ["golden_cheesecake", "strawberry_shortcake"], "liked": []},
        }
        # Exactly 1 of each item:
        inv = {"golden_cheesecake": 1, "strawberry_shortcake": 1}

        plan = plan_max_relationship(
            npc_gift_definitions=custom_npcs,
            item_metadata=self.mock_meta,
            inventory=inv,
        )

        self.assertEqual(plan["npc_progress"]["zoe"]["assigned_item_id"], "golden_cheesecake")
        self.assertEqual(plan["npc_progress"]["zoe"]["assigned_points"], 20)
        self.assertEqual(plan["npc_progress"]["aaron"]["assigned_item_id"], "strawberry_shortcake")
        self.assertEqual(plan["npc_progress"]["aaron"]["assigned_points"], 20)
        self.assertEqual(plan["overall_stats"]["total_relationship_points"], 40)
        self.assertEqual(plan["overall_stats"]["covered_npcs_count"], 2)

    def test_mrv_three_tier_constraint_cascade(self):
        """
        Stress test: 3-tier cascade of constraints.
        NPC 1 (most constrained): 1 option  -> item_a
        NPC 2 (medium constrained): 2 options -> item_a, item_b
        NPC 3 (least constrained): 3 options -> item_a, item_b, item_c
        Inventory: 1 of each item.
        Alphabetical order inverted (NPC 3 is named 'Aaron', NPC 1 is named 'Zoe').
        MRV must allocate NPC 1 -> item_a, NPC 2 -> item_b, NPC 3 -> item_c.
        """
        custom_npcs = {
            "npc_zoe": {"name": "Zoe", "loved": ["item_a"], "liked": []},
            "npc_maya": {"name": "Maya", "loved": ["item_a", "item_b"], "liked": []},
            "npc_aaron": {"name": "Aaron", "loved": ["item_a", "item_b", "item_c"], "liked": []},
        }
        inv = {"item_a": 1, "item_b": 1, "item_c": 1}
        meta = {
            "item_a": {"display_name": "Apple"},
            "item_b": {"display_name": "Berry"},
            "item_c": {"display_name": "Cherry"},
        }

        plan = plan_max_relationship(
            npc_gift_definitions=custom_npcs,
            item_metadata=meta,
            inventory=inv,
        )

        self.assertEqual(plan["npc_progress"]["npc_zoe"]["assigned_item_id"], "item_a")
        self.assertEqual(plan["npc_progress"]["npc_maya"]["assigned_item_id"], "item_b")
        self.assertEqual(plan["npc_progress"]["npc_aaron"]["assigned_item_id"], "item_c")
        self.assertEqual(plan["overall_stats"]["covered_npcs_count"], 3)
        self.assertEqual(plan["overall_stats"]["total_relationship_points"], 60)

    # =========================================================================
    # 2. SHARED INVENTORY & CONCURRENCY (Scenario 10 Adversarial Stress)
    # =========================================================================

    def test_high_concurrency_inventory_depletion_no_negative_balance(self):
        """
        Stress test for Scenario 10:
        10 NPCs contending for 3 units of item_x and 2 units of item_y.
        Verifies exact depletion, zero negative balances, and clean unassigned fallback.
        """
        custom_npcs = {
            f"npc_{i:02d}": {
                "name": f"NPC_{i:02d}",
                "loved": ["shared_pie"],
                "liked": ["shared_soup"],
            }
            for i in range(10)
        }
        inv = {"shared_pie": 3, "shared_soup": 2}

        plan = plan_max_relationship(
            npc_gift_definitions=custom_npcs,
            item_metadata=self.mock_meta,
            inventory=inv,
        )

        assigned_pies = sum(1 for p in plan["npc_progress"].values() if p["assigned_item_id"] == "shared_pie")
        assigned_soups = sum(1 for p in plan["npc_progress"].values() if p["assigned_item_id"] == "shared_soup")
        unassigned = sum(1 for p in plan["npc_progress"].values() if p["assigned_item_id"] is None)

        self.assertEqual(assigned_pies, 3, "Must assign exactly 3 loved pies")
        self.assertEqual(assigned_soups, 2, "Must assign exactly 2 liked soups")
        self.assertEqual(unassigned, 5, "Remaining 5 NPCs must be skipped")
        self.assertEqual(plan["overall_stats"]["total_relationship_points"], 3 * 20 + 2 * 10)
        self.assertEqual(plan["overall_stats"]["covered_npcs_count"], 5)
        self.assertEqual(plan["overall_stats"]["target_npcs_count"], 10)

    def test_cross_pool_bidirectional_sync_strict_limits(self):
        """
        Stress test: Physical inventory vs lovable and likable pools.
        1 item exists in physical inventory and is marked lovable.
        If consumed as specific love, universal pool must be 0.
        If consumed as universal love, physical inventory must be 0.
        """
        custom_npcs = {
            "alice": {"name": "Alice", "loved": ["apple_pie"], "liked": []},
            "bob": {"name": "Bob", "loved": ["other_item"], "liked": []},
        }
        plan = plan_max_relationship(
            npc_gift_definitions=custom_npcs,
            inventory={"apple_pie": 1},
            infused_items={"lovable": [{"item_id": "apple_pie", "count": 1}], "likable": []},
        )
        self.assertEqual(plan["overall_stats"]["covered_npcs_count"], 1)
        self.assertEqual(plan["overall_stats"]["total_relationship_points"], 20)
        self.assertEqual(plan["npc_progress"]["alice"]["assigned_item_id"], "apple_pie")
        self.assertIsNone(plan["npc_progress"]["bob"]["assigned_item_id"])

    # =========================================================================
    # 3. PRIORITY HIERARCHY & REJECTION (Scenario 9 Adversarial Stress)
    # =========================================================================

    def test_priority_hierarchy_comprehensive_matrix(self):
        """
        Adversarial matrix testing all preference levels simultaneously:
        NPC 1: Love available -> Gets Love (+20)
        NPC 2: Univ Love available -> Gets Univ Love (+20)
        NPC 3: Like available -> Gets Like (+10)
        NPC 4: Univ Like available -> Gets Univ Like (+10)
        NPC 5: Neutral only available -> Gets None (+0)
        NPC 6: Dislike only available -> Gets None (+0)
        """
        custom_npcs = {
            "n1": {"name": "1_N1", "loved": ["pie"], "liked": []},
            "n2": {"name": "2_N2", "loved": ["absent_1"], "liked": []},
            "n3": {"name": "3_N3", "loved": ["absent_2"], "liked": ["strawberry"]},
            "n4": {"name": "4_N4", "loved": ["absent_3"], "liked": ["absent_4"]},
            "n5": {"name": "5_N5", "loved": ["absent_5"], "liked": ["absent_6"]},
            "n6": {"name": "6_N6", "loved": [], "liked": []},
        }
        inv = {
            "pie": 1,
            "strawberry": 1,
            "stone": 100,      # neutral
            "weed": 50,        # dislike
        }
        infused = {
            "lovable": [{"item_id": "dish_love", "count": 1}],
            "likable": [{"item_id": "dish_like", "count": 1}],
        }
        plan = plan_max_relationship(
            npc_gift_definitions=custom_npcs,
            item_metadata=self.mock_meta,
            inventory=inv,
            infused_items=infused,
        )

        p = plan["npc_progress"]
        self.assertEqual((p["n1"]["assigned_item_id"], p["n1"]["assigned_pref_type"]), ("pie", "LOVE"))
        self.assertEqual((p["n2"]["assigned_item_id"], p["n2"]["assigned_pref_type"]), ("dish_love", "UNIV_LOVE"))
        self.assertEqual((p["n3"]["assigned_item_id"], p["n3"]["assigned_pref_type"]), ("strawberry", "LIKE"))
        self.assertEqual((p["n4"]["assigned_item_id"], p["n4"]["assigned_pref_type"]), ("dish_like", "UNIV_LIKE"))
        self.assertIsNone(p["n5"]["assigned_item_id"])
        self.assertIsNone(p["n6"]["assigned_item_id"])
        self.assertEqual(plan["overall_stats"]["total_relationship_points"], 20 + 20 + 10 + 10)

    # =========================================================================
    # 4. MATHEMATICAL INVARIANTS (Scenario 14 Stress)
    # =========================================================================

    def test_mathematical_points_invariants_across_heterogeneous_roster(self):
        """
        Stress test: Roster with diverse point allocations verifying strict invariant:
        total_relationship_points == 20 * today_loved_completed + 10 * today_liked_completed
        """
        npcs = {
            "n_love1": {"name": "L1", "loved": ["cake"], "liked": []},
            "n_love2": {"name": "L2", "loved": ["cake"], "liked": []},
            "n_ulove": {"name": "UL", "loved": ["absent"], "liked": []},
            "n_like1": {"name": "K1", "loved": [], "liked": ["berry"]},
            "n_ulike": {"name": "UK", "loved": [], "liked": ["absent"]},
            "n_skip":  {"name": "SK", "loved": ["absent"], "liked": []},
        }
        inv = {"cake": 2, "berry": 1}
        infused = {
            "lovable": [{"item_id": "dish_l", "count": 1}],
            "likable": [{"item_id": "dish_k", "count": 1}],
        }
        plan = plan_max_relationship(
            npc_gift_definitions=npcs,
            inventory=inv,
            infused_items=infused,
        )

        stats = plan["overall_stats"]
        expected_points = 20 * stats["today_loved_completed"] + 10 * stats["today_liked_completed"]
        self.assertEqual(stats["total_relationship_points"], expected_points)
        self.assertEqual(stats["today_loved_completed"], 3)  # 2 specific + 1 universal
        self.assertEqual(stats["today_liked_completed"], 2)  # 1 specific + 1 universal
        self.assertEqual(stats["today_total_completed"], 5)
        self.assertEqual(stats["total_relationship_points"], 80)
        self.assertEqual(stats["covered_npcs_count"], 5)
        self.assertEqual(stats["target_npcs_count"], 6)

    # =========================================================================
    # 5. RESILIENCE & EDGE CASES (Scenarios 12 & 13 Stress)
    # =========================================================================

    def test_empty_and_corrupt_inventory_robustness(self):
        """
        Stress test: None, empty dicts, corrupted counts, float counts, negative counts.
        Optimizer must sanitize without throwing exceptions.
        """
        weird_inv = {
            "valid_pie": 2,
            "zero_item": 0,
            "negative_item": -5,
            "none_item": None,
            "": 10,
        }
        plan = plan_max_relationship(
            npc_gift_definitions={"adeline": {"name": "Adeline", "loved": ["valid_pie"], "liked": []}},
            inventory=weird_inv,
            infused_items=None,
        )
        self.assertEqual(plan["npc_progress"]["adeline"]["assigned_item_id"], "valid_pie")
        self.assertEqual(plan["overall_stats"]["total_relationship_points"], 20)

    def test_all_unlocked_and_locked_combinations(self):
        """
        Verifies behavior when save has locked NPCs vs unlocked NPCs.
        Locked NPCs must be excluded from target_npcs and recorded in locked_npcs.
        """
        with tempfile.TemporaryDirectory() as td:
            save_path = Path(td) / "test_locks.sav"
            create_synthetic_save_file(save_path, day=3, bag_items={"golden_cheesecake": 10})
            save = parse_save_file(save_path)

            plan = plan_max_relationship(
                save=save,
                npc_gift_definitions=self.mock_npcs,
                item_metadata=self.mock_meta,
            )
            self.assertNotIn("darcy", plan["target_npcs"])
            self.assertIn("Darcy", plan["overall_stats"]["not_present_npcs"])

    # =========================================================================
    # 6. SATURDAY MARKET MATRIX (Scenario 15 Stress)
    # =========================================================================

    def test_saturday_market_presence_calendar_matrix(self):
        """
        Tests the full 7-day calendar matrix for Saturday Market vendors:
        Days 1-5, 7: Vendor Darcy must be absent.
        Day 6 (Saturday): Vendor Darcy must be present and targeted.
        """
        with tempfile.TemporaryDirectory() as td:
            for day_num in range(1, 8):
                sp = Path(td) / f"day_{day_num}.sav"
                create_synthetic_save_file(sp, day=day_num, bag_items={"golden_cheesecake": 5})
                save = parse_save_file(sp)
                plan = plan_max_relationship(
                    save=save,
                    npc_gift_definitions=self.mock_npcs,
                    item_metadata=self.mock_meta,
                    mode="auto",
                )
                if day_num == 6:
                    self.assertIn("darcy", plan["target_npcs"], f"Darcy must be present on Saturday (Day {day_num})")
                    self.assertTrue(plan["overall_stats"]["planning_for_saturday"])
                else:
                    self.assertNotIn("darcy", plan["target_npcs"], f"Darcy must be absent on Day {day_num}")
                    self.assertFalse(plan["overall_stats"]["planning_for_saturday"])


# ============================================================================
# 5. TEST HARNESS COMPATIBILITY & SCENARIOS 1 TO 8 STRESS
# ============================================================================

def _legacy_create_mock_slot(item_id: Optional[str], count: int) -> Dict[str, Any]:
    """Exact pre-M4 implementation of create_mock_slot for differential testing."""
    if item_id is None or count <= 0:
        return {"count": 0, "item": None, "required_tags": []}
    return {
        "count": float(count),
        "item": {"item_id": str(item_id)},
        "required_tags": [],
    }


class TestMockSlotBackwardCompatibility(unittest.TestCase):
    """Stress tests create_mock_slot backward compatibility and parameter robustness."""

    def test_legacy_exact_match_valid_items(self):
        """Verify create_mock_slot matches legacy behavior for valid items across counts."""
        test_cases = [
            ("apple", 1),
            ("strawberry_shortcake", 5),
            ("stone", 999),
            ("wood", 10),
        ]
        for item_id, count in test_cases:
            with self.subTest(item_id=item_id, count=count):
                actual = create_mock_slot(item_id, count)
                expected = _legacy_create_mock_slot(item_id, count)
                self.assertEqual(actual, expected)
                self.assertNotIn("infusion", actual["item"])
                self.assertIsInstance(actual["count"], float)
                self.assertEqual(actual["required_tags"], [])

    def test_legacy_exact_match_none_and_zero_counts(self):
        """Verify create_mock_slot handles None and non-positive counts identically to legacy."""
        edge_inputs = [
            (None, 0),
            (None, 5),
            (None, -1),
            ("apple", 0),
            ("apple", -1),
            ("apple", -999),
        ]
        for item_id, count in edge_inputs:
            with self.subTest(item_id=item_id, count=count):
                actual = create_mock_slot(item_id, count)
                expected = _legacy_create_mock_slot(item_id, count)
                self.assertEqual(actual, expected)
                self.assertEqual(actual, {"count": 0, "item": None, "required_tags": []})

    def test_infusion_parameter_behavior(self):
        """Verify infusion parameter behavior: None omits key, valid strings set key."""
        # infusion=None must omit infusion key
        slot_none = create_mock_slot("apple_pie", 2, infusion=None)
        self.assertNotIn("infusion", slot_none["item"])
        self.assertEqual(slot_none["item"], {"item_id": "apple_pie"})

        # infusion="lovable" sets key
        slot_lovable = create_mock_slot("apple_pie", 2, infusion="lovable")
        self.assertEqual(slot_lovable["item"]["infusion"], "lovable")
        self.assertEqual(slot_lovable["item"]["item_id"], "apple_pie")
        self.assertEqual(slot_lovable["count"], 2.0)

        # infusion="likable" sets key
        slot_likable = create_mock_slot("vegetable_soup", 3, infusion="likable")
        self.assertEqual(slot_likable["item"]["infusion"], "likable")
        self.assertEqual(slot_likable["item"]["item_id"], "vegetable_soup")
        self.assertEqual(slot_likable["count"], 3.0)

    def test_empty_slot_overrides_infusion(self):
        """If item_id is None or count <= 0, infusion parameter must not create an item dict."""
        slot_empty_none = create_mock_slot(None, 5, infusion="lovable")
        self.assertEqual(slot_empty_none, {"count": 0, "item": None, "required_tags": []})

        slot_empty_zero = create_mock_slot("apple_pie", 0, infusion="lovable")
        self.assertEqual(slot_empty_zero, {"count": 0, "item": None, "required_tags": []})

        slot_empty_neg = create_mock_slot("apple_pie", -2, infusion="likable")
        self.assertEqual(slot_empty_neg, {"count": 0, "item": None, "required_tags": []})


class TestSyntheticSaveBackwardCompatibility(unittest.TestCase):
    """Stress tests create_synthetic_save_entries and create_synthetic_save_file backward compatibility."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_entries_legacy_signature_bag_items(self):
        """Verify entries generated with only bag_items have exactly 30 slots and expected items."""
        bag_items = {"strawberry": 5, "deluxe_sandwich": 2}
        entries = create_synthetic_save_entries(bag_items=bag_items)

        self.assertIn("player", entries)
        player_data = json.loads(entries["player"])
        inv = player_data["inventory"]
        self.assertEqual(len(inv), 30)

        # First 2 slots match bag_items
        self.assertEqual(inv[0]["item"]["item_id"], "strawberry")
        self.assertEqual(inv[0]["count"], 5.0)
        self.assertEqual(inv[1]["item"]["item_id"], "deluxe_sandwich")
        self.assertEqual(inv[1]["count"], 2.0)

        # Remaining 28 slots are empty
        for i in range(2, 30):
            self.assertIsNone(inv[i]["item"])
            self.assertEqual(inv[i]["count"], 0)

    def test_entries_bag_slots_padding_and_preservation(self):
        """Verify bag_slots parameter correctly preserves custom slots and pads to 30."""
        custom_slots = [
            create_mock_slot("apple_pie", 1, infusion="lovable"),
            create_mock_slot("vegetable_soup", 2, infusion="likable"),
        ]
        entries = create_synthetic_save_entries(bag_slots=custom_slots)
        player_data = json.loads(entries["player"])
        inv = player_data["inventory"]

        self.assertEqual(len(inv), 30)
        self.assertEqual(inv[0]["item"]["item_id"], "apple_pie")
        self.assertEqual(inv[0]["item"]["infusion"], "lovable")
        self.assertEqual(inv[1]["item"]["item_id"], "vegetable_soup")
        self.assertEqual(inv[1]["item"]["infusion"], "likable")

        # Empty slots fill remainder
        for i in range(2, 30):
            self.assertIsNone(inv[i]["item"])

    def test_entries_bag_slots_exceeding_30(self):
        """Verify bag_slots with > 30 items preserves all items without crash or truncation."""
        large_slots = [create_mock_slot(f"item_{i}", 1) for i in range(40)]
        entries = create_synthetic_save_entries(bag_slots=large_slots)
        player_data = json.loads(entries["player"])
        self.assertEqual(len(player_data["inventory"]), 40)

    def test_synthetic_save_file_roundtrip_parsing(self):
        """Verify binary .sav file created by create_synthetic_save_file parses cleanly."""
        save_path = self.work_dir / "roundtrip.sav"
        custom_slots = [
            create_mock_slot("apple_pie", 2, infusion="lovable"),
            create_mock_slot("strawberry", 10),
        ]
        chests = {
            "farm": [
                [
                    create_mock_slot("vegetable_soup", 4, infusion="likable"),
                    create_mock_slot("stone", 99),
                ]
            ]
        }
        create_synthetic_save_file(
            save_path,
            bag_slots=custom_slots,
            chests_by_location=chests,
            year=1,
            season="spring",
            day=1,
        )

        save = parse_save_file(save_path)
        self.assertIsInstance(save, SaveData)

        # Verify bag extraction
        bag_items = save.get_bag_items()
        self.assertEqual(bag_items["apple_pie"], 2)
        self.assertEqual(bag_items["strawberry"], 10)

        # Verify chest extraction
        chest_items = save.get_chest_items()
        self.assertEqual(chest_items["vegetable_soup"], 4)
        self.assertEqual(chest_items["stone"], 99)

        all_chests = save.get_chests_by_location()
        self.assertIn("farm", all_chests)
        self.assertEqual(len(all_chests["farm"]), 1)
        self.assertEqual(len(all_chests["farm"][0]), 2)

        # Verify infusion extraction
        infused = save.get_infused_items()
        self.assertEqual(len(infused["lovable"]), 1)
        self.assertEqual(infused["lovable"][0]["item_id"], "apple_pie")
        self.assertEqual(infused["lovable"][0]["count"], 2)
        self.assertEqual(infused["lovable"][0]["location"], "bag")

        self.assertEqual(len(infused["likable"]), 1)
        self.assertEqual(infused["likable"][0]["item_id"], "vegetable_soup")
        self.assertEqual(infused["likable"][0]["count"], 4)
        self.assertEqual(infused["likable"][0]["location"], "farm")


class TestAdversarialScenarios1To3(unittest.TestCase):
    """Adversarial stress testing of Scenarios 1 to 3: Infused item detection & edge cases."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_scenario_1_adversarial_bag_detection(self):
        """Scenario 1 Stress: Multiple stacks, unknown infusions, negative/zero counts in bag."""
        save_path = self.work_dir / "scen1_stress.sav"
        custom_slots = [
            create_mock_slot("apple_pie", 2, infusion="lovable"),
            create_mock_slot("apple_pie", 3, infusion="lovable"),  # Duplicate lovable
            create_mock_slot("soup", 1, infusion="likable"),
            create_mock_slot("soup", 4, infusion="likable"),  # Duplicate likable
            create_mock_slot("berry_tart", 5, infusion="other_unknown_perk"),  # Unknown infusion
            {"count": 0, "item": {"item_id": "ghost_dish", "infusion": "lovable"}, "required_tags": []},  # 0 count
            {"count": -5, "item": {"item_id": "neg_dish", "infusion": "lovable"}, "required_tags": []},  # Negative count
            create_mock_slot("wood", 100),  # Non-infused
        ]
        create_synthetic_save_file(save_path, bag_slots=custom_slots)
        save = parse_save_file(save_path)
        infused = save.get_infused_items()

        # Lovable must aggregate apple_pie (2 + 3 = 5), exclude ghost_dish and neg_dish
        self.assertEqual(len(infused["lovable"]), 1)
        self.assertEqual(infused["lovable"][0]["item_id"], "apple_pie")
        self.assertEqual(infused["lovable"][0]["count"], 5)
        self.assertEqual(infused["lovable"][0]["location"], "bag")

        # Likable must aggregate soup (1 + 4 = 5), exclude berry_tart
        self.assertEqual(len(infused["likable"]), 1)
        self.assertEqual(infused["likable"][0]["item_id"], "soup")
        self.assertEqual(infused["likable"][0]["count"], 5)
        self.assertEqual(infused["likable"][0]["location"], "bag")

    def test_scenario_2_adversarial_chests_across_locations(self):
        """Scenario 2 Stress: Sorting order, multiple chests per location, non-location keys."""
        save_path = self.work_dir / "scen2_stress.sav"
        chests = {
            "mines": [
                [create_mock_slot("zebra_pie", 2, infusion="lovable")],
                [create_mock_slot("apple_pie", 1, infusion="lovable")],
            ],
            "farm": [
                [create_mock_slot("apple_pie", 4, infusion="lovable")],
                [create_mock_slot("apple_pie", 6, infusion="lovable")],  # Duplicate in farm (4+6=10)
            ],
            "beach": [
                [create_mock_slot("fish_stew", 3, infusion="likable")],
            ],
        }
        create_synthetic_save_file(save_path, chests_by_location=chests)
        save = parse_save_file(save_path)
        infused = save.get_infused_items()

        # Deterministic sort order by (item_id, location):
        # 1. ("apple_pie", "farm", 10)
        # 2. ("apple_pie", "mines", 1)
        # 3. ("zebra_pie", "mines", 2)
        lovable = infused["lovable"]
        self.assertEqual(len(lovable), 3)
        self.assertEqual(lovable[0], {"item_id": "apple_pie", "count": 10, "location": "farm"})
        self.assertEqual(lovable[1], {"item_id": "apple_pie", "count": 1, "location": "mines"})
        self.assertEqual(lovable[2], {"item_id": "zebra_pie", "count": 2, "location": "mines"})

        # Likable: ("fish_stew", "beach", 3)
        likable = infused["likable"]
        self.assertEqual(len(likable), 1)
        self.assertEqual(likable[0], {"item_id": "fish_stew", "count": 3, "location": "beach"})

    def test_scenario_3_adversarial_empty_infusions(self):
        """Scenario 3 Stress: Completely empty save, zero infusions, and optimizer call."""
        save_path = self.work_dir / "scen3_empty.sav"
        create_synthetic_save_file(save_path, bag_items={}, chests_by_location={})
        save = parse_save_file(save_path)

        infused = save.get_infused_items()
        self.assertEqual(infused, {"lovable": [], "likable": []})

        # Optimizer with empty infusions and empty inventory
        plan = plan_max_relationship(
            save=save,
            npc_gift_definitions=get_mock_npcs(),
            item_metadata=get_mock_meta(),
        )
        self.assertEqual(plan["overall_stats"]["total_relationship_points"], 0)
        self.assertEqual(plan["overall_stats"]["infused_items_detected"], 0)
        self.assertEqual(plan["bag_plan"], [])


class TestAdversarialScenarios4To8(unittest.TestCase):
    """Adversarial stress testing of Scenarios 4 to 8: Gift allocation hierarchy."""

    def setUp(self):
        self.meta = get_mock_meta()

    def test_scenario_4_love_priority_over_abundant_likes(self):
        """Scenario 4: Loved gift (+20) strictly selected over 100x more abundant like gifts (+10)."""
        npcs = {
            "adeline": {
                "name": "Adeline",
                "loved": ["golden_cheesecake"],
                "liked": ["strawberry", "bread", "apple"],
            }
        }
        inv = {
            "golden_cheesecake": 1,
            "strawberry": 100,
            "bread": 100,
            "apple": 100,
        }
        plan = plan_max_relationship(
            npc_gift_definitions=npcs,
            item_metadata=self.meta,
            inventory=inv,
            force_all_npcs=True,
        )
        prog = plan["npc_progress"]["adeline"]
        self.assertEqual(prog["assigned_item_id"], "golden_cheesecake")
        self.assertEqual(prog["assigned_pref_type"], "LOVE")
        self.assertEqual(prog["assigned_points"], 20)
        self.assertEqual(plan["overall_stats"]["total_relationship_points"], 20)
        self.assertEqual(plan["overall_stats"]["today_loved_completed"], 1)
        self.assertEqual(plan["overall_stats"]["today_liked_completed"], 0)

    def test_scenario_5_abundance_and_tie_breaking(self):
        """Scenario 5: Most abundant candidate chosen, zero-count candidates ignored."""
        npcs = {
            "march": {
                "name": "March",
                "loved": ["item_low", "item_high", "item_zero"],
                "liked": [],
            }
        }
        inv = {
            "item_low": 2,
            "item_high": 15,
            "item_zero": 0,
        }
        plan = plan_max_relationship(
            npc_gift_definitions=npcs,
            item_metadata=self.meta,
            inventory=inv,
            force_all_npcs=True,
        )
        prog = plan["npc_progress"]["march"]
        self.assertEqual(prog["assigned_item_id"], "item_high")
        self.assertEqual(prog["assigned_points"], 20)

    def test_scenario_6_universal_love_over_specific_likes(self):
        """Scenario 6: Universal love (+20) strictly selected over specific likes (+10)."""
        npcs = {
            "celine": {
                "name": "Celine",
                "loved": ["absent_flower"],
                "liked": ["strawberry", "daffodil"],
            }
        }
        inv = {"strawberry": 50, "daffodil": 50}
        infused = {
            "lovable": [{"item_id": "infused_pie", "count": 1, "location": "bag"}],
            "likable": [],
        }
        plan = plan_max_relationship(
            npc_gift_definitions=npcs,
            item_metadata=self.meta,
            inventory=inv,
            infused_items=infused,
            force_all_npcs=True,
        )
        prog = plan["npc_progress"]["celine"]
        self.assertEqual(prog["assigned_item_id"], "infused_pie")
        self.assertEqual(prog["assigned_pref_type"], "UNIV_LOVE")
        self.assertEqual(prog["assigned_points"], 20)
        self.assertEqual(plan["overall_stats"]["total_relationship_points"], 20)
        self.assertEqual(plan["overall_stats"]["today_loved_completed"], 1)
        self.assertEqual(plan["overall_stats"]["today_liked_completed"], 0)

    def test_scenario_7_specific_like_preserves_universal_like(self):
        """Scenario 7: Specific like (+10) chosen over universal like (+10) to preserve universal pool."""
        npcs = {
            "adeline": {
                "name": "Adeline",
                "loved": ["absent_cake"],
                "liked": ["strawberry"],
            }
        }
        inv = {"strawberry": 1}
        infused = {
            "lovable": [],
            "likable": [{"item_id": "infused_soup", "count": 1, "location": "bag"}],
        }
        plan = plan_max_relationship(
            npc_gift_definitions=npcs,
            item_metadata=self.meta,
            inventory=inv,
            infused_items=infused,
            force_all_npcs=True,
        )
        prog = plan["npc_progress"]["adeline"]
        # Must pick strawberry (specific like), preserving infused_soup
        self.assertEqual(prog["assigned_item_id"], "strawberry")
        self.assertEqual(prog["assigned_pref_type"], "LIKE")
        self.assertEqual(prog["assigned_points"], 10)

    def test_scenario_8_universal_like_and_neutral_exclusion(self):
        """Scenario 8: Universal like chosen as last resort, neutrals (+3) strictly excluded, exhaustion skips."""
        npcs = {
            "npc1": {"name": "NPC1", "loved": ["absent_a"], "liked": ["absent_b"]},
            "npc2": {"name": "NPC2", "loved": ["absent_c"], "liked": ["absent_d"]},
        }
        # Only 1 universal like dish available, but 1000 neutral items exist
        inv = {"stone": 500, "wood": 500}
        infused = {
            "lovable": [],
            "likable": [{"item_id": "infused_soup", "count": 1, "location": "bag"}],
        }
        plan = plan_max_relationship(
            npc_gift_definitions=npcs,
            item_metadata=self.meta,
            inventory=inv,
            infused_items=infused,
            force_all_npcs=True,
        )
        stats = plan["overall_stats"]
        self.assertEqual(stats["total_relationship_points"], 10)
        self.assertEqual(stats["covered_npcs_count"], 1)
        self.assertEqual(stats["target_npcs_count"], 2)

        # 1 NPC got infused_soup (+10), 1 NPC skipped (0 pts, None)
        assignments = [p["assigned_item_id"] for p in plan["npc_progress"].values()]
        self.assertIn("infused_soup", assignments)
        self.assertIn(None, assignments)

        # Neutral items stone/wood NEVER packed into bag_plan
        packed_ids = [b["item_id"] for b in plan["bag_plan"]]
        self.assertNotIn("stone", packed_ids)
        self.assertNotIn("wood", packed_ids)


class TestAdversarialHarnessStress(unittest.TestCase):
    """Deep adversarial fuzzing and combinatorial testing of test fixtures and optimizer constraints."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_differential_fuzzing_create_mock_slot(self):
        """Differential fuzz test: create_mock_slot must be 100% equivalent to legacy for all pre-M4 call patterns."""
        sample_ids = [None, "", "apple", "apple_pie", "item_123", "stone", "very_long_item_id_string_name"]
        sample_counts = [-100, -1, 0, 1, 2, 5, 10, 999]

        for item_id in sample_ids:
            for count in sample_counts:
                with self.subTest(item_id=item_id, count=count):
                    # Test positional call
                    res_pos = create_mock_slot(item_id, count)
                    exp = _legacy_create_mock_slot(item_id, count)
                    self.assertEqual(res_pos, exp)

                    # Test keyword call
                    res_kw = create_mock_slot(item_id=item_id, count=count)
                    self.assertEqual(res_kw, exp)

                    # Test with explicit infusion=None
                    res_none = create_mock_slot(item_id, count, infusion=None)
                    self.assertEqual(res_none, exp)

    def test_synthetic_save_parameter_matrix(self):
        """Verify create_synthetic_save_file correctly writes binary files across parameter matrices."""
        custom_slots = [
            create_mock_slot("apple_pie", 1, infusion="lovable"),
            create_mock_slot("vegetable_soup", 2, infusion="likable"),
        ]
        # Test matrix: giftable_all variations, gifted_npcs, custom npc_ids
        for giftable in [True, False]:
            for day_val in [3, 6]:
                save_file = self.work_dir / f"test_save_{giftable}_{day_val}.sav"
                create_synthetic_save_file(
                    save_file,
                    bag_slots=custom_slots,
                    day=day_val,
                    giftable_all=giftable,
                    gifted_npcs={"adeline": ["apple"]} if not giftable else None,
                    npc_ids=["adeline", "darcy", "balor"],
                )
                save = parse_save_file(save_file)
                self.assertEqual(save.in_game_date.day, day_val)
                self.assertEqual(save.in_game_date.is_saturday, (day_val == 6))
                infused = save.get_infused_items()
                self.assertEqual(len(infused["lovable"]), 1)
                self.assertEqual(len(infused["likable"]), 1)

    def test_max_slots_pruning_in_max_relationship(self):
        """Verify max_slots constraint correctly truncates and reverts lowest-value packed items."""
        npcs = {
            "npc_high": {"name": "HighPoints", "loved": ["love_dish"], "liked": []},
            "npc_low": {"name": "LowPoints", "loved": [], "liked": ["like_dish"]},
        }
        inv = {"love_dish": 1, "like_dish": 1}

        # max_slots = 1 -> only 1 item can be packed
        plan = plan_max_relationship(
            npc_gift_definitions=npcs,
            inventory=inv,
            max_slots=1,
            force_all_npcs=True,
        )

        self.assertEqual(len(plan["bag_plan"]), 1)
        self.assertEqual(plan["bag_plan"][0]["item_id"], "love_dish")
        self.assertEqual(plan["overall_stats"]["slots_used"], 1)
        self.assertEqual(plan["overall_stats"]["total_relationship_points"], 20)
        self.assertIn("npc_high", plan["covered_npcs"])
        self.assertNotIn("npc_low", plan["covered_npcs"])
        self.assertIsNone(plan["npc_progress"]["npc_low"]["assigned_item_id"])



if __name__ == "__main__":
    unittest.main()
