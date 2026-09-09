"""
tests/test_exporters.py

Exhaustive tests for terminal, CSV, and Excel exporters:
- Terminal plan formatting (infused banner, badges, relationship impact, max-relationship banner)
- CSV export integrity (columns, status badges, recipient lists, unicode)
- Excel workbook export (formatting, multi-sheet preservation, openpyxl resilience)
"""

import csv
import io
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from fom_planner.constants import SATURDAY_MARKET_VENDORS
from fom_planner.exporters.csv_export import export_plan_to_csv
from fom_planner.exporters.excel_export import OPENPYXL_AVAILABLE, export_plan_to_excel
from fom_planner.exporters.terminal import _format_infused_summary, print_terminal_plan
from fom_planner.models import InGameDate, SaveData
from fom_planner.optimizer import plan_max_relationship


def make_mock_slot(
    item_id: Optional[str] = None,
    count: Any = 1,
    infusion: Optional[str] = None,
) -> Dict[str, Any]:
    """Creates a mock inventory slot dictionary."""
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
    day: int = 1,
    present_npcs: Optional[List[str]] = None,
    giftable_npcs: Optional[List[str]] = None,
    heart_points: Optional[Dict[str, float]] = None,
) -> SaveData:
    """Creates a fully functional synthetic SaveData instance."""
    season_idx = {"spring": 0, "summer": 1, "autumn": 2, "fall": 2, "winter": 3}.get(season.lower(), 0)
    cal_days = (year - 1) * 112 + season_idx * 28 + (day - 1)
    cal_time = cal_days * 86400

    raw: Dict[str, str] = {
        "header": json.dumps({
            "name": "ChallengerHero",
            "farm_name": "AdversarialFarm",
            "playtime": 7200.0,
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

    npcs_dict: Dict[str, Any] = {}
    is_sat = (day % 7 == 6)

    for nid in all_34_npcs:
        is_vendor = nid in SATURDAY_MARKET_VENDORS
        in_town = (nid in present_npcs) if present_npcs is not None else (is_sat or not is_vendor)
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

    if chest_locations is not None:
        raw["locations"] = json.dumps({
            loc: [{"grid": grid} for grid in grids]
            for loc, grids in chest_locations.items()
        })
    else:
        raw["locations"] = json.dumps({})

    return SaveData(file_path=Path("adversarial_test.sav"), entries=raw)


def capture_terminal_output(save: Optional[SaveData], plan_results: dict) -> str:
    """Helper to capture sys.stdout of print_terminal_plan."""
    captured = io.StringIO()
    with patch("sys.stdout", captured):
        print_terminal_plan(save, plan_results)
    return captured.getvalue()


# ==============================================================================
# 1. EMPTY PLAN & 0 RELATIONSHIP POINTS TESTS
# ==============================================================================

class TestTerminalPlanEmptyAndZeroPoints(unittest.TestCase):
    """Stress tests print_terminal_plan with empty plan and 0 relationship points."""

    def test_terminal_plan_completely_empty_results(self):
        """Empty bag plan, zero target NPCs, zero covered NPCs, zero points."""
        plan_results = {
            "bag_plan": [],
            "npc_progress": {},
            "covered_npcs": set(),
            "target_npcs": set(),
            "overall_stats": {
                "strategy": "max-relationship",
                "total_relationship_points": 0,
                "game_given_loved": 0,
                "game_total_loved": 0,
                "game_given_liked": 0,
                "game_total_liked": 0,
                "game_given_total": 0,
                "game_total_preferences": 0,
                "remaining_unique_items": 0,
                "mode": "weekday",
                "max_slots": 20,
                "covered_npcs_count": 0,
                "target_npcs_count": 0,
                "vendors_covered_today": 0,
                "today_loved_completed": 0,
                "today_liked_completed": 0,
                "locked_npcs": [],
                "ungiftable_npcs": [],
            },
            "infused_items": {"lovable": [], "likable": []},
        }
        out = capture_terminal_output(None, plan_results)
        self.assertIn("TOTAL RELATIONSHIP POINTS EARNED TODAY: +0 pts", out)
        self.assertIn("💞 RELATIONSHIP IMPACT: +0 total points earned today across 0 NPCs!", out)
        self.assertIn("Loved: 0 gifts (+20 pts each) | Liked: 0 gifts (+10 pts each)", out)
        self.assertIn("OPTIMAL BAG LOADOUT (0/20 slots → covers 0/0 NPCs):", out)
        # Should not falsely claim 100% coverage when target_npcs_count == 0
        self.assertNotIn("100% NPC coverage achieved!", out)
        # Check no ZeroDivisionError in progress formatting (0/0 preferences)
        self.assertIn("Loved Gifts: 0/0 (0.0%)", out)
        self.assertIn("Liked Gifts: 0/0 (0.0%)", out)
        self.assertIn("Total Preferences: 0/0 (0.0%)", out)

    def test_terminal_plan_zero_points_with_targets_uncovered(self):
        """Target NPCs exist, but empty inventory results in 0 gifts packed and 0 points."""
        npc_progress = {
            "adeline": {"name": "Adeline", "is_vendor": False, "is_unlocked": True},
            "march": {"name": "March", "is_vendor": False, "is_unlocked": True},
        }
        plan_results = {
            "bag_plan": [],
            "npc_progress": npc_progress,
            "covered_npcs": set(),
            "target_npcs": {"adeline", "march"},
            "overall_stats": {
                "strategy": "max-relationship",
                "total_relationship_points": 0,
                "game_given_loved": 0,
                "game_total_loved": 20,
                "game_given_liked": 0,
                "game_total_liked": 40,
                "game_given_total": 0,
                "game_total_preferences": 60,
                "remaining_unique_items": 30,
                "mode": "weekday",
                "max_slots": 20,
                "covered_npcs_count": 0,
                "target_npcs_count": 2,
                "vendors_covered_today": 0,
                "today_loved_completed": 0,
                "today_liked_completed": 0,
                "locked_npcs": [],
                "ungiftable_npcs": [],
            },
        }
        out = capture_terminal_output(None, plan_results)
        self.assertIn("TOTAL RELATIONSHIP POINTS EARNED TODAY: +0 pts", out)
        self.assertIn("💞 RELATIONSHIP IMPACT: +0 total points earned today across 0 NPCs!", out)
        self.assertIn("OPTIMAL BAG LOADOUT (0/20 slots → covers 0/2 NPCs):", out)
        self.assertNotIn("100% NPC coverage achieved!", out)

    def test_terminal_plan_all_npcs_already_gifted_today(self):
        """All present NPCs have already received gifts today, resulting in ungiftable warning."""
        plan_results = {
            "bag_plan": [],
            "npc_progress": {},
            "covered_npcs": set(),
            "target_npcs": set(),
            "overall_stats": {
                "strategy": "max-relationship",
                "total_relationship_points": 0,
                "game_given_loved": 5,
                "game_total_loved": 10,
                "game_given_liked": 10,
                "game_total_liked": 20,
                "game_given_total": 15,
                "game_total_preferences": 30,
                "remaining_unique_items": 15,
                "mode": "weekday",
                "max_slots": 20,
                "covered_npcs_count": 0,
                "target_npcs_count": 0,
                "vendors_covered_today": 0,
                "today_loved_completed": 0,
                "today_liked_completed": 0,
                "locked_npcs": [],
                "ungiftable_npcs": ["Adeline", "March", "Celine"],
            },
        }
        out = capture_terminal_output(None, plan_results)
        self.assertIn("⚠️  ALREADY GIFTED TODAY (3 NPCs): Adeline, March, Celine", out)
        self.assertIn("TOTAL RELATIONSHIP POINTS EARNED TODAY: +0 pts", out)


# ==============================================================================
# 2. SAVE=NONE RESILIENCE TESTS
# ==============================================================================

class TestTerminalPlanSaveNoneResilience(unittest.TestCase):
    """Stress tests print_terminal_plan with save=None across all modes and configurations."""

    def test_save_none_default_fallbacks(self):
        """Verify fallback player name, farm name, calendar date, and save session name."""
        plan_results = {
            "bag_plan": [],
            "npc_progress": {},
            "covered_npcs": set(),
            "target_npcs": set(),
            "overall_stats": {
                "strategy": "max-relationship",
                "total_relationship_points": 0,
                "game_given_loved": 0,
                "game_total_loved": 10,
                "game_given_liked": 0,
                "game_total_liked": 20,
                "game_given_total": 0,
                "game_total_preferences": 30,
                "remaining_unique_items": 15,
                "mode": "weekday",
                "max_slots": 20,
                "covered_npcs_count": 0,
                "target_npcs_count": 0,
                "vendors_covered_today": 0,
                "today_loved_completed": 0,
                "today_liked_completed": 0,
                "locked_npcs": [],
                "ungiftable_npcs": [],
            },
        }
        out = capture_terminal_output(None, plan_results)
        self.assertIn("Player: Player @ Farm", out)
        self.assertIn("Year 1, Spring Day 1 (Monday, 06:00)", out)
        self.assertIn("Save: active_session", out)
        # INVENTORY & STORAGE STATUS banner requires save.get_all_available_items, so must not appear
        self.assertNotIn("📦 INVENTORY & STORAGE STATUS:", out)

    def test_save_none_saturday_mode_and_market_only(self):
        """Verify save=None handles Saturday and market-only mode displays cleanly."""
        for mode in ("saturday", "market-only"):
            plan_results = {
                "bag_plan": [],
                "npc_progress": {
                    "darcy": {"name": "Darcy", "is_vendor": True, "is_unlocked": True},
                },
                "covered_npcs": set(),
                "target_npcs": set(),
                "overall_stats": {
                    "strategy": "max-relationship",
                    "total_relationship_points": 0,
                    "game_given_loved": 0,
                    "game_total_loved": 10,
                    "game_given_liked": 0,
                    "game_total_liked": 20,
                    "game_given_total": 0,
                    "game_total_preferences": 30,
                    "remaining_unique_items": 15,
                    "mode": mode,
                    "max_slots": 20,
                    "covered_npcs_count": 0,
                    "target_npcs_count": 0,
                    "vendors_covered_today": 0,
                    "today_loved_completed": 0,
                    "today_liked_completed": 0,
                    "locked_npcs": [],
                    "ungiftable_npcs": [],
                },
            }
            out = capture_terminal_output(None, plan_results)
            if mode == "saturday":
                self.assertIn("PLANNING FOR SATURDAY MARKET", out)
            else:
                self.assertIn("PLANNING FOR SATURDAY MARKET VENDORS ONLY", out)

    def test_save_none_with_animal_festival_mode(self):
        """Verify save=None handles animal festival date / stats flag cleanly."""
        plan_results = {
            "bag_plan": [],
            "npc_progress": {
                "merri": {"name": "Merri", "is_vendor": True, "is_unlocked": True},
                "louis": {"name": "Louis", "is_vendor": True, "is_unlocked": True},
            },
            "covered_npcs": set(),
            "target_npcs": set(),
            "overall_stats": {
                "strategy": "max-relationship",
                "total_relationship_points": 0,
                "game_given_loved": 0,
                "game_total_loved": 10,
                "game_given_liked": 0,
                "game_total_liked": 20,
                "game_given_total": 0,
                "game_total_preferences": 30,
                "remaining_unique_items": 15,
                "mode": "weekday",
                "is_animal_festival": True,
                "max_slots": 20,
                "covered_npcs_count": 0,
                "target_npcs_count": 0,
                "vendors_covered_today": 0,
                "today_loved_completed": 0,
                "today_liked_completed": 0,
                "locked_npcs": [],
                "ungiftable_npcs": [],
            },
        }
        out = capture_terminal_output(None, plan_results)
        self.assertIn("TODAY IS ANIMAL FESTIVAL DAY! (Winter 10)", out)
        self.assertIn("Merri & Louis receive priority boost", out)


# ==============================================================================
# 3. POPULATED INFUSED ITEMS TESTS
# ==============================================================================

class TestTerminalPlanInfusedItemsFormatting(unittest.TestCase):
    """Stress tests print_terminal_plan with populated lovable and likable infused dishes."""

    def test_both_lovable_and_likable_dishes_displayed(self):
        """Simultaneous lovable and likable dishes are formatted and alphabetized correctly."""
        plan_results = {
            "bag_plan": [],
            "npc_progress": {},
            "covered_npcs": set(),
            "target_npcs": set(),
            "overall_stats": {
                "strategy": "max-relationship",
                "total_relationship_points": 0,
                "game_given_loved": 0,
                "game_total_loved": 10,
                "game_given_liked": 0,
                "game_total_liked": 20,
                "game_given_total": 0,
                "game_total_preferences": 30,
                "remaining_unique_items": 15,
                "mode": "weekday",
                "max_slots": 20,
                "covered_npcs_count": 0,
                "target_npcs_count": 0,
                "vendors_covered_today": 0,
                "today_loved_completed": 0,
                "today_liked_completed": 0,
                "locked_npcs": [],
                "ungiftable_npcs": [],
            },
            "infused_items": {
                "lovable": [
                    {"item_id": "berry_tart", "count": 1, "location": "bag"},
                    {"item_id": "apple_pie", "count": 2, "location": "chest"},
                ],
                "likable": [
                    {"item_id": "vegetable_soup", "count": 3, "location": "bag"},
                    {"item_id": "grilled_fish", "count": 2, "location": "farm"},
                ],
            },
        }
        out = capture_terminal_output(None, plan_results)
        self.assertIn("🔮 DETECTED INFUSED ITEMS (Cooking Perk):", out)
        # Note: Alphabetically sorted items inside summary string
        self.assertIn("Lovable Dishes (✨ Universal Love, +20 pts): 3 total — apple_pie (x2), berry_tart (x1)", out)
        self.assertIn("Likable Dishes (🌟 Universal Like, +10 pts): 5 total — grilled_fish (x2), vegetable_soup (x3)", out)

    def test_infused_items_alternate_spelling_likeable(self):
        """Supports alternate spelling 'likeable' in infused_items dictionary."""
        plan_results = {
            "bag_plan": [],
            "npc_progress": {},
            "covered_npcs": set(),
            "target_npcs": set(),
            "overall_stats": {
                "strategy": "max-relationship",
                "total_relationship_points": 0,
                "game_given_loved": 0,
                "game_total_loved": 10,
                "game_given_liked": 0,
                "game_total_liked": 20,
                "game_given_total": 0,
                "game_total_preferences": 30,
                "remaining_unique_items": 15,
                "mode": "weekday",
                "max_slots": 20,
                "covered_npcs_count": 0,
                "target_npcs_count": 0,
                "vendors_covered_today": 0,
                "today_loved_completed": 0,
                "today_liked_completed": 0,
                "locked_npcs": [],
                "ungiftable_npcs": [],
            },
            "infused_items": {
                "lovable": [],
                "likeable": [{"item_id": "herbal_tea", "count": 4}],
            },
        }
        out = capture_terminal_output(None, plan_results)
        self.assertIn("Likable Dishes (🌟 Universal Like, +10 pts): 4 total — herbal_tea (x4)", out)

    def test_infused_items_dict_mapping_format(self):
        """_format_infused_summary defensively accepts dict mapping {item_id: count}."""
        plan_results = {
            "bag_plan": [],
            "npc_progress": {},
            "covered_npcs": set(),
            "target_npcs": set(),
            "overall_stats": {
                "strategy": "max-relationship",
                "total_relationship_points": 0,
                "game_given_loved": 0,
                "game_total_loved": 10,
                "game_given_liked": 0,
                "game_total_liked": 20,
                "game_given_total": 0,
                "game_total_preferences": 30,
                "remaining_unique_items": 15,
                "mode": "weekday",
                "max_slots": 20,
                "covered_npcs_count": 0,
                "target_npcs_count": 0,
                "vendors_covered_today": 0,
                "today_loved_completed": 0,
                "today_liked_completed": 0,
                "locked_npcs": [],
                "ungiftable_npcs": [],
            },
            "infused_items": {
                "lovable": {"apple_pie": 3, "cherry_cobbler": 2},
                "likable": {"herbal_tea": 5},
            },
        }
        out = capture_terminal_output(None, plan_results)
        self.assertIn("Lovable Dishes (✨ Universal Love, +20 pts): 5 total — apple_pie (x3), cherry_cobbler (x2)", out)
        self.assertIn("Likable Dishes (🌟 Universal Like, +10 pts): 5 total — herbal_tea (x5)", out)

    def test_infused_items_extracted_from_save_when_plan_results_lacks_it(self):
        """When plan_results lacks 'infused_items', extracts from save.get_infused_items()."""
        save = make_synthetic_save(
            bag_slots=[
                make_mock_slot("apple_pie", 2, infusion="lovable"),
                make_mock_slot("vegetable_soup", 3, infusion="likable"),
            ]
        )
        plan_results = {
            "bag_plan": [],
            "npc_progress": {},
            "covered_npcs": set(),
            "target_npcs": set(),
            "overall_stats": {
                "strategy": "max-relationship",
                "total_relationship_points": 0,
                "game_given_loved": 0,
                "game_total_loved": 10,
                "game_given_liked": 0,
                "game_total_liked": 20,
                "game_given_total": 0,
                "game_total_preferences": 30,
                "remaining_unique_items": 15,
                "mode": "weekday",
                "max_slots": 20,
                "covered_npcs_count": 0,
                "target_npcs_count": 0,
                "vendors_covered_today": 0,
                "today_loved_completed": 0,
                "today_liked_completed": 0,
                "locked_npcs": [],
                "ungiftable_npcs": [],
            },
            # Note: No 'infused_items' key here
        }
        out = capture_terminal_output(save, plan_results)
        self.assertIn("🔮 DETECTED INFUSED ITEMS (Cooking Perk):", out)
        self.assertIn("Lovable Dishes (✨ Universal Love, +20 pts): 2 total — apple_pie (x2)", out)
        self.assertIn("Likable Dishes (🌟 Universal Like, +10 pts): 3 total — vegetable_soup (x3)", out)

    def test_format_infused_summary_adversarial_types(self):
        """Stress _format_infused_summary with negative counts, floats, strings, and whitespace."""
        # Non-numeric / corrupted count
        cnt, s = _format_infused_summary([{"item_id": "apple_pie", "count": "bad_count"}])
        self.assertEqual(cnt, 1)  # Fallback to 1
        self.assertIn("apple_pie (x1)", s)

        # Zero or negative counts should be excluded
        cnt, s = _format_infused_summary([
            {"item_id": "apple_pie", "count": 0},
            {"item_id": "berry_tart", "count": -5},
            {"item_id": "cherry_tart", "count": 2},
        ])
        self.assertEqual(cnt, 2)
        self.assertEqual(s, "cherry_tart (x2)")

        # Dict mapping with non-integer values
        cnt, s = _format_infused_summary({"soup": 3.7, "tea": -1, "bread": 0})
        self.assertEqual(cnt, 4)
        self.assertEqual(s, "soup (x4)")

        # Non-iterable types should return (0, "")
        self.assertEqual(_format_infused_summary(12345), (0, ""))
        self.assertEqual(_format_infused_summary(None), (0, ""))


# ==============================================================================
# 4. ALL 4 RECIPIENT PREFERENCE BADGES TESTS
# ==============================================================================

class TestTerminalPlanRecipientBadges(unittest.TestCase):
    """Stress tests print_terminal_plan with all 4 recipient preference badges."""

    def test_all_four_badges_rendered_in_bag_table(self):
        """Verifies [💖 LOVE], [✨ UNIV. LOVE], [💙 LIKE], [🌟 UNIV. LIKE] in terminal output."""
        plan_results = {
            "bag_plan": [
                {
                    "slot": 1,
                    "quantity_to_pack": 1,
                    "item_name": "Deluxe Sandwich",
                    "status_badge": "📦 HAVE",
                    "all_recipients_today": [{"name": "March", "pref": "LOVE", "is_vendor": False}],
                },
                {
                    "slot": 2,
                    "quantity_to_pack": 1,
                    "item_name": "Apple Pie (Infused)",
                    "status_badge": "📦 HAVE",
                    "all_recipients_today": [{"name": "Adeline", "pref": "UNIV_LOVE", "is_vendor": False}],
                },
                {
                    "slot": 3,
                    "quantity_to_pack": 1,
                    "item_name": "Copper Ingot",
                    "status_badge": "📦 HAVE",
                    "all_recipients_today": [{"name": "Celine", "pref": "LIKE", "is_vendor": False}],
                },
                {
                    "slot": 4,
                    "quantity_to_pack": 1,
                    "item_name": "Vegetable Soup (Infused)",
                    "status_badge": "📦 HAVE",
                    "all_recipients_today": [{"name": "Darcy", "pref": "UNIV_LIKE", "is_vendor": True}],
                },
            ],
            "npc_progress": {},
            "covered_npcs": {"march", "adeline", "celine", "darcy"},
            "target_npcs": {"march", "adeline", "celine", "darcy"},
            "overall_stats": {
                "strategy": "max-relationship",
                "total_relationship_points": 60,
                "game_given_loved": 2,
                "game_total_loved": 10,
                "game_given_liked": 2,
                "game_total_liked": 20,
                "game_given_total": 4,
                "game_total_preferences": 30,
                "remaining_unique_items": 15,
                "mode": "saturday",
                "max_slots": 20,
                "covered_npcs_count": 4,
                "target_npcs_count": 4,
                "vendors_covered_today": 1,
                "today_loved_completed": 2,
                "today_liked_completed": 2,
                "locked_npcs": [],
                "ungiftable_npcs": [],
            },
        }
        out = capture_terminal_output(None, plan_results)
        self.assertIn("[💖 LOVE] March", out)
        self.assertIn("[✨ UNIV. LOVE] Adeline", out)
        self.assertIn("[💙 LIKE] Celine", out)
        self.assertIn("[🌟 UNIV. LIKE] Darcy [Market]", out)
        # Relationship points summary
        self.assertIn("TOTAL RELATIONSHIP POINTS EARNED TODAY: +60 pts", out)
        self.assertIn("💞 RELATIONSHIP IMPACT: +60 total points earned today across 4 NPCs! (including 1 Saturday Market vendors)", out)
        self.assertIn("Loved: 2 gifts (+20 pts each) | Liked: 2 gifts (+10 pts each)", out)
        self.assertIn("✨ 100% NPC coverage achieved! You have 16 extra bag slots free for tools/foraging.", out)

    def test_mixed_badges_in_single_bag_slot(self):
        """Multiple recipients with different preference tiers packed into the same bag slot."""
        plan_results = {
            "bag_plan": [
                {
                    "slot": 1,
                    "quantity_to_pack": 4,
                    "item_name": "Multi-Preference Feast",
                    "status_badge": "📦 HAVE",
                    "all_recipients_today": [
                        {"name": "Adeline", "pref": "LOVE", "is_vendor": False},
                        {"name": "Balor", "pref": "UNIV_LOVE", "is_vendor": False},
                        {"name": "Celine", "pref": "LIKE", "is_vendor": False},
                        {"name": "Darcy", "pref": "UNIV_LIKE", "is_vendor": True},
                    ],
                }
            ],
            "npc_progress": {},
            "covered_npcs": {"adeline", "balor", "celine", "darcy"},
            "target_npcs": {"adeline", "balor", "celine", "darcy"},
            "overall_stats": {
                "strategy": "max-relationship",
                "total_relationship_points": 60,
                "game_given_loved": 2,
                "game_total_loved": 10,
                "game_given_liked": 2,
                "game_total_liked": 20,
                "game_given_total": 4,
                "game_total_preferences": 30,
                "remaining_unique_items": 15,
                "mode": "saturday",
                "max_slots": 20,
                "covered_npcs_count": 4,
                "target_npcs_count": 4,
                "vendors_covered_today": 1,
                "today_loved_completed": 2,
                "today_liked_completed": 2,
                "locked_npcs": [],
                "ungiftable_npcs": [],
            },
        }
        out = capture_terminal_output(None, plan_results)
        expected_recipients_line = "[💖 LOVE] Adeline, [✨ UNIV. LOVE] Balor, [💙 LIKE] Celine, [🌟 UNIV. LIKE] Darcy [Market]"
        self.assertIn(expected_recipients_line, out)

    def test_badges_case_insensitivity_and_aliases(self):
        """Preference aliases (universal_love, universal_like, lowercase) resolve to correct badges."""
        plan_results = {
            "bag_plan": [
                {
                    "slot": 1,
                    "quantity_to_pack": 4,
                    "item_name": "Item",
                    "status_badge": "📦 HAVE",
                    "all_recipients_today": [
                        {"name": "P1", "pref": "love", "is_vendor": False},
                        {"name": "P2", "pref": "universal_love", "is_vendor": False},
                        {"name": "P3", "pref": "like", "is_vendor": False},
                        {"name": "P4", "pref": "universal_like", "is_vendor": False},
                    ],
                }
            ],
            "npc_progress": {},
            "covered_npcs": {"p1", "p2", "p3", "p4"},
            "target_npcs": {"p1", "p2", "p3", "p4"},
            "overall_stats": {
                "strategy": "max-relationship",
                "total_relationship_points": 60,
                "game_given_loved": 2,
                "game_total_loved": 10,
                "game_given_liked": 2,
                "game_total_liked": 20,
                "game_given_total": 4,
                "game_total_preferences": 30,
                "remaining_unique_items": 15,
                "mode": "weekday",
                "max_slots": 20,
                "covered_npcs_count": 4,
                "target_npcs_count": 4,
                "vendors_covered_today": 0,
                "today_loved_completed": 2,
                "today_liked_completed": 2,
                "locked_npcs": [],
                "ungiftable_npcs": [],
            },
        }
        out = capture_terminal_output(None, plan_results)
        self.assertIn("[💖 LOVE] P1", out)
        self.assertIn("[✨ UNIV. LOVE] P2", out)
        self.assertIn("[💙 LIKE] P3", out)
        self.assertIn("[🌟 UNIV. LIKE] P4", out)

    def test_journal_strategy_retains_legacy_symbols(self):
        """When strategy is journal, uses ♥ and ♡ symbols, suppressing 💖 LOVE / 💙 LIKE badges."""
        plan_results = {
            "bag_plan": [
                {
                    "slot": 1,
                    "quantity_to_pack": 2,
                    "item_name": "Wild Berry",
                    "status_badge": "📦 HAVE",
                    "all_recipients_today": [
                        {"name": "March", "pref": "LOVE", "is_vendor": False},
                        {"name": "Celine", "pref": "LIKE", "is_vendor": False},
                    ],
                }
            ],
            "npc_progress": {},
            "covered_npcs": {"march", "celine"},
            "target_npcs": {"march", "celine"},
            "overall_stats": {
                "strategy": "journal",
                "game_given_loved": 1,
                "game_total_loved": 10,
                "game_given_liked": 1,
                "game_total_liked": 20,
                "game_given_total": 2,
                "game_total_preferences": 30,
                "remaining_unique_items": 15,
                "mode": "weekday",
                "max_slots": 20,
                "covered_npcs_count": 2,
                "target_npcs_count": 2,
                "vendors_covered_today": 0,
                "today_loved_completed": 1,
                "today_liked_completed": 1,
                "locked_npcs": [],
                "ungiftable_npcs": [],
            },
        }
        out = capture_terminal_output(None, plan_results)
        self.assertIn("♥March, ♡Celine", out)
        self.assertNotIn("[💖 LOVE]", out)
        self.assertNotIn("[💙 LIKE]", out)
        self.assertIn("🎯 IMPACT: +1 Loved & +1 Liked preferences completed in one trip!", out)


# ==============================================================================
# 5. CSV & EXCEL EXPORTER MAX-RELATIONSHIP INTEGRATION TESTS
# ==============================================================================

class TestExportersMaxRelationshipResults(unittest.TestCase):
    """Stress tests export_plan_to_csv and export_plan_to_excel with realistic max-relationship results."""

    def setUp(self):
        self.npc_defs = {
            "adeline": {"name": "Adeline", "loved": ["apple_pie"], "liked": ["turnip"]},
            "march": {"name": "March", "loved": ["deluxe_sandwich"], "liked": ["copper_ingot"]},
            "celine": {"name": "Celine", "loved": ["rose"], "liked": ["strawberry"]},
            "darcy": {"name": "Darcy", "loved": ["sweet_treat"], "liked": ["tea"]},
        }
        self.metadata = {
            "apple_pie": {"display_name": "Apple Pie", "bin_price": 120, "store_price": 250, "tags": ["cooking", "dessert"], "description": "Fresh pie."},
            "deluxe_sandwich": {"display_name": "Deluxe Sandwich", "bin_price": 200, "store_price": 400, "tags": ["cooking", "meal"], "description": "Savory sandwich."},
            "strawberry": {"display_name": "Strawberry", "bin_price": 40, "store_price": 80, "tags": ["crop", "fruit"], "description": "Sweet berry."},
            "tea": {"display_name": "Tea", "bin_price": 30, "store_price": 60, "tags": ["drink"], "description": "Warm beverage."},
            "soup_univ_love": {"display_name": "Infused Soup Love", "bin_price": 150, "store_price": 300, "tags": ["cooking"], "description": "Universal love soup."},
            "soup_univ_like": {"display_name": "Infused Soup Like", "bin_price": 100, "store_price": 200, "tags": ["cooking"], "description": "Universal like soup."},
        }

    def _generate_max_rel_plan(self):
        """Generates realistic max-relationship plan with all 4 preference tiers represented."""
        # adeline gets specific love (apple_pie)
        # march gets universal love (soup_univ_love)
        # celine gets specific like (strawberry)
        # darcy gets universal like (soup_univ_like)
        inventory = {
            "apple_pie": 1,
            "strawberry": 1,
            "soup_univ_love": 1,
            "soup_univ_like": 1,
        }
        infused = {
            "lovable": [{"item_id": "soup_univ_love", "count": 1, "location": "bag"}],
            "likable": [{"item_id": "soup_univ_like", "count": 1, "location": "bag"}],
        }
        plan = plan_max_relationship(
            save=None,
            npc_gift_definitions=self.npc_defs,
            item_metadata=self.metadata,
            mode="saturday",
            inventory=inventory,
            infused_items=infused,
            force_all_npcs=True,
        )
        return plan

    def test_export_plan_to_csv_max_relationship(self):
        """Verifies CSV export structure, headers, UTF-8 BOM, and populated recipient tiers."""
        plan = self._generate_max_rel_plan()

        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            export_plan_to_csv(plan, out_dir, csv_name="test_max_rel.csv")
            csv_path = out_dir / "test_max_rel.csv"

            self.assertTrue(csv_path.exists())

            # Verify UTF-8 BOM
            raw_bytes = csv_path.read_bytes()
            self.assertTrue(raw_bytes.startswith(b"\xef\xbb\xbf"), "CSV file must begin with UTF-8 BOM")

            # Parse CSV content
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                rows = list(reader)

            headers = rows[0]
            self.assertEqual(headers[0], "Slot #")
            self.assertEqual(headers[1], "Pack Qty")
            self.assertEqual(headers[3], "Item Name")
            self.assertEqual(headers[7], "Loved Targets (Today)")
            self.assertEqual(headers[8], "Liked Targets (Today)")

            # Expect 4 items packed
            data_rows = rows[1:]
            self.assertEqual(len(data_rows), len(plan["bag_plan"]))

            # Verify specific and universal assignments appear in corresponding columns
            items_found = {row[4]: row for row in data_rows}
            self.assertIn("apple_pie", items_found)
            self.assertIn("Adeline", items_found["apple_pie"][7])  # Loved Targets (Today)

            self.assertIn("soup_univ_love", items_found)
            self.assertIn("Darcy", items_found["soup_univ_love"][7])  # Darcy (boosted Saturday vendor) in Loved Targets for UNIV_LOVE

            self.assertIn("strawberry", items_found)
            self.assertIn("Celine", items_found["strawberry"][8])  # Liked Targets (Today)

            self.assertIn("soup_univ_like", items_found)
            self.assertIn("March", items_found["soup_univ_like"][8])  # March in Liked Targets for UNIV_LIKE

            # Verify tags formatting (must not contain raw python brackets)
            for row in data_rows:
                tags_val = row[11]
                self.assertNotIn("[", tags_val)
                self.assertNotIn("]", tags_val)

    def test_export_plan_to_excel_max_relationship(self):
        """Verifies multi-sheet Excel export, formatting, Sheet 4 Universal Love/Like markings."""
        if not OPENPYXL_AVAILABLE:
            self.skipTest("openpyxl is not installed")

        import openpyxl

        plan = self._generate_max_rel_plan()

        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = Path(tmpdir) / "test_max_rel.xlsx"
            export_plan_to_excel(None, plan, self.npc_defs, self.metadata, excel_path)

            self.assertTrue(excel_path.exists())

            wb = openpyxl.load_workbook(excel_path)
            expected_sheets = ["Daily Bag Plan", "NPC Gift Progress", "All Remaining Items", "Gift Completion Matrix"]
            for s in expected_sheets:
                self.assertIn(s, wb.sheetnames)

            # Sheet 1: Daily Bag Plan
            ws1 = wb["Daily Bag Plan"]
            self.assertEqual(ws1.cell(row=1, column=1).value, "Slot #")
            self.assertEqual(ws1.max_row, len(plan["bag_plan"]) + 1)

            # Sheet 2: NPC Gift Progress
            ws2 = wb["NPC Gift Progress"]
            npc_rows = {}
            for r in range(2, ws2.max_row + 1):
                name = ws2.cell(row=r, column=1).value
                assigned_item = ws2.cell(row=r, column=6).value
                pref_met = ws2.cell(row=r, column=7).value
                npc_rows[name] = (assigned_item, pref_met)

            self.assertEqual(npc_rows["Adeline"], ("Apple Pie", "LOVE"))
            self.assertEqual(npc_rows["Darcy"], ("Infused Soup Love", "UNIV_LOVE"))
            self.assertEqual(npc_rows["Celine"], ("Strawberry", "LIKE"))
            self.assertEqual(npc_rows["March"], ("Infused Soup Like", "UNIV_LIKE"))

            # Sheet 4: Gift Completion Matrix
            ws4 = wb["Gift Completion Matrix"]
            self.assertIn("Item Name", ws4.cell(row=1, column=1).value)

            # Map column indices for NPCs
            npc_cols = {}
            for c in range(4, ws4.max_column + 1):
                header = str(ws4.cell(row=1, column=c).value)
                clean_name = header.replace(" (Market)", "").strip()
                npc_cols[clean_name] = c

            self.assertIn("Adeline", npc_cols)
            self.assertIn("March", npc_cols)
            self.assertIn("Celine", npc_cols)
            self.assertIn("Darcy", npc_cols)

            # Map row indices for item IDs
            item_rows = {}
            for r in range(2, ws4.max_row + 1):
                iid = ws4.cell(row=r, column=2).value
                item_rows[iid] = r

            # Verify:
            # Apple Pie -> Adeline: PACK (LOVE)
            self.assertEqual(ws4.cell(row=item_rows["apple_pie"], column=npc_cols["Adeline"]).value, "PACK (LOVE)")
            # Universal Love soup -> Darcy: PACK (LOVE)
            self.assertEqual(ws4.cell(row=item_rows["soup_univ_love"], column=npc_cols["Darcy"]).value, "PACK (LOVE)")
            # Strawberry -> Celine: PACK (LIKE)
            self.assertEqual(ws4.cell(row=item_rows["strawberry"], column=npc_cols["Celine"]).value, "PACK (LIKE)")
            # Universal Like soup -> March: PACK (LIKE)
            self.assertEqual(ws4.cell(row=item_rows["soup_univ_like"], column=npc_cols["March"]).value, "PACK (LIKE)")

            # Verify universal dishes are present in Sheet 4 even if not in base preferences
            self.assertIn("soup_univ_love", item_rows)
            self.assertIn("soup_univ_like", item_rows)

    def test_export_plan_to_excel_openpyxl_missing_graceful_fallback(self):
        """When openpyxl is not installed/mocked as False, export_plan_to_excel exits cleanly without error."""
        plan = self._generate_max_rel_plan()
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = Path(tmpdir) / "fallback.xlsx"
            with patch("fom_planner.exporters.excel_export.OPENPYXL_AVAILABLE", False):
                # Should not raise exception
                export_plan_to_excel(None, plan, self.npc_defs, self.metadata, excel_path)
            self.assertFalse(excel_path.exists())


# ==============================================================================
# 6. ADVERSARIAL EDGE CASES & STRESS HARNESS
# ==============================================================================

class TestExportersAdversarialEdgeCases(unittest.TestCase):
    """Adversarial stress tests for formatting robustness, unusual characters, and boundary conditions."""

    def test_unicode_and_emojis_in_terminal_and_csv(self):
        """Special characters, apostrophes, and unicode in NPC names and item descriptions."""
        npc_defs = {
            "olric": {"name": "Ol'ric 🛡️", "loved": ["star_gem"], "liked": []},
        }
        metadata = {
            "star_gem": {
                "display_name": "⭐ Star Gem / Étoile",
                "bin_price": 500,
                "store_price": 1000,
                "tags": ["gem", "rare ✨"],
                "description": "A radiant, shining gem from the earth's mantle — 100% pure.",
            }
        }
        plan = plan_max_relationship(
            save=None,
            npc_gift_definitions=npc_defs,
            item_metadata=metadata,
            inventory={"star_gem": 1},
            force_all_npcs=True,
        )

        # Terminal output
        out = capture_terminal_output(None, plan)
        self.assertIn("⭐ Star Gem / Étoile", out)
        self.assertIn("Ol'ric 🛡️", out)

        # CSV output
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            export_plan_to_csv(plan, out_dir, csv_name="unicode.csv")
            with open(out_dir / "unicode.csv", "r", encoding="utf-8-sig") as f:
                content = f.read()
            self.assertIn("⭐ Star Gem / Étoile", content)
            self.assertIn("Ol'ric 🛡️", content)
            self.assertIn("rare ✨", content)

    def test_missing_optional_fields_in_bag_dict(self):
        """Terminal and CSV exporters handle stripped-down or malformed bag item dicts."""
        plan_results = {
            "bag_plan": [
                {
                    "slot": 1,
                    "item_id": "minimal_item",
                    "item_name": "Minimal Item",
                    "quantity_to_pack": 1,
                    "all_recipients_today": [{"name": "March", "pref": "LOVE"}],
                    # Missing status_badge, crafting_chain, bin_price, tags, description, etc.
                    "market_vendors_covered": [],
                    "loved_recipients_today": ["March"],
                    "liked_recipients_today": [],
                    "bin_price": "",
                    "store_price": "",
                    "tags": "",
                    "description": "",
                }
            ],
            "npc_progress": {},
            "covered_npcs": {"march"},
            "target_npcs": {"march"},
            "overall_stats": {
                "strategy": "max-relationship",
                "total_relationship_points": 20,
                "game_given_loved": 1,
                "game_total_loved": 10,
                "game_given_liked": 0,
                "game_total_liked": 20,
                "game_given_total": 1,
                "game_total_preferences": 30,
                "remaining_unique_items": 15,
                "mode": "weekday",
                "max_slots": 20,
                "covered_npcs_count": 1,
                "target_npcs_count": 1,
                "vendors_covered_today": 0,
                "today_loved_completed": 1,
                "today_liked_completed": 0,
                "locked_npcs": [],
                "ungiftable_npcs": [],
            },
        }

        # Terminal exporter must not crash
        out = capture_terminal_output(None, plan_results)
        self.assertIn("Minimal Item", out)
        self.assertIn("[💖 LOVE] March", out)

        # CSV exporter must not crash
        with tempfile.TemporaryDirectory() as tmpdir:
            export_plan_to_csv(plan_results, Path(tmpdir))
            self.assertTrue((Path(tmpdir) / "daily_gift_bag_plan.csv").exists())

    def test_large_scale_max_relationship_roster_stress(self):
        """Simulate all 34 NPCs receiving gifts (highest possible relationship points = 680 pts)."""
        all_34_npcs = [
            "adeline", "balor", "celine", "darcy", "dell", "dozy", "eiland", "elsie", "errol",
            "hayden", "hemlock", "henrietta", "holt", "josephine", "juniper", "landen", "louis",
            "luc", "maple", "march", "merri", "nora", "olric", "reina", "ryis", "seridia",
            "stillwell", "taliferro", "terithia", "valen", "vera", "wheedle", "zorel", "caldarus",
        ]
        npc_defs = {
            nid: {"name": nid.capitalize(), "loved": [f"love_{nid}"], "liked": []}
            for nid in all_34_npcs
        }
        metadata = {
            f"love_{nid}": {"display_name": f"Gift For {nid.capitalize()}", "bin_price": 50, "store_price": 100, "tags": ["gift"]}
            for nid in all_34_npcs
        }
        inventory = {f"love_{nid}": 1 for nid in all_34_npcs}

        # Saturday mode with 35 bag slots to fit all 34 NPCs
        plan = plan_max_relationship(
            save=None,
            npc_gift_definitions=npc_defs,
            item_metadata=metadata,
            mode="saturday",
            max_slots=35,
            inventory=inventory,
            force_all_npcs=True,
        )

        self.assertEqual(plan["overall_stats"]["total_relationship_points"], 34 * 20)
        self.assertEqual(plan["overall_stats"]["covered_npcs_count"], 34)

        # Stress terminal exporter
        out = capture_terminal_output(None, plan)
        self.assertIn("TOTAL RELATIONSHIP POINTS EARNED TODAY: +680 pts", out)
        self.assertIn("💞 RELATIONSHIP IMPACT: +680 total points earned today across 34 NPCs!", out)
        self.assertIn("Loved: 34 gifts (+20 pts each) | Liked: 0 gifts (+10 pts each)", out)
        self.assertIn("✨ 100% NPC coverage achieved!", out)

        # Stress CSV and Excel exporters
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            export_plan_to_csv(plan, out_dir)
            self.assertTrue((out_dir / "daily_gift_bag_plan.csv").exists())

            if OPENPYXL_AVAILABLE:
                export_plan_to_excel(None, plan, npc_defs, metadata, out_dir / "stress.xlsx")
                self.assertTrue((out_dir / "stress.xlsx").exists())

# ============================================================================
# EXPORTER TERMINAL & EXCEL SPECIALIZED TESTS
# ============================================================================

class TestTerminalExporterFormatting(unittest.TestCase):
    """Tests for print_terminal_plan() formatting (infused banner, badges, impact summary)."""

    def setUp(self):
        self.dummy_save = None

    def _capture_terminal_output(self, plan_results, save=None):
        out = io.StringIO()
        with patch("sys.stdout", out):
            print_terminal_plan(save, plan_results)
        return out.getvalue()

    def test_format_infused_summary_helper(self):
        # List of dicts
        cnt, s = _format_infused_summary([{"item_id": "apple_pie", "count": 2}, {"item_id": "berry_tart", "count": 1}])
        self.assertEqual(cnt, 3)
        self.assertIn("apple_pie (x2)", s)
        self.assertIn("berry_tart (x1)", s)

        # Dict mapping
        cnt, s = _format_infused_summary({"tea": 2, "cake": 3})
        self.assertEqual(cnt, 5)
        self.assertIn("cake (x3)", s)
        self.assertIn("tea (x2)", s)

        # Empty / None
        self.assertEqual(_format_infused_summary(None), (0, ""))
        self.assertEqual(_format_infused_summary([]), (0, ""))

    def test_terminal_output_infused_items_banner_empty_in_max_rel(self):
        plan_results = {
            "bag_plan": [],
            "npc_progress": {},
            "covered_npcs": set(),
            "target_npcs": set(),
            "overall_stats": {
                "strategy": "max-relationship",
                "total_relationship_points": 0,
                "game_given_loved": 0, "game_total_loved": 10,
                "game_given_liked": 0, "game_total_liked": 20,
                "game_given_total": 0, "game_total_preferences": 30,
                "remaining_unique_items": 15,
                "mode": "weekday", "max_slots": 20, "covered_npcs_count": 0,
                "target_npcs_count": 0, "vendors_covered_today": 0,
                "today_loved_completed": 0, "today_liked_completed": 0,
                "locked_npcs": [], "ungiftable_npcs": [],
            },
            "infused_items": {"lovable": [], "likable": []},
        }
        out = self._capture_terminal_output(plan_results)
        self.assertIn("🔮 DETECTED INFUSED ITEMS (Cooking Perk):", out)
        self.assertIn("• None detected in bag or chest storage.", out)
        self.assertIn("TOTAL RELATIONSHIP POINTS EARNED TODAY: +0 pts", out)
        self.assertIn("💞 RELATIONSHIP IMPACT: +0 total points earned today across 0 NPCs!", out)

    def test_terminal_output_infused_items_banner_populated(self):
        plan_results = {
            "bag_plan": [],
            "npc_progress": {},
            "covered_npcs": set(),
            "target_npcs": set(),
            "overall_stats": {
                "strategy": "max-relationship",
                "total_relationship_points": 40,
                "game_given_loved": 2, "game_total_loved": 10,
                "game_given_liked": 0, "game_total_liked": 20,
                "game_given_total": 2, "game_total_preferences": 30,
                "remaining_unique_items": 15,
                "mode": "weekday", "max_slots": 20, "covered_npcs_count": 2,
                "target_npcs_count": 2, "vendors_covered_today": 0,
                "today_loved_completed": 2, "today_liked_completed": 0,
                "locked_npcs": [], "ungiftable_npcs": [],
            },
            "infused_items": {
                "lovable": [{"item_id": "apple_pie", "count": 2, "location": "bag"}],
                "likable": [{"item_id": "vegetable_soup", "count": 3, "location": "farm"}],
            },
        }
        out = self._capture_terminal_output(plan_results)
        self.assertIn("🔮 DETECTED INFUSED ITEMS (Cooking Perk):", out)
        self.assertIn("Lovable Dishes (✨ Universal Love, +20 pts): 2 total — apple_pie (x2)", out)
        self.assertIn("Likable Dishes (🌟 Universal Like, +10 pts): 3 total — vegetable_soup (x3)", out)

    def test_terminal_output_preference_tier_badges_max_rel(self):
        plan_results = {
            "bag_plan": [
                {
                    "slot": 1,
                    "quantity_to_pack": 1,
                    "item_name": "Apple Pie",
                    "status_badge": "📦 HAVE",
                    "all_recipients_today": [{"name": "March", "pref": "LOVE", "is_vendor": False}],
                },
                {
                    "slot": 2,
                    "quantity_to_pack": 1,
                    "item_name": "Berry Tart",
                    "status_badge": "📦 HAVE",
                    "all_recipients_today": [{"name": "Adeline", "pref": "UNIV_LOVE", "is_vendor": False}],
                },
                {
                    "slot": 3,
                    "quantity_to_pack": 1,
                    "item_name": "Strawberry",
                    "status_badge": "📦 HAVE",
                    "all_recipients_today": [{"name": "Celine", "pref": "LIKE", "is_vendor": False}],
                },
                {
                    "slot": 4,
                    "quantity_to_pack": 1,
                    "item_name": "Vegetable Soup",
                    "status_badge": "📦 HAVE",
                    "all_recipients_today": [{"name": "Darcy", "pref": "UNIV_LIKE", "is_vendor": True}],
                },
            ],
            "npc_progress": {},
            "covered_npcs": {"march", "adeline", "celine", "darcy"},
            "target_npcs": {"march", "adeline", "celine", "darcy"},
            "overall_stats": {
                "strategy": "max-relationship",
                "total_relationship_points": 60,
                "game_given_loved": 2, "game_total_loved": 10,
                "game_given_liked": 2, "game_total_liked": 20,
                "game_given_total": 4, "game_total_preferences": 30,
                "remaining_unique_items": 15,
                "mode": "saturday", "max_slots": 20, "covered_npcs_count": 4,
                "target_npcs_count": 4, "vendors_covered_today": 1,
                "today_loved_completed": 2, "today_liked_completed": 2,
                "locked_npcs": [], "ungiftable_npcs": [],
            },
        }
        out = self._capture_terminal_output(plan_results)
        self.assertIn("[💖 LOVE] March", out)
        self.assertIn("[✨ UNIV. LOVE] Adeline", out)
        self.assertIn("[💙 LIKE] Celine", out)
        self.assertIn("[🌟 UNIV. LIKE] Darcy [Market]", out)
        self.assertIn("TOTAL RELATIONSHIP POINTS EARNED TODAY: +60 pts", out)
        self.assertIn("💞 RELATIONSHIP IMPACT: +60 total points earned today across 4 NPCs! (including 1 Saturday Market vendors)", out)

    def test_terminal_output_legacy_badges_journal_mode(self):
        plan_results = {
            "bag_plan": [
                {
                    "slot": 1,
                    "quantity_to_pack": 1,
                    "item_name": "Apple Pie",
                    "status_badge": "📦 HAVE",
                    "all_recipients_today": [
                        {"name": "March", "pref": "LOVE", "is_vendor": False},
                        {"name": "Celine", "pref": "LIKE", "is_vendor": False},
                    ],
                },
            ],
            "npc_progress": {},
            "covered_npcs": {"march", "celine"},
            "target_npcs": {"march", "celine"},
            "overall_stats": {
                "strategy": "journal",
                "game_given_loved": 1, "game_total_loved": 10,
                "game_given_liked": 1, "game_total_liked": 20,
                "game_given_total": 2, "game_total_preferences": 30,
                "remaining_unique_items": 15,
                "mode": "weekday", "max_slots": 20, "covered_npcs_count": 2,
                "target_npcs_count": 2, "vendors_covered_today": 0,
                "today_loved_completed": 1, "today_liked_completed": 1,
                "locked_npcs": [], "ungiftable_npcs": [],
            },
        }
        out = self._capture_terminal_output(plan_results)
        self.assertIn("♥March", out)
        self.assertIn("♡Celine", out)
        self.assertNotIn("[💖 LOVE]", out)
        self.assertIn("🎯 IMPACT: +1 Loved & +1 Liked preferences completed in one trip!", out)
        self.assertNotIn("RELATIONSHIP IMPACT", out)


class TestExcelExporterUniversalLove(unittest.TestCase):
    """Tests for Excel exporter Sheet 4 Universal Love assignment marking."""

    def test_excel_export_marks_univ_love_as_pack_love(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl is not installed")
        import tempfile
        from fom_planner.optimizer import plan_max_relationship

        npc_defs = {
            "march": {"name": "March", "loved": ["deluxe_sandwich"], "liked": ["copper_ingot"]},
        }
        metadata = {
            "apple_pie": {"display_name": "Apple Pie"},
            "deluxe_sandwich": {"display_name": "Deluxe Sandwich"},
            "copper_ingot": {"display_name": "Copper Ingot"},
        }

        # March has only apple_pie available as a universal love gift
        plan_results = plan_max_relationship(
            save=None,
            npc_gift_definitions=npc_defs,
            item_metadata=metadata,
            inventory={"apple_pie": 1},
            infused_items={"lovable": [{"item_id": "apple_pie", "count": 1, "location": "bag"}]},
            mode="weekday",
            force_all_npcs=True,
        )

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tf:
            excel_path = Path(tf.name)

        try:
            export_plan_to_excel(None, plan_results, npc_defs, metadata, excel_path)
            wb = openpyxl.load_workbook(excel_path)
            self.assertIn("Gift Completion Matrix", wb.sheetnames)
            ws = wb["Gift Completion Matrix"]

            # Find row for Apple Pie and col for March
            march_col = None
            for col in range(4, ws.max_column + 1):
                if ws.cell(row=1, column=col).value == "March":
                    march_col = col
                    break
            self.assertIsNotNone(march_col)

            apple_pie_val = None
            for row in range(2, ws.max_row + 1):
                if ws.cell(row=row, column=2).value == "apple_pie":
                    apple_pie_val = ws.cell(row=row, column=march_col).value
                    break

            self.assertEqual(apple_pie_val, "PACK (LOVE)")
        finally:
            if excel_path.exists():
                excel_path.unlink()


class TestTerminalMaxRelationshipBanner(unittest.TestCase):
    """Verify terminal banner for NPCs reaching max relationship."""

    def test_terminal_plan_prints_max_relationship_banner(self):
        plan_results = {
            "bag_plan": [],
            "npc_progress": {},
            "covered_npcs": set(),
            "target_npcs": set(),
            "overall_stats": {
                "strategy": "max-relationship",
                "total_relationship_points": 0,
                "game_given_loved": 0,
                "game_total_loved": 10,
                "game_given_liked": 0,
                "game_total_liked": 20,
                "game_given_total": 0,
                "game_total_preferences": 30,
                "remaining_unique_items": 15,
                "mode": "weekday",
                "max_slots": 20,
                "covered_npcs_count": 0,
                "target_npcs_count": 1,
                "vendors_covered_today": 0,
                "today_loved_completed": 0,
                "today_liked_completed": 0,
                "locked_npcs": [],
                "ungiftable_npcs": [],
                "max_relationship_npcs": ["Adeline", "March"],
                "max_relationship_npcs_count": 2,
            },
        }
        out = io.StringIO()
        with patch("sys.stdout", out):
            print_terminal_plan(None, plan_results)
        output = out.getvalue()
        self.assertIn("💖 MAX RELATIONSHIP REACHED (2 NPCs): Adeline, March", output)


if __name__ == "__main__":
    unittest.main()
