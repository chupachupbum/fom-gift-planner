#!/usr/bin/env python3
"""
tests/test_challenger_cli_and_exporters.py

Empirical Challenger 2 Test Suite:
Validates CLI integration, Terminal presentation, and Excel multi-sheet export
for the Fields of Mistria Focus Recipes feature.
"""

import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import openpyxl
from starlette.testclient import TestClient

from companion.config import CompanionConfig
from companion.json_exporter import plan_to_json
from companion.server import app
from fom_planner.cli import build_planner_parser, run_planner
from fom_planner.crafting import load_recipes
from fom_planner.data_loader import load_item_metadata, load_npc_preferences_from_json, load_recipe_sources
from fom_planner.exporters.excel_export import export_plan_to_excel
from fom_planner.exporters.terminal import print_terminal_plan
from fom_planner.models import SaveData
from fom_planner.optimizer import plan_daily_gift_bag, plan_max_relationship
from tests.test_gift_planner import create_synthetic_save_entries

DATA_RECIPES_PATH = REPO_ROOT / "data" / "recipes.json"
DATA_RECIPE_SOURCES_PATH = REPO_ROOT / "data" / "recipe_sources.json"


class TestCLIExecutionAndHelp(unittest.TestCase):
    """Empirical verification of CLI argument parsing and execution."""

    def test_cli_help_shows_recipe_sources(self):
        """python -m fom_planner.cli plan --help shows --recipe-sources."""
        parser = build_planner_parser()
        help_output = parser.format_help()
        self.assertIn("--recipe-sources", help_output)
        self.assertIn("recipe_sources.json", help_output)

    @patch("fom_planner.cli.find_latest_save", return_value=None)
    def test_cli_run_journal_strategy_with_recipe_sources(self, mock_save):
        """CLI execution: plan --strategy journal with --recipe-sources."""
        args = build_planner_parser().parse_args([
            "--strategy", "journal",
            "--recipe-sources", str(DATA_RECIPE_SOURCES_PATH),
            "--format", "terminal",
        ])
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            run_planner(args)
        out = buf.getvalue()
        self.assertIn("FIELDS OF MISTRIA — DAILY GIFT BAG PLANNER", out)
        # Without save file, focus recipes should be silently omitted
        self.assertNotIn("🍳 FOCUS RECIPES", out)

    @patch("fom_planner.cli.find_latest_save", return_value=None)
    def test_cli_run_max_relationship_strategy_with_recipe_sources(self, mock_save):
        """CLI execution: plan --strategy max-relationship with --recipe-sources."""
        args = build_planner_parser().parse_args([
            "--strategy", "max-relationship",
            "--recipe-sources", str(DATA_RECIPE_SOURCES_PATH),
            "--format", "terminal",
        ])
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            run_planner(args)
        out = buf.getvalue()
        self.assertIn("FIELDS OF MISTRIA — DAILY GIFT BAG PLANNER", out)
        self.assertNotIn("🍳 FOCUS RECIPES", out)

    def test_cli_nonexistent_recipe_sources_graceful_fallback(self):
        """CLI with nonexistent --recipe-sources runs without crashing."""
        args = build_planner_parser().parse_args([
            "--strategy", "journal",
            "--recipe-sources", "data/nonexistent_file_path.json",
            "--format", "terminal",
        ])
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            run_planner(args)
        out = buf.getvalue()
        self.assertIn("FIELDS OF MISTRIA — DAILY GIFT BAG PLANNER", out)


class TestTerminalPresentationEmpirical(unittest.TestCase):
    """Empirical verification of Terminal presentation formatting and rules."""

    def setUp(self):
        self.recipes = load_recipes()
        self.cooking_keys = [k for k, v in self.recipes.items() if v.get("source") == "cooking"]
        self.sources = load_recipe_sources()
        self.raw = create_synthetic_save_entries(bag_items={"bread": 1})

    def _render_terminal(self, save, plan_results) -> str:
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            print_terminal_plan(save, plan_results)
        return buf.getvalue()

    def test_terminal_without_save_file_silently_omitted(self):
        """Terminal output when run without save file must silently omit FOCUS RECIPES."""
        res = plan_daily_gift_bag(save=None, recipe_sources=self.sources)
        out = self._render_terminal(None, res)
        self.assertNotIn("🍳 FOCUS RECIPES", out)

    def test_terminal_some_recipes_unlocked_formatting_and_width(self):
        """Terminal presentation with 10 unlocked recipes displays header, table, and 86-char dividers."""
        pdict = json.loads(self.raw["player"])
        pdict["recipe_unlocks"] = self.cooking_keys[:10]
        self.raw["player"] = json.dumps(pdict)
        save = SaveData(Path("test_some.sav"), self.raw)

        res = plan_daily_gift_bag(save=save, recipe_sources=self.sources)
        out = self._render_terminal(save, res)

        self.assertIn("🍳 FOCUS RECIPES (10/163 cooking recipes unlocked — 6.1%):", out)
        self.assertIn("━" * 86, out)
        self.assertIn("═" * 86, out)

        # Check table headers and alignment
        expected_header = f" {'Rank':<5} │ {'Recipe Name':<24} │ {'Impact':<15} │ {'Unlock Source'}"
        self.assertIn(expected_header, out)

        # Verify dividers match 86 characters
        for line in out.splitlines():
            if line.startswith("━"):
                self.assertEqual(len(line), 86)
            elif line.startswith("═"):
                self.assertEqual(len(line), 86)

    def test_terminal_all_recipes_unlocked_celebration_banner(self):
        """Terminal presentation with all 163 recipes unlocked displays celebration banner."""
        pdict = json.loads(self.raw["player"])
        pdict["recipe_unlocks"] = self.cooking_keys
        self.raw["player"] = json.dumps(pdict)
        save = SaveData(Path("test_all.sav"), self.raw)

        res = plan_daily_gift_bag(save=save, recipe_sources=self.sources)
        out = self._render_terminal(save, res)

        self.assertIn("🍳 FOCUS RECIPES (163/163 cooking recipes unlocked — 100.0%):", out)
        self.assertIn("  🎉 All cooking recipes unlocked!", out)
        self.assertIn("━" * 86, out)

    def test_terminal_zero_cooking_recipes_unlocked(self):
        """Terminal presentation when save has unlocked items but 0 cooking recipes."""
        pdict = json.loads(self.raw["player"])
        # 'flour' is a milling recipe, not cooking
        pdict["recipe_unlocks"] = ["flour"]
        self.raw["player"] = json.dumps(pdict)
        save = SaveData(Path("test_0_cooking.sav"), self.raw)

        res = plan_daily_gift_bag(save=save, recipe_sources=self.sources)
        out = self._render_terminal(save, res)

        self.assertIn("🍳 FOCUS RECIPES (0/163 cooking recipes unlocked — 0.0%):", out)
        self.assertIn("━" * 86, out)
        self.assertIn("in 0 gifts", out)


class TestExcelExportEmpirical(unittest.TestCase):
    """Empirical inspection of Excel workbook structure using openpyxl."""

    def setUp(self):
        self.recipes = load_recipes()
        self.cooking_keys = [k for k, v in self.recipes.items() if v.get("source") == "cooking"]
        self.sources = load_recipe_sources()
        self.npcs, _ = load_npc_preferences_from_json(Path("data/item_data.json"))
        self.meta = load_item_metadata(Path("assets/fiddle"), Path("data/item_data.json"))

        raw = create_synthetic_save_entries(bag_items={"bread": 2, "apple": 5})
        pdict = json.loads(raw["player"])
        pdict["recipe_unlocks"] = self.cooking_keys[:10]
        raw["player"] = json.dumps(pdict)
        self.save = SaveData(Path("test_excel.sav"), raw)

    def test_excel_sheet_5_focus_recipes_structure(self):
        """Inspects that Sheet 5 exists, is named 'Focus Recipes', and matches expected headers and types."""
        plan = plan_daily_gift_bag(
            save=self.save,
            npc_gift_definitions=self.npcs,
            item_metadata=self.meta,
            recipe_sources=self.sources,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "test_plan.xlsx"
            export_plan_to_excel(self.save, plan, self.npcs, self.meta, out_file)

            self.assertTrue(out_file.exists())
            wb = openpyxl.load_workbook(str(out_file))

            # 1. Total sheets must be at least 5 (now 6 with Focus Trees)
            self.assertGreaterEqual(len(wb.sheetnames), 5)

            # 2. Sheet 5 must be named "Focus Recipes"
            self.assertEqual(wb.sheetnames[4], "Focus Recipes")

            ws = wb["Focus Recipes"]

            # 3. Headers match ["Rank", "Recipe Name", "Impact", "Unlock Source"]
            headers = [cell.value for cell in ws[1]]
            self.assertEqual(headers, ["Rank", "Recipe Name", "Impact", "Unlock Source"])

            # 4. Check data rows (at least 1 row, up to 10)
            data_rows = list(ws.iter_rows(min_row=2, values_only=True))
            self.assertGreater(len(data_rows), 0)
            self.assertLessEqual(len(data_rows), 10)

            for idx, (rank, name, impact, source) in enumerate(data_rows, start=1):
                self.assertEqual(rank, idx)
                self.assertIsInstance(rank, int)
                self.assertIsInstance(name, str)
                self.assertGreater(len(name), 0)
                self.assertIsInstance(impact, int)
                self.assertGreaterEqual(impact, 0)
                self.assertIsInstance(source, str)
                self.assertGreater(len(source), 0)

            # 5. Styling and freeze panes
            self.assertEqual(ws.freeze_panes, "A2")
            self.assertIsNotNone(ws.auto_filter.ref)

    def test_excel_sheet_5_max_relationship_strategy(self):
        """Inspects that Sheet 5 is generated properly with max-relationship strategy."""
        plan = plan_max_relationship(
            save=self.save,
            npc_gift_definitions=self.npcs,
            item_metadata=self.meta,
            recipe_sources=self.sources,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "test_plan_max_rel.xlsx"
            export_plan_to_excel(self.save, plan, self.npcs, self.meta, out_file)

            wb = openpyxl.load_workbook(str(out_file))
            self.assertIn("Focus Recipes", wb.sheetnames)
            ws = wb["Focus Recipes"]
            headers = [cell.value for cell in ws[1]]
            self.assertEqual(headers, ["Rank", "Recipe Name", "Impact", "Unlock Source"])


class TestPresentationSurfacesTerminalAdversarial(unittest.TestCase):
    """Empirical adversarial verification of Terminal UI output rendering (Requirement R3)."""

    def setUp(self):
        raw = create_synthetic_save_entries(bag_items={"milk": 2, "flour": 1})
        self.save = SaveData(Path("test_term.sav"), raw)

    def _render(self, save, plan_results) -> str:
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            print_terminal_plan(save, plan_results)
        return buf.getvalue()

    def test_terminal_tree_rendering_with_focus_trees(self):
        """Verifies full terminal rendering with multi-node focus crafting trees, box characters, and badges."""
        plan_results = {
            "bag_plan": [],
            "npc_progress": {},
            "remaining_items_map": {},
            "overall_stats": {
                "today_loved_completed": 0,
                "today_liked_completed": 0,
                "covered_npcs_count": 0,
                "target_npcs_count": 0,
            },
            "focus_suggestions": [
                {
                    "item_id": "cow_milk",
                    "item_name": "Milk",
                    "deficit": 4,
                    "rank": 1,
                    "blocked_pairs": 6,
                    "ready_pairs": 2,
                    "location_hint": "Ranch (Cows)",
                },
                {
                    "item_id": "sugar",
                    "item_name": "Sugar",
                    "deficit": 2,
                    "rank": 2,
                    "blocked_pairs": 3,
                    "ready_pairs": 0,
                    "location_hint": "General Store",
                },
            ],
            "focus_trees": [
                {
                    "item_id": "cow_milk",
                    "item_name": "Milk",
                    "alt_sources": [
                        {"type": "shop", "vendor": "Balor's Wagon"},
                        {"type": "chicken_statue", "cost": 10, "currency": "shiny_beads"},
                    ],
                    "gift_npcs": [],
                    "children": [
                        {
                            "item_id": "cheese",
                            "item_name": "Cheese",
                            "alt_sources": [{"type": "chicken_statue", "cost": 10, "currency": "shiny_beads"}],
                            "gift_npcs": [],
                            "children": [
                                {
                                    "item_id": "cheesecake",
                                    "item_name": "Cheesecake",
                                    "alt_sources": [{"type": "chicken_statue", "cost": 100, "currency": "shiny_beads"}],
                                    "gift_npcs": ["Darcy", "Eiland"],
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
                {
                    "item_id": "sugar",
                    "item_name": "Sugar",
                    "alt_sources": [
                        {"type": "shop", "vendor": "General Store", "cost": 115, "currency": "tesserae"},
                    ],
                    "gift_npcs": [],
                    "children": [
                        {
                            "item_id": "cookies",
                            "item_name": "Cookies",
                            "alt_sources": [{"type": "mimic", "location": "Upper Mines"}],
                            "gift_npcs": ["Ryis"],
                            "children": [],
                        }
                    ],
                },
            ],
        }

        out = self._render(self.save, plan_results)

        # Header and dividers
        self.assertIn("💡 FOCUS SUGGESTIONS", out)
        self.assertIn("━" * 86, out)
        self.assertIn("═" * 86, out)

        # Suggestion entries
        self.assertIn("Milk", out)
        self.assertIn("Sugar", out)
        self.assertIn("blocks 6 gifts (2 ready)", out)
        self.assertIn("blocks 3 gifts", out)

        # Crafting tree headers
        self.assertIn("🌳 Crafting Tree:", out)

        # Box drawing characters
        self.assertTrue("├── " in out or "└── " in out)
        self.assertTrue("│   " in out or "    " in out)

        # Child products & gift recipients
        self.assertIn("Cheese", out)
        self.assertIn("Cheesecake", out)
        self.assertIn("→ Darcy, Eiland", out)
        self.assertIn("Cookies", out)
        self.assertIn("→ Ryis", out)

        # Alt-source emoji badges
        self.assertIn("🛒 Balor's Wagon", out)
        self.assertIn("🐔 Chicken Statue: 10 beads", out)
        self.assertIn("🐔 Chicken Statue: 100 beads", out)
        self.assertIn("🛒 General Store: 115t", out)
        self.assertIn("⛏️ Upper Mines", out)

    def test_terminal_tree_rendering_without_focus_trees(self):
        """Verifies terminal rendering does not crash and omits tree when focus_trees key is absent."""
        plan_results = {
            "bag_plan": [],
            "npc_progress": {},
            "remaining_items_map": {},
            "overall_stats": {
                "today_loved_completed": 0,
                "today_liked_completed": 0,
                "covered_npcs_count": 0,
                "target_npcs_count": 0,
            },
            "focus_suggestions": [
                {
                    "item_id": "milk",
                    "item_name": "Milk",
                    "deficit": 2,
                    "rank": 1,
                    "location_hint": "Ranch",
                }
            ],
        }

        out = self._render(self.save, plan_results)
        self.assertIn("💡 FOCUS SUGGESTIONS", out)
        self.assertIn("Milk", out)
        self.assertNotIn("🌳 Crafting Tree:", out)

    def test_terminal_tree_rendering_empty_focus_trees(self):
        """Verifies terminal rendering handles focus_trees: [] gracefully without crashing."""
        plan_results = {
            "bag_plan": [],
            "npc_progress": {},
            "remaining_items_map": {},
            "overall_stats": {
                "today_loved_completed": 0,
                "today_liked_completed": 0,
                "covered_npcs_count": 0,
                "target_npcs_count": 0,
            },
            "focus_suggestions": [
                {
                    "item_id": "flour",
                    "item_name": "Flour",
                    "deficit": 1,
                    "rank": 1,
                    "location_hint": "General Store",
                }
            ],
            "focus_trees": [],
        }

        out = self._render(self.save, plan_results)
        self.assertIn("Flour", out)
        self.assertNotIn("🌳 Crafting Tree:", out)

    def test_terminal_tree_rendering_empty_focus_suggestions(self):
        """Verifies celebration banner when focus_suggestions is empty."""
        plan_results = {
            "bag_plan": [],
            "npc_progress": {},
            "remaining_items_map": {},
            "overall_stats": {
                "today_loved_completed": 0,
                "today_liked_completed": 0,
                "covered_npcs_count": 0,
                "target_npcs_count": 0,
            },
            "focus_suggestions": [],
            "focus_trees": [],
        }

        out = self._render(self.save, plan_results)
        self.assertIn("🎉 All required materials and gifts are currently in your inventory!", out)

    def test_terminal_tree_rendering_all_twelve_emoji_badges(self):
        """Adversarially asserts that all 12 source types plus fallback render correct emojis in terminal."""
        twelve_sources = [
            {"type": "shop", "vendor": "General Store", "cost": 200, "currency": "tesserae"},
            {"type": "inn", "vendor": "Sleeping Dragon Inn"},
            {"type": "market_stall", "vendor": "Darcy's Stall"},
            {"type": "chicken_statue", "cost": 10, "currency": "shiny_beads"},
            {"type": "mimic", "location": "Tide Caverns"},
            {"type": "mill", "location": "The Mill"},
            {"type": "fishing", "location": "Treasure Box"},
            {"type": "wishing_well", "cost": 500, "currency": "tesserae"},
            {"type": "festival", "vendor": "Harvest Festival Stall"},
            {"type": "date", "location": "Deep Woods Picnic"},
            {"type": "quest", "location": "Request Board"},
            {"type": "museum", "location": "Museum Milestone"},
            {"type": "unknown_future_type", "location": "Secret Location"},
        ]

        plan_results = {
            "bag_plan": [],
            "npc_progress": {},
            "remaining_items_map": {},
            "overall_stats": {
                "today_loved_completed": 0,
                "today_liked_completed": 0,
                "covered_npcs_count": 0,
                "target_npcs_count": 0,
            },
            "focus_suggestions": [
                {"item_id": "omni_item", "item_name": "Omni Item", "deficit": 1, "rank": 1}
            ],
            "focus_trees": [
                {
                    "item_id": "omni_item",
                    "item_name": "Omni Item",
                    "alt_sources": twelve_sources,
                    "children": [],
                }
            ],
        }

        out = self._render(self.save, plan_results)

        expected_emojis = [
            ("shop", "🛒"),
            ("inn", "🍽️"),
            ("market_stall", "🛒"),
            ("chicken_statue", "🐔"),
            ("mimic", "⛏️"),
            ("mill", "⚙️"),
            ("fishing", "🎣"),
            ("wishing_well", "💫"),
            ("festival", "🎪"),
            ("date", "💕"),
            ("quest", "📋"),
            ("museum", "🏛️"),
            ("fallback", "📍"),
        ]

        for stype, emoji in expected_emojis:
            self.assertIn(
                emoji,
                out,
                f"Emoji '{emoji}' for source type '{stype}' missing in terminal tree rendering",
            )

    def test_terminal_tree_rendering_deep_nesting_and_multiple_branches(self):
        """Verifies tree formatting for deep multi-level branches with proper box-drawing indentation."""
        plan_results = {
            "bag_plan": [],
            "npc_progress": {},
            "remaining_items_map": {},
            "overall_stats": {
                "today_loved_completed": 0,
                "today_liked_completed": 0,
                "covered_npcs_count": 0,
                "target_npcs_count": 0,
            },
            "focus_suggestions": [
                {"item_id": "raw_root", "item_name": "Raw Root", "deficit": 10, "rank": 1}
            ],
            "focus_trees": [
                {
                    "item_id": "raw_root",
                    "item_name": "Raw Root",
                    "alt_sources": [],
                    "children": [
                        {
                            "item_id": "branch_1",
                            "item_name": "Branch One",
                            "alt_sources": [],
                            "children": [
                                {
                                    "item_id": "sub_1a",
                                    "item_name": "Subchild 1A",
                                    "gift_npcs": ["March"],
                                    "children": [],
                                },
                                {
                                    "item_id": "sub_1b",
                                    "item_name": "Subchild 1B",
                                    "children": [
                                        {
                                            "item_id": "leaf_1b1",
                                            "item_name": "Deep Leaf",
                                            "gift_npcs": ["Celine", "Hayden"],
                                            "children": [],
                                        }
                                    ],
                                },
                            ],
                        },
                        {
                            "item_id": "branch_2",
                            "item_name": "Branch Two",
                            "gift_npcs": ["Adeline"],
                            "children": [],
                        },
                    ],
                }
            ],
        }

        out = self._render(self.save, plan_results)
        self.assertIn("Raw Root", out)
        self.assertIn("Branch One", out)
        self.assertIn("Branch Two", out)
        self.assertIn("Subchild 1A", out)
        self.assertIn("Subchild 1B", out)
        self.assertIn("Deep Leaf", out)
        self.assertIn("🎁 Subchild 1A → March", out)
        self.assertIn("🎁 Deep Leaf → Celine, Hayden", out)
        self.assertIn("🎁 Branch Two → Adeline", out)

    def test_terminal_tree_rendering_defensive_data_handling(self):
        """Verifies tree rendering does not crash on malformed node structures or unexpected types."""
        malformed_plan = {
            "bag_plan": [],
            "npc_progress": {},
            "remaining_items_map": {},
            "overall_stats": {
                "today_loved_completed": 0,
                "today_liked_completed": 0,
                "covered_npcs_count": 0,
                "target_npcs_count": 0,
            },
            "focus_suggestions": [
                {"item_id": "weird_item", "item_name": "Weird Item", "deficit": 1, "rank": 1}
            ],
            "focus_trees": [
                {
                    "item_id": "weird_item",
                    "item_name": None,
                    "alt_sources": [
                        None,  # Non-dict
                        "not a dict",
                        {"type": "shop", "vendor": "Free Store", "cost": 0, "currency": "tesserae"},
                        {"type": "shop", "vendor": "No Cost Shop", "cost": None},
                        {"type": "mimic", "note": "Floor 5"},
                    ],
                    "gift_npcs": None,
                    "children": [
                        None,  # Non-dict child
                        {
                            "item_id": "child_missing_fields",
                            # Missing item_name, alt_sources, gift_npcs, children
                        },
                    ],
                }
            ],
        }

        # Must execute without raising any exceptions
        out = self._render(self.save, malformed_plan)
        self.assertIn("Weird Item", out)
        self.assertIn("Free Store: 0t", out)
        self.assertIn("No Cost Shop", out)
        self.assertIn("Child Missing Fields", out)


class TestPresentationSurfacesExcelAdversarial(unittest.TestCase):
    """Empirical adversarial verification of Excel multi-sheet export (Requirement R5)."""

    def setUp(self):
        self.recipes = load_recipes()
        self.sources = load_recipe_sources()
        self.npcs, _ = load_npc_preferences_from_json(Path("data/item_data.json"))
        self.meta = load_item_metadata(Path("assets/fiddle"), Path("data/item_data.json"))
        raw = create_synthetic_save_entries(bag_items={"cow_milk": 3, "sugar": 2})
        self.save = SaveData(Path("test_excel_adv.sav"), raw)

    def _export_and_load(self, plan_results, npc_defs=None) -> openpyxl.Workbook:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "test_report_adv.xlsx"
            defs = self.npcs if npc_defs is None else npc_defs
            export_plan_to_excel(self.save, plan_results, defs, self.meta, out_file)
            self.assertTrue(out_file.exists())
            wb = openpyxl.load_workbook(str(out_file))
            return wb

    def test_excel_sheet_6_position_and_headers(self):
        """Verifies Sheet 6 exists, is named 'Focus Trees' at index 5, and has exact required headers."""
        plan = plan_daily_gift_bag(
            save=self.save,
            npc_gift_definitions=self.npcs,
            item_metadata=self.meta,
            recipe_sources=self.sources,
        )

        wb = self._export_and_load(plan)

        self.assertGreaterEqual(len(wb.sheetnames), 6)
        self.assertEqual(wb.sheetnames[5], "Focus Trees")

        ws6 = wb["Focus Trees"]
        headers = [cell.value for cell in ws6[1]]
        expected_headers = ["Blocker Item", "Depth", "Product", "Alt Sources", "Gift For (NPCs)"]
        self.assertEqual(headers, expected_headers)

    def test_excel_all_sheets_1_to_5_remain_intact(self):
        """Verifies that sheets 1 through 5 remain intact and undamaged by the addition of Sheet 6."""
        plan = plan_daily_gift_bag(
            save=self.save,
            npc_gift_definitions=self.npcs,
            item_metadata=self.meta,
            recipe_sources=self.sources,
        )

        wb = self._export_and_load(plan)

        # Expected sheet sequence
        expected_sheets = [
            "Daily Bag Plan",
            "NPC Gift Progress",
            "All Remaining Items",
            "Gift Completion Matrix",
            "Focus Recipes",
            "Focus Trees",
        ]
        self.assertEqual(wb.sheetnames[:6], expected_sheets)

        # Sheet 1: Daily Bag Plan
        ws1 = wb["Daily Bag Plan"]
        headers1 = [cell.value for cell in ws1[1]]
        self.assertIn("Slot #", headers1)
        self.assertIn("Item Name", headers1)
        self.assertIn("Today Loved Targets", headers1)

        # Sheet 2: NPC Gift Progress
        ws2 = wb["NPC Gift Progress"]
        headers2 = [cell.value for cell in ws2[1]]
        self.assertIn("NPC Name", headers2)
        self.assertIn("Heart Points", headers2)
        self.assertIn("% Total Done", headers2)

        # Sheet 3: All Remaining Items
        ws3 = wb["All Remaining Items"]
        headers3 = [cell.value for cell in ws3[1]]
        self.assertIn("Rank", headers3)
        self.assertIn("Item Name", headers3)
        self.assertIn("Item ID", headers3)

        # Sheet 4: Gift Completion Matrix
        ws4 = wb["Gift Completion Matrix"]
        headers4 = [cell.value for cell in ws4[1]]
        self.assertIn("Item Name", headers4)
        self.assertIn("Item ID", headers4)
        self.assertIn("Status Today", headers4)

        # Sheet 5: Focus Recipes
        ws5 = wb["Focus Recipes"]
        headers5 = [cell.value for cell in ws5[1]]
        self.assertEqual(headers5, ["Rank", "Recipe Name", "Impact", "Unlock Source"])

    def test_excel_focus_trees_hierarchical_indentation(self):
        """Verifies hierarchical indentation format ('→ ' * depth) for depths 0, 1, 2, 3."""
        plan_results = {
            "bag_plan": [],
            "npc_progress": {nid: {"name": n["name"], "is_vendor": False} for nid, n in self.npcs.items()},
            "remaining_items_map": {},
            "overall_stats": {},
            "focus_suggestions": [],
            "focus_trees": [
                {
                    "item_id": "milk",
                    "item_name": "Milk",
                    "alt_sources": [{"type": "shop", "vendor": "General Store", "cost": 200, "currency": "tesserae"}],
                    "gift_npcs": [],
                    "children": [
                        {
                            "item_id": "cheese",
                            "item_name": "Cheese",
                            "alt_sources": [{"type": "chicken_statue", "cost": 10, "currency": "shiny_beads"}],
                            "gift_npcs": [],
                            "children": [
                                {
                                    "item_id": "cheesecake",
                                    "item_name": "Cheesecake",
                                    "alt_sources": [{"type": "chicken_statue", "cost": 100, "currency": "shiny_beads"}],
                                    "gift_npcs": ["Darcy", "Eiland"],
                                    "children": [
                                        {
                                            "item_id": "golden_cheesecake",
                                            "item_name": "Golden Cheesecake",
                                            "alt_sources": [],
                                            "gift_npcs": ["Darcy"],
                                            "children": [],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        wb = self._export_and_load(plan_results, npc_defs={})
        ws6 = wb["Focus Trees"]
        rows = list(ws6.iter_rows(min_row=2, values_only=True))

        self.assertEqual(len(rows), 4)

        # Depth 0: Root Blocker (no prefix)
        self.assertEqual(rows[0][0], "Milk")
        self.assertEqual(rows[0][1], 0)
        self.assertEqual(rows[0][2], "Milk")
        self.assertIn("General Store", rows[0][3])
        self.assertEqual(rows[0][4], "—")

        # Depth 1: Intermediate Cheese ("→ ")
        self.assertEqual(rows[1][0], "Milk")
        self.assertEqual(rows[1][1], 1)
        self.assertEqual(rows[1][2], "→ Cheese")
        self.assertIn("Chicken Statue", rows[1][3])
        self.assertEqual(rows[1][4], "—")

        # Depth 2: Cheesecake ("→ → ")
        self.assertEqual(rows[2][0], "Milk")
        self.assertEqual(rows[2][1], 2)
        self.assertEqual(rows[2][2], "→ → Cheesecake")
        self.assertIn("Chicken Statue", rows[2][3])
        self.assertEqual(rows[2][4], "Darcy, Eiland")

        # Depth 3: Golden Cheesecake ("→ → → ")
        self.assertEqual(rows[3][0], "Milk")
        self.assertEqual(rows[3][1], 3)
        self.assertEqual(rows[3][2], "→ → → Golden Cheesecake")
        self.assertEqual(rows[3][3], "—")
        self.assertEqual(rows[3][4], "Darcy")

    def test_excel_focus_trees_empty_and_null_safety(self):
        """Verifies export_plan_to_excel creates Sheet 6 with headers even when focus_trees is empty or None."""
        for empty_val in ([], None):
            plan_results = {
                "bag_plan": [],
                "npc_progress": {},
                "remaining_items_map": {},
                "overall_stats": {},
                "focus_suggestions": [],
                "focus_trees": empty_val,
            }

            wb = self._export_and_load(plan_results, npc_defs={})
            self.assertIn("Focus Trees", wb.sheetnames)
            ws6 = wb["Focus Trees"]
            headers = [cell.value for cell in ws6[1]]
            self.assertEqual(headers, ["Blocker Item", "Depth", "Product", "Alt Sources", "Gift For (NPCs)"])
            rows = list(ws6.iter_rows(min_row=2, values_only=True))
            self.assertEqual(len(rows), 0)


class TestPresentationSurfacesWebCompanionAdversarial(unittest.TestCase):
    """Empirical adversarial verification of Web Companion server and location sprite routes (Requirement R4)."""

    def setUp(self):
        self.client = TestClient(app)
        self.expected_locations = [
            "balor_wagon",
            "chicken_statue",
            "date",
            "festival_stall",
            "fishing",
            "general_store",
            "inn",
            "mill",
            "mimic",
            "museum",
            "quest_board",
            "ranch_shop",
            "saturday_market",
            "tackle_shop",
            "wishing_well",
        ]

    def test_web_companion_all_15_location_sprites_http_200_png(self):
        """Empirically tests that all 15 location PNG names return HTTP 200, image/png, and valid PNG magic bytes."""
        self.assertEqual(len(self.expected_locations), 15)
        for loc in self.expected_locations:
            resp = self.client.get(f"/assets/sprites/locations/{loc}")
            self.assertEqual(
                resp.status_code,
                200,
                f"Location sprite '{loc}' failed with HTTP {resp.status_code}",
            )
            self.assertEqual(
                resp.headers.get("content-type"),
                "image/png",
                f"Location sprite '{loc}' returned wrong content-type: {resp.headers.get('content-type')}",
            )
            self.assertGreater(
                len(resp.content),
                100,
                f"Location sprite '{loc}' payload is unexpectedly small: {len(resp.content)} bytes",
            )
            # Verify PNG 8-byte magic signature (\x89PNG\r\n\x1a\n)
            self.assertEqual(
                resp.content[:8],
                b"\x89PNG\r\n\x1a\n",
                f"Location sprite '{loc}' is not a valid PNG binary file",
            )

    def test_web_companion_sprite_casing_and_extension(self):
        """Verifies that location sprite route handles uppercase, trailing .png extension, and whitespace."""
        # Trailing extension
        resp_ext = self.client.get("/assets/sprites/locations/general_store.png")
        self.assertEqual(resp_ext.status_code, 200)
        self.assertEqual(resp_ext.headers.get("content-type"), "image/png")

        # Uppercase
        resp_upper = self.client.get("/assets/sprites/locations/GENERAL_STORE")
        self.assertEqual(resp_upper.status_code, 200)

        # Mixed case
        resp_mixed = self.client.get("/assets/sprites/locations/Chicken_Statue")
        self.assertEqual(resp_mixed.status_code, 200)

    def test_web_companion_nonexistent_sprites_http_404(self):
        """Verifies nonexistent location sprite names return HTTP 404 and prevent path traversal."""
        nonexistent_cases = [
            "nonexistent_location_icon_xyz",
            "fake_shop_12345",
            "unknown_source",
            "../../main.py",
            "%2e%2e%2fmain.py",
        ]
        for name in nonexistent_cases:
            resp = self.client.get(f"/assets/sprites/locations/{name}")
            self.assertIn(
                resp.status_code,
                (404, 400),
                f"Expected 404/400 for '{name}', got HTTP {resp.status_code}",
            )


class TestPresentationSurfacesJsonExportAdversarial(unittest.TestCase):
    """Empirical adversarial verification of Web Companion JSON export schema (Requirement R4)."""

    def setUp(self):
        raw = create_synthetic_save_entries(bag_items={"bread": 1})
        self.save = SaveData(Path("test_json.sav"), raw)
        self.config = CompanionConfig()

    def test_json_export_schema_and_focus_trees_presence(self):
        """Verifies plan_to_json() includes focus_trees in top-level JSON schema with valid serialization."""
        plan_results = {
            "bag_plan": [],
            "npc_progress": {},
            "remaining_items_map": {},
            "overall_stats": {},
            "focus_suggestions": [],
            "focus_trees": [
                {
                    "item_id": "cow_milk",
                    "item_name": "Milk",
                    "alt_sources": [{"type": "shop", "vendor": "Balor's Wagon"}],
                    "gift_npcs": [],
                    "sprite_url": "/assets/sprites/items/cow_milk",
                    "children": [
                        {
                            "item_id": "cheese",
                            "item_name": "Cheese",
                            "alt_sources": [{"type": "chicken_statue", "cost": 10, "currency": "shiny_beads"}],
                            "gift_npcs": ["Darcy"],
                            "sprite_url": "/assets/sprites/items/cheese",
                            "children": [],
                        }
                    ],
                }
            ],
        }

        json_dict = plan_to_json(self.save, plan_results, {}, Path("test_json.sav"), self.config)

        # Required top-level keys
        for key in ("generated_at", "save_info", "in_game_date", "config", "stats", "bag_plan", "focus_suggestions", "focus_trees", "npc_progress", "error"):
            self.assertIn(key, json_dict, f"Missing top-level key '{key}' in plan_to_json()")

        self.assertIsInstance(json_dict["focus_trees"], list)
        self.assertEqual(len(json_dict["focus_trees"]), 1)

        # Full json.dumps() round-trip without TypeError
        serialized = json.dumps(json_dict)
        deserialized = json.loads(serialized)
        tree = deserialized["focus_trees"][0]
        self.assertEqual(tree["item_id"], "cow_milk")
        self.assertEqual(tree["item_name"], "Milk")
        self.assertEqual(tree["sprite_url"], "/assets/sprites/items/cow_milk")
        self.assertEqual(len(tree["children"]), 1)
        self.assertEqual(tree["children"][0]["gift_npcs"], ["Darcy"])

    def test_json_export_nested_sets_and_paths_serialization(self):
        """Adversarially verifies plan_to_json() safely serializes Python sets, frozensets, and Paths without crash."""
        plan_results = {
            "bag_plan": [],
            "npc_progress": {},
            "remaining_items_map": {},
            "overall_stats": {
                "locked_npcs": {"npc_z", "npc_a"},  # set in stats
            },
            "focus_suggestions": [],
            "focus_trees": [
                {
                    "item_id": "test_item",
                    "item_name": "Test Item",
                    "alt_sources": [],
                    "gift_npcs": {"Darcy", "Adeline"},  # set in gift_npcs
                    "custom_frozenset": frozenset(["frozen_val"]),
                    "custom_path": Path("/local/path/to/icon.png"),
                    "children": [],
                }
            ],
        }

        json_dict = plan_to_json(self.save, plan_results, {}, Path("test_json.sav"), self.config)

        # Serialization to string
        serialized = json.dumps(json_dict)
        deserialized = json.loads(serialized)

        stats = deserialized["stats"]
        self.assertEqual(stats["locked_npcs"], ["npc_a", "npc_z"])  # sorted list

        tree = deserialized["focus_trees"][0]
        self.assertEqual(tree["gift_npcs"], ["Adeline", "Darcy"])  # sorted list
        self.assertEqual(tree["custom_frozenset"], ["frozen_val"])
        self.assertEqual(tree["custom_path"], "/local/path/to/icon.png")

    def test_json_export_empty_and_null_focus_trees(self):
        """Verifies plan_to_json() safely serializes empty list, omitted, and None focus_trees."""
        # 1. Empty list
        plan_results_empty = {
            "bag_plan": [],
            "npc_progress": {},
            "remaining_items_map": {},
            "overall_stats": {},
            "focus_suggestions": [],
            "focus_trees": [],
        }
        json_dict = plan_to_json(self.save, plan_results_empty, {}, Path("test_json.sav"), self.config)
        self.assertIn("focus_trees", json_dict)
        self.assertEqual(json_dict["focus_trees"], [])
        serialized = json.dumps(json_dict)
        self.assertIn('"focus_trees": []', serialized)

        # 2. Omitted focus_trees key
        plan_results_omitted = {
            "bag_plan": [],
            "npc_progress": {},
            "remaining_items_map": {},
            "overall_stats": {},
            "focus_suggestions": [],
        }
        json_dict_omitted = plan_to_json(self.save, plan_results_omitted, {}, Path("test_json.sav"), self.config)
        self.assertIn("focus_trees", json_dict_omitted)
        self.assertEqual(json_dict_omitted["focus_trees"], [])

        # 3. Explicitly None
        plan_results_none = {
            "bag_plan": [],
            "npc_progress": {},
            "remaining_items_map": {},
            "overall_stats": {},
            "focus_suggestions": [],
            "focus_trees": None,
        }
        json_dict_none = plan_to_json(self.save, plan_results_none, {}, Path("test_json.sav"), self.config)
        self.assertIn("focus_trees", json_dict_none)
        self.assertIsNone(json_dict_none["focus_trees"])
        self.assertEqual(json.loads(json.dumps(json_dict_none))["focus_trees"], None)


if __name__ == "__main__":
    unittest.main()

