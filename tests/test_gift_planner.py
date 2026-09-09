#!/usr/bin/env python3
"""
test_gift_planner.py

Comprehensive Integration & Regression Test Suite for gift_planner.py.
Covers:
  - SaveData parsing, in-game calendar, and bag/chest inventory aggregation
  - Saturday Market awareness and planning modes (auto, saturday, market-only, townsfolk, all)
  - Inventory awareness & tiered availability scoring (HAVE=2 > CRAFT=1 > UNAVAILABLE=0)
  - Dynamic material pool deduction across multi-slot gift bags
  - Output formats (Terminal badges/chains, CSV export, Excel multi-sheet export)
  - CLI argument parsing & subprocess execution (--save-file, --date, --format, --output-dir)
"""

import csv
import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from save_parser import (
        SaveData,
        InGameDate,
        parse_save_file,
        find_save_files,
        find_latest_save,
        SATURDAY_MARKET_VENDORS,
        ANIMAL_FESTIVAL_ATTENDING_VENDORS,
    )
    from export_gift_rankings import (
        load_npc_preferences_from_fiddle,
        load_npc_preferences_from_json,
        load_item_metadata,
        OPENPYXL_AVAILABLE,
    )
    from crafting_calculator import (
        AvailabilityTier,
        CraftingPlan,
        CraftingStep,
        load_recipes,
        evaluate_craftability,
        deduct_crafting_materials,
        format_crafting_chain,
    )
    from gift_planner import (
        plan_daily_gift_bag,
        plan_max_relationship,
        print_terminal_plan,
        export_plan_to_csv,
        export_plan_to_excel,
        compute_focus_suggestions,
        resolve_root_raw_materials,
        load_item_locations,
        ITEM_LOCATIONS,
    )
except ImportError:
    from scripts.save_parser import (
        SaveData,
        InGameDate,
        parse_save_file,
        find_save_files,
        find_latest_save,
        SATURDAY_MARKET_VENDORS,
        ANIMAL_FESTIVAL_ATTENDING_VENDORS,
    )
    from scripts.export_gift_rankings import (
        load_npc_preferences_from_fiddle,
        load_npc_preferences_from_json,
        load_item_metadata,
        OPENPYXL_AVAILABLE,
    )
    from scripts.crafting_calculator import (
        AvailabilityTier,
        CraftingPlan,
        CraftingStep,
        load_recipes,
        evaluate_craftability,
        deduct_crafting_materials,
        format_crafting_chain,
    )
    from scripts.gift_planner import (
        plan_daily_gift_bag,
        plan_max_relationship,
        print_terminal_plan,
        export_plan_to_csv,
        export_plan_to_excel,
        compute_focus_suggestions,
        resolve_root_raw_materials,
        load_item_locations,
        ITEM_LOCATIONS,
    )

if OPENPYXL_AVAILABLE:
    import openpyxl


# ==============================================================================
# SYNTHETIC TEST FIXTURE GENERATORS
# ==============================================================================

def create_mock_slot(
    item_id: Optional[str],
    count: int,
    infusion: Optional[str] = None,
) -> Dict[str, Any]:
    """Creates a standard FoM inventory slot dictionary with optional cooking perk infusion."""
    if item_id is None or count <= 0:
        return {"count": 0, "item": None, "required_tags": []}
    item_dict: Dict[str, Any] = {"item_id": str(item_id)}
    if infusion is not None:
        item_dict["infusion"] = str(infusion)
    return {
        "count": float(count),
        "item": item_dict,
        "required_tags": []
    }


def create_synthetic_save_entries(
    bag_items: Optional[Dict[str, int]] = None,
    chests_by_location: Optional[Dict[str, List[List[Dict[str, Any]]]]] = None,
    year: int = 2,
    season: str = "winter",
    day: int = 6,  # Day 6 is Saturday
    player_name: str = "TestHero",
    farm_name: str = "TestFarm",
    giftable_all: bool = True,
    gifted_npcs: Optional[Dict[str, List[str]]] = None,
    npc_ids: Optional[List[str]] = None,
    bag_slots: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, str]:
    """Generates a complete dictionary of raw_entries for a FoM save file."""
    season_idx = {"spring": 0, "summer": 1, "autumn": 2, "winter": 3}.get(season.lower(), 0)
    cal_days = (year - 1) * 112 + season_idx * 28 + (day - 1)
    cal_time = cal_days * 86400

    entries: Dict[str, str] = {}

    header_data = {
        "name": player_name,
        "farm_name": farm_name,
        "playtime": 7200.0,
        "calendar_time": cal_time,
        "clock_time": 21600,
    }
    entries["header"] = json.dumps(header_data)

    if bag_slots is not None:
        bag_slots_to_use = [dict(s) for s in bag_slots]
        while len(bag_slots_to_use) < 30:
            bag_slots_to_use.append(create_mock_slot(None, 0))
    else:
        bag_slots_to_use = []
        if bag_items:
            for iid, cnt in bag_items.items():
                bag_slots_to_use.append(create_mock_slot(iid, cnt))
        while len(bag_slots_to_use) < 30:
            bag_slots_to_use.append(create_mock_slot(None, 0))

    player_data = {
        "name": player_name,
        "farm_name": farm_name,
        "inventory": bag_slots_to_use,
    }
    entries["player"] = json.dumps(player_data)

    npcs_data: Dict[str, Any] = {}
    all_34_npc_ids = [
        "adeline", "balor", "celine", "darcy", "dell", "dozy", "eiland", "elsie", "errol",
        "hayden", "hemlock", "henrietta", "holt", "josephine", "juniper", "landen", "louis",
        "luc", "maple", "march", "merri", "nora", "olric", "reina", "ryis", "seridia",
        "stillwell", "taliferro", "terithia", "valen", "vera", "wheedle", "zorel", "caldarus"
    ]
    target_npc_list = npc_ids if npc_ids is not None else all_34_npc_ids
    if gifted_npcs is None:
        gifted_npcs = {}

    is_animal_fest = (season.lower() == "winter" and day == 10)
    for nid in target_npc_list:
        is_vendor = nid in SATURDAY_MARKET_VENDORS
        is_fest_vendor = is_animal_fest and (nid in ("merri", "louis"))
        loc_id = "town" if (day % 7 == 6 or not is_vendor or is_fest_vendor) else "aldaria"
        npcs_data[nid] = {
            "name": nid.capitalize(),
            "heart_points": 100.0,
            "gift_flag": giftable_all,
            "gifts_given": gifted_npcs.get(nid, []),
            "known_gift_preferences": [],
            "location_position": {"location_id": loc_id},
        }
    entries["npcs"] = json.dumps(npcs_data)

    if chests_by_location:
        for loc_name, chest_list in chests_by_location.items():
            entries[loc_name] = json.dumps({
                "location_id": loc_name,
                "inventories": chest_list
            })

    entries["gamedata"] = json.dumps({"date": cal_time})
    entries["game_stats"] = json.dumps({})
    entries["quests"] = json.dumps({})
    entries["info"] = json.dumps({})

    return entries


def create_synthetic_save_file(
    file_path: Path,
    bag_items: Optional[Dict[str, int]] = None,
    chests_by_location: Optional[Dict[str, List[List[Dict[str, Any]]]]] = None,
    year: int = 2,
    season: str = "winter",
    day: int = 6,
    player_name: str = "TestHero",
    farm_name: str = "TestFarm",
    giftable_all: bool = True,
    gifted_npcs: Optional[Dict[str, List[str]]] = None,
    npc_ids: Optional[List[str]] = None,
    bag_slots: Optional[List[Dict[str, Any]]] = None,
) -> Path:
    """Encodes and writes a synthetic binary FoM .sav file to disk."""
    entries = create_synthetic_save_entries(
        bag_items=bag_items,
        chests_by_location=chests_by_location,
        year=year,
        season=season,
        day=day,
        player_name=player_name,
        farm_name=farm_name,
        giftable_all=giftable_all,
        gifted_npcs=gifted_npcs,
        npc_ids=npc_ids,
        bag_slots=bag_slots,
    )
    raw = bytearray()
    raw.extend(struct.pack("<Q", len(entries)))
    for k, v in entries.items():
        kb = k.encode("utf-8")
        vb = v.encode("utf-8")
        raw.extend(struct.pack("<Q", len(kb)))
        raw.extend(kb)
        raw.extend(struct.pack("<Q", len(vb)))
        raw.extend(vb)

    compressed = zlib.compress(bytes(raw))
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "wb") as f:
        f.write(compressed)
    return file_path


def get_mock_recipes() -> Dict[str, Any]:
    """Returns a comprehensive mock recipe dictionary for tests."""
    return {
        "golden_cheese": {
            "item_id": "golden_cheese", "display_name": "Golden Cheese", "source": "milling", "output_count": 1,
            "ingredients": [{"item_id": "golden_cow_milk", "display_name": "Golden Milk", "count": 2}]
        },
        "golden_butter": {
            "item_id": "golden_butter", "display_name": "Golden Butter", "source": "milling", "output_count": 1,
            "ingredients": [{"item_id": "golden_cow_milk", "display_name": "Golden Milk", "count": 2}]
        },
        "golden_cheesecake": {
            "item_id": "golden_cheesecake", "display_name": "Golden Cheesecake", "source": "cooking", "output_count": 1,
            "ingredients": [
                {"item_id": "golden_cow_milk", "display_name": "Golden Milk", "count": 2},
                {"item_id": "golden_cheese", "display_name": "Golden Cheese", "count": 1},
                {"item_id": "golden_butter", "display_name": "Golden Butter", "count": 1},
                {"item_id": "egg", "display_name": "Egg", "count": 1},
                {"item_id": "flour", "display_name": "Flour", "count": 1},
                {"item_id": "sugar", "display_name": "Sugar", "count": 1}
            ]
        },
        "cornmeal": {
            "item_id": "cornmeal", "display_name": "Cornmeal", "source": "milling", "output_count": 1,
            "ingredients": [{"item_id": "corn", "display_name": "Corn", "count": 1}]
        },
        "strawberry_shortcake": {
            "item_id": "strawberry_shortcake", "display_name": "Strawberry Shortcake", "source": "cooking", "output_count": 1,
            "ingredients": [
                {"item_id": "strawberry", "display_name": "Strawberry", "count": 3},
                {"item_id": "flour", "display_name": "Flour", "count": 1},
                {"item_id": "sugar", "display_name": "Sugar", "count": 1}
            ]
        },
        "bread": {
            "item_id": "bread", "display_name": "Bread", "source": "cooking", "output_count": 1,
            "ingredients": [{"item_id": "flour", "display_name": "Flour", "count": 2}]
        },
        "deluxe_sandwich": {
            "item_id": "deluxe_sandwich", "display_name": "Deluxe Sandwich", "source": "cooking", "output_count": 1,
            "ingredients": [
                {"item_id": "bread", "display_name": "Bread", "count": 1},
                {"item_id": "tomato", "display_name": "Tomato", "count": 1}
            ]
        }
    }


def get_mock_npcs() -> Dict[str, Any]:
    """Returns sample NPC gift preferences for testing."""
    return {
        "adeline": {
            "name": "Adeline",
            "loved": ["golden_cheesecake", "strawberry_shortcake"],
            "liked": ["strawberry", "cornmeal"]
        },
        "darcy": {  # Saturday Vendor
            "name": "Darcy",
            "loved": ["golden_cheesecake", "deluxe_sandwich"],
            "liked": ["cornmeal", "sugar"]
        },
        "louis": {  # Saturday Vendor
            "name": "Louis",
            "loved": ["strawberry_shortcake"],
            "liked": ["strawberry"]
        },
        "march": {
            "name": "March",
            "loved": ["deluxe_sandwich"],
            "liked": ["bread", "cornmeal"]
        },
        "celine": {
            "name": "Celine",
            "loved": ["strawberry_shortcake"],
            "liked": ["strawberry"]
        }
    }


def get_mock_meta() -> Dict[str, Any]:
    """Returns sample item metadata for testing."""
    return {
        "golden_cheesecake": {"display_name": "Golden Cheesecake", "bin_price": 500, "store_price": 1000},
        "strawberry_shortcake": {"display_name": "Strawberry Shortcake", "bin_price": 200, "store_price": 400},
        "deluxe_sandwich": {"display_name": "Deluxe Sandwich", "bin_price": 300, "store_price": 600},
        "cornmeal": {"display_name": "Cornmeal", "bin_price": 50, "store_price": 100},
        "bread": {"display_name": "Bread", "bin_price": 70, "store_price": 140},
        "strawberry": {"display_name": "Strawberry", "bin_price": 40, "store_price": 80},
    }


# ==============================================================================
# TEST SUITE
# ==============================================================================

class TestGiftPlannerIntegration(unittest.TestCase):
    """Main integration test suite for gift_planner.py with inventory & crafting support."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.temp_dir.name)
        self.mock_recipes = get_mock_recipes()
        self.mock_npcs = get_mock_npcs()
        self.mock_meta = get_mock_meta()

    def tearDown(self):
        self.temp_dir.cleanup()

    # --------------------------------------------------------------------------
    # 1. Save Parser & Calendar Tests
    # --------------------------------------------------------------------------

    def test_save_parser_calendar_and_npcs(self):
        """Verify save parser reads date, Saturday market status, and NPC counts."""
        save_path = self.work_dir / "test_wednesday.sav"
        create_synthetic_save_file(save_path, day=3)  # Wednesday
        save = parse_save_file(save_path)

        self.assertEqual(save.player_name, "TestHero")
        self.assertEqual(save.farm_name, "TestFarm")
        self.assertEqual(save.in_game_date.day, 3)
        self.assertEqual(save.in_game_date.day_of_week, "Wednesday")
        self.assertFalse(save.in_game_date.is_saturday)
        self.assertEqual(save.in_game_date.days_until_saturday, 3)
        self.assertEqual(save.in_game_date.next_saturday_day, 6)

        # On Wednesday, 26 townsfolk are present in town, 8 vendors in Aldaria
        self.assertEqual(len(save.get_present_npcs_today()), 26)

    def test_save_parser_chest_and_bag_aggregation(self):
        """Verify get_all_available_items combines player bag and chest storages."""
        bag = {"strawberry": 5, "egg": 2}
        chests = {
            "farm": [[create_mock_slot("golden_cow_milk", 6), create_mock_slot("flour", 3)]],
            "player_home": [[create_mock_slot("sugar", 4)]],
        }
        save_path = self.work_dir / "test_inventory.sav"
        create_synthetic_save_file(save_path, bag_items=bag, chests_by_location=chests)
        save = parse_save_file(save_path)

        avail = save.get_all_available_items()
        self.assertEqual(avail.get("strawberry"), 5)
        self.assertEqual(avail.get("egg"), 2)
        self.assertEqual(avail.get("golden_cow_milk"), 6)
        self.assertEqual(avail.get("flour"), 3)
        self.assertEqual(avail.get("sugar"), 4)

    # --------------------------------------------------------------------------
    # 2. Planning Modes & Saturday Market Awareness
    # --------------------------------------------------------------------------

    def test_gift_planner_auto_mode_weekday(self):
        """Verify auto mode on Wednesday restricts to townsfolk."""
        save_path = self.work_dir / "wednesday.sav"
        create_synthetic_save_file(save_path, day=3)
        save = parse_save_file(save_path)

        plan = plan_daily_gift_bag(
            save=save,
            npc_gift_definitions=self.mock_npcs,
            item_metadata=self.mock_meta,
            mode="auto",
            max_slots=10,
            recipes=self.mock_recipes,
        )

        stats = plan["overall_stats"]
        bag_plan = plan["bag_plan"]
        # Only Adeline, March, Celine are townsfolk in mock_npcs (Darcy and Louis are vendors)
        self.assertEqual(stats["target_npcs_count"], 3)
        self.assertEqual(stats["vendors_covered_today"], 0)
        for b in bag_plan:
            self.assertEqual(len(b["market_vendors_covered"]), 0)

    def test_gift_planner_saturday_mode(self):
        """Verify Saturday mode covers all NPCs and boosts visiting vendors."""
        save_path = self.work_dir / "saturday.sav"
        create_synthetic_save_file(save_path, day=6)
        save = parse_save_file(save_path)

        plan = plan_daily_gift_bag(
            save=save,
            npc_gift_definitions=self.mock_npcs,
            item_metadata=self.mock_meta,
            mode="saturday",
            max_slots=10,
            recipes=self.mock_recipes,
        )

        stats = plan["overall_stats"]
        self.assertEqual(stats["target_npcs_count"], 5)
        self.assertEqual(stats["vendors_covered_today"], 2)

    def test_gift_planner_market_only_mode(self):
        """Verify market-only mode targets only visiting vendors."""
        save_path = self.work_dir / "market_only.sav"
        create_synthetic_save_file(save_path, day=6)
        save = parse_save_file(save_path)

        plan = plan_daily_gift_bag(
            save=save,
            npc_gift_definitions=self.mock_npcs,
            item_metadata=self.mock_meta,
            mode="market-only",
            max_slots=10,
            recipes=self.mock_recipes,
        )

        stats = plan["overall_stats"]
        self.assertEqual(stats["target_npcs_count"], 2)
        for b in plan["bag_plan"]:
            for r in b["all_recipients_today"]:
                self.assertTrue(r["is_vendor"])

    # --------------------------------------------------------------------------
    # 3. Inventory Awareness & Tiered Scoring (HAVE > CRAFT > UNAVAILABLE)
    # --------------------------------------------------------------------------

    def test_tiered_availability_prioritization(self):
        """
        Verify HAVE items (tier 2) rank higher than CRAFT (tier 1) and UNAVAILABLE (tier 0).
        Scenario:
          - Player has 1 'strawberry' in bag (HAVE)
          - Player has 1 'corn' to craft 'cornmeal' (CRAFT)
          - Player has 0 materials for 'golden_cheesecake' (UNAVAILABLE)
        """
        bag = {"strawberry": 1, "corn": 1}
        save_path = self.work_dir / "tier_test.sav"
        create_synthetic_save_file(save_path, bag_items=bag, day=6)
        save = parse_save_file(save_path)

        plan = plan_daily_gift_bag(
            save=save,
            npc_gift_definitions=self.mock_npcs,
            item_metadata=self.mock_meta,
            mode="all",
            max_slots=5,
            recipes=self.mock_recipes,
        )

        bag_plan = plan["bag_plan"]
        self.assertGreater(len(bag_plan), 0)

        # First item should have status HAVE
        self.assertEqual(bag_plan[0]["status"], "HAVE")
        self.assertEqual(bag_plan[0]["availability_tier"], 2)

    def test_craft_beats_unavailable_despite_lower_raw_score(self):
        """Verify craftable items rank above unavailable items even if coverage score is lower."""
        # Player has 1 corn -> can craft 1 cornmeal (liked by Darcy & March)
        # Deluxe sandwich is loved by Darcy & March, but has 0 materials (UNAVAILABLE)
        bag = {"corn": 1}
        save_path = self.work_dir / "craft_vs_unavail.sav"
        create_synthetic_save_file(save_path, bag_items=bag, day=6)
        save = parse_save_file(save_path)

        plan = plan_daily_gift_bag(
            save=save,
            npc_gift_definitions=self.mock_npcs,
            item_metadata=self.mock_meta,
            mode="all",
            max_slots=5,
            recipes=self.mock_recipes,
        )

        bag_plan = plan["bag_plan"]
        # Cornmeal is CRAFT (tier 1), so it must appear before any UNAVAILABLE (tier 0) items
        craft_indices = [i for i, b in enumerate(bag_plan) if b["status"] == "CRAFT"]
        unavail_indices = [i for i, b in enumerate(bag_plan) if b["status"] == "UNAVAILABLE"]

        if craft_indices and unavail_indices:
            self.assertLess(min(craft_indices), min(unavail_indices))

    # --------------------------------------------------------------------------
    # 4. Dynamic Material Pool Deduction
    # --------------------------------------------------------------------------

    def test_dynamic_deduction_in_multi_slot_bag(self):
        """
        Verify that selecting an item into slot 1 deducts its materials so subsequent
        slots evaluate availability against remaining inventory.
        """
        # Exactly 1 corn available -> after slot 1 picks cornmeal, 0 corn left
        bag = {"corn": 1}
        save_path = self.work_dir / "deduction_test.sav"
        create_synthetic_save_file(save_path, bag_items=bag, day=6)
        save = parse_save_file(save_path)

        plan = plan_daily_gift_bag(
            save=save,
            npc_gift_definitions=self.mock_npcs,
            item_metadata=self.mock_meta,
            mode="all",
            max_slots=5,
            recipes=self.mock_recipes,
        )

        bag_plan = plan["bag_plan"]
        # At most 1 slot can be cornmeal
        cornmeal_slots = [b for b in bag_plan if b["item_id"] == "cornmeal"]
        self.assertLessEqual(len(cornmeal_slots), 1)

    def test_shared_materials_between_recipes_deduction(self):
        """
        Verify two recipes sharing Flour (Strawberry Shortcake needs 1, Bread needs 2)
        compete for the same pool.
        """
        # 2 Flour available. Shortcake consumes 1 -> 1 left -> Bread needs 2, so Bread becomes UNAVAILABLE.
        bag = {"flour": 2, "strawberry": 5, "sugar": 2}
        save_path = self.work_dir / "shared_flour.sav"
        create_synthetic_save_file(save_path, bag_items=bag, day=6)
        save = parse_save_file(save_path)

        plan = plan_daily_gift_bag(
            save=save,
            npc_gift_definitions=self.mock_npcs,
            item_metadata=self.mock_meta,
            mode="all",
            max_slots=5,
            recipes=self.mock_recipes,
        )

        bag_plan = plan["bag_plan"]
        # If Strawberry shortcake is chosen as CRAFT in slot 1, bread cannot be CRAFT in slot 2
        shortcake_slots = [b for b in bag_plan if b["item_id"] == "strawberry_shortcake" and b["status"] == "CRAFT"]
        bread_slots = [b for b in bag_plan if b["item_id"] == "bread" and b["status"] == "CRAFT"]
        # Bread cannot be crafted after shortcake consumes 1 of 2 flour
        if shortcake_slots:
            self.assertEqual(len(bread_slots), 0)

    # --------------------------------------------------------------------------
    # 5. Output Formatting & Export Preservation
    # --------------------------------------------------------------------------

    def test_terminal_presentation_badges_and_chains(self):
        """Verify print_terminal_plan outputs badges, crafting chains, and inventory summary."""
        bag = {"strawberry": 2}
        chests = {
            "farm": [[
                create_mock_slot("golden_cow_milk", 6),
                create_mock_slot("egg", 1),
                create_mock_slot("flour", 1),
                create_mock_slot("sugar", 1),
            ]]
        }
        save_path = self.work_dir / "terminal_test.sav"
        create_synthetic_save_file(save_path, bag_items=bag, chests_by_location=chests, day=6)
        save = parse_save_file(save_path)

        plan_results = plan_daily_gift_bag(
            save=save,
            npc_gift_definitions=self.mock_npcs,
            item_metadata=self.mock_meta,
            mode="saturday",
            max_slots=5,
            recipes=self.mock_recipes,
        )

        # Capture terminal output
        stdout_buf = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = stdout_buf
            print_terminal_plan(save, plan_results)
        finally:
            sys.stdout = old_stdout

        output = stdout_buf.getvalue()
        self.assertIn("FIELDS OF MISTRIA", output)
        self.assertIn("INVENTORY & STORAGE STATUS", output)
        self.assertIn("OPTIMAL BAG LOADOUT", output)
        self.assertIn("Status", output)
        self.assertIn("Recipients", output)

        # Check for presence of badges in output
        self.assertTrue("📦 HAVE" in output or "✅ CRAFT" in output or "❌ NEED" in output)

    def test_csv_export_includes_availability_column(self):
        """Verify export_plan_to_csv writes valid CSV with Availability and Crafting Chain columns."""
        bag = {"strawberry": 5}
        save_path = self.work_dir / "csv_test.sav"
        create_synthetic_save_file(save_path, bag_items=bag, day=6)
        save = parse_save_file(save_path)

        plan_results = plan_daily_gift_bag(
            save=save,
            npc_gift_definitions=self.mock_npcs,
            item_metadata=self.mock_meta,
            mode="all",
            max_slots=5,
            recipes=self.mock_recipes,
        )

        csv_file = self.work_dir / "test_export.csv"
        export_plan_to_csv(plan_results, self.work_dir, "test_export.csv")
        self.assertTrue(csv_file.exists())
        self.assertGreater(csv_file.stat().st_size, 0)

        with open(csv_file, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header = next(reader)
            self.assertIn("Availability", header)
            self.assertIn("Item Name", header)
            self.assertIn("Crafting Chain", header)
            self.assertIn("Pack Qty", header)

    def test_excel_export_multi_sheet_preservation(self):
        """Verify export_plan_to_excel creates all 4 expected worksheets with proper styling."""
        if not OPENPYXL_AVAILABLE:
            self.skipTest("openpyxl not available")

        bag = {"strawberry": 5}
        save_path = self.work_dir / "excel_test.sav"
        create_synthetic_save_file(save_path, bag_items=bag, day=6)
        save = parse_save_file(save_path)

        plan_results = plan_daily_gift_bag(
            save=save,
            npc_gift_definitions=self.mock_npcs,
            item_metadata=self.mock_meta,
            mode="all",
            max_slots=5,
            recipes=self.mock_recipes,
        )

        xlsx_file = self.work_dir / "test_export.xlsx"
        export_plan_to_excel(save, plan_results, self.mock_npcs, self.mock_meta, xlsx_file)
        self.assertTrue(xlsx_file.exists())
        self.assertGreater(xlsx_file.stat().st_size, 0)

        wb = openpyxl.load_workbook(xlsx_file)
        sheet_names = wb.sheetnames
        self.assertIn("Daily Bag Plan", sheet_names)
        self.assertIn("NPC Gift Progress", sheet_names)
        self.assertIn("All Remaining Items", sheet_names)
        self.assertIn("Gift Completion Matrix", sheet_names)

    # --------------------------------------------------------------------------
    # 6. CLI Options & Subprocess Execution
    # --------------------------------------------------------------------------

    def test_cli_flags_subprocess_execution(self):
        """Verify CLI runs cleanly with --save-file, --date, --format, --output-dir."""
        save_path = self.work_dir / "cli_runner.sav"
        create_synthetic_save_file(save_path, bag_items={"strawberry": 10}, day=6)

        csv_name = "cli_bag_plan.csv"
        cmd = [
            sys.executable,
            str(REPO_ROOT / "gift_planner.py" if (REPO_ROOT / "gift_planner.py").exists() else REPO_ROOT / "scripts" / "gift_planner.py"),
            "--save-file", str(save_path),
            "--date", "saturday",
            "--mode", "saturday",
            "--slots", "8",
            "--format", "csv",
            "--output-dir", str(self.work_dir),
            "--csv-name", csv_name
        ]

        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=str(REPO_ROOT)
        )
        self.assertEqual(res.returncode, 0, f"CLI command failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
        self.assertTrue((self.work_dir / csv_name).exists())

    def test_cli_terminal_format_subprocess(self):
        """Verify CLI runs with --format terminal and returns exit code 0."""
        save_path = self.work_dir / "cli_terminal.sav"
        create_synthetic_save_file(save_path, bag_items={"strawberry": 5}, day=6)

        cmd = [
            sys.executable,
            str(REPO_ROOT / "gift_planner.py" if (REPO_ROOT / "gift_planner.py").exists() else REPO_ROOT / "scripts" / "gift_planner.py"),
            "--save-file", str(save_path),
            "--format", "terminal",
            "--mode", "all",
            "--slots", "5"
        ]

        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=str(REPO_ROOT)
        )
        self.assertEqual(res.returncode, 0, f"CLI command failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
        self.assertIsNotNone(res.stdout)
        self.assertIn("FIELDS OF MISTRIA", res.stdout)
        self.assertIn("OPTIMAL BAG LOADOUT", res.stdout)



class TestFocusSuggestions(unittest.TestCase):
    """Unit and Integration Tests for Focus Suggestion Algorithm and Terminal Output."""

    def setUp(self):
        self.recipes = {
            "golden_cheesecake": {
                "item_id": "golden_cheesecake",
                "display_name": "Golden Cheesecake",
                "output_count": 1,
                "ingredients": [
                    {"item_id": "golden_cheese", "count": 2},
                    {"item_id": "golden_butter", "count": 2},
                    {"item_id": "golden_cow_milk", "count": 2},
                    {"item_id": "golden_egg", "count": 2},
                    {"item_id": "flour", "count": 2},
                    {"item_id": "sugar", "count": 2},
                ]
            },
            "golden_cheese": {
                "item_id": "golden_cheese",
                "display_name": "Golden Cheese",
                "output_count": 1,
                "ingredients": [
                    {"item_id": "golden_cow_milk", "count": 2}
                ]
            },
            "golden_butter": {
                "item_id": "golden_butter",
                "display_name": "Golden Butter",
                "output_count": 1,
                "ingredients": [
                    {"item_id": "golden_cow_milk", "count": 2}
                ]
            },
            "flour": {
                "item_id": "flour",
                "display_name": "Flour",
                "output_count": 1,
                "ingredients": [
                    {"item_id": "wheat", "count": 1}
                ]
            },
            "sugar": {
                "item_id": "sugar",
                "display_name": "Sugar",
                "output_count": 1,
                "ingredients": [
                    {"item_id": "sugar_cane", "count": 1}
                ]
            },
            "cycle_a": {
                "item_id": "cycle_a",
                "display_name": "Cycle A",
                "ingredients": [{"item_id": "cycle_b", "count": 1}]
            },
            "cycle_b": {
                "item_id": "cycle_b",
                "display_name": "Cycle B",
                "ingredients": [{"item_id": "cycle_a", "count": 1}]
            }
        }
        self.meta = {
            "golden_cow_milk": {"display_name": "Golden Milk"},
            "golden_egg": {"display_name": "Golden Egg"},
            "wheat": {"display_name": "Wheat"},
            "sugar_cane": {"display_name": "Sugar Cane"},
            "ruby": {"display_name": "Ruby"},
            "ore_ruby": {"display_name": "Ruby"},
            "diamond": {"display_name": "Diamond"},
            "ore_diamond": {"display_name": "Diamond"},
            "apple": {"display_name": "Apple"},
        }

    def test_resolve_root_raw_materials_direct_item(self):
        """Direct raw item with no recipe resolves to itself."""
        res = resolve_root_raw_materials("ruby", self.recipes)
        self.assertEqual(res, {"ruby": 1})

    def test_resolve_root_raw_materials_single_step(self):
        """Single-step crafted item resolves to its ingredient."""
        res = resolve_root_raw_materials("golden_cheese", self.recipes)
        self.assertEqual(res, {"golden_cow_milk": 2})

    def test_resolve_root_raw_materials_multi_level(self):
        """Multi-level recipe resolves down to root raw materials."""
        res = resolve_root_raw_materials("golden_cheesecake", self.recipes)
        expected = {
            "golden_cow_milk": 10,  # 2*2 from cheese + 2*2 from butter + 2 direct = 10
            "golden_egg": 2,
            "wheat": 2,            # 2*1 from flour
            "sugar_cane": 2,       # 2*1 from sugar
        }
        self.assertEqual(res, expected)

    def test_resolve_root_raw_materials_circular_safe(self):
        """Circular recipe does not cause infinite recursion."""
        res = resolve_root_raw_materials("cycle_a", self.recipes)
        self.assertIn("cycle_a", res)

    def test_focus_ranking_by_blocked_pairs(self):
        """Items are ranked by number of blocked NPC-gift pairs descending."""
        remaining_map = {
            "item_a": {"loved": {"npc1", "npc2", "npc3"}, "liked": set()},  # 3 pairs for item_a
            "item_b": {"loved": {"npc1"}, "liked": {"npc2"}},               # 2 pairs for item_b
            "item_c": {"loved": {"npc4"}, "liked": set()},                   # 1 pair for item_c
        }
        suggestions = compute_focus_suggestions(
            remaining_items_map=remaining_map,
            inventory={},
            recipes={},
            item_metadata=self.meta,
        )
        self.assertEqual(len(suggestions), 3)
        self.assertEqual(suggestions[0]["item_id"], "item_a")
        self.assertEqual(suggestions[0]["blocked_pairs"], 3)
        self.assertEqual(suggestions[1]["item_id"], "item_b")
        self.assertEqual(suggestions[1]["blocked_pairs"], 2)
        self.assertEqual(suggestions[2]["item_id"], "item_c")
        self.assertEqual(suggestions[2]["blocked_pairs"], 1)

    def test_focus_ranking_tiebreaker_by_deficit(self):
        """When blocked NPC-gift pairs are equal, higher deficit breaks the tie."""
        remaining_map = {
            "ruby": {"loved": {"npc1", "npc2"}, "liked": set()},      # 2 pairs, demand = 2
            "golden_cheese": {"loved": {"npc1", "npc2"}, "liked": set()},  # 2 pairs, demand = 4 golden_cow_milk
        }
        suggestions = compute_focus_suggestions(
            remaining_items_map=remaining_map,
            inventory={},
            recipes=self.recipes,
            item_metadata=self.meta,
        )
        self.assertEqual(len(suggestions), 2)
        # Both have 2 blocked pairs, but golden_cow_milk has deficit 4, ruby has deficit 2
        self.assertEqual(suggestions[0]["item_id"], "golden_cow_milk")
        self.assertEqual(suggestions[0]["deficit"], 4)
        self.assertEqual(suggestions[1]["item_id"], "ruby")
        self.assertEqual(suggestions[1]["deficit"], 2)

    def test_focus_ranking_tiebreaker_by_name(self):
        """When blocked pairs and deficit are equal, alphabetical display name breaks the tie."""
        remaining_map = {
            "apple": {"loved": {"npc1"}, "liked": set()},
            "ruby": {"loved": {"npc2"}, "liked": set()},
        }
        suggestions = compute_focus_suggestions(
            remaining_items_map=remaining_map,
            inventory={},
            recipes=self.recipes,
            item_metadata=self.meta,
        )
        self.assertEqual(len(suggestions), 2)
        self.assertEqual(suggestions[0]["item_name"], "Apple")
        self.assertEqual(suggestions[1]["item_name"], "Ruby")

    def test_focus_inventory_deduction(self):
        """Player inventory reduces deficit; items with deficit <= 0 are excluded."""
        remaining_map = {
            "golden_cheese": {"loved": {"npc1", "npc2"}, "liked": set()},  # Needs 4 golden_cow_milk
            "ruby": {"loved": {"npc1"}, "liked": set()},                   # Needs 1 ruby
        }
        # Player has 1 golden_cow_milk (deficit 3) and 5 ruby (deficit 0)
        inv = {"golden_cow_milk": 1, "ruby": 5}
        suggestions = compute_focus_suggestions(
            remaining_items_map=remaining_map,
            inventory=inv,
            recipes=self.recipes,
            item_metadata=self.meta,
        )
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["item_id"], "golden_cow_milk")
        self.assertEqual(suggestions[0]["demand"], 4)
        self.assertEqual(suggestions[0]["inventory"], 1)
        self.assertEqual(suggestions[0]["deficit"], 3)

    def test_focus_recursive_resolution_blocks_root_materials(self):
        """Golden Cheesecake identifies Golden Milk, Golden Egg, Wheat, Sugar Cane as blockers."""
        remaining_map = {
            "golden_cheesecake": {"loved": {"npc1"}, "liked": {"npc2"}}
        }
        suggestions = compute_focus_suggestions(
            remaining_items_map=remaining_map,
            inventory={},
            recipes=self.recipes,
            item_metadata=self.meta,
        )
        suggestion_ids = [s["item_id"] for s in suggestions]
        self.assertIn("golden_cow_milk", suggestion_ids)
        self.assertIn("golden_egg", suggestion_ids)
        self.assertIn("wheat", suggestion_ids)
        self.assertIn("sugar_cane", suggestion_ids)
        self.assertNotIn("golden_cheese", suggestion_ids)
        self.assertNotIn("golden_butter", suggestion_ids)
        self.assertNotIn("flour", suggestion_ids)
        self.assertNotIn("sugar", suggestion_ids)

    def test_focus_location_hints(self):
        """Known farmable/minable/ranch items have location hints, unknown items have empty string."""
        remaining_map = {
            "golden_cow_milk": {"loved": {"npc1"}, "liked": set()},
            "ore_ruby": {"loved": {"npc2"}, "liked": set()},
            "unknown_mystery_item": {"loved": {"npc3"}, "liked": set()},
        }
        suggestions = compute_focus_suggestions(
            remaining_items_map=remaining_map,
            inventory={},
            recipes={},
            item_metadata={"unknown_mystery_item": {"display_name": "Mystery Item"}},
        )
        lookup = {s["item_id"]: s["location_hint"] for s in suggestions}
        self.assertIn("Ranch", lookup["golden_cow_milk"])
        self.assertIn("Upper Mines", lookup["ore_ruby"])
        self.assertEqual(lookup["unknown_mystery_item"], "")

    def test_focus_top_5_limit(self):
        """Top 5 limit is respected when more than 5 items have deficits."""
        remaining_map = {f"item_{i}": {"loved": {f"npc_{i}"}, "liked": set()} for i in range(10)}
        suggestions = compute_focus_suggestions(
            remaining_items_map=remaining_map,
            inventory={},
            recipes={},
            top_n=5,
        )
        self.assertEqual(len(suggestions), 5)
        for i, s in enumerate(suggestions, start=1):
            self.assertEqual(s["rank"], i)

    def test_focus_edge_case_empty_remaining_items(self):
        """When no gifts are pending, returns empty list."""
        suggestions = compute_focus_suggestions(
            remaining_items_map={},
            inventory={},
            recipes=self.recipes,
        )
        self.assertEqual(suggestions, [])

    def test_focus_edge_case_all_items_available(self):
        """When player has everything needed in inventory, returns empty list."""
        remaining_map = {
            "ruby": {"loved": {"npc1"}, "liked": set()}
        }
        inv = {"ruby": 10}
        suggestions = compute_focus_suggestions(
            remaining_items_map=remaining_map,
            inventory=inv,
            recipes=self.recipes,
        )
        self.assertEqual(suggestions, [])

    def test_focus_edge_case_no_save_file_or_inventory(self):
        """When inventory is None or empty, deficit equals demand."""
        remaining_map = {
            "ruby": {"loved": {"npc1", "npc2"}, "liked": set()}
        }
        suggestions = compute_focus_suggestions(
            remaining_items_map=remaining_map,
            inventory=None,
            recipes=self.recipes,
        )
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["demand"], 2)
        self.assertEqual(suggestions[0]["inventory"], 0)
        self.assertEqual(suggestions[0]["deficit"], 2)

    def test_plan_daily_gift_bag_returns_focus_suggestions(self):
        """plan_daily_gift_bag includes focus_suggestions in its return dict."""
        npcs = {
            "adeline": {"name": "Adeline", "loved": ["golden_cheesecake"], "liked": []}
        }
        plan = plan_daily_gift_bag(
            save=None,
            npc_gift_definitions=npcs,
            recipes=self.recipes,
            item_metadata=self.meta,
        )
        self.assertIn("focus_suggestions", plan)
        self.assertIsInstance(plan["focus_suggestions"], list)
        self.assertTrue(len(plan["focus_suggestions"]) > 0)
        top = plan["focus_suggestions"][0]
        self.assertIn("rank", top)
        self.assertIn("item_name", top)
        self.assertIn("deficit", top)
        self.assertIn("location_hint", top)

    def test_terminal_output_focus_suggestions_section(self):
        """print_terminal_plan includes FOCUS SUGGESTIONS section with Need X more and location hint."""
        plan_results = {
            "overall_stats": {
                "mode": "auto",
                "max_slots": 20,
                "covered_npcs_count": 1,
                "target_npcs_count": 1,
                "today_loved_completed": 1,
                "today_liked_completed": 0,
                "vendors_covered_today": 0,
                "game_total_loved": 1,
                "game_total_liked": 0,
                "game_total_preferences": 1,
                "game_given_loved": 0,
                "game_given_liked": 0,
                "game_given_total": 0,
                "remaining_unique_items": 1,
                "ungiftable_npcs": [],
                "not_present_npcs": [],
            },
            "bag_plan": [],
            "npc_progress": {},
            "focus_suggestions": [
                {
                    "rank": 1,
                    "item_id": "golden_cow_milk",
                    "item_name": "Golden Milk",
                    "blocked_pairs": 5,
                    "demand": 10,
                    "inventory": 2,
                    "deficit": 8,
                    "location_hint": "Ranch (Cows with high happiness)",
                }
            ],
            "remaining_items_map": {},
        }

        buf = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buf
            print_terminal_plan(save=None, plan_results=plan_results)
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        self.assertIn("FOCUS SUGGESTIONS", output)
        self.assertIn("Golden Milk", output)
        self.assertIn("Need 8 more", output)
        self.assertIn("Ranch (Cows with high happiness)", output)

    def test_terminal_output_congratulations_when_no_deficit(self):
        """print_terminal_plan outputs a congratulations message when focus_suggestions is empty."""
        plan_results = {
            "overall_stats": {
                "mode": "auto",
                "max_slots": 20,
                "covered_npcs_count": 1,
                "target_npcs_count": 1,
                "today_loved_completed": 1,
                "today_liked_completed": 0,
                "vendors_covered_today": 0,
                "game_total_loved": 1,
                "game_total_liked": 0,
                "game_total_preferences": 1,
                "game_given_loved": 1,
                "game_given_liked": 0,
                "game_given_total": 1,
                "remaining_unique_items": 0,
                "ungiftable_npcs": [],
                "not_present_npcs": [],
            },
            "bag_plan": [],
            "npc_progress": {},
            "focus_suggestions": [],
            "remaining_items_map": {},
        }

        buf = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buf
            print_terminal_plan(save=None, plan_results=plan_results)
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        self.assertIn("FOCUS SUGGESTIONS", output)
        self.assertIn("All required materials and gifts are currently in your inventory!", output)

    def test_direct_and_crafted_gifts_share_raw_material_demand_and_blocked_pairs(self):
        """When an item is used directly and in multiple recipes, demand and blocked pairs are aggregated."""
        remaining_map = {
            "golden_cow_milk": {"loved": {"npc1"}, "liked": set()},      # Direct: 1 * 1 = 1 milk, pair (npc1, golden_cow_milk)
            "golden_cheese": {"loved": {"npc2"}, "liked": set()},        # Crafted: 1 * 2 = 2 milk, pair (npc2, golden_cheese)
            "golden_cheesecake": {"loved": {"npc3"}, "liked": set()},    # Crafted: 1 * 10 = 10 milk, pair (npc3, golden_cheesecake)
        }
        suggestions = compute_focus_suggestions(
            remaining_items_map=remaining_map,
            inventory={"golden_cow_milk": 3},
            recipes=self.recipes,
            item_metadata=self.meta,
        )
        # Total demand for golden_cow_milk = 1 + 2 + 10 = 13. Inventory = 3. Deficit = 10.
        # Blocked pairs = 3: (npc1, golden_cow_milk), (npc2, golden_cheese), (npc3, golden_cheesecake)
        milk_sugg = next(s for s in suggestions if s["item_id"] == "golden_cow_milk")
        self.assertEqual(milk_sugg["demand"], 13)
        self.assertEqual(milk_sugg["inventory"], 3)
        self.assertEqual(milk_sugg["deficit"], 10)
        self.assertEqual(milk_sugg["blocked_pairs"], 3)

    def test_focus_diamond_recipe_dag(self):
        """Diamond DAG recipe tree counts all paths to root raw materials."""
        diamond_recipes = {
            "item_top": {
                "item_id": "item_top",
                "ingredients": [{"item_id": "branch_left", "count": 2}, {"item_id": "branch_right", "count": 3}]
            },
            "branch_left": {
                "item_id": "branch_left",
                "ingredients": [{"item_id": "root_ore", "count": 4}]
            },
            "branch_right": {
                "item_id": "branch_right",
                "ingredients": [{"item_id": "root_ore", "count": 5}]
            },
        }
        # 1 item_top = 2*4 + 3*5 = 8 + 15 = 23 root_ore
        res = resolve_root_raw_materials("item_top", diamond_recipes)
        self.assertEqual(res, {"root_ore": 23})

    def test_focus_robustness_with_float_and_string_inventory(self):
        """Inventory with float numbers and string floats cleans properly."""
        remaining_map = {
            "ruby": {"loved": {"npc1", "npc2"}, "liked": set()}
        }
        inv = {"ruby": "1.0", "ore_ruby": 5.5}
        suggestions = compute_focus_suggestions(
            remaining_items_map=remaining_map,
            inventory=inv,
            recipes=self.recipes,
            item_metadata=self.meta,
        )
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["demand"], 2)
        self.assertEqual(suggestions[0]["inventory"], 1)
        self.assertEqual(suggestions[0]["deficit"], 1)

    def test_focus_malformed_recipe_inputs_safe(self):
        """Malformed recipes, None ingredients, and invalid counts are handled safely without crashing."""
        bad_recipes = {
            "bad_1": None,
            "bad_2": {"ingredients": "not_a_list"},
            "bad_3": {"ingredients": [None, {}, {"item_id": "", "count": "abc"}, {"item_id": "raw_x", "count": -5}]},
        }
        self.assertEqual(resolve_root_raw_materials("bad_1", bad_recipes), {"bad_1": 1})
        self.assertEqual(resolve_root_raw_materials("bad_2", bad_recipes), {"bad_2": 1})
        self.assertEqual(resolve_root_raw_materials("bad_3", bad_recipes), {"raw_x": 1})

    def test_focus_top_n_zero_or_negative(self):
        """Passing top_n <= 0 returns an empty list."""
        remaining_map = {"ruby": {"loved": {"npc1"}, "liked": set()}}
        self.assertEqual(compute_focus_suggestions(remaining_map, top_n=0), [])
        self.assertEqual(compute_focus_suggestions(remaining_map, top_n=-5), [])

    def test_expanded_location_hints_categories(self):
        """Test location hints across diverse categories: mines, crops, ranch, fish, store."""
        remaining_map = {
            "salmon": {"loved": {"npc1"}, "liked": set()},
            "oil": {"loved": {"npc2"}, "liked": set()},
            "ore_gold": {"loved": {"npc3"}, "liked": set()},
            "turnip": {"loved": {"npc4"}, "liked": set()},
            "golden_cow_milk": {"loved": {"npc5"}, "liked": set()},
            "bonito": {"loved": {"npc6"}, "liked": set()},
            "golden_bristle": {"loved": {"npc7"}, "liked": set()},
            "clay": {"loved": {"npc8"}, "liked": set()},
            "fog_orchid": {"loved": {"npc9"}, "liked": set()},
            "coral": {"loved": {"npc10"}, "liked": set()},
        }
        suggestions = compute_focus_suggestions(
            remaining_items_map=remaining_map,
            inventory={},
            recipes={},
            top_n=10,
        )
        lookup = {s["item_id"]: s["location_hint"] for s in suggestions}
        self.assertIn("Fishing (River, Spring / Fall)", lookup["salmon"])
        self.assertIn("General Store", lookup["oil"])
        self.assertIn("The Lava Caves", lookup["ore_gold"])
        self.assertIn("Spring Crop", lookup["turnip"])
        self.assertIn("Ranch (Cows with high happiness)", lookup["golden_cow_milk"])
        self.assertIn("Fishing (Ocean", lookup["bonito"])
        self.assertIn("Ranch (Capybaras with high happiness)", lookup["golden_bristle"])
        self.assertIn("Digging", lookup["clay"])
        self.assertIn("Foraging (Fall", lookup["fog_orchid"])
        self.assertIn("The Beach", lookup["coral"])

    def test_focus_single_string_npc_in_loved_or_liked(self):
        """Passing a single string as loved or liked is treated as a single NPC, not character split."""
        remaining_map = {
            "ruby": {"loved": "adeline", "liked": ""}
        }
        suggestions = compute_focus_suggestions(
            remaining_items_map=remaining_map,
            inventory={},
            recipes=self.recipes,
            item_metadata=self.meta,
        )
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["blocked_pairs"], 1)
        self.assertEqual(suggestions[0]["demand"], 1)
        self.assertEqual(suggestions[0]["deficit"], 1)

    def test_focus_npc_collection_with_none_and_empty_strings(self):
        """None and empty strings in loved/liked lists are filtered out."""
        remaining_map = {
            "ruby": {"loved": ["adeline", None, "", "   "], "liked": [None]}
        }
        suggestions = compute_focus_suggestions(
            remaining_items_map=remaining_map,
            inventory={},
            recipes=self.recipes,
            item_metadata=self.meta,
        )
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["blocked_pairs"], 1)
        self.assertEqual(suggestions[0]["demand"], 1)
        self.assertEqual(suggestions[0]["deficit"], 1)

    def test_focus_remaining_items_map_non_dict_safe(self):
        """Passing None or non-dict as remaining_items_map returns empty list safely."""
        self.assertEqual(compute_focus_suggestions(None), [])
        self.assertEqual(compute_focus_suggestions(["not", "a", "dict"]), [])

    def test_focus_non_dict_and_malformed_inventory(self):
        """Passing list or invalid type as inventory does not crash and defaults to 0 inventory."""
        remaining_map = {"ruby": {"loved": {"npc1"}, "liked": set()}}
        s1 = compute_focus_suggestions(remaining_map, inventory=["not", "a", "dict"])
        self.assertEqual(len(s1), 1)
        self.assertEqual(s1[0]["inventory"], 0)
        self.assertEqual(s1[0]["deficit"], 1)

        s2 = compute_focus_suggestions(remaining_map, inventory=12345)
        self.assertEqual(len(s2), 1)
        self.assertEqual(s2[0]["inventory"], 0)

    def test_focus_item_metadata_string_values_and_malformed(self):
        """item_metadata with string values or non-dict structures is handled gracefully."""
        remaining_map = {"ruby": {"loved": {"npc1"}, "liked": set()}}
        s1 = compute_focus_suggestions(remaining_map, item_metadata={"ruby": "Ruby Gem"})
        self.assertEqual(len(s1), 1)
        self.assertEqual(s1[0]["item_name"], "Ruby Gem")

        s2 = compute_focus_suggestions(remaining_map, item_metadata="not_a_dict")
        self.assertEqual(len(s2), 1)
        self.assertEqual(s2[0]["item_name"], "Ruby")

    def test_focus_empty_and_whitespace_item_keys(self):
        """Empty or whitespace-only item keys in remaining_items_map are safely ignored."""
        remaining_map = {
            "   ": {"loved": {"npc1"}, "liked": set()},
            "": {"loved": {"npc2"}, "liked": set()},
            "ruby": {"loved": {"npc3"}, "liked": set()},
        }
        suggestions = compute_focus_suggestions(remaining_map)
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["item_id"], "ruby")

    def test_expanded_location_hints_flowers_and_mining(self):
        """Verifies location hints for farm flowers, crystals, and mine artifacts."""
        remaining_map = {
            "daisy": {"loved": {"npc1"}, "liked": set()},
            "cosmos": {"loved": {"npc2"}, "liked": set()},
            "crystal_rose": {"loved": {"npc3"}, "liked": set()},
            "jewel_beetle": {"loved": {"npc4"}, "liked": set()},
        }
        suggestions = compute_focus_suggestions(remaining_map, top_n=10)
        lookup = {s["item_id"]: s["location_hint"] for s in suggestions}
        self.assertIn("Summer Flower", lookup["daisy"])
        self.assertIn("Summer Flower", lookup["cosmos"])
        self.assertIn("Floors 41-59", lookup["crystal_rose"])
        self.assertIn("Catching", lookup["jewel_beetle"])

    def test_intermediate_goods_satisfy_root_raw_material_deficits(self):
        """Having processed intermediate goods (e.g. flour, sugar) satisfies raw crop demand."""
        recipes = {
            "flour": {"ingredients": [{"item_id": "wheat", "count": 1}]},
            "sugar": {"ingredients": [{"item_id": "sugar_cane", "count": 1}]},
            "cake": {
                "ingredients": [
                    {"item_id": "flour", "count": 1},
                    {"item_id": "sugar", "count": 1},
                ]
            }
        }
        remaining_map = {
            "cake": {"loved": {"npc1", "npc2"}, "liked": set()},  # Needs 2 flour (2 wheat) + 2 sugar (2 sugar_cane)
        }
        # Case A: Empty inventory -> both wheat and sugar_cane needed
        suggs_empty = compute_focus_suggestions(remaining_map, inventory={}, recipes=recipes)
        ids_empty = [s["item_id"] for s in suggs_empty]
        self.assertIn("wheat", ids_empty)
        self.assertIn("sugar_cane", ids_empty)

        # Case B: Player bought flour and sugar -> deficits are satisfied and removed
        inv = {"flour": 5, "sugar": 5}
        suggs_satisfied = compute_focus_suggestions(remaining_map, inventory=inv, recipes=recipes)
        self.assertEqual(suggs_satisfied, [])

    def test_pre_crafted_gifts_in_inventory_satisfy_pending_preferences(self):
        """Pre-crafted finished gifts in inventory eliminate raw material demand for those gifts."""
        recipes = {
            "lemon_cake": {
                "ingredients": [
                    {"item_id": "lemon", "count": 1},
                    {"item_id": "sugar", "count": 1},
                ]
            }
        }
        remaining_map = {
            "lemon_cake": {"loved": {"npc1"}, "liked": set()}
        }
        # Player has the finished cake in storage -> no lemons or sugar needed
        inv = {"lemon_cake": 1}
        suggs = compute_focus_suggestions(remaining_map, inventory=inv, recipes=recipes)
        self.assertEqual(suggs, [])

    def test_focus_suggestions_include_saturday_market_vendors_on_weekday(self):
        """
        Verify that even on a weekday (or mode='weekday') when Saturday Market vendors
        (e.g. Darcy, Stillwell) are not in town, focus suggestions evaluate their pending
        gift preferences so players know what to farm/collect during the week.
        """
        npcs = {
            "adeline": {"name": "Adeline", "loved": ["tea"], "liked": []},
            "darcy": {"name": "Darcy", "loved": ["spell_fruit"], "liked": []},
        }
        meta = {
            "tea": {"display_name": "Tea"},
            "spell_fruit": {"display_name": "Spell Fruit"},
        }
        plan = plan_daily_gift_bag(
            save=None,
            npc_gift_definitions=npcs,
            item_metadata=meta,
            mode="weekday",
            recipes={},
        )
        # Darcy is a market vendor, so Darcy should NOT be in target_npcs for a weekday
        self.assertNotIn("darcy", plan["target_npcs"])
        self.assertIn("adeline", plan["target_npcs"])
        # Bag plan should not cover Darcy today
        for b in plan["bag_plan"]:
            self.assertNotIn("Darcy", b["all_recipients_today"])

        # BUT focus suggestions MUST include Darcy's Spell Fruit!
        sugg_ids = [s["item_id"] for s in plan["focus_suggestions"]]
        self.assertIn("spell_fruit", sugg_ids)

    def test_focus_suggestions_include_already_gifted_npcs(self):
        """
        Verify that NPCs already gifted today (can_gift=False) are excluded from
        today's daily bag loadout, but their unfulfilled gift preferences are still
        accounted for in focus suggestions.
        """
        class MockSave:
            in_game_date = None
            def get_npc_gifts_given(self, nid):
                return set()
            def is_npc_present_in_town_today(self, nid):
                return True
            def can_gift_npc_today(self, nid):
                return nid != "adeline"  # Adeline already gifted today
            def get_npc_heart_points(self, nid):
                return 0.0

        npcs = {
            "adeline": {"name": "Adeline", "loved": ["golden_cheesecake"], "liked": []},
            "balor": {"name": "Balor", "loved": ["ruby"], "liked": []},
        }
        plan = plan_daily_gift_bag(
            save=MockSave(),
            npc_gift_definitions=npcs,
            item_metadata=self.meta,
            recipes=self.recipes,
            mode="auto",
        )
        # Adeline cannot be gifted today
        self.assertNotIn("adeline", plan["target_npcs"])
        self.assertIn("balor", plan["target_npcs"])

        # But Adeline's Golden Cheesecake blockers (golden_cow_milk, etc.) must still appear in focus suggestions
        sugg_ids = [s["item_id"] for s in plan["focus_suggestions"]]
        self.assertIn("golden_cow_milk", sugg_ids)

    def test_focus_suggestions_consistency_weekday_vs_saturday(self):
        """
        Verify that focus suggestions return identical rankings and blocker deficits
        regardless of whether mode='weekday' or mode='saturday' when the underlying
        game/inventory state is the same.
        """
        npcs = {
            "adeline": {"name": "Adeline", "loved": ["wheat"], "liked": []},
            "darcy": {"name": "Darcy", "loved": ["spell_fruit"], "liked": []},
            "hayden": {"name": "Hayden", "loved": ["golden_cow_milk"], "liked": []},
        }
        meta = {
            "wheat": {"display_name": "Wheat"},
            "spell_fruit": {"display_name": "Spell Fruit"},
            "golden_cow_milk": {"display_name": "Golden Milk"},
        }
        plan_weekday = plan_daily_gift_bag(
            save=None,
            npc_gift_definitions=npcs,
            item_metadata=meta,
            mode="weekday",
            recipes={},
        )
        plan_saturday = plan_daily_gift_bag(
            save=None,
            npc_gift_definitions=npcs,
            item_metadata=meta,
            mode="saturday",
            recipes={},
        )
        suggs_w = plan_weekday["focus_suggestions"]
        suggs_s = plan_saturday["focus_suggestions"]
        self.assertEqual(len(suggs_w), len(suggs_s))
        self.assertEqual([s["item_id"] for s in suggs_w], [s["item_id"] for s in suggs_s])
        self.assertEqual([s["deficit"] for s in suggs_w], [s["deficit"] for s in suggs_s])

    def test_focus_suggestions_respects_exclude_npcs(self):
        """
        Verify that explicitly excluded NPCs (via exclude_npcs) are excluded
        from focus suggestions as well.
        """
        npcs = {
            "adeline": {"name": "Adeline", "loved": ["tea"], "liked": []},
            "darcy": {"name": "Darcy", "loved": ["spell_fruit"], "liked": []},
        }
        meta = {
            "tea": {"display_name": "Tea"},
            "spell_fruit": {"display_name": "Spell Fruit"},
        }
        plan = plan_daily_gift_bag(
            save=None,
            npc_gift_definitions=npcs,
            item_metadata=meta,
            exclude_npcs={"darcy"},
            recipes={},
        )
        sugg_ids = [s["item_id"] for s in plan["focus_suggestions"]]
        self.assertNotIn("spell_fruit", sugg_ids)
        self.assertIn("tea", sugg_ids)



class TestAnimalFestivalPlanning(unittest.TestCase):
    """Integration tests for Animal Festival (Winter 10) planning, vendor boost, and CLI banners."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.temp_dir.name)
        self.mock_recipes = get_mock_recipes()
        self.mock_meta = get_mock_meta()

        # Custom NPC list with townsfolk, festival vendors (Merri, Louis), and non-festival vendor (Darcy)
        self.test_npcs = {
            "adeline": {
                "name": "Adeline",
                "loved": ["golden_cheesecake"],
                "liked": ["cornmeal"]
            },
            "march": {
                "name": "March",
                "loved": ["deluxe_sandwich"],
                "liked": ["bread"]
            },
            "celine": {
                "name": "Celine",
                "loved": ["strawberry_shortcake"],
                "liked": ["strawberry"]
            },
            "louis": {  # Saturday Vendor attending Animal Festival
                "name": "Louis",
                "loved": ["strawberry_shortcake"],
                "liked": ["strawberry"]
            },
            "merri": {  # Saturday Vendor attending Animal Festival
                "name": "Merri",
                "loved": ["golden_cheesecake"],
                "liked": ["cornmeal"]
            },
            "darcy": {  # Saturday Vendor NOT attending Animal Festival
                "name": "Darcy",
                "loved": ["deluxe_sandwich"],
                "liked": ["sugar"]
            },
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_auto_mode_on_winter_10_includes_merri_and_louis(self):
        """Verify that on Winter 10 (Animal Festival), auto mode includes Merri & Louis and excludes Darcy."""
        save_path = self.work_dir / "animal_festival.sav"
        create_synthetic_save_file(save_path, season="winter", day=10)
        save = parse_save_file(save_path)

        self.assertTrue(save.in_game_date.is_animal_festival)
        self.assertFalse(save.in_game_date.is_saturday)

        plan = plan_daily_gift_bag(
            save=save,
            npc_gift_definitions=self.test_npcs,
            item_metadata=self.mock_meta,
            mode="auto",
            max_slots=10,
            recipes=self.mock_recipes,
        )

        stats = plan["overall_stats"]
        self.assertTrue(stats["is_animal_festival"])
        # Target NPCs should be 5: Adeline, March, Celine, Louis, Merri (Darcy is excluded as non-attending vendor)
        self.assertEqual(stats["target_npcs_count"], 5)

        p = plan["npc_progress"]
        self.assertTrue(p["louis"]["is_present_today"])
        self.assertTrue(p["merri"]["is_present_today"])
        self.assertFalse(p["darcy"]["is_present_today"])

    def test_vendor_boost_applies_to_animal_festival_vendors(self):
        """Verify that vendor_boost prioritizes Louis/Merri over townsfolk on Animal Festival."""
        # Player has 1 strawberry_shortcake (loved by Celine [townsfolk] and Louis [festival vendor]).
        # With max_slots=1, if both compete for an item or if vendor boost is active, Louis gets priority.
        bag = {"strawberry_shortcake": 1}
        save_path = self.work_dir / "boost_test.sav"
        create_synthetic_save_file(save_path, bag_items=bag, season="winter", day=10)
        save = parse_save_file(save_path)

        plan = plan_daily_gift_bag(
            save=save,
            npc_gift_definitions=self.test_npcs,
            item_metadata=self.mock_meta,
            mode="auto",
            max_slots=1,
            vendor_boost=2.0,
            recipes=self.mock_recipes,
        )

        slot = plan["bag_plan"][0]
        recip_ids = [r["npc_id"] for r in slot["all_recipients_today"]]
        # Louis must be selected as the recipient due to vendor boost
        self.assertIn("louis", recip_ids)

    def test_animal_festival_terminal_banner(self):
        """Verify print_terminal_plan prints dedicated Animal Festival banner."""
        save_path = self.work_dir / "banner_test.sav"
        create_synthetic_save_file(save_path, season="winter", day=10)
        save = parse_save_file(save_path)

        plan = plan_daily_gift_bag(
            save=save,
            npc_gift_definitions=self.test_npcs,
            item_metadata=self.mock_meta,
            mode="auto",
            max_slots=5,
            recipes=self.mock_recipes,
        )

        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_terminal_plan(save, plan)
        output = buf.getvalue()

        self.assertIn("TODAY IS ANIMAL FESTIVAL DAY! (Winter 10)", output)
        self.assertIn("28 NPCs present in town", output)
        self.assertIn("Merri & Louis receive priority boost", output)
        self.assertIn("6 Saturday Market vendors remain in Aldaria", output)


class TestItemLocations(unittest.TestCase):
    """Tests verifying data/item_locations.json loading and injection."""

    def test_load_item_locations_canonical(self):
        """load_item_locations() loads data/item_locations.json with expected items."""
        locs = load_item_locations()
        self.assertIsInstance(locs, dict)
        self.assertGreater(len(locs), 200)
        self.assertIn("golden_cow_milk", locs)
        self.assertEqual(locs["golden_cow_milk"], "Ranch (Cows with high happiness)")
        self.assertIn("copper_ore", locs)
        self.assertEqual(locs["copper_ore"], "Upper Mines (Floors 1-19)")
        self.assertIn("tulip", locs)
        self.assertEqual(locs["tulip"], "Farm (Spring Flower)")

    def test_load_item_locations_custom_path(self):
        """load_item_locations() loads custom path when specified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_file = Path(tmpdir) / "custom_locs.json"
            custom_data = {
                "super_gem": "Mystic Cavern Floor 100",
                "rare_flower": "Secret Garden",
            }
            custom_file.write_text(json.dumps(custom_data), encoding="utf-8")

            loaded = load_item_locations(str(custom_file))
            self.assertEqual(loaded.get("super_gem"), "Mystic Cavern Floor 100")
            self.assertEqual(loaded.get("rare_flower"), "Secret Garden")
            self.assertNotIn("copper_ore", loaded)

    def test_load_item_locations_missing_or_invalid(self):
        """load_item_locations() returns empty dict for missing or invalid files."""
        self.assertEqual(load_item_locations("non_existent_file.json"), {})
        with tempfile.TemporaryDirectory() as tmpdir:
            corrupt = Path(tmpdir) / "corrupt.json"
            corrupt.write_text("NOT JSON CONTENT", encoding="utf-8")
            self.assertEqual(load_item_locations(str(corrupt)), {})

    def test_compute_focus_suggestions_custom_locations(self):
        """compute_focus_suggestions respects explicitly injected item_locations."""
        remaining_map = {
            "special_ore": {"loved": {"march"}, "liked": set()},
        }
        custom_locs = {"special_ore": "Custom Secret Spot"}
        suggestions = compute_focus_suggestions(
            remaining_map,
            inventory={},
            recipes={},
            item_locations=custom_locs,
        )
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["location_hint"], "Custom Secret Spot")

    def test_plan_daily_gift_bag_custom_locations(self):
        """plan_daily_gift_bag propagates custom item_locations to focus suggestions."""
        npcs = {
            "march": {"name": "March", "loved": ["custom_ore"], "liked": []},
        }
        custom_locs = {"custom_ore": "Custom Mine Level 42"}
        plan = plan_daily_gift_bag(
            npc_gift_definitions=npcs,
            item_locations=custom_locs,
        )
        suggs = plan.get("focus_suggestions", [])
        self.assertTrue(any(s.get("location_hint") == "Custom Mine Level 42" for s in suggs))


class TestProgressionAwareGiftPlanning(unittest.TestCase):
    """Unit tests for progression-aware Saturday Market vendor and story-gated NPC unlock planning."""

    def setUp(self):
        import tempfile
        import shutil
        self.test_dir = Path(tempfile.mkdtemp())

        # Base 4 vendors + 24 townsfolk (no Caldarus, no Seridia, no upgrade vendors)
        self.base_townsfolk_ids = [
            "adeline", "balor", "celine", "dell", "dozy", "eiland", "elsie", "errol",
            "hayden", "hemlock", "henrietta", "holt", "josephine", "juniper", "landen",
            "luc", "maple", "march", "nora", "olric", "reina", "ryis", "terithia", "valen"
        ]
        self.base_vendor_ids = ["darcy", "louis", "merri", "vera"]
        self.early_game_npc_ids = self.base_townsfolk_ids + self.base_vendor_ids

        # Full 34 NPC gift definitions
        self.full_npcs = {}
        for nid in self.early_game_npc_ids:
            self.full_npcs[nid] = {
                "name": nid.capitalize(),
                "loved": [f"{nid}_loved_gift"],
                "liked": [f"{nid}_liked_gift"],
            }
        # Add locked upgrade vendors
        for nid in ["taliferro", "wheedle", "stillwell", "zorel"]:
            self.full_npcs[nid] = {
                "name": nid.capitalize(),
                "loved": [f"{nid}_loved_gift"],
                "liked": [f"{nid}_liked_gift"],
            }
        # Add locked story-gated townsfolk
        for nid in ["caldarus", "seridia"]:
            self.full_npcs[nid] = {
                "name": nid.capitalize(),
                "loved": [f"{nid}_loved_gift"],
                "liked": [f"{nid}_liked_gift"],
            }

        self.mock_recipes = {}
        self.mock_meta = {}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_early_game_save_filters_locked_vendors_and_townsfolk(self):
        """Verify that early game save only plans for unlocked NPCs, excluding locked vendors & townsfolk."""
        save_path = self.test_dir / "early_game.sav"
        create_synthetic_save_file(save_path, day=6, npc_ids=self.early_game_npc_ids)
        save = parse_save_file(save_path)

        # Confirm save only has 28 NPCs
        self.assertEqual(len(save.get_unlocked_npc_ids()), 28)
        self.assertEqual(len(save.get_unlocked_vendor_ids()), 4)

        plan = plan_daily_gift_bag(
            save=save,
            npc_gift_definitions=self.full_npcs,
            item_metadata=self.mock_meta,
            mode="saturday",
            max_slots=30,
            recipes=self.mock_recipes,
        )

        stats = plan["overall_stats"]
        self.assertEqual(stats["unlocked_vendors_count"], 4)
        self.assertEqual(stats["unlocked_townsfolk_count"], 24)
        self.assertEqual(stats["unlocked_npcs_count"], 28)
        self.assertEqual(stats["target_npcs_count"], 28)

        # 6 NPCs should be detected as locked (4 vendors + 2 story townsfolk)
        locked_names = stats["locked_npcs"]
        self.assertEqual(len(locked_names), 6)
        for expected in ["Taliferro", "Wheedle", "Stillwell", "Zorel", "Caldarus", "Seridia"]:
            self.assertIn(expected, locked_names)

        # Ensure no locked NPC is targeted in bag_plan
        for b in plan["bag_plan"]:
            for r in b["all_recipients_today"]:
                self.assertNotIn(r["npc_id"], ["taliferro", "wheedle", "stillwell", "zorel", "caldarus", "seridia"])

    def test_no_save_file_treats_all_as_unlocked(self):
        """When no save file is provided, all NPCs in definitions are treated as unlocked."""
        plan = plan_daily_gift_bag(
            save=None,
            npc_gift_definitions=self.full_npcs,
            item_metadata=self.mock_meta,
            mode="saturday",
            max_slots=30,
            recipes=self.mock_recipes,
        )
        stats = plan["overall_stats"]
        self.assertEqual(len(stats["locked_npcs"]), 0)
        self.assertEqual(stats["target_npcs_count"], 34)

    def test_focus_suggestions_include_locked_npcs(self):
        """Focus suggestions should remain forward-looking and include gifts for locked NPCs."""
        save_path = self.test_dir / "early_game_focus.sav"
        create_synthetic_save_file(save_path, day=6, npc_ids=self.early_game_npc_ids)
        save = parse_save_file(save_path)

        # Caldarus is locked in this save, but loves 'dragon_statue'
        custom_npcs = {
            "adeline": {
                "name": "Adeline",
                "loved": ["adeline_loved_gift"],
                "liked": [],
            },
            "caldarus": {
                "name": "Caldarus",
                "loved": ["dragon_statue"],
                "liked": [],
            },
        }

        plan = plan_daily_gift_bag(
            save=save,
            npc_gift_definitions=custom_npcs,
            item_metadata={"dragon_statue": {"display_name": "Dragon Statue"}},
            mode="saturday",
            max_slots=5,
            recipes={},
        )

        # Caldarus is locked and not targeted in bag plan
        self.assertIn("Caldarus", plan["overall_stats"]["locked_npcs"])
        for b in plan["bag_plan"]:
            for r in b["all_recipients_today"]:
                self.assertNotEqual(r["npc_id"], "caldarus")

        # But 'dragon_statue' should be in focus suggestions
        suggestion_ids = [s["item_id"] for s in plan["focus_suggestions"]]
        self.assertIn("dragon_statue", suggestion_ids)

    def test_terminal_output_dynamic_counts_and_locked_banner(self):
        """Verify terminal output shows dynamic counts and the locked NPCs banner."""
        save_path = self.test_dir / "terminal_progression.sav"
        create_synthetic_save_file(save_path, day=6, npc_ids=self.early_game_npc_ids)
        save = parse_save_file(save_path)

        plan = plan_daily_gift_bag(
            save=save,
            npc_gift_definitions=self.full_npcs,
            item_metadata=self.mock_meta,
            mode="saturday",
            max_slots=10,
            recipes=self.mock_recipes,
        )

        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_terminal_plan(save, plan)
        output = buf.getvalue()

        # Check dynamic counts on Saturday: 28 NPCs (24 townsfolk + 4 visiting vendors)
        self.assertIn("All 28 NPCs (24 townsfolk + 4 visiting vendors) are in town!", output)

        # Check locked NPCs banner
        self.assertIn("🔒 NOT YET UNLOCKED (6 NPCs):", output)
        self.assertIn("Zorel", output)
        self.assertIn("Caldarus", output)


# ==============================================================================
# MAX-RELATIONSHIP STRATEGY & INFUSED ITEM TEST SUITE (Milestone 4, Requirement R5)
# ==============================================================================

class TestMaxRelationshipStrategy(unittest.TestCase):
    """
    Comprehensive test suite for the max-relationship gift planning strategy and
    cooking-perk infused item detection (Milestone 4, Requirement R5).
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.temp_dir.name)
        self.mock_recipes = get_mock_recipes()
        self.mock_npcs = get_mock_npcs()
        self.mock_meta = get_mock_meta()

    def tearDown(self):
        self.temp_dir.cleanup()

    # ==========================================================================
    # SCENARIO 1: Infused item detection from bag inventory (lovable/likable)
    # ==========================================================================

    def test_get_infused_items_bag_scenario_1(self):
        """
        Scenario 1: Infused item detection from bag inventory (lovable/likable).
        Verifies that SaveData.get_infused_items() extracts lovable and likable items
        from the player bag inventory, aggregates duplicate stacks within the bag,
        records location as 'bag', and ignores non-infused items.
        """
        save_path = self.work_dir / "scenario_1_bag_infused.sav"
        custom_bag_slots = [
            create_mock_slot("apple_pie", 2, infusion="lovable"),
            create_mock_slot("vegetable_soup", 1, infusion="likable"),
            create_mock_slot("strawberry", 5, infusion=None),  # Normal item without infusion
            create_mock_slot("apple_pie", 3, infusion="lovable"),  # Duplicate stack in bag
        ]
        create_synthetic_save_file(save_path, bag_slots=custom_bag_slots)
        save = parse_save_file(save_path)

        infused = save.get_infused_items()

        # 1. Structure validation
        self.assertIsInstance(infused, dict)
        self.assertIn("lovable", infused)
        self.assertIn("likable", infused)

        # 2. Lovable dishes: apple_pie stacks aggregated (2 + 3 = 5)
        self.assertEqual(len(infused["lovable"]), 1)
        self.assertEqual(infused["lovable"][0]["item_id"], "apple_pie")
        self.assertEqual(infused["lovable"][0]["count"], 5)
        self.assertEqual(infused["lovable"][0]["location"], "bag")

        # 3. Likable dishes: vegetable_soup
        self.assertEqual(len(infused["likable"]), 1)
        self.assertEqual(infused["likable"][0]["item_id"], "vegetable_soup")
        self.assertEqual(infused["likable"][0]["count"], 1)
        self.assertEqual(infused["likable"][0]["location"], "bag")

        # 4. Non-infused items are excluded
        lovable_ids = [x["item_id"] for x in infused["lovable"]]
        likable_ids = [x["item_id"] for x in infused["likable"]]
        self.assertNotIn("strawberry", lovable_ids)
        self.assertNotIn("strawberry", likable_ids)

    # ==========================================================================
    # SCENARIO 2: Infused item detection from chest inventories across locations
    # ==========================================================================

    def test_get_infused_items_chests_across_locations_scenario_2(self):
        """
        Scenario 2: Infused item detection from chest inventories across locations.
        Verifies that SaveData.get_infused_items() scans chests across multiple location keys,
        aggregates duplicate stacks within the same location, keeps separate entries for distinct
        locations, ignores non-location keys, and sorts deterministically by (item_id, location).
        """
        save_path = self.work_dir / "scenario_2_chests_infused.sav"
        chests = {
            "farm": [
                [
                    create_mock_slot("berry_tart", 3, infusion="lovable"),
                    create_mock_slot("wood", 50),
                ],
                [
                    create_mock_slot("berry_tart", 2, infusion="lovable"),  # 2nd chest in farm
                ],
            ],
            "farm_house": [
                [
                    create_mock_slot("bread", 2, infusion="likable"),
                ],
            ],
            "mines": [
                [
                    create_mock_slot("berry_tart", 4, infusion="lovable"),
                    create_mock_slot("iron_ore", 10),
                ],
            ],
        }
        create_synthetic_save_file(save_path, chests_by_location=chests)
        save = parse_save_file(save_path)

        infused = save.get_infused_items()

        # 1. Structure validation
        self.assertIsInstance(infused, dict)
        self.assertIn("lovable", infused)
        self.assertIn("likable", infused)

        # 2. Lovable dishes across locations
        # "farm": 3 + 2 = 5 berry_tart; "mines": 4 berry_tart
        self.assertEqual(len(infused["lovable"]), 2)
        # Deterministic sorting: ("berry_tart", "farm") before ("berry_tart", "mines")
        self.assertEqual(
            infused["lovable"][0],
            {"item_id": "berry_tart", "count": 5, "location": "farm"},
        )
        self.assertEqual(
            infused["lovable"][1],
            {"item_id": "berry_tart", "count": 4, "location": "mines"},
        )

        # 3. Likable dishes: farm_house has 2 bread
        self.assertEqual(len(infused["likable"]), 1)
        self.assertEqual(
            infused["likable"][0],
            {"item_id": "bread", "count": 2, "location": "farm_house"},
        )

        # 4. Total counts across storage
        total_lovable = sum(x["count"] for x in infused["lovable"])
        total_likable = sum(x["count"] for x in infused["likable"])
        self.assertEqual(total_lovable, 9)
        self.assertEqual(total_likable, 2)

        # 5. Non-infused materials excluded
        all_detected_ids = [x["item_id"] for x in infused["lovable"] + infused["likable"]]
        self.assertNotIn("wood", all_detected_ids)
        self.assertNotIn("iron_ore", all_detected_ids)

    # ==========================================================================
    # SCENARIO 3: No infused items edge case
    # ==========================================================================

    def test_get_infused_items_empty_edge_case_scenario_3(self):
        """
        Scenario 3: No infused items edge case.
        Verifies that SaveData.get_infused_items() returns clean empty lists without errors
        when a save file has zero infused items. Also verifies that plan_max_relationship()
        handles the empty infusion structure cleanly without crashing.
        """
        save_path = self.work_dir / "scenario_3_no_infusions.sav"
        bag = {"strawberry": 5, "egg": 10}
        chests = {
            "farm": [[create_mock_slot("corn", 8)]],
        }
        create_synthetic_save_file(save_path, bag_items=bag, chests_by_location=chests)
        save = parse_save_file(save_path)

        infused = save.get_infused_items()

        # 1. Structure must contain guaranteed keys with empty lists
        self.assertEqual(infused, {"lovable": [], "likable": []})

        # 2. Verify optimizer execution with zero infused items
        plan = plan_max_relationship(
            save=save,
            npc_gift_definitions=self.mock_npcs,
            item_metadata=self.mock_meta,
            mode="auto",
            max_slots=10,
            force_all_npcs=True,
        )

        stats = plan["overall_stats"]
        self.assertEqual(stats["strategy"], "max-relationship")
        self.assertEqual(stats["infused_items_detected"], 0)
        # Normal gifts still assigned according to inventory
        self.assertGreaterEqual(stats["covered_npcs_count"], 1)
        self.assertGreaterEqual(stats["total_relationship_points"], 10)

    # ==========================================================================
    # SCENARIO 4: Basic love gift assignment (+20 pts)
    # ==========================================================================

    def test_plan_max_rel_basic_love_assignment_scenario_4(self):
        """
        Scenario 4: Basic love gift assignment (+20 pts).
        Verifies that plan_max_relationship() prioritizes loved gifts (+20 pts each)
        for eligible present NPCs over like gifts, correctly tags preference type
        as 'LOVE', awards 20 points per recipient, and sums total relationship points.
        """
        npcs = {
            "adeline": {
                "name": "Adeline",
                "loved": ["golden_cheesecake"],
                "liked": ["strawberry"],  # 10 available, but loved item (+20) must be picked
            },
            "march": {
                "name": "March",
                "loved": ["deluxe_sandwich"],
                "liked": ["bread"],
            },
        }
        inv = {
            "golden_cheesecake": 1,
            "strawberry": 10,
            "deluxe_sandwich": 1,
            "bread": 5,
        }

        plan = plan_max_relationship(
            npc_gift_definitions=npcs,
            item_metadata=self.mock_meta,
            inventory=inv,
            force_all_npcs=True,
        )

        stats = plan["overall_stats"]
        progress = plan["npc_progress"]
        bag_plan = plan["bag_plan"]

        # 1. Overall stats assertions
        self.assertEqual(stats["strategy"], "max-relationship")
        self.assertEqual(stats["covered_npcs_count"], 2)
        self.assertEqual(stats["target_npcs_count"], 2)
        self.assertEqual(stats["today_loved_completed"], 2)
        self.assertEqual(stats["today_liked_completed"], 0)
        self.assertEqual(stats["total_relationship_points"], 40)  # 2 x 20 pts

        # 2. Adeline received golden_cheesecake (loved), NOT strawberry (liked)
        self.assertEqual(progress["adeline"]["assigned_item_id"], "golden_cheesecake")
        self.assertEqual(progress["adeline"]["assigned_pref_type"], "LOVE")
        self.assertEqual(progress["adeline"]["assigned_points"], 20)

        # 3. March received deluxe_sandwich (loved)
        self.assertEqual(progress["march"]["assigned_item_id"], "deluxe_sandwich")
        self.assertEqual(progress["march"]["assigned_pref_type"], "LOVE")
        self.assertEqual(progress["march"]["assigned_points"], 20)

        # 4. Bag plan slots verification
        packed_item_ids = {b["item_id"] for b in bag_plan}
        self.assertEqual(packed_item_ids, {"golden_cheesecake", "deluxe_sandwich"})
        for b in bag_plan:
            self.assertEqual(b["status"], "HAVE")
            self.assertEqual(b["status_badge"], "📦 HAVE")
            for recip in b["all_recipients_today"]:
                self.assertEqual(recip["pref"], "LOVE")
                self.assertEqual(recip["points"], 20)

    # ==========================================================================
    # SCENARIO 5: Most abundant love gift selection
    # ==========================================================================

    def test_plan_max_rel_most_abundant_love_selection_scenario_5(self):
        """
        Scenario 5: Most abundant love gift selection.
        Verifies that when an NPC loves multiple items present in inventory,
        plan_max_relationship() prioritizes the candidate with the highest inventory count.
        Also verifies the symmetric case and deterministic tie-breaking.
        """
        npcs = {
            "adeline": {
                "name": "Adeline",
                "loved": ["golden_cheesecake", "strawberry_shortcake"],
                "liked": ["strawberry"],
            }
        }

        # Case A: strawberry_shortcake is more abundant (8 vs 2)
        inv_a = {"golden_cheesecake": 2, "strawberry_shortcake": 8}
        plan_a = plan_max_relationship(
            npc_gift_definitions=npcs,
            item_metadata=self.mock_meta,
            inventory=inv_a,
            force_all_npcs=True,
        )
        self.assertEqual(
            plan_a["npc_progress"]["adeline"]["assigned_item_id"],
            "strawberry_shortcake",
            "Should pick strawberry_shortcake because count 8 > count 2",
        )
        self.assertEqual(plan_a["npc_progress"]["adeline"]["assigned_points"], 20)

        # Case B: golden_cheesecake is more abundant (10 vs 1)
        inv_b = {"golden_cheesecake": 10, "strawberry_shortcake": 1}
        plan_b = plan_max_relationship(
            npc_gift_definitions=npcs,
            item_metadata=self.mock_meta,
            inventory=inv_b,
            force_all_npcs=True,
        )
        self.assertEqual(
            plan_b["npc_progress"]["adeline"]["assigned_item_id"],
            "golden_cheesecake",
            "Should pick golden_cheesecake because count 10 > count 1",
        )
        self.assertEqual(plan_b["npc_progress"]["adeline"]["assigned_points"], 20)

        # Case C: Equal abundance tie-breaker (5 vs 5)
        # "Golden Cheesecake" ('g') precedes "Strawberry Shortcake" ('s') alphabetically
        inv_c = {"golden_cheesecake": 5, "strawberry_shortcake": 5}
        plan_c = plan_max_relationship(
            npc_gift_definitions=npcs,
            item_metadata=self.mock_meta,
            inventory=inv_c,
            force_all_npcs=True,
        )
        self.assertEqual(
            plan_c["npc_progress"]["adeline"]["assigned_item_id"],
            "golden_cheesecake",
            "Should tie-break deterministically by display name",
        )

    # ==========================================================================
    # SCENARIO 6: Universal love fallback when no specific love gift available
    # ==========================================================================

    def test_plan_max_rel_universal_love_fallback_scenario_6(self):
        """
        Scenario 6: Universal love fallback when no specific love gift available.
        Verifies that when an NPC has no specific love gift available in physical inventory,
        but a cooking-infused lovable dish exists, plan_max_relationship() allocates the
        universal love dish (+20 pts) even if multiple specific like gifts are present in inventory.
        Also tests integration with synthetic save containing lovable dishes in chests.
        """
        # Part 1: Direct inventory & infused_items call
        custom_npcs = {
            "adeline": {
                "name": "Adeline",
                "loved": ["golden_cheesecake"],
                "liked": ["strawberry"],
            }
        }
        inventory = {"strawberry": 10}
        infused_items = {
            "lovable": [{"item_id": "apple_pie", "count": 1, "location": "bag"}],
            "likable": [],
        }

        plan = plan_max_relationship(
            npc_gift_definitions=custom_npcs,
            item_metadata=self.mock_meta,
            inventory=inventory,
            infused_items=infused_items,
            mode="all",
        )

        p = plan["npc_progress"]["adeline"]
        # Must assign Universal Love dish (apple_pie), NOT specific like (strawberry)
        self.assertEqual(p["assigned_item_id"], "apple_pie")
        self.assertEqual(p["assigned_pref_type"], "UNIV_LOVE")
        self.assertEqual(p["assigned_points"], 20)

        stats = plan["overall_stats"]
        self.assertEqual(stats["total_relationship_points"], 20)
        self.assertEqual(stats["today_loved_completed"], 1)
        self.assertEqual(stats["today_liked_completed"], 0)
        self.assertEqual(stats["covered_npcs_count"], 1)

        # Verify bag plan slot structure
        self.assertEqual(len(plan["bag_plan"]), 1)
        bag_slot = plan["bag_plan"][0]
        self.assertEqual(bag_slot["item_id"], "apple_pie")
        self.assertEqual(bag_slot["quantity_to_pack"], 1)
        self.assertIn("Adeline", bag_slot["loved_recipients_today"])
        self.assertNotIn("Adeline", bag_slot["liked_recipients_today"])
        self.assertEqual(bag_slot["all_recipients_today"][0]["pref"], "UNIV_LOVE")
        self.assertEqual(bag_slot["all_recipients_today"][0]["pref_tier"], "UNIV_LOVE")
        self.assertEqual(bag_slot["all_recipients_today"][0]["points"], 20)

        # Part 2: Integration variant reading lovable dish from save chests
        save_path = self.work_dir / "scenario6_fallback.sav"
        chests = {
            "farm": [[
                create_mock_slot("apple_pie", 1, infusion="lovable")
            ]]
        }
        create_synthetic_save_file(
            save_path,
            bag_items={"strawberry": 5},
            chests_by_location=chests,
            day=6,
        )
        save = parse_save_file(save_path)

        plan_save = plan_max_relationship(
            save=save,
            npc_gift_definitions=custom_npcs,
            item_metadata=self.mock_meta,
            mode="all",
        )
        p_save = plan_save["npc_progress"]["adeline"]
        self.assertEqual(p_save["assigned_item_id"], "apple_pie")
        self.assertEqual(p_save["assigned_pref_type"], "UNIV_LOVE")
        self.assertEqual(p_save["assigned_points"], 20)
        self.assertEqual(plan_save["overall_stats"]["total_relationship_points"], 20)

    # ==========================================================================
    # SCENARIO 7: Like gift fallback when no love available
    # ==========================================================================

    def test_plan_max_rel_like_gift_fallback_scenario_7(self):
        """
        Scenario 7: Like gift fallback when no love available.
        Verifies that when no specific love and no universal love are available,
        the planner falls back to a specific liked gift (+10 pts).
        Also verifies specific like is prioritized over universal like to preserve universal pool.
        """
        custom_npcs = {
            "adeline": {
                "name": "Adeline",
                "loved": ["golden_cheesecake"],
                "liked": ["strawberry"],
            }
        }
        # Part 1: Basic like gift fallback
        inventory = {"strawberry": 5, "stone": 100}
        infused_items = {"lovable": [], "likable": []}

        plan = plan_max_relationship(
            npc_gift_definitions=custom_npcs,
            item_metadata=self.mock_meta,
            inventory=inventory,
            infused_items=infused_items,
            mode="all",
        )

        p = plan["npc_progress"]["adeline"]
        self.assertEqual(p["assigned_item_id"], "strawberry")
        self.assertEqual(p["assigned_pref_type"], "LIKE")
        self.assertEqual(p["assigned_points"], 10)

        stats = plan["overall_stats"]
        self.assertEqual(stats["total_relationship_points"], 10)
        self.assertEqual(stats["today_loved_completed"], 0)
        self.assertEqual(stats["today_liked_completed"], 1)
        self.assertEqual(stats["today_total_completed"], 1)

        # Bag slot verification
        self.assertEqual(len(plan["bag_plan"]), 1)
        bag_slot = plan["bag_plan"][0]
        self.assertEqual(bag_slot["item_id"], "strawberry")
        self.assertEqual(bag_slot["quantity_to_pack"], 1)
        self.assertIn("Adeline", bag_slot["liked_recipients_today"])
        self.assertNotIn("Adeline", bag_slot["loved_recipients_today"])
        self.assertEqual(bag_slot["all_recipients_today"][0]["pref"], "LIKE")
        self.assertEqual(bag_slot["all_recipients_today"][0]["points"], 10)

        # Part 2: Specific like is prioritized over universal like (even when universal like is 5x more abundant)
        inventory = {"strawberry": 1, "stone": 100}
        infused_items_with_likable = {
            "lovable": [],
            "likable": [{"item_id": "vegetable_soup", "count": 5, "location": "bag"}],
        }
        plan_preservation = plan_max_relationship(
            npc_gift_definitions=custom_npcs,
            item_metadata=self.mock_meta,
            inventory=inventory,
            infused_items=infused_items_with_likable,
            mode="all",
        )
        p_pres = plan_preservation["npc_progress"]["adeline"]
        self.assertEqual(p_pres["assigned_item_id"], "strawberry")
        self.assertEqual(p_pres["assigned_pref_type"], "LIKE")
        self.assertEqual(p_pres["assigned_points"], 10)

    # ==========================================================================
    # SCENARIO 8: Universal like fallback as last resort
    # ==========================================================================

    def test_plan_max_rel_universal_like_fallback_scenario_8(self):
        """
        Scenario 8: Universal like fallback as last resort.
        Verifies that when an NPC has no specific love, universal love, or specific like available,
        the planner assigns a universal like dish (+10 pts) as a last resort, strictly avoiding
        neutral items. Also verifies that when universal like pool is exhausted, remaining NPCs are skipped.
        """
        # Part 1: Universal like fallback avoids neutral items
        custom_npcs = {
            "adeline": {
                "name": "Adeline",
                "loved": ["golden_cheesecake"],
                "liked": ["cornmeal"],
            }
        }
        # Inventory contains only neutral items (stone, wood); loved/liked items are absent (0)
        inventory = {"stone": 50, "wood": 50}
        infused_items = {
            "lovable": [],
            "likable": [{"item_id": "vegetable_soup", "count": 1, "location": "farm"}],
        }

        plan = plan_max_relationship(
            npc_gift_definitions=custom_npcs,
            item_metadata=self.mock_meta,
            inventory=inventory,
            infused_items=infused_items,
            mode="all",
        )

        p = plan["npc_progress"]["adeline"]
        self.assertEqual(p["assigned_item_id"], "vegetable_soup")
        self.assertEqual(p["assigned_pref_type"], "UNIV_LIKE")
        self.assertEqual(p["assigned_points"], 10)

        stats = plan["overall_stats"]
        self.assertEqual(stats["total_relationship_points"], 10)
        self.assertEqual(stats["today_loved_completed"], 0)
        self.assertEqual(stats["today_liked_completed"], 1)
        self.assertEqual(stats["covered_npcs_count"], 1)

        # Bag slot verification: universal like dish is packed; neutral items are NOT packed
        self.assertEqual(len(plan["bag_plan"]), 1)
        bag_slot = plan["bag_plan"][0]
        self.assertEqual(bag_slot["item_id"], "vegetable_soup")
        self.assertIn("Adeline", bag_slot["liked_recipients_today"])
        self.assertEqual(bag_slot["all_recipients_today"][0]["pref"], "UNIV_LIKE")
        self.assertEqual(bag_slot["all_recipients_today"][0]["pref_tier"], "UNIV_LIKE")

        # Part 2: Universal like exhaustion skips remaining NPCs
        custom_two_npcs = {
            "adeline": {"name": "Adeline", "loved": ["absent_love"], "liked": ["absent_like"]},
            "balor": {"name": "Balor", "loved": ["absent_love"], "liked": ["absent_like"]},
        }
        plan_exhaust = plan_max_relationship(
            npc_gift_definitions=custom_two_npcs,
            inventory={"stone": 100},
            infused_items={"lovable": [], "likable": [{"item_id": "vegetable_soup", "count": 1}]},
            mode="all",
        )
        self.assertEqual(plan_exhaust["overall_stats"]["covered_npcs_count"], 1)
        self.assertEqual(plan_exhaust["overall_stats"]["target_npcs_count"], 2)
        self.assertEqual(plan_exhaust["overall_stats"]["total_relationship_points"], 10)
        assigned_items = [p_exp["assigned_item_id"] for p_exp in plan_exhaust["npc_progress"].values()]
        self.assertIn("vegetable_soup", assigned_items)
        self.assertIn(None, assigned_items)

    # ==========================================================================
    # SCENARIO 9: Full priority hierarchy verification
    # ==========================================================================

    def test_plan_max_rel_full_priority_hierarchy_scenario_9(self):
        """
        Scenario 9: Full priority hierarchy verification.
        Verifies the full 5-tier priority hierarchy:
        Specific Love (+20) > Universal Love (+20) > Specific Like (+10) > Universal Like (+10) > Skip (+0).
        Tests both concurrent multi-NPC allocation and sequential downgrade for a single NPC.
        """
        # Part 1: Concurrent multi-NPC plan with exact mathematical relationship score validation
        custom_npcs = {
            "npc_love": {"name": "1_NPC_Love", "loved": ["item_love"], "liked": ["item_like"]},
            "npc_univ_love": {"name": "2_NPC_UnivLove", "loved": ["absent_a"], "liked": []},
            "npc_like": {"name": "3_NPC_Like", "loved": ["absent_b"], "liked": ["item_like"]},
            "npc_univ_like": {"name": "4_NPC_UnivLike", "loved": ["absent_c"], "liked": ["absent_d"]},
            "npc_skip": {"name": "5_NPC_Skip", "loved": ["absent_e"], "liked": ["absent_f"]},
        }
        inventory = {
            "item_love": 1,
            "item_like": 1,
            "neutral_stone": 50,
        }
        infused_items = {
            "lovable": [{"item_id": "dish_love", "count": 1}],
            "likable": [{"item_id": "dish_like", "count": 1}],
        }

        plan = plan_max_relationship(
            npc_gift_definitions=custom_npcs,
            item_metadata=self.mock_meta,
            inventory=inventory,
            infused_items=infused_items,
            mode="all",
        )

        progress = plan["npc_progress"]

        # 1. Specific Love (+20)
        self.assertEqual(progress["npc_love"]["assigned_item_id"], "item_love")
        self.assertEqual(progress["npc_love"]["assigned_pref_type"], "LOVE")
        self.assertEqual(progress["npc_love"]["assigned_points"], 20)

        # 2. Universal Love (+20)
        self.assertEqual(progress["npc_univ_love"]["assigned_item_id"], "dish_love")
        self.assertEqual(progress["npc_univ_love"]["assigned_pref_type"], "UNIV_LOVE")
        self.assertEqual(progress["npc_univ_love"]["assigned_points"], 20)

        # 3. Specific Like (+10)
        self.assertEqual(progress["npc_like"]["assigned_item_id"], "item_like")
        self.assertEqual(progress["npc_like"]["assigned_pref_type"], "LIKE")
        self.assertEqual(progress["npc_like"]["assigned_points"], 10)

        # 4. Universal Like (+10)
        self.assertEqual(progress["npc_univ_like"]["assigned_item_id"], "dish_like")
        self.assertEqual(progress["npc_univ_like"]["assigned_pref_type"], "UNIV_LIKE")
        self.assertEqual(progress["npc_univ_like"]["assigned_points"], 10)

        # 5. Skip (+0)
        self.assertIsNone(progress["npc_skip"]["assigned_item_id"])
        self.assertIsNone(progress["npc_skip"]["assigned_pref_type"])
        self.assertEqual(progress["npc_skip"]["assigned_points"], 0)

        # Overall summary mathematical verification: 20 + 20 + 10 + 10 + 0 = 60
        stats = plan["overall_stats"]
        self.assertEqual(stats["total_relationship_points"], 60)
        self.assertEqual(stats["today_loved_completed"], 2)
        self.assertEqual(stats["today_liked_completed"], 2)
        self.assertEqual(stats["today_total_completed"], 4)
        self.assertEqual(stats["covered_npcs_count"], 4)
        self.assertEqual(stats["target_npcs_count"], 5)
        self.assertEqual(len(plan["bag_plan"]), 4)

        # Part 2: Sequential step-by-step downgrade for a single NPC
        single_npc = {
            "adeline": {
                "name": "Adeline",
                "loved": ["golden_cheesecake"],
                "liked": ["strawberry"],
            }
        }
        # Step 1: All available -> Specific Love
        p1 = plan_max_relationship(
            npc_gift_definitions=single_npc,
            inventory={"golden_cheesecake": 1, "strawberry": 1, "stone": 10},
            infused_items={"lovable": [{"item_id": "apple_pie", "count": 1}], "likable": [{"item_id": "soup", "count": 1}]},
            mode="all",
        )["npc_progress"]["adeline"]
        self.assertEqual(p1["assigned_item_id"], "golden_cheesecake")
        self.assertEqual(p1["assigned_pref_type"], "LOVE")
        self.assertEqual(p1["assigned_points"], 20)

        # Step 2: Specific Love removed -> Universal Love
        p2 = plan_max_relationship(
            npc_gift_definitions=single_npc,
            inventory={"strawberry": 1, "stone": 10},
            infused_items={"lovable": [{"item_id": "apple_pie", "count": 1}], "likable": [{"item_id": "soup", "count": 1}]},
            mode="all",
        )["npc_progress"]["adeline"]
        self.assertEqual(p2["assigned_item_id"], "apple_pie")
        self.assertEqual(p2["assigned_pref_type"], "UNIV_LOVE")
        self.assertEqual(p2["assigned_points"], 20)

        # Step 3: Universal Love removed -> Specific Like
        p3 = plan_max_relationship(
            npc_gift_definitions=single_npc,
            inventory={"strawberry": 1, "stone": 10},
            infused_items={"lovable": [], "likable": [{"item_id": "soup", "count": 1}]},
            mode="all",
        )["npc_progress"]["adeline"]
        self.assertEqual(p3["assigned_item_id"], "strawberry")
        self.assertEqual(p3["assigned_pref_type"], "LIKE")
        self.assertEqual(p3["assigned_points"], 10)

        # Step 4: Specific Like removed -> Universal Like
        p4 = plan_max_relationship(
            npc_gift_definitions=single_npc,
            inventory={"stone": 10},
            infused_items={"lovable": [], "likable": [{"item_id": "soup", "count": 1}]},
            mode="all",
        )["npc_progress"]["adeline"]
        self.assertEqual(p4["assigned_item_id"], "soup")
        self.assertEqual(p4["assigned_pref_type"], "UNIV_LIKE")
        self.assertEqual(p4["assigned_points"], 10)

        # Step 5: Universal Like removed -> Skipped (+0 pts)
        p5 = plan_max_relationship(
            npc_gift_definitions=single_npc,
            inventory={"stone": 10},
            infused_items={"lovable": [], "likable": []},
            mode="all",
        )["npc_progress"]["adeline"]
        self.assertIsNone(p5["assigned_item_id"])
        self.assertIsNone(p5["assigned_pref_type"])
        self.assertEqual(p5["assigned_points"], 0)

    # ==========================================================================
    # SCENARIO 10: Shared inventory constraint
    # ==========================================================================

    def test_plan_max_rel_shared_inventory_deduction_scenario_10(self):
        """
        Scenario 10: Shared inventory constraint.
        Verifies that when multiple NPCs love the same item, inventory is deducted correctly
        after each assignment, unallocated NPCs fall back or are skipped, and cross-pool
        synchronization prevents double spending.
        """
        # Part 1: 3 NPCs love golden_cheesecake, 2 in inventory, 3rd falls back to like
        custom_npcs = {
            "adeline": {"name": "Adeline", "loved": ["golden_cheesecake"], "liked": []},
            "balor": {"name": "Balor", "loved": ["golden_cheesecake"], "liked": []},
            "celine": {"name": "Celine", "loved": ["golden_cheesecake"], "liked": ["strawberry"]},
        }
        inventory = {"golden_cheesecake": 2, "strawberry": 5}

        plan = plan_max_relationship(
            npc_gift_definitions=custom_npcs,
            item_metadata=self.mock_meta,
            inventory=inventory,
            mode="all",
        )

        progress = plan["npc_progress"]
        self.assertEqual(progress["adeline"]["assigned_item_id"], "golden_cheesecake")
        self.assertEqual(progress["adeline"]["assigned_pref_type"], "LOVE")
        self.assertEqual(progress["adeline"]["assigned_points"], 20)

        self.assertEqual(progress["balor"]["assigned_item_id"], "golden_cheesecake")
        self.assertEqual(progress["balor"]["assigned_pref_type"], "LOVE")
        self.assertEqual(progress["balor"]["assigned_points"], 20)

        self.assertEqual(progress["celine"]["assigned_item_id"], "strawberry")
        self.assertEqual(progress["celine"]["assigned_pref_type"], "LIKE")
        self.assertEqual(progress["celine"]["assigned_points"], 10)

        stats = plan["overall_stats"]
        self.assertEqual(stats["total_relationship_points"], 50)
        self.assertEqual(stats["today_loved_completed"], 2)
        self.assertEqual(stats["today_liked_completed"], 1)
        self.assertEqual(stats["covered_npcs_count"], 3)

        # Exactly 2 packed for cheesecake, 1 for strawberry
        self.assertEqual(len(plan["bag_plan"]), 2)
        cheesecake_slot = next(b for b in plan["bag_plan"] if b["item_id"] == "golden_cheesecake")
        strawberry_slot = next(b for b in plan["bag_plan"] if b["item_id"] == "strawberry")
        self.assertEqual(cheesecake_slot["quantity_to_pack"], 2)
        self.assertCountEqual(cheesecake_slot["loved_recipients_today"], ["Adeline", "Balor"])
        self.assertEqual(strawberry_slot["quantity_to_pack"], 1)
        self.assertEqual(strawberry_slot["liked_recipients_today"], ["Celine"])

        # Part 2: Strict exhaustion without fallback (3rd NPC skipped)
        strict_npcs = {
            "adeline": {"name": "Adeline", "loved": ["golden_cheesecake"], "liked": []},
            "balor": {"name": "Balor", "loved": ["golden_cheesecake"], "liked": []},
            "darcy": {"name": "Darcy", "loved": ["golden_cheesecake"], "liked": []},
        }
        plan_strict = plan_max_relationship(
            npc_gift_definitions=strict_npcs,
            item_metadata=self.mock_meta,
            inventory={"golden_cheesecake": 2},
            mode="all",
        )
        assigned_items = [p_s["assigned_item_id"] for p_s in plan_strict["npc_progress"].values()]
        self.assertEqual(assigned_items.count("golden_cheesecake"), 2)
        self.assertEqual(assigned_items.count(None), 1)
        self.assertEqual(plan_strict["overall_stats"]["total_relationship_points"], 40)
        self.assertEqual(plan_strict["overall_stats"]["covered_npcs_count"], 2)
        self.assertEqual(plan_strict["overall_stats"]["target_npcs_count"], 3)

        # Part 3: Cross-pool synchronization deduction
        sync_npcs = {
            "npc_specific": {"name": "NPC1", "loved": ["apple_pie"], "liked": []},
            "npc_univ1": {"name": "NPC2", "loved": ["absent"], "liked": []},
            "npc_univ2": {"name": "NPC3", "loved": ["absent"], "liked": []},
        }
        plan_sync = plan_max_relationship(
            npc_gift_definitions=sync_npcs,
            inventory={"apple_pie": 2},
            infused_items={"lovable": [{"item_id": "apple_pie", "count": 2}], "likable": []},
            mode="all",
        )
        self.assertEqual(plan_sync["npc_progress"]["npc_specific"]["assigned_pref_type"], "LOVE")
        self.assertEqual(plan_sync["npc_progress"]["npc_univ1"]["assigned_pref_type"], "UNIV_LOVE")
        self.assertIsNone(plan_sync["npc_progress"]["npc_univ2"]["assigned_pref_type"])
        apple_slot = plan_sync["bag_plan"][0]
        self.assertEqual(apple_slot["item_id"], "apple_pie")
        self.assertEqual(apple_slot["quantity_to_pack"], 2)
        self.assertEqual(plan_sync["overall_stats"]["total_relationship_points"], 40)

    # ==========================================================================
    # SCENARIO 11: Greedy most-constrained-first allocation (MRV)
    # ==========================================================================

    def test_plan_max_rel_greedy_mrv_allocation_scenario_11(self):
        """
        Scenario 11: Greedy most-constrained-first allocation (MRV).
        Constrained NPCs with fewer gift alternatives are allocated shared items
        before flexible NPCs, overriding alphabetical tie-breaking.
        """
        # "Zoe" is alphabetically last but has only 1 love option (constrained).
        # "Aaron" is alphabetically first but has 2 love options (flexible).
        custom_npcs = {
            "zoe": {
                "name": "Zoe",
                "loved": ["golden_cheesecake"],
                "liked": [],
            },
            "aaron": {
                "name": "Aaron",
                "loved": ["golden_cheesecake", "strawberry_shortcake"],
                "liked": [],
            },
        }
        # Shared item: golden_cheesecake (1). Alternative: strawberry_shortcake (1).
        inv = {"golden_cheesecake": 1, "strawberry_shortcake": 1}

        plan = plan_max_relationship(
            npc_gift_definitions=custom_npcs,
            item_metadata=self.mock_meta,
            inventory=inv,
        )

        # Zoe (constrained, 1 candidate) must receive golden_cheesecake
        self.assertEqual(plan["npc_progress"]["zoe"]["assigned_item_id"], "golden_cheesecake")
        self.assertEqual(plan["npc_progress"]["zoe"]["assigned_pref_type"], "LOVE")
        self.assertEqual(plan["npc_progress"]["zoe"]["assigned_points"], 20)

        # Aaron (flexible, 2 candidates) must receive alternative strawberry_shortcake
        self.assertEqual(plan["npc_progress"]["aaron"]["assigned_item_id"], "strawberry_shortcake")
        self.assertEqual(plan["npc_progress"]["aaron"]["assigned_pref_type"], "LOVE")
        self.assertEqual(plan["npc_progress"]["aaron"]["assigned_points"], 20)

        # Both covered, total 40 points
        self.assertEqual(plan["overall_stats"]["today_loved_completed"], 2)
        self.assertEqual(plan["overall_stats"]["today_liked_completed"], 0)
        self.assertEqual(plan["overall_stats"]["covered_npcs_count"], 2)
        self.assertEqual(plan["overall_stats"]["total_relationship_points"], 40)

    # ==========================================================================
    # SCENARIO 12: Empty inventory edge case
    # ==========================================================================

    def test_plan_max_rel_empty_inventory_edge_case_scenario_12(self):
        """
        Scenario 12: Empty inventory edge case.
        Verifies that planner handles completely empty inventory without crashing.
        Expects empty bag plan, 0 covered NPCs, and 0 relationship points.
        """
        plan = plan_max_relationship(
            npc_gift_definitions=self.mock_npcs,
            item_metadata=self.mock_meta,
            inventory={},
            infused_items={},
        )

        self.assertEqual(len(plan["bag_plan"]), 0)
        self.assertEqual(plan["covered_npcs"], set())
        self.assertEqual(plan["overall_stats"]["slots_used"], 0)
        self.assertEqual(plan["overall_stats"]["covered_npcs_count"], 0)
        self.assertEqual(plan["overall_stats"]["total_relationship_points"], 0)
        self.assertEqual(plan["overall_stats"]["today_loved_completed"], 0)
        self.assertEqual(plan["overall_stats"]["today_liked_completed"], 0)

        # All NPCs unassigned
        for nid, prog in plan["npc_progress"].items():
            self.assertIsNone(prog["assigned_item_id"])
            self.assertEqual(prog["assigned_points"], 0)
            self.assertIsNone(prog["assigned_pref_type"])

        # downstream maps and focus suggestions must still be valid
        self.assertIsInstance(plan["remaining_items_map"], dict)
        self.assertIsInstance(plan["focus_suggestions"], list)

    # ==========================================================================
    # SCENARIO 13: No giftable NPCs edge case
    # ==========================================================================

    def test_plan_max_rel_no_giftable_npcs_edge_case_scenario_13(self):
        """
        Scenario 13: No giftable NPCs edge case.
        Verifies planner behavior when all NPCs have already received gifts today.
        Expects target_npcs to be empty, bag_plan empty, and 0 points awarded.
        Also verifies force_all_npcs=True bypasses this restriction.
        """
        save_path = self.work_dir / "all_gifted.sav"
        create_synthetic_save_file(
            save_path,
            bag_items={"golden_cheesecake": 5, "strawberry": 10},
            giftable_all=False,  # Sets gift_flag=False for all NPCs
        )
        save = parse_save_file(save_path)

        plan = plan_max_relationship(
            save=save,
            npc_gift_definitions=self.mock_npcs,
            item_metadata=self.mock_meta,
        )

        self.assertEqual(plan["target_npcs"], set())
        self.assertEqual(plan["covered_npcs"], set())
        self.assertEqual(len(plan["bag_plan"]), 0)
        self.assertEqual(plan["overall_stats"]["target_npcs_count"], 0)
        self.assertEqual(plan["overall_stats"]["covered_npcs_count"], 0)
        self.assertEqual(plan["overall_stats"]["total_relationship_points"], 0)
        self.assertTrue(len(plan["overall_stats"]["ungiftable_npcs"]) > 0)

        # Verify force_all_npcs=True bypasses this restriction
        plan_forced = plan_max_relationship(
            save=save,
            npc_gift_definitions=self.mock_npcs,
            item_metadata=self.mock_meta,
            force_all_npcs=True,
        )
        self.assertTrue(len(plan_forced["target_npcs"]) > 0)
        self.assertTrue(plan_forced["overall_stats"]["total_relationship_points"] > 0)

    # ==========================================================================
    # SCENARIO 14: Total relationship points calculation
    # ==========================================================================

    def test_plan_max_rel_total_relationship_points_calculation_scenario_14(self):
        """
        Scenario 14: Total relationship points calculation.
        Verifies exact mathematical sum of relationship points across all tiers:
        Specific Love (+20), Universal Love (+20), Specific Like (+10), Universal Like (+10),
        and Skipped (+0).
        """
        hetero_npcs = {
            "npc_love": {"name": "Alice", "loved": ["deluxe_sandwich"], "liked": []},
            "npc_univ_love": {"name": "Bob", "loved": ["unobtainium_1"], "liked": []},
            "npc_like": {"name": "Charlie", "loved": ["unobtainium_2"], "liked": ["strawberry"]},
            "npc_univ_like": {"name": "David", "loved": ["unobtainium_3"], "liked": ["unobtainium_4"]},
            "npc_skip": {"name": "Eve", "loved": ["unobtainium_5"], "liked": ["unobtainium_6"]},
        }
        inv = {"deluxe_sandwich": 1, "strawberry": 5}
        infused = {
            "lovable": [{"item_id": "apple_pie", "count": 1}],
            "likable": [{"item_id": "vegetable_soup", "count": 1}],
        }

        plan = plan_max_relationship(
            npc_gift_definitions=hetero_npcs,
            item_metadata=self.mock_meta,
            inventory=inv,
            infused_items=infused,
        )

        # Alice: Specific Love (+20)
        self.assertEqual(plan["npc_progress"]["npc_love"]["assigned_pref_type"], "LOVE")
        self.assertEqual(plan["npc_progress"]["npc_love"]["assigned_points"], 20)

        # Bob: Universal Love (+20)
        self.assertEqual(plan["npc_progress"]["npc_univ_love"]["assigned_pref_type"], "UNIV_LOVE")
        self.assertEqual(plan["npc_progress"]["npc_univ_love"]["assigned_points"], 20)

        # Charlie: Specific Like (+10)
        self.assertEqual(plan["npc_progress"]["npc_like"]["assigned_pref_type"], "LIKE")
        self.assertEqual(plan["npc_progress"]["npc_like"]["assigned_points"], 10)

        # David: Universal Like (+10)
        self.assertEqual(plan["npc_progress"]["npc_univ_like"]["assigned_pref_type"], "UNIV_LIKE")
        self.assertEqual(plan["npc_progress"]["npc_univ_like"]["assigned_points"], 10)

        # Eve: Skipped (+0)
        self.assertIsNone(plan["npc_progress"]["npc_skip"]["assigned_item_id"])
        self.assertEqual(plan["npc_progress"]["npc_skip"]["assigned_points"], 0)

        # Exact mathematical sum: 20 + 20 + 10 + 10 + 0 = 60 points
        self.assertEqual(plan["overall_stats"]["today_loved_completed"], 2)
        self.assertEqual(plan["overall_stats"]["today_liked_completed"], 2)
        self.assertEqual(plan["overall_stats"]["today_total_completed"], 4)
        self.assertEqual(plan["overall_stats"]["covered_npcs_count"], 4)
        self.assertEqual(plan["overall_stats"]["target_npcs_count"], 5)
        self.assertEqual(plan["overall_stats"]["total_relationship_points"], 60)

    # ==========================================================================
    # SCENARIO 15: Saturday Market vendor inclusion
    # ==========================================================================

    def test_plan_max_rel_saturday_market_vendor_inclusion_scenario_15(self):
        """
        Scenario 15: Saturday Market vendor inclusion.
        Verifies Saturday Market vendors are targeted on Saturdays (Day 6)
        and excluded on weekdays (Day 3) in auto mode. Also verifies mode='saturday' override.
        """
        sat_path = self.work_dir / "saturday_market.sav"
        wed_path = self.work_dir / "weekday.sav"
        create_synthetic_save_file(sat_path, day=6, bag_items={"golden_cheesecake": 5})
        create_synthetic_save_file(wed_path, day=3, bag_items={"golden_cheesecake": 5})

        save_sat = parse_save_file(sat_path)
        save_wed = parse_save_file(wed_path)

        # On Saturday in auto mode: Darcy (market vendor) is present and giftable
        plan_sat = plan_max_relationship(
            save=save_sat,
            npc_gift_definitions=self.mock_npcs,
            item_metadata=self.mock_meta,
            mode="auto",
        )
        self.assertIn("darcy", plan_sat["target_npcs"])
        self.assertIn("darcy", plan_sat["covered_npcs"])
        self.assertEqual(plan_sat["npc_progress"]["darcy"]["assigned_item_id"], "golden_cheesecake")
        self.assertTrue(plan_sat["overall_stats"]["planning_for_saturday"])
        self.assertGreaterEqual(plan_sat["overall_stats"]["vendors_covered_today"], 1)

        # On Wednesday in auto mode: Darcy is absent from town
        plan_wed = plan_max_relationship(
            save=save_wed,
            npc_gift_definitions=self.mock_npcs,
            item_metadata=self.mock_meta,
            mode="auto",
        )
        self.assertNotIn("darcy", plan_wed["target_npcs"])
        self.assertNotIn("darcy", plan_wed["covered_npcs"])
        self.assertFalse(plan_wed["overall_stats"]["planning_for_saturday"])
        self.assertEqual(plan_wed["overall_stats"]["vendors_covered_today"], 0)
        self.assertIn("Darcy", plan_wed["overall_stats"]["not_present_npcs"])

        # Mode override: mode="saturday" on Wednesday forces vendor presence
        plan_override = plan_max_relationship(
            save=save_wed,
            npc_gift_definitions=self.mock_npcs,
            item_metadata=self.mock_meta,
            mode="saturday",
        )
        self.assertIn("darcy", plan_override["target_npcs"])
        self.assertGreaterEqual(plan_override["overall_stats"]["vendors_covered_today"], 1)

    # ==========================================================================
    # PLUS: Package __init__.py Export Verification Test
    # ==========================================================================

    def test_plan_max_rel_package_init_exports(self):
        """
        Plus: Package __init__.py and gift_planner.py export verification.
        Verifies plan_max_relationship is properly exported in __all__ and callable
        from both fom_planner package and the root gift_planner module.
        """
        import fom_planner
        import gift_planner

        # Verify fom_planner package export
        self.assertTrue(hasattr(fom_planner, "plan_max_relationship"))
        self.assertIn("plan_max_relationship", fom_planner.__all__)
        self.assertTrue(callable(fom_planner.plan_max_relationship))

        # Verify backward-compatibility root module export
        self.assertTrue(hasattr(gift_planner, "plan_max_relationship"))
        self.assertIn("plan_max_relationship", gift_planner.__all__)
        self.assertTrue(callable(gift_planner.plan_max_relationship))

        # Verify both refer to the identical function object in memory
        self.assertIs(fom_planner.plan_max_relationship, gift_planner.plan_max_relationship)

    # ==========================================================================
    # SCENARIOS 12-18: Crafting Integration Tests for Max-Relationship Strategy
    # ==========================================================================

    def test_plan_max_rel_basic_crafting_assignment(self):
        """
        Scenario 12: Basic crafting assignment (+20 pts).
        Verifies that when an NPC loves an item with 0 in stock, but craftable
        from ingredients, plan_max_relationship assigns it with LOVE pref tier,
        awards 20 points, sets CRAFT status and '🔨 CRAFT' badge in the bag plan.
        """
        npcs = {
            "adeline": {
                "name": "Adeline",
                "loved": ["bread"],
                "liked": [],
            }
        }
        # Bread requires 2 flour (mock_recipes)
        inventory = {"flour": 2}
        plan = plan_max_relationship(
            npc_gift_definitions=npcs,
            item_metadata=self.mock_meta,
            inventory=inventory,
            recipes=self.mock_recipes,
            force_all_npcs=True,
        )

        progress = plan["npc_progress"]["adeline"]
        self.assertEqual(progress["assigned_item_id"], "bread")
        self.assertEqual(progress["assigned_pref_type"], "LOVE")
        self.assertEqual(progress["assigned_points"], 20)

        bag = plan["bag_plan"]
        self.assertEqual(len(bag), 1)
        self.assertEqual(bag[0]["item_id"], "bread")
        self.assertEqual(bag[0]["quantity_to_pack"], 1)
        self.assertEqual(bag[0]["status"], "CRAFT")
        self.assertEqual(bag[0]["availability_tier"], int(AvailabilityTier.CRAFT))
        self.assertEqual(bag[0]["status_badge"], "🔨 CRAFT")
        self.assertTrue(len(bag[0]["crafting_chain"]) > 0)
        self.assertEqual(plan["overall_stats"]["total_relationship_points"], 20)

    def test_plan_max_rel_have_preferred_over_craft(self):
        """
        Scenario 13: HAVE preferred over CRAFT within the same tier.
        When an NPC loves both an in-stock item and a craftable item, the planner
        must assign the in-stock item to preserve materials.
        """
        npcs = {
            "adeline": {
                "name": "Adeline",
                "loved": ["golden_cheesecake", "bread"],
                "liked": [],
            }
        }
        # 1 golden_cheesecake in stock, plus 10 flour (enough to craft 5 bread)
        inventory = {"golden_cheesecake": 1, "flour": 10}
        plan = plan_max_relationship(
            npc_gift_definitions=npcs,
            item_metadata=self.mock_meta,
            inventory=inventory,
            recipes=self.mock_recipes,
            force_all_npcs=True,
        )

        progress = plan["npc_progress"]["adeline"]
        self.assertEqual(progress["assigned_item_id"], "golden_cheesecake")
        self.assertEqual(progress["assigned_pref_type"], "LOVE")
        self.assertEqual(progress["assigned_points"], 20)

        bag = plan["bag_plan"]
        self.assertEqual(len(bag), 1)
        self.assertEqual(bag[0]["item_id"], "golden_cheesecake")
        self.assertEqual(bag[0]["status"], "HAVE")
        self.assertEqual(bag[0]["status_badge"], "📦 HAVE")

    def test_plan_max_rel_shared_ingredient_deduction(self):
        """
        Scenario 14: Shared ingredient deduction across multiple craft assignments.
        Adeline loves bread (needs 2 flour), March loves strawberry_shortcake (needs 1 flour).
        With only 2 flour available, only one NPC can receive their crafted love gift.
        """
        npcs = {
            "adeline": {
                "name": "Adeline",
                "loved": ["bread"],
                "liked": [],
            },
            "march": {
                "name": "March",
                "loved": ["strawberry_shortcake"],
                "liked": [],
            },
        }
        # 2 flour, 10 strawberries, 10 sugar
        inventory = {"flour": 2, "strawberry": 10, "sugar": 10}
        plan = plan_max_relationship(
            npc_gift_definitions=npcs,
            item_metadata=self.mock_meta,
            inventory=inventory,
            recipes=self.mock_recipes,
            force_all_npcs=True,
        )

        stats = plan["overall_stats"]
        # Exactly 1 NPC covered, not both
        self.assertEqual(stats["covered_npcs_count"], 1)
        self.assertEqual(stats["total_relationship_points"], 20)

        adeline_assigned = plan["npc_progress"]["adeline"]["assigned_item_id"]
        march_assigned = plan["npc_progress"]["march"]["assigned_item_id"]
        # One got assigned, the other is None
        self.assertTrue((adeline_assigned is not None) ^ (march_assigned is not None))

    def test_plan_max_rel_mrv_ordering_with_crafting(self):
        """
        Scenario 15: Minimum Remaining Values (MRV) ordering during crafting sub-pass.
        Constrained NPC has 1 craftable option (cornmeal), Flexible NPC has 2 (bread, cornmeal).
        MRV must allocate the constrained option to Constrained NPC first, allowing both to be covered.
        """
        npcs = {
            "constrained": {
                "name": "Constrained NPC",
                "loved": ["cornmeal"],
                "liked": [],
            },
            "flexible": {
                "name": "Flexible NPC",
                "loved": ["bread", "cornmeal"],
                "liked": [],
            },
        }
        # Enough materials for 1 cornmeal (1 corn) and 1 bread (2 flour)
        inventory = {"corn": 1, "flour": 2}
        plan = plan_max_relationship(
            npc_gift_definitions=npcs,
            item_metadata=self.mock_meta,
            inventory=inventory,
            recipes=self.mock_recipes,
            force_all_npcs=True,
        )

        progress = plan["npc_progress"]
        self.assertEqual(progress["constrained"]["assigned_item_id"], "cornmeal")
        self.assertEqual(progress["flexible"]["assigned_item_id"], "bread")
        self.assertEqual(plan["overall_stats"]["covered_npcs_count"], 2)
        self.assertEqual(plan["overall_stats"]["total_relationship_points"], 40)

    def test_plan_max_rel_infusion_pool_sync_after_crafting(self):
        """
        Scenario 16: Infusion pool synchronization after crafting.
        When ingredients are consumed to craft a specific gift, any overlapping counts
        in the lovable/likable infusion pools must be clamped down so they cannot be
        double-spent in subsequent universal gift stages.
        """
        npcs = {
            "adeline": {
                "name": "Adeline",
                "loved": ["bread"],  # Needs 2 flour
                "liked": [],
            },
            "balor": {
                "name": "Balor",
                "loved": ["rare_gem"],  # Absent
                "liked": [],
            },
        }
        # 2 flour in physical inventory, which was also marked as lovable infusion
        inventory = {"flour": 2}
        infused = {
            "lovable": [{"item_id": "flour", "count": 2, "location": "bag"}],
            "likable": [],
        }
        plan = plan_max_relationship(
            npc_gift_definitions=npcs,
            item_metadata=self.mock_meta,
            inventory=inventory,
            infused_items=infused,
            recipes=self.mock_recipes,
            force_all_npcs=True,
        )

        # Adeline crafts bread, consuming the 2 flour
        self.assertEqual(plan["npc_progress"]["adeline"]["assigned_item_id"], "bread")
        # Balor cannot receive the consumed flour as a universal love gift
        self.assertIsNone(plan["npc_progress"]["balor"]["assigned_item_id"])
        self.assertEqual(plan["overall_stats"]["covered_npcs_count"], 1)
        self.assertEqual(plan["overall_stats"]["total_relationship_points"], 20)

    def test_plan_max_rel_bag_plan_craft_badge(self):
        """
        Scenario 17: Bag plan crafting metadata and badges.
        Verifies CRAFT items receive the '🔨 CRAFT' badge, detailed crafting chain,
        and max_craftable metadata, while HAVE items keep '📦 HAVE' and empty chain.
        """
        npcs = {
            "adeline": {
                "name": "Adeline",
                "loved": ["bread"],
                "liked": [],
            },
            "march": {
                "name": "March",
                "loved": ["strawberry"],
                "liked": [],
            },
        }
        # 5 strawberries in stock (HAVE), 2 flour for bread (CRAFT)
        inventory = {"strawberry": 5, "flour": 2}
        plan = plan_max_relationship(
            npc_gift_definitions=npcs,
            item_metadata=self.mock_meta,
            inventory=inventory,
            recipes=self.mock_recipes,
            force_all_npcs=True,
        )

        bag = plan["bag_plan"]
        self.assertEqual(len(bag), 2)
        slot_by_id = {b["item_id"]: b for b in bag}

        # Strawberry slot (in stock)
        self.assertEqual(slot_by_id["strawberry"]["status"], "HAVE")
        self.assertEqual(slot_by_id["strawberry"]["status_badge"], "📦 HAVE")
        self.assertEqual(slot_by_id["strawberry"]["crafting_chain"], "")

        # Bread slot (crafted)
        self.assertEqual(slot_by_id["bread"]["status"], "CRAFT")
        self.assertEqual(slot_by_id["bread"]["status_badge"], "🔨 CRAFT")
        self.assertIn("Flour", slot_by_id["bread"]["crafting_chain"])
        self.assertGreaterEqual(slot_by_id["bread"]["max_craftable"], 1)

    def test_plan_max_rel_mixed_have_and_craft_same_item(self):
        """
        Scenario 18: Mixed HAVE + CRAFT for the same item across multiple NPCs.
        Verifies that when 3 NPCs love the same item, and the player has 1 in stock
        plus materials to craft 2 more, all 3 NPCs receive the item, and the bag plan
        displays the composite '🔨 HAVE (1) + CRAFT (2)' status badge.
        """
        npcs = {
            "adeline": {
                "name": "Adeline",
                "loved": ["bread"],
                "liked": [],
            },
            "march": {
                "name": "March",
                "loved": ["bread"],
                "liked": [],
            },
            "balor": {
                "name": "Balor",
                "loved": ["bread"],
                "liked": [],
            },
        }
        # 1 bread in stock, plus 4 flour (enough to craft 2 bread)
        inventory = {"bread": 1, "flour": 4}
        plan = plan_max_relationship(
            npc_gift_definitions=npcs,
            item_metadata=self.mock_meta,
            inventory=inventory,
            recipes=self.mock_recipes,
            force_all_npcs=True,
        )

        # All 3 NPCs receive bread (+20 pts each, 60 pts total)
        self.assertEqual(plan["npc_progress"]["adeline"]["assigned_item_id"], "bread")
        self.assertEqual(plan["npc_progress"]["march"]["assigned_item_id"], "bread")
        self.assertEqual(plan["npc_progress"]["balor"]["assigned_item_id"], "bread")
        self.assertEqual(plan["overall_stats"]["total_relationship_points"], 60)
        self.assertEqual(plan["overall_stats"]["covered_npcs_count"], 3)

        # Exactly 1 bag slot with composite badge
        bag = plan["bag_plan"]
        self.assertEqual(len(bag), 1)
        self.assertEqual(bag[0]["item_id"], "bread")
        self.assertEqual(bag[0]["quantity_to_pack"], 3)
        self.assertEqual(bag[0]["status"], "CRAFT")
        self.assertEqual(bag[0]["status_badge"], "🔨 HAVE (1) + CRAFT (2)")
        self.assertEqual(len(bag[0]["all_recipients_today"]), 3)


if __name__ == "__main__":
    unittest.main()




