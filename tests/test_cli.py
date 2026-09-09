"""
tests/test_cli.py

Unit and integration tests for fom_planner CLI:
- build_planner_parser options and flags (--strategy, --max-relationship-points, --no-exclude-max-relationship)
- run_planner dispatch for journal and max-relationship strategies
"""

import unittest
from unittest.mock import MagicMock, patch

from fom_planner.cli import build_planner_parser, run_planner
from fom_planner.constants import DEFAULT_MAX_RELATIONSHIP_POINTS


class TestCliParserAndOptions(unittest.TestCase):
    """Tests for CLI arguments in build_planner_parser()."""

    def setUp(self):
        self.parser = build_planner_parser()

    def test_cli_parser_defaults_to_journal(self):
        args = self.parser.parse_args([])
        self.assertEqual(args.strategy, "journal")

    def test_cli_parser_accepts_journal(self):
        args = self.parser.parse_args(["--strategy", "journal"])
        self.assertEqual(args.strategy, "journal")

    def test_cli_parser_accepts_max_relationship(self):
        args = self.parser.parse_args(["--strategy", "max-relationship"])
        self.assertEqual(args.strategy, "max-relationship")

    def test_cli_parser_rejects_invalid_strategy(self):
        with self.assertRaises(SystemExit) as cm:
            self.parser.parse_args(["--strategy", "invalid_strategy"])
        self.assertEqual(cm.exception.code, 2)

    def test_cli_parser_help_contains_strategy(self):
        help_out = self.parser.format_help()
        self.assertIn("--strategy", help_out)
        self.assertIn("max-relationship", help_out)
        self.assertIn("journal", help_out)

    def test_cli_parser_max_relationship_flags(self):
        """Verify --max-relationship-points and --no-exclude-max-relationship flags."""
        args_default = self.parser.parse_args([])
        self.assertIsNone(args_default.max_relationship_points)
        self.assertFalse(args_default.no_exclude_max_relationship)

        args_custom = self.parser.parse_args([
            "--max-relationship-points", "1500",
            "--no-exclude-max-relationship",
        ])
        self.assertEqual(args_custom.max_relationship_points, 1500.0)
        self.assertTrue(args_custom.no_exclude_max_relationship)


class TestCliExecutionDispatch(unittest.TestCase):
    """Tests for run_planner() dispatch based on --strategy."""

    @patch("fom_planner.cli.plan_daily_gift_bag")
    @patch("fom_planner.cli.load_npc_preferences_from_json")
    def test_run_planner_dispatches_journal_by_default(self, mock_load_json, mock_plan_daily):
        mock_load_json.return_value = ({"adeline": {"name": "Adeline", "loved": [], "liked": []}}, set())
        mock_plan_daily.return_value = {
            "bag_plan": [],
            "npc_progress": {},
            "covered_npcs": set(),
            "target_npcs": set(),
            "overall_stats": {
                "game_given_loved": 0, "game_total_loved": 10,
                "game_given_liked": 0, "game_total_liked": 20,
                "game_given_total": 0, "game_total_preferences": 30,
                "remaining_unique_items": 15,
                "mode": "weekday", "max_slots": 20, "covered_npcs_count": 0,
                "target_npcs_count": 1, "vendors_covered_today": 0,
                "today_loved_completed": 0, "today_liked_completed": 0,
                "locked_npcs": [], "ungiftable_npcs": [],
            },
        }

        parser = build_planner_parser()
        args = parser.parse_args(["--format", "terminal"])
        with patch("fom_planner.exporters.terminal.print_terminal_plan"):
            run_planner(args)

        mock_plan_daily.assert_called_once()

    @patch("fom_planner.optimizer.plan_max_relationship")
    @patch("fom_planner.cli.load_npc_preferences_from_json")
    def test_run_planner_dispatches_max_relationship(self, mock_load_json, mock_plan_max_rel):
        mock_load_json.return_value = ({"adeline": {"name": "Adeline", "loved": [], "liked": []}}, set())
        mock_plan_max_rel.return_value = {
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
                "target_npcs_count": 1, "vendors_covered_today": 0,
                "today_loved_completed": 0, "today_liked_completed": 0,
                "locked_npcs": [], "ungiftable_npcs": [],
            },
        }

        parser = build_planner_parser()
        args = parser.parse_args(["--strategy", "max-relationship", "--format", "terminal"])
        with patch("fom_planner.exporters.terminal.print_terminal_plan"):
            run_planner(args)

        mock_plan_max_rel.assert_called_once()


if __name__ == "__main__":
    unittest.main()
