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
        print_terminal_plan,
        export_plan_to_csv,
        export_plan_to_excel,
        compute_focus_suggestions,
        resolve_root_raw_materials,
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
        print_terminal_plan,
        export_plan_to_csv,
        export_plan_to_excel,
        compute_focus_suggestions,
        resolve_root_raw_materials,
        ITEM_LOCATIONS,
    )

if OPENPYXL_AVAILABLE:
    import openpyxl


# ==============================================================================
# SYNTHETIC TEST FIXTURE GENERATORS
# ==============================================================================

def create_mock_slot(item_id: Optional[str], count: int) -> Dict[str, Any]:
    """Creates a standard FoM inventory slot dictionary."""
    if item_id is None or count <= 0:
        return {"count": 0, "item": None, "required_tags": []}
    return {
        "count": float(count),
        "item": {"item_id": str(item_id)},
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

    bag_slots = []
    if bag_items:
        for iid, cnt in bag_items.items():
            bag_slots.append(create_mock_slot(iid, cnt))
    while len(bag_slots) < 30:
        bag_slots.append(create_mock_slot(None, 0))

    player_data = {
        "name": player_name,
        "farm_name": farm_name,
        "inventory": bag_slots,
    }
    entries["player"] = json.dumps(player_data)

    npcs_data: Dict[str, Any] = {}
    all_34_npc_ids = [
        "adeline", "balor", "celine", "darcy", "dell", "dozy", "eiland", "elsie", "errol",
        "hayden", "hemlock", "henrietta", "holt", "josephine", "juniper", "landen", "louis",
        "luc", "maple", "march", "merri", "nora", "olric", "reina", "ryis", "seridia",
        "stillwell", "taliferro", "terithia", "valen", "vera", "wheedle", "zorel", "caldarus"
    ]
    if gifted_npcs is None:
        gifted_npcs = {}

    is_animal_fest = (season.lower() == "winter" and day == 10)
    for nid in all_34_npc_ids:
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


if __name__ == "__main__":
    unittest.main()



